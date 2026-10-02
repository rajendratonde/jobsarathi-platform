# Decisions and open items

## Approved and applied

| Item | Status | Where |
|---|---|---|
| T1 working baseline: AWS, PostgreSQL, 8 service databases, EC2 + Docker, RDS target, S3, HTTPS | Working baseline | Nothing AWS-specific is hard-coded; all via configuration |
| Python stack: FastAPI, SQLAlchemy 2, Alembic, Pydantic; React | Approved | Foundation |
| Middleware disabled initially (`MIDDLEWARE_ENABLED=false`) | Approved | `js_core.config`, `js_integration` |
| No message broker; outbox only | Approved | `js_outbox` |
| E1 — `auth_identities.password_change_required` | Approved, implemented | `identity_db` migration `0002_identity_access` |
| Email data model: `email_settings`, `email_templates`, `email_delivery_logs` | Approved 2026-10-02, implemented (data model only) | `engagement_db` migration `0002_email_tables`; catalogue `applied_changes` |

## Deferred

| Item | Why |
|---|---|
| E2 — outbox `status` / `failed_at` | Only needed when a broker relay exists |

## Still open (do not decide in code)

| Decision | Effect on Foundation |
|---|---|
| T2 API Gateway | `gateway/` is empty; services are reached directly on local ports |
| T3 Git host / CI/CD | Local git only, no remote; `tools/check_all.sh` is what CI will run |
| T4 Authentication | Not decided as a product. Identity implements the in-house design from v5 (Argon2id passwords, OTP, ES256 tokens, sessions); an external IdP can replace the sign-in part later without changing RBAC |
| T5 Middleware / providers (SMS, email provider) | Email is generic SMTP; SMS has no provider |
| T6 Other | — |
| Secret store product (T1 TBD) | `env:` / `file:` references only; cloud stores refused |
| Q2 OTP visibility for testers | Decided for development only: `OTP_DEV_SINK=true` logs the code and serves `GET /v1/dev/otp`; refused by settings outside local/development/test. Production never exposes codes |
| Q7 Which roles are privileged | `USER_ROLE_ASSIGNMENT` approval policy is seeded **off**; switching it on is a data change. Per-role "privileged" selection would need a new column — NEW CHANGE if wanted |

## Email data model — owner decision (approved tables, 2026-10-02)

**Owner: Engagement (`engagement_db`).** Each of the eight services was considered:

| Service | Fit | Why not / why |
|---|---|---|
| Identity & Access | No | Sends OTP/password mails, but outbound mail is not identity. Keeping SMTP egress and template editing out of the most security-critical service keeps its attack surface and blast radius small |
| Candidate, Employer, Job, Application, Learning | No | Each *triggers* emails; owning the channel in any one of them would make the others depend on it for a cross-cutting concern |
| Reference Data | No | Static lists; delivery logs are high-volume operational data |
| **Engagement** | **Yes** | Already the service for outbound/inbound user communication (enquiries, reports) and has no synchronous dependencies. Other services publish events (outbox) or call one Engagement API to send; templates and delivery history live with the channel |

Rules implemented in the data model:

* `email_settings.smtp_password_ref` holds a **secret reference** (`env:NAME` / `file:/path`); a CHECK constraint refuses anything else, and no column can hold a password. `EmailSettings.public_view()` reports only `smtp_password_set` / `smtp_username_set`.
* `email_templates` soft delete YES; one live template per (code, language).
* `email_delivery_logs`: masked recipient + hash, template code, status, provider reference, error code; **no subject, no body, no secret**; idempotent on (source_service, source_reference).
* No provider is chosen (T5): delivery modes are DISABLED / DEV_LOG / SMTP (generic).
* Still open: retention for `email_delivery_logs` (proposal 12 months); the Engagement send API comes with the Engagement phase.

## Identity & Access — implementation notes

* Authorization is data: permission codes and scopes from `identity_db`; no role code or name is checked in code (enforced by `tools/check_architecture.py`).
* Any access change raises `users.authz_version`; tokens carrying an older `av` get `401 TOKEN_STALE` and the client refreshes.
* Identity resolves permissions on every request (`AUTHZ_CACHE_SECONDS=0`); other services may cache up to 60 s keyed by `authz_version`.
* `permissions` has no `version` column in v5; Maker-Checker uses a fingerprint of `updated_at`/`is_active`/`deleted_at` instead (no schema change).
* Permissions Identity enforces itself (`declared_by_service = 'identity'`) cannot be disabled or deleted, so access management cannot lock itself out. The system role `PLATFORM_ADMIN` can gain permissions but not lose them, and cannot be renamed, disabled or deleted.
* The last member of an organization holding `ROLE.ASSIGN` cannot be suspended, removed or lose that assignment.
* `POST /internal/organizations` has no stored idempotency key (v5 has no column for it); callers must not blindly retry. Adding one would be a NEW CHANGE.

## Reference Data — implementation notes (2026-10-02)

* Tables exactly as v5 section 19: eleven lists + `lookup_values` + the shared Maker-Checker tables. Soft delete is NO
  everywhere (v5): values are deactivated, never deleted, and codes never change or get reused.
* v5 reference tables have no `version` column. Optimistic locking and the Maker-Checker version check use a
  fingerprint of `updated_at`/`is_active` (same approach as Identity `permissions`). No schema change.
* Maker-Checker: one approval policy per list, seeded **off** (v5 "off by default"); maker `REFERENCE.EDIT`, checker
  `REFERENCE.APPROVE` with ALL scope. Changes are proposals applied on approval; a CREATE proposal carries version 0
  and is valid only while the record does not exist (shared engine extension, no schema change).
* `REFERENCE.EDIT` / `REFERENCE.APPROVE` are rows in identity_db (Identity data migration 0004), granted to the
  protected system role. No role is named in Reference code.
* Reference verifies tokens with Identity's JWKS and asks Identity's internal authz API for permissions with its own
  service token (cached 60 s by authz_version; Identity unreachable = 503, fail closed). Local keys come from
  `tools/local_keys.py`.
* Public read `GET /v1/reference/{list}` needs no sign-in, returns codes not ids, and supports ETag / 304.
  Children of an inactive parent are hidden.
* `libs/js_reference` is the client cache other services will use (ETag revalidation, last good copy, 503 with no
  copy). Not yet wired into another service: those services are not started.
