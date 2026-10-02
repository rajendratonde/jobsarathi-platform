"""FastAPI application factory used by every service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from js_core.config import ServiceSettings
from js_core.db.session import Database
from js_core.errors import ErrorResponse, install_error_handlers
from js_core.health import health_router
from js_core.logging import configure_logging
from js_core.middleware import RequestContextMiddleware

log = logging.getLogger("js_core.app")

ERROR_RESPONSES = {code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 429, 500, 503)}


def create_app(*, settings: ServiceSettings, version: str, database: Database | None,
               routers: Sequence[APIRouter] = (), expected_revision: Callable[[], str | None] | None = None,
               on_startup: Callable[[], None] | None = None) -> FastAPI:
    configure_logging(settings.service_name, settings.app_env.value, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("starting", extra={"version": version, "middleware_enabled": settings.middleware_enabled})
        if on_startup:
            on_startup()
        yield
        if database is not None:
            database.dispose()
        log.info("stopped")

    app = FastAPI(
        title=f"JobSarathi {settings.service_name} service",
        version=version,
        lifespan=lifespan,
        docs_url="/docs" if settings.show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.show_docs else None,
        responses=ERROR_RESPONSES,
    )
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["X-Correlation-Id", "X-Request-Id", "ETag"])
    app.add_middleware(RequestContextMiddleware)  # outermost: every response carries the IDs

    app.include_router(health_router(settings.service_name, version, database, expected_revision))
    for router in routers:
        app.include_router(router, prefix=settings.api_prefix)
    return app
