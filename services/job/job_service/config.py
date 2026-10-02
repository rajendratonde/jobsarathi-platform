"""Configuration for the Job service. All values come from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from js_core.config import DatabaseSettings, ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "job"


class ServiceDatabaseSettings(DatabaseSettings):
    """job_db, reached only by this service's roles."""

    name: str = "job_db"
    user: str = "job_service_role"
    migration_user: str | None = Field(default="job_migration_role")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_db_settings() -> ServiceDatabaseSettings:
    return ServiceDatabaseSettings()
