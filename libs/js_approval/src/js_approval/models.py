"""The three v5 approval tables, identical in every service that uses Maker-Checker."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from js_core.db.mixins import TimestampMixin, VersionMixin
from js_core.ids import uuid7

ZERO_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"


class ApprovalPolicyMixin(TimestampMixin, VersionMixin):
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    maker_permission_code: Mapped[str] = mapped_column(String(120), nullable=False)
    checker_permission_code: Mapped[str] = mapped_column(String(120), nullable=False)
    required_approvals: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"), default=1)

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (
            CheckConstraint("required_approvals BETWEEN 1 AND 3", name="required_approvals"),
            Index("uq_approval_policies_entity_org", "entity_type", text(f"COALESCE(organization_id, {ZERO_UUID})"),
                  unique=True),
        )


class ApprovalRequestMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    request_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    proposed_changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    maker_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    maker_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'PENDING'"), default="PENDING")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # policy_id is declared by the concrete model (it needs the service's own FK target).

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (
            CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','WITHDRAWN','SUPERSEDED')", name="status"),
            CheckConstraint("decided_by IS NULL OR decided_by <> maker_user_id", name="four_eyes"),
            CheckConstraint("decided_by IS NULL OR subject_user_id IS NULL OR decided_by <> subject_user_id",
                            name="not_own_access"),
            CheckConstraint("(status IN ('APPROVED','REJECTED')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
                            name="decision_recorded"),
            CheckConstraint("status <> 'REJECTED' OR length(trim(decision_reason)) >= 5", name="rejection_reason"),
            Index("uq_approval_requests_one_pending", "entity_type", "entity_id", unique=True,
                  postgresql_where=text("status = 'PENDING'")),
            Index("ix_approval_requests_inbox", "organization_id", "submitted_at",
                  postgresql_where=text("status = 'PENDING'")),
            Index("ix_approval_requests_maker", "maker_user_id", text("submitted_at DESC")),
            Index("ix_approval_requests_entity", "entity_type", "entity_id", text("submitted_at DESC")),
        )


class ApprovalActionMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    action: Mapped[str] = mapped_column(String(15), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    acting_organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # approval_request_id is declared by the concrete model.

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (
            CheckConstraint("action IN ('SUBMITTED','APPROVED','REJECTED','WITHDRAWN','SUPERSEDED','COMMENTED')",
                            name="action"),
            Index("ix_approval_actions_request", "approval_request_id", "acted_at"),
        )
