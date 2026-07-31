from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Kalibr Reports Bot"
    app_env: Literal["development", "test", "production"] = "development"
    app_timezone: str = "Asia/Tashkent"
    app_base_url: str = "http://localhost:8000"
    secret_key: str = Field(default="development-only-secret-change-me")
    bootstrap_key: str = Field(default="development-bootstrap")
    database_url: str = "postgresql+asyncpg://kalibr:kalibr@localhost:5432/kalibr_reports"
    redis_url: str = "redis://localhost:6379/0"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"

    amocrm_base_url: str = "https://kalibrbooks.amocrm.ru"
    amocrm_access_token: str = ""
    amocrm_pipeline_id: int | None = None
    amocrm_new_stage_id: int | None = None
    amocrm_critical_stage_id: int | None = None
    amocrm_resolved_stage_id: int | None = None

    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str = "kalibr-reports"
    s3_region: str = "auto"

    admin_cookie_secure: bool = False
    auto_create_schema: bool = False

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://") and "+asyncpg" not in value:
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("amocrm_base_url")
    @classmethod
    def normalize_amocrm_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache

def get_settings() -> Settings:
    return Settings()


settings = get_settings()
