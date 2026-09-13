from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    endpoint: HttpUrl
    method: str = Field(default="GET", pattern="^(GET|POST|HEAD)$")
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_ms: int = Field(default=3000, ge=100, le=30000)
    latency_threshold_ms: int | None = Field(default=1000, ge=1)
    check_interval_seconds: int = Field(default=60, ge=5, le=86400)
    expected_json_key: str | None = None
    expected_json_value: str | None = None
    headers: dict[str, str] | None = None
    active: bool = True


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: HttpUrl | None = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    timeout_ms: int | None = Field(default=None, ge=100, le=30000)
    latency_threshold_ms: int | None = Field(default=None, ge=1)
    check_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    expected_json_key: str | None = None
    expected_json_value: str | None = None
    active: bool | None = None


class IntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    endpoint: str
    method: str
    expected_status: int
    timeout_ms: int
    latency_threshold_ms: int | None
    check_interval_seconds: int
    expected_json_key: str | None
    expected_json_value: str | None
    active: bool
    created_at: datetime
    last_checked_at: datetime | None


class CheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    execution_id: str
    integration_id: int
    checked_at: datetime
    outcome: str
    http_status: int | None
    latency_ms: float | None
    failure_type: str | None
    error_message: str | None


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    integration_id: int
    started_at: datetime
    resolved_at: datetime | None
    status: str
    severity: str
    cause: str | None
    failure_count: int


class Overview(BaseModel):
    total_integrations: int
    healthy: int
    degraded: int
    down: int
    active_incidents: int
    checks_24h: int
    availability_24h: float | None
    avg_latency_ms_24h: float | None
    p95_latency_ms_24h: float | None


class SimulatorState(BaseModel):
    mode: str = Field(pattern="^(healthy|slow|unauthorized|rate_limit|server_error|malformed)$")
    delay_seconds: float = Field(default=4.0, ge=0.0, le=30.0)
