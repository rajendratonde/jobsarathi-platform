# Job service

Owns `job_db` (roles `job_service_role` runtime, `job_migration_role` migrations).
Local port 8004 → container port 8000.

Foundation only: health endpoints, `audit_logs`, `outbox_events`. Business
tables and endpoints come from the v5 ERD and the service's OpenAPI contract
in its own phase.

```bash
# from the repo root, with .venv active and local PostgreSQL running
cd services/job
alembic upgrade head          # uses DB_* / migration role from the environment
uvicorn job_service.main:app --port 8004
pytest
```
