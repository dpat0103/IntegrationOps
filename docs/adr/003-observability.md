# Freshness, readiness, and cross-process metrics

Status: implemented.

A historical success is not current evidence. A service becomes Stale once its latest check exceeds the expected interval plus a configurable grace period. With no check, the creation time provides the initial freshness reference.

Liveness reports that the API process can respond. Readiness checks the database and, in distributed mode, the broker and recent scheduler/worker heartbeats. Manual-only previews explicitly identify that checks are not automatic.

Process-local Prometheus counters would miss separate Celery worker activity and reset an incident gauge on API restart. The exporter instead collects committed metric totals, incident/run/outbox state, and heartbeats from the shared database.

Probe counters and duration buckets commit with the observation. They use bounded result-category labels, never a service URL or visitor ID. Lifetime totals survive historical-detail retention. Open incident and queue measurements are gauges reconstructed on every scrape.

The status query batches latest-result lookup. Availability uses SQL aggregation; percentile lookup orders measured durations in the database rather than loading the entire window into application memory.

Evidence: exporter/restart tests, the real worker smoke test, the API restart experiment, and the 100-to-1 SQL lookup comparison.
