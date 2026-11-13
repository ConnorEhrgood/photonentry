from __future__ import annotations

from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Three database logins (the sister products' split): the OWNER runs migrations and nothing else; the API's routes connect as `entry_app`, to
    # which row-level security applies; the link service (controllers are found by their key, not by a person), the worker and the directory
    # sync connect as `entry_system`. Empty `system_database_url` / `migrate_database_url`: the same as `database_url` (development).
    database_url: str = "postgresql+psycopg://entry_app:entry_app@localhost:5432/photonentry"
    system_database_url: str = ""
    migrate_database_url: str = ""
    # The passwords migration 0001 gives the two login roles. Empty: the role is created without a login.
    app_db_password: str = ""
    system_db_password: str = ""

    # OIDC (PhotonID, Zitadel): tokens carry identity only.
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: str = "RS256"
    cors_origins: str = ""                  # development: http://localhost:5193

    # The PhotonID directory: our read-only copy, kept by notify-then-pull.
    directory_url: str = ""
    directory_product: str = "entry"
    directory_client_id: str = ""
    directory_client_secret: str = ""
    directory_notice_secret: str = ""       # comma separated during rotation
    directory_pull_every_s: int = 300
    directory_resolve_timeout_s: float = 3.0
    directory_timeout_s: float = 10.0

    # Fernet keys for card numbers and PINs at rest (comma separated: the first encrypts, all decrypt), and the key of their fingerprints.
    secrets_key: str = ""
    fingerprint_key: str = ""

    # The link service (controllers): how long a sync with nothing to say is held open.
    link_wait_s: float = 25.0

    environment: str = "development"

    @property
    def notice_secrets(self) -> List[str]:
        return [s.strip() for s in self.directory_notice_secret.split(",") if s.strip()]

    @property
    def cors_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def production_safe(self) -> Optional[str]:
        """A reason this configuration is unsafe in production, or None."""
        if self.environment != "production":
            return None
        if not self.oidc_issuer or not self.oidc_audience:
            return "OIDC_ISSUER and OIDC_AUDIENCE must be set"
        if not self.directory_url.startswith("https://"):
            return "DIRECTORY_URL must be an https:// URL"
        if not self.directory_client_id or not self.directory_client_secret:
            return "DIRECTORY_CLIENT_ID and DIRECTORY_CLIENT_SECRET must be set"
        if not self.notice_secrets or any(len(s) < 32 for s in self.notice_secrets):
            return "DIRECTORY_NOTICE_SECRET must be set to a long random value"
        if not self.system_database_url:
            return "SYSTEM_DATABASE_URL must be set (the link service and the sync connect as entry_system)"
        if not self.secrets_key:
            return "SECRETS_KEY must be set (card numbers and PINs are kept encrypted with it)"
        if len(self.fingerprint_key) < 32:
            return "FINGERPRINT_KEY must be set to a long random value"
        if not self.cors_list or any(not o.startswith("https://") for o in self.cors_list):
            return "CORS_ORIGINS must list the web app's https:// origin"
        return None


settings = Settings()
