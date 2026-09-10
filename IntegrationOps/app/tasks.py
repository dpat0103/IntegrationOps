from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select

from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import build_engine_and_session, init_db
from app.core.models import Integration
from app.services.orchestrator import run_integration_check

settings = get_settings()
engine, SessionFactory = build_engine_and_session(settings.database_url)
if settings.auto_create_schema:
    init_db(engine)


@celery_app.task(name="app.tasks.check_integration", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def check_integration(integration_id: int):
    with SessionFactory() as session:
        integration = session.get(Integration, integration_id)
        if not integration or not integration.active:
            return {"skipped": True}
        check = asyncio.run(run_integration_check(
            session,
            integration,
            failure_threshold=settings.failure_threshold,
            recovery_threshold=settings.recovery_threshold,
            slack_webhook_url=settings.slack_webhook_url,
            allow_private_endpoints=settings.private_endpoints_allowed,
            integration_secret_key=settings.integration_secret_key,
            demo_mode=settings.demo_mode,
            demo_integration_url=settings.resolved_demo_integration_url,
        ))
        return {"check_id": check.id, "outcome": check.outcome}


@celery_app.task(name="app.tasks.dispatch_due_checks")
def dispatch_due_checks():
    now = datetime.now(timezone.utc)
    queued = 0
    with SessionFactory() as session:
        integrations = list(session.scalars(select(Integration).where(Integration.active.is_(True))))
        for integration in integrations:
            due = integration.last_checked_at is None
            if integration.last_checked_at is not None:
                last = integration.last_checked_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                due = (now - last).total_seconds() >= integration.check_interval_seconds
            if due:
                check_integration.delay(integration.id)
                queued += 1
    return {"queued": queued}
