import httpx
import pytest
from sqlalchemy import select
from app.core.db import build_engine_and_session, init_db
from app.core.models import Incident, Integration
from app.services.orchestrator import run_integration_check


@pytest.mark.asyncio
async def test_full_incident_lifecycle(tmp_path):
    engine, Factory = build_engine_and_session(f"sqlite:///{tmp_path/'db.sqlite'}")
    init_db(engine)
    state = {'status':503}
    def handler(request):
        if state['status'] == 503:
            return httpx.Response(503, json={'error':'down'})
        return httpx.Response(200, json={'status':'healthy'})
    transport = httpx.MockTransport(handler)

    with Factory() as session:
        integration = Integration(name='Payments API', endpoint='https://payments.test/health', expected_status=200,
            timeout_ms=1000, latency_threshold_ms=500, check_interval_seconds=60, expected_json_key='status', expected_json_value='healthy')
        session.add(integration); session.commit(); session.refresh(integration)
        for n in range(3):
            await run_integration_check(session, integration, failure_threshold=3, recovery_threshold=2, transport=transport, execution_id=f'fail-{n}')
        incidents = list(session.scalars(select(Incident)))
        assert len(incidents) == 1 and incidents[0].status == 'OPEN'

        state['status'] = 200
        for n in range(2):
            await run_integration_check(session, integration, failure_threshold=3, recovery_threshold=2, transport=transport, execution_id=f'ok-{n}')
        session.refresh(incidents[0])
        assert incidents[0].status == 'RESOLVED'
        assert incidents[0].resolved_at is not None
