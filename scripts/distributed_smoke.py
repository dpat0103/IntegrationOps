"""Validate the real Beat/Redis/Celery/PostgreSQL path in the Compose network."""

import json
import os
import time
import httpx
from sqlalchemy import func, select
from app.core.config import get_settings
from app.core.db import build_engine_and_session
from app.core.models import HealthCheck, Incident
from app.tasks import check_integration


def wait_for(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.3)
    raise AssertionError("Timed out waiting for distributed workflow")


def main():
    settings = get_settings()
    engine, factory = build_engine_and_session(settings.database_url)
    client = httpx.Client(base_url=os.getenv("API_BASE", "http://api:8000"), timeout=10)
    wait_for(lambda: client.get("/api/health/ready").status_code == 200)
    examples = client.post("/api/demo").json()
    payment = next(item for item in examples if item["demo_key"] == "payment")
    history = lambda: client.get(f"/api/integrations/{payment['id']}/checks").json()
    wait_for(lambda: len(history()) >= 1)

    def scenario(mode):
        response = client.post(
            "/api/demo/scenario", json={"service": "payment", "mode": mode}
        )
        assert response.status_code == 200, response.text

    def run():
        response = client.post(f"/api/integrations/{payment['id']}/check")
        assert response.status_code == 202, response.text
        run_id = response.json()["execution_id"]
        result = wait_for(lambda: client.get("/api/runs/" + run_id).json().get("check"))
        return run_id, result

    scenario("server_error")
    run_ids = []
    for _ in range(3):
        run_id, result = run()
        run_ids.append(run_id)
        assert result["failure_type"] == "UPSTREAM_FAILURE"
    assert any(item["status"] == "OPEN" for item in client.get("/api/incidents").json())
    with factory() as session:
        incident = session.scalar(
            select(Incident).where(
                Incident.integration_id == payment["id"], Incident.status == "OPEN"
            )
        )
        failures_before = incident.failure_count
    for _ in range(2):
        task = check_integration.apply_async(args=[run_ids[-1]], task_id=run_ids[-1])
        task.get(timeout=20)
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(HealthCheck)
                .where(HealthCheck.execution_id == run_ids[-1])
            )
            == 1
        )
        assert session.get(Incident, incident.id).failure_count == failures_before
    scenario("slow")
    _, result = run()
    assert result["outcome"] == "DEGRADED"
    assert any(item["status"] == "OPEN" for item in client.get("/api/incidents").json())
    scenario("healthy")
    for _ in range(2):
        run()
    assert not any(
        item["status"] == "OPEN" for item in client.get("/api/incidents").json()
    )
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "integrationops_checks_total" in metrics.text
    assert "integrationops_check_duration_seconds_bucket" in metrics.text
    from prometheus_client.parser import text_string_to_metric_families

    parsed = list(text_string_to_metric_families(metrics.text))
    assert any(family.name == "integrationops_checks" for family in parsed)
    report = {
        "status": "passed",
        "scheduled_checks": True,
        "manual_checks_queued": True,
        "replay_safe": True,
        "slow_does_not_resolve": True,
        "recovery": True,
        "worker_metrics": True,
        "database": engine.dialect.name,
        "service_id": payment["id"],
    }
    print(json.dumps(report, indent=2), flush=True)
    engine.dispose()
    client.close()


if __name__ == "__main__":
    main()
