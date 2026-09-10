from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(1000))
    method: Mapped[str] = mapped_column(String(10), default="GET")
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=3000)
    latency_threshold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability_target_pct: Mapped[float | None] = mapped_column(Float, nullable=True, default=99.0)
    p95_latency_target_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    expected_json_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_json_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    checks: Mapped[list[HealthCheck]] = relationship(back_populates="integration", cascade="all, delete-orphan")
    incidents: Mapped[list[Incident]] = relationship(back_populates="integration", cascade="all, delete-orphan")


class HealthCheck(Base):
    __tablename__ = "health_checks"
    __table_args__ = (UniqueConstraint("execution_id", name="uq_health_checks_execution_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), index=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)  # HEALTHY / DEGRADED / FAILED
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    response_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    integration: Mapped[Integration] = relationship(back_populates="checks")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    severity: Mapped[str] = mapped_column(String(20), default="HIGH")
    cause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    integration: Mapped[Integration] = relationship(back_populates="incidents")
    alerts: Mapped[list[AlertEvent]] = relationship(back_populates="incident", cascade="all, delete-orphan")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30), default="slack")
    event_type: Mapped[str] = mapped_column(String(30))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="SENT")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="alerts")
