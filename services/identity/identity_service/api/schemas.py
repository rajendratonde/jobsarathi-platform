"""Request and response bodies. Responses list their fields explicitly: password hashes,
OTP hashes, refresh-token hashes and mobile hashes have no field here, so they cannot leak."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from identity_service.security import mask_email, mask_mobile


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ auth
class PasswordLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class OtpRequestIn(BaseModel):
    mobile: str = Field(min_length=10, max_length=20)
    purpose: str = "LOGIN"


class OtpRequestOut(BaseModel):
    challenge_id: uuid.UUID
    expires_at: datetime
    resend_after_seconds: int
    sent_to: str


class OtpVerifyIn(BaseModel):
    challenge_id: uuid.UUID
    mobile: str = Field(min_length=10, max_length=20)
    code: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class SwitchOrganizationIn(BaseModel):
    organization_id: uuid.UUID


class UserBrief(Out):
    id: uuid.UUID
    display_name: str
    status: str


class OrganizationBrief(Out):
    id: uuid.UUID
    organization_code: str
    name: str
    organization_type: str
    is_platform: bool
    status: str


class MyOrganization(BaseModel):
    organization: OrganizationBrief
    membership_id: uuid.UUID
    membership_status: str
    roles: list[str]


class TokenOut(BaseModel):
    """The refresh token travels only in the httpOnly cookie, never in this body."""
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - the scheme name, not a secret
    expires_at: int
    password_change_required: bool
    user: UserBrief
    active_organization_id: uuid.UUID | None
    organizations: list[MyOrganization] = []


class PermissionsOut(BaseModel):
    organization_id: uuid.UUID | None
    authz_version: int
    roles: list[str]
    permissions: dict[str, str]  # code -> scope


class SwitchOut(BaseModel):
    token: TokenOut
    permissions: PermissionsOut


class IdentityOut(BaseModel):
    identity_type: str
    identifier: str  # masked
    verified: bool
    is_primary: bool

    @classmethod
    def of(cls, identity: Any) -> IdentityOut:
        if identity.identity_type == "EMAIL_PASSWORD":
            shown = mask_email(identity.identifier)
        elif identity.identity_type == "MOBILE_OTP":
            shown = mask_mobile(identity.identifier)
        else:
            shown = identity.provider_code or "SSO"
        return cls(identity_type=identity.identity_type, identifier=shown, verified=identity.verified_at is not None,
                   is_primary=identity.is_primary)


class MeOut(BaseModel):
    user: UserBrief
    active_organization: OrganizationBrief | None
    authz_version: int
    password_change_required: bool
    identities: list[IdentityOut]
    last_login_at: datetime | None


# ------------------------------------------------------------------ users and organizations
class UserOut(Out):
    id: uuid.UUID
    display_name: str
    status: str
    authz_version: int
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class UserDetailOut(UserOut):
    identities: list[IdentityOut] = []
    memberships: list[dict[str, Any]] = []


class UserCreateIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    organization_id: uuid.UUID | None = None


class UserCreatedOut(BaseModel):
    user: UserOut
    membership_id: uuid.UUID
    temporary_password: str = Field(description="Shown once. The user must change it at first sign-in.")


class UserUpdateIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=150)
    version: int | None = None


class UserStatusIn(BaseModel):
    status: str = Field(pattern=r"^(ACTIVE|DISABLED|UNLOCK)$")
    reason: str | None = Field(default=None, max_length=300)


class TemporaryPasswordOut(BaseModel):
    temporary_password: str


class OrganizationOut(Out):
    id: uuid.UUID
    organization_code: str
    name: str
    organization_type: str
    is_platform: bool
    status: str
    created_at: datetime
    version: int


class StatusIn(BaseModel):
    status: str = Field(min_length=3, max_length=20)
    version: int | None = None


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    user: UserBrief
    status: str
    joined_at: datetime | None
    version: int


class MemberAddIn(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    mobile: str | None = Field(default=None, max_length=20)


class InternalOrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    organization_type: str = "EMPLOYER"
    owner_user_id: uuid.UUID


class InternalOrganizationOut(BaseModel):
    organization_id: uuid.UUID
    organization_code: str
    membership_id: uuid.UUID


# ------------------------------------------------------------------ RBAC
class RoleOut(Out):
    id: uuid.UUID
    role_code: str
    name: str
    description: str | None
    owner_organization_id: uuid.UUID | None
    is_system: bool
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class RoleDetailOut(RoleOut):
    permission_ids: list[uuid.UUID] = []
    permission_codes: list[str] = []
    holders: int = 0
    pending_request: dict[str, Any] | None = None


class RoleCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    role_code: str | None = Field(default=None, max_length=60)
    permission_ids: list[uuid.UUID] = []
    owner_organization_id: uuid.UUID | None = None


class RoleUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    version: int | None = None


class RolePermissionsIn(BaseModel):
    permission_ids: list[uuid.UUID]
    version: int | None = None


class VersionIn(BaseModel):
    version: int | None = None


class ApprovalBrief(Out):
    id: uuid.UUID
    request_number: str
    status: str


class ChangeOut(BaseModel):
    status: str  # APPLIED | PENDING_APPROVAL | UNCHANGED
    approval_request: ApprovalBrief | None = None
    entity_id: uuid.UUID


class PermissionOut(BaseModel):
    id: uuid.UUID
    permission_code: str
    description: str | None
    module_code: str
    resource_code: str
    action_code: str
    is_active: bool
    is_enforced: bool
    declared_by_service: str | None
    version: int


class PermissionCreateIn(BaseModel):
    resource_id: uuid.UUID
    action_id: uuid.UUID
    description: str | None = Field(default=None, max_length=1000)


class PermissionStatusIn(BaseModel):
    is_active: bool


class ModuleOut(Out):
    id: uuid.UUID
    module_code: str
    name: str
    description: str | None
    sort_order: int
    is_active: bool


class ModuleIn(BaseModel):
    module_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,49}$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    sort_order: int = 0


class ResourceOut(Out):
    id: uuid.UUID
    module_id: uuid.UUID
    resource_code: str
    name: str
    description: str | None
    is_active: bool


class ResourceIn(BaseModel):
    module_id: uuid.UUID
    resource_code: str = Field(pattern=r"^[A-Z][A-Z_]{1,49}$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class ActionOut(Out):
    id: uuid.UUID
    action_code: str
    name: str
    is_active: bool


class ActionIn(BaseModel):
    action_code: str = Field(pattern=r"^[A-Z][A-Z_]{1,49}$")
    name: str = Field(min_length=2, max_length=120)


class CatalogueUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class AssignmentOut(BaseModel):
    id: uuid.UUID
    role: dict[str, Any]
    membership_id: uuid.UUID | None
    organization: dict[str, Any] | None
    scope_type: str
    status: str
    valid_from: datetime
    valid_until: datetime | None
    revoked_at: datetime | None
    version: int


class AssignIn(BaseModel):
    role_id: uuid.UUID
    membership_id: uuid.UUID | None = None
    scope_type: str = "ORGANIZATION"
    valid_until: datetime | None = None


class RevokeIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class DeclareIn(BaseModel):
    codes: list[str] = Field(max_length=1000)


class DeclareOut(BaseModel):
    declared: list[str]
    unknown: list[str]


# ------------------------------------------------------------------ approvals and audit
class ApprovalActionOut(Out):
    action: str
    actor_user_id: uuid.UUID
    reviewed_version: int | None
    comment: str | None
    acted_at: datetime


class ApprovalOut(Out):
    id: uuid.UUID
    request_number: str
    entity_type: str
    entity_id: uuid.UUID
    entity_version: int
    action_type: str
    organization_id: uuid.UUID | None
    subject_user_id: uuid.UUID | None
    proposed_changes: dict[str, Any] | None
    change_summary: str | None
    maker_user_id: uuid.UUID
    maker_comment: str | None
    submitted_at: datetime
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None


class ApprovalDetailOut(ApprovalOut):
    actions: list[ApprovalActionOut] = []
    can_decide: bool = False
    can_withdraw: bool = False


class DecideIn(BaseModel):
    reviewed_version: int
    comment: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    reviewed_version: int
    reason: str = Field(min_length=1, max_length=1000)


class AuditOut(Out):
    id: uuid.UUID
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    actor_type: str
    organization_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    result: str
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    correlation_id: str | None
