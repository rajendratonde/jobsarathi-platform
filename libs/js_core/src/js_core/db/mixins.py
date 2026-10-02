"""Column mixins matching the v5 common-column standard (v5 §31).

Only add a mixin where the v5 table definition has those columns:

* ``UUIDPrimaryKeyMixin`` - ``id uuid`` primary key, app-generated UUIDv7
* ``CreatedMixin``        - created_at, created_by
* ``TimestampMixin``      - created_at, created_by, updated_at, updated_by
* ``SoftDeleteMixin``     - deleted_at, deleted_by (only tables classified YES/SPECIAL in v5 §26)
* ``VersionMixin``        - version, used for optimistic locking
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from js_core.ids import uuid7


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class TimestampMixin(CreatedMixin):
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow, server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


def soft_delete_check() -> CheckConstraint:
    """v5 rule for every soft-delete table; include it in the model's ``__table_args__``."""
    return CheckConstraint("deleted_at IS NULL OR deleted_by IS NOT NULL", name="deleted_by_required")


class SoftDeleteMixin:
    """Rows with deleted_at set are hidden from every ORM query by default.

    Read deleted rows only on purpose: ``session.execute(stmt.execution_options(include_deleted=True))``.
    Models using this mixin must add ``soft_delete_check()`` to ``__table_args__``
    (checked by tools/check_architecture.py).
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, actor_id: uuid.UUID) -> None:
        if self.deleted_at is None:
            self.deleted_at = utcnow()
            self.deleted_by = actor_id

    def restore(self) -> None:
        self.deleted_at = None
        self.deleted_by = None


class VersionMixin:
    """``version`` starts at 1 and SQLAlchemy raises StaleDataError (→ 409) on a lost update."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls) -> dict:  # noqa: N805
        return {"version_id_col": cls.version}
