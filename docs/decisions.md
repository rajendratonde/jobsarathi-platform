# Decisions and open items

## Approved and applied

| Item | Status | Where |
|---|---|---|
| T1 working baseline: AWS, PostgreSQL, 8 service databases, EC2 + Docker, RDS target, S3, HTTPS | Working baseline | Nothing AWS-specific is hard-coded; all via configuration |
| Python stack: FastAPI, SQLAlchemy 2, Alembic, Pydantic; React | Approved | Foundation |
| Middleware disabled initially (`MIDDLEWARE_ENABLED=false`) | Approved | `js_core.config`, `js_integration` |
| No message broker; outbox only | Approved | `js_outbox` |
| E1 — `auth_identities.password_change_required` | Approved | Recorded in `docs/erd/v5-table-catalogue.json`; the table itself is created in the Identity phase |

## Deferred

| Item | Why |
|---|---|
| E2 — outbox `status` / `failed_at` | Only needed when a broker relay exists |

## Still open (do not decide in code)

| Decision | Effect on Foundation |
|---|---|
| T2 API Gateway | `gateway/` is empty; services are reached directly on local ports |
| T3 Git host / CI/CD | Local git only, no remote; `tools/check_all.sh` is what CI will run |
| T4 Authentication | No auth in Foundation |
| T5 Middleware / providers (SMS, email provider) | Email is generic SMTP; SMS has no provider |
| T6 Other | — |
| Secret store product (T1 TBD) | `env:` / `file:` references only; cloud stores refused |
| Q2 OTP visibility for testers | SMS dev sink logs only the last 4 digits; OTP codes are an Identity-phase decision |

## NEW CHANGE — REQUIRES EXPLICIT APPROVAL

**Email settings, templates and delivery logs as database tables.** The brief requires
email templates and delivery logs, which need tables v5 does not have. Proposal for
approval (not implemented):

| Proposed table | Owner (proposal) | Notes |
|---|---|---|
| `email_settings` | Engagement | One active configuration; holds the SMTP **secret reference**, never the password |
| `email_templates` | Engagement | Code, subject, body, status; soft delete YES |
| `email_delivery_logs` | Engagement | Recipient (masked), template, status, provider reference, error code; no body, no secret; retention to decide |

Other services would ask Engagement to send an email through its API instead of holding
SMTP settings themselves. Owner service and retention need sign-off before the tables are
added to v5.
