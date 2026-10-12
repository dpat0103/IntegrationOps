import uuid
from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import lock_writes
from app.core.models import CheckRun, HealthCheck, Integration, utcnow
from app.services.alerts import enqueue_incident_alert
from app.services.checker import persist_result, probe_integration
from app.services.demo import demo_transport
from app.services.incidents import apply_incident_policy
from app.services.jobs import (
    RunBusy,
    claim_run,
    heartbeat,
    release_for_retry,
    reserve_run,
)
from app.services.metrics import record_probe


async def run_integration_check(
    session,
    integration,
    *,
    failure_threshold=None,
    recovery_threshold=None,
    slack_webhook_url=None,
    execution_id=None,
    transport=None,
    settings=None,
):
    settings = settings or get_settings()
    integration_id = integration.id
    execution_id = execution_id or str(uuid.uuid4())
    existing = session.scalar(
        select(HealthCheck).where(HealthCheck.execution_id == execution_id)
    )
    if existing:
        if existing.integration_id != integration_id:
            raise ValueError("Execution ID belongs to another service")
        return existing
    run, _ = reserve_run(session, integration_id, settings, execution_id)
    if run is None:
        raise RunBusy("Service is paused or unavailable")
    execution_id = run.execution_id
    token = claim_run(session, execution_id, settings)
    try:
        session.expire_all()
        integration = session.get(Integration, integration_id)
        if transport is None and integration.demo_owner:
            transport = demo_transport(session, integration)
        session.commit()
        result = await probe_integration(integration, transport, settings)
        lock_writes(session)
        integration = session.scalar(
            select(Integration)
            .where(Integration.id == integration_id)
            .with_for_update()
        )
        run = session.get(CheckRun, execution_id, populate_existing=True)
        if not integration or not run or run.lease_token != token:
            session.rollback()
            raise RunBusy("Run lease was replaced")
        existing = session.scalar(
            select(HealthCheck).where(HealthCheck.execution_id == execution_id)
        )
        if existing:
            session.rollback()
            return existing
        check = persist_result(session, integration, execution_id, result)
        record_probe(session, result)
        incident, event = apply_incident_policy(
            session,
            integration,
            failure_threshold=failure_threshold or settings.failure_threshold,
            recovery_threshold=recovery_threshold or settings.recovery_threshold,
        )
        if incident and event:
            enqueue_incident_alert(session, integration, incident, event, settings)
        run.status = "DONE"
        run.finished_at = utcnow()
        run.lease_token = None
        run.lease_until = None
        run.error_code = None
        heartbeat(session, "worker")
        session.commit()
        session.refresh(check)
        return check
    except BaseException:
        release_for_retry(session, execution_id, token)
        raise
