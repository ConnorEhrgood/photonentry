"""Secrets at rest (ARCHITECTURE §7.5): Fernet, keyed by SECRETS_KEY. A secret is encrypted before it reaches the database and decrypted only where
it is used (when settings are compiled for a controller). Values are never logged or returned by the API."""
from __future__ import annotations

import hashlib
import hmac
from typing import List

from cryptography.fernet import Fernet, MultiFernet

from app.config import settings


def _keys() -> List[str]:
    keys = [k.strip() for k in settings.secrets_key.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("SECRETS_KEY is not set")
    return keys


def _box() -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in _keys()])


def seal(value: str) -> str:
    return _box().encrypt(value.encode()).decode()


def unseal(token: str) -> str:
    return _box().decrypt(token.encode()).decode()


def fingerprint(kind: str, value: str) -> str:
    """A keyed hash of a card number or PIN, so the database can refuse a second holder of the same one without being able to read either
    (the value itself is sealed). Its key (FINGERPRINT_KEY) is separate from SECRETS_KEY so that rotating the sealing key changes no fingerprint."""
    key = settings.fingerprint_key.encode()
    if not key:
        raise RuntimeError("FINGERPRINT_KEY is not set")
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
