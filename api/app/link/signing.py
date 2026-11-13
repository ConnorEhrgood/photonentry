"""Signed requests from controllers (CRITICAL: 100% branch coverage).

Every request `entry-link` makes is signed with the controller's own Ed25519 key, made on the controller and never sent anywhere; the cloud
keeps only the public key. Nothing shared can leak from the cloud and let someone else act as a controller (the PhotonEdge rule, suite §3).

    X-PhotonEntry-Link: k=<key id>,t=<unix seconds>,n=<nonce, 32 hex>,v1=<base64url signature, no padding>

The signature covers `photonentry-link-v1 \\n t \\n n \\n METHOD \\n path \\n hex sha256(body)`. A request is refused when its time is more than
five minutes from ours, or its nonce was already used by that key inside the window (a replayed request). The key id is the first 16 hex
digits of sha256(public key). `contract/link/vectors.json` holds a fixed example that the C signer is tested against.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from typing import Callable, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

HEADER = "X-PhotonEntry-Link"
PREFIX = "photonentry-link-v1"
WINDOW_S = 300


class LinkAuthError(Exception):
    """The request is not from a key we accept. The message is for our logs; the controller is told only 401."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def key_id(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


def message(t: int, nonce: str, method: str, path: str, body: bytes) -> bytes:
    return "\n".join([PREFIX, str(t), nonce, method.upper(), path, hashlib.sha256(body).hexdigest()]).encode()


def sign(private_key: Ed25519PrivateKey, t: int, method: str, path: str, body: bytes, nonce: Optional[str] = None) -> str:
    """The header value for a request. Used by tests and by the reference client; the controller's is in C (acap/entry-link/app/sign.c)."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    nonce = nonce or secrets.token_hex(16)
    pub = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    sig = private_key.sign(message(t, nonce, method, path, body))
    return f"k={key_id(pub)},t={t},n={nonce},v1={b64u(sig)}"


def parse(header: str) -> Dict[str, str]:
    parts: Dict[str, str] = {}
    for item in header.split(","):
        name, sep, value = item.strip().partition("=")
        if not sep or not value or name in parts:
            raise LinkAuthError("malformed signature header")
        parts[name] = value
    if set(parts) != {"k", "t", "n", "v1"}:
        raise LinkAuthError("signature header needs exactly k, t, n and v1")
    if not parts["t"].isdigit() or len(parts["t"]) > 12:
        raise LinkAuthError("bad time")
    if len(parts["n"]) != 32 or any(ch not in "0123456789abcdef" for ch in parts["n"]):
        raise LinkAuthError("bad nonce")
    return parts


class NonceCache:
    """Nonces seen per key inside the window. In memory: a restart forgets them, which a five-minute window makes harmless only together with
    the time check (a request older than five minutes is refused anyway). Several API workers each keep their own; Step 2 moves it to Postgres."""

    def __init__(self) -> None:
        self._seen: Dict[Tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def use(self, kid: str, nonce: str, t: int, now: int) -> bool:
        """Record the nonce; False if it was already used."""
        with self._lock:
            for k in [k for k, when in self._seen.items() if when < now - WINDOW_S]:
                del self._seen[k]
            if (kid, nonce) in self._seen:
                return False
            self._seen[(kid, nonce)] = t
            return True


def verify(header: Optional[str], method: str, path: str, body: bytes, public_key_for: Callable[[str], Optional[bytes]],
           nonces: NonceCache, now: int) -> str:
    """The key id of a correctly signed, fresh, unreplayed request, or LinkAuthError."""
    if not header:
        raise LinkAuthError("no signature")
    parts = parse(header)
    t = int(parts["t"])
    if abs(now - t) > WINDOW_S:
        raise LinkAuthError("time outside the window (check the controller's clock)")
    public = public_key_for(parts["k"])
    if public is None or key_id(public) != parts["k"]:
        raise LinkAuthError("unknown key")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(unb64u(parts["v1"]), message(t, parts["n"], method, path, body))
    except (InvalidSignature, ValueError) as e:
        raise LinkAuthError("bad signature") from e
    if not nonces.use(parts["k"], parts["n"], t, now):
        raise LinkAuthError("nonce already used")
    return parts["k"]
