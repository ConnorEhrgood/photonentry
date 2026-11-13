from __future__ import annotations

import json
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.link import signing

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PUB = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
KID = signing.key_id(PUB)
NOW = 1_800_000_000


def _verify(header, body=b"{}", now=NOW, path="/link/v1/sync", nonces=None, pub=PUB):
    return signing.verify(header, "POST", path, body, lambda k: pub if k == KID else None, nonces or signing.NonceCache(), now)


def test_a_signed_request_verifies():
    h = signing.sign(KEY, NOW, "POST", "/link/v1/sync", b"{}")
    assert _verify(h) == KID


def test_the_vector_the_c_signer_is_tested_against():
    with open(os.path.join(ROOT, "contract", "link", "vectors.json")) as f:
        v = json.load(f)
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(v["private_key_hex"]))
    body = v["body"].encode()
    assert signing.sign(key, v["t"], v["method"], v["path"], body, nonce=v["nonce"]) == v["header"]
    assert signing.b64u(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)) == v["public_key"]


@pytest.mark.parametrize("header", [None, "", "k=1", "k=a,t=1,n=2,v1=3,x=4", "k=a,k=b,t=1,n=2", "k=,t=1,n=2,v1=3", "k=a t=1 n=2 v1=3"])
def test_malformed_headers_are_refused(header):
    with pytest.raises(signing.LinkAuthError):
        _verify(header)


def test_bad_time_and_nonce_shapes_are_refused():
    good = signing.parse(signing.sign(KEY, NOW, "POST", "/p", b""))
    for change in ({"t": "abc"}, {"t": "1" * 13}, {"n": "abc"}, {"n": "Z" * 32}):
        bad = {**good, **change}
        with pytest.raises(signing.LinkAuthError):
            signing.parse(",".join(f"{k}={v}" for k, v in bad.items()))


def test_old_and_future_requests_are_refused():
    for t in (NOW - 301, NOW + 301):
        with pytest.raises(signing.LinkAuthError, match="window"):
            _verify(signing.sign(KEY, t, "POST", "/link/v1/sync", b"{}"))
    assert _verify(signing.sign(KEY, NOW - 300, "POST", "/link/v1/sync", b"{}")) == KID


def test_unknown_key_is_refused():
    with pytest.raises(signing.LinkAuthError, match="unknown"):
        _verify(signing.sign(KEY, NOW, "POST", "/link/v1/sync", b"{}"), pub=None)


def test_a_key_that_does_not_match_its_id_is_refused():
    other = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    with pytest.raises(signing.LinkAuthError, match="unknown"):
        signing.verify(signing.sign(KEY, NOW, "POST", "/p", b""), "POST", "/p", b"", lambda k: other, signing.NonceCache(), NOW)


@pytest.mark.parametrize("what", ["body", "path", "method", "signature", "garbage"])
def test_tampering_is_refused(what):
    h = signing.sign(KEY, NOW, "POST", "/link/v1/sync", b"{}")
    body, path, method = b"{}", "/link/v1/sync", "POST"
    if what == "body":
        body = b'{"x":1}'
    elif what == "path":
        path = "/link/v1/hello"
    elif what == "method":
        method = "GET"
    elif what == "signature":
        h = h[:-4] + ("AAAA" if not h.endswith("AAAA") else "BBBB")
    else:
        h = h.split("v1=")[0] + "v1=!!!"
    with pytest.raises(signing.LinkAuthError, match="signature"):
        signing.verify(h, method, path, body, lambda k: PUB, signing.NonceCache(), NOW)


def test_a_replayed_nonce_is_refused_and_old_nonces_are_forgotten():
    nonces = signing.NonceCache()
    h = signing.sign(KEY, NOW, "POST", "/link/v1/sync", b"{}")
    assert _verify(h, nonces=nonces) == KID
    with pytest.raises(signing.LinkAuthError, match="nonce"):
        _verify(h, nonces=nonces)
    # After the window the nonce is forgotten; the request is refused by its time instead.
    assert nonces.use("other", "a" * 32, NOW + 1000, NOW + 1000)
    assert (KID, signing.parse(h)["n"]) not in nonces._seen
