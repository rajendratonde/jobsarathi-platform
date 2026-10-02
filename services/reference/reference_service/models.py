"""Tables owned by reference_db, exactly as defined in v5 section 19.

Reference lists: states, cities, industries, job_categories, job_roles, skills,
                 education_levels, experience_bands, job_types, work_modes, pay_types,
                 lookup_values
Maker-Checker:   approval_policies, approval_requests, approval_actions (optional per list)
Platform:        audit_logs, outbox_events

v5 classifies every reference table soft delete NO: values are deactivated, never
deleted, and codes are never changed or reused, so other services' stored codes always
resolve. No foreign key leaves reference_db.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Sequence, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from js_approval import ApprovalActionMixin, ApprovalPolicyMixin, ApprovalRequestMixin
from js_audit import AuditLogMixin
from js_core.db import TimestampMixin, UUIDPrimaryKeyMixin, make_base
from js_outbox import OutboxEventMixin

Base = make_base()

APPROVAL_NUMBER_SEQ = Sequence("approval_request_number_seq", metadata=Base.metadata)


def _fk(table: str) -> ForeignKey:
    return ForeignKey(f"{table}.id", ondelete="RESTRICT")


class ReferenceValueMixin(UUIDPrimaryKeyMixin, TimestampMixin):
    """Columns every v5 reference list shares."""

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    name_hi: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class _ActiveSortIndex:
    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (Index(f"ix_{cls.__tablename__}_active_sort", "is_active", "sort_order"),)


class State(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "states"


class City(ReferenceValueMixin, Base):
    __tablename__ = "cities"
    __table_args__ = (
        Index("uq_cities_state_name", "state_id", text("lower(name)"), unique=True),
        Index("ix_cities_state_active", "state_id", "is_active"),
    )
    state_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("states"), nullable=False)


class Industry(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "industries"


class JobCategory(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "job_categories"


class JobRole(ReferenceValueMixin, Base):
    __tablename__ = "job_roles"
    __table_args__ = (Index("ix_job_roles_category", "job_category_id"),)
    job_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("job_categories"),
                                                              nullable=True)


class Skill(ReferenceValueMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        Index("ix_skills_active_sort", "is_active", "sort_order"),
        Index("ix_skills_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )


class EducationLevel(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "education_levels"
    level_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ExperienceBand(ReferenceValueMixin, Base):
    __tablename__ = "experience_bands"
    __table_args__ = (
        CheckConstraint("max_months IS NULL OR max_months > min_months", name="month_range"),
        Index("ix_experience_bands_active_sort", "is_active", "sort_order"),
    )
    min_months: Mapped[int] = mapped_column(Integer, nullable=False)
    max_months: Mapped[int | None] = mapped_column(Integer, nullable=True)


class JobType(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "job_types"


class WorkMode(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "work_modes"


class PayType(_ActiveSortIndex, ReferenceValueMixin, Base):
    __tablename__ = "pay_types"


class LookupValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Small lists that do not justify their own table (v5: optional)."""

    __tablename__ = "lookup_values"
    __table_args__ = (Index("uq_lookup_values_list_code", "list_code", "code", unique=True),)
    list_code: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    name_hi: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


# ------------------------------------------------------------------ Maker-Checker (shared model)
class ApprovalPolicy(ApprovalPolicyMixin, Base):
    __tablename__ = "approval_policies"


class ApprovalRequest(ApprovalRequestMixin, Base):
    __tablename__ = "approval_requests"
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("approval_policies"), nullable=False)


class ApprovalAction(ApprovalActionMixin, Base):
    __tablename__ = "approval_actions"
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("approval_requests"),
                                                           nullable=False)


# ------------------------------------------------------------------ platform tables
class AuditLog(AuditLogMixin, Base):
    __tablename__ = "audit_logs"


class OutboxEvent(OutboxEventMixin, Base):
    __tablename__ = "outbox_events"
