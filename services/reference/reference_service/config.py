"""Configuration for the Reference Data service. All values come from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr

from js_core.config import DatabaseSettings, ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "reference"

    # Identity: verifies access tokens (JWKS) and resolves permissions (internal authz API).
    identity_url: str = "http://127.0.0.1:8001"
    # This service's own EC P-256 private key for service tokens (env:NAME / file:/path).
    # Identity must hold the matching public key under SERVICE_PUBLIC_KEYS["reference"].
    service_private_key_ref: SecretStr | None = None
    authz_cache_seconds: int = 60  # Blueprint: callers cache permissions for at most 60 s

    # Public read API: browsers and services may cache lists this long (ETag revalidation after).
    read_max_age_seconds: int = 300


class ServiceDatabaseSettings(DatabaseSettings):
    """reference_db, reached only by this service's roles."""

    name: str = "reference_db"
    user: str = "reference_service_role"
    migration_user: str | None = Field(default="reference_migration_role")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_db_settings() -> ServiceDatabaseSettings:
    return ServiceDatabaseSettings()
