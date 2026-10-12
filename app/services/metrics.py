"""Metrics collected from committed database state, including work done by separate workers."""

from sqlalchemy import func, select
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)
from app.core.models import (
    AlertEvent,
    CheckRun,
    Heartbeat,
    Incident,
    MetricTotal,
    aware,
    utcnow,
)

BUCKETS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)


def increment(session, key, value=1):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(MetricTotal).values(key=key, value=value)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["key"], set_={"value": MetricTotal.value + value}
        )
    )


def record_probe(session, result):
    increment(session, f"checks:{result.outcome}:{result.failure_type or 'NONE'}")
    seconds = (result.latency_ms or 0) / 1000
    increment(session, "duration:count")
    increment(session, "duration:sum", seconds)
    for bucket in BUCKETS:
        if seconds <= bucket:
            increment(session, f"duration:{bucket}")


class DatabaseCollector:
    def __init__(self, factory):
        self.factory = factory

    def collect(self):
        with self.factory() as session:
            totals = dict(
                session.execute(select(MetricTotal.key, MetricTotal.value)).all()
            )
            checks = CounterMetricFamily(
                "integrationops_checks",
                "Committed health checks",
                labels=["outcome", "failure_type"],
            )
            for key, value in sorted(totals.items()):
                if key.startswith("checks:"):
                    _, outcome, failure = key.split(":")
                    checks.add_metric([outcome, failure], value)
            yield checks
            histogram = HistogramMetricFamily(
                "integrationops_check_duration_seconds",
                "Probe duration from all processes",
            )
            histogram.add_metric(
                [],
                [
                    (str(bucket), totals.get(f"duration:{bucket}", 0))
                    for bucket in BUCKETS
                ]
                + [("+Inf", totals.get("duration:count", 0))],
                totals.get("duration:sum", 0),
            )
            yield histogram
            for name, description, query in [
                (
                    "active_incidents",
                    "Persisted open incidents",
                    select(func.count())
                    .select_from(Incident)
                    .where(Incident.status == "OPEN"),
                ),
                (
                    "pending_runs",
                    "Queued check runs",
                    select(func.count())
                    .select_from(CheckRun)
                    .where(CheckRun.status == "QUEUED"),
                ),
                (
                    "running_checks",
                    "Claimed check runs",
                    select(func.count())
                    .select_from(CheckRun)
                    .where(CheckRun.status == "RUNNING"),
                ),
                (
                    "failed_runs",
                    "Runs requiring operator attention",
                    select(func.count())
                    .select_from(CheckRun)
                    .where(CheckRun.status == "FAILED"),
                ),
                (
                    "pending_alerts",
                    "Notifications awaiting delivery",
                    select(func.count())
                    .select_from(AlertEvent)
                    .where(AlertEvent.status.in_(["PENDING", "RETRY", "SENDING"])),
                ),
                (
                    "dead_alerts",
                    "Notifications with exhausted retries",
                    select(func.count())
                    .select_from(AlertEvent)
                    .where(AlertEvent.status == "DEAD"),
                ),
            ]:
                metric = GaugeMetricFamily("integrationops_" + name, description)
                metric.add_metric([], session.scalar(query) or 0)
                yield metric
            heartbeat = GaugeMetricFamily(
                "integrationops_heartbeat_age_seconds",
                "Age of persisted process heartbeat",
                labels=["role"],
            )
            for role in ("scheduler", "worker"):
                value = session.get(Heartbeat, role)
                heartbeat.add_metric(
                    [role],
                    max(0, (utcnow() - aware(value.updated_at)).total_seconds())
                    if value
                    else -1,
                )
            yield heartbeat
            oldest = session.scalar(
                select(func.min(CheckRun.scheduled_at)).where(
                    CheckRun.status == "QUEUED"
                )
            )
            lag = GaugeMetricFamily(
                "integrationops_queue_oldest_age_seconds", "Age of oldest queued run"
            )
            lag.add_metric(
                [], max(0, (utcnow() - aware(oldest)).total_seconds()) if oldest else 0
            )
            yield lag
            alerts = CounterMetricFamily(
                "integrationops_alert_deliveries",
                "Committed notification delivery attempts",
                labels=["status"],
            )
            for status in ("SENT", "RETRY", "DEAD"):
                alerts.add_metric([status], totals.get("alerts:" + status, 0))
            yield alerts


def render_metrics(factory):
    registry = CollectorRegistry()
    registry.register(DatabaseCollector(factory))
    return generate_latest(registry)
