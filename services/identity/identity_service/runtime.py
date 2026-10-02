"""Everything the Identity routes need, built once per app and kept on ``app.state.runtime``."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from fastapi import Request
from sqlalchemy.orm import Session

from identity_service.authz import LocalAuthzProvider
from identity_service.config import Settings
from identity_service.models import ApprovalAction, ApprovalPolicy, ApprovalRequest
from identity_service.security import OtpHasher
from js_approval import ApprovalEngine, ApprovalModels
from js_auth import AuthContext, Authenticator, Authorized, KeyRing, TokenSettings, load_key_ring
from js_auth.authz import CachingAuthzProvider
from js_auth.context import Scope
from js_auth.service_tokens import ServiceAuthenticator
from js_core import secrets
from js_core.db import Database
from js_integration.sms import SmsSender, SmsSettings, build_sms_sender

log = logging.getLogger("identity_service.runtime")
dev_otp_log = logging.getLogger("identity_service.dev_otp_sink")


class DevOtpSink:
    """Local/development/test only (enforced by Settings): remembers the latest code per mobile
    for 10 minutes so testers and e2e tests can sign in without an SMS provider."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._codes: dict[str, tuple[float, str]] = {}

    def put(self, e164: str, code: str) -> None:
        with self._lock:
            self._codes[e164] = (time.monotonic() + 600, code)
        dev_otp_log.warning("DEV OTP SINK (never in production): %s ******%s -> %s", e164[:3], e164[-4:], code)

    def get(self, e164: str) -> str | None:
        with self._lock:
            hit = self._codes.get(e164)
        return hit[1] if hit and hit[0] > time.monotonic() else None


@dataclass
class Runtime:
    settings: Settings
    database: Database
    ring: KeyRing
    tokens: TokenSettings
    authenticator: Authenticator
    approvals: ApprovalEngine
    otp: OtpHasher
    sms: SmsSender
    services: ServiceAuthenticator
    dev_sink: DevOtpSink | None = None
    extra: dict = field(default_factory=dict)


def _service_callers(settings: Settings) -> dict:
    callers = {}
    for name, ref in settings.service_public_keys.items():
        pem = secrets.resolve(ref).get_secret_value()  # type: ignore[union-attr]
        callers[name] = serialization.load_pem_public_key(pem.encode())
    return callers


def build_runtime(settings: Settings, database: Database) -> Runtime:
    from identity_service.approvals import register_handlers

    ring = load_key_ring(env=settings.app_env, private_key_ref=settings.jwt_private_key_ref)
    tokens = TokenSettings()
    provider = CachingAuthzProvider(LocalAuthzProvider(database.session), ttl_seconds=settings.authz_cache_seconds)
    engine = ApprovalEngine(ApprovalModels(policy=ApprovalPolicy, request=ApprovalRequest, action=ApprovalAction,
                                           number_sequence="approval_request_number_seq", number_prefix="APR-I-"))
    register_handlers(engine)
    sms = build_sms_sender(SmsSettings(), middleware_enabled=settings.middleware_enabled, env=settings.app_env)
    return Runtime(
        settings=settings, database=database, ring=ring, tokens=tokens,
        authenticator=Authenticator(ring, tokens, provider), approvals=engine,
        otp=OtpHasher.from_settings(settings.otp_secret_ref, settings.app_env), sms=sms,
        services=ServiceAuthenticator("identity", _service_callers(settings)),
        dev_sink=DevOtpSink() if settings.otp_dev_sink else None,
    )


# ------------------------------------------------------------------ request dependencies
def runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def db_session(request: Request) -> Iterator[Session]:
    yield from runtime(request).database.dependency()


def authenticated(*, allow_password_change: bool = False) -> Callable[[Request], AuthContext]:
    def dependency(request: Request) -> AuthContext:
        return runtime(request).authenticator.authenticated(allow_password_change=allow_password_change)(request)
    return dependency


def require(permission: str) -> Callable[[Request], Authorized]:
    """403 unless the caller holds ``permission`` in the active organization (any active scope)."""
    def dependency(request: Request) -> Authorized:
        return runtime(request).authenticator.require(permission)(request)
    return dependency


def caller(request: Request) -> Authorized:
    """Authenticated with effective permissions loaded, without naming one permission
    (approval decisions check the policy's checker permission themselves)."""
    rt = runtime(request)
    ctx = rt.authenticator.authenticated()(request)
    effective = rt.authenticator.permissions(ctx)
    return Authorized(auth=ctx, permission="", scope=Scope.OWN, permissions=effective)


def service_caller(*allowed: str) -> Callable[[Request], str]:
    def dependency(request: Request) -> str:
        return runtime(request).services.require(*allowed)(request)
    return dependency
