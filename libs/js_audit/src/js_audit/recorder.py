"""Write an audit row inside the caller's transaction.

The row is added to the same session as the business change, so it commits
or rolls back with it. Sensitive values are masked before they are stored.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from js_core import context
from js_core.logging import mask


class ActorType(StrEnum):
    USER = "USER"
    SERVICE = "SERVICE"
    SYSTEM = "SYSTEM"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


def record_audit(session: Session, model: type, *, action: str, entity_type: str,
                 entity_id: uuid.UUID | None = None, actor_user_id: uuid.UUID | None = None,
                 actor_type: ActorType = ActorType.USER, organization_id: uuid.UUID | None = None,
                 result: AuditResult = AuditResult.SUCCESS, before: dict[str, Any] | None = None,
                 after: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> Any:
    """Add one audit row to ``session`` (not committed here)."""
    ctx = context.current()
    row = model(
        action=action[:60], entity_type=entity_type[:50], entity_id=entity_id,
        actor_user_id=actor_user_id, actor_type=str(actor_type), organization_id=organization_id,
        result=str(result), before_data=mask(before) if before else None, after_data=mask(after) if after else None,
        metadata_=mask(metadata) if metadata else None, correlation_id=ctx.correlation_id,
        ip_address=ctx.client_ip, user_agent=ctx.user_agent,
    )
    session.add(row)
    return row
