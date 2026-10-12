from datetime import datetime, timezone
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_serializer,
    model_validator,
)


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*")
    def timestamps(self, value):
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
            ).isoformat()
        return value


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: HttpUrl | None = None
    method: str | None = Field(default=None, pattern="^(GET|POST|HEAD)$")
    expected_status: int | None = Field(default=None, ge=100, le=599)
    timeout_ms: int | None = Field(default=None, ge=100, le=30000)
    latency_threshold_ms: int | None = Field(default=None, ge=1)
    check_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    expected_json_key: str | None = None
    expected_json_value: str | None = None
    headers: dict[str, str] | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def required_fields(self):
        for name in (
            "name",
            "endpoint",
            "method",
            "expected_status",
            "timeout_ms",
            "check_interval_seconds",
            "active",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class IntegrationRead(ReadModel):
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
    demo_key: str | None = None


class CheckRead(ReadModel):
    id: int
    execution_id: str
    integration_id: int
    checked_at: datetime
    outcome: str
    http_status: int | None
    latency_ms: float | None
    failure_type: str | None
    error_message: str | None


class IncidentRead(ReadModel):
    id: int
    integration_id: int
    started_at: datetime
    resolved_at: datetime | None
    status: str
    severity: str
    cause: str | None
    failure_count: int


class RunRead(ReadModel):
    execution_id: str
    integration_id: int
    status: str
    attempts: int
    scheduled_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None


class Overview(BaseModel):
    total_integrations: int
    healthy: int
    degraded: int
    down: int
    stale: int = 0
    unknown: int = 0
    active_incidents: int
    checks_24h: int
    availability_24h: float | None
    avg_latency_ms_24h: float | None
    p95_latency_ms_24h: float | None


class SimulatorState(BaseModel):
    mode: str = Field(
        pattern="^(healthy|slow|unauthorized|rate_limit|server_error|malformed|timeout)$"
    )
    delay_seconds: float = Field(default=0.8, ge=0.0, le=4.0)


class DemoScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str = Field(default="payment", pattern="^(payment|shipping|identity)$")
    mode: str = Field(
        pattern="^(healthy|slow|unauthorized|rate_limit|server_error|malformed|timeout)$"
    )
