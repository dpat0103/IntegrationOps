# Incident opening and recovery

Status: implemented.

A single failed probe can be a transient network interruption. The default policy therefore opens an incident only after three consecutive Failed observations. Operators can configure this threshold.

Recovery requires two consecutive Healthy observations. A valid but slow response remains Degraded and cannot resolve an incident. This keeps “recovered” consistent with the dashboard's Working state.

Check-based availability uses a different definition: both Healthy and Degraded responses count as acceptable responses. The UI explains that distinction explicitly.

An incident is updated in the same transaction as its triggering check. The service row is locked in PostgreSQL; SQLite final writes are serialized. A partial unique index permits only one Open incident per service.

Evidence: regression tests for thresholds and slow recovery, PostgreSQL concurrency tests, and the browser outage/recovery workflow.
