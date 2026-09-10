import httpx
import pytest

from app.core.db import build_engine_and_session, init_db
from app.core.models import Integration
from app.services.checker import execute_check


def make_integration(session, **kwargs):
    base = dict(
        name="Test",
        endpoint="https://service.test/health",
        expected_status=200,
        timeout_ms=1000,
        latency_threshold_ms=5000,
        check_interval_seconds=60,
        expected_json_key="status",
        expected_json_value="healthy",
    )
    base.update(kwargs)
    obj = Integration(**base)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [(401,"AUTHENTICATION_FAILURE"),(403,"AUTHENTICATION_FAILURE"),(429,"RATE_LIMITED"),(503,"UPSTREAM_FAILURE"),(404,"HTTP_ERROR")],
)
async def test_http_failure_classification(tmp_path, status, expected):
    engine, Factory = build_engine_and_session(f"sqlite:///{tmp_path/'db.sqlite'}")
    init_db(engine)
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error":"x"}))
    with Factory() as session:
        integration = make_integration(session)
        check = await execute_check(session, integration, transport=transport)
        assert check.outcome == "FAILED"
        assert check.failure_type == expected


@pytest.mark.asyncio
async def test_response_validation_failure(tmp_path):
    engine, Factory = build_engine_and_session(f"sqlite:///{tmp_path/'db.sqlite'}")
    init_db(engine)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"state":"healthy"}))
    with Factory() as session:
        integration = make_integration(session)
        check = await execute_check(session, integration, transport=transport)
        assert check.outcome == "FAILED"
        assert check.failure_type == "RESPONSE_VALIDATION_FAILURE"


@pytest.mark.asyncio
async def test_idempotent_execution_id(tmp_path):
    engine, Factory = build_engine_and_session(f"sqlite:///{tmp_path/'db.sqlite'}")
    init_db(engine)
    calls = {"n":0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"status":"healthy"})
    transport = httpx.MockTransport(handler)
    with Factory() as session:
        integration = make_integration(session)
        first = await execute_check(session, integration, execution_id="same-id", transport=transport)
        session.commit()
        second = await execute_check(session, integration, execution_id="same-id", transport=transport)
        assert first.id == second.id
        assert calls["n"] == 1

@pytest.mark.asyncio
async def test_rate_limit_captures_retry_after(tmp_path):
    engine, Factory = build_engine_and_session(f"sqlite:///{tmp_path/'db.sqlite'}")
    init_db(engine)
    transport = httpx.MockTransport(lambda request: httpx.Response(429, headers={'Retry-After':'60'}, json={'error':'rate limited'}))
    with Factory() as session:
        integration = make_integration(session)
        check = await execute_check(session, integration, transport=transport)
        assert check.failure_type == 'RATE_LIMITED'
        assert check.retry_after_seconds == 60
