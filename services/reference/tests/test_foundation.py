"""Foundation regression and schema tests for the Reference Data service."""

from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from js_core.migrations import alembic_config
from reference_service.models import Base

SERVICE_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = Path(__file__).resolve().parents[3] / "docs" / "erd" / "v5-table-catalogue.json"
REFERENCE_TABLES = {
    "states", "cities", "industries", "job_categories", "job_roles", "skills", "education_levels",
    "experience_bands", "job_types", "work_modes", "pay_types", "lookup_values",
    "approval_policies", "approval_requests", "approval_actions", "audit_logs", "outbox_events",
}


def test_live_and_ready(app_client):
    live = app_client.get("/health/live")
    assert live.status_code == 200 and live.json()["service"] == "reference"
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
        extensions = {r[0] for r in conn.execute(text("SELECT extname FROM pg_extension"))}
    engine.dispose()
    assert diff == [], diff
    assert tables == REFERENCE_TABLES
    assert "pg_trgm" in extensions


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
    command.downgrade(cfg, "0001_platform_tables")
    command.upgrade(cfg, "head")


def test_tables_and_columns_match_the_v5_catalogue():
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))["databases"]["reference_db"]["tables"]
    assert set(Base.metadata.tables) == REFERENCE_TABLES == set(catalogue)
    for name, table in Base.metadata.tables.items():
        v5 = {c["name"]: c for c in catalogue[name]["columns"]}
        assert {c.name for c in table.columns} == set(v5), name
        for column in table.columns:
            assert column.nullable == v5[column.name]["nullable"], f"{name}.{column.name} nullability"
        assert catalogue[name]["soft_delete"] == "NO" and "deleted_at" not in table.columns


def test_foreign_keys_stay_inside_reference_db():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.name in REFERENCE_TABLES and fk.ondelete == "RESTRICT"


def test_seed_lists_and_policies_off(db):
    with db.connect() as conn:
        counts = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in (
            "states", "cities", "industries", "job_categories", "job_roles", "skills", "education_levels",
            "experience_bands", "job_types", "work_modes", "pay_types")}
        policies = conn.execute(text("SELECT count(*), bool_or(is_enabled) FROM approval_policies")).one()
    assert counts["states"] == 36 and all(counts.values()), counts
    assert policies == (12, False)  # one per list, all off by default (v5)
