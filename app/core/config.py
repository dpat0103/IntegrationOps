from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IntegrationOps"
    environment: str = "development"
    database_url: str = "sqlite:///./integrationops.db"
    auto_migrate: bool = True
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = Field(default=5, ge=1, le=60)
    failure_threshold: int = Field(default=3, ge=1, le=20)
    recovery_threshold: int = Field(default=2, ge=1, le=20)
    max_concurrent_checks: int = Field(default=8, ge=1, le=64)
    lease_seconds: int = Field(default=60, ge=35, le=600)
    stale_grace_seconds: int = Field(default=15, ge=1, le=600)
    max_run_attempts: int = Field(default=3, ge=1, le=10)
    retention_days: int = Field(default=30, ge=1)
    demo_ttl_hours: int = Field(default=24, ge=1, le=168)
    demo_mode: bool = True
    demo_session_secret: str | None = None
    cookie_secure: bool = False
    operator_token: str | None = None
    integration_secret_key: str | None = None
    slack_webhook_url: str | None = None
    alert_max_attempts: int = Field(default=5, ge=1, le=10)
    task_mode: str = Field(default="local", pattern="^(local|celery)$")
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def production_configuration(self):
        if self.environment == "production":
            if not self.operator_token or len(self.operator_token) < 32:
                raise ValueError(
                    "Production requires an OPERATOR_TOKEN of at least 32 characters"
                )
            if self.demo_mode and (
                not self.demo_session_secret or len(self.demo_session_secret) < 32
            ):
                raise ValueError(
                    "Production demo requires a stable DEMO_SESSION_SECRET of at least 32 characters"
                )
            if not self.cookie_secure:
                raise ValueError("Production requires secure cookies and HTTPS")
        return self

    @property
    def cors_origin_list(self):
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings():
    return Settings()
