from __future__ import annotations

import httpx
from sqlalchemy.orm import Session
from app.core.models import AlertEvent, Incident, Integration
from app.services.metrics import ALERTS_TOTAL


async def emit_incident_alert(
    session: Session,
    *,
    integration: Integration,
    incident: Incident,
    event_type: str,
    slack_webhook_url: str | None,
) -> AlertEvent | None:
    if not slack_webhook_url:
        return None

    if event_type == "OPENED":
        text = (
            f"🚨 IntegrationOps incident\n"
            f"Service: {integration.name}\n"
            f"Cause: {incident.cause or 'UNKNOWN'}\n"
            f"Incident: #{incident.id}"
        )
    else:
        text = (
            f"✅ IntegrationOps incident resolved\n"
            f"Service: {integration.name}\n"
            f"Incident: #{incident.id}"
        )

    event = AlertEvent(incident_id=incident.id, channel="slack", event_type=event_type, status="PENDING")
    session.add(event)
    session.flush()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(slack_webhook_url, json={"text": text})
            response.raise_for_status()
        event.status = "SENT"
        ALERTS_TOTAL.labels(event_type=event_type, status="SENT").inc()
    except Exception as exc:  # alert failures must not fail the health-check transaction
        event.status = "FAILED"
        event.error_message = str(exc)
        ALERTS_TOTAL.labels(event_type=event_type, status="FAILED").inc()
    return event
