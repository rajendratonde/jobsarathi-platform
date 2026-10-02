"""Health endpoints.

* ``/health/live``  - the process is up (no dependencies checked)
* ``/health/ready`` - the database answers and the schema is at the latest migration
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from js_core.db.session import Database

log = logging.getLogger("js_core.health")


def health_router(service_name: str, version: str, database: Database | None,
                  expected_revision: Callable[[], str | None] | None = None) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live")
    def live() -> dict:
        return {"status": "ok", "service": service_name, "version": version}

    @router.get("/ready")
    def ready() -> JSONResponse:
        checks: dict[str, dict] = {}
        ok = True
        if database is not None:
            try:
                database.ping()
                checks["database"] = {"status": "ok"}
            except Exception as exc:  # never leak connection strings
                ok = False
                log.warning("Readiness: database unreachable (%s)", type(exc).__name__)
                checks["database"] = {"status": "error", "reason": type(exc).__name__}
            if expected_revision is not None and checks["database"]["status"] == "ok":
                expected, current = expected_revision(), database.current_revision()
                migrated = expected is not None and current == expected
                ok = ok and migrated
                checks["migrations"] = {"status": "ok" if migrated else "pending",
                                        "current": current, "expected": expected}
        body = {"status": "ok" if ok else "unavailable", "service": service_name, "version": version, "checks": checks}
        return JSONResponse(body, status_code=200 if ok else 503)

    return router
