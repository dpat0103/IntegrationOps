from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.core.models import HealthCheck, Integration
from app.services.alerts import emit_incident_alert
from app.services.checker import execute_check
from app.services.incidents import apply_incident_policy


DEMO_INTEGRATION_NAME = "Demo Upstream"


def _allow_private_for_integration(
    integration: Integration,
    *,
    allow_private_endpoints: bool,
    demo_mode: bool,
    demo_integration_url: str,
) -> bool:
    """Allow a private URL only for the server-controlled demo integration.

    This avoids turning DEMO_MODE into a blanket SSRF bypass. Arbitrary user
    integrations still follow ALLOW_PRIVATE_ENDPOINTS.
    """
    if allow_private_endpoints:
        return True
    return (
        demo_mode
        and integration.name == DEMO_INTEGRATION_NAME
        and integration.endpoint.rstrip("/") == demo_integration_url.rstrip("/")
    )


async def run_integration_check(
    session: Session,
    integration: Integration,
    *,
    failure_threshold: int,
    recovery_threshold: int,
    slack_webhook_url: str | None = None,
    execution_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    allow_private_endpoints: bool = False,
    integration_secret_key: str | None = None,
    demo_mode: bool = False,
    demo_integration_url: str = "",
) -> HealthCheck:
    check = await execute_check(
        session,
        integration,
        execution_id=execution_id,
        transport=transport,
        allow_private_endpoints=_allow_private_for_integration(
            integration,
            allow_private_endpoints=allow_private_endpoints,
            demo_mode=demo_mode,
            demo_integration_url=demo_integration_url,
        ),
        integration_secret_key=integration_secret_key,
    )
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
