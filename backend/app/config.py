from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://goat:goat@localhost:5432/goat"
    environment: str = "development"
    cookie_secure: bool = False
    cookie_name: str = "goat_session"
    session_hours: int = Field(default=24, ge=1, le=168)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    storage_dir: Path = Path("storage")
    max_pdf_bytes: int = 50 * 1024 * 1024
    news_poll_minutes: int = Field(default=20, ge=1)
    news_collection_enabled: bool = True
    news_max_new_publications: int = Field(default=100, ge=1, le=1000)
    worker_poll_seconds: float = Field(default=2, gt=0)
    job_timeout_seconds: int = Field(default=900, ge=60)
    ai_module: str = ""
    ai_generation_version: str = "1"
    feed_candidate_limit: int = Field(default=30, ge=1, le=200)
    feed_prepare_top_k: int = Field(default=3, ge=1, le=10)
    product_event_retention_days: int = Field(default=90, ge=1, le=365)
    product_test_emails: list[str] = []
    admin_password: SecretStr | None = None
    demo_password: SecretStr | None = None
    ranking_weights: dict[str, float] = {"industry": 4, "product": 3, "geo": 2, "relation": 2, "focus": 2}

    @model_validator(mode="after")
    def production_cookies(self):
        if self.environment == "production" and (not self.cookie_secure):
            raise ValueError("COOKIE_SECURE must be true in production")
        if self.feed_prepare_top_k > self.feed_candidate_limit:
            raise ValueError("FEED_PREPARE_TOP_K cannot exceed FEED_CANDIDATE_LIMIT")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
