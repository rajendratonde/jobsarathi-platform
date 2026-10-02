"""Standard API error model (Implementation Blueprint §21) and handlers.

Every service answers errors in the same shape:

    {"type", "status", "code", "message", "errors": [...], "details": {},
     "correlation_id", "timestamp"}

Stack traces never reach the response body.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from js_core import context

log = logging.getLogger("js_core.errors")
ERROR_TYPE_BASE = "https://jobsarathi.in/errors/"


class FieldError(BaseModel):
    field: str
    code: str
    message: str


class ErrorResponse(BaseModel):
    type: str
    status: int
    code: str
    message: str
    errors: list[FieldError] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    timestamp: str


class AppError(Exception):
    status = 500
    code = "INTERNAL_ERROR"
    message = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 errors: list[FieldError] | None = None, details: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.code = code or self.code
        self.errors = errors or []
        self.details = details or {}
        self.headers = headers or {}


class BadRequest(AppError):
    status, code, message = 400, "BAD_REQUEST", "The request is not valid."


class Unauthenticated(AppError):
    status, code, message = 401, "UNAUTHENTICATED", "Sign in to continue."


class PermissionDenied(AppError):
    status, code, message = 403, "PERMISSION_DENIED", "You do not have permission to do this."


class NotFound(AppError):
    status, code, message = 404, "NOT_FOUND", "Not found."


class Conflict(AppError):
    status, code, message = 409, "CONFLICT", "This conflicts with the current state."


class VersionConflict(Conflict):
    code, message = "VERSION_CONFLICT", "This record was changed by someone else. Reload and try again."


class ValidationFailed(AppError):
    status, code, message = 422, "VALIDATION_FAILED", "Some fields need attention."


class Locked(AppError):
    status, code, message = 423, "LOCKED", "This is locked."


class RateLimited(AppError):
    status, code, message = 429, "RATE_LIMITED", "Too many requests. Please wait and try again."


class DependencyUnavailable(AppError):
    status, code, message = 503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable. Try again shortly."


class IntegrationDisabled(DependencyUnavailable):
    code, message = "INTEGRATION_DISABLED", "This integration is switched off in this environment."


def _body(status: int, code: str, message: str, errors: list[FieldError] | None = None,
          details: dict[str, Any] | None = None) -> dict[str, Any]:
    return ErrorResponse(
        type=ERROR_TYPE_BASE + code.lower().replace("_", "-"),
        status=status, code=code, message=message, errors=errors or [], details=details or {},
        correlation_id=context.correlation_id_var.get(),
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
    ).model_dump(mode="json")


def error_response(status: int, code: str, message: str, errors: list[FieldError] | None = None,
                   details: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(_body(status, code, message, errors, details), status_code=status, headers=headers)


_HTTP_CODES = {400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
               405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE",
               422: "VALIDATION_FAILED", 428: "PRECONDITION_REQUIRED", 429: "RATE_LIMITED", 503: "DEPENDENCY_UNAVAILABLE"}


def _field_name(location: Any) -> str:
    """("body", "salary", "max") -> "salary.max"; the request part is dropped."""
    return ".".join(str(p) for p in location if p not in ("body", "query", "path", "header")) or "request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            log.error("Application error %s: %s", exc.code, exc.message)
        return error_response(exc.status, exc.code, exc.message, exc.errors, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [FieldError(field=_field_name(err.get("loc", [])), code=str(err.get("type", "invalid")).upper(),
                             message=err.get("msg", "Invalid value"))
                  for err in exc.errors()]
        return error_response(422, "VALIDATION_FAILED", "Some fields need attention.", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
        return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError) -> JSONResponse:
        exc = VersionConflict()
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", type(exc).__name__)
        return error_response(500, "INTERNAL_ERROR", "Something went wrong. Please try again.")
