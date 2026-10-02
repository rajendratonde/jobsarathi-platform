"""Service configuration.

Everything environment-specific comes from environment variables (or an
untracked .env file locally). Nothing AWS-specific is hard-coded: hosts,
buckets and secret locations are plain settings.
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from js_core import secrets


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is Environment.PRODUCTION

    @property
    def allows_dev_tools(self) -> bool:
        """Dev-only conveniences (log sinks, docs UI, migrate-on-start)."""
        return self in {Environment.LOCAL, Environment.DEVELOPMENT, Environment.TEST}


class DatabaseSettings(BaseSettings):
    """One service's own database. The runtime role can only reach this database."""

    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore", hide_input_in_errors=True)

    host: str = "localhost"
    port: int = 5432
    name: str
    user: str
    password: SecretStr
    # Migration role owns the schema; the runtime role cannot run DDL.
    migration_user: str | None = None
    migration_password: SecretStr | None = None
    sslmode: str = "prefer"
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout_seconds: int = 10
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 15000

    def _url(self, user: str, password: SecretStr | None) -> str:
        pwd = secrets.resolve(password)
        auth = quote(user, safe="") + (":" + quote(pwd.get_secret_value(), safe="") if pwd else "")
        return f"postgresql+psycopg://{auth}@{self.host}:{self.port}/{self.name}?sslmode={self.sslmode}"

    def runtime_url(self) -> str:
        return self._url(self.user, self.password)

    def migration_url(self) -> str:
        if self.migration_user:
            return self._url(self.migration_user, self.migration_password)
        return self.runtime_url()


class ServiceSettings(BaseSettings):
    """Base settings every service extends."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)  # never echo secrets in config errors

    service_name: str
    app_env: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_format: str = "json"  # json | text
    api_prefix: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool | None = None  # default: on outside production
    run_migrations_on_start: bool = False
    middleware_enabled: bool = False  # MIDDLEWARE_ENABLED

    @field_validator("log_format")
    @classmethod
    def _log_format(cls, value: str) -> str:
        if value not in {"json", "text"}:
            raise ValueError("log_format must be json or text")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> ServiceSettings:
        if self.app_env.is_production:
            if self.run_migrations_on_start:
                raise ValueError("RUN_MIGRATIONS_ON_START is not allowed in production; migrate as a separate step")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS='*' is not allowed in production")
            if self.log_format != "json":
                raise ValueError("Production logs must be JSON")
        return self

    @property
    def show_docs(self) -> bool:
        return self.docs_enabled if self.docs_enabled is not None else not self.app_env.is_production
