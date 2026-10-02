# Identity & Access service

Owns `identity_db` (roles `identity_service_role` runtime, `identity_migration_role` migrations).
Local port 8001 → container port 8000. Tables: the 16 v5 identity tables (with E1
`auth_identities.password_change_required`) plus `audit_logs` and `outbox_events`.

| Area | What it does |
|---|---|
| Sign-in | Email + password (Argon2id, lockout after 5 failures for 15 min); mobile OTP (HMAC-hashed codes, 5 min expiry, 5 attempts, 3 per 15 min / 10 per day per number) |
| Temporary passwords (E1) | Admin-created users and admin resets must change the password before anything except `/me`, `/auth/password/change`, `/auth/logout` |
| Sessions | ES256 access token (15 min: `sub sid org av pcr`); refresh token in an httpOnly cookie, stored only as SHA-256, rotated on every refresh |
| Organizations | Multi-organization users; the session holds the active organization (`/me/organization/switch`) |
| RBAC | Modules → resources × actions → permissions → roles → assignments with scope OWN / ORGANIZATION / ALL (CITY, REGION stored but inactive). All data; nothing hard-coded |
| Maker-Checker | Roles, role permissions, permissions (policies on); role assignments (policy seeded off, Q7). Four-eyes and own-access rules in code **and** CHECK constraints; stale versions are SUPERSEDED |
| Audit | Sign-in, OTP, user, membership, role, permission, assignment and approval actions; never credentials or codes |

```bash
# from the repo root, with .venv active and local PostgreSQL running
cd services/identity
alembic upgrade head          # 0001 platform, 0002 identity tables, 0003 seed (platform org, catalogue, roles, policies)
BOOTSTRAP_ADMIN_PASSWORD_REF=env:FIRST_ADMIN_PASSWORD FIRST_ADMIN_PASSWORD='...' \
  python -m identity_service.bootstrap --email you@example.com --name "You" --role-code PLATFORM_ADMIN
OTP_DEV_SINK=true REFRESH_COOKIE_SECURE=false uvicorn identity_service.main:app --port 8001
pytest
```

API: `/v1/auth/*`, `/v1/me*`, `/v1/organizations*`, `/v1/users*`, `/v1/roles*`, `/v1/permissions*`,
`/v1/modules|resources|actions`, `/v1/rbac/matrix`, `/v1/approvals*`, `/v1/audit-logs`,
`/v1/internal/*` (service tokens), `/.well-known/jwks.json`. OpenAPI at `/docs` outside production.
