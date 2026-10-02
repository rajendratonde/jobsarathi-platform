"""Request middleware: correlation/request IDs and the request log line.

Pure ASGI (no BaseHTTPMiddleware) so streaming and background tasks are unaffected.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from js_core import context

CORRELATION_HEADER = "x-correlation-id"
REQUEST_HEADER = "x-request-id"
log = logging.getLogger("js_core.request")

# Health probes would otherwise flood the log.
QUIET_PATHS = ("/health/live", "/health/ready")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        correlation_id = context.accept_correlation_id(headers.get(CORRELATION_HEADER)) or context.new_id()
        request_id = context.new_id()
        client = scope.get("client")
        tokens = [
            context.correlation_id_var.set(correlation_id),
            context.request_id_var.set(request_id),
            context.client_ip_var.set(context.accept_ip(client[0]) if client else None),
            context.user_agent_var.set((headers.get("user-agent") or "")[:300] or None),
        ]
        started = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_with_ids(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw = list(message.get("headers", []))
                raw.append((b"x-correlation-id", correlation_id.encode()))
                raw.append((b"x-request-id", request_id.encode()))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_with_ids)
        finally:
            path = scope.get("path", "")
            if not path.startswith(QUIET_PATHS) or status_holder["status"] >= 400:
                log.info("request", extra={
                    "http_method": scope.get("method"), "path": path, "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
            for var, token in zip((context.correlation_id_var, context.request_id_var,
                                   context.client_ip_var, context.user_agent_var), tokens, strict=True):
                var.reset(token)
