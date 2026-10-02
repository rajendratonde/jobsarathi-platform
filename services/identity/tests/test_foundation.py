"""Foundation regression tests for the Identity & Access service."""

from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from identity_service.models import Base
from js_core.migrations import alembic_config

SERVICE_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = Path(__file__).resolve().parents[3] / "docs" / "erd" / "v5-table-catalogue.json"

IDENTITY_TABLES = {
    "users", "auth_identities", "otp_challenges", "user_sessions", "organizations", "organization_memberships",
    "modules", "resources", "actions", "permissions", "roles", "role_permissions", "user_role_assignments",
    "approval_policies", "approval_requests", "approval_actions", "audit_logs", "outbox_events",
}


def test_live_and_ready(app_client):
    live = app_client.get("/health/live")
    assert live.status_code == 200 and live.json()["service"] == "identity"
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
    assert tables == IDENTITY_TABLES


def test_downgrade_to_base_and_upgrade_again(scratch_database):
    cfg = alembic_config(SERVICE_ROOT, scratch_database)
    cfg.attributes["runtime_role"] = ""
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(scratch_database)
    with engine.connect() as conn:
        assert set(inspect(conn).get_table_names()) - {"alembic_version"} == set()
        assert conn.execute(text("SELECT count(*) FROM pg_sequences WHERE schemaname = 'public'")).scalar() == 0
    engine.dispose()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001_platform_tables")  # step back over identity only
    command.upgrade(cfg, "head")


def test_only_identity_tables_from_the_v5_catalogue():
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    assert set(Base.metadata.tables) == IDENTITY_TABLES
    assert IDENTITY_TABLES == set(catalogue["databases"]["identity_db"]["tables"])


def test_foreign_keys_stay_inside_identity_db():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.name in IDENTITY_TABLES, f"{table.name} -> {fk.target_fullname}"
            assert fk.ondelete == "RESTRICT"


def test_seed_is_data_not_code(db):
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM organizations WHERE is_platform")).scalar() == 1
        policies = dict(conn.execute(text("SELECT entity_type, is_enabled FROM approval_policies")).all())
    assert policies == {"ROLE": True, "ROLE_PERMISSIONS": True, "PERMISSION": True, "USER_ROLE_ASSIGNMENT": False}
