"""Synthetic scheduling experiment. Writes measured results, never business-impact estimates."""

import argparse
import json
import os
import platform
import time
import uuid
from datetime import timedelta
from pathlib import Path
import httpx
from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import build_engine_and_session
from app.core.models import CheckRun, DemoState, HealthCheck, Integration, aware, utcnow


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, __import__("math").ceil(len(values) * p) - 1)], 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--services", type=int, default=100)
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--output", default="/tmp/integrationops-benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.services <= 200 or not 30 <= args.duration <= 300:
        raise ValueError("Experiment bounds: 1–200 services, 30–300 seconds")
    settings = get_settings()
    engine, factory = build_engine_and_session(settings.database_url)
    owner = "benchmark-" + uuid.uuid4().hex[:20]
    started = utcnow()
    with factory() as session:
        for i in range(args.services):
            key = f"b{i}"
            session.add(
                Integration(
                    name=f"Synthetic {i} :: {owner}",
                    endpoint=f"https://demo.integrationops.invalid/{key}",
                    demo_owner=owner,
                    demo_key=key,
                    method="GET",
                    expected_status=200,
                    timeout_ms=1500,
                    latency_threshold_ms=500,
                    check_interval_seconds=30,
                    expected_json_key="status",
                    expected_json_value="healthy",
                )
            )
            session.add(
                DemoState(
                    owner=owner,
                    service=key,
                    mode="slow" if i % 5 == 0 else "healthy",
                    delay_seconds=0.8,
                    expires_at=started + timedelta(hours=1),
                )
            )
        session.commit()
    latencies = []
    client = httpx.Client(
        base_url=os.getenv("API_BASE", "http://api:8000"),
        timeout=10,
        headers={"Authorization": "Bearer " + settings.operator_token}
        if settings.operator_token
        else {},
    )
    print(
        json.dumps(
            {
                "experiment": "started",
                "services": args.services,
                "duration_seconds": args.duration,
            }
        ),
        flush=True,
    )
    deadline = time.monotonic() + args.duration
    last_progress = 0
    while time.monotonic() < deadline:
        tick = time.perf_counter()
        response = client.get("/api/overview")
        assert response.status_code == 200, response.text
        latencies.append((time.perf_counter() - tick) * 1000)
        remaining = deadline - time.monotonic()
        if int(remaining) // 20 != last_progress:
            last_progress = int(remaining) // 20
            print(json.dumps({"remaining_seconds": max(0, int(remaining))}), flush=True)
        time.sleep(0.5)
    with factory() as session:
        ids = list(
            session.scalars(
                select(Integration.id).where(Integration.demo_owner == owner)
            )
        )
        checks = list(
            session.scalars(
                select(HealthCheck).where(HealthCheck.integration_id.in_(ids))
            )
        )
        runs = list(
            session.scalars(
                select(CheckRun).where(
                    CheckRun.integration_id.in_(ids), CheckRun.started_at.is_not(None)
                )
            )
        )
        lag = [
            (aware(run.started_at) - aware(run.scheduled_at)).total_seconds()
            for run in runs
        ]
        duplicates = len(checks) - len({check.execution_id for check in checks})
        serviced = len({check.integration_id for check in checks})
        result = {
            "workload": "synthetic HTTP responses via in-process HTTPX transports; no real provider traffic",
            "services": args.services,
            "interval_seconds": 30,
            "slow_service_fraction": 0.2,
            "slow_response_seconds": 0.8,
            "duration_seconds": args.duration,
            "worker_processes": 2,
            "database": "PostgreSQL"
            if engine.dialect.name == "postgresql"
            else "SQLite",
            "controller_platform": platform.platform(),
            "visible_cpu_count": os.cpu_count(),
            "checks_completed": len(checks),
            "services_checked": serviced,
            "observed_checks_per_second": round(len(checks) / args.duration, 3),
            "scheduling_delay_seconds_p50": percentile(lag, 0.5),
            "scheduling_delay_seconds_p95": percentile(lag, 0.95),
            "scheduling_delay_seconds_max": round(max(lag), 3) if lag else None,
            "api_overview_latency_ms_p50": percentile(latencies, 0.5),
            "api_overview_latency_ms_p95": percentile(latencies, 0.95),
            "api_scope": "operator overview including the synthetic services"
            if settings.operator_token
            else "anonymous empty demo overview",
            "api_sample_count": len(latencies),
            "duplicate_persisted_execution_ids": duplicates,
            "started_at": started.isoformat(),
            "measured_at": utcnow().isoformat(),
            "limits": "One machine, two workers, synthetic transport, short observation window; not a production capacity or uptime guarantee.",
        }
        for service in session.scalars(
            select(Integration).where(Integration.demo_owner == owner)
        ):
            service.active = False
        session.commit()
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    client.close()
    engine.dispose()


if __name__ == "__main__":
    main()
