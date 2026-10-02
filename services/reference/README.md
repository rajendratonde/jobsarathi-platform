# Reference Data service

Owns `reference_db` (roles `reference_service_role` runtime, `reference_migration_role` migrations).
Local port 8008 → container port 8000. Single source of truth for shared master lists; other
services never read `reference_db`: they call the read API (or use `libs/js_reference`).

| Area | What it does |
|---|---|
| Lists (v5 §19) | states, cities, industries, job_categories, job_roles, skills, education_levels, experience_bands, job_types, work_modes, pay_types, lookup_values |
| Rules | no delete (deactivate); codes never change or get reused; city names unique per state; children of an inactive parent are hidden and cannot be added |
| Public read | `GET /v1/reference/{list}` (no sign-in, ETag / 304, codes not ids); `cities?state=`, `job_roles?category=`, `skills?q=` (trigram index) |
| Admin | `/v1/admin/reference/{list}` create / edit / (de)activate; `REFERENCE.EDIT` with ALL scope |
| Maker-Checker | per-list approval policy, seeded off; checker `REFERENCE.APPROVE`; proposals applied on approval; stale versions superseded |
| Auth | tokens verified with Identity's JWKS; permissions from Identity's internal authz API with this service's token |
| Audit / outbox | every change audited; `ReferenceValueChanged` events |

```bash
# from the repo root, with .venv active and local PostgreSQL running
cd services/reference
alembic upgrade head          # 0001 platform, 0002 lists + pg_trgm, 0003 seed (lists, policies off)
IDENTITY_URL=http://127.0.0.1:8001 SERVICE_PRIVATE_KEY_REF=file:../../infrastructure/local/secrets/reference_service.pem \
  uvicorn reference_service.main:app --port 8008
pytest
```
