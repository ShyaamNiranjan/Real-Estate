from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
