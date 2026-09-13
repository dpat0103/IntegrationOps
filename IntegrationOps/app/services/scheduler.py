from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select

from app.core.models import Integration
from app.services.orchestrator import run_integration_check


class LocalScheduler:
    def __init__(self, session_factory, settings):
        self.session_factory = session_factory
        self.settings = settings
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._dispatch_due()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.scheduler_tick_seconds)
            except asyncio.TimeoutError:
                pass

    async def _dispatch_due(self) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            integrations = list(session.scalars(select(Integration).where(Integration.active.is_(True))))
            due_ids = []
            for integration in integrations:
                if integration.last_checked_at is None:
                    due_ids.append(integration.id)
                    continue
                last_checked = integration.last_checked_at
                if last_checked.tzinfo is None:
                    last_checked = last_checked.replace(tzinfo=timezone.utc)
                if (now - last_checked).total_seconds() >= integration.check_interval_seconds:
                    due_ids.append(integration.id)

        if due_ids:
            await asyncio.gather(*(self._check_one(integration_id) for integration_id in due_ids), return_exceptions=True)

    async def _check_one(self, integration_id: int) -> None:
        with self.session_factory() as session:
            integration = session.get(Integration, integration_id)
            if not integration or not integration.active:
                return
            await run_integration_check(
                session,
                integration,
                failure_threshold=self.settings.failure_threshold,
                recovery_threshold=self.settings.recovery_threshold,
                slack_webhook_url=self.settings.slack_webhook_url,
            )
