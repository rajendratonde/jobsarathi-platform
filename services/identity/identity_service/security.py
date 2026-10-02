"""Credential handling for Identity. Nothing here logs, returns or stores a plaintext secret.

* passwords      Argon2id (argon2-cffi defaults: RFC 9106 low-memory profile)
* OTP codes      HMAC-SHA256 keyed with OTP_SECRET_REF, bound to the challenge id
* mobile numbers HMAC-SHA256 in otp_challenges (plus last 4 digits for support)
* refresh tokens SHA-256 of a 256-bit random token; only the hash is stored
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import SecretStr

from js_core import secrets as secret_refs
from js_core.config import Environment
from js_core.errors import FieldError, ValidationFailed

_hasher = PasswordHasher()
# Verified when the email is unknown so both paths take the same time (no account enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def check_password_policy(password: str, *, min_length: int, field: str = "new_password",
                          forbidden: tuple[str, ...] = ()) -> None:
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"Use at least {min_length} characters.")
    if len(password) > 128:
        problems.append("Use at most 128 characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        problems.append("Use both letters and numbers.")
    if any(f and f.lower() in password.lower() for f in forbidden):
        problems.append("Do not include your email address.")
    if problems:
        raise ValidationFailed(errors=[FieldError(field=field, code="PASSWORD_POLICY", message=m) for m in problems])


def temporary_password(length: int = 14) -> str:
    """Shown once to the admin who issued it; the user must change it at next sign-in (E1)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            return value


def new_refresh_token() -> tuple[str, str]:
    """(token for the cookie, sha256 hex for user_sessions.refresh_token_hash)."""
    token = secrets.token_urlsafe(32)
    return token, sha256_hex(token)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class OtpHasher:
    """Keyed hashes for OTP codes and mobile numbers."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("OTP secret must be at least 32 bytes")
        self._key = key

    @classmethod
    def from_settings(cls, ref: SecretStr | None, env: Environment) -> OtpHasher:
        if ref is None:
            if not env.allows_dev_tools:
                raise RuntimeError(f"OTP_SECRET_REF is required in APP_ENV={env.value}")
            return cls(secrets.token_bytes(32))  # ephemeral: pending challenges die with the process
        resolved = secret_refs.resolve(ref)
        return cls(resolved.get_secret_value().encode())  # type: ignore[union-attr]

    def _mac(self, message: str) -> str:
        return hmac.new(self._key, message.encode(), hashlib.sha256).hexdigest()

    def mobile_hash(self, e164: str) -> str:
        return self._mac(f"mobile:{e164}")

    def code_hash(self, challenge_id: uuid.UUID, code: str) -> str:
        return self._mac(f"otp:{challenge_id}:{code}")

    def code_matches(self, challenge_id: uuid.UUID, code: str, stored: str) -> bool:
        return hmac.compare_digest(self.code_hash(challenge_id, code), stored)


def new_otp_code(length: int) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


_INDIAN_MOBILE = re.compile(r"^[6-9]\d{9}$")


def normalize_mobile(raw: str, country_code: str = "+91") -> str:
    """Return E.164 (+91XXXXXXXXXX) or raise 422. Phase 1 accepts Indian mobile numbers only."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    if digits.startswith(country_code):
        digits = digits[len(country_code):]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not _INDIAN_MOBILE.match(digits):
        raise ValidationFailed(errors=[FieldError(field="mobile", code="INVALID_MOBILE",
                                                  message="Enter a valid 10-digit mobile number.")])
    return f"{country_code}{digits}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def mask_mobile(e164: str) -> str:
    return f"{e164[:3]} ******{e164[-4:]}"
