"""Service-to-service authentication for ``/internal/*`` routes (Implementation Blueprint §17).

Each calling service signs a 60-second ES256 token with its own private key
(iss = its service name, aud = the target service). The target holds an
allow-list of caller public keys per internal route. Keys come from secret
references; the store is still TBD.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Request

from js_core.errors import PermissionDenied, Unauthenticated

ALGORITHM = "ES256"
TTL_SECONDS = 60


def sign_service_token(private_key: ec.EllipticCurvePrivateKey, *, issuer: str, audience: str) -> str:
    now = int(time.time())
    return jwt.encode({"iss": issuer, "aud": audience, "iat": now, "exp": now + TTL_SECONDS,
                       "jti": uuid.uuid4().hex, "typ": "service"}, private_key, algorithm=ALGORITHM)


class ServiceAuthenticator:
    def __init__(self, audience: str, callers: dict[str, ec.EllipticCurvePublicKey]) -> None:
        self.audience = audience
        self.callers = callers

    def require(self, *allowed: str) -> Callable[[Request], str]:
        def dependency(request: Request) -> str:
            header = request.headers.get("x-service-token", "")
            if not header:
                raise Unauthenticated("Service token required.")
            try:
                issuer = jwt.decode(header, options={"verify_signature": False}).get("iss", "")
            except jwt.PyJWTError:
                raise Unauthenticated("Service token not valid.") from None
            key = self.callers.get(issuer)
            if key is None or (allowed and issuer not in allowed):
                raise PermissionDenied("This service may not call this route.")
            try:
                payload = jwt.decode(header, key, algorithms=[ALGORITHM], audience=self.audience,
                                     options={"require": ["exp", "iat", "iss", "aud"]})
            except jwt.PyJWTError:
                raise Unauthenticated("Service token not valid.") from None
            if payload.get("typ") != "service":
                raise Unauthenticated("Service token not valid.")
            return issuer
        return dependency
