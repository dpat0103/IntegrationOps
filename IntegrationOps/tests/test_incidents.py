from app.core.db import build_engine_and_session, init_db
from app.core.models import HealthCheck, Integration
from app.services.incidents import apply_incident_policy


def add_check(session, integration_id, outcome, n):
    session.add(HealthCheck(execution_id=f"e{n}", integration_id=integration_id, outcome=outcome))
    session.flush()


def test_incident_opens_after_three_failures_and_resolves_after_two_successes(tmp_path):
    engine, Factory = build_engine_and_session(f"sqlite:///{tmp_path/'db.sqlite'}")
    init_db(engine)
    with Factory() as session:
        integration = Integration(name="A", endpoint="https://a.test", check_interval_seconds=60)
        session.add(integration)
        session.commit()
        for n in range(1,4):
            add_check(session, integration.id, "FAILED", n)
            incident, event = apply_incident_policy(session, integration, failure_threshold=3, recovery_threshold=2)
        assert incident is not None
        assert event == "OPENED"
        assert incident.status == "OPEN"

        add_check(session, integration.id, "HEALTHY", 4)
        incident, event = apply_incident_policy(session, integration, failure_threshold=3, recovery_threshold=2)
        assert event is None
        add_check(session, integration.id, "HEALTHY", 5)
        incident, event = apply_incident_policy(session, integration, failure_threshold=3, recovery_threshold=2)
        assert event == "RESOLVED"
        assert incident.status == "RESOLVED"
        assert incident.resolved_at is not None
