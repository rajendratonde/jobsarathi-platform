"""Tables owned by identity_db, exactly as defined in v5 (+ approved E1).

Authentication: users, auth_identities, otp_challenges, user_sessions
Organizations:  organizations, organization_memberships
RBAC:           modules, resources, actions, permissions, roles, role_permissions, user_role_assignments
Maker-Checker:  approval_policies, approval_requests, approval_actions
Platform:       audit_logs, outbox_events

Soft delete only where v5 §26 classifies YES/SPECIAL. role_permissions rows are
hard-deleted (audited); user_role_assignments are revoked, never deleted.
No foreign key leaves identity_db.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from js_approval import ApprovalActionMixin, ApprovalPolicyMixin, ApprovalRequestMixin
from js_audit import AuditLogMixin
from js_core.db import (
    CreatedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
    make_base,
    soft_delete_check,
)
from js_outbox import OutboxEventMixin

Base = make_base()
ZERO_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"

ORGANIZATION_CODE_SEQ = Sequence("organization_code_seq", metadata=Base.metadata)
APPROVAL_NUMBER_SEQ = Sequence("approval_request_number_seq", metadata=Base.metadata)


def _fk(table: str) -> ForeignKey:
    return ForeignKey(f"{table}.id", ondelete="RESTRICT")


# ------------------------------------------------------------------ organizations
class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("organization_type IN ('PLATFORM','EMPLOYER','COLLEGE','PARTNER')", name="organization_type"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED')", name="status"),
        CheckConstraint("is_platform = (organization_type = 'PLATFORM')", name="platform_type"),
        soft_delete_check(),
        Index("uq_organizations_single_platform", "is_platform", unique=True, postgresql_where=text("is_platform")),
        Index("ix_organizations_type_status", "organization_type", "status", postgresql_where=text("deleted_at IS NULL")),
    )
    organization_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_platform: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'ACTIVE'"), default="ACTIVE")


# ------------------------------------------------------------------ users and authentication
class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','ACTIVE','DISABLED','LOCKED')", name="status"),
        soft_delete_check(),
        Index("ix_users_status", "status", postgresql_where=text("deleted_at IS NULL")),
    )
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'ACTIVE'"), default="ACTIVE")
    authz_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"), default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        CheckConstraint("identity_type IN ('MOBILE_OTP','EMAIL_PASSWORD','SSO')", name="identity_type"),
        CheckConstraint("(identity_type = 'EMAIL_PASSWORD') = (password_hash IS NOT NULL)", name="password_only_for_email"),
        CheckConstraint("identity_type <> 'SSO' OR provider_code IS NOT NULL", name="sso_provider"),
        soft_delete_check(),
        Index("uq_auth_identities_identifier", "identity_type", "identifier", text("COALESCE(provider_code, '')"),
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_auth_identities_user", "user_id", postgresql_where=text("deleted_at IS NULL")),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users"), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    identifier: Mapped[str] = mapped_column(String(254), nullable=False)
    provider_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # E1 (approved): a temporary password must be changed at the next sign-in.
    password_change_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"),
                                                           default=False)


class OtpChallenge(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint("purpose IN ('LOGIN','SIGNUP','VERIFY_MOBILE')", name="purpose"),
        CheckConstraint("status IN ('PENDING','VERIFIED','EXPIRED','LOCKED','CANCELLED')", name="status"),
        CheckConstraint("delivery_status IN ('NOT_SENT','SENT','FAILED','DISABLED')", name="delivery_status"),
        CheckConstraint("attempt_count <= max_attempts", name="attempts"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        CheckConstraint("(status = 'VERIFIED') = (verified_at IS NOT NULL)", name="verified_at"),
        Index("ix_otp_challenges_mobile_recent", "mobile_hash", text("created_at DESC")),
        Index("ix_otp_challenges_pending", "status", "expires_at", postgresql_where=text("status = 'PENDING'")),
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    mobile_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    mobile_last4: Mapped[str] = mapped_column(CHAR(4), nullable=False)
    auth_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("auth_identities"), nullable=True)
    code_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"), default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("5"), default=5)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'PENDING'"), default="PENDING")
    delivery_status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'NOT_SENT'"),
                                                 default="NOT_SENT")
    delivery_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requested_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index("ix_user_sessions_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users"), nullable=False)
    auth_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("auth_identities"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    active_organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("organizations"),
                                                                     nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)


class OrganizationMembership(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint("status IN ('INVITED','ACTIVE','SUSPENDED','ENDED')", name="status"),
        soft_delete_check(),
        Index("uq_organization_memberships_org_user", "organization_id", "user_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_organization_memberships_user_active", "user_id",
              postgresql_where=text("deleted_at IS NULL AND status = 'ACTIVE'")),
        Index("ix_organization_memberships_org_status", "organization_id", "status",
              postgresql_where=text("deleted_at IS NULL")),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("organizations"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users"), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'ACTIVE'"), default="ACTIVE")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ------------------------------------------------------------------ RBAC catalogue
class Module(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "modules"
    __table_args__ = (
        soft_delete_check(),
        Index("uq_modules_code", "module_code", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )
    module_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class Resource(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("resource_code ~ '^[A-Z][A-Z_]*$'", name="resource_code"),
        soft_delete_check(),
        Index("uq_resources_code", "resource_code", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_resources_module", "module_id"),
    )
    module_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("modules"), nullable=False)
    resource_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class Action(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint("action_code ~ '^[A-Z][A-Z_]*$'", name="action_code"),
        soft_delete_check(),
        Index("uq_actions_code", "action_code", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )
    action_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (
        CheckConstraint(r"permission_code ~ '^[A-Z][A-Z_]*\.[A-Z][A-Z_]*$'", name="permission_code"),
        soft_delete_check(),
        Index("uq_permissions_resource_action", "resource_id", "action_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("uq_permissions_code", "permission_code", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_permissions_resource", "resource_id"),
        Index("ix_permissions_action", "action_id"),
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("resources"), nullable=False)
    action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("actions"), nullable=False)
    permission_code: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    declared_by_service: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','ACTIVE','DISABLED')", name="status"),
        CheckConstraint("NOT (is_system AND deleted_at IS NOT NULL)", name="system_not_deleted"),
        soft_delete_check(),
        Index("uq_roles_owner_name", text(f"COALESCE(owner_organization_id, {ZERO_UUID})"), text("lower(name)"),
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_roles_code", "role_code", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_roles_status", "status", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_roles_owner", "owner_organization_id"),
    )
    role_code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("organizations"),
                                                                    nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'DRAFT'"), default="DRAFT")


class RolePermission(CreatedMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("ix_role_permissions_permission", "permission_id"),)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("roles"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("permissions"), primary_key=True)


class UserRoleAssignment(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "user_role_assignments"
    __table_args__ = (
        CheckConstraint("scope_type IN ('OWN','ORGANIZATION','CITY','REGION','ALL')", name="scope_type"),
        CheckConstraint("status IN ('PENDING_APPROVAL','ACTIVE','REVOKED')", name="status"),
        CheckConstraint("scope_type NOT IN ('ORGANIZATION','ALL') OR membership_id IS NOT NULL",
                        name="scope_needs_membership"),
        CheckConstraint("(status = 'REVOKED') = (revoked_at IS NOT NULL)", name="revoked_at"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity"),
        Index("uq_user_role_assignments_live", "user_id", "role_id", text(f"COALESCE(membership_id, {ZERO_UUID})"),
              unique=True, postgresql_where=text("status <> 'REVOKED'")),
        Index("ix_user_role_assignments_user_active", "user_id", postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_user_role_assignments_membership", "membership_id"),
        Index("ix_user_role_assignments_role", "role_id"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("roles"), nullable=False)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("organization_memberships"),
                                                            nullable=True)
    scope_type: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ACTIVE'"), default="ACTIVE")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


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
