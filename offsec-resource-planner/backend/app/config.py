"""Environment-based configuration.

All secrets (JWT signing key, SMTP password, database password) are read from
environment variables only. They are never stored in the database and never
returned by any API endpoint.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ORP_", extra="ignore")

    environment: str = "development"  # development | production | test
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/orp"

    secret_key: str = Field(default="dev-insecure-change-me", min_length=16)
    session_hours: int = 8
    cookie_secure: bool = False  # MUST be true in production (HTTPS)
    session_cookie_name: str = "orp_session"
    csrf_cookie_name: str = "orp_csrf"

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

    worker_interval_seconds: int = 30
    app_base_url: str = "http://localhost:8080"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        if s.secret_key.startswith("dev-") or len(s.secret_key) < 32:
            raise RuntimeError("ORP_SECRET_KEY must be a strong secret (>=32 chars) in production")
        if not s.cookie_secure:
            raise RuntimeError("ORP_COOKIE_SECURE must be true in production (HTTPS required)")
    return s
