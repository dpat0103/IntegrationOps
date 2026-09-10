# Release Checklist

Completed in-repo:
- [x] Git hygiene (`.gitignore`, MIT license)
- [x] Backend monitoring engine and deterministic simulator
- [x] Failure taxonomy and structured 429 metadata
- [x] Incident open/recovery lifecycle
- [x] SLO endpoint and error-budget calculation
- [x] Idempotent execution IDs
- [x] SSRF protection for production probing; demo mode is not a blanket private-network bypass
- [x] Encrypted request-header storage when a Fernet key is configured
- [x] Alembic initial migration
- [x] PostgreSQL / Redis / Celery Docker Compose architecture
- [x] Prometheus configuration
- [x] Grafana datasource + dashboard provisioning
- [x] GitHub Actions CI
- [x] Architecture and demo documentation
- [x] 16 automated tests passing
- [x] Fresh Alembic migration validated against an empty SQLite database

External verification before placing a live URL on a resume:
- [x] Run `docker compose up --build` on a machine with Docker and confirm all seven services become healthy.
- [ ] Deploy to the chosen hosting account with managed PostgreSQL/Redis and worker/beat processes.
- [ ] Set a real `INTEGRATION_SECRET_KEY` and never commit it.
- [x] Public demo restricts general writes while keeping the server-controlled simulator usable.
- [ ] Add the final public URL to this README after deployment.
