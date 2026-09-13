from prometheus_client import Counter, Gauge, Histogram

CHECKS_TOTAL = Counter(
    "integrationops_checks_total",
    "Total integration health checks",
    ["outcome", "failure_type"],
)
CHECK_DURATION = Histogram(
    "integrationops_check_duration_seconds",
    "Integration check duration in seconds",
)
ACTIVE_INCIDENTS = Gauge(
    "integrationops_active_incidents",
    "Currently open integration incidents",
)
ALERTS_TOTAL = Counter(
    "integrationops_alerts_total",
    "Alerts emitted by IntegrationOps",
    ["event_type", "status"],
)
