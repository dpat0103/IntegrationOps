# Deployment and release checklist

## Tested local configurations

- One FastAPI process, SQLite, bounded local scheduler.
- Docker Compose: PostgreSQL, Redis, Celery Beat, a two-process worker, FastAPI, Prometheus, and Grafana.

Compose binds published ports to localhost. The database and broker are internal services. Migrations complete before API/worker startup. Use the supplied health checks and `docker compose up --build -d --wait`.

## Hosting configuration

Configure these values through the hosting service's secret settings, never Git:

- `ENVIRONMENT=production`
- `OPERATOR_TOKEN`: randomly generated, at least 32 characters.
- `DEMO_SESSION_SECRET`: stable random value, at least 32 characters.
- `COOKIE_SECURE=true`
- `DEMO_MODE=true` for the public simulated demonstration.
- `INTEGRATION_SECRET_KEY` if storing real request headers.
- `SLACK_WEBHOOK_URL` only if real incident notifications are required.

Production startup fails closed if the required operator/session/cookie configuration is missing.

A simple Render-style process can build with `pip install -r requirements-core.txt` and start with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Local mode needs `TASK_MODE=local` and `SCHEDULER_ENABLED=true`.

SQLite on an ephemeral hosting filesystem loses history on replacement/restart. It is suitable only for a disposable public demo. Use durable PostgreSQL for monitoring that needs retained state, and provision the broker/worker/scheduler separately if using worker mode. Creating hosting resources can incur charges; use the account's chosen infrastructure and budget.

## Existing database

Back up the database before upgrading. Run `python -m app.migrate`; local automatic migration uses the same revision path. Inspect and resolve any pre-existing duplicate open incidents or duplicate transition records before adding the uniqueness constraints.

Legacy plaintext headers are not used by probes. Configure the encryption key, inspect `python -m scripts.encrypt_legacy_headers`, then explicitly apply the conversion with `--apply`.

## Network and access controls

The HTTP transport pins a validated DNS result, rejects non-public destinations, preserves TLS hostname verification, disables redirects, ignores proxy environment variables, and bounds response size and duration.

Apply deployment-level egress restrictions as an additional control. Keep metrics/Grafana internal or protect them at the ingress layer. Restrict operator-token distribution and establish a rotation procedure. The public demo is constrained but is not a commercial account system.

## Release gates

1. Backend tests and compile checks pass.
2. Browser tests and responsive inspection pass.
3. Frontend production build passes.
4. Distributed scheduled/manual checks, replay, and PostgreSQL concurrency tests pass.
5. Worker interruption and API restart behavior are documented.
6. README, About page, and measured evidence describe the same behavior.
7. Review the Git diff and CI checks before updating the production branch.
8. After deployment, verify readiness, the About/GitHub links, and the outage/recovery workflow on the hosted URL.

The developer preview and Docker validation stack use disposable databases and temporary secrets. Stop the validation stack after testing; keep the evidence files.
