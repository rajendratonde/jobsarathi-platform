"""Users, organizations, memberships and role assignments."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from js_auth.context import Authorized, Scope
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from identity_service.approvals import activate_assignment, assignment_snapshot, revoke_assignment
from identity_service.authz import bump_authz, members_of, organization_holders
from identity_service.common import (
    audit,
    check_version,
    event,
    get_or_404,
    require_all_scope,
    require_organization,
)
from identity_service.models import (
    AuthIdentity,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
    UserSession,
)
from identity_service.runtime import Runtime
from identity_service.security import hash_password, mask_email, normalize_mobile, temporary_password
from identity_service.services.rbac import ChangeResult, _submit_or_apply
from js_audit import ActorType, AuditResult
from js_core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed

# The permission that manages access in an organization. Removing its last holder would
# lock the organization out, so that is refused. A permission code, never a role name.
ACCESS_ADMIN_PERMISSION = "ROLE.ASSIGN"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not _EMAIL.match(email) or len(email) > 254:
        raise ValidationFailed(errors=[FieldError(field="email", code="INVALID_EMAIL",
                                                  message="Enter a valid email address.")])
    return email


def _revoke_sessions(session: Session, user_id: uuid.UUID, reason: str) -> int:
    count = 0
    for s in session.scalars(select(UserSession).where(UserSession.user_id == user_id,
                                                       UserSession.revoked_at.is_(None))):
        s.revoked_at, s.revoked_reason = _now(), reason
        count += 1
    return count


# ------------------------------------------------------------------ visibility
def _shares_active_org(session: Session, caller: Authorized, user_id: uuid.UUID) -> bool:
    if caller.auth.organization_id is None:
        return False
    return session.scalar(select(OrganizationMembership.id).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.organization_id == caller.auth.organization_id)) is not None


def visible_user(session: Session, caller: Authorized, user_id: uuid.UUID) -> User:
    user = get_or_404(session, User, user_id, label="User")
    if caller.scope is Scope.ALL:
        return user
    if caller.scope is Scope.ORGANIZATION and _shares_active_org(session, caller, user_id):
        return user
    if caller.scope is Scope.OWN and user_id == caller.auth.user_id:
        return user
    raise NotFound("User not found.")  # do not reveal users outside the caller's reach


def user_query(caller: Authorized, q: str | None, status: str | None):
    stmt = select(User)
    if caller.scope is Scope.ORGANIZATION:
        stmt = stmt.where(User.id.in_(select(OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id == caller.auth.organization_id)))
    elif caller.scope is Scope.OWN:
        stmt = stmt.where(User.id == caller.auth.user_id)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.display_name).like(like), User.id.in_(
            select(AuthIdentity.user_id).where(func.lower(AuthIdentity.identifier).like(like)))))
    return stmt


# ------------------------------------------------------------------ users
def create_user(session: Session, caller: Authorized, *, display_name: str, email: str,
                organization_id: uuid.UUID | None) -> tuple[User, OrganizationMembership, str]:
    org_id = organization_id or caller.auth.organization_id
    if org_id is None:
        raise ValidationFailed(errors=[FieldError(field="organization_id", code="REQUIRED",
                                                  message="Choose the organization the user belongs to.")])
    require_organization(caller, org_id)
    org = get_or_404(session, Organization, org_id, label="Organization")
    if org.status != "ACTIVE":
        raise Conflict("This organization is suspended.", code="ORGANIZATION_SUSPENDED")
    email = normalize_email(email)
    if session.scalar(select(AuthIdentity.id).where(AuthIdentity.identity_type == "EMAIL_PASSWORD",
                                                    AuthIdentity.identifier == email)):
        raise Conflict("A user with this email already exists.", code="IDENTITY_EXISTS")
    actor = caller.auth.user_id
    password = temporary_password()
    user = User(display_name=display_name.strip(), status="ACTIVE", created_by=actor, updated_by=actor)
    session.add(user)
    session.flush()
    session.add(AuthIdentity(user_id=user.id, identity_type="EMAIL_PASSWORD", identifier=email,
                             password_hash=hash_password(password), is_primary=True, password_change_required=True,
                             created_by=actor, updated_by=actor))
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, status="ACTIVE", joined_at=_now(),
                                        created_by=actor, updated_by=actor)
    session.add(membership)
    session.flush()
    audit(session, action="USER.CREATED", entity_type="USER", entity_id=user.id, actor=actor, organization_id=org.id,
          after={"display_name": user.display_name, "email": mask_email(email), "identity_type": "EMAIL_PASSWORD",
                 "temporary_credential_issued": True})
    audit(session, action="MEMBERSHIP.CREATED", entity_type="ORGANIZATION_MEMBERSHIP", entity_id=membership.id,
          actor=actor, organization_id=org.id, after={"user_id": user.id, "status": "ACTIVE"})
    event(session, aggregate_type="USER", aggregate_id=user.id, event_type="UserCreated",
          payload={"user_id": user.id, "organization_id": org.id}, organization_id=org.id)
    return user, membership, password


def update_user(session: Session, caller: Authorized, user_id: uuid.UUID, version: int | None,
                display_name: str) -> User:
    user = visible_user(session, caller, user_id)
    check_version(user, version)
    before = {"display_name": user.display_name}
    user.display_name, user.updated_by = display_name.strip(), caller.auth.user_id
    session.flush()
    audit(session, action="USER.UPDATED", entity_type="USER", entity_id=user.id, actor=caller.auth.user_id,
          organization_id=caller.auth.organization_id, before=before, after={"display_name": user.display_name})
    return user


def set_user_status(session: Session, caller: Authorized, user_id: uuid.UUID, status: str,
                    reason: str | None) -> User:
    require_all_scope(caller)
    user = get_or_404(session, User, user_id, label="User")
    if user.id == caller.auth.user_id:
        raise ValidationFailed("You cannot change your own status.", code="SELF_STATUS_CHANGE")
    before = {"status": user.status}
    if status == "UNLOCK":
        for identity in session.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)):
            identity.failed_attempts, identity.locked_until = 0, None
        if user.status == "LOCKED":
            user.status = "ACTIVE"
    elif status in {"ACTIVE", "DISABLED"}:
        user.status = status
    else:
        raise ValidationFailed(errors=[FieldError(field="status", code="INVALID",
                                                  message="Use ACTIVE, DISABLED or UNLOCK.")])
    user.updated_by = caller.auth.user_id
    ended = _revoke_sessions(session, user.id, "USER_DISABLED") if user.status == "DISABLED" else 0
    session.flush()
    bump_authz(session, [user.id])
    audit(session, action="USER.STATUS_CHANGED", entity_type="USER", entity_id=user.id, actor=caller.auth.user_id,
          before=before, after={"status": user.status}, metadata={"reason": reason, "sessions_ended": ended,
                                                                   "requested": status})
    event(session, aggregate_type="USER", aggregate_id=user.id, event_type="UserStatusChanged",
          payload={"user_id": user.id, "status": user.status})
    return user


def reset_password(session: Session, caller: Authorized, user_id: uuid.UUID) -> str:
    user = visible_user(session, caller, user_id)
    if user.id == caller.auth.user_id:
        raise ValidationFailed("Use 'change password' for your own account.", code="SELF_RESET")
    identity = session.scalar(select(AuthIdentity).where(AuthIdentity.user_id == user.id,
                                                         AuthIdentity.identity_type == "EMAIL_PASSWORD"))
    if identity is None:
        raise ValidationFailed("This user signs in with a mobile code, not a password.", code="NO_PASSWORD_IDENTITY")
    password = temporary_password()
    identity.password_hash = hash_password(password)
    identity.password_change_required = True
    identity.failed_attempts, identity.locked_until = 0, None
    identity.updated_by = caller.auth.user_id
    ended = _revoke_sessions(session, user.id, "PASSWORD_RESET")
    audit(session, action="USER.PASSWORD_RESET", entity_type="USER", entity_id=user.id, actor=caller.auth.user_id,
          organization_id=caller.auth.organization_id,
          metadata={"temporary_credential_issued": True, "sessions_ended": ended})
    return password


# ------------------------------------------------------------------ organizations
def organization_query(caller: Authorized, q: str | None, organization_type: str | None, status: str | None):
    stmt = select(Organization)
    if caller.scope is not Scope.ALL:
        stmt = stmt.where(Organization.id == caller.auth.organization_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Organization.name).like(like),
                              func.lower(Organization.organization_code).like(like)))
    if organization_type:
        stmt = stmt.where(Organization.organization_type == organization_type)
    if status:
        stmt = stmt.where(Organization.status == status)
    return stmt


def visible_organization(session: Session, caller: Authorized, organization_id: uuid.UUID) -> Organization:
    org = get_or_404(session, Organization, organization_id, label="Organization")
    if not caller.allows_organization(org.id):
        raise NotFound("Organization not found.")
    return org


def create_organization(session: Session, *, name: str, organization_type: str, owner_user_id: uuid.UUID,
                        actor_service: str) -> tuple[Organization, OrganizationMembership]:
    if organization_type not in {"EMPLOYER", "COLLEGE", "PARTNER"}:
        raise ValidationFailed(errors=[FieldError(field="organization_type", code="INVALID",
                                                  message="Use EMPLOYER, COLLEGE or PARTNER.")])
    owner = get_or_404(session, User, owner_user_id, label="User")
    number = session.execute(select(func.nextval("organization_code_seq"))).scalar_one()
    org = Organization(organization_code=f"ORG-{number:06d}", name=name.strip(), organization_type=organization_type,
                       is_platform=False, status="ACTIVE")
    session.add(org)
    session.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=owner.id, status="ACTIVE", joined_at=_now())
    session.add(membership)
    session.flush()
    audit(session, action="ORGANIZATION.CREATED", entity_type="ORGANIZATION", entity_id=org.id,
          organization_id=org.id, actor_type=ActorType.SERVICE,
          after={"organization_code": org.organization_code, "name": org.name, "type": organization_type,
                 "owner_user_id": owner.id}, metadata={"service": actor_service})
    event(session, aggregate_type="ORGANIZATION", aggregate_id=org.id, event_type="OrganizationCreated",
          payload={"organization_id": org.id, "organization_type": organization_type, "owner_user_id": owner.id},
          organization_id=org.id)
    bump_authz(session, [owner.id])
    return org, membership


def set_organization_status(session: Session, caller: Authorized, organization_id: uuid.UUID, version: int | None,
                            status: str) -> Organization:
    require_all_scope(caller)
    org = get_or_404(session, Organization, organization_id, label="Organization")
    check_version(org, version)
    if org.is_platform:
        raise ValidationFailed("The platform organization cannot be suspended.", code="PLATFORM_ORGANIZATION")
    if status not in {"ACTIVE", "SUSPENDED"}:
        raise ValidationFailed(errors=[FieldError(field="status", code="INVALID", message="Use ACTIVE or SUSPENDED.")])
    before = {"status": org.status}
    org.status, org.updated_by = status, caller.auth.user_id
    session.flush()
    affected = bump_authz(session, members_of(session, org.id))
    audit(session, action="ORGANIZATION.STATUS_CHANGED", entity_type="ORGANIZATION", entity_id=org.id,
          actor=caller.auth.user_id, organization_id=org.id, before=before, after={"status": status},
          metadata={"users_affected": len(affected)})
    event(session, aggregate_type="ORGANIZATION", aggregate_id=org.id, event_type="OrganizationStatusChanged",
          payload={"organization_id": org.id, "status": status}, organization_id=org.id)
    return org


# ------------------------------------------------------------------ memberships
def membership_query(organization_id: uuid.UUID, status: str | None):
    stmt = (select(OrganizationMembership, User).join(User, User.id == OrganizationMembership.user_id)
            .where(OrganizationMembership.organization_id == organization_id))
    if status:
        stmt = stmt.where(OrganizationMembership.status == status)
    return stmt


def add_member(session: Session, caller: Authorized, organization_id: uuid.UUID, *, email: str | None,
               mobile: str | None) -> OrganizationMembership:
    require_organization(caller, organization_id)
    org = get_or_404(session, Organization, organization_id, label="Organization")
    if bool(email) == bool(mobile):
        raise ValidationFailed(errors=[FieldError(field="email", code="ONE_OF",
                                                  message="Give either an email or a mobile number.")])
    if email:
        identity_type, identifier = "EMAIL_PASSWORD", normalize_email(email)
    else:
        identity_type, identifier = "MOBILE_OTP", normalize_mobile(mobile or "")
    identity = session.scalar(select(AuthIdentity).where(AuthIdentity.identity_type == identity_type,
                                                         AuthIdentity.identifier == identifier))
    if identity is None:
        raise NotFound("No user has this email or mobile number. Create the user first.", code="USER_NOT_FOUND")
    if session.scalar(select(OrganizationMembership.id).where(OrganizationMembership.organization_id == org.id,
                                                              OrganizationMembership.user_id == identity.user_id)):
        raise Conflict("This user is already a member.", code="ALREADY_MEMBER")
    membership = OrganizationMembership(organization_id=org.id, user_id=identity.user_id, status="ACTIVE",
                                        joined_at=_now(), created_by=caller.auth.user_id,
                                        updated_by=caller.auth.user_id)
    session.add(membership)
    session.flush()
    bump_authz(session, [identity.user_id])
    audit(session, action="MEMBERSHIP.CREATED", entity_type="ORGANIZATION_MEMBERSHIP", entity_id=membership.id,
          actor=caller.auth.user_id, organization_id=org.id, after={"user_id": identity.user_id, "status": "ACTIVE"})
    event(session, aggregate_type="ORGANIZATION", aggregate_id=org.id, event_type="MembershipChanged",
          payload={"membership_id": membership.id, "user_id": identity.user_id, "status": "ACTIVE"},
          organization_id=org.id)
    return membership


def _membership(session: Session, caller: Authorized, organization_id: uuid.UUID,
                membership_id: uuid.UUID) -> OrganizationMembership:
    require_organization(caller, organization_id)
    membership = get_or_404(session, OrganizationMembership, membership_id, label="Membership")
    if membership.organization_id != organization_id:
        raise NotFound("Membership not found.")
    return membership


def _guard_last_access_admin(session: Session, membership: OrganizationMembership, *,
                             excluding_assignment: uuid.UUID | None = None) -> None:
    holders_now = organization_holders(session, membership.organization_id, ACCESS_ADMIN_PERMISSION)
    if membership.user_id not in holders_now:
        return
    remaining = organization_holders(session, membership.organization_id, ACCESS_ADMIN_PERMISSION,
                                     excluding_assignment=excluding_assignment,
                                     excluding_membership=None if excluding_assignment else membership.id)
    if not remaining:
        raise ValidationFailed("This is the last person who can manage access in this organization.",
                               code="LAST_ACCESS_ADMIN")


def set_membership_status(session: Session, caller: Authorized, organization_id: uuid.UUID, membership_id: uuid.UUID,
                          version: int | None, status: str) -> OrganizationMembership:
    membership = _membership(session, caller, organization_id, membership_id)
    check_version(membership, version)
    if status not in {"ACTIVE", "SUSPENDED", "ENDED"}:
        raise ValidationFailed(errors=[FieldError(field="status", code="INVALID",
                                                  message="Use ACTIVE, SUSPENDED or ENDED.")])
    if membership.user_id == caller.auth.user_id and status != "ACTIVE":
        raise ValidationFailed("You cannot suspend or end your own membership.", code="SELF_MEMBERSHIP")
    if status != "ACTIVE" and membership.status == "ACTIVE":
        _guard_last_access_admin(session, membership)
    before = {"status": membership.status}
    membership.status, membership.updated_by = status, caller.auth.user_id
    membership.ended_at = _now() if status == "ENDED" else None
    session.flush()
    bump_authz(session, [membership.user_id])
    audit(session, action="MEMBERSHIP.STATUS_CHANGED", entity_type="ORGANIZATION_MEMBERSHIP", entity_id=membership.id,
          actor=caller.auth.user_id, organization_id=organization_id, before=before, after={"status": status})
    event(session, aggregate_type="ORGANIZATION", aggregate_id=organization_id, event_type="MembershipChanged",
          payload={"membership_id": membership.id, "user_id": membership.user_id, "status": status},
          organization_id=organization_id)
    return membership


def delete_membership(session: Session, caller: Authorized, organization_id: uuid.UUID, membership_id: uuid.UUID,
                      version: int | None) -> None:
    membership = _membership(session, caller, organization_id, membership_id)
    check_version(membership, version)
    if membership.user_id == caller.auth.user_id:
        raise ValidationFailed("You cannot remove your own membership.", code="SELF_MEMBERSHIP")
    if membership.status == "ACTIVE":
        _guard_last_access_admin(session, membership)
    revoked = 0
    for assignment in session.scalars(select(UserRoleAssignment).where(
            UserRoleAssignment.membership_id == membership.id, UserRoleAssignment.status != "REVOKED")):
        revoke_assignment(session, assignment, caller.auth.user_id, organization_id, "Membership removed")
        revoked += 1
    membership.soft_delete(caller.auth.user_id)
    membership.updated_by = caller.auth.user_id
    session.flush()
    bump_authz(session, [membership.user_id])
    audit(session, action="MEMBERSHIP.DELETED", entity_type="ORGANIZATION_MEMBERSHIP", entity_id=membership.id,
          actor=caller.auth.user_id, organization_id=organization_id, before={"status": membership.status},
          metadata={"assignments_revoked": revoked})


# ------------------------------------------------------------------ role assignments
def assignments_of(session: Session, caller: Authorized, user_id: uuid.UUID) -> list[tuple]:
    visible_user(session, caller, user_id)
    stmt = (select(UserRoleAssignment, Role, OrganizationMembership, Organization)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .outerjoin(OrganizationMembership, OrganizationMembership.id == UserRoleAssignment.membership_id)
            .outerjoin(Organization, Organization.id == OrganizationMembership.organization_id)
            .where(UserRoleAssignment.user_id == user_id)
            .order_by(UserRoleAssignment.status, UserRoleAssignment.created_at.desc())
            .execution_options(include_deleted=True))
    rows = list(session.execute(stmt))
    if caller.scope is not Scope.ALL:
        rows = [r for r in rows if r[2] is None or r[2].organization_id == caller.auth.organization_id]
    return rows


def assign_role(rt: Runtime, session: Session, caller: Authorized, user_id: uuid.UUID, *, role_id: uuid.UUID,
                membership_id: uuid.UUID | None, scope_type: str,
                valid_until: datetime | None) -> ChangeResult:
    user = visible_user(session, caller, user_id)
    if user.id == caller.auth.user_id:
        raise PermissionDenied("You cannot assign roles to yourself.", code="SELF_ASSIGNMENT")
    if user.status != "ACTIVE":
        raise Conflict("This user is not active.", code="USER_NOT_ACTIVE")
    try:
        scope = Scope(scope_type)
    except ValueError:
        raise ValidationFailed(errors=[FieldError(field="scope_type", code="INVALID",
                                                  message="Use OWN, ORGANIZATION or ALL.")]) from None
    if not scope.active:
        raise ValidationFailed(errors=[FieldError(field="scope_type", code="SCOPE_INACTIVE",
                                                  message=f"{scope.value} scope is not available yet.")])
    org_id = None
    if membership_id is None:
        if scope is not Scope.OWN:
            raise ValidationFailed(errors=[FieldError(field="membership_id", code="REQUIRED",
                                                      message="Organization and platform-wide roles need a membership.")])
        require_all_scope(caller)
    else:
        membership = get_or_404(session, OrganizationMembership, membership_id, label="Membership")
        if membership.user_id != user.id:
            raise ValidationFailed(errors=[FieldError(field="membership_id", code="NOT_THIS_USER",
                                                      message="This membership belongs to another user.")])
        if membership.status != "ACTIVE":
            raise Conflict("This membership is not active.", code="MEMBERSHIP_NOT_ACTIVE")
        org_id = membership.organization_id
        require_organization(caller, org_id)
        if scope is Scope.ALL:
            org = session.get(Organization, org_id)
            if not (org and org.is_platform):
                raise ValidationFailed(errors=[FieldError(field="scope_type", code="ALL_NEEDS_PLATFORM",
                                                          message="ALL scope is only given on a platform membership.")])
    role = get_or_404(session, Role, role_id, label="Role")
    if role.status != "ACTIVE":
        raise Conflict("Only an active role can be assigned.", code="ROLE_NOT_ACTIVE")
    if role.owner_organization_id is not None and role.owner_organization_id != org_id:
        raise ValidationFailed(errors=[FieldError(field="role_id", code="ROLE_OF_OTHER_ORGANIZATION",
                                                  message="This role belongs to another organization.")])
    # Nobody can hand out more than they hold: every permission, at least as wide.
    codes = list(session.scalars(select(Permission.permission_code).join(
        RolePermission, RolePermission.permission_id == Permission.id).where(RolePermission.role_id == role.id)))
    lacking = [c for c in codes
               if (held := caller.permissions.scope_for(c)) is None or held.rank < scope.rank]
    if lacking:
        audit(session, action="ROLE_ASSIGNMENT.DENIED", entity_type="USER_ROLE_ASSIGNMENT", actor=caller.auth.user_id,
              organization_id=org_id, result=AuditResult.DENIED,
              metadata={"user_id": user.id, "role_id": role.id, "reason": "GRANTS_MORE_THAN_CALLER_HOLDS",
                        "lacking": lacking})
        session.commit()
        raise PermissionDenied("You cannot give access you do not hold yourself.", code="CANNOT_GRANT_MORE",
                               details={"lacking": lacking})
    if valid_until is not None and valid_until <= _now():
        raise ValidationFailed(errors=[FieldError(field="valid_until", code="IN_PAST",
                                                  message="The end date must be in the future.")])
    existing = session.scalar(select(UserRoleAssignment.id).where(
        UserRoleAssignment.user_id == user.id, UserRoleAssignment.role_id == role.id,
        UserRoleAssignment.membership_id.is_(None) if membership_id is None
        else UserRoleAssignment.membership_id == membership_id,
        UserRoleAssignment.status != "REVOKED"))
    if existing:
        raise Conflict("The user already has this role here.", code="ALREADY_ASSIGNED")
    pending = rt.approvals.is_required(session, "USER_ROLE_ASSIGNMENT", org_id)
    assignment = UserRoleAssignment(user_id=user.id, role_id=role.id, membership_id=membership_id,
                                    scope_type=scope.value, status="PENDING_APPROVAL" if pending else "ACTIVE",
                                    valid_until=valid_until, created_by=caller.auth.user_id,
                                    updated_by=caller.auth.user_id)
    session.add(assignment)
    session.flush()
    audit(session, action="ROLE_ASSIGNMENT.CREATED", entity_type="USER_ROLE_ASSIGNMENT", entity_id=assignment.id,
          actor=caller.auth.user_id, organization_id=org_id, after=assignment_snapshot(assignment))
    if not pending:
        bump_authz(session, [user.id])
        event(session, aggregate_type="USER", aggregate_id=user.id, event_type="UserRoleAssigned",
              payload={"assignment_id": assignment.id, "role_id": role.id, "scope": scope.value},
              organization_id=org_id)
        return ChangeResult("APPLIED", assignment)
    return _submit_or_apply(
        rt, session, caller, entity_type="USER_ROLE_ASSIGNMENT", entity=assignment,
        entity_version=assignment.version, action_type="CREATE",
        proposed={"role_id": role.id, "role_name": role.name, "scope_type": scope.value},
        summary=f"Give {role.name} ({scope.value}) to {user.display_name}",
        apply=lambda: activate_assignment(session, assignment, caller.auth.user_id, org_id),
        organization_id=org_id, subject_user_id=user.id)


def revoke_role(session: Session, caller: Authorized, user_id: uuid.UUID, assignment_id: uuid.UUID,
                reason: str | None) -> None:
    assignment = get_or_404(session, UserRoleAssignment, assignment_id, label="Assignment")
    if assignment.user_id != user_id:
        raise NotFound("Assignment not found.")
    visible_user(session, caller, user_id)
    if assignment.status == "REVOKED":
        raise Conflict("This assignment is already revoked.", code="ALREADY_REVOKED")
    org_id = None
    if assignment.membership_id is None:
        require_all_scope(caller)
    else:
        membership = session.scalar(select(OrganizationMembership).where(
            OrganizationMembership.id == assignment.membership_id).execution_options(include_deleted=True))
        org_id = membership.organization_id if membership else None
        require_organization(caller, org_id)
        if membership is not None and assignment.status == "ACTIVE":
            _guard_last_access_admin(session, membership, excluding_assignment=assignment.id)
    revoke_assignment(session, assignment, caller.auth.user_id, org_id, reason)
