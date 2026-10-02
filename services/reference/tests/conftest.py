"""Test fixtures for the Reference Data service.

One throwaway database and one app per test session. Identity is replaced by two test
doubles with the same contracts: a local signing key (instead of Identity's JWKS) and a
``StubIdentity`` permission provider (instead of the internal authz API). The real HTTP
clients are covered by libs/tests/test_remote_clients.py and the Playwright run.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from js_auth.context import EffectivePermissions, Scope

SERVICE_ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_PG_ADMIN_URL", "postgresql+psycopg://jobsarathi_admin:local-dev-only@127.0.0.1:5434/postgres")


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


def upgrade(url: str, revision: str = "head") -> None:
    from alembic import command

    from js_core.migrations import alembic_config

    cfg = alembic_config(SERVICE_ROOT, url)
    cfg.attributes["runtime_role"] = ""  # no runtime role in a throwaway database
    command.upgrade(cfg, revision)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    name, admin, url = _create_db("test_reference")
    yield url
    _drop_db(name, admin)


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    upgrade(database_url)
    return database_url


@pytest.fixture()
def scratch_database() -> Iterator[str]:
    name, admin, url = _create_db("test_reference_mig")
    yield url
    _drop_db(name, admin)


@pytest.fixture(scope="session")
def db(migrated: str) -> Iterator[Engine]:
    engine = create_engine(migrated)
    yield engine
    engine.dispose()


@dataclass
class Person:
    user_id: uuid.UUID
    headers: dict[str, str] = field(default_factory=dict)


class StubIdentity:
    """Same contract as Identity's /internal/authz: permission code -> scope, plus authz_version."""

    def __init__(self) -> None:
        self.grants: dict[uuid.UUID, dict[str, Scope]] = {}
        self.versions: dict[uuid.UUID, int] = {}
        self.down = False

    def effective(self, user_id: uuid.UUID, organization_id: uuid.UUID | None) -> EffectivePermissions:
        if self.down:
            from js_core.errors import DependencyUnavailable
            raise DependencyUnavailable("Access checks are unavailable. Try again shortly.", code="AUTHZ_UNAVAILABLE")
        return EffectivePermissions(authz_version=self.versions.get(user_id, 1), scopes=dict(self.grants.get(user_id, {})))


class Tokens:
    def __init__(self, ring, identity: StubIdentity) -> None:
        from js_auth import TokenSettings

        self.ring, self.settings, self.identity = ring, TokenSettings(), identity

    def person(self, grants: dict[str, str] | None = None) -> Person:
        from js_auth.tokens import issue_access_token

        user_id = uuid.uuid4()
        self.identity.grants[user_id] = {code: Scope(scope) for code, scope in (grants or {}).items()}
        token, _ = issue_access_token(self.ring, self.settings, user_id=user_id, session_id=uuid.uuid4(),
                                      organization_id=uuid.uuid4(), authz_version=self.identity.versions.get(user_id, 1),
                                      password_change_required=False)
        return Person(user_id, {"Authorization": f"Bearer {token}"})


@pytest.fixture(scope="session")
def identity() -> StubIdentity:
    return StubIdentity()


@pytest.fixture(scope="session")
def app_client(migrated: str, identity: StubIdentity):
    from fastapi.testclient import TestClient

    from js_auth.keys import load_key_ring
    from js_core.config import Environment

    url = make_url(migrated)
    env = {"APP_ENV": "test", "LOG_FORMAT": "text", "LOG_LEVEL": "WARNING", "DB_HOST": url.host,
           "DB_PORT": str(url.port), "DB_NAME": url.database, "DB_USER": url.username, "DB_PASSWORD": url.password,
           "DB_SSLMODE": "disable", "AUTHZ_CACHE_SECONDS": "0"}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    from reference_service import config
    config.get_settings.cache_clear()
    config.get_db_settings.cache_clear()
    from reference_service.main import build_app

    ring = load_key_ring(env=Environment.TEST)
    try:
        with TestClient(build_app(keys=ring, provider=identity)) as client:
            client.ring = ring  # type: ignore[attr-defined]
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
def tokens(app_client, identity) -> Tokens:
    return Tokens(app_client.ring, identity)


EDITOR = {"REFERENCE.EDIT": "ALL", "MAKER_CHECKER.VIEW": "ALL", "AUDIT.VIEW": "ALL"}
CHECKER = {"REFERENCE.APPROVE": "ALL", "MAKER_CHECKER.VIEW": "ALL", "REFERENCE.EDIT": "ALL"}


@pytest.fixture()
def editor(tokens) -> Person:
    return tokens.person(EDITOR)


@pytest.fixture()
def checker(tokens) -> Person:
    return tokens.person(CHECKER)


@pytest.fixture()
def approval_on(db):
    """Switch Maker-Checker on for every list during one test (a data change, as in production)."""
    with db.begin() as conn:
        conn.execute(text("UPDATE approval_policies SET is_enabled = true"))
    yield
    with db.begin() as conn:
        conn.execute(text("UPDATE approval_policies SET is_enabled = false"))
