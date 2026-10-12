from datetime import timedelta
from sqlalchemy import delete, func, select
from app.core.models import (
    CheckRun,
    DemoState,
    HealthCheck,
    Incident,
    Integration,
    RateLimitBucket,
    utcnow,
)


def maintain(session, settings):
    session.execute(
        delete(RateLimitBucket).where(RateLimitBucket.expires_at < utcnow())
    )
    expired = set(
        session.scalars(select(DemoState.owner).where(DemoState.expires_at < utcnow()))
    )
    for integration in session.scalars(
        select(Integration).where(Integration.demo_owner.in_(expired))
    ):
        session.delete(integration)
    if expired:
        session.execute(delete(DemoState).where(DemoState.owner.in_(expired)))
    cutoff = utcnow() - timedelta(days=settings.retention_days)
    latest = select(func.max(HealthCheck.id)).group_by(HealthCheck.integration_id)
    session.execute(
        delete(HealthCheck).where(
            HealthCheck.checked_at < cutoff, HealthCheck.id.not_in(latest)
        )
    )
    session.execute(
        delete(CheckRun).where(
            CheckRun.status.in_(["DONE", "FAILED", "CANCELLED"]),
            CheckRun.finished_at < cutoff,
        )
    )
    for incident in session.scalars(
        select(Incident).where(
            Incident.status == "RESOLVED", Incident.resolved_at < cutoff
        )
    ):
        session.delete(incident)
    session.commit()
