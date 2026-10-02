"""FastAPI dependencies: authenticate the request, then check a permission code.

    auth = Authenticator(ring, token_settings, authz_provider)

    @router.get("/users")
    def list_users(caller: Authorized = Depends(auth.require("USER.VIEW"))): ...

* No token / bad token          -> 401 UNAUTHENTICATED
* Password change still owed    -> 403 PASSWORD_CHANGE_REQUIRED (except where allowed)
* Token older than the user's
  current authorization version -> 401 TOKEN_STALE (client refreshes)
* Permission not held           -> 403 PERMISSION_DENIED
The record-level part of scope (OWN / ORGANIZATION) is checked by the use case
with ``Authorized.allows_record``; the dependency only proves the permission exists.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from js_auth.authz import CachingAuthzProvider
from js_auth.context import AuthContext, Authorized, EffectivePermissions
from js_auth.keys import KeyRing
from js_auth.tokens import TokenError, TokenSettings, verify_access_token
from js_core.errors import PermissionDenied, Unauthenticated


class PasswordChangeRequired(PermissionDenied):
    code, message = "PASSWORD_CHANGE_REQUIRED", "Change your temporary password to continue."


class TokenStale(Unauthenticated):
    code, message = "TOKEN_STALE", "Your access changed. Refresh your session."


class Authenticator:
    def __init__(self, ring: KeyRing, settings: TokenSettings, provider: CachingAuthzProvider) -> None:
        self.ring = ring
        self.settings = settings
        self.provider = provider

    def _context(self, request: Request) -> AuthContext:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthenticated()
        try:
            claims = verify_access_token(self.ring, self.settings, token.strip())
        except TokenError:
            raise Unauthenticated("Your session is not valid. Sign in again.") from None
        ctx = AuthContext(user_id=claims.user_id, session_id=claims.session_id,
                          organization_id=claims.organization_id, authz_version=claims.authz_version,
                          password_change_required=claims.password_change_required)
        request.state.auth = ctx
        return ctx

    def authenticated(self, *, allow_password_change: bool = False) -> Callable[[Request], AuthContext]:
        def dependency(request: Request) -> AuthContext:
            ctx = self._context(request)
            if ctx.password_change_required and not allow_password_change:
                raise PasswordChangeRequired()
            return ctx
        return dependency

    def permissions(self, ctx: AuthContext) -> EffectivePermissions:
        effective = self.provider.effective(ctx.user_id, ctx.organization_id, ctx.authz_version)
        if effective.authz_version != ctx.authz_version:
            raise TokenStale()
        return effective

    def require(self, permission: str) -> Callable[[Request], Authorized]:
        def dependency(request: Request) -> Authorized:
            ctx = self._context(request)
            if ctx.password_change_required:
                raise PasswordChangeRequired()
            effective = self.permissions(ctx)
            scope = effective.scope_for(permission)
            if scope is None:
                raise PermissionDenied()
            return Authorized(auth=ctx, permission=permission, scope=scope, permissions=effective)
        return dependency
