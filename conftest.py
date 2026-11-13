"""Test-wide settings, loaded before any test imports app code (app.config reads the environment once).

The database suite (api/tests/db) runs only when a database is provided: scripts/with-local-pg.py on the runner, scripts/remote-test.sh on
LXC 800. Everything else needs nothing."""
import os

os.environ.setdefault("OIDC_ISSUER", "https://idp.test")
os.environ.setdefault("OIDC_AUDIENCE", "photonentry")
os.environ.setdefault("DIRECTORY_URL", "https://directory.test")
os.environ.setdefault("DIRECTORY_NOTICE_SECRET", "notice-secret-for-tests-0123456789-abcdef")
os.environ.setdefault("SECRETS_KEY", "dGVzdC1zZWNyZXRzLWtleS1mb3ItcGhvdG9uZW50cnk=")   # Fernet: 32 bytes, url-safe base64
os.environ.setdefault("FINGERPRINT_KEY", "fingerprint-key-for-tests-0123456789-abcdef")

collect_ignore_glob = [] if os.environ.get("PHOTONENTRY_DB_TESTS") else ["api/tests/db/*"]
