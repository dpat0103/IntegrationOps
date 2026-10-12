"""Concurrency checks against isolated schemas in a real PostgreSQL database."""

import asyncio
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.orm import sessionmaker
from app.core.config import Settings
from app.core.db import init_db
from app.core.models import HealthCheck, Incident, Integration
from app.services.jobs import RunBusy, reserve_run
from app.services.orchestrator import run_integration_check

pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_TEST_URL"), reason="Requires explicit POSTGRES_TEST_URL"
)


@pytest.fixture
def postgres():
    url = os.environ["POSTGRES_TEST_URL"]
    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, pool_size=8
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    init_db(engine)
    with factory() as session:
        service = Integration(
            name="Concurrent service",
            endpoint="https://provider.test",
            method="GET",
            expected_status=200,
            timeout_ms=1000,
            latency_threshold_ms=1000,
            check_interval_seconds=5,
        )
        session.add(service)
        session.commit()
        service_id = service.id
    settings = Settings(database_url=url, task_mode="local", scheduler_enabled=False)
    yield settings, factory, service_id
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(DropSchema(schema, cascade=True))
    admin.dispose()


def test_postgres_overlapping_schedulers_reserve_once(postgres):
    settings, factory, service_id = postgres

    def dispatch(_):
        with factory() as session:
            run, publish = reserve_run(session, service_id, settings, scheduled=True)
            return run.execution_id, publish

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(dispatch, range(12)))
    assert len({key for key, _ in results}) == 1
    assert sum(publish for _, publish in results) == 1


def test_postgres_concurrent_delivery_is_replay_safe(postgres):
    settings, factory, service_id = postgres
    calls = {"count": 0}
    lock = threading.Lock()

    async def response(request):
        with lock:
            calls["count"] += 1
        await asyncio.sleep(0.2)
        return httpx.Response(503)

    def deliver(_):
        with factory() as session:
            try:
                result = asyncio.run(
                    run_integration_check(
                        session,
                        session.get(Integration, service_id),
                        settings=settings,
                        execution_id="same-logical-run",
                        failure_threshold=1,
                        transport=httpx.MockTransport(response),
                    )
                )
                return result.id
            except RunBusy:
                return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(deliver, range(12)))
    assert calls["count"] == 1
    assert len({result for result in results if result is not None}) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HealthCheck)) == 1
        assert session.scalar(select(func.count()).select_from(Incident)) == 1
        assert session.scalar(select(Incident)).failure_count == 1


def test_postgres_separate_runs_preserve_single_open_incident(postgres):
    settings, factory, service_id = postgres

    def deliver(index):
        with factory() as session:
            try:
                return asyncio.run(
                    run_integration_check(
                        session,
                        session.get(Integration, service_id),
                        settings=settings,
                        execution_id=f"run-{index}",
                        failure_threshold=1,
                        transport=httpx.MockTransport(lambda req: httpx.Response(503)),
                    )
                ).id
            except RunBusy:
                return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(deliver, range(12)))
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Incident)
                .where(Incident.status == "OPEN")
            )
            == 1
        )
        assert session.scalar(select(func.count()).select_from(HealthCheck)) >= 1
