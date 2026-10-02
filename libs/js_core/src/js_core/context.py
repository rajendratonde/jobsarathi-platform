"""Per-request context carried through logs, audit rows and outbound calls.

Set by the request middleware; read anywhere without passing it around.
Authentication will add the actor and active organization in the Identity
phase; until then they stay empty.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)
user_agent_var: ContextVar[str | None] = ContextVar("user_agent", default=None)

# Accept only plain, short IDs from callers so a header cannot inject log lines.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_id() -> str:
    return uuid.uuid4().hex


def accept_correlation_id(value: str | None) -> str | None:
    if value and _SAFE_ID.match(value):
        return value
    return None


@dataclass(frozen=True)
class RequestContext:
    correlation_id: str | None
    request_id: str | None
    client_ip: str | None
    user_agent: str | None


def current() -> RequestContext:
    return RequestContext(
        correlation_id=correlation_id_var.get(),
        request_id=request_id_var.get(),
        client_ip=client_ip_var.get(),
        user_agent=user_agent_var.get(),
    )
