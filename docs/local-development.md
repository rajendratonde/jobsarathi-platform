# Local development

Everything runs on your machine; no AWS account is needed.

## Prerequisites

* Docker with Compose v2
* Python 3.12+ (the images use 3.12)
* Node.js 20+

## 1. Configuration

```bash
cp .env.example .env
```

Set `PG_ADMIN_PASSWORD` and `LOCAL_DB_PASSWORD`, and the same admin password in
`TEST_PG_ADMIN_URL`. `.env` is git-ignored. Use `127.0.0.1`, not `localhost`: on
Windows `localhost` may resolve to IPv6 and hang.

## 2. Database and services in Docker

```bash
docker compose -f infrastructure/local/docker-compose.yml --env-file .env up -d --build
```

* PostgreSQL 16 on `127.0.0.1:5434` with eight databases (`identity_db` … `reference_db`).
* For each database: `<svc>_migration_role` owns the schema, `<svc>_service_role` is the
  runtime login with data rights only. No role can connect to another service's database.
  `audit_logs` is append-only for runtime roles.
* Services on `127.0.0.1:8001`–`8008` (identity, candidate, employer, job, application,
  learning, engagement, reference). Locally they run their migrations on start
  (`RUN_MIGRATIONS_ON_START=true`, refused in production).

Check: `curl http://127.0.0.1:8004/health/ready`

## 3. Python outside Docker (for development and tests)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e libs/js_core -e libs/js_audit -e libs/js_outbox -e libs/js_integration
for s in identity candidate employer job application learning engagement reference; do
  .venv/Scripts/python -m pip install --no-deps -e services/$s; done
.venv/Scripts/python -m pip install pytest httpx ruff
```

Run one service against the Docker database:

```bash
cd services/job
export DB_HOST=127.0.0.1 DB_PORT=5434 DB_SSLMODE=disable DB_PASSWORD=env:LOCAL_DB_PASSWORD DB_MIGRATION_PASSWORD=env:LOCAL_DB_PASSWORD LOG_FORMAT=text
alembic upgrade head
uvicorn job_service.main:app --port 8004
```

## 4. React

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 — the System status page shows all 8 services
```

The dev server forwards `/svc/<service>` to the local service ports. That is a local
convenience only; it is not the API Gateway (decision T2).

## 5. Checks

```bash
bash tools/check_all.sh
```

Runs lint, the architecture check, the library tests, all eight service test suites
and the React tests and build. Tests create and drop their own throwaway databases.

## Adding things later

* **A table:** add it to the service's `models.py` exactly as in `docs/erd/v5-table-catalogue.json`,
  then `alembic revision --autogenerate -m "..."` in that service and review the file.
  `tools/check_architecture.py` rejects tables or columns that are not in v5.
* **A service file change across all services:** edit `tools/scaffold_services.py` and
  run it with `--force` only for files you have not customised.
