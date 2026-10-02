"""Signing keys for access tokens.

Keys come from secret references (``env:`` / ``file:``; the cloud secret store is
still TBD). Only Identity holds the private key; other services load public keys.
In local/development/test, if no key is configured, an ephemeral key is generated
so the stack runs without setup; that is refused in staging and production.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr

from js_core import secrets
from js_core.config import Environment

log = logging.getLogger("js_auth.keys")
ALGORITHM = "ES256"


class KeyConfigurationError(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass(frozen=True)
class KeyRing:
    kid: str
    private_key: ec.EllipticCurvePrivateKey | None
    public_keys: dict[str, ec.EllipticCurvePublicKey]

    def jwks(self) -> dict:
        keys = []
        for kid, key in self.public_keys.items():
            numbers = key.public_numbers()
            keys.append({"kty": "EC", "crv": "P-256", "alg": ALGORITHM, "use": "sig", "kid": kid,
                         "x": _b64(numbers.x.to_bytes(32, "big")), "y": _b64(numbers.y.to_bytes(32, "big"))})
        return {"keys": keys}


def key_id(public_key: ec.EllipticCurvePublicKey) -> str:
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:16]


def _load_private(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise KeyConfigurationError("Access-token key must be an EC P-256 private key")
    return key


def _load_public(pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise KeyConfigurationError("Access-token public key must be EC P-256")
    return key


def load_key_ring(*, env: Environment, private_key_ref: SecretStr | None = None,
                  public_key_refs: list[SecretStr] | None = None) -> KeyRing:
    """Identity passes ``private_key_ref``; every other service passes ``public_key_refs``."""
    private = None
    publics: dict[str, ec.EllipticCurvePublicKey] = {}
    if private_key_ref is not None:
        resolved = secrets.resolve(private_key_ref)
        private = _load_private(resolved.get_secret_value())  # type: ignore[union-attr]
    for ref in public_key_refs or []:
        resolved = secrets.resolve(ref)
        public = _load_public(resolved.get_secret_value())  # type: ignore[union-attr]
        publics[key_id(public)] = public
    if private is None and not publics:
        if not env.allows_dev_tools:
            raise KeyConfigurationError(f"No access-token key configured (APP_ENV={env.value})")
        private = ec.generate_private_key(ec.SECP256R1())
        log.warning("Using an ephemeral access-token key: tokens will not survive a restart (development only)")
    if private is not None:
        public = private.public_key()
        publics.setdefault(key_id(public), public)
        return KeyRing(kid=key_id(public), private_key=private, public_keys=publics)
    first = next(iter(publics))
    return KeyRing(kid=first, private_key=None, public_keys=publics)


def generate_private_key_pem() -> str:
    """Helper for tests and tools/new_signing_key.py; never called at runtime."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
