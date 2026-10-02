"""Database access for one service.

* one engine per service database, runtime credentials only
* sessions hide soft-deleted rows unless asked otherwise
* ``transaction()`` wraps a use case: commit on success, rollback on error
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria

from js_core.config import DatabaseSettings
from js_core.db.mixins import SoftDeleteMixin

log = logging.getLogger("js_core.db")


def _hide_soft_deleted(state: ORMExecuteState) -> None:
    if (state.is_select and not state.is_column_load and not state.is_relationship_load
            and not state.execution_options.get("include_deleted", False)):
        state.statement = state.statement.options(
            with_loader_criteria(SoftDeleteMixin, lambda cls: cls.deleted_at.is_(None), include_aliases=True))


def install_soft_delete_filter(factory: sessionmaker) -> None:
    event.listen(factory, "do_orm_execute", _hide_soft_deleted)


class Database:
    def __init__(self, settings: DatabaseSettings, *, echo: bool = False) -> None:
        self.settings = settings
        self.engine: Engine = create_engine(
            settings.runtime_url(),
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_seconds,
            pool_pre_ping=True,
            echo=echo,
            connect_args={"options": f"-c statement_timeout={settings.statement_timeout_ms} -c timezone=UTC",
                          "application_name": settings.user,
                          "connect_timeout": settings.connect_timeout_seconds},
        )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        install_soft_delete_filter(self.session_factory)

    def session(self) -> Session:
        return self.session_factory()

    def dependency(self) -> Iterator[Session]:
        """FastAPI dependency yielding a session that is always closed."""
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def current_revision(self) -> str | None:
        with self.engine.connect() as conn:
            try:
                return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            except Exception:  # table missing = never migrated
                conn.rollback()
                return None

    def dispose(self) -> None:
        self.engine.dispose()


@contextmanager
def transaction(session: Session) -> Iterator[Session]:
    """One use case = one transaction. Audit and outbox rows join the same transaction."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
