"""Configuration, loaded from `.env` only. Fails fast on missing required values."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0
    openai_timeout: int = 30

    # Conversation memory
    max_chat_history: int = 10

    # Auth
    jwt_secret: str = "change-me-in-env"
    jwt_expiry_minutes: int = 30
    jwt_algorithm: str = "HS256"

    # Runtime
    log_level: str = "INFO"
    app_env: str = "development"
    database_path: str = "enrollment.db"

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
