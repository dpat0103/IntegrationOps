from sqlalchemy import select
from app.core.models import HealthCheck, Incident, utcnow


def get_open_incident(session, integration_id):
    return session.scalar(
        select(Incident).where(
            Incident.integration_id == integration_id, Incident.status == "OPEN"
        )
    )


def apply_incident_policy(
    session, integration, *, failure_threshold=3, recovery_threshold=2
):
    # The orchestrator locks the integration row; the partial unique index is a second invariant.
    current = get_open_incident(session, integration.id)
    checks = list(
        session.scalars(
            select(HealthCheck)
            .where(HealthCheck.integration_id == integration.id)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(max(failure_threshold, recovery_threshold))
        )
    )
    if len(checks) >= failure_threshold and all(
        check.outcome == "FAILED" for check in checks[:failure_threshold]
    ):
        if current is None:
            current = Incident(
                integration_id=integration.id,
                status="OPEN",
                severity="HIGH",
                cause=checks[0].failure_type,
                failure_count=failure_threshold,
            )
            session.add(current)
            session.flush()
            return current, "OPENED"
        current.failure_count += 1
    # Resolution requires normal performance, not merely an HTTP response.
    if (
        current
        and len(checks) >= recovery_threshold
        and all(check.outcome == "HEALTHY" for check in checks[:recovery_threshold])
    ):
        current.status = "RESOLVED"
        current.resolved_at = utcnow()
        session.flush()
        return current, "RESOLVED"
    return current, None
