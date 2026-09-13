from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IntegrationOps"
    environment: str = "development"
    database_url: str = "sqlite:///./integrationops.db"
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 5
    failure_threshold: int = 3
    recovery_threshold: int = 2
    slack_webhook_url: str | None = None
    task_mode: str = "local"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
