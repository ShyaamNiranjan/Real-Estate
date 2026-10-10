from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    environment: str = "development"

    migrations_database_url: str
    database_url: str
    public_database_url: str
    hq_database_url: str

    test_migrations_database_url: str | None = None
    test_database_url: str | None = None
    test_public_database_url: str | None = None
    test_hq_database_url: str | None = None

    secret_key: str = Field(min_length=32)

    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    allowed_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = True
    session_days: int = 30

    terms_version: str = "2026-10-draft"
    privacy_version: str = "2026-10-draft"

    email_from: str = "Scrollwalk <no-reply@mail.scrollwalk.com>"

    google_client_id: str | None = None
    google_client_secret: str | None = None

    storage_backend: Literal["local", "r2"] = "local"
    local_media_dir: Path = Path(__file__).resolve().parent.parent / ".data" / "media"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    media_public_base_url: str | None = None

    consent_version: str = "2026-10-draft"
    turnstile_secret: str | None = None

    # Any OpenAI-compatible chat API (Gemini in development, GPT-6 Luna in production). "stub" writes
    # template text locally so the flow works before a key exists. Keys live only in backend/.env.
    ai_provider: Literal["stub", "openai_compatible"] = "stub"
    ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    ai_api_key: str | None = None
    ai_model: str = "gemini-2.5-flash"
    ai_timeout_seconds: float = 60
    ai_input_usd_per_million: float = 0
    ai_output_usd_per_million: float = 0

    # Merchant of record. "stub" simulates checkout and webhooks until a provider is chosen; it is
    # refused when ENVIRONMENT=production. Secrets live only in backend/.env.
    billing_provider: Literal["stub"] = "stub"
    billing_api_key: str | None = None
    billing_webhook_secret: str | None = None

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.api_url}/api/v1/auth/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
