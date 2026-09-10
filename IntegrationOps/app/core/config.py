from functools import lru_cache
import os

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
    demo_mode: bool = True
    demo_integration_url: str | None = None
    allow_private_endpoints: bool = False
    public_write_enabled: bool = True
    integration_secret_key: str | None = None
    auto_create_schema: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def private_endpoints_allowed(self) -> bool:
        # Never make demo mode a blanket SSRF bypass. Arbitrary private targets
        # must require the explicit ALLOW_PRIVATE_ENDPOINTS override.
        return self.allow_private_endpoints

    @property
    def resolved_demo_integration_url(self) -> str:
        """Return the server-controlled endpoint used by the built-in demo.

        Docker Compose sets DEMO_INTEGRATION_URL to the API service hostname so
        Celery workers can reach it. Render exposes RENDER_EXTERNAL_URL to the
        web service, which gives the demo a public, worker-reachable endpoint.
        Local non-Docker development falls back to loopback.
        """
        if self.demo_integration_url:
            return self.demo_integration_url.rstrip("/")
        render_external_url = os.getenv("RENDER_EXTERNAL_URL")
        if render_external_url:
            return f"{render_external_url.rstrip('/')}/simulator/status"
        return "http://127.0.0.1:8000/simulator/status"


@lru_cache
def get_settings() -> Settings:
    return Settings()
