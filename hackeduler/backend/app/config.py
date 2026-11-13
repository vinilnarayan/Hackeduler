"""Environment-based configuration.

All secrets (JWT signing key, SMTP password, database password) are read from
environment variables only. They are never stored in the database and never
returned by any API endpoint.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HACKEDULER_", extra="ignore")

    environment: str = "development"  # development | production | test
    # Database. Either give one full URL (HACKEDULER_DATABASE_URL) or the separate parts below (RDS / any managed
    # PostgreSQL). With the parts, the URL is built for you and the password may contain any character.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/hackeduler"
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "hackeduler"
    db_user: str = "hackeduler"
    db_password: str = ""                  # secret - env only
    db_sslmode: str = "verify-full"        # disable | require | verify-ca | verify-full  (RDS: verify-full)
    db_sslrootcert: str = "/certs/rds-global-bundle.pem"   # AWS RDS CA bundle (deploy.sh downloads it into ./certs)
    db_connect_timeout: int = 10
    db_pool_size: int = 5                  # per backend worker process; keep (web workers x (size+overflow)) well below
    db_max_overflow: int = 5               # the RDS max_connections of your instance class
    db_pool_recycle_seconds: int = 1800

    secret_key: str = Field(default="dev-insecure-change-me", min_length=16)
    session_hours: int = 8
    cookie_secure: bool = False  # MUST be true in production (HTTPS)
    session_cookie_name: str = "hackeduler_session"
    csrf_cookie_name: str = "hackeduler_csrf"

    cors_origins: list[str] = ["http://localhost:5173"]

    # Rate limiting (per client IP, in-memory; use a shared store for multi-instance)
    rate_limit_per_minute: int = 600
    login_rate_limit_per_minute: int = 10

    # Email
    email_backend: str = "smtp"  # smtp | console | memory
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""  # secret - env only
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    smtp_timeout: int = 15

    # Which service delivers mail when email_backend=smtp ("real delivery"): smtp | ses. The admin Settings page can
    # override both; an optional fallback is tried when the primary fails. SES uses the standard AWS credential
    # chain (EC2 instance role - recommended - or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in the environment).
    email_primary: str = "smtp"
    email_fallback: str = ""
    aws_region: str = ""                   # falls back to AWS_REGION / AWS_DEFAULT_REGION
    ses_configuration_set: str = ""

    # Key used to encrypt secrets stored in the database (SSO client secrets).
    # If unset it is derived from secret_key; set it explicitly so secret_key can be rotated independently.
    encryption_key: str = ""
    # Break-glass: forces local password login ON regardless of the admin "local login" policy
    # (use if an SSO misconfiguration locks everyone out).
    force_local_login: bool = False
    sso_http_timeout: int = 10

    worker_interval_seconds: int = 30
    app_base_url: str = "http://localhost:8080"

    @property
    def effective_database_url(self) -> str:
        """The SQLAlchemy URL to use: built from the DB_* parts when HACKEDULER_DB_HOST is set, else database_url."""
        if not self.db_host:
            return self.database_url
        from sqlalchemy.engine import URL

        query = {"connect_timeout": str(self.db_connect_timeout), "sslmode": self.db_sslmode}
        if self.db_sslmode in ("verify-ca", "verify-full") and self.db_sslrootcert:
            query["sslrootcert"] = self.db_sslrootcert
        return URL.create("postgresql+psycopg", username=self.db_user, password=self.db_password or None,
                          host=self.db_host, port=self.db_port, database=self.db_name,
                          query=query).render_as_string(hide_password=False)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def _apply_legacy_env() -> None:
    """Accept settings from deployments made before the rename (ORP_* -> HACKEDULER_*).
    A HACKEDULER_* value always wins; legacy names are only used when the new one is absent."""
    import logging
    import os

    used = []
    for key, value in list(os.environ.items()):
        if key.startswith("ORP_"):
            new = "HACKEDULER_" + key[4:]
            if new not in os.environ:
                os.environ[new] = value
                used.append(key)
    if used:
        logging.getLogger("hackeduler").warning(
            "Using legacy environment variable(s) %s - rename them to HACKEDULER_* in your .env", ", ".join(sorted(used)))


@lru_cache
def get_settings() -> Settings:
    _apply_legacy_env()
    s = Settings()
    if s.is_production:
        if s.secret_key.startswith("dev-") or len(s.secret_key) < 32:
            raise RuntimeError("HACKEDULER_SECRET_KEY must be a strong secret (>=32 chars) in production")
        if not s.cookie_secure:
            raise RuntimeError("HACKEDULER_COOKIE_SECURE must be true in production (HTTPS required)")
    return s
