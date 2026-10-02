"""Configuration for the Identity & Access service. All values come from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator

from js_core.config import DatabaseSettings, ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "identity"

    # Access tokens: private key as a secret reference (env:NAME / file:/path).
    # Empty in local/development/test = ephemeral key (refused elsewhere).
    jwt_private_key_ref: SecretStr | None = None

    # Refresh token cookie
    refresh_ttl_days: int = 30
    refresh_cookie_name: str = "js_refresh"
    refresh_cookie_path: str = "/"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: str = "strict"

    # Passwords (Argon2id)
    password_min_length: int = 10
    password_max_failures: int = 5
    password_lock_minutes: int = 15

    # OTP (v5 §8; Implementation Blueprint §14). The HMAC key is a secret reference.
    otp_secret_ref: SecretStr | None = None
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 30
    otp_limit_per_15_minutes: int = 3
    otp_limit_per_day: int = 10
    otp_country_code: str = "+91"
    # Dev OTP sink: logs the code and serves it at GET /v1/dev/otp for local testing.
    # Refused outside local/development/test, so production never exposes OTP values.
    otp_dev_sink: bool = False

    # Optional data-driven default: a role CODE from the roles table, never role logic.
    default_signup_role_code: str | None = None

    # Internal routes: caller service -> public key reference (Implementation Blueprint §17).
    service_public_keys: dict[str, SecretStr] = Field(default_factory=dict)

    # Identity resolves permissions from its own tables on every request (0 = no cache),
    # so a disabled role or revoked assignment stops granting access at once.
    authz_cache_seconds: int = 0

    @model_validator(mode="after")
    def _identity_guards(self) -> Settings:
        if self.otp_dev_sink and not self.app_env.allows_dev_tools:
            raise ValueError(f"OTP_DEV_SINK is not allowed in APP_ENV={self.app_env.value}")
        if self.app_env.is_production and not self.refresh_cookie_secure:
            raise ValueError("REFRESH_COOKIE_SECURE must be true in production")
        if self.refresh_cookie_samesite not in {"strict", "lax"}:
            raise ValueError("REFRESH_COOKIE_SAMESITE must be strict or lax")
        if not 4 <= self.otp_length <= 8:
            raise ValueError("OTP_LENGTH must be between 4 and 8")
        return self


class ServiceDatabaseSettings(DatabaseSettings):
    """identity_db, reached only by this service's roles."""

    name: str = "identity_db"
    user: str = "identity_service_role"
    migration_user: str | None = Field(default="identity_migration_role")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_db_settings() -> ServiceDatabaseSettings:
    return ServiceDatabaseSettings()
