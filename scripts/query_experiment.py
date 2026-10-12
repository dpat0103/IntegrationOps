"""Compare the previous per-service latest-check lookup with the batched implementation."""

import json
import statistics
import time
from pathlib import Path
from sqlalchemy import event, select
from app.core.config import get_settings
from app.core.db import build_engine_and_session
from app.core.models import HealthCheck, Integration
from app.services.status import latest_checks


def main():
    engine, factory = build_engine_and_session(get_settings().database_url)
    with factory() as session:
        owner = session.scalar(
            select(Integration.demo_owner)
            .where(Integration.demo_owner.like("benchmark-%"))
            .limit(1)
        )
        ids = list(
            session.scalars(
                select(Integration.id).where(Integration.demo_owner == owner)
            )
        )
    assert len(ids) == 100, "Run the 100-service experiment first"
    queries = {"count": 0}

    def count(*args):
        queries["count"] += 1

    event.listen(engine, "before_cursor_execute", count)

    def baseline(session):
        return [
            session.scalar(
                select(HealthCheck)
                .where(HealthCheck.integration_id == service_id)
                .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
                .limit(1)
            )
            for service_id in ids
        ]

    output = {}
    for name, lookup in (
        ("previous_per_service_lookup", baseline),
        ("batched_lookup", lambda session: latest_checks(session, ids)),
    ):
        timings = []
        counts = []
        for _ in range(20):
            with factory() as session:
                queries["count"] = 0
                start = time.perf_counter()
                result = lookup(session)
                timings.append((time.perf_counter() - start) * 1000)
                counts.append(queries["count"])
                assert len(result) == 100
        output[name] = {
            "sql_statements_per_lookup": counts[0],
            "latency_ms_median": round(statistics.median(timings), 3),
            "iterations": 20,
        }
    output["scope"] = (
        "Latest-check lookup only, 100 services and stored synthetic results, PostgreSQL on one machine"
    )
    output["measured_at"] = (
        __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat()
    )
    Path("/tmp/query-experiment.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
