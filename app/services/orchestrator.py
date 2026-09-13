from __future__ import annotations

import httpx
from sqlalchemy.orm import Session
from app.core.models import Integration, HealthCheck
from app.services.alerts import emit_incident_alert
from app.services.checker import execute_check
from app.services.incidents import apply_incident_policy


async def run_integration_check(
    session: Session,
    integration: Integration,
    *,
    failure_threshold: int,
    recovery_threshold: int,
    slack_webhook_url: str | None = None,
    execution_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HealthCheck:
    check = await execute_check(session, integration, execution_id=execution_id, transport=transport)
    incident, event_type = apply_incident_policy(
        session,
        integration,
        failure_threshold=failure_threshold,
        recovery_threshold=recovery_threshold,
    )
    if incident and event_type:
        await emit_incident_alert(
            session,
            integration=integration,
            incident=incident,
            event_type=event_type,
            slack_webhook_url=slack_webhook_url,
        )
    session.commit()
    session.refresh(check)
    return check
