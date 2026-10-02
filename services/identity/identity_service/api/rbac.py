"""Roles, permissions, catalogue and the permission matrix."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from identity_service.api.admin import IfMatch, Paging, _etag, _version, change_out, paginate
from identity_service.api.schemas import (
    ActionIn,
    ActionOut,
    CatalogueUpdateIn,
    ChangeOut,
    ModuleIn,
    ModuleOut,
    PermissionCreateIn,
    PermissionOut,
    PermissionStatusIn,
    ResourceIn,
    ResourceOut,
    RoleCreateIn,
    RoleDetailOut,
    RoleOut,
    RolePermissionsIn,
    RoleUpdateIn,
    StatusIn,
    VersionIn,
)
from identity_service.approvals import permission_version
from identity_service.common import get_or_404, parse_if_match
from identity_service.models import (
    Action,
    ApprovalRequest,
    Module,
    Permission,
    Resource,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from identity_service.runtime import Runtime, db_session, require, runtime
from identity_service.services import rbac as svc
from js_auth.context import Authorized
from js_core.errors import NotFound
from js_core.responses import Page

router = APIRouter(tags=["rbac"])
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]


# ------------------------------------------------------------------ roles
@router.get("/roles", response_model=Page[RoleOut])
def list_roles(session: Db, paging: Paging, q: str | None = Query(default=None, max_length=100),
               status_: str | None = Query(default=None, alias="status"), include_deleted: bool = False,
               caller: Authorized = Depends(require("ROLE.VIEW"))) -> Page[RoleOut]:
    stmt = select(Role).where(svc.visible_roles_filter(caller))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Role.name).like(like) | func.lower(Role.role_code).like(like))
    if status_:
        stmt = stmt.where(Role.status == status_)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    rows, total = paginate(session, stmt, paging, [Role.is_system.desc(), Role.name])
    return Page(items=[RoleOut.model_validate(r[0]) for r in rows], page=paging.page, size=paging.size, total=total)


def _role_detail(session: Session, role: Role) -> RoleDetailOut:
    perms = session.execute(select(Permission.id, Permission.permission_code).join(
        RolePermission, RolePermission.permission_id == Permission.id).where(RolePermission.role_id == role.id)
        .order_by(Permission.permission_code).execution_options(include_deleted=True)).all()
    holders = session.scalar(select(func.count()).select_from(UserRoleAssignment).where(
        UserRoleAssignment.role_id == role.id, UserRoleAssignment.status == "ACTIVE")) or 0
    pending = session.scalar(select(ApprovalRequest).where(
        ApprovalRequest.entity_id == role.id, ApprovalRequest.status == "PENDING"))
    out = RoleDetailOut.model_validate(role)
    out.permission_ids = [p[0] for p in perms]
    out.permission_codes = [p[1] for p in perms]
    out.holders = holders
    out.pending_request = None if pending is None else {
        "id": str(pending.id), "request_number": pending.request_number, "entity_type": pending.entity_type,
        "action_type": pending.action_type, "summary": pending.change_summary,
        "maker_user_id": str(pending.maker_user_id)}
    return out


@router.get("/roles/{role_id}", response_model=RoleDetailOut)
def get_role(role_id: uuid.UUID, response: Response, session: Db,
             caller: Authorized = Depends(require("ROLE.VIEW"))) -> RoleDetailOut:
    role = session.scalar(select(Role).where(Role.id == role_id, svc.visible_roles_filter(caller))
                          .execution_options(include_deleted=True))
    if role is None:
        raise NotFound("Role not found.")
    _etag(response, role.version)
    return _role_detail(session, role)


@router.post("/roles", response_model=ChangeOut, status_code=status.HTTP_201_CREATED)
def create_role(body: RoleCreateIn, rt: Rt, session: Db,
                caller: Authorized = Depends(require("ROLE.CREATE"))) -> ChangeOut:
    result = svc.create_role(rt, session, caller, name=body.name, description=body.description,
                             role_code=body.role_code, permission_ids=body.permission_ids,
                             owner_organization_id=body.owner_organization_id)
    session.commit()
    return change_out(result)


@router.put("/roles/{role_id}", response_model=ChangeOut)
def update_role(role_id: uuid.UUID, body: RoleUpdateIn, rt: Rt, session: Db, if_match: IfMatch = None,
                caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.update_role(rt, session, caller, role_id, _version(body.version, if_match), name=body.name,
                             description=body.description)
    session.commit()
    return change_out(result)


@router.put("/roles/{role_id}/permissions", response_model=ChangeOut)
def set_role_permissions(role_id: uuid.UUID, body: RolePermissionsIn, rt: Rt, session: Db, if_match: IfMatch = None,
                         caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.propose_role_permissions(rt, session, caller, role_id, _version(body.version, if_match),
                                          body.permission_ids)
    session.commit()
    return change_out(result)


@router.patch("/roles/{role_id}/status", response_model=ChangeOut)
def set_role_status(role_id: uuid.UUID, body: StatusIn, rt: Rt, session: Db, if_match: IfMatch = None,
                    caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.set_role_status(rt, session, caller, role_id, _version(body.version, if_match), body.status)
    session.commit()
    return change_out(result)


@router.delete("/roles/{role_id}", response_model=ChangeOut)
def delete_role(role_id: uuid.UUID, rt: Rt, session: Db, if_match: IfMatch = None,
                caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.delete_role(rt, session, caller, role_id, parse_if_match(if_match))
    session.commit()
    return change_out(result)


@router.post("/roles/{role_id}/restore", response_model=ChangeOut)
def restore_role(role_id: uuid.UUID, body: VersionIn, rt: Rt, session: Db, if_match: IfMatch = None,
                 caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.restore_role(rt, session, caller, role_id, _version(body.version, if_match))
    session.commit()
    return change_out(result)


# ------------------------------------------------------------------ permissions
def _permission_rows(session: Session, stmt) -> list[PermissionOut]:
    return [PermissionOut(id=p.id, permission_code=p.permission_code, description=p.description,
                          module_code=m.module_code, resource_code=r.resource_code, action_code=a.action_code,
                          is_active=p.is_active, is_enforced=p.is_enforced, declared_by_service=p.declared_by_service,
                          version=permission_version(p))
            for p, r, a, m in session.execute(stmt)]


def _permission_select():
    return (select(Permission, Resource, Action, Module).join(Resource, Resource.id == Permission.resource_id)
            .join(Action, Action.id == Permission.action_id).join(Module, Module.id == Resource.module_id))


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(session: Db, module: str | None = None, resource: str | None = None,
                     _: Authorized = Depends(require("ROLE.VIEW"))) -> list[PermissionOut]:
    stmt = _permission_select()
    if module:
        stmt = stmt.where(Module.module_code == module)
    if resource:
        stmt = stmt.where(Resource.resource_code == resource)
    return _permission_rows(session, stmt.order_by(Module.sort_order, Permission.permission_code))


@router.post("/permissions", response_model=ChangeOut, status_code=status.HTTP_201_CREATED)
def create_permission(body: PermissionCreateIn, rt: Rt, session: Db,
                      caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.create_permission(rt, session, caller, resource_id=body.resource_id, action_id=body.action_id,
                                   description=body.description)
    session.commit()
    return change_out(result)


@router.patch("/permissions/{permission_id}/status", response_model=ChangeOut)
def set_permission_status(permission_id: uuid.UUID, body: PermissionStatusIn, rt: Rt, session: Db,
                          caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.set_permission_status(rt, session, caller, permission_id, body.is_active)
    session.commit()
    return change_out(result)


@router.delete("/permissions/{permission_id}", response_model=ChangeOut)
def delete_permission(permission_id: uuid.UUID, rt: Rt, session: Db,
                      caller: Authorized = Depends(require("ROLE.EDIT"))) -> ChangeOut:
    result = svc.delete_permission(rt, session, caller, permission_id)
    session.commit()
    return change_out(result)


# ------------------------------------------------------------------ catalogue
@router.get("/modules", response_model=list[ModuleOut])
def list_modules(session: Db, _: Authorized = Depends(require("ROLE.VIEW"))) -> list[ModuleOut]:
    return [ModuleOut.model_validate(m) for m in session.scalars(select(Module).order_by(Module.sort_order, Module.name))]


@router.post("/modules", response_model=ModuleOut, status_code=status.HTTP_201_CREATED)
def create_module(body: ModuleIn, session: Db, caller: Authorized = Depends(require("ROLE.EDIT"))) -> ModuleOut:
    item = svc.create_catalogue_item(session, caller, "modules", body.model_dump())
    session.commit()
    return ModuleOut.model_validate(item)


@router.get("/resources", response_model=list[ResourceOut])
def list_resources(session: Db, module_id: uuid.UUID | None = None,
                   _: Authorized = Depends(require("ROLE.VIEW"))) -> list[ResourceOut]:
    stmt = select(Resource).order_by(Resource.resource_code)
    if module_id:
        stmt = stmt.where(Resource.module_id == module_id)
    return [ResourceOut.model_validate(r) for r in session.scalars(stmt)]


@router.post("/resources", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
def create_resource(body: ResourceIn, session: Db, caller: Authorized = Depends(require("ROLE.EDIT"))) -> ResourceOut:
    item = svc.create_catalogue_item(session, caller, "resources", body.model_dump())
    session.commit()
    return ResourceOut.model_validate(item)


@router.get("/actions", response_model=list[ActionOut])
def list_actions(session: Db, _: Authorized = Depends(require("ROLE.VIEW"))) -> list[ActionOut]:
    return [ActionOut.model_validate(a) for a in session.scalars(select(Action).order_by(Action.action_code))]


@router.post("/actions", response_model=ActionOut, status_code=status.HTTP_201_CREATED)
def create_action(body: ActionIn, session: Db, caller: Authorized = Depends(require("ROLE.EDIT"))) -> ActionOut:
    item = svc.create_catalogue_item(session, caller, "actions", body.model_dump())
    session.commit()
    return ActionOut.model_validate(item)


def _update_item(session: Session, caller: Authorized, kind: str, item_id: uuid.UUID, body: CatalogueUpdateIn):
    data = body.model_dump(exclude_unset=True)
    if kind == "actions":
        data.pop("description", None)
    item = svc.update_catalogue_item(session, caller, kind, item_id, data)
    session.commit()
    return item


@router.patch("/modules/{item_id}", response_model=ModuleOut)
def update_module(item_id: uuid.UUID, body: CatalogueUpdateIn, session: Db,
                  caller: Authorized = Depends(require("ROLE.EDIT"))) -> ModuleOut:
    return ModuleOut.model_validate(_update_item(session, caller, "modules", item_id, body))


@router.patch("/resources/{item_id}", response_model=ResourceOut)
def update_resource(item_id: uuid.UUID, body: CatalogueUpdateIn, session: Db,
                    caller: Authorized = Depends(require("ROLE.EDIT"))) -> ResourceOut:
    return ResourceOut.model_validate(_update_item(session, caller, "resources", item_id, body))


@router.patch("/actions/{item_id}", response_model=ActionOut)
def update_action(item_id: uuid.UUID, body: CatalogueUpdateIn, session: Db,
                  caller: Authorized = Depends(require("ROLE.EDIT"))) -> ActionOut:
    return ActionOut.model_validate(_update_item(session, caller, "actions", item_id, body))


# ------------------------------------------------------------------ matrix
@router.get("/rbac/matrix")
def rbac_matrix(session: Db, role_id: uuid.UUID | None = None,
                caller: Authorized = Depends(require("ROLE.VIEW"))) -> dict:
    if role_id:
        role = get_or_404(session, Role, role_id, label="Role")
        if not (role.owner_organization_id is None or caller.allows_organization(role.owner_organization_id)):
            raise NotFound("Role not found.")
    return svc.matrix(session, role_id)
