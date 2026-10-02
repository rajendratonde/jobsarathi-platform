from __future__ import annotations

from js_core.config import Environment


class UnsafeIntegrationConfig(RuntimeError):
    """Raised at start-up for a configuration that must never run in production."""


def forbid_dev_sink(mode: str, env: Environment, what: str) -> None:
    if mode == "dev_log" and not env.allows_dev_tools:
        raise UnsafeIntegrationConfig(
            f"{what} delivery mode 'dev_log' is only allowed in local, development and test (APP_ENV={env.value})")
