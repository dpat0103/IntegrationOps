# Demo Flow

A repeatable demo is built into the application so an interview does not depend on a real third-party outage.

1. Start local mode with `make run` or the full stack with `docker compose up --build`.
2. Open `http://localhost:8000` and click **Create demo integration**. The browser does not submit a private endpoint; the server assigns the correct demo URL for the current environment.
3. Run a healthy check.
4. Set simulator mode to **503 upstream failure** and run three checks.
5. Confirm one incident opens with cause `UPSTREAM_FAILURE`.
6. Return the simulator to **Healthy** and run two checks.
7. Confirm the same incident resolves.
8. Switch to **429 rate limited** and inspect the captured `Retry-After` metadata in `/docs`.
9. Open `/metrics` or Grafana in the Docker stack to inspect operational telemetry.

The simulator also provides 401 authentication, high-latency, and malformed-response scenarios. In Docker, the server stores `http://api:8000/simulator/status` for the controlled demo so the Celery worker can resolve the API service across the Compose network. Arbitrary user-created private targets remain blocked.
