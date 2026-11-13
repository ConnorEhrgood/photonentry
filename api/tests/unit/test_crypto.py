import pytest

from app import crypto
from app.config import settings


def test_seal_unseal_and_fingerprints():
    sealed = crypto.seal("10213")
    assert "10213" not in sealed and crypto.unseal(sealed) == "10213"
    assert crypto.fingerprint("card", "x") == crypto.fingerprint("card", "x") != crypto.fingerprint("pin", "x")


def test_missing_keys_are_refused(monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", "")
    with pytest.raises(RuntimeError, match="SECRETS_KEY"):
        crypto.seal("x")
    monkeypatch.setattr(settings, "fingerprint_key", "")
    with pytest.raises(RuntimeError, match="FINGERPRINT_KEY"):
        crypto.fingerprint("pin", "1234")
