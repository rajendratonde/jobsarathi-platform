"""Service-to-service routes (X-Service-Token), JWKS and the development OTP sink."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from identity_service.api.auth import permissions_out
from identity_service.api.schemas import (
    DeclareIn,
    DeclareOut,
    InternalOrganizationIn,
    InternalOrganizationOut,
    PermissionsOut,
)
from identity_service.authz import resolve
from identity_service.runtime import Runtime, db_session, runtime, service_caller
from identity_service.security import normalize_mobile
from identity_service.services import directory, rbac
from js_core.errors import NotFound

internal = APIRouter(prefix="/internal", tags=["internal"])
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]


@internal.get("/authz/users/{user_id}", response_model=PermissionsOut)
def authz_for_user(user_id: uuid.UUID, session: Db, organization_id: uuid.UUID | None = None,
                   _: str = Depends(service_caller())) -> PermissionsOut:
    """Callers cache the answer by (user, organization, authz_version) for at most 60 s."""
    effective = resolve(session, user_id, organization_id)
    if effective.authz_version < 0:
        raise NotFound("User not found.")
    return permissions_out(organization_id, effective)


@internal.post("/organizations", response_model=InternalOrganizationOut, status_code=201)
def create_organization(body: InternalOrganizationIn, session: Db,
                        service: str = Depends(service_caller("employer"))) -> InternalOrganizationOut:
    org, membership = directory.create_organization(session, name=body.name, organization_type=body.organization_type,
                                                    owner_user_id=body.owner_user_id, actor_service=service)
    session.commit()
    return InternalOrganizationOut(organization_id=org.id, organization_code=org.organization_code,
                                   membership_id=membership.id)


@internal.post("/permissions/declare", response_model=DeclareOut)
def declare_permissions(body: DeclareIn, session: Db, service: str = Depends(service_caller())) -> DeclareOut:
    declared, unknown = rbac.declare_permissions(session, service, body.codes)
    session.commit()
    return DeclareOut(declared=declared, unknown=unknown)


well_known = APIRouter(tags=["auth"])


@well_known.get("/.well-known/jwks.json")
def jwks(rt: Rt) -> dict:
    return rt.ring.jwks()


dev = APIRouter(prefix="/dev", tags=["development only"])


@dev.get("/otp")
def dev_latest_otp(rt: Rt, mobile: str = Query(min_length=10, max_length=20)) -> dict:
    """Mounted only when OTP_DEV_SINK=true, which Settings refuses outside local/development/test."""
    if rt.dev_sink is None or not rt.settings.app_env.allows_dev_tools:
        raise NotFound()
    code = rt.dev_sink.get(normalize_mobile(mobile, rt.settings.otp_country_code))
    if code is None:
        raise NotFound("No recent code for this number.")
    return {"code": code, "warning": "Development sink. Never available in production."}
