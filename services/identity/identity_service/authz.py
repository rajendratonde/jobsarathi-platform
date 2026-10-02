"""Effective permissions, resolved from identity_db (v5 §9).

An assignment grants its role's permissions only while every link is live:

    user ACTIVE and not deleted
    assignment ACTIVE, inside valid_from / valid_until
    role ACTIVE and not deleted
    permission active, not deleted; its resource, action and module active and not deleted
    membership (when present) ACTIVE and not deleted, its organization ACTIVE and not deleted

Which assignments apply in the active organization:

    personal (no membership, OWN scope)       always
    membership in the active organization      always
    ALL scope (only on a platform membership)  in every organization

CITY and REGION are stored but inactive in Phase 1, so they grant nothing.
No role code or name is consulted here.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from js_auth.context import EffectivePermissions, Scope, widest
from sqlalchemy import and_, false, or_, select, update
from sqlalchemy.orm import Session

from identity_service.models import (
    Action,
    Module,
    Organization,
    OrganizationMembership,
    Permission,
    Resource,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
)


def resolve(session: Session, user_id: uuid.UUID, organization_id: uuid.UUID | None) -> EffectivePermissions:
    user = session.get(User, user_id)
    if user is None:
        return EffectivePermissions(authz_version=-1)
    if user.status != "ACTIVE":
        return EffectivePermissions(authz_version=user.authz_version)

    now = datetime.now(UTC)
    a, r, rp, p = UserRoleAssignment, Role, RolePermission, Permission
    m, o = OrganizationMembership, Organization
    applies = or_(
        a.membership_id.is_(None),
        m.organization_id == organization_id if organization_id else false(),
        and_(a.scope_type == Scope.ALL.value, o.is_platform.is_(True)),
    )
    stmt = (
        select(p.permission_code, a.scope_type, r.role_code)
        .select_from(a)
        .join(r, r.id == a.role_id)
        .join(rp, rp.role_id == r.id)
        .join(p, p.id == rp.permission_id)
        .join(Resource, Resource.id == p.resource_id)
        .join(Action, Action.id == p.action_id)
        .join(Module, Module.id == Resource.module_id)
        .outerjoin(m, m.id == a.membership_id)
        .outerjoin(o, o.id == m.organization_id)
        .where(
            a.user_id == user_id, a.status == "ACTIVE", a.valid_from <= now,
            or_(a.valid_until.is_(None), a.valid_until > now),
            r.status == "ACTIVE", r.deleted_at.is_(None),
            p.is_active.is_(True), p.deleted_at.is_(None),
            Resource.is_active.is_(True), Resource.deleted_at.is_(None),
            Action.is_active.is_(True), Action.deleted_at.is_(None),
            Module.is_active.is_(True), Module.deleted_at.is_(None),
            or_(a.membership_id.is_(None),
                and_(m.status == "ACTIVE", m.deleted_at.is_(None), o.status == "ACTIVE", o.deleted_at.is_(None))),
            applies,
        )
    )
    scopes: dict[str, Scope] = {}
    roles: set[str] = set()
    for code, scope_type, role_code in session.execute(stmt):
        scope = Scope(scope_type)
        if not scope.active:
            continue
        scopes[code] = widest(scopes.get(code), scope)
        roles.add(role_code)
    return EffectivePermissions(authz_version=user.authz_version, scopes=scopes, roles=tuple(sorted(roles)))


class LocalAuthzProvider:
    """``AuthzProvider`` for Identity itself: a short session per lookup."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def effective(self, user_id: uuid.UUID, organization_id: uuid.UUID | None) -> EffectivePermissions:
        with self.session_factory() as session:
            return resolve(session, user_id, organization_id)


# ------------------------------------------------------------------ authz_version maintenance
def bump_authz(session: Session, user_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Any change to what a user may do raises users.authz_version, which invalidates
    their access tokens (TOKEN_STALE) and every cached permission set at once."""
    ids = {u for u in user_ids if u is not None}
    if ids:
        session.execute(update(User).where(User.id.in_(ids)).values(authz_version=User.authz_version + 1)
                        .execution_options(synchronize_session=False))
        for obj in list(session.identity_map.values()):
            if isinstance(obj, User) and obj.id in ids:
                session.expire(obj, ["authz_version"])
    return ids


def holders_of_roles(session: Session, role_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(role_ids)
    if not ids:
        return set()
    rows = session.scalars(select(UserRoleAssignment.user_id).where(
        UserRoleAssignment.role_id.in_(ids), UserRoleAssignment.status != "REVOKED"))
    return set(rows)


def holders_of_permission(session: Session, permission_id: uuid.UUID) -> set[uuid.UUID]:
    role_ids = session.scalars(select(RolePermission.role_id).where(RolePermission.permission_id == permission_id))
    return holders_of_roles(session, list(role_ids))


def members_of(session: Session, organization_id: uuid.UUID) -> set[uuid.UUID]:
    rows = session.scalars(select(OrganizationMembership.user_id)
                           .where(OrganizationMembership.organization_id == organization_id)
                           .execution_options(include_deleted=True))
    return set(rows)


def organization_holders(session: Session, organization_id: uuid.UUID, permission_code: str,
                         *, excluding_assignment: uuid.UUID | None = None,
                         excluding_membership: uuid.UUID | None = None) -> set[uuid.UUID]:
    """Users who hold ``permission_code`` through an ACTIVE membership of this organization.

    Used to stop the last person who can manage access from being removed (data-driven:
    the permission code decides, never a role name)."""
    a, m = UserRoleAssignment, OrganizationMembership
    stmt = (
        select(a.user_id)
        .join(m, m.id == a.membership_id)
        .join(Role, Role.id == a.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .join(User, User.id == a.user_id)
        .where(m.organization_id == organization_id, m.status == "ACTIVE", m.deleted_at.is_(None),
               a.status == "ACTIVE", Role.status == "ACTIVE", Role.deleted_at.is_(None),
               Permission.permission_code == permission_code, Permission.is_active.is_(True),
               Permission.deleted_at.is_(None), User.status == "ACTIVE", User.deleted_at.is_(None),
               a.scope_type.in_([Scope.ORGANIZATION.value, Scope.ALL.value]))
    )
    if excluding_assignment:
        stmt = stmt.where(a.id != excluding_assignment)
    if excluding_membership:
        stmt = stmt.where(m.id != excluding_membership)
    return set(session.scalars(stmt))
