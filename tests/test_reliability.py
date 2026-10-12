import asyncio
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from app.core.config import Settings
from app.core.db import build_engine_and_session, init_db
from app.core.models import (
    CheckRun,
    HealthCheck,
    Heartbeat,
    Incident,
    Integration,
    utcnow,
)
from app.services.jobs import RunBusy, claim_run, reserve_run
from app.services.orchestrator import run_integration_check


@pytest.fixture
def database(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'runs.db'}", scheduler_enabled=False
    )
    engine, factory = build_engine_and_session(settings.database_url)
    init_db(engine)
    with factory() as session:
        service = Integration(
            name="Reliable service",
            endpoint="https://provider.test",
            check_interval_seconds=5,
            method="GET",
            expected_status=200,
            timeout_ms=1000,
            latency_threshold_ms=1000,
        )
        session.add(service)
        session.commit()
        service_id = service.id
    yield settings, engine, factory, service_id
    engine.dispose()


@pytest.mark.asyncio
async def test_replay_has_no_incident_or_metric_side_effects(database):
    settings, engine, factory, service_id = database
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with factory() as session:
        service = session.get(Integration, service_id)
        for key in ("first", "second", "third"):
            await run_integration_check(
                session,
                service,
                execution_id=key,
                transport=transport,
                settings=settings,
            )
        incident = session.scalar(select(Incident))
        assert incident.failure_count == 3
        for _ in range(3):
            await run_integration_check(
                session,
                service,
                execution_id="third",
                transport=transport,
                settings=settings,
            )
        assert session.scalar(select(func.count()).select_from(HealthCheck)) == 3
        assert incident.failure_count == 3
        from app.services.metrics import render_metrics

        metrics = render_metrics(factory).decode()
        assert (
            'integrationops_checks_total{failure_type="UPSTREAM_FAILURE",outcome="FAILED"} 3.0'
            in metrics
        )


def test_overlapping_dispatches_share_one_run(database):
    settings, engine, factory, service_id = database

    def dispatch(_):
        with factory() as session:
            run, publish = reserve_run(session, service_id, settings, scheduled=True)
            return run.execution_id, publish

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(dispatch, range(6)))
    assert len({run for run, _ in results}) == 1
    assert sum(publish for _, publish in results) == 1


@pytest.mark.asyncio
async def test_expired_worker_claim_reuses_run_and_fences_old_owner(database):
    settings, engine, factory, service_id = database
    with factory() as session:
        run, _ = reserve_run(session, service_id, settings, scheduled=True)
        claim_run(session, run.execution_id, settings)
        run = session.get(CheckRun, run.execution_id)
        run.lease_until = utcnow() - timedelta(seconds=1)
        session.commit()
        run, publish = reserve_run(session, service_id, settings, scheduled=True)
        assert publish
        result = await run_integration_check(
            session,
            session.get(Integration, service_id),
            execution_id=run.execution_id,
            settings=settings,
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        )
        assert result.execution_id == run.execution_id
        assert session.get(CheckRun, run.execution_id).attempts == 2
        assert session.get(CheckRun, run.execution_id).lease_token is None


def test_database_rejects_two_open_incidents(database):
    settings, engine, factory, service_id = database
    with factory() as session:
        session.add(Incident(integration_id=service_id, status="OPEN"))
        session.commit()
        session.add(Incident(integration_id=service_id, status="OPEN"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Incident)) == 1


@pytest.mark.asyncio
async def test_slow_response_does_not_resolve_an_open_incident(database):
    settings, engine, factory, service_id = database

    async def slow(request):
        await asyncio.sleep(0.02)
        return httpx.Response(200)

    with factory() as session:
        service = session.get(Integration, service_id)
        for i in range(3):
            await run_integration_check(
                session,
                service,
                execution_id=f"failure{i}",
                settings=settings,
                transport=httpx.MockTransport(lambda req: httpx.Response(503)),
            )
        service.latency_threshold_ms = 1
        session.commit()
        for i in range(2):
            result = await run_integration_check(
                session,
                service,
                execution_id=f"slow{i}",
                settings=settings,
                transport=httpx.MockTransport(slow),
            )
            assert result.outcome == "DEGRADED"
        assert session.scalar(select(Incident)).status == "OPEN"
        service.latency_threshold_ms = 1000
        session.commit()
        for i in range(2):
            await run_integration_check(
                session,
                service,
                execution_id=f"recovery{i}",
                settings=settings,
                transport=httpx.MockTransport(lambda req: httpx.Response(200)),
            )
        assert session.scalar(select(Incident)).status == "RESOLVED"


def test_stale_results_and_readiness_are_distinct(client, monkeypatch):
    with client.app.state.session_factory() as session:
        service = Integration(
            name="Stopped monitoring",
            endpoint="https://provider.test",
            check_interval_seconds=5,
            last_checked_at=utcnow() - timedelta(days=7),
        )
        session.add(service)
        session.flush()
        session.add(
            HealthCheck(
                execution_id="old",
                integration_id=service.id,
                outcome="HEALTHY",
                checked_at=utcnow() - timedelta(days=7),
            )
        )
        session.commit()
    result = client.get("/api/status").json()[0]
    assert result["status"] == "STALE"
    assert result["last_outcome"] == "HEALTHY"
    assert client.get("/api/overview").json()["healthy"] == 0
    assert client.get("/api/health/live").status_code == 200
    client.app.state.settings.task_mode = "celery"
    monkeypatch.setattr("app.services.status.broker_available", lambda _: True)
    assert client.get("/api/health/ready").status_code == 503
    with client.app.state.session_factory() as session:
        session.add_all([Heartbeat(name="worker"), Heartbeat(name="scheduler")])
        session.commit()
    assert client.get("/api/health/ready").status_code == 200


@pytest.mark.asyncio
async def test_replaced_lease_cannot_commit_old_probe(database):
    settings, engine, factory, service_id = database
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_failure(request):
        entered.set()
        await release.wait()
        return httpx.Response(503)

    async def old_worker():
        with factory() as session:
            return await run_integration_check(
                session,
                session.get(Integration, service_id),
                settings=settings,
                execution_id="fenced-run",
                transport=httpx.MockTransport(delayed_failure),
            )

    old = asyncio.create_task(old_worker())
    await entered.wait()
    with factory() as session:
        run = session.get(CheckRun, "fenced-run")
        run.lease_until = utcnow() - timedelta(seconds=1)
        session.commit()
        new = await run_integration_check(
            session,
            session.get(Integration, service_id),
            settings=settings,
            execution_id="fenced-run",
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        )
        assert new.outcome == "HEALTHY"
    release.set()
    with pytest.raises(RunBusy):
        await old
    with factory() as session:
        checks = list(session.scalars(select(HealthCheck)))
        assert len(checks) == 1 and checks[0].outcome == "HEALTHY"
        assert session.get(CheckRun, "fenced-run").status == "DONE"
