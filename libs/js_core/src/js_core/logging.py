"""Structured logging.

Technical logs only (business audit lives in audit_logs). Every line carries
the service, environment, correlation and request IDs. Values under sensitive
keys are masked before anything is written.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from js_core import context

SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|authorization|cookie|otp|code_hash|api[_-]?key|credential|smtp_password)", re.I)
MASK = "***"

_RESERVED = set(vars(logging.LogRecord("x", 0, "x", 0, "x", None, None)).keys()) | {"message", "asctime"}


def mask(value: Any) -> Any:
    """Recursively mask values whose key looks sensitive."""
    if isinstance(value, dict):
        return {k: (MASK if SENSITIVE_KEYS.search(str(k)) else mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


class ContextFilter(logging.Filter):
    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self.service = service
        self.env = env

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service
        record.env = self.env
        record.correlation_id = context.correlation_id_var.get()
        record.request_id = context.request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, "service", None),
            "env": getattr(record, "env", None),
            "correlation_id": getattr(record, "correlation_id", None),
            "request_id": getattr(record, "request_id", None),
        }
        extra = {k: v for k, v in vars(record).items()
                 if k not in _RESERVED and k not in payload and k not in {"service", "env", "color_message"}}
        if extra:
            payload.update(mask(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(service)s [%(correlation_id)s] %(name)s: %(message)s")


def configure_logging(service: str, env: str, level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(ContextFilter(service, env))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's own access log duplicates our request log.
    logging.getLogger("uvicorn.access").handlers[:] = []
    logging.getLogger("uvicorn.access").propagate = False
    for name in ("uvicorn", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
