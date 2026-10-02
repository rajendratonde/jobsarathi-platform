"""Generate the eight Phase-1 service skeletons from one template.

Run from the repo root:  python tools/scaffold_services.py
Existing files are only overwritten with --force, so hand-made changes in a
service are never lost by accident.

The skeleton contains Foundation only: configuration, database wiring, the two
v5 platform tables (audit_logs, outbox_events), Alembic, health endpoints and
tests. Business tables are added per v5 in each service's own phase.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# key, package, display name, local port
SERVICES = [
    ("identity", "identity_service", "Identity & Access", 8001),
    ("candidate", "candidate_service", "Candidate & Resume", 8002),
    ("employer", "employer_service", "Employer", 8003),
    ("job", "job_service", "Job", 8004),
    ("application", "application_service", "Application", 8005),
    ("learning", "learning_service", "Learning", 8006),
    ("engagement", "engagement_service", "Engagement", 8007),
    ("reference", "reference_service", "Reference Data", 8008),
]

PYPROJECT = '''[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "js-__KEY__-service"
version = "0.1.0"
description = "JobSarathi __NAME__ service"
requires-python = ">=3.12"
# Installed with --no-deps after the shared libs (see Dockerfile / docs/local-development.md).
dependencies = ["js-core", "js-audit", "js-outbox", "js-integration"]

[tool.setuptools.packages.find]
include = ["__PKG__*"]
'''

INIT = '''"""JobSarathi __NAME__ service. Owns __KEY___db only."""

SERVICE_KEY = "__KEY__"
VERSION = "0.1.0"
'''

CONFIG = '''"""Configuration for the __NAME__ service. All values come from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from js_core.config import DatabaseSettings, ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "__KEY__"


class ServiceDatabaseSettings(DatabaseSettings):
    """__KEY___db, reached only by this service's roles."""

    name: str = "__KEY___db"
    user: str = "__KEY___service_role"
    migration_user: str | None = Field(default="__KEY___migration_role")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_db_settings() -> ServiceDatabaseSettings:
    return ServiceDatabaseSettings()
'''

MODELS = '''"""Tables owned by __KEY___db.

Foundation contains only the two v5 platform tables present in every service
database. Business tables are added exactly as defined in the v5 ERD when the
__NAME__ phase starts; nothing here may reference another service's tables.
"""

from __future__ import annotations

from js_audit import AuditLogMixin
from js_core.db import make_base
from js_outbox import OutboxEventMixin

Base = make_base()


class AuditLog(AuditLogMixin, Base):
    __tablename__ = "audit_logs"


class OutboxEvent(OutboxEventMixin, Base):
    __tablename__ = "outbox_events"
'''

API = '''"""HTTP routes of the __NAME__ service.

Foundation: no business endpoints. Routes are added from the approved OpenAPI
contract in contracts/ when the service's phase starts.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["__KEY__"])
'''

MAIN = '''"""ASGI entry point: uvicorn __PKG__.main:app"""

from __future__ import annotations

import logging
from pathlib import Path

from js_core.app import create_app
from js_core.db import Database
from js_core.migrations import head_revision

from __PKG__ import VERSION
from __PKG__.api import router
from __PKG__.config import get_db_settings, get_settings

SERVICE_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("__PKG__")


def _migrate_on_start() -> None:
    """Local/dev convenience only; refused in production by the settings validator."""
    from alembic import command

    from js_core.migrations import alembic_config

    log.info("RUN_MIGRATIONS_ON_START: upgrading __KEY___db to head")
    command.upgrade(alembic_config(SERVICE_ROOT, get_db_settings().migration_url()), "head")


def build_app():
    settings = get_settings()
    database = Database(get_db_settings())
    return create_app(
        settings=settings, version=VERSION, database=database, routers=[router],
        expected_revision=lambda: head_revision(SERVICE_ROOT),
        on_startup=_migrate_on_start if settings.run_migrations_on_start else None,
    )


app = build_app()
'''

ALEMBIC_INI = '''# Alembic for __KEY___db only. The URL is taken from the service settings
# (migration role) in migrations/env.py, never written here.
[alembic]
script_location = %(here)s/migrations
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s
prepend_sys_path = .
path_separator = os
sqlalchemy.url =

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
'''

ENV_PY = '''"""Alembic environment for __KEY___db (one migration stream per service)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from __PKG__.models import Base

config = context.config
target_metadata = Base.metadata


def _url_and_role() -> tuple[str, str | None]:
    url = config.get_main_option("sqlalchemy.url")
    role = config.attributes.get("runtime_role")
    if not url or role is None:
        from __PKG__.config import get_db_settings
        db = get_db_settings()
        url = url or db.migration_url()
        role = role or db.user
    return url, role


def run_migrations_offline() -> None:
    url, role = _url_and_role()
    config.attributes["runtime_role"] = role
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url, role = _url_and_role()
    config.attributes["runtime_role"] = role
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

MAKO = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''

FIRST_MIGRATION = '''"""Platform tables: audit_logs and outbox_events (v5, identical in every service database)

Revision ID: 0001_platform_tables
Revises:
Create Date: 2026-10-15
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from js_core.migrations import runtime_role_grants_sql

revision = "0001_platform_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(10), server_default=sa.text("'USER'"), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", sa.String(10), server_default=sa.text("'SUCCESS'"), nullable=False),
        sa.Column("before_data", postgresql.JSONB(), nullable=True),
        sa.Column("after_data", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.CheckConstraint("actor_type IN ('USER','SERVICE','SYSTEM')", name="ck_audit_logs_actor_type"),
        sa.CheckConstraint("result IN ('SUCCESS','FAILURE','DENIED')", name="ck_audit_logs_result"),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_user_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_logs_organization", "audit_logs", ["organization_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_logs_occurred_brin", "audit_logs", ["occurred_at"], postgresql_using="brin")

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index("ix_outbox_events_unpublished", "outbox_events", ["occurred_at"],
                    postgresql_where=sa.text("published_at IS NULL"))

    # Runtime role: DML on this database, but audit_logs stays append-only.
    role = context.config.attributes.get("runtime_role")
    if role:
        for statement in runtime_role_grants_sql(role):
            op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    for name in ("ix_audit_logs_occurred_brin", "ix_audit_logs_organization", "ix_audit_logs_actor", "ix_audit_logs_entity"):
        op.drop_index(name, table_name="audit_logs")
    op.drop_table("audit_logs")
'''

CONFTEST = '''"""Test fixtures for the __NAME__ service: a throwaway database per test session."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

SERVICE_ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_PG_ADMIN_URL", "postgresql+psycopg://jobsarathi_admin:local-dev-only@127.0.0.1:5434/postgres")


@pytest.fixture(scope="session")
def database_url() -> str:
    name = f"test___KEY___{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    from alembic import command
    from js_core.migrations import alembic_config

    cfg = alembic_config(SERVICE_ROOT, database_url)
    cfg.attributes["runtime_role"] = ""  # no runtime role in a throwaway database
    command.upgrade(cfg, "head")
    return database_url


@pytest.fixture()
def app_client(migrated: str, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    url = make_url(migrated)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("DB_HOST", url.host)
    monkeypatch.setenv("DB_PORT", str(url.port))
    monkeypatch.setenv("DB_NAME", url.database)
    monkeypatch.setenv("DB_USER", url.username)
    monkeypatch.setenv("DB_PASSWORD", url.password)
    monkeypatch.setenv("DB_SSLMODE", "disable")

    from __PKG__ import config
    config.get_settings.cache_clear()
    config.get_db_settings.cache_clear()
    from __PKG__.main import build_app

    with TestClient(build_app()) as client:
        yield client
'''

TEST_SERVICE = '''"""Foundation tests for the __NAME__ service."""

from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from js_core.migrations import alembic_config

from __PKG__.models import Base
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]

FOUNDATION_TABLES = {"audit_logs", "outbox_events"}


def test_live_and_ready(app_client):
    live = app_client.get("/health/live")
    assert live.status_code == 200 and live.json()["service"] == "__KEY__"
    assert live.headers["x-correlation-id"] and live.headers["x-request-id"]
    ready = app_client.get("/health/ready")
    assert ready.status_code == 200, ready.json()
    assert ready.json()["checks"]["migrations"]["status"] == "ok"


def test_unknown_route_uses_error_model(app_client):
    body = app_client.get("/v1/does-not-exist", headers={"X-Correlation-Id": "test-corr-12345"}).json()
    assert body["status"] == 404 and body["code"] == "NOT_FOUND"
    assert body["correlation_id"] == "test-corr-12345"


def test_migrations_match_models_exactly(migrated):
    engine = create_engine(migrated)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        tables = set(inspect(conn).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert diff == [], diff
    assert tables == FOUNDATION_TABLES


def test_downgrade_and_upgrade_again(migrated):
    cfg = alembic_config(SERVICE_ROOT, migrated)
    cfg.attributes["runtime_role"] = ""
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_only_foundation_tables_and_no_foreign_keys():
    assert set(Base.metadata.tables) == FOUNDATION_TABLES
    for table in Base.metadata.tables.values():
        assert not table.foreign_keys, f"{table.name} has a foreign key"
'''

README = '''# __NAME__ service

Owns `__KEY___db` (roles `__KEY___service_role` runtime, `__KEY___migration_role` migrations).
Local port __PORT__ → container port 8000.

Foundation only: health endpoints, `audit_logs`, `outbox_events`. Business
tables and endpoints come from the v5 ERD and the service's OpenAPI contract
in its own phase.

```bash
# from the repo root, with .venv active and local PostgreSQL running
cd services/__KEY__
alembic upgrade head          # uses DB_* / migration role from the environment
uvicorn __PKG__.main:app --port __PORT__
pytest
```
'''


def render(template: str, key: str, pkg: str, name: str, port: int) -> str:
    return (template.replace("__PKG__", pkg).replace("__KEY__", key)
            .replace("__NAME__", name).replace("__PORT__", str(port)))


def write(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    for key, pkg, name, port in SERVICES:
        base = ROOT / "services" / key
        files = {
            "pyproject.toml": PYPROJECT, f"{pkg}/__init__.py": INIT, f"{pkg}/config.py": CONFIG,
            f"{pkg}/models.py": MODELS, f"{pkg}/api/__init__.py": API, f"{pkg}/main.py": MAIN,
            "alembic.ini": ALEMBIC_INI, "migrations/env.py": ENV_PY, "migrations/script.py.mako": MAKO,
            "migrations/versions/20261015_0001_platform_tables.py": FIRST_MIGRATION,
            "tests/conftest.py": CONFTEST, "tests/test_foundation.py": TEST_SERVICE, "README.md": README,
        }
        for rel, template in files.items():
            write(base / rel, render(template, key, pkg, name, port), args.force)
        print(f"{key:<12} {pkg:<22} :{port}")


if __name__ == "__main__":
    main()
