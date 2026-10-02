"""Everything the Reference Data routes need, built once per app (``app.state.runtime``)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Request
from sqlalchemy.orm import Session

from js_approval import ApprovalEngine, ApprovalModels
from js_auth import Authenticator, Authorized, TokenSettings
from js_auth.authz import AuthzProvider, CachingAuthzProvider
from js_auth.context import Scope
from js_auth.keys import VerifyingKeys, load_private_key
from js_auth.remote import HttpAuthzProvider, JwksKeys
from js_core.db import Database
from js_core.errors import PermissionDenied
from reference_service.config import Settings
from reference_service.models import ApprovalAction, ApprovalPolicy, ApprovalRequest

log = logging.getLogger("reference_service.runtime")


@dataclass
class Runtime:
    settings: Settings
    database: Database
    authenticator: Authenticator
    approvals: ApprovalEngine


def _service_key(settings: Settings) -> ec.EllipticCurvePrivateKey:
    if settings.service_private_key_ref is not None:
        return load_private_key(settings.service_private_key_ref)
    if not settings.app_env.allows_dev_tools:
        raise RuntimeError(f"SERVICE_PRIVATE_KEY_REF is required in APP_ENV={settings.app_env.value}")
    log.warning("No service key configured: Identity will refuse permission lookups (development only)")
    return ec.generate_private_key(ec.SECP256R1())


def build_runtime(settings: Settings, database: Database, *, keys: VerifyingKeys | None = None,
                  provider: AuthzProvider | None = None) -> Runtime:
    """``keys`` and ``provider`` are injected by tests; otherwise both come from Identity."""
    from reference_service.approvals import register_handlers

    keys = keys or JwksKeys(f"{settings.identity_url.rstrip('/')}/.well-known/jwks.json")
    provider = provider or HttpAuthzProvider(settings.identity_url, service_name=settings.service_name,
                                             private_key=_service_key(settings))
    engine = ApprovalEngine(ApprovalModels(policy=ApprovalPolicy, request=ApprovalRequest, action=ApprovalAction,
                                           number_sequence="approval_request_number_seq", number_prefix="APR-R-"))
    register_handlers(engine)
    caching = CachingAuthzProvider(provider, ttl_seconds=settings.authz_cache_seconds)
    return Runtime(settings=settings, database=database,
                   authenticator=Authenticator(keys, TokenSettings(), caching),  # type: ignore[arg-type]
                   approvals=engine)


# ------------------------------------------------------------------ request dependencies
def runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def db_session(request: Request) -> Iterator[Session]:
    yield from runtime(request).database.dependency()


def require(permission: str, *, platform: bool = False) -> Callable[[Request], Authorized]:
    """403 unless the caller holds ``permission``; ``platform`` also requires ALL scope
    (reference lists are platform-wide, not owned by an organization)."""
    def dependency(request: Request) -> Authorized:
        caller = runtime(request).authenticator.require(permission)(request)
        if platform and caller.scope is not Scope.ALL:
            raise PermissionDenied("Reference lists are managed platform-wide; this needs ALL scope.")
        return caller
    return dependency


def caller(request: Request) -> Authorized:
    rt = runtime(request)
    ctx = rt.authenticator.authenticated()(request)
    return Authorized(auth=ctx, permission="", scope=Scope.OWN, permissions=rt.authenticator.permissions(ctx))
