"""/auth/* and /me/* routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from identity_service.api.schemas import (
    IdentityOut,
    MeOut,
    MyOrganization,
    OrganizationBrief,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    PasswordChangeIn,
    PasswordLoginIn,
    PermissionsOut,
    SwitchOrganizationIn,
    SwitchOut,
    TokenOut,
    UserBrief,
)
from identity_service.models import AuthIdentity, Organization, Role, User, UserRoleAssignment
from identity_service.runtime import Runtime, authenticated, db_session, runtime
from identity_service.services import auth as svc
from js_auth.context import AuthContext, EffectivePermissions
from js_core.errors import Unauthenticated

router = APIRouter(tags=["auth"])
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]


def my_organizations(session: Session, user_id) -> list[MyOrganization]:
    result = []
    for membership, org in svc.active_memberships(session, user_id):
        roles = session.scalars(select(Role.name).join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id).where(
            UserRoleAssignment.membership_id == membership.id, UserRoleAssignment.status == "ACTIVE",
            Role.status == "ACTIVE")).all()
        result.append(MyOrganization(organization=OrganizationBrief.model_validate(org), membership_id=membership.id,
                                     membership_status=membership.status, roles=sorted(roles)))
    return result


def _token_out(session: Session, signed: svc.SignedIn) -> TokenOut:
    return TokenOut(access_token=signed.access_token, expires_at=signed.expires_at,
                    password_change_required=signed.password_change_required,
                    user=UserBrief.model_validate(signed.user),
                    active_organization_id=signed.user_session.active_organization_id,
                    organizations=my_organizations(session, signed.user.id))


def _set_refresh_cookie(rt: Runtime, response: Response, token: str | None) -> None:
    s = rt.settings
    if token is None:
        return
    response.set_cookie(s.refresh_cookie_name, token, max_age=s.refresh_ttl_days * 86400, httponly=True,
                        secure=s.refresh_cookie_secure, samesite=s.refresh_cookie_samesite,  # type: ignore[arg-type]
                        path=s.refresh_cookie_path)


def _clear_refresh_cookie(rt: Runtime, response: Response) -> None:
    s = rt.settings
    response.delete_cookie(s.refresh_cookie_name, path=s.refresh_cookie_path, httponly=True,
                           secure=s.refresh_cookie_secure, samesite=s.refresh_cookie_samesite)  # type: ignore[arg-type]


def permissions_out(organization_id, effective: EffectivePermissions) -> PermissionsOut:
    return PermissionsOut(organization_id=organization_id, authz_version=effective.authz_version,
                          roles=list(effective.roles),
                          permissions={code: scope.value for code, scope in sorted(effective.scopes.items())})


# ------------------------------------------------------------------ sign-in
@router.post("/auth/password/login", response_model=TokenOut)
def password_login(body: PasswordLoginIn, response: Response, rt: Rt, session: Db) -> TokenOut:
    signed = svc.password_login(rt, session, body.email, body.password)
    out = _token_out(session, signed)
    session.commit()
    _set_refresh_cookie(rt, response, signed.refresh_token)
    return out


@router.post("/auth/otp/request", response_model=OtpRequestOut, status_code=status.HTTP_201_CREATED)
def otp_request(body: OtpRequestIn, rt: Rt, session: Db) -> OtpRequestOut:
    result = svc.request_otp(rt, session, body.mobile, body.purpose)
    session.commit()
    return OtpRequestOut(challenge_id=result.challenge_id, expires_at=result.expires_at,
                         resend_after_seconds=result.resend_after, sent_to=result.sent_to)


@router.post("/auth/otp/verify", response_model=TokenOut)
def otp_verify(body: OtpVerifyIn, response: Response, rt: Rt, session: Db) -> TokenOut:
    signed = svc.verify_otp(rt, session, body.challenge_id, body.mobile, body.code)
    out = _token_out(session, signed)
    session.commit()
    _set_refresh_cookie(rt, response, signed.refresh_token)
    return out


@router.post("/auth/password/change", response_model=TokenOut)
def password_change(body: PasswordChangeIn, rt: Rt, session: Db,
                    ctx: AuthContext = Depends(authenticated(allow_password_change=True))) -> TokenOut:
    signed = svc.change_password(rt, session, ctx, body.current_password, body.new_password)
    out = _token_out(session, signed)
    session.commit()
    return out


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, rt: Rt, session: Db) -> TokenOut:
    try:
        signed = svc.refresh(rt, session, request.cookies.get(rt.settings.refresh_cookie_name))
    except Unauthenticated:
        _clear_refresh_cookie(rt, response)
        raise
    out = _token_out(session, signed)
    session.commit()
    _set_refresh_cookie(rt, response, signed.refresh_token)
    return out


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, rt: Rt, session: Db,
           ctx: AuthContext = Depends(authenticated(allow_password_change=True))) -> Response:
    svc.logout(session, ctx)
    session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_refresh_cookie(rt, response)
    return response


# ------------------------------------------------------------------ me
@router.get("/me", response_model=MeOut)
def me(session: Db, ctx: AuthContext = Depends(authenticated(allow_password_change=True))) -> MeOut:
    user = session.get(User, ctx.user_id)
    if user is None:
        raise Unauthenticated()
    org = session.get(Organization, ctx.organization_id) if ctx.organization_id else None
    identities = session.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).all()
    return MeOut(user=UserBrief.model_validate(user),
                 active_organization=OrganizationBrief.model_validate(org) if org else None,
                 authz_version=user.authz_version, password_change_required=ctx.password_change_required,
                 identities=[IdentityOut.of(i) for i in identities], last_login_at=user.last_login_at)


@router.get("/me/organizations", response_model=list[MyOrganization])
def me_organizations(session: Db, ctx: AuthContext = Depends(authenticated())) -> list[MyOrganization]:
    return my_organizations(session, ctx.user_id)


@router.post("/me/organization/switch", response_model=SwitchOut)
def switch_organization(body: SwitchOrganizationIn, rt: Rt, session: Db,
                        ctx: AuthContext = Depends(authenticated())) -> SwitchOut:
    signed, effective = svc.switch_organization(rt, session, ctx, body.organization_id)
    out = _token_out(session, signed)
    session.commit()
    return SwitchOut(token=out, permissions=permissions_out(body.organization_id, effective))


@router.get("/me/permissions", response_model=PermissionsOut)
def me_permissions(rt: Rt, ctx: AuthContext = Depends(authenticated())) -> PermissionsOut:
    """For the React UI only (show or hide controls). Every API still checks on the server."""
    # TOKEN_STALE (401) when the token is older than the user's current access: the client refreshes.
    return permissions_out(ctx.organization_id, rt.authenticator.permissions(ctx))
