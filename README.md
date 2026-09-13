# IntegrationOps

A backend-first integration reliability platform for monitoring external APIs, classifying failures, opening/resolving incidents, and exposing operational metrics.

## What it demonstrates

- REST API design with FastAPI
- background health checks and scheduling
- production worker architecture with Celery + Redis
- durable operational history in PostgreSQL / SQLite local fallback
- API failure classification: auth, rate-limit, timeout, network, upstream, response validation
- incident state machine: configurable consecutive-failure and recovery thresholds
- idempotent check execution IDs
- P95 latency and 24-hour availability calculations
- Prometheus metrics + Grafana datasource provisioning
- Docker Compose multi-service architecture
- PyTest coverage of failure and incident behavior
- GitHub Actions CI

## Architecture

```text
                       Next.js / built-in dashboard
                                  |
                               FastAPI
                                  |
                   +--------------+--------------+
                   |                             |
              PostgreSQL                      Redis
          configs/checks/incidents          task broker
                                                 |
                                         Celery workers
                                                 |
                                     external integrations

              FastAPI / workers -> /metrics -> Prometheus -> Grafana
```

The default local mode deliberately avoids infrastructure friction: FastAPI uses SQLite and an in-process async scheduler. The Docker Compose profile switches the exact same monitoring domain logic to PostgreSQL + Redis + Celery workers/beat.

## Fastest local run

The core mode requires only the packages in `requirements-core.txt`.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-core.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open:

- Dashboard: http://localhost:8000
- OpenAPI docs: http://localhost:8000/docs
- Prometheus endpoint: http://localhost:8000/metrics

### Demo flow

1. Click **Create demo integration** on the dashboard.
2. Keep the simulator `Healthy` and run a check.
3. Change the simulator to `401 auth failure`, `429 rate limited`, or `503 upstream failure`.
4. Run three checks. IntegrationOps opens an incident after the third consecutive hard failure.
5. Change the simulator back to `Healthy` and run two checks. The incident resolves.
6. Choose `Malformed payload` to demonstrate JSON contract validation.
7. Choose `High latency` to demonstrate a degraded state without a hard outage.

For the timeout demo, the local demo integration uses a 1500ms timeout while the simulator delays for 4 seconds.

## Production-style Docker stack

```bash
docker compose up --build
```

Services:

- API: `localhost:8000`
- PostgreSQL
- Redis
- Celery worker
- Celery beat scheduler
- Prometheus: `localhost:9090`
- Grafana: `localhost:3001`

In Compose, `TASK_MODE=celery` and `SCHEDULER_ENABLED=false` on the API. Celery Beat dispatches due checks to Redis, and workers execute them independently from web requests.

## Main API

```text
POST   /api/integrations
GET    /api/integrations
PATCH  /api/integrations/{id}
DELETE /api/integrations/{id}
POST   /api/integrations/{id}/check
GET    /api/integrations/{id}/checks
GET    /api/incidents
GET    /api/overview
GET    /api/status
GET    /metrics
```

## Incident policy

Default policy:

- 3 consecutive `FAILED` checks => open incident
- 2 consecutive `HEALTHY` or `DEGRADED` checks => resolve incident
- `DEGRADED` currently represents high latency and does not count as a hard outage

These thresholds are configurable through `FAILURE_THRESHOLD` and `RECOVERY_THRESHOLD`.

## Failure taxonomy

| Failure | Classification |
|---|---|
| 401 / 403 | `AUTHENTICATION_FAILURE` |
| 429 | `RATE_LIMITED` |
| 5xx | `UPSTREAM_FAILURE` |
| Other 4xx | `HTTP_ERROR` |
| timeout | `TIMEOUT` |
| connection / DNS / network | `NETWORK_ERROR` |
| invalid or unexpected JSON | `RESPONSE_VALIDATION_FAILURE` |
| latency over threshold | `HIGH_LATENCY` / `DEGRADED` |

## Tests

```bash
pytest -q
```

The tests cover HTTP failure classification, response validation, idempotent execution IDs, incident open/resolve behavior, CRUD/overview API behavior, and simulator state.

## Thin Next.js frontend

A minimal Next.js 16 / TypeScript frontend is included under `frontend/`. It is intentionally small because the project's portfolio value is in the backend architecture. The built-in dashboard at `/` remains available for the fastest demo with no Node dependency.

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

## Suggested next upgrades

1. Add Alembic migrations rather than `create_all` for production schema changes.
2. Add secure credential references instead of storing integration headers directly.
3. Add per-integration SLO targets and error-budget calculations.
4. Add OpenTelemetry traces across API -> broker -> worker -> upstream check.
5. Add multi-tenant auth only if the project actually needs public users.
