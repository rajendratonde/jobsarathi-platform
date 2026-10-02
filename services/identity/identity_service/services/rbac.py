"""Roles, permissions, catalogue and matrix. Changes go through Maker-Checker when the
entity's approval policy is enabled; otherwise they apply at once (same code path)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from identity_service.approvals import (
    apply_permission_change,
    apply_role_change,
    apply_role_permissions,
    permission_version,
)
from identity_service.authz import bump_authz
from identity_service.common import audit, check_version, get_or_404, require_all_scope, require_organization
from identity_service.models import (
    Action,
    Module,
    Permission,
    Resource,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from identity_service.runtime import Runtime
from js_audit import ActorType
from js_auth.context import Authorized, Scope
from js_core.errors import Conflict, FieldError, NotFound, ValidationFailed


class SystemRoleProtected(ValidationFailed):
    code, message = "SYSTEM_ROLE", "A system role cannot be renamed, disabled or deleted, and keeps its permissions."


@dataclass
class ChangeResult:
    status: str                 # APPLIED | PENDING_APPROVAL
    entity: Any
    approval_request: Any | None = None


def _submit_or_apply(rt: Runtime, session: Session, caller: Authorized, *, entity_type: str, entity: Any,
                     entity_version: int, action_type: str, proposed: dict, summary: str,
                     apply: Callable[[], None], organization_id: uuid.UUID | None = None,
                     subject_user_id: uuid.UUID | None = None, maker_permission: str | None = None,
                     comment: str | None = None) -> ChangeResult:
    if rt.approvals.is_required(session, entity_type, organization_id):
        request = rt.approvals.submit(
            session, entity_type=entity_type, entity_id=entity.id, entity_version=entity_version,
            action_type=action_type, maker=caller.auth.user_id, maker_permissions=caller.permissions,
            organization_id=organization_id, subject_user_id=subject_user_id, proposed_changes=_jsonable(proposed),
            change_summary=summary, comment=comment, acting_organization_id=caller.auth.organization_id,
            maker_permission=maker_permission)
        audit(session, action="APPROVAL.SUBMITTED", entity_type=entity_type, entity_id=entity.id,
              actor=caller.auth.user_id, organization_id=organization_id,
              metadata={"approval_request": request.request_number, "action_type": action_type, "summary": summary})
        return ChangeResult("PENDING_APPROVAL", entity, request)
    apply()
    return ChangeResult("APPLIED", entity)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


# ------------------------------------------------------------------ roles
def visible_roles_filter(caller: Authorized):
    if caller.scope is Scope.ALL:
        return True
    return or_(Role.owner_organization_id.is_(None), Role.owner_organization_id == caller.auth.organization_id)


def _check_role_owner(caller: Authorized, owner_organization_id: uuid.UUID | None) -> None:
    if owner_organization_id is None:
        require_all_scope(caller)
    else:
        require_organization(caller, owner_organization_id)


def _validate_permissions(session: Session, permission_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    ids = list(dict.fromkeys(permission_ids))
    if not ids:
        return []
    found = set(session.scalars(select(Permission.id).where(Permission.id.in_(ids), Permission.is_active.is_(True))))
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise ValidationFailed(errors=[FieldError(field="permission_ids", code="UNKNOWN_PERMISSION",
                                                  message=f"Unknown or inactive permission: {', '.join(missing)}")])
    return ids


def _role_code(session: Session, name: str, requested: str | None) -> str:
    base = (requested or re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")).upper()[:50] or "ROLE"
    if not re.match(r"^[A-Z][A-Z0-9_]*$", base):
        raise ValidationFailed(errors=[FieldError(field="role_code", code="INVALID",
                                                  message="Use capital letters, digits and underscores.")])
    code, n = base, 2
    while session.scalar(select(Role.id).where(Role.role_code == code).execution_options(include_deleted=True)):
        if requested:
            raise Conflict("This role code is already used.", code="ROLE_CODE_TAKEN")
        code, n = f"{base[:55]}_{n}", n + 1
    return code


def _name_taken(session: Session, name: str, owner: uuid.UUID | None, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Role.id).where(func.lower(Role.name) == name.strip().lower(),
                                 Role.owner_organization_id.is_(None) if owner is None
                                 else Role.owner_organization_id == owner)
    if exclude:
        stmt = stmt.where(Role.id != exclude)
    return session.scalar(stmt) is not None


def create_role(rt: Runtime, session: Session, caller: Authorized, *, name: str, description: str | None,
                role_code: str | None, permission_ids: list[uuid.UUID],
                owner_organization_id: uuid.UUID | None) -> ChangeResult:
    _check_role_owner(caller, owner_organization_id)
    if _name_taken(session, name, owner_organization_id):
        raise Conflict("A role with this name already exists.", code="ROLE_NAME_TAKEN")
    ids = _validate_permissions(session, permission_ids)
    role = Role(role_code=_role_code(session, name, role_code), name=name.strip(), description=description,
                owner_organization_id=owner_organization_id, status="DRAFT", created_by=caller.auth.user_id,
                updated_by=caller.auth.user_id)
    pending = rt.approvals.is_required(session, "ROLE", owner_organization_id)
    if pending:
        role.status = "PENDING_APPROVAL"
    session.add(role)
    session.flush()
    audit(session, action="ROLE.DRAFTED", entity_type="ROLE", entity_id=role.id, actor=caller.auth.user_id,
          organization_id=owner_organization_id,
          after={"role_code": role.role_code, "name": role.name, "permission_ids": [str(i) for i in ids]})
    return _submit_or_apply(
        rt, session, caller, entity_type="ROLE", entity=role, entity_version=role.version, action_type="CREATE",
        proposed={"permission_ids": ids}, summary=f"Create role {role.name} with {len(ids)} permissions",
        apply=lambda: apply_role_change(session, role, "CREATE", {"permission_ids": ids}, caller.auth.user_id),
        organization_id=owner_organization_id, maker_permission="ROLE.CREATE")


def _editable_role(session: Session, caller: Authorized, role_id: uuid.UUID, version: int | None,
                   *, include_deleted: bool = False) -> Role:
    role = get_or_404(session, Role, role_id, label="Role", include_deleted=include_deleted)
    _check_role_owner(caller, role.owner_organization_id)
    check_version(role, version)
    return role


def update_role(rt: Runtime, session: Session, caller: Authorized, role_id: uuid.UUID, version: int | None,
                *, name: str | None, description: str | None) -> ChangeResult:
    role = _editable_role(session, caller, role_id, version)
    if role.is_system:
        raise SystemRoleProtected()
    proposed: dict = {}
    if name is not None and name.strip() != role.name:
        if _name_taken(session, name, role.owner_organization_id, exclude=role.id):
            raise Conflict("A role with this name already exists.", code="ROLE_NAME_TAKEN")
        proposed["name"] = name.strip()
    if description is not None and description != role.description:
        proposed["description"] = description
    if not proposed:
        return ChangeResult("UNCHANGED", role)
    return _submit_or_apply(
        rt, session, caller, entity_type="ROLE", entity=role, entity_version=role.version, action_type="UPDATE",
        proposed=proposed, summary=f"Edit role {role.name}",
        apply=lambda: apply_role_change(session, role, "UPDATE", proposed, caller.auth.user_id),
        organization_id=role.owner_organization_id)


def set_role_status(rt: Runtime, session: Session, caller: Authorized, role_id: uuid.UUID, version: int | None,
                    status: str) -> ChangeResult:
    role = _editable_role(session, caller, role_id, version)
    if role.is_system:
        raise SystemRoleProtected()
    if status not in {"ACTIVE", "DISABLED"}:
        raise ValidationFailed(errors=[FieldError(field="status", code="INVALID", message="Use ACTIVE or DISABLED.")])
    if role.status not in {"ACTIVE", "DISABLED"}:
        raise Conflict(f"A {role.status.lower().replace('_', ' ')} role cannot change status.", code="ROLE_NOT_READY")
    if role.status == status:
        return ChangeResult("UNCHANGED", role)
    return _submit_or_apply(
        rt, session, caller, entity_type="ROLE", entity=role, entity_version=role.version,
        action_type="STATUS_CHANGE", proposed={"status": status},
        summary=f"{'Enable' if status == 'ACTIVE' else 'Disable'} role {role.name}",
        apply=lambda: apply_role_change(session, role, "STATUS_CHANGE", {"status": status}, caller.auth.user_id),
        organization_id=role.owner_organization_id)


def delete_role(rt: Runtime, session: Session, caller: Authorized, role_id: uuid.UUID,
                version: int | None) -> ChangeResult:
    role = _editable_role(session, caller, role_id, version)
    if role.is_system:
        raise SystemRoleProtected()
    holders = session.scalar(select(func.count()).select_from(UserRoleAssignment).where(
        UserRoleAssignment.role_id == role.id, UserRoleAssignment.status != "REVOKED")) or 0
    if holders:
        raise ValidationFailed(f"Revoke this role from its {holders} holder(s) first.", code="ROLE_IN_USE")
    return _submit_or_apply(
        rt, session, caller, entity_type="ROLE", entity=role, entity_version=role.version, action_type="DELETE",
        proposed={}, summary=f"Delete role {role.name}",
        apply=lambda: apply_role_change(session, role, "DELETE", {}, caller.auth.user_id),
        organization_id=role.owner_organization_id)


def restore_role(rt: Runtime, session: Session, caller: Authorized, role_id: uuid.UUID,
                 version: int | None) -> ChangeResult:
    role = _editable_role(session, caller, role_id, version, include_deleted=True)
    if role.deleted_at is None:
        raise Conflict("This role is not deleted.", code="NOT_DELETED")
    if _name_taken(session, role.name, role.owner_organization_id, exclude=role.id):
        raise Conflict("Another role now uses this name.", code="ROLE_NAME_TAKEN")
    if session.scalar(select(Role.id).where(Role.role_code == role.role_code, Role.id != role.id)):
        raise Conflict("Another role now uses this code.", code="ROLE_CODE_TAKEN")
    return _submit_or_apply(
        rt, session, caller, entity_type="ROLE", entity=role, entity_version=role.version, action_type="RESTORE",
        proposed={}, summary=f"Restore role {role.name}",
        apply=lambda: apply_role_change(session, role, "RESTORE", {}, caller.auth.user_id),
        organization_id=role.owner_organization_id)


def propose_role_permissions(rt: Runtime, session: Session, caller: Authorized, role_id: uuid.UUID,
                             version: int | None, permission_ids: list[uuid.UUID]) -> ChangeResult:
    role = _editable_role(session, caller, role_id, version)
    current = set(session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)))
    ids = list(dict.fromkeys(permission_ids))
    # Only additions must be active; links the role already has (even to a since-disabled
    # permission, which grants nothing) may be kept or removed.
    _validate_permissions(session, [i for i in ids if i not in current])
    if role.is_system and not current.issubset(set(ids)):
        raise SystemRoleProtected("A system role can gain permissions but never lose them.")
    if current == set(ids):
        return ChangeResult("UNCHANGED", role)
    added, removed = len(set(ids) - current), len(current - set(ids))
    return _submit_or_apply(
        rt, session, caller, entity_type="ROLE_PERMISSIONS", entity=role, entity_version=role.version,
        action_type="UPDATE", proposed={"permission_ids": ids},
        summary=f"Role {role.name}: +{added} / -{removed} permissions",
        apply=lambda: apply_role_permissions(session, role, {"permission_ids": ids}, caller.auth.user_id),
        organization_id=role.owner_organization_id)


# ------------------------------------------------------------------ permissions
def create_permission(rt: Runtime, session: Session, caller: Authorized, *, resource_id: uuid.UUID,
                      action_id: uuid.UUID, description: str | None) -> ChangeResult:
    require_all_scope(caller)
    resource = get_or_404(session, Resource, resource_id, label="Resource")
    action = get_or_404(session, Action, action_id, label="Action")
    code = f"{resource.resource_code}.{action.action_code}"
    if session.scalar(select(Permission.id).where(Permission.permission_code == code)):
        raise Conflict("This permission already exists.", code="PERMISSION_EXISTS")
    pending = rt.approvals.is_required(session, "PERMISSION", None)
    permission = Permission(resource_id=resource.id, action_id=action.id, permission_code=code,
                            description=description, is_active=not pending, created_by=caller.auth.user_id,
                            updated_by=caller.auth.user_id)
    session.add(permission)
    session.flush()
    if not pending:
        audit(session, action="PERMISSION.CREATED", entity_type="PERMISSION", entity_id=permission.id,
              actor=caller.auth.user_id, after={"permission_code": code})
        return ChangeResult("APPLIED", permission)
    return _submit_or_apply(
        rt, session, caller, entity_type="PERMISSION", entity=permission, entity_version=permission_version(permission),
        action_type="CREATE", proposed={"permission_code": code}, summary=f"Create permission {code}",
        apply=lambda: None)


def _protected(permission: Permission) -> None:
    if permission.declared_by_service == "identity":
        raise ValidationFailed("Identity enforces this permission itself; it cannot be disabled or deleted.",
                               code="PERMISSION_PROTECTED")


def set_permission_status(rt: Runtime, session: Session, caller: Authorized, permission_id: uuid.UUID,
                          is_active: bool) -> ChangeResult:
    require_all_scope(caller)
    permission = get_or_404(session, Permission, permission_id, label="Permission")
    _protected(permission)
    if permission.is_active == is_active:
        return ChangeResult("UNCHANGED", permission)
    proposed = {"is_active": is_active}
    return _submit_or_apply(
        rt, session, caller, entity_type="PERMISSION", entity=permission,
        entity_version=permission_version(permission), action_type="STATUS_CHANGE", proposed=proposed,
        summary=f"{'Enable' if is_active else 'Disable'} permission {permission.permission_code}",
        apply=lambda: apply_permission_change(session, permission, "STATUS_CHANGE", proposed, caller.auth.user_id))


def delete_permission(rt: Runtime, session: Session, caller: Authorized, permission_id: uuid.UUID) -> ChangeResult:
    require_all_scope(caller)
    permission = get_or_404(session, Permission, permission_id, label="Permission")
    _protected(permission)
    return _submit_or_apply(
        rt, session, caller, entity_type="PERMISSION", entity=permission,
        entity_version=permission_version(permission), action_type="DELETE", proposed={},
        summary=f"Delete permission {permission.permission_code}",
        apply=lambda: apply_permission_change(session, permission, "DELETE", {}, caller.auth.user_id))


def declare_permissions(session: Session, service: str, codes: list[str]) -> tuple[list[str], list[str]]:
    """A service lists the permission codes it enforces. Known codes are marked enforced;
    unknown codes are reported, never created (creation goes through Maker-Checker)."""
    declared, unknown = [], []
    for code in sorted(set(codes)):
        permission = session.scalar(select(Permission).where(Permission.permission_code == code))
        if permission is None:
            unknown.append(code)
            continue
        permission.is_enforced, permission.declared_by_service = True, service
        declared.append(code)
    audit(session, action="PERMISSION.DECLARED", entity_type="PERMISSION", actor_type=ActorType.SERVICE,
          metadata={"service": service, "declared": declared, "unknown": unknown})
    return declared, unknown


# ------------------------------------------------------------------ catalogue (modules, resources, actions)
CATALOGUE = {"modules": (Module, "module_code"), "resources": (Resource, "resource_code"),
             "actions": (Action, "action_code")}


def create_catalogue_item(session: Session, caller: Authorized, kind: str, data: dict) -> Any:
    require_all_scope(caller)
    model, code_field = CATALOGUE[kind]
    code = data[code_field]
    if session.scalar(select(model.id).where(getattr(model, code_field) == code)):
        raise Conflict("This code already exists.", code="CODE_TAKEN")
    if kind == "resources":
        get_or_404(session, Module, data["module_id"], label="Module")
    item = model(**data, created_by=caller.auth.user_id, updated_by=caller.auth.user_id)
    session.add(item)
    session.flush()
    audit(session, action=f"CATALOGUE.{kind[:-1].upper()}_CREATED", entity_type=kind[:-1].upper(), entity_id=item.id,
          actor=caller.auth.user_id, after={k: v for k, v in data.items()})
    return item


def update_catalogue_item(session: Session, caller: Authorized, kind: str, item_id: uuid.UUID, data: dict) -> Any:
    require_all_scope(caller)
    model, _ = CATALOGUE[kind]
    item = get_or_404(session, model, item_id, label=kind[:-1].capitalize())
    before = {k: getattr(item, k) for k in data}
    for key, value in data.items():
        setattr(item, key, value)
    item.updated_by = caller.auth.user_id
    session.flush()
    if "is_active" in data and before.get("is_active") != data["is_active"]:
        # A catalogue switch changes what many roles grant: invalidate every holder's tokens.
        users = set(session.scalars(select(UserRoleAssignment.user_id).where(UserRoleAssignment.status != "REVOKED")))
        bump_authz(session, users)
    audit(session, action=f"CATALOGUE.{kind[:-1].upper()}_UPDATED", entity_type=kind[:-1].upper(), entity_id=item.id,
          actor=caller.auth.user_id, before=before, after=data)
    return item


# ------------------------------------------------------------------ matrix
def matrix(session: Session, role_id: uuid.UUID | None) -> dict:
    """Resources (rows) x actions (columns), built entirely from the database."""
    granted: set[uuid.UUID] = set()
    role = None
    if role_id:
        role = session.get(Role, role_id)
        if role is None:
            raise NotFound("Role not found.")
        granted = set(session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role_id)))
    permissions = session.scalars(select(Permission)).all()
    by_cell = {(p.resource_id, p.action_id): p for p in permissions}
    used_actions = {p.action_id for p in permissions}
    actions = [a for a in session.scalars(select(Action).order_by(Action.action_code)) if a.id in used_actions]
    rows = []
    for module, resource in session.execute(select(Module, Resource).join(Resource, Resource.module_id == Module.id)
                                            .order_by(Module.sort_order, Module.name, Resource.resource_code)):
        cells = []
        for action in actions:
            p = by_cell.get((resource.id, action.id))
            cells.append(None if p is None else {
                "permission_id": str(p.id), "permission_code": p.permission_code, "is_active": p.is_active,
                "is_enforced": p.is_enforced, "granted": p.id in granted})
        rows.append({"module_code": module.module_code, "module_name": module.name, "resource_id": str(resource.id),
                     "resource_code": resource.resource_code, "resource_name": resource.name,
                     "is_active": resource.is_active and module.is_active, "cells": cells})
    return {"role": None if role is None else {"id": str(role.id), "name": role.name, "role_code": role.role_code,
                                                "version": role.version, "status": role.status,
                                                "is_system": role.is_system},
            "columns": [{"action_id": str(a.id), "action_code": a.action_code, "name": a.name} for a in actions],
            "rows": rows}
