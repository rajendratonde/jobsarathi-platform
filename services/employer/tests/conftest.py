"""Test fixtures for the Employer service: a throwaway database per test session."""

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
    name = f"test_employer_{uuid.uuid4().hex[:8]}"
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

    from employer_service import config
    config.get_settings.cache_clear()
    config.get_db_settings.cache_clear()
    from employer_service.main import build_app

    with TestClient(build_app()) as client:
        yield client
