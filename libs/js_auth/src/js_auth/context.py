from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class Scope(StrEnum):
    """Phase 1 uses OWN, ORGANIZATION and ALL. CITY and REGION are stored values but inactive."""

    OWN = "OWN"
    ORGANIZATION = "ORGANIZATION"
    CITY = "CITY"
    REGION = "REGION"
    ALL = "ALL"

    @property
    def rank(self) -> int:
        return {"OWN": 1, "ORGANIZATION": 2, "ALL": 3}.get(self.value, 0)

    @property
    def active(self) -> bool:
        return self.rank > 0


ACTIVE_SCOPES = (Scope.OWN, Scope.ORGANIZATION, Scope.ALL)


@dataclass(frozen=True)
class AuthContext:
    """Who is calling, from the verified access token. Never built from request bodies."""

    user_id: uuid.UUID
    session_id: uuid.UUID | None
    organization_id: uuid.UUID | None  # active organization
    authz_version: int
    password_change_required: bool = False


@dataclass(frozen=True)
class EffectivePermissions:
    """Permission code -> widest active scope the user holds for it in the active organization."""

    authz_version: int
    scopes: dict[str, Scope] = field(default_factory=dict)
    roles: tuple[str, ...] = ()

    def scope_for(self, code: str) -> Scope | None:
        return self.scopes.get(code)

    def has(self, code: str) -> bool:
        return code in self.scopes


@dataclass(frozen=True)
class Authorized:
    """Result of a permission check: the caller and the scope they hold for that permission."""

    auth: AuthContext
    permission: str
    scope: Scope
    permissions: EffectivePermissions

    def allows_organization(self, organization_id: uuid.UUID | None) -> bool:
        """ALL: any organization. ORGANIZATION: only the active one. OWN: decided per record."""
        if self.scope is Scope.ALL:
            return True
        if self.scope is Scope.ORGANIZATION:
            return organization_id is not None and organization_id == self.auth.organization_id
        return False

    def allows_record(self, *, organization_id: uuid.UUID | None = None, owner_user_id: uuid.UUID | None = None) -> bool:
        if self.scope is Scope.ALL:
            return True
        if self.scope is Scope.ORGANIZATION:
            return organization_id is not None and organization_id == self.auth.organization_id
        if self.scope is Scope.OWN:
            return owner_user_id is not None and owner_user_id == self.auth.user_id
        return False


def widest(a: Scope | None, b: Scope) -> Scope:
    if not b.active:
        return a  # type: ignore[return-value]
    if a is None or b.rank > a.rank:
        return b
    return a
