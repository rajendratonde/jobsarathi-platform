"""ASGI entry point: uvicorn reference_service.main:app"""

from __future__ import annotations

import logging
from pathlib import Path

from js_core.app import create_app
from js_core.db import Database
from js_core.migrations import head_revision
from reference_service import VERSION
from reference_service.api import build_router
from reference_service.config import get_db_settings, get_settings
from reference_service.runtime import build_runtime

SERVICE_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("reference_service")


def _migrate_on_start() -> None:
    """Local/dev convenience only; refused in production by the settings validator."""
    from alembic import command

    from js_core.migrations import alembic_config

    log.info("RUN_MIGRATIONS_ON_START: upgrading reference_db to head")
    command.upgrade(alembic_config(SERVICE_ROOT, get_db_settings().migration_url()), "head")


def build_app(**overrides):
    """``overrides`` (keys, provider) let tests replace the calls to Identity."""
    settings = get_settings()
    database = Database(get_db_settings())
    app = create_app(
        settings=settings, version=VERSION, database=database, routers=[build_router()],
        expected_revision=lambda: head_revision(SERVICE_ROOT),
        on_startup=_migrate_on_start if settings.run_migrations_on_start else None,
    )
    app.state.runtime = build_runtime(settings, database, **overrides)
    return app


app = build_app()
