"""Foundation tests for the Engagement service."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from engagement_service.models import Base
from js_core.migrations import alembic_config

SERVICE_ROOT = Path(__file__).resolve().parents[1]

FOUNDATION_TABLES = {"audit_logs", "outbox_events"}
EMAIL_TABLES = {"email_settings", "email_templates", "email_delivery_logs"}  # approved 2026-10-02
ENGAGEMENT_TABLES = FOUNDATION_TABLES | EMAIL_TABLES


def test_live_and_ready(app_client):
    live = app_client.get("/health/live")
    assert live.status_code == 200 and live.json()["service"] == "engagement"
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
    assert tables == ENGAGEMENT_TABLES


def test_downgrade_and_upgrade_again(migrated):
    cfg = alembic_config(SERVICE_ROOT, migrated)
    cfg.attributes["runtime_role"] = ""
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_only_approved_tables_and_no_foreign_keys_leave_the_database():
    assert set(Base.metadata.tables) == ENGAGEMENT_TABLES
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.name in ENGAGEMENT_TABLES, f"{table.name} -> {fk.target_fullname}"
