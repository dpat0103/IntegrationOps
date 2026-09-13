from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.models import HealthCheck, Incident, Integration
from app.core.schemas import (
    CheckRead,
    IncidentRead,
    IntegrationCreate,
    IntegrationRead,
    IntegrationUpdate,
    Overview,
    SimulatorState,
)
from app.services.orchestrator import run_integration_check

router = APIRouter(prefix="/api")


def _pct(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = max(0, min(len(values) - 1, math.ceil(percentile * len(values)) - 1))
    return round(values[idx], 2)


@router.get("/health")
def api_health():
    return {"status": "ok", "service": "IntegrationOps"}


@router.post("/integrations", response_model=IntegrationRead, status_code=201)
def create_integration(payload: IntegrationCreate, session: Session = Depends(get_db)):
    if session.scalar(select(Integration).where(Integration.name == payload.name)):
        raise HTTPException(status_code=409, detail="Integration name already exists")
    integration = Integration(
        name=payload.name,
        endpoint=str(payload.endpoint),
        method=payload.method,
        expected_status=payload.expected_status,
        timeout_ms=payload.timeout_ms,
        latency_threshold_ms=payload.latency_threshold_ms,
        check_interval_seconds=payload.check_interval_seconds,
        expected_json_key=payload.expected_json_key,
        expected_json_value=payload.expected_json_value,
        headers_json=json.dumps(payload.headers) if payload.headers else None,
        active=payload.active,
    )
    session.add(integration)
    session.commit()
    session.refresh(integration)
    return integration


@router.get("/integrations", response_model=list[IntegrationRead])
def list_integrations(session: Session = Depends(get_db)):
    return list(session.scalars(select(Integration).order_by(Integration.id)))


@router.get("/integrations/{integration_id}", response_model=IntegrationRead)
def get_integration(integration_id: int, session: Session = Depends(get_db)):
    integration = session.get(Integration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.patch("/integrations/{integration_id}", response_model=IntegrationRead)
def update_integration(integration_id: int, payload: IntegrationUpdate, session: Session = Depends(get_db)):
    integration = session.get(Integration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "endpoint" and value is not None:
            value = str(value)
        setattr(integration, key, value)
    session.commit()
    session.refresh(integration)
    return integration


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(integration_id: int, session: Session = Depends(get_db)):
    integration = session.get(Integration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    session.delete(integration)
    session.commit()


@router.post("/integrations/{integration_id}/check", response_model=CheckRead)
async def manual_check(integration_id: int, request: Request, session: Session = Depends(get_db)):
    integration = session.get(Integration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return await run_integration_check(
        session,
        integration,
        failure_threshold=request.app.state.settings.failure_threshold,
        recovery_threshold=request.app.state.settings.recovery_threshold,
        slack_webhook_url=request.app.state.settings.slack_webhook_url,
    )


@router.get("/integrations/{integration_id}/checks", response_model=list[CheckRead])
def integration_checks(integration_id: int, limit: int = 100, session: Session = Depends(get_db)):
    if not session.get(Integration, integration_id):
        raise HTTPException(status_code=404, detail="Integration not found")
    return list(
        session.scalars(
            select(HealthCheck)
            .where(HealthCheck.integration_id == integration_id)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(min(max(limit, 1), 500))
        )
    )


@router.get("/incidents", response_model=list[IncidentRead])
def list_incidents(status: str | None = None, session: Session = Depends(get_db)):
    stmt = select(Incident).order_by(Incident.started_at.desc())
    if status:
        stmt = stmt.where(Incident.status == status.upper())
    return list(session.scalars(stmt.limit(200)))


@router.get("/overview", response_model=Overview)
def overview(session: Session = Depends(get_db)):
    integrations = list(session.scalars(select(Integration).where(Integration.active.is_(True))))
    statuses = {"HEALTHY": 0, "DEGRADED": 0, "FAILED": 0}
    for integration in integrations:
        latest = session.scalar(
            select(HealthCheck)
            .where(HealthCheck.integration_id == integration.id)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(1)
        )
        if latest:
            statuses[latest.outcome] = statuses.get(latest.outcome, 0) + 1

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = list(session.scalars(select(HealthCheck).where(HealthCheck.checked_at >= since)))
    available = [c for c in recent if c.outcome in ("HEALTHY", "DEGRADED")]
    latencies = [c.latency_ms for c in recent if c.latency_ms is not None]
    availability = round(len(available) / len(recent) * 100, 2) if recent else None
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
    active_incidents = session.scalar(select(func.count()).select_from(Incident).where(Incident.status == "OPEN")) or 0

    return Overview(
        total_integrations=len(integrations),
        healthy=statuses.get("HEALTHY", 0),
        degraded=statuses.get("DEGRADED", 0),
        down=statuses.get("FAILED", 0),
        active_incidents=active_incidents,
        checks_24h=len(recent),
        availability_24h=availability,
        avg_latency_ms_24h=avg_latency,
        p95_latency_ms_24h=_pct(latencies, 0.95),
    )


@router.get("/status")
def current_status(session: Session = Depends(get_db)):
    rows = []
    integrations = list(session.scalars(select(Integration).where(Integration.active.is_(True)).order_by(Integration.name)))
    for integration in integrations:
        latest = session.scalar(
            select(HealthCheck)
            .where(HealthCheck.integration_id == integration.id)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(1)
        )
        rows.append({
            "id": integration.id,
            "name": integration.name,
            "endpoint": integration.endpoint,
            "status": latest.outcome if latest else "UNKNOWN",
            "latency_ms": round(latest.latency_ms, 2) if latest and latest.latency_ms is not None else None,
            "failure_type": latest.failure_type if latest else None,
            "last_checked_at": latest.checked_at.isoformat() if latest else None,
        })
    return rows


@router.post("/simulator/state")
def set_simulator_state(payload: SimulatorState, request: Request):
    request.app.state.simulator_mode = payload.mode
    request.app.state.simulator_delay_seconds = payload.delay_seconds
    return {"mode": payload.mode, "delay_seconds": payload.delay_seconds}


@router.get("/simulator/state")
def get_simulator_state(request: Request):
    return {"mode": request.app.state.simulator_mode, "delay_seconds": request.app.state.simulator_delay_seconds}
