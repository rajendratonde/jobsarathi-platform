# Foundation

What the Foundation provides, and the rules every later phase builds on.

## Services and databases

| Service | Package | Database | Runtime role | Migration role | Local port |
|---|---|---|---|---|---|
| Identity & Access | `identity_service` | `identity_db` | `identity_service_role` | `identity_migration_role` | 8001 |
| Candidate & Resume | `candidate_service` | `candidate_db` | `candidate_service_role` | `candidate_migration_role` | 8002 |
| Employer | `employer_service` | `employer_db` | `employer_service_role` | `employer_migration_role` | 8003 |
| Job | `job_service` | `job_db` | `job_service_role` | `job_migration_role` | 8004 |
| Application | `application_service` | `application_db` | `application_service_role` | `application_migration_role` | 8005 |
| Learning | `learning_service` | `learning_db` | `learning_service_role` | `learning_migration_role` | 8006 |
| Engagement | `engagement_service` | `engagement_db` | `engagement_service_role` | `engagement_migration_role` | 8007 |
| Reference Data | `reference_service` | `reference_db` | `reference_service_role` | `reference_migration_role` | 8008 |

Each database currently holds only the two v5 platform tables, `audit_logs` and
`outbox_events` (migration `0001_platform_tables`). Business tables are added per v5
in each service's phase.

## Shared libraries (`libs/`)

| Package | Provides |
|---|---|
| `js_core.config` | `ServiceSettings`, `DatabaseSettings`, `Environment`; production guards (no migrate-on-start, no `*` CORS, JSON logs only) |
| `js_core.secrets` | Secret references `env:NAME` / `file:/path`. Cloud secret stores are refused until the store is chosen (T1 TBD) |
| `js_core.logging` | JSON logs with service, env, correlation and request IDs; sensitive keys masked |
| `js_core.middleware` | `X-Correlation-Id` (accepted if safe, else generated) and `X-Request-Id` on every response; one log line per request |
| `js_core.errors` | Error model `{type,status,code,message,errors[],details,correlation_id,timestamp}` and handlers for 400–503; no stack traces in responses |
| `js_core.responses` | `Page[T]`, `page_params` (default 20, max 100), `parse_sort` with an allow-list |
| `js_core.db` | Per-service `make_base()`, mixins (`UUIDPrimaryKeyMixin` UUIDv7, `CreatedMixin`, `TimestampMixin`, `SoftDeleteMixin` + `soft_delete_check()`, `VersionMixin`), `Database`, `transaction()` |
| `js_core.health` | `/health/live` and `/health/ready` (database reachable, schema at Alembic head) |
| `js_core.migrations` | Alembic config helper, head revision, runtime-role grants with append-only audit |
| `js_core.app` | `create_app()` wiring all of the above; docs off in production |
| `js_audit` | `audit_logs` (v5 columns) and `record_audit()` inside the business transaction |
| `js_outbox` | `outbox_events` (v5 columns, E2 not applied) and `add_event()` |
| `js_integration` | Email (disabled · dev_log · generic SMTP) and SMS (disabled · dev_log); off while `MIDDLEWARE_ENABLED=false`; dev sinks refused outside local/development/test |

### Rules the libraries enforce

* **Soft delete:** any model with `SoftDeleteMixin` is hidden from ORM selects by default;
  read deleted rows only with `.execution_options(include_deleted=True)`. Use the mixin
  only on tables v5 classifies YES/SPECIAL, and add `soft_delete_check()`.
* **Versions:** `VersionMixin` makes SQLAlchemy check `version` on every update; a lost
  update raises `StaleDataError`, returned as 409 `VERSION_CONFLICT`.
* **Audit and outbox** rows are added to the same session, so they commit or roll back
  with the business change.
* **Secrets** (database passwords, SMTP password) are `SecretStr`, resolved from
  references, never in `repr`, logs, errors or API responses.

## Guard-rails (`tools/check_architecture.py`)

Fails if a service defines a table or column that is not in the v5 catalogue for its
database, a foreign key leaves its database, soft delete appears where v5 says NO, a
service imports another service, a secret looks hard-coded, or code/config names a
product that belongs to an undecided T2–T6 decision.

## Email (platform capability)

Foundation includes the sending side only: `js_integration.email` with settings for host,
port, username, password **reference**, TLS mode (STARTTLS/SSL/NONE), from email, from
name, reply-to, timeout and enable/disable (`EMAIL_MODE`), plus `describe()` for a safe
admin view and a send that can serve as the "test email" action. No provider is chosen.

**Not in Foundation — needs a decision:** email settings stored in a database, email
templates and email delivery logs need tables that are not in v5. They are listed in
[decisions.md](decisions.md) as a new change requiring explicit approval.

## What Foundation deliberately does not contain

No authentication or authorization (Identity phase, T4), no RBAC tables, no
Maker-Checker package (`js_approval`, built with Identity), no business tables or
endpoints, no API Gateway (T2), no CI pipeline (T3), no AWS resources or IaC, no message
broker, no AI.
