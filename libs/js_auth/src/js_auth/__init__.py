"""Authentication context and data-driven authorization (v5 §9, Implementation Blueprint §11).

No role name appears anywhere in this package: services ask for permission codes
(``JOB.EDIT``) and receive the scope the caller holds for it in the active
organization. Roles, permissions and assignments are data owned by Identity.
"""

from js_auth.context import AuthContext, Authorized, EffectivePermissions, Scope
from js_auth.dependencies import Authenticator
from js_auth.keys import KeyRing, load_key_ring
from js_auth.tokens import AccessClaims, TokenSettings

__all__ = [
    "AuthContext", "Authorized", "EffectivePermissions", "Scope", "Authenticator",
    "KeyRing", "load_key_ring", "AccessClaims", "TokenSettings",
]
