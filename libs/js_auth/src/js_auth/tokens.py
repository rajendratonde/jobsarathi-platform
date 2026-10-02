"""Short-lived signed access tokens (ES256 JWT).

Claims: sub (user), sid (session), org (active organization), av (users.authz_version),
pcr (password change required), iss, aud, iat, exp, jti, typ. The token never carries
the permission list: services resolve permissions from Identity, cached by ``av``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt
from pydantic_settings import BaseSettings, SettingsConfigDict

from js_auth.keys import ALGORITHM, KeyRing, VerifyingKeys


class TokenSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JWT_", extra="ignore", hide_input_in_errors=True)

    issuer: str = "jobsarathi-identity"
    audience: str = "jobsarathi-api"
    access_ttl_seconds: int = 900  # 15 minutes
    leeway_seconds: int = 30


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    authz_version: int
    password_change_required: bool
    expires_at: int
    token_id: str


class TokenError(Exception):
    pass


def issue_access_token(ring: KeyRing, settings: TokenSettings, *, user_id: uuid.UUID, session_id: uuid.UUID | None,
                       organization_id: uuid.UUID | None, authz_version: int,
                       password_change_required: bool) -> tuple[str, int]:
    if ring.private_key is None:
        raise TokenError("This service cannot issue tokens")
    now = int(time.time())
    exp = now + settings.access_ttl_seconds
    payload = {
        "iss": settings.issuer, "aud": settings.audience, "sub": str(user_id), "iat": now, "exp": exp,
        "jti": uuid.uuid4().hex, "typ": "access", "sid": str(session_id) if session_id else None,
        "org": str(organization_id) if organization_id else None, "av": int(authz_version),
        "pcr": bool(password_change_required),
    }
    token = jwt.encode(payload, ring.private_key, algorithm=ALGORITHM, headers={"kid": ring.kid})
    return token, exp


def verify_access_token(ring: KeyRing | VerifyingKeys, settings: TokenSettings, token: str) -> AccessClaims:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = ring.key_for(kid or "")
        if key is None:
            raise TokenError("Unknown signing key")
        payload = jwt.decode(token, key, algorithms=[ALGORITHM], audience=settings.audience, issuer=settings.issuer,
                             leeway=settings.leeway_seconds, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
        if payload.get("typ") != "access":
            raise TokenError("Not an access token")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]) if payload.get("sid") else None,
            organization_id=uuid.UUID(payload["org"]) if payload.get("org") else None,
            authz_version=int(payload.get("av", 0)),
            password_change_required=bool(payload.get("pcr", False)),
            expires_at=int(payload["exp"]),
            token_id=str(payload.get("jti", "")),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise TokenError(type(exc).__name__) from exc
