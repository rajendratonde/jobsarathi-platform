"""``audit_logs`` exactly as defined in v5 §25 (identical in all 8 service databases).

Columns: id, occurred_at, actor_user_id, actor_type, organization_id, action,
entity_type, entity_id, result, before_data, after_data, metadata,
correlation_id, ip_address, user_agent.

No updated_* and no soft-delete columns: audit rows are append-only, and the
runtime role is granted INSERT + SELECT only (see each service's migration).
No FK to the audited entity, so the row outlives it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from js_core.ids import uuid7

ACTOR_TYPES = ("USER", "SERVICE", "SYSTEM")
RESULTS = ("SUCCESS", "FAILURE", "DENIED")


class AuditLogMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'USER'"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'SUCCESS'"))
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # "metadata" is reserved on declarative classes, so the attribute is metadata_.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (
            CheckConstraint("actor_type IN ('USER','SERVICE','SYSTEM')", name="actor_type"),
            CheckConstraint("result IN ('SUCCESS','FAILURE','DENIED')", name="result"),
            Index("ix_audit_logs_entity", "entity_type", "entity_id", text("occurred_at DESC")),
            Index("ix_audit_logs_actor", "actor_user_id", text("occurred_at DESC")),
            Index("ix_audit_logs_organization", "organization_id", text("occurred_at DESC")),
            Index("ix_audit_logs_occurred_brin", "occurred_at", postgresql_using="brin"),
        )
