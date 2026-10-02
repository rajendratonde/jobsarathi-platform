# JobSarathi platform

The new JobSarathi backend and frontend, built from the approved design:

* **v5** — *JobSarathi — Detailed ERD & Database Design* (source of truth for every table)
* **v6** — *JobSarathi — Implementation Blueprint*
* **T1** — *JobSarathi — T1 AWS Hosting & Infrastructure Decision* (working baseline)

Status: **Foundation complete. No business functionality yet.** See [docs/foundation.md](docs/foundation.md).

## Stack

React · Python (FastAPI, SQLAlchemy 2, Alembic, Pydantic) · PostgreSQL · eight microservices, one database each.

## Layout

```
libs/            shared Python packages (technical only, no business rules)
  js_core/         config, logging, errors, request context, DB, health, app factory
  js_audit/        audit_logs (v5) + recorder
  js_outbox/       outbox_events (v5) + writer (no broker)
  js_integration/  external providers: email (SMTP), SMS — disabled by default
  tests/           library tests
services/        eight services, each owning one database
  identity/ candidate/ employer/ job/ application/ learning/ engagement/ reference/
frontend/        React (Vite + TypeScript)
contracts/       OpenAPI contracts (written before each service's code)
gateway/         reserved for the API Gateway (product = decision T2)
infrastructure/  local Docker stack and the service image
docs/            foundation guide, local development, decisions, v5 table catalogue
tools/           service scaffold, architecture checks, check runner
```

## Quick start

See [docs/local-development.md](docs/local-development.md).

```bash
cp .env.example .env          # set the passwords
docker compose -f infrastructure/local/docker-compose.yml --env-file .env up -d --build
curl http://127.0.0.1:8001/health/ready
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173
```

Run every check: `bash tools/check_all.sh`
