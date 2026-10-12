import asyncio
import logging
from sqlalchemy import select
from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import build_engine_and_session
from app.core.models import CheckRun, Integration
from app.services.alerts import deliver_alerts
from app.services.jobs import RunBusy, RunExhausted, heartbeat, reserve_run
from app.services.maintenance import maintain
from app.services.orchestrator import run_integration_check

settings = get_settings()
engine, SessionFactory = build_engine_and_session(settings.database_url)
logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.check_integration",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=6,
)
def check_integration(self, execution_id):
    try:
        with SessionFactory() as session:
            run = session.get(CheckRun, execution_id)
            if not run or run.status in ("FAILED", "CANCELLED"):
                return {"skipped": True}
            integration = session.get(Integration, run.integration_id)
            if not integration or not integration.active:
                run.status = "CANCELLED"
                session.commit()
                return {"skipped": True}
            check = asyncio.run(
                run_integration_check(
                    session, integration, execution_id=execution_id, settings=settings
                )
            )
            return {"check_id": check.id, "outcome": check.outcome}
    except RunExhausted:
        return {"failed": True}
    except RunBusy as exc:
        raise self.retry(exc=exc, countdown=settings.lease_seconds + 1)
    except Exception as exc:
        logger.exception("Worker execution failed for run %s", execution_id)
        raise self.retry(exc=exc, countdown=2)


@celery_app.task(name="app.tasks.dispatch_due_checks")
def dispatch_due_checks():
    queued = 0
    with SessionFactory() as session:
        heartbeat(session, "scheduler")
        session.commit()
        ids = list(
            session.scalars(select(Integration.id).where(Integration.active.is_(True)))
        )
        for integration_id in ids:
            run, publish = reserve_run(
                session, integration_id, settings, scheduled=True
            )
            if run and publish:
                # A lost publication is recovered after the persisted lease expires.
                try:
                    check_integration.apply_async(
                        args=[run.execution_id], task_id=run.execution_id
                    )
                    queued += 1
                except Exception:
                    logger.warning(
                        "Could not publish run %s; its persisted lease permits recovery",
                        run.execution_id,
                    )
    return {"queued": queued}


@celery_app.task(name="app.tasks.operations_tick")
def operations_tick():
    with SessionFactory() as session:
        heartbeat(session, "worker")
        session.commit()
    return {"alerts_delivered": asyncio.run(deliver_alerts(SessionFactory, settings))}


@celery_app.task(name="app.tasks.maintenance")
def maintenance():
    with SessionFactory() as session:
        maintain(session, settings)
