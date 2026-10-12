# Validation record — October 11, 2026

This record describes the implemented local release and its controlled experiments. The source, workflow, and evidence are prepared for publication; a hosted deployment must be verified separately.

## Automated backend validation

- Local suite: **53 passed**, with 3 PostgreSQL-only tests skipped locally.
- The 3 PostgreSQL concurrency tests were separately executed against real PostgreSQL in isolated schemas: **3 passed**.
- Python compile checks passed.
- Next.js production build and browser-test TypeScript checks passed.
- Dependency deprecation warnings remain in the Starlette test-client integration.

Coverage includes API validation, HTTP classification, JSON contract failures, timeouts/network errors, bounded bodies, redirects, restricted targets, DNS pinning, encrypted headers, visitor isolation, cross-origin demo actions, action limits, stable run replay, concurrent reservation, interrupted leases, single-open-incident constraints, stale status, readiness, notification retries, restart-safe metrics, legacy migration, and retention.

## Real distributed workflow

The Docker Compose stack ran FastAPI, PostgreSQL, Redis, Celery Beat, a two-process Celery worker, Prometheus, and Grafana on local-only test ports.

The distributed smoke test passed:

- Beat scheduled checks through Redis and the worker stored results in PostgreSQL.
- Manual checks returned 202 and completed through a worker.
- Repeated delivery of a completed run produced one stored check and no repeated incident failure increment.
- Slow responses did not resolve an open incident.
- Two normal responses resolved it.
- Worker-produced check counters and duration buckets were exported from committed database state.

## Controlled interruption experiment

[Raw results](validation/restart-experiment.json)

A worker container was killed with SIGKILL while a check was Running. After restart, the scheduler republished the same logical run after its lease expired. It completed with two attempts and exactly one persisted result. Recovery elapsed time was 66.25 seconds under the default 60-second lease.

The API was then restarted while an incident was Open. The incident and its exported gauge remained available. Recovery checks subsequently resolved it.

## Measured synthetic workload

[Raw results](validation/benchmark.json)

- 100 independent synthetic services.
- 2 worker processes.
- 30-second intervals; 90-second observation.
- 20% of services returned a delayed 0.8-second response.
- 300 completed checks; all 100 services observed.
- 0 duplicate persisted execution IDs.
- p95 scheduling delay: 7.551 seconds.
- Operator overview p95 response time: 12.195 ms, from 176 request samples.

The operator overview included the synthetic services. Provider responses used in-process HTTPX transports. The report records the environment and explicitly limits the interpretation to this synthetic experiment.

## Query comparison

[Raw results](validation/query-experiment.json)

The previous latest-result lookup issued one SQL statement per service. At 100 services, the batched lookup reduced statements from 100 to 1. Over 20 repetitions, median measured lookup time changed from 36.278 ms to 2.301 ms.

This comparison covers the latest-result lookup only, not the entire API or a production workload.

## Browser and visual verification

Manual browser verification covered the three-service setup, outage/recovery, the complete 11-step case study, About navigation, direct GitHub links, and service history. Responsive inspection covers desktop and narrow mobile layouts.

The hosted Playwright job passed all 8 desktop/mobile tests: failure classification and recovery, service history, About/source links, narrow layouts, the complete case study, and visible connection/invalid-service errors. The backend and frontend jobs also passed. [Hosted validation run](https://github.com/dpat0103/IntegrationOps/actions/runs/38199536192). The distributed recovery job is reported separately by that workflow.

Saved previews are in `docs/validation/`. They show simulated data.

## Limits

These checks establish specific observed behaviors, not exhaustive correctness, production capacity, continuous uptime, or a full accessibility audit. Notification delivery can repeat across an external-send/commit crash boundary. Production hosting needs the configuration and operational controls described in [DEPLOYMENT.md](DEPLOYMENT.md).
