"""Sign-in, sessions, OTP, password change and organization switch."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from identity_service.authz import resolve
from identity_service.common import audit, event
from identity_service.models import (
    AuthIdentity,
    Organization,
    OrganizationMembership,
    OtpChallenge,
    Role,
    User,
    UserRoleAssignment,
    UserSession,
)
from identity_service.runtime import Runtime
from identity_service.security import (
    check_password_policy,
    hash_password,
    mask_mobile,
    needs_rehash,
    new_otp_code,
    new_refresh_token,
    normalize_mobile,
    sha256_hex,
    verify_password,
)
from js_audit import AuditResult
from js_auth.context import AuthContext, EffectivePermissions, Scope
from js_auth.tokens import issue_access_token
from js_core import context
from js_core.errors import (
    DependencyUnavailable,
    FieldError,
    IntegrationDisabled,
    Locked,
    PermissionDenied,
    RateLimited,
    Unauthenticated,
    ValidationFailed,
)
from js_core.ids import uuid7
from js_integration.result import IntegrationStatus
from js_integration.sms import DisabledSmsSender


class InvalidCredentials(Unauthenticated):
    code, message = "INVALID_CREDENTIALS", "The email or password is not correct."


class AccountDisabled(PermissionDenied):
    code, message = "ACCOUNT_DISABLED", "This account cannot sign in. Contact support."


class OtpInvalid(Unauthenticated):
    code, message = "OTP_INVALID", "The code is not correct."


class OtpExpired(Unauthenticated):
    code, message = "OTP_EXPIRED", "The code has expired. Request a new one."


class OtpLocked(Locked):
    code, message = "OTP_LOCKED", "Too many wrong attempts. Request a new code."


class NoMembership(PermissionDenied):
    code, message = "NO_ACTIVE_MEMBERSHIP", "You are not an active member of this organization."


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SignedIn:
    access_token: str
    expires_at: int
    refresh_token: str | None
    user: User
    user_session: UserSession
    password_change_required: bool


# ------------------------------------------------------------------ sessions and tokens
def active_memberships(session: Session, user_id: uuid.UUID) -> list[tuple[OrganizationMembership, Organization]]:
    rows = session.execute(
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(OrganizationMembership.user_id == user_id, OrganizationMembership.status == "ACTIVE",
               Organization.status == "ACTIVE")
        .order_by(Organization.is_platform.desc(), Organization.name))
    return [(m, o) for m, o in rows]


def _default_organization(session: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    """One active membership: use it. Several: the client asks the user to choose."""
    memberships = active_memberships(session, user_id)
    return memberships[0][1].id if len(memberships) == 1 else None


def issue_token(rt: Runtime, user: User, user_session: UserSession, *, password_change_required: bool) -> tuple[str, int]:
    return issue_access_token(rt.ring, rt.tokens, user_id=user.id, session_id=user_session.id,
                              organization_id=user_session.active_organization_id, authz_version=user.authz_version,
                              password_change_required=password_change_required)


def _open_session(rt: Runtime, session: Session, user: User, identity: AuthIdentity) -> SignedIn:
    ctx = context.current()
    refresh, refresh_hash = new_refresh_token()
    user_session = UserSession(
        user_id=user.id, auth_identity_id=identity.id, refresh_token_hash=refresh_hash,
        active_organization_id=_default_organization(session, user.id),
        expires_at=_now() + timedelta(days=rt.settings.refresh_ttl_days),
        ip_address=ctx.client_ip, user_agent=(ctx.user_agent or "")[:300] or None)
    session.add(user_session)
    user.last_login_at = _now()
    session.flush()
    pcr = identity.password_change_required
    token, exp = issue_token(rt, user, user_session, password_change_required=pcr)
    return SignedIn(token, exp, refresh, user, user_session, pcr)


def _password_change_pending(session: Session, user_session: UserSession) -> bool:
    identity = session.get(AuthIdentity, user_session.auth_identity_id)
    return bool(identity and identity.password_change_required)


# ------------------------------------------------------------------ password sign-in
def password_login(rt: Runtime, session: Session, email: str, password: str) -> SignedIn:
    identifier = email.strip().lower()
    identity = session.scalar(select(AuthIdentity).where(
        AuthIdentity.identity_type == "EMAIL_PASSWORD", AuthIdentity.identifier == identifier).with_for_update())
    s = rt.settings
    if identity is None:
        verify_password(None, password)  # same work as a real check
        audit(session, action="AUTH.LOGIN_FAILED", entity_type="AUTH_IDENTITY", result=AuditResult.FAILURE,
              metadata={"method": "EMAIL_PASSWORD", "reason": "UNKNOWN_IDENTITY"})
        session.commit()
        raise InvalidCredentials()
    if identity.locked_until and identity.locked_until > _now():
        session.rollback()
        raise Locked("Too many failed attempts. Try again later.", code="IDENTITY_LOCKED",
                     details={"locked_until": identity.locked_until.isoformat()})
    if not verify_password(identity.password_hash, password):
        identity.failed_attempts += 1
        locked = identity.failed_attempts >= s.password_max_failures
        if locked:
            identity.locked_until = _now() + timedelta(minutes=s.password_lock_minutes)
            identity.failed_attempts = 0
        audit(session, action="AUTH.LOGIN_FAILED", entity_type="AUTH_IDENTITY", entity_id=identity.id,
              actor=identity.user_id, result=AuditResult.FAILURE,
              metadata={"method": "EMAIL_PASSWORD", "reason": "WRONG_PASSWORD", "identity_locked": locked})
        session.commit()
        raise InvalidCredentials()
    user = session.get(User, identity.user_id)
    if user is None or user.status != "ACTIVE":
        audit(session, action="AUTH.LOGIN_FAILED", entity_type="USER", entity_id=identity.user_id,
              actor=identity.user_id, result=AuditResult.DENIED, metadata={"reason": "ACCOUNT_NOT_ACTIVE"})
        session.commit()
        raise AccountDisabled()
    identity.failed_attempts = 0
    identity.locked_until = None
    if needs_rehash(identity.password_hash or ""):
        identity.password_hash = hash_password(password)
    signed = _open_session(rt, session, user, identity)
    audit(session, action="AUTH.LOGIN_SUCCEEDED", entity_type="USER", entity_id=user.id, actor=user.id,
          organization_id=signed.user_session.active_organization_id,
          metadata={"method": "EMAIL_PASSWORD", "session_id": signed.user_session.id,
                    "change_required": signed.password_change_required})
    return signed


def change_password(rt: Runtime, session: Session, ctx: AuthContext, current: str, new: str) -> SignedIn:
    identity = session.scalar(select(AuthIdentity).where(
        AuthIdentity.user_id == ctx.user_id, AuthIdentity.identity_type == "EMAIL_PASSWORD").with_for_update())
    if identity is None:
        raise ValidationFailed("This account signs in without a password.", code="NO_PASSWORD_IDENTITY")
    if not verify_password(identity.password_hash, current):
        audit(session, action="AUTH.PASSWORD_CHANGE_FAILED", entity_type="AUTH_IDENTITY", entity_id=identity.id,
              actor=ctx.user_id, result=AuditResult.FAILURE, metadata={"reason": "WRONG_CURRENT"})
        session.commit()
        raise ValidationFailed(errors=[FieldError(field="current_password", code="INCORRECT",
                                                  message="Your current password is not correct.")])
    if current == new:
        raise ValidationFailed(errors=[FieldError(field="new_password", code="SAME_AS_CURRENT",
                                                  message="Choose a password different from the current one.")])
    check_password_policy(new, min_length=rt.settings.password_min_length,
                          forbidden=(identity.identifier.split("@")[0],))
    identity.password_hash = hash_password(new)
    identity.password_change_required = False
    identity.failed_attempts = 0
    # Every other session ends; this one continues with a fresh token.
    for other in session.scalars(select(UserSession).where(
            UserSession.user_id == ctx.user_id, UserSession.revoked_at.is_(None), UserSession.id != ctx.session_id)):
        other.revoked_at, other.revoked_reason = _now(), "PASSWORD_CHANGED"
    user = session.get(User, ctx.user_id)
    current_session = session.get(UserSession, ctx.session_id) if ctx.session_id else None
    if user is None or current_session is None or current_session.revoked_at is not None:
        raise Unauthenticated()
    audit(session, action="AUTH.PASSWORD_CHANGED", entity_type="AUTH_IDENTITY", entity_id=identity.id,
          actor=ctx.user_id, organization_id=ctx.organization_id)
    session.flush()
    token, exp = issue_token(rt, user, current_session, password_change_required=False)
    return SignedIn(token, exp, None, user, current_session, False)


# ------------------------------------------------------------------ OTP
@dataclass
class OtpRequested:
    challenge_id: uuid.UUID
    expires_at: datetime
    resend_after: int
    sent_to: str


def request_otp(rt: Runtime, session: Session, mobile: str, purpose: str) -> OtpRequested:
    s = rt.settings
    if purpose not in {"LOGIN", "SIGNUP"}:
        raise ValidationFailed(errors=[FieldError(field="purpose", code="INVALID", message="Use LOGIN or SIGNUP.")])
    e164 = normalize_mobile(mobile, s.otp_country_code)
    mobile_hash = rt.otp.mobile_hash(e164)
    now = _now()

    def recent(seconds: int) -> int:
        return session.scalar(select(func.count()).select_from(OtpChallenge).where(
            OtpChallenge.mobile_hash == mobile_hash, OtpChallenge.created_at > now - timedelta(seconds=seconds))) or 0

    last = session.scalar(select(func.max(OtpChallenge.created_at)).where(OtpChallenge.mobile_hash == mobile_hash))
    if last and (now - last).total_seconds() < s.otp_resend_seconds:
        wait = int(s.otp_resend_seconds - (now - last).total_seconds()) + 1
        raise RateLimited("Wait before asking for another code.", details={"retry_after": wait},
                          headers={"Retry-After": str(wait)})
    if recent(900) >= s.otp_limit_per_15_minutes or recent(86400) >= s.otp_limit_per_day:
        audit(session, action="AUTH.OTP_RATE_LIMITED", entity_type="OTP_CHALLENGE", result=AuditResult.DENIED,
              metadata={"mobile_last4": e164[-4:]})
        session.commit()
        raise RateLimited("Too many codes requested for this number. Try again later.")

    if rt.dev_sink is None and isinstance(rt.sms, DisabledSmsSender):
        raise IntegrationDisabled("Sign-in by SMS is not available yet.", code="SMS_UNAVAILABLE")

    for pending in session.scalars(select(OtpChallenge).where(
            OtpChallenge.mobile_hash == mobile_hash, OtpChallenge.status == "PENDING")):
        pending.status = "CANCELLED"
    identity = session.scalar(select(AuthIdentity).where(
        AuthIdentity.identity_type == "MOBILE_OTP", AuthIdentity.identifier == e164))
    code = new_otp_code(s.otp_length)
    challenge_id = uuid7()
    challenge = OtpChallenge(id=challenge_id, purpose=purpose, mobile_hash=mobile_hash, mobile_last4=e164[-4:],
                             auth_identity_id=identity.id if identity else None,
                             code_hash=rt.otp.code_hash(challenge_id, code),
                             expires_at=now + timedelta(seconds=s.otp_ttl_seconds), max_attempts=s.otp_max_attempts,
                             requested_ip=context.current().client_ip, created_at=now)

    if rt.dev_sink is not None:
        rt.dev_sink.put(e164, code)
        challenge.delivery_status, challenge.delivery_reference = "SENT", "dev-sink"
    else:
        result = rt.sms.send(e164, "OTP_LOGIN", {"code": code})
        challenge.delivery_status = {IntegrationStatus.OK: "SENT", IntegrationStatus.FAILED: "FAILED"}.get(
            result.status, "DISABLED")
        challenge.delivery_reference = result.reference
    del code
    session.add(challenge)
    audit(session, action="AUTH.OTP_REQUESTED", entity_type="OTP_CHALLENGE", entity_id=challenge.id,
          actor=identity.user_id if identity else None,
          metadata={"purpose": purpose, "mobile_last4": e164[-4:], "delivery": challenge.delivery_status})
    if challenge.delivery_status == "FAILED":
        session.commit()
        raise DependencyUnavailable("We could not send the code. Try again shortly.", code="SMS_FAILED")
    return OtpRequested(challenge.id, challenge.expires_at, s.otp_resend_seconds, mask_mobile(e164))


def verify_otp(rt: Runtime, session: Session, challenge_id: uuid.UUID, mobile: str, code: str) -> SignedIn:
    e164 = normalize_mobile(mobile, rt.settings.otp_country_code)
    challenge = session.scalar(select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update())
    if challenge is None or challenge.mobile_hash != rt.otp.mobile_hash(e164):
        raise OtpInvalid()
    if challenge.status == "LOCKED":
        raise OtpLocked()
    if challenge.status != "PENDING":
        raise OtpExpired("This code is no longer valid. Request a new one.")
    if challenge.expires_at <= _now():
        challenge.status = "EXPIRED"
        audit(session, action="AUTH.OTP_FAILED", entity_type="OTP_CHALLENGE", entity_id=challenge.id,
              result=AuditResult.FAILURE, metadata={"reason": "EXPIRED"})
        session.commit()
        raise OtpExpired()
    if not rt.otp.code_matches(challenge.id, (code or "").strip(), challenge.code_hash):
        challenge.attempt_count += 1
        locked = challenge.attempt_count >= challenge.max_attempts
        if locked:
            challenge.status = "LOCKED"
        audit(session, action="AUTH.OTP_FAILED", entity_type="OTP_CHALLENGE", entity_id=challenge.id,
              result=AuditResult.FAILURE, metadata={"reason": "LOCKED" if locked else "WRONG_CODE",
                                                    "attempts": challenge.attempt_count})
        session.commit()
        if locked:
            raise OtpLocked()
        raise OtpInvalid(details={"attempts_left": challenge.max_attempts - challenge.attempt_count})

    challenge.status, challenge.verified_at = "VERIFIED", _now()
    identity = session.scalar(select(AuthIdentity).where(
        AuthIdentity.identity_type == "MOBILE_OTP", AuthIdentity.identifier == e164).with_for_update())
    created = False
    if identity is None:
        user, identity = _register_mobile_user(rt, session, e164)
        created = True
    else:
        user = session.get(User, identity.user_id)
        if user is None or user.status != "ACTIVE":
            audit(session, action="AUTH.LOGIN_FAILED", entity_type="USER", entity_id=identity.user_id,
                  actor=identity.user_id, result=AuditResult.DENIED, metadata={"reason": "ACCOUNT_NOT_ACTIVE"})
            session.commit()
            raise AccountDisabled()
        if identity.verified_at is None:
            identity.verified_at = _now()
    challenge.auth_identity_id = identity.id
    signed = _open_session(rt, session, user, identity)
    audit(session, action="AUTH.OTP_VERIFIED", entity_type="OTP_CHALLENGE", entity_id=challenge.id, actor=user.id,
          metadata={"new_user": created})
    audit(session, action="AUTH.LOGIN_SUCCEEDED", entity_type="USER", entity_id=user.id, actor=user.id,
          organization_id=signed.user_session.active_organization_id,
          metadata={"method": "MOBILE_OTP", "session_id": signed.user_session.id})
    return signed


def _register_mobile_user(rt: Runtime, session: Session, e164: str) -> tuple[User, AuthIdentity]:
    user = User(display_name=f"User {e164[-4:]}", status="ACTIVE")
    session.add(user)
    session.flush()
    identity = AuthIdentity(user_id=user.id, identity_type="MOBILE_OTP", identifier=e164, verified_at=_now(),
                            is_primary=True)
    session.add(identity)
    role_code = rt.settings.default_signup_role_code
    if role_code:  # configuration names a role CODE (data); no role is assumed in code
        role = session.scalar(select(Role).where(Role.role_code == role_code, Role.status == "ACTIVE"))
        if role is not None:
            session.add(UserRoleAssignment(user_id=user.id, role_id=role.id, scope_type=Scope.OWN.value,
                                           status="ACTIVE"))
    session.flush()
    audit(session, action="USER.REGISTERED", entity_type="USER", entity_id=user.id, actor=user.id,
          after={"display_name": user.display_name, "identity_type": "MOBILE_OTP", "mobile_last4": e164[-4:],
                 "default_role": role_code})
    event(session, aggregate_type="USER", aggregate_id=user.id, event_type="UserRegistered",
          payload={"user_id": user.id, "identity_type": "MOBILE_OTP"})
    return user, identity


# ------------------------------------------------------------------ refresh, logout, switch
def refresh(rt: Runtime, session: Session, refresh_token: str | None) -> SignedIn:
    if not refresh_token:
        raise Unauthenticated("Sign in to continue.")
    user_session = session.scalar(select(UserSession).where(
        UserSession.refresh_token_hash == sha256_hex(refresh_token)).with_for_update())
    if user_session is None or user_session.revoked_at is not None or user_session.expires_at <= _now():
        raise Unauthenticated("Your session has ended. Sign in again.", code="SESSION_ENDED")
    user = session.get(User, user_session.user_id)
    if user is None or user.status != "ACTIVE":
        user_session.revoked_at, user_session.revoked_reason = _now(), "USER_NOT_ACTIVE"
        session.commit()
        raise AccountDisabled()
    if user_session.active_organization_id and not any(
            o.id == user_session.active_organization_id for _, o in active_memberships(session, user.id)):
        user_session.active_organization_id = None  # membership ended: the user chooses again
    new_token, new_hash = new_refresh_token()
    user_session.refresh_token_hash = new_hash
    user_session.last_used_at = _now()
    pcr = _password_change_pending(session, user_session)
    session.flush()
    token, exp = issue_token(rt, user, user_session, password_change_required=pcr)
    return SignedIn(token, exp, new_token, user, user_session, pcr)


def logout(session: Session, ctx: AuthContext) -> None:
    if ctx.session_id:
        user_session = session.get(UserSession, ctx.session_id)
        if user_session and user_session.revoked_at is None and user_session.user_id == ctx.user_id:
            user_session.revoked_at, user_session.revoked_reason = _now(), "LOGOUT"
    audit(session, action="AUTH.LOGOUT", entity_type="USER", entity_id=ctx.user_id, actor=ctx.user_id,
          organization_id=ctx.organization_id, metadata={"session_id": ctx.session_id})


def switch_organization(rt: Runtime, session: Session, ctx: AuthContext,
                        organization_id: uuid.UUID) -> tuple[SignedIn, EffectivePermissions]:
    if not any(o.id == organization_id for _, o in active_memberships(session, ctx.user_id)):
        raise NoMembership()
    user_session = session.get(UserSession, ctx.session_id) if ctx.session_id else None
    if user_session is None or user_session.revoked_at is not None or user_session.user_id != ctx.user_id:
        raise Unauthenticated()
    user = session.get(User, ctx.user_id)
    previous = user_session.active_organization_id
    user_session.active_organization_id = organization_id
    audit(session, action="AUTH.ORGANIZATION_SWITCHED", entity_type="USER", entity_id=ctx.user_id, actor=ctx.user_id,
          organization_id=organization_id, before={"organization_id": previous},
          after={"organization_id": organization_id})
    session.flush()
    token, exp = issue_token(rt, user, user_session, password_change_required=False)  # type: ignore[arg-type]
    return SignedIn(token, exp, None, user, user_session, False), resolve(session, ctx.user_id, organization_id)  # type: ignore[arg-type]
