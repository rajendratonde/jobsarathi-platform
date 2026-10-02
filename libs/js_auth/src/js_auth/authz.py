"""Where effective permissions come from.

Identity resolves them from its own tables (``LocalAuthzProvider`` in the Identity
service). Every other service will use an HTTP provider calling Identity's internal
API. Both are wrapped in ``CachingAuthzProvider``: entries are keyed by
(user, organization, authz_version), so any RBAC change - which raises
users.authz_version - makes the old entry unreachable at once.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Protocol

from js_auth.context import EffectivePermissions


class AuthzProvider(Protocol):
    def effective(self, user_id: uuid.UUID, organization_id: uuid.UUID | None) -> EffectivePermissions: ...


class CachingAuthzProvider:
    def __init__(self, inner: AuthzProvider, ttl_seconds: int = 60, max_entries: int = 10_000) -> None:
        self.inner = inner
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, EffectivePermissions]] = {}

    def effective(self, user_id: uuid.UUID, organization_id: uuid.UUID | None, authz_version: int) -> EffectivePermissions:
        key = (user_id, organization_id, authz_version)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
        result = self.inner.effective(user_id, organization_id)
        if result.authz_version != authz_version:
            # Token is older than the user's current authorization: do not trust either.
            return EffectivePermissions(authz_version=result.authz_version)
        with self._lock:
            if len(self._cache) >= self.max_entries:
                self._cache.clear()
            self._cache[key] = (now + self.ttl, result)
        return result

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
