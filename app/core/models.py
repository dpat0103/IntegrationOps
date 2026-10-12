from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return (
        value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
    )


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(1000))
    method: Mapped[str] = mapped_column(String(10), default="GET")
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=3000)
    latency_threshold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    expected_json_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_json_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    demo_owner: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    demo_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checks: Mapped[list[HealthCheck]] = relationship(
        back_populates="integration", cascade="all, delete-orphan"
    )
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="integration", cascade="all, delete-orphan"
    )
    runs: Mapped[list[CheckRun]] = relationship(cascade="all, delete-orphan")

    @property
    def display_name(self):
        return self.name.split(" :: ")[0] if self.demo_owner else self.name


class HealthCheck(Base):
    __tablename__ = "health_checks"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_health_checks_execution_id"),
        Index("ix_checks_integration_time", "integration_id", "checked_at", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), index=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), index=True
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_type: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    integration: Mapped[Integration] = relationship(back_populates="checks")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "uq_one_open_incident",
            "integration_id",
            unique=True,
            sqlite_where=text("status = 'OPEN'"),
            postgresql_where=text("status = 'OPEN'"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    severity: Mapped[str] = mapped_column(String(20), default="HIGH")
    cause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    integration: Mapped[Integration] = relationship(back_populates="incidents")
    alerts: Mapped[list[AlertEvent]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class CheckRun(Base):
    __tablename__ = "check_runs"
    __table_args__ = (
        Index(
            "uq_one_inflight_run",
            "integration_id",
            unique=True,
            sqlite_where=text("status IN ('QUEUED', 'RUNNING')"),
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )
    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MetricTotal(Base):
    __tablename__ = "metric_totals"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[float] = mapped_column(Float, default=0)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DemoState(Base):
    __tablename__ = "demo_states"
    owner: Mapped[str] = mapped_column(String(40), primary_key=True)
    service: Mapped[str] = mapped_column(String(20), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="healthy")
    delay_seconds: Mapped[float] = mapped_column(Float, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("incident_id", "event_type", name="uq_alert_transition"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30), default="slack")
    event_type: Mapped[str] = mapped_column(String(30))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(40), nullable=True)
    incident: Mapped[Incident] = relationship(back_populates="alerts")
