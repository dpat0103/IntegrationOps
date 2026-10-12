# Stable runs, claims, and interrupted delivery

Status: implemented.

Queue delivery can repeat. Every scheduled observation receives a persisted UUID before publication; Celery messages carry that logical run ID.

A partial unique index permits one Queued or Running run per service. Reservation takes the service row lock, so overlapping dispatchers share the same reservation. Queued publications and Running executions have bounded leases.

A conditional update claims an eligible run with a unique token. Probing occurs outside the final database transaction. Final persistence verifies the claim token before committing the result, incident transition, metrics, and notification outbox. A replaced owner cannot commit stale work.

Retries reuse the run ID. Completed runs return the stored result immediately and do not invoke the incident policy again. Unpublished work and interrupted claims can be republished after lease expiry. Exhausted runs are retained as Failed for operator visibility.

External HTTP probes can execute again after a crash; the guarantee concerns one committed outcome per logical run, not exactly-once contact with the provider. Monitor endpoints should be safe/idempotent. Slack delivery is separately retryable and can repeat across the external-send/commit boundary.

The default lease is 60 seconds; the maximum probe timeout is 30 seconds. Lower leases still exceed the maximum probe deadline.

Evidence: reservation/replay tests, PostgreSQL concurrent-delivery tests, and the controlled SIGKILL experiment, which recovered one result using two attempts.
