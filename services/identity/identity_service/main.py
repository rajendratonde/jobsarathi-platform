"""ASGI entry point: uvicorn identity_service.main:app"""

from __future__ import annotations

import logging
from pathlib import Path

from identity_service import VERSION
from identity_service.api import build_router, well_known
from identity_service.config import get_db_settings, get_settings
from identity_service.runtime import build_runtime
from js_core.app import create_app
from js_core.db import Database
from js_core.migrations import head_revision

SERVICE_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("identity_service")


def _migrate_on_start() -> None:
    """Local/dev convenience only; refused in production by the settings validator."""
    from alembic import command

    from js_core.migrations import alembic_config

    log.info("RUN_MIGRATIONS_ON_START: upgrading identity_db to head")
    command.upgrade(alembic_config(SERVICE_ROOT, get_db_settings().migration_url()), "head")


def build_app():
    settings = get_settings()
    database = Database(get_db_settings())
    app = create_app(
        settings=settings, version=VERSION, database=database,
        routers=[build_router(dev_sink=settings.otp_dev_sink), well_known],
        expected_revision=lambda: head_revision(SERVICE_ROOT),
        on_startup=_migrate_on_start if settings.run_migrations_on_start else None,
    )
    app.state.runtime = build_runtime(settings, database)
    return app


app = build_app()
