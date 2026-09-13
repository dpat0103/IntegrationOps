from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import HealthCheck, Incident, Integration, utcnow
from app.services.metrics import ACTIVE_INCIDENTS


def get_open_incident(session: Session, integration_id: int) -> Incident | None:
    return session.scalar(
        select(Incident)
        .where(Incident.integration_id == integration_id, Incident.status == "OPEN")
        .order_by(Incident.started_at.desc())
    )


def _recent_checks(session: Session, integration_id: int, limit: int) -> list[HealthCheck]:
    return list(
        session.scalars(
            select(HealthCheck)
            .where(HealthCheck.integration_id == integration_id)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(limit)
        )
    )


def apply_incident_policy(
    session: Session,
    integration: Integration,
    *,
    failure_threshold: int = 3,
    recovery_threshold: int = 2,
) -> tuple[Incident | None, str | None]:
    open_incident = get_open_incident(session, integration.id)

    failures = _recent_checks(session, integration.id, failure_threshold)
    if len(failures) == failure_threshold and all(c.outcome == "FAILED" for c in failures):
        if open_incident is None:
            cause = failures[0].failure_type
            incident = Incident(
                integration_id=integration.id,
                status="OPEN",
                severity="HIGH",
                cause=cause,
                failure_count=failure_threshold,
            )
            session.add(incident)
            session.flush()
            ACTIVE_INCIDENTS.inc()
            return incident, "OPENED"
        open_incident.failure_count += 1
        return open_incident, None

    successes = _recent_checks(session, integration.id, recovery_threshold)
    if open_incident and len(successes) == recovery_threshold and all(c.outcome in ("HEALTHY", "DEGRADED") for c in successes):
        open_incident.status = "RESOLVED"
        open_incident.resolved_at = utcnow()
        ACTIVE_INCIDENTS.dec()
        session.flush()
        return open_incident, "RESOLVED"

    return open_incident, None
