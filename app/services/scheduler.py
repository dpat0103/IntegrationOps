import asyncio
import logging
from sqlalchemy import select
from app.core.models import Integration
from app.services.alerts import deliver_alerts
from app.services.jobs import RunBusy, heartbeat, reserve_run
from app.services.maintenance import maintain
from app.services.orchestrator import run_integration_check

logger = logging.getLogger(__name__)


class LocalScheduler:
    def __init__(self, session_factory, settings):
        self.session_factory, self.settings = session_factory, settings
        self._stop = asyncio.Event()
        self._task = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_checks)
        self._ticks = 0

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop.set()
        if self._task:
            await self._task

    async def _run(self):
        while not self._stop.is_set():
            try:
                await self._dispatch_due()
                await deliver_alerts(self.session_factory, self.settings)
                self._ticks += 1
                if self._ticks % 120 == 0:
                    with self.session_factory() as session:
                        maintain(session, self.settings)
            except Exception:
                logger.exception("Local monitoring cycle failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.scheduler_tick_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def _dispatch_due(self):
        with self.session_factory() as session:
            heartbeat(session, "scheduler")
            session.commit()
            ids = list(
                session.scalars(
                    select(Integration.id).where(Integration.active.is_(True))
                )
            )
        await asyncio.gather(*(self._check_one(service_id) for service_id in ids))

    async def _check_one(self, service_id):
        async with self._semaphore:
            try:
                with self.session_factory() as session:
                    run, execute = reserve_run(
                        session, service_id, self.settings, scheduled=True
                    )
                    if not run or not execute:
                        return
                    integration = session.get(Integration, service_id)
                    await run_integration_check(
                        session,
                        integration,
                        execution_id=run.execution_id,
                        settings=self.settings,
                    )
            except RunBusy:
                pass
            except Exception:
                logger.exception("Scheduled check failed for service %s", service_id)
