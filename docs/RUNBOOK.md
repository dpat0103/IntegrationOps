# IntegrationOps troubleshooting runbook

## Start with the monitor

1. Check `/api/health/live`: a response means the API process is running.
2. Check `/api/health/ready`: inspect unavailable components and heartbeat ages.
3. Inspect the provisioned Grafana dashboard. A growing queue or missing worker heartbeat indicates a monitoring-system problem.
4. Check container logs for dispatch or execution failures. Do not paste credentials, webhook URLs, or unredacted environment configuration into public issues.

## A service shows Out of date

Compare its last-check timestamp with the configured interval and grace period. The previous success remains in history, but it is not treated as current health.

If many services are stale, inspect the scheduler heartbeat, broker, workers, and oldest queued-run age. If one service is affected, inspect its persisted run status and attempt count.

A worker interrupted during a probe leaves a leased Running run. The scheduler can republish the same run after expiry. The default recovery window includes the 60-second lease plus the scheduling tick and actual check duration. Failed runs with exhausted attempts require operator attention.

## An incident is open

Open the service detail view and inspect the latest observations:

| Category                  | Investigation                                                                        |
| ------------------------- | ------------------------------------------------------------------------------------ |
| Access denied             | Check credentials and access permissions through the provider's supported process.   |
| Rate limited              | Check provider quotas and the monitoring interval.                                   |
| Timeout / network failure | Check provider reachability, DNS, connectivity, and the configured deadline.         |
| Unexpected response data  | Compare the expected JSON field/value with the provider's current response contract. |
| Slow response             | Check latency history and the configured performance threshold.                      |
| Unsafe target             | Review the destination policy; private or metadata targets must remain blocked.      |
| Configuration error       | Check the configured encryption key and legacy credential migration.                 |

These categories identify observable failure conditions. They do not prove the provider's internal root cause.

## Recovery

Two consecutive normal responses resolve an incident by default. A slow valid response remains Degraded and does not resolve it. Inspect the incident's opened and recovered timestamps rather than relying on a single successful check.

## Slack did not notify

The incident and outbox record commit before external delivery. Inspect pending/retry/dead notification counts. A transient webhook failure retries with bounded backoff; a Dead delivery needs configuration correction and operator investigation.

Delivery can repeat after a crash between sending and recording success. Do not describe notifications as exactly-once.

## Worked example

In the Payment API case study, the provider returns 503 repeatedly. IntegrationOps records Upstream Failure checks, opens an incident at the failure threshold, and preserves its history. Switching to a slow response does not resolve the incident. Restoring normal responses twice resolves it.

To reproduce from the browser, use Cause outage, then Restore service. The longer case study also demonstrates access errors, rate limits, contract failure, and latency degradation.

## Restart and data maintenance

Apply migrations before the distributed services start. Back up an owned database before upgrades. The initial migration supports additive upgrade of the original schema; it refuses destructive downgrade.

Demo state expires by TTL. Detail retention defaults to 30 days while preserving the latest result for each service. Database-backed lifetime metrics remain available. Use durable PostgreSQL storage and a backup policy for non-demo monitoring.
