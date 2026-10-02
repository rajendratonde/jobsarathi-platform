"""Shared-library tests. Database tests use a throwaway database on the local PostgreSQL."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get("TEST_PG_ADMIN_URL", "postgresql+psycopg://jobsarathi_admin:local-dev-only@127.0.0.1:5434/postgres")


@pytest.fixture(scope="session")
def db_url() -> str:
    name = f"test_libs_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_settings(db_url: str):
    from js_core.config import DatabaseSettings

    url = make_url(db_url)
    return DatabaseSettings(host=url.host, port=url.port, name=url.database, user=url.username,
                            password=url.password, sslmode="disable")
