from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from js_core import context
from js_core.errors import DependencyUnavailable, FieldError, ValidationFailed

log = logging.getLogger("js_reference")


@dataclass(frozen=True)
class ReferenceValue:
    code: str
    name: str
    name_hi: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReferenceList:
    values: dict[str, ReferenceValue]
    etag: str | None
    fetched_at: float


class ReferenceClient:
    def __init__(self, base_url: str, *, ttl_seconds: float = 300, timeout: float = 2.0, retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl = ttl_seconds
        self.timeout = timeout
        self.retries = retries
        self._lists: dict[str, ReferenceList] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ public API
    def values(self, list_name: str) -> dict[str, ReferenceValue]:
        return self._get(list_name).values

    def is_valid(self, list_name: str, code: str) -> bool:
        return code in self.values(list_name)

    def require(self, list_name: str, code: str, *, field_name: str | None = None) -> ReferenceValue:
        value = self.values(list_name).get(code)
        if value is None:
            raise ValidationFailed(errors=[FieldError(field=field_name or list_name, code="UNKNOWN_CODE",
                                                      message=f"'{code}' is not a valid value.")])
        return value

    def label(self, list_name: str, code: str) -> str | None:
        value = self.values(list_name).get(code)
        return value.name if value else None

    # ------------------------------------------------------------ cache
    def _get(self, list_name: str) -> ReferenceList:
        with self._lock:
            cached = self._lists.get(list_name)
        if cached and time.monotonic() - cached.fetched_at < self.ttl:
            return cached
        fresh = self._fetch(list_name, cached)
        if fresh is not None:
            with self._lock:
                self._lists[list_name] = fresh
            return fresh
        if cached:
            log.warning("Reference Data unreachable; using the last good copy of %s", list_name)
            return cached
        raise DependencyUnavailable("Reference data is unavailable. Try again shortly.", code="REFERENCE_UNAVAILABLE")

    def _fetch(self, list_name: str, cached: ReferenceList | None) -> ReferenceList | None:
        url = f"{self.base_url}/v1/reference/{list_name}"
        for _ in range(self.retries + 1):
            request = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310 - configured URL
            if cached and cached.etag:
                request.add_header("If-None-Match", cached.etag)
            correlation = context.correlation_id_var.get()
            if correlation:
                request.add_header("X-Correlation-Id", correlation)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - configured URL
                    body = json.loads(response.read().decode("utf-8"))
                    return ReferenceList(values=_parse(body), etag=response.headers.get("ETag"),
                                         fetched_at=time.monotonic())
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and cached:
                    return ReferenceList(values=cached.values, etag=cached.etag, fetched_at=time.monotonic())
                if exc.code == 404:
                    raise ValueError(f"Unknown reference list '{list_name}'") from exc
            except (OSError, ValueError):
                pass
        return None


_BASE = {"code", "name", "name_hi", "sort_order"}


def _parse(body: dict) -> dict[str, ReferenceValue]:
    return {item["code"]: ReferenceValue(code=item["code"], name=item["name"], name_hi=item.get("name_hi"),
                                         extra={k: v for k, v in item.items() if k not in _BASE})
            for item in body.get("items", [])}
