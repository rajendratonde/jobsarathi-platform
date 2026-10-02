"""Test fixtures for the Identity & Access service.

One throwaway database and one app per test session. Signing and OTP keys are fixed
for the session so tokens stay valid across tests. Tests create their own users,
organizations and mobile numbers, so they do not depend on each other.
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from js_auth.keys import generate_private_key_pem

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # identity_test_helpers (pytest importlib mode)
ADMIN_URL = os.environ.get("TEST_PG_ADMIN_URL", "postgresql+psycopg://jobsarathi_admin:local-dev-only@127.0.0.1:5434/postgres")
BOOTSTRAP_PASSWORD = "FirstAdmin2026"


def _create_db(prefix: str) -> tuple[str, Engine, str]:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    return name, admin, make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


def _drop_db(name: str, admin: Engine) -> None:
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _upgrade(url: str) -> None:
    from alembic import command

    from js_core.migrations import alembic_config

    cfg = alembic_config(SERVICE_ROOT, url)
    cfg.attributes["runtime_role"] = ""  # no runtime role in a throwaway database
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    name, admin, url = _create_db("test_identity")
    yield url
    _drop_db(name, admin)


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    _upgrade(database_url)
    return database_url


@pytest.fixture()
def scratch_database() -> Iterator[str]:
    """A separate database for destructive migration tests."""
    name, admin, url = _create_db("test_identity_mig")
    yield url
    _drop_db(name, admin)


@pytest.fixture(scope="session")
def db(migrated: str) -> Iterator[Engine]:
    """Direct database access for arranging time-based cases and checking stored values."""
    engine = create_engine(migrated)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def employer_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def app_client(migrated: str, employer_key):
    from fastapi.testclient import TestClient

    url = make_url(migrated)
    public_pem = employer_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    env = {
        "APP_ENV": "test", "LOG_FORMAT": "text", "LOG_LEVEL": "WARNING",
        "DB_HOST": url.host, "DB_PORT": str(url.port), "DB_NAME": url.database, "DB_USER": url.username,
        "DB_PASSWORD": url.password, "DB_SSLMODE": "disable",
        "DB_MIGRATION_USER": url.username, "DB_MIGRATION_PASSWORD": url.password,
        "JWT_PRIVATE_KEY_REF": "env:TEST_JWT_PRIVATE_KEY", "TEST_JWT_PRIVATE_KEY": generate_private_key_pem(),
        "OTP_SECRET_REF": "env:TEST_OTP_SECRET", "TEST_OTP_SECRET": uuid.uuid4().hex + uuid.uuid4().hex,
        "OTP_DEV_SINK": "true", "REFRESH_COOKIE_SECURE": "false", "OTP_RESEND_SECONDS": "0",
        "SERVICE_PUBLIC_KEYS": json.dumps({"employer": "env:TEST_EMPLOYER_PUBLIC_KEY"}),
        "TEST_EMPLOYER_PUBLIC_KEY": public_pem,
        "BOOTSTRAP_ADMIN_PASSWORD_REF": "env:TEST_BOOTSTRAP_PASSWORD", "TEST_BOOTSTRAP_PASSWORD": BOOTSTRAP_PASSWORD,
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    from identity_service import config
    config.get_settings.cache_clear()
    config.get_db_settings.cache_clear()
    from identity_service.main import build_app

    try:
        with TestClient(build_app()) as client:
            yield client
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.get_settings.cache_clear()
        config.get_db_settings.cache_clear()


@pytest.fixture(scope="session")
def api(app_client, db):
    from identity_test_helpers import Api
    return Api(app_client, db)


@pytest.fixture(scope="session")
def world(api, employer_key):
    """Two platform administrators (maker and checker) and two employer organizations."""
    return api.build_world(employer_key, BOOTSTRAP_PASSWORD)


@pytest.fixture()
def mobile() -> str:
    """A fresh Indian mobile number per test (OTP rate limits are per number)."""
    return f"9{random.randint(100_000_000, 999_999_999)}"
