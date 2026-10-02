"""Organizations, members, users and user role assignments."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from identity_service.api.schemas import (
    ApprovalBrief,
    AssignIn,
    AssignmentOut,
    ChangeOut,
    IdentityOut,
    MemberAddIn,
    MemberOut,
    OrganizationOut,
    RevokeIn,
    StatusIn,
    TemporaryPasswordOut,
    UserBrief,
    UserCreatedOut,
    UserCreateIn,
    UserDetailOut,
    UserOut,
    UserStatusIn,
    UserUpdateIn,
)
from identity_service.common import parse_if_match
from identity_service.models import AuthIdentity, Organization, OrganizationMembership, User
from identity_service.runtime import Runtime, db_session, require, runtime
from identity_service.services import directory as svc
from js_auth.context import Authorized
from js_core.responses import Page, PageParams, page_params

router = APIRouter()
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]
Paging = Annotated[PageParams, Depends(page_params)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def paginate(session: Session, stmt, params: PageParams, order_by) -> tuple[list, int]:
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.execute(stmt.order_by(*order_by).offset(params.offset).limit(params.size)).all()
    return rows, total


def _version(body_version: int | None, if_match: str | None) -> int | None:
    return body_version if body_version is not None else parse_if_match(if_match)


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


def change_out(result) -> ChangeOut:
    request = result.approval_request
    return ChangeOut(status=result.status, entity_id=result.entity.id,
                     approval_request=ApprovalBrief.model_validate(request) if request is not None else None)


# ------------------------------------------------------------------ organizations
@router.get("/organizations", response_model=Page[OrganizationOut], tags=["organizations"])
def list_organizations(session: Db, paging: Paging, q: str | None = None,
                       organization_type: str | None = Query(default=None, alias="type"),
                       status_: str | None = Query(default=None, alias="status"),
                       caller: Authorized = Depends(require("ORGANIZATION.VIEW"))) -> Page[OrganizationOut]:
    stmt = svc.organization_query(caller, q, organization_type, status_)
    rows, total = paginate(session, stmt, paging, [Organization.is_platform.desc(), Organization.name])
    return Page(items=[OrganizationOut.model_validate(r[0]) for r in rows], page=paging.page, size=paging.size,
                total=total)


@router.get("/organizations/{organization_id}", response_model=OrganizationOut, tags=["organizations"])
def get_organization(organization_id: uuid.UUID, response: Response, session: Db,
                     caller: Authorized = Depends(require("ORGANIZATION.VIEW"))) -> OrganizationOut:
    org = svc.visible_organization(session, caller, organization_id)
    _etag(response, org.version)
    return OrganizationOut.model_validate(org)


@router.patch("/organizations/{organization_id}/status", response_model=OrganizationOut, tags=["organizations"])
def set_organization_status(organization_id: uuid.UUID, body: StatusIn, session: Db, if_match: IfMatch = None,
                            caller: Authorized = Depends(require("ORGANIZATION.EDIT"))) -> OrganizationOut:
    org = svc.set_organization_status(session, caller, organization_id, _version(body.version, if_match), body.status)
    session.commit()
    return OrganizationOut.model_validate(org)


@router.get("/organizations/{organization_id}/members", response_model=Page[MemberOut], tags=["organizations"])
def list_members(organization_id: uuid.UUID, session: Db, paging: Paging,
                 status_: str | None = Query(default=None, alias="status"),
                 caller: Authorized = Depends(require("USER.VIEW"))) -> Page[MemberOut]:
    svc.visible_organization(session, caller, organization_id)
    rows, total = paginate(session, svc.membership_query(organization_id, status_), paging, [User.display_name])
    return Page(items=[MemberOut(membership_id=m.id, user=UserBrief.model_validate(u), status=m.status,
                                 joined_at=m.joined_at, version=m.version) for m, u in rows],
                page=paging.page, size=paging.size, total=total)


@router.post("/organizations/{organization_id}/members", response_model=MemberOut,
             status_code=status.HTTP_201_CREATED, tags=["organizations"])
def add_member(organization_id: uuid.UUID, body: MemberAddIn, session: Db,
               caller: Authorized = Depends(require("USER.CREATE"))) -> MemberOut:
    membership = svc.add_member(session, caller, organization_id, email=body.email, mobile=body.mobile)
    session.commit()
    user = session.get(User, membership.user_id)
    return MemberOut(membership_id=membership.id, user=UserBrief.model_validate(user), status=membership.status,
                     joined_at=membership.joined_at, version=membership.version)


@router.patch("/organizations/{organization_id}/members/{membership_id}", response_model=MemberOut,
              tags=["organizations"])
def set_member_status(organization_id: uuid.UUID, membership_id: uuid.UUID, body: StatusIn, session: Db,
                      if_match: IfMatch = None, caller: Authorized = Depends(require("USER.EDIT"))) -> MemberOut:
    membership = svc.set_membership_status(session, caller, organization_id, membership_id,
                                           _version(body.version, if_match), body.status)
    session.commit()
    user = session.get(User, membership.user_id)
    return MemberOut(membership_id=membership.id, user=UserBrief.model_validate(user), status=membership.status,
                     joined_at=membership.joined_at, version=membership.version)


@router.delete("/organizations/{organization_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT,
               tags=["organizations"])
def delete_member(organization_id: uuid.UUID, membership_id: uuid.UUID, session: Db, if_match: IfMatch = None,
                  caller: Authorized = Depends(require("USER.DISABLE"))) -> Response:
    svc.delete_membership(session, caller, organization_id, membership_id, parse_if_match(if_match))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ users
@router.get("/users", response_model=Page[UserOut], tags=["users"])
def list_users(session: Db, paging: Paging, q: str | None = Query(default=None, max_length=100),
               status_: str | None = Query(default=None, alias="status"),
               caller: Authorized = Depends(require("USER.VIEW"))) -> Page[UserOut]:
    rows, total = paginate(session, svc.user_query(caller, q, status_), paging, [User.display_name, User.id])
    return Page(items=[UserOut.model_validate(r[0]) for r in rows], page=paging.page, size=paging.size, total=total)


@router.post("/users", response_model=UserCreatedOut, status_code=status.HTTP_201_CREATED, tags=["users"])
def create_user(body: UserCreateIn, session: Db,
                caller: Authorized = Depends(require("USER.CREATE"))) -> UserCreatedOut:
    user, membership, password = svc.create_user(session, caller, display_name=body.display_name, email=body.email,
                                                 organization_id=body.organization_id)
    session.commit()
    return UserCreatedOut(user=UserOut.model_validate(user), membership_id=membership.id, temporary_password=password)


@router.get("/users/{user_id}", response_model=UserDetailOut, tags=["users"])
def get_user(user_id: uuid.UUID, response: Response, session: Db,
             caller: Authorized = Depends(require("USER.VIEW"))) -> UserDetailOut:
    user = svc.visible_user(session, caller, user_id)
    identities = session.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).all()
    memberships = session.execute(
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(OrganizationMembership.user_id == user.id)).all()
    out = UserDetailOut.model_validate(user)
    out.identities = [IdentityOut.of(i) for i in identities]
    out.memberships = [{"membership_id": str(m.id), "organization_id": str(o.id), "organization_name": o.name,
                        "organization_code": o.organization_code, "is_platform": o.is_platform, "status": m.status,
                        "version": m.version}
                       for m, o in memberships if caller.allows_organization(o.id)]
    _etag(response, user.version)
    return out


@router.put("/users/{user_id}", response_model=UserOut, tags=["users"])
def update_user(user_id: uuid.UUID, body: UserUpdateIn, session: Db, if_match: IfMatch = None,
                caller: Authorized = Depends(require("USER.EDIT"))) -> UserOut:
    user = svc.update_user(session, caller, user_id, _version(body.version, if_match), body.display_name)
    session.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}/status", response_model=UserOut, tags=["users"])
def set_user_status(user_id: uuid.UUID, body: UserStatusIn, session: Db,
                    caller: Authorized = Depends(require("USER.DISABLE"))) -> UserOut:
    user = svc.set_user_status(session, caller, user_id, body.status, body.reason)
    session.commit()
    session.refresh(user)
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/password/reset", response_model=TemporaryPasswordOut, tags=["users"])
def reset_password(user_id: uuid.UUID, session: Db,
                   caller: Authorized = Depends(require("USER.EDIT"))) -> TemporaryPasswordOut:
    password = svc.reset_password(session, caller, user_id)
    session.commit()
    return TemporaryPasswordOut(temporary_password=password)


# ------------------------------------------------------------------ user roles
@router.get("/users/{user_id}/roles", response_model=list[AssignmentOut], tags=["users"])
def list_user_roles(user_id: uuid.UUID, session: Db,
                    caller: Authorized = Depends(require("ROLE.VIEW"))) -> list[AssignmentOut]:
    return [AssignmentOut(
        id=a.id, role={"id": str(r.id), "name": r.name, "role_code": r.role_code, "status": r.status,
                       "deleted": r.deleted_at is not None},
        membership_id=a.membership_id,
        organization=None if o is None else {"id": str(o.id), "name": o.name, "is_platform": o.is_platform},
        scope_type=a.scope_type, status=a.status, valid_from=a.valid_from, valid_until=a.valid_until,
        revoked_at=a.revoked_at, version=a.version) for a, r, _m, o in svc.assignments_of(session, caller, user_id)]


@router.post("/users/{user_id}/roles", response_model=ChangeOut, status_code=status.HTTP_201_CREATED, tags=["users"])
def assign_role(user_id: uuid.UUID, body: AssignIn, rt: Rt, session: Db,
                caller: Authorized = Depends(require("ROLE.ASSIGN"))) -> ChangeOut:
    result = svc.assign_role(rt, session, caller, user_id, role_id=body.role_id, membership_id=body.membership_id,
                             scope_type=body.scope_type, valid_until=body.valid_until)
    session.commit()
    return change_out(result)


@router.delete("/users/{user_id}/roles/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["users"])
def revoke_role(user_id: uuid.UUID, assignment_id: uuid.UUID, session: Db, body: RevokeIn | None = None,
                caller: Authorized = Depends(require("ROLE.ASSIGN"))) -> Response:
    svc.revoke_role(session, caller, user_id, assignment_id, body.reason if body else None)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
