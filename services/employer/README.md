# Employer service

Owns `employer_db` (roles `employer_service_role` runtime, `employer_migration_role` migrations).
Local port 8003 → container port 8000.

Foundation only: health endpoints, `audit_logs`, `outbox_events`. Business
tables and endpoints come from the v5 ERD and the service's OpenAPI contract
in its own phase.

```bash
# from the repo root, with .venv active and local PostgreSQL running
cd services/employer
alembic upgrade head          # uses DB_* / migration role from the environment
uvicorn employer_service.main:app --port 8003
pytest
```
