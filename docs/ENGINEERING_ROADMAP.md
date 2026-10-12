# IntegrationOps — engineering assessment and resume-readiness plan

## Implementation update

The roadmap's reliability, safety, observability, case-study, and measurement work is now implemented locally. Validation includes 53 fast backend tests, 3 real PostgreSQL concurrency tests, distributed scheduling/replay, a worker SIGKILL recovery experiment, API restart, and a 100-service synthetic workload. The site now includes an About page and service history; the README describes the implemented behavior. See [VALIDATION.md](VALIDATION.md) for evidence and the GitHub CI result for automated browser execution. Publication and hosted verification remain release steps.

The assessment below is the historical starting point and records the reasons for those changes.

Assessment date: October 11, 2026. Scope: current local source, test suite, and saved browser-validation evidence. This assessment does not claim that the local redesign has been published. No application servers or workers were started for this assessment.

## Decision

IntegrationOps is already suitable for a resume as an independent backend engineering portfolio project, particularly for early-career Python/backend roles. Its failure classifier, persistent incident lifecycle, API, tests, and usable simulation provide concrete work to discuss.

Its strongest future identity is **a dependency-monitoring system that demonstrates correctness under failure**. The next release should prove that checks, incidents, alerts, and monitoring freshness remain trustworthy across retries, concurrent workers, and restarts.

The code currently provides more operational architecture than verified operational guarantees. It needs that evidence before it should be presented as a production-ready reliability platform or a strong demonstration of distributed operations.

## Current evidence

- Re-ran the backend suite: **20 tests passed**, with two dependency deprecation warnings.
- Previous local validation documented a successful Next.js production build, a real browser outage/recovery workflow, error-state behavior, and responsive checks at 390 px and 320 px.
- API workflow tests use an isolated SQLite database and a mocked upstream. The test client disables background scheduling.
- Docker/Celery/PostgreSQL end-to-end operation remains unverified in the validation record.
- The redesigned interface and README are local changes. This folder has no `.git` directory; publication needs a proper repository checkout and tracked commits.

### Two issues reproduced during this assessment

1. Inserted a successful check from seven days ago into an isolated test database. `/api/status` still returned `HEALTHY`, and `/api/health` returned `ok`. The monitor has no stale-result classification or scheduler health gate.
2. Ran three unique failed checks, then replayed the final execution ID through the orchestrator. The number of stored check results stayed unchanged, but the incident's failure count increased from 3 to 4. Check-result reuse does not prevent repeated incident-policy side effects.

### Issues identified through source review

- Beat checks `last_checked_at` every five seconds without an atomic reservation. A slow task or backlog can be queued again before completion updates that field.
- The worker does not pass a stable execution ID to the orchestrator; checks generate a new UUID by default. Worker retries therefore do not have end-to-end deduplication.
- Incident opening uses read-then-create without a database constraint enforcing one open incident per integration or concurrency coordination.
- Prometheus scrapes `api:8000` only. Worker counters and histograms live in separate processes and are not collected by that endpoint. The open-incident gauge is in-memory and is not reconstructed from persistent state on restart.
- Configuration and simulator mutation routes have no authentication. Probes accept arbitrary HTTP URLs and follow redirects without target-address validation. Stored request headers are plaintext.
- The local scheduler gathers all due tasks without a concurrency bound and discards returned exceptions without logging them.
- Overview/status requests query the latest result per integration; overview loads the full 24-hour check set into memory. Historical storage has no retention policy.
- Slack delivery happens before the monitoring transaction commits. Delivery errors are caught, but the design has no durable retry queue or outbox for the case where delivery succeeds and the database commit fails.
- Availability is aggregated across recorded checks, and recovery includes slow responses. Those semantics need explicit tests and a consistent definition in dashboards and documentation.

These source-review findings are engineering risks and gaps; this assessment did not run a concurrent PostgreSQL load test or reproduce every failure mode.

## Strengths to preserve

| Strength                           | Why it matters to a reviewer                                                                                               |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| A recognizable operational problem | An application can be online while its payment, shipping, identity, or other provider is failing.                          |
| Failure-aware checks               | HTTP errors, timeouts, connection failures, response mismatches, and slow responses require different diagnoses.           |
| Explicit incident lifecycle        | Consecutive failure/recovery thresholds demonstrate stateful business rules and reduce transient incident noise.           |
| Stored history and API control     | Gives interviewers database modeling, REST design, and validation work to inspect.                                         |
| Background-worker architecture     | Provides a concrete setting for discussing queues, retries, independent execution, and scheduling.                         |
| Repeatable demonstration           | An evaluator can intentionally break a service and watch recovery rather than waiting for an outage.                       |
| Clearer presentation               | Plain-language framing, readable interface, and technical detail let recruiters and engineers explore at different depths. |
| Honest documentation               | Separating implemented capabilities from future work makes technical claims easier to trust.                               |

## Role alignment

**Backend / Python software engineering:** strongest current fit. Emphasize API design, validation, data modeling, asynchronous execution, incident rules, and tests.

**API integration / technical solutions engineering:** useful supporting project. It demonstrates diagnosing external API behavior and documenting a workflow. Enterprise integration roles also involve authenticating to providers, mapping data, synchronization, webhooks, and reconciliation; monitoring alone does not demonstrate all of those.

**Platform / reliability / DevOps engineering:** promising direction. The missing evidence is operating the worker stack, correct observability, failure recovery, readiness, deployment automation, and runbooks.

Current employer-posting examples reinforce this direction:

- [Canonical — Python software engineering](https://job-boards.greenhouse.io/canonical/jobs/5703396): Python delivery, containers, testing, personal projects, observability, identity, and tracing.
- [Qover — site reliability and platform engineering](https://jobs.lever.co/Qover/a91df316-2f49-48ed-9da4-428c52b8d295): monitoring, incident response, SLIs/SLOs, asynchronous messaging, data persistence, and infrastructure operation.
- [Nscale — systems integration engineering](https://job-boards.greenhouse.io/nscaleoperationsukltd/jobs/4854859101): API error handling, retries, monitoring, integration documentation, dashboards, and support runbooks.

These are a small sample of employer requirements, including experienced roles, used to identify relevant skills. They are not a survey of the whole hiring market.

## Ordered implementation plan

### Milestone 1: make the monitoring state trustworthy

**Priority: highest.** Start here because the central product promise depends on correct state.

Implement:

- A stale/unmonitored state based on the expected check interval and an explicit grace period. Show the last check time in the primary UI.
- Separate liveness, readiness, and scheduler/worker freshness signals. A web process responding is insufficient evidence that monitoring is working.
- Stable logical run IDs created when scheduling work, retained through retries.
- Atomic task claims with a lease or scheduling-slot constraint so overlapping dispatches do not enqueue the same logical check repeatedly.
- Transactional incident updates with a database-enforced invariant allowing one open incident per service.
- Replay-safe orchestration: a previously completed logical check must not repeat incident transitions or alerts.
- Bounded check concurrency, logging of scheduler failures, and a defined retry policy that distinguishes monitor infrastructure errors from genuine provider failures.

Acceptance evidence:

- Replaying a completed job produces one check result and no extra incident-side effects.
- Two concurrent workers cannot create two open incidents for one service.
- A scheduler interval firing while a check is pending does not create a duplicate logical run.
- Killing and restarting a worker recovers or explicitly fails the claimed run without leaving permanently stuck work.
- Paused monitoring changes a formerly healthy service to stale within the documented interval.

### Milestone 2: run the actual architecture safely and repeatably

**Priority: highest, alongside milestone 1.** Use the Compose stack as the test environment.

Implement:

- Alembic migrations and startup/readiness checks for PostgreSQL and Redis.
- A constrained public demo: allow only the simulator target for public mutations, scope example state to a visitor or a clearly defined demo instance, and prevent untrusted arbitrary probing.
- Authentication/authorization for real configuration changes. One protected operator role is enough initially.
- Target validation for any real external probes: validate resolved addresses, cover IPv4/IPv6 and restricted ranges, and disable redirects or revalidate every hop. Add deployment-level egress restrictions where practical.
- Credential references or encrypted stored headers; redact secrets from logs and API responses.
- CI that runs real PostgreSQL/Redis/Celery integration tests, the frontend build, and browser smoke tests. Keep local unit tests fast.

Acceptance evidence:

- A clean clone can start the full stack with documented commands.
- Fresh initialization and upgrading an existing database both succeed.
- Unauthenticated callers cannot mutate real monitoring configuration or probe arbitrary destinations.
- Tests reject private, loopback, link-local, metadata, and redirect-based target escapes without actually contacting those destinations.
- The CI run demonstrates scheduled checks through Beat -> Redis -> worker -> PostgreSQL.

### Milestone 3: make observability match reality

**Priority: high.** An operational dashboard must agree with stored state and worker activity.

Implement:

- A supported way to collect worker counters/histograms, such as worker exporters or an appropriate aggregation design.
- Database-backed incident counts, or another strategy that remains correct across restarts and multiple processes.
- Scheduler heartbeat, overdue checks, queue depth, execution duration, and alert-delivery failures.
- A provisioned Grafana dashboard and actionable alerts for monitoring-system failure.
- Durable notification delivery using an outbox/queue with bounded retries and transition-level deduplication. Define delivery semantics rather than promising exactly-once external notifications.
- An explicit decision on incident recovery when responses are slow, plus tests for the chosen behavior.

Acceptance evidence:

- Worker-produced metrics are visible in Prometheus.
- Restarting the API does not reset the reported count of persisted open incidents.
- Slack being unavailable does not lose the incident; pending notification work survives restart and can retry.
- A screenshot and a short runbook show how to distinguish provider failure from monitor failure.

### Milestone 4: give the project one memorable operational story

**Priority: high after correctness.** Build a coherent example that uses the existing architecture.

Implement:

- A small controlled example application with payment, shipping, and identity dependencies represented by independent synthetic services.
- A reproducible failure campaign: baseline -> expired access -> rate limiting -> slow response -> invalid response -> outage -> recovery.
- A service detail view with check history, the incident timeline, recorded HTTP status, response-validation error, and a short explanation of the detected category.
- Three short architecture decision records: incident thresholds/recovery, job idempotency/claims, and monitoring freshness/observability.
- A troubleshooting runbook with a worked incident example.

Acceptance evidence:

- A recruiter can understand the scenario in under a minute.
- An engineer can reproduce the same incident campaign from a command or browser test.
- An interview walkthrough shows the original failure, the evidence, the relevant design decision, and the recovery.
- Expected diagnoses are deterministic rule-based classifications, not unsupported claims of root-cause inference or automatic repair.

### Milestone 5: measure performance and publish an evidence-backed release

**Priority: medium for initial resume inclusion; high for making it a standout project.** Measurements must follow worker correctness.

Implement:

- A repeatable synthetic workload with declared hardware, worker count, endpoint behavior, interval, sample count, and duration.
- Begin with a proposed 100 synthetic services and two workers; adjust the workload based on observed capacity. These are experiment settings, not achieved scale claims.
- Measure scheduling delay, actual checks per second, API response latency during slow-provider load, detection/recovery delay, and duplicate-job outcomes.
- Optimize the observed bottleneck: database latest-result queries, in-memory overview aggregation, excessive HTTP client creation, or unbounded storage.
- Document retention, maximum expected concurrency, and measured limitations.
- Put the local work into a proper Git checkout, review the tracked diff, exclude databases/dependencies/secrets, run CI, and publish the tested version.
- Verify the hosted demo and API against the release, including startup behavior. Add a short recording or screenshots that remain understandable during hosting cold starts.

Acceptance evidence:

- A checked-in benchmark script/report supports every resume number.
- A before/after result identifies the optimization and workload; no unmeasured business-impact claims.
- The public README, deployed demo, and source all describe the same release.

## Resume-readiness gates

### Suitable to list today

The existing API, failure classification, incident lifecycle, tests, and independent portfolio framing are enough to list this for early-career backend roles. Use accurate language and be prepared to explain the implemented rules and limitations.

### Strong engineering showcase

Complete milestones 1–3, the automated distributed workflow, and a published demonstration. The central claim becomes that monitoring state stays trustworthy through defined failure conditions, with reproducible evidence.

### Strong differentiator

Add the operational case study and measured workload from milestones 4–5. Be able to explain a bug, its failure mechanism, the tradeoff in the fix, and the test that prevents its return.

## Resume wording supported today

- Built a Python/FastAPI API-monitoring application that classifies external-service failures and persists check history and configurable incident opening/recovery transitions.
- Implemented a guided outage/recovery simulator and 20 passing automated tests covering API validation, failure handling, and the monitoring lifecycle; designed a Celery/Redis/PostgreSQL worker deployment with Docker Compose.

The second bullet describes the deployment architecture as designed until its operation is validated. Tailor wording to personal authorship and ensure you can explain every component.

After completing the plan, replace tool-heavy claims with verified behaviors and measured results. Examples of future evidence include one persisted outcome under task replay, successful worker restart recovery, bounded scheduling delay at a documented workload, and usable worker metrics. Do not insert numbers until measured.

## Scope discipline

Keep one primary dashboard and one clear monitoring workflow. The highest-value work is reliable execution, trustworthy state, safe operation, and reproducible proof. Multi-tenancy, a large integration marketplace, Kubernetes deployment, and AI-generated diagnosis can remain later extensions; they do not resolve the current correctness gaps.
