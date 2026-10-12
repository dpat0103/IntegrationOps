"""Transactional notification outbox. External delivery is at-least-once, with bounded retry."""

import json
import uuid
from datetime import timedelta
from urllib.parse import urlsplit
import httpx
from sqlalchemy import or_, select, update
from app.core.models import AlertEvent, utcnow
from app.core.security import PublicTransport


def enqueue_incident_alert(session, integration, incident, event_type, settings):
    if not settings.slack_webhook_url or integration.demo_owner:
        return None
    text = (
        f"IntegrationOps: {integration.display_name} — "
        f"{'incident opened' if event_type == 'OPENED' else 'incident resolved'} "
        f"(#{incident.id}, {incident.cause or 'available'})"
    )
    event = AlertEvent(
        incident_id=incident.id,
        event_type=event_type,
        status="PENDING",
        payload_json=json.dumps({"text": text}),
        next_attempt_at=utcnow(),
    )
    session.add(event)
    return event


async def deliver_alerts(factory, settings, transport=None):
    if not settings.slack_webhook_url:
        return 0
    parsed = urlsplit(settings.slack_webhook_url)
    if transport is None and (
        parsed.scheme != "https"
        or parsed.hostname != "hooks.slack.com"
        or parsed.username
    ):
        raise ValueError("Slack webhook must use HTTPS at hooks.slack.com")
    with factory() as session:
        ids = list(
            session.scalars(
                select(AlertEvent.id)
                .where(
                    or_(
                        AlertEvent.status.in_(["PENDING", "RETRY"]),
                        (AlertEvent.status == "SENDING")
                        & (AlertEvent.lease_until <= utcnow()),
                    ),
                    AlertEvent.next_attempt_at <= utcnow(),
                )
                .order_by(AlertEvent.id)
                .limit(50)
            )
        )
    delivered = 0
    for event_id in ids:
        token = str(uuid.uuid4())
        with factory() as session:
            claim = session.execute(
                update(AlertEvent)
                .where(
                    AlertEvent.id == event_id,
                    or_(
                        AlertEvent.status.in_(["PENDING", "RETRY"]),
                        (AlertEvent.status == "SENDING")
                        & (AlertEvent.lease_until <= utcnow()),
                    ),
                    AlertEvent.next_attempt_at <= utcnow(),
                )
                .values(
                    status="SENDING",
                    lease_token=token,
                    lease_until=utcnow() + timedelta(seconds=30),
                    attempts=AlertEvent.attempts + 1,
                )
            )
            session.commit()
            if claim.rowcount != 1:
                continue
            event = session.get(AlertEvent, event_id)
            payload, attempts = json.loads(event.payload_json), event.attempts
        try:
            async with httpx.AsyncClient(
                timeout=5, transport=transport or PublicTransport(), trust_env=False
            ) as client:
                response = await client.post(
                    settings.slack_webhook_url,
                    json=payload,
                    headers={"X-IntegrationOps-Event": str(event_id)},
                )
                response.raise_for_status()
            status, message = "SENT", None
            delivered += 1
        except (httpx.HTTPError, ValueError):
            status = "DEAD" if attempts >= settings.alert_max_attempts else "RETRY"
            message = "Notification delivery failed"
        with factory() as session:
            changed = session.execute(
                update(AlertEvent)
                .where(AlertEvent.id == event_id, AlertEvent.lease_token == token)
                .values(
                    status=status,
                    error_message=message,
                    lease_token=None,
                    lease_until=None,
                    sent_at=utcnow(),
                    next_attempt_at=utcnow() + timedelta(seconds=min(300, 2**attempts)),
                )
            )
            if changed.rowcount == 1:
                from app.services.metrics import increment

                increment(session, "alerts:" + status)
            session.commit()
    return delivered
