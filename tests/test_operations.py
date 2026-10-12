from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select
from app.core.models import AlertEvent, Incident, Integration, utcnow
from app.services.alerts import deliver_alerts
from app.services.orchestrator import run_integration_check


@pytest.mark.asyncio
async def test_alert_outbox_survives_delivery_failure_and_replay(client):
    settings = client.app.state.settings
    settings.slack_webhook_url = "https://hooks.slack.com/services/fake-test"
    factory = client.app.state.session_factory
    with factory() as session:
        service = Integration(
            name="Alert service",
            endpoint="https://provider.test",
            method="GET",
            expected_status=200,
            timeout_ms=1000,
            check_interval_seconds=60,
        )
        session.add(service)
        session.commit()
        for index in range(3):
            await run_integration_check(
                session,
                service,
                settings=settings,
                execution_id=f"alert{index}",
                transport=httpx.MockTransport(lambda request: httpx.Response(503)),
            )
        event = session.scalar(select(AlertEvent))
        assert event.status == "PENDING" and event.attempts == 0
        incident_id = event.incident_id
    assert (
        await deliver_alerts(
            factory, settings, httpx.MockTransport(lambda req: httpx.Response(503))
        )
        == 0
    )
    with factory() as session:
        event = session.scalar(select(AlertEvent))
        assert event.status == "RETRY" and event.attempts == 1
        assert session.get(Incident, incident_id).status == "OPEN"
        event.next_attempt_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert (
        await deliver_alerts(
            factory, settings, httpx.MockTransport(lambda req: httpx.Response(200))
        )
        == 1
    )
    assert (
        await deliver_alerts(
            factory, settings, httpx.MockTransport(lambda req: httpx.Response(200))
        )
        == 0
    )
    with factory() as session:
        event = session.scalar(select(AlertEvent))
        assert event.status == "SENT" and event.attempts == 2
        service = session.scalar(
            select(Integration).where(Integration.name == "Alert service")
        )
        await run_integration_check(
            session,
            service,
            settings=settings,
            execution_id="alert2",
            transport=httpx.MockTransport(lambda req: httpx.Response(503)),
        )
        assert len(list(session.scalars(select(AlertEvent)))) == 1
    assert client.get("/metrics").status_code == 200
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as restarted:
        metrics = restarted.get("/metrics").text
        assert "integrationops_active_incidents 1.0" in metrics
        assert 'integrationops_alert_deliveries_total{status="SENT"} 1.0' in metrics


@pytest.mark.asyncio
async def test_alert_retries_are_bounded(client):
    settings = client.app.state.settings
    settings.slack_webhook_url = "https://hooks.slack.com/services/fake-test"
    settings.alert_max_attempts = 2
    factory = client.app.state.session_factory
    with factory() as session:
        service = Integration(
            name="Bounded alerts",
            endpoint="https://provider.test",
            method="GET",
            expected_status=200,
            timeout_ms=1000,
            check_interval_seconds=60,
        )
        session.add(service)
        session.commit()
        await run_integration_check(
            session,
            service,
            settings=settings,
            failure_threshold=1,
            transport=httpx.MockTransport(lambda req: httpx.Response(503)),
        )
    for _ in range(2):
        with factory() as session:
            event = session.scalar(select(AlertEvent))
            event.next_attempt_at = utcnow() - timedelta(seconds=1)
            session.commit()
        await deliver_alerts(
            factory, settings, httpx.MockTransport(lambda req: httpx.Response(503))
        )
    with factory() as session:
        event = session.scalar(select(AlertEvent))
        assert event.status == "DEAD" and event.attempts == 2
        assert session.scalar(select(Incident)).status == "OPEN"


def test_upgrade_preserves_legacy_data_and_is_repeatable(tmp_path):
    import sqlite3
    from app.core.db import build_engine_and_session, init_db

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE integrations (id INTEGER PRIMARY KEY,name VARCHAR(120) NOT NULL,endpoint VARCHAR(1000) NOT NULL,method VARCHAR(10) NOT NULL,expected_status INTEGER NOT NULL,timeout_ms INTEGER NOT NULL,latency_threshold_ms INTEGER,check_interval_seconds INTEGER NOT NULL,expected_json_key VARCHAR(255),expected_json_value VARCHAR(255),headers_json TEXT,active BOOLEAN NOT NULL,created_at DATETIME NOT NULL,last_checked_at DATETIME)"
        )
        connection.execute(
            "INSERT INTO integrations VALUES (1,'Legacy','https://example.com','GET',200,3000,1000,60,NULL,NULL,NULL,1,CURRENT_TIMESTAMP,NULL)"
        )
    engine, factory = build_engine_and_session(f"sqlite:///{path}")
    init_db(engine)
    init_db(engine)
    with factory() as session:
        service = session.get(Integration, 1)
        assert service.name == "Legacy"
        assert service.demo_owner is None
        from sqlalchemy import text

        assert (
            session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0003_demo_limits"
        )
    engine.dispose()


def test_retention_preserves_latest_result_and_removes_expired_demo(client):
    from app.core.models import DemoState, HealthCheck
    from app.services.maintenance import maintain

    factory = client.app.state.session_factory
    with factory() as session:
        service = Integration(name="History", endpoint="https://provider.test")
        expired = Integration(
            name="Expired :: owner",
            endpoint="https://demo.integrationops.invalid/payment",
            demo_owner="owner",
            demo_key="payment",
        )
        session.add_all([service, expired])
        session.flush()
        session.add_all(
            [
                HealthCheck(
                    execution_id="older",
                    integration_id=service.id,
                    outcome="HEALTHY",
                    checked_at=utcnow() - timedelta(days=60),
                ),
                HealthCheck(
                    execution_id="latest",
                    integration_id=service.id,
                    outcome="HEALTHY",
                    checked_at=utcnow() - timedelta(days=40),
                ),
                DemoState(
                    owner="owner",
                    service="payment",
                    expires_at=utcnow() - timedelta(hours=1),
                ),
            ]
        )
        session.commit()
        maintain(session, client.app.state.settings)
        assert len(list(session.scalars(select(HealthCheck)))) == 1
        assert session.scalar(select(HealthCheck)).execution_id == "latest"
        assert (
            session.scalar(select(Integration).where(Integration.demo_owner == "owner"))
            is None
        )
