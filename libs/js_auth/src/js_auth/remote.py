"""How a service other than Identity verifies tokens and resolves permissions
(Implementation Blueprint service-call table, "Every service -> Identity").

* ``JwksKeys``          public keys from Identity's /.well-known/jwks.json; refetched when an
                        unknown ``kid`` appears (at most every ``min_refresh_seconds``); the last
                        good keys are kept if Identity is unreachable.
* ``HttpAuthzProvider`` effective permissions from Identity's internal authz API, called with a
                        60-second service token. Wrap it in ``CachingAuthzProvider`` (keyed by
                        authz_version). If Identity cannot be reached the request fails closed
                        with 503: no permission data means no access.

Only the standard library is used for HTTP so services need no extra dependency.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from cryptography.hazmat.primitives.asymmetric import ec

from js_auth.context import EffectivePermissions, Scope
from js_auth.keys import KeyConfigurationError, public_key_from_jwk
from js_auth.service_tokens import sign_service_token
from js_core import context
from js_core.errors import DependencyUnavailable

log = logging.getLogger("js_auth.remote")


def _get_json(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})  # noqa: S310
    correlation = context.correlation_id_var.get()
    if correlation:
        request.add_header("X-Correlation-Id", correlation)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL comes from configuration
        return json.loads(response.read().decode("utf-8"))


class JwksKeys:
    def __init__(self, jwks_url: str, *, timeout: float = 2.0, min_refresh_seconds: float = 30.0) -> None:
        self.jwks_url = jwks_url
        self.timeout = timeout
        self.min_refresh_seconds = min_refresh_seconds
        self._keys: dict[str, ec.EllipticCurvePublicKey] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def refresh(self) -> bool:
        try:
            body = _get_json(self.jwks_url, timeout=self.timeout)
            keys = {k["kid"]: public_key_from_jwk(k) for k in body.get("keys", []) if k.get("kid")}
        except (OSError, ValueError, KeyError, KeyConfigurationError) as exc:
            log.warning("Could not fetch Identity signing keys: %s", type(exc).__name__)
            return False
        with self._lock:
            self._keys = keys
            self._fetched_at = time.monotonic()
        return True

    def key_for(self, kid: str) -> ec.EllipticCurvePublicKey | None:
        with self._lock:
            key = self._keys.get(kid)
            stale = time.monotonic() - self._fetched_at >= self.min_refresh_seconds
        if key is None and stale:  # key rotation, or Identity restarted with a new key
            self.refresh()
            with self._lock:
                key = self._keys.get(kid)
        return key


class HttpAuthzProvider:
    def __init__(self, base_url: str, *, service_name: str, private_key: ec.EllipticCurvePrivateKey,
                 timeout: float = 1.0, retries: int = 1) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.private_key = private_key
        self.timeout = timeout
        self.retries = retries

    def effective(self, user_id: uuid.UUID, organization_id: uuid.UUID | None) -> EffectivePermissions:
        query = f"?{urllib.parse.urlencode({'organization_id': organization_id})}" if organization_id else ""
        url = f"{self.base_url}/v1/internal/authz/users/{user_id}{query}"
        last: Exception | None = None
        for _ in range(self.retries + 1):
            token = sign_service_token(self.private_key, issuer=self.service_name, audience="identity")
            try:
                body = _get_json(url, timeout=self.timeout, headers={"X-Service-Token": token})
            except urllib.error.HTTPError as exc:
                if exc.code == 404:  # user no longer exists: no access
                    return EffectivePermissions(authz_version=-1)
                last = exc
                if exc.code < 500:
                    break  # 401/403: misconfigured service key; retrying will not help
            except (OSError, ValueError) as exc:
                last = exc
            else:
                return EffectivePermissions(
                    authz_version=int(body["authz_version"]), roles=tuple(body.get("roles", [])),
                    scopes={code: Scope(scope) for code, scope in body.get("permissions", {}).items()})
        log.error("Identity authorization lookup failed: %s", type(last).__name__)
        raise DependencyUnavailable("Access checks are unavailable. Try again shortly.", code="AUTHZ_UNAVAILABLE")
