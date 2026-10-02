"""Alembic environment for employer_db (one migration stream per service)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from employer_service.models import Base

config = context.config
target_metadata = Base.metadata


def _url_and_role() -> tuple[str, str | None]:
    url = config.get_main_option("sqlalchemy.url")
    role = config.attributes.get("runtime_role")
    if not url or role is None:
        from employer_service.config import get_db_settings
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
