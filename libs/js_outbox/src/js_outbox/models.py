"""``outbox_events`` exactly as defined in v5 (all 8 service databases).

Columns: id, aggregate_type, aggregate_id, event_type, event_version, payload,
organization_id, occurred_at, published_at, attempts, last_error.

The deferred change E2 (status / failed_at for a broker relay) is deliberately
NOT applied: there is no broker in Phase 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from js_core.ids import uuid7


class OutboxEventMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"), default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (
            Index("ix_outbox_events_unpublished", "occurred_at", postgresql_where=text("published_at IS NULL")),
        )
