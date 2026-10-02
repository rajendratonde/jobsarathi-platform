"""Configuration for the Employer service. All values come from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from js_core.config import DatabaseSettings, ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "employer"


class ServiceDatabaseSettings(DatabaseSettings):
    """employer_db, reached only by this service's roles."""

    name: str = "employer_db"
    user: str = "employer_service_role"
    migration_user: str | None = Field(default="employer_migration_role")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_db_settings() -> ServiceDatabaseSettings:
    return ServiceDatabaseSettings()
