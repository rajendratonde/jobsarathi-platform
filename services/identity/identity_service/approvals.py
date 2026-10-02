"""Maker-Checker handlers for Identity entity types (v5 §10).

    ROLE                  create / rename / enable-disable / delete / restore a role
    ROLE_PERMISSIONS      replace a role's permission set
    PERMISSION            create / enable-disable / delete a permission
    USER_ROLE_ASSIGNMENT  activate an assignment (policy seeded OFF until Q7)

The same ``apply_*`` functions run directly when a policy is switched off, so a
change has one implementation whether or not it needs a checker. Every applied
change raises users.authz_version for the people it affects.
"""

from __future__ import annotations

import uuid
import zlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from identity_service.authz import bump_authz, holders_of_permission, holders_of_roles
from identity_service.common import audit, event
from identity_service.models import Permission, Role, RolePermission, UserRoleAssignment
from js_approval import ApprovalEngine


def _now() -> datetime:
    return datetime.now(UTC)


def _meta(request: Any | None) -> dict | None:
    if request is None:
        return None
    return {"approval_request": request.request_number, "maker_user_id": request.maker_user_id}


# ------------------------------------------------------------------ roles
def role_snapshot(role: Role) -> dict:
    return {"role_code": role.role_code, "name": role.name, "description": role.description, "status": role.status,
            "owner_organization_id": role.owner_organization_id, "deleted": role.deleted_at is not None}


def set_role_permissions(session: Session, role: Role, permission_ids: list[uuid.UUID], actor: uuid.UUID) -> dict:
    current = set(session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)))
    wanted = {uuid.UUID(str(p)) for p in permission_ids}
    removed, added = current - wanted, wanted - current
    if removed:
        session.execute(delete(RolePermission).where(RolePermission.role_id == role.id,
                                                     RolePermission.permission_id.in_(removed)))
    for pid in added:
        session.add(RolePermission(role_id=role.id, permission_id=pid, created_by=actor))
    role.updated_by, role.updated_at = actor, _now()  # forces an UPDATE: role.version rises, pending proposals go stale
    return {"added": sorted(str(p) for p in added), "removed": sorted(str(p) for p in removed)}


def apply_role_change(session: Session, role: Role, action_type: str, proposed: dict, actor: uuid.UUID,
                      request: Any | None = None) -> None:
    before = role_snapshot(role)
    diff = None
    if action_type == "CREATE":
        role.status = "ACTIVE"
        diff = set_role_permissions(session, role, proposed.get("permission_ids", []), actor)
    elif action_type == "UPDATE":
        role.name = proposed.get("name", role.name)
        role.description = proposed.get("description", role.description)
    elif action_type == "STATUS_CHANGE":
        role.status = proposed["status"]
    elif action_type == "DELETE":
        role.soft_delete(actor)
    elif action_type == "RESTORE":
        role.restore()
        role.status = "DISABLED"
    else:
        raise ValueError(f"Unknown role action {action_type}")
    role.updated_by = actor
    session.flush()
    affected = bump_authz(session, holders_of_roles(session, [role.id]))
    audit(session, action=f"ROLE.{'CREATED' if action_type == 'CREATE' else action_type}", entity_type="ROLE",
          entity_id=role.id, actor=actor, before=before, after=role_snapshot(role),
          metadata={**(_meta(request) or {}), "permissions": diff, "users_affected": len(affected)})
    event(session, aggregate_type="ROLE", aggregate_id=role.id, event_type="RoleChanged",
          payload={"role_id": role.id, "action": action_type, "status": role.status})


def apply_role_permissions(session: Session, role: Role, proposed: dict, actor: uuid.UUID,
                           request: Any | None = None) -> None:
    diff = set_role_permissions(session, role, proposed["permission_ids"], actor)
    session.flush()
    affected = bump_authz(session, holders_of_roles(session, [role.id]))
    audit(session, action="ROLE.PERMISSIONS_CHANGED", entity_type="ROLE", entity_id=role.id, actor=actor,
          before={"removed": diff["removed"]}, after={"added": diff["added"]},
          metadata={**(_meta(request) or {}), "users_affected": len(affected)})
    event(session, aggregate_type="ROLE", aggregate_id=role.id, event_type="RolePermissionsChanged",
          payload={"role_id": role.id, **diff})


class RoleHandler:
    def load_for_update(self, session: Session, entity_id: uuid.UUID) -> Role | None:
        return session.scalar(select(Role).where(Role.id == entity_id).with_for_update()
                              .execution_options(include_deleted=True))

    def apply_approval(self, session: Session, entity: Role, request: Any, checker: uuid.UUID) -> None:
        apply_role_change(session, entity, request.action_type, request.proposed_changes or {}, checker, request)

    def apply_rejection(self, session: Session, entity: Role, request: Any, checker: uuid.UUID) -> None:
        if request.action_type == "CREATE":
            entity.status = "DRAFT"

    def apply_withdrawal(self, session: Session, entity: Role, request: Any, actor: uuid.UUID) -> None:
        self.apply_rejection(session, entity, request, actor)


class RolePermissionsHandler(RoleHandler):
    def apply_approval(self, session: Session, entity: Role, request: Any, checker: uuid.UUID) -> None:
        apply_role_permissions(session, entity, request.proposed_changes or {}, checker, request)

    def apply_rejection(self, session: Session, entity: Role, request: Any, checker: uuid.UUID) -> None:
        return None


# ------------------------------------------------------------------ permissions
def permission_version(permission: Permission) -> int:
    """v5 ``permissions`` has no version column; its last-change fingerprint plays that role."""
    marker = f"{permission.updated_at.timestamp():.6f}|{permission.is_active}|{permission.deleted_at is not None}"
    return zlib.crc32(marker.encode()) & 0x7FFFFFFF


def permission_snapshot(p: Permission) -> dict:
    return {"permission_code": p.permission_code, "is_active": p.is_active, "deleted": p.deleted_at is not None}


def apply_permission_change(session: Session, permission: Permission, action_type: str, proposed: dict,
                            actor: uuid.UUID, request: Any | None = None) -> None:
    before = permission_snapshot(permission)
    if action_type == "CREATE":
        permission.is_active = True
    elif action_type == "STATUS_CHANGE":
        permission.is_active = bool(proposed["is_active"])
    elif action_type == "DELETE":
        permission.soft_delete(actor)
    else:
        raise ValueError(f"Unknown permission action {action_type}")
    permission.updated_by = actor
    session.flush()
    affected = bump_authz(session, holders_of_permission(session, permission.id))
    audit(session, action=f"PERMISSION.{'CREATED' if action_type == 'CREATE' else action_type}",
          entity_type="PERMISSION", entity_id=permission.id, actor=actor, before=before,
          after=permission_snapshot(permission), metadata={**(_meta(request) or {}), "users_affected": len(affected)})


class PermissionHandler:
    def version_of(self, entity: Permission) -> int:
        return permission_version(entity)

    def load_for_update(self, session: Session, entity_id: uuid.UUID) -> Permission | None:
        return session.scalar(select(Permission).where(Permission.id == entity_id).with_for_update()
                              .execution_options(include_deleted=True))

    def apply_approval(self, session: Session, entity: Permission, request: Any, checker: uuid.UUID) -> None:
        apply_permission_change(session, entity, request.action_type, request.proposed_changes or {}, checker, request)

    def apply_rejection(self, session: Session, entity: Permission, request: Any, checker: uuid.UUID) -> None:
        if request.action_type == "CREATE":
            entity.soft_delete(checker)  # frees the code; the proposal is kept in approval_requests

    def apply_withdrawal(self, session: Session, entity: Permission, request: Any, actor: uuid.UUID) -> None:
        self.apply_rejection(session, entity, request, actor)


# ------------------------------------------------------------------ role assignments
def assignment_snapshot(a: UserRoleAssignment) -> dict:
    return {"user_id": a.user_id, "role_id": a.role_id, "membership_id": a.membership_id, "scope_type": a.scope_type,
            "status": a.status, "valid_until": a.valid_until}


def activate_assignment(session: Session, assignment: UserRoleAssignment, actor: uuid.UUID,
                        organization_id: uuid.UUID | None, request: Any | None = None) -> None:
    before = assignment_snapshot(assignment)
    assignment.status = "ACTIVE"
    assignment.updated_by = actor
    session.flush()
    bump_authz(session, [assignment.user_id])
    audit(session, action="ROLE_ASSIGNMENT.ACTIVATED", entity_type="USER_ROLE_ASSIGNMENT", entity_id=assignment.id,
          actor=actor, organization_id=organization_id, before=before, after=assignment_snapshot(assignment),
          metadata=_meta(request))
    event(session, aggregate_type="USER", aggregate_id=assignment.user_id, event_type="UserRoleAssigned",
          payload={"assignment_id": assignment.id, "role_id": assignment.role_id, "scope": assignment.scope_type},
          organization_id=organization_id)


def revoke_assignment(session: Session, assignment: UserRoleAssignment, actor: uuid.UUID,
                      organization_id: uuid.UUID | None, reason: str | None, request: Any | None = None) -> None:
    before = assignment_snapshot(assignment)
    assignment.status, assignment.revoked_at, assignment.revoked_by = "REVOKED", _now(), actor
    assignment.updated_by = actor
    session.flush()
    bump_authz(session, [assignment.user_id])
    audit(session, action="ROLE_ASSIGNMENT.REVOKED", entity_type="USER_ROLE_ASSIGNMENT", entity_id=assignment.id,
          actor=actor, organization_id=organization_id, before=before, after=assignment_snapshot(assignment),
          metadata={**(_meta(request) or {}), "reason": reason})
    event(session, aggregate_type="USER", aggregate_id=assignment.user_id, event_type="UserRoleRevoked",
          payload={"assignment_id": assignment.id, "role_id": assignment.role_id}, organization_id=organization_id)


class AssignmentHandler:
    def load_for_update(self, session: Session, entity_id: uuid.UUID) -> UserRoleAssignment | None:
        return session.scalar(select(UserRoleAssignment).where(UserRoleAssignment.id == entity_id).with_for_update())

    def apply_approval(self, session: Session, entity: UserRoleAssignment, request: Any, checker: uuid.UUID) -> None:
        activate_assignment(session, entity, checker, request.organization_id, request)

    def apply_rejection(self, session: Session, entity: UserRoleAssignment, request: Any, checker: uuid.UUID) -> None:
        revoke_assignment(session, entity, checker, request.organization_id, "Approval rejected", request)

    def apply_withdrawal(self, session: Session, entity: UserRoleAssignment, request: Any, actor: uuid.UUID) -> None:
        revoke_assignment(session, entity, actor, request.organization_id, "Approval withdrawn", request)


def register_handlers(engine: ApprovalEngine) -> None:
    engine.register("ROLE", RoleHandler())
    engine.register("ROLE_PERMISSIONS", RolePermissionsHandler())
    engine.register("PERMISSION", PermissionHandler())
    engine.register("USER_ROLE_ASSIGNMENT", AssignmentHandler())
