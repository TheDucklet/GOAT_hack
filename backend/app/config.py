from functools import lru_cache

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
    ai_module: str = ""
    ai_generation_version: str = "1"
    admin_password: SecretStr | None = None
    demo_password: SecretStr | None = None
    ranking_weights: dict[str, float] = {"industry": 4, "product": 3, "geo": 2, "relation": 2, "focus": 2}

    @model_validator(mode="after")
    def production_cookies(self):
        if self.environment == "production" and (not self.cookie_secure):
            raise ValueError("COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
