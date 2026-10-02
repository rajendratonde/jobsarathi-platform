"""Add an event to the outbox inside the business transaction.

Naming: past tense, PascalCase (``JobPublished``). Payload carries IDs and the
changed state, never personal data beyond IDs.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

_EVENT_NAME = re.compile(r"^[A-Z][A-Za-z0-9]+$")


def add_event(session: Session, model: type, *, aggregate_type: str, aggregate_id: uuid.UUID, event_type: str,
              payload: dict[str, Any], organization_id: uuid.UUID | None = None, event_version: int = 1) -> Any:
    if not _EVENT_NAME.match(event_type):
        raise ValueError(f"Event type must be PascalCase, got {event_type!r}")
    row = model(aggregate_type=aggregate_type[:50], aggregate_id=aggregate_id, event_type=event_type,
                event_version=event_version, payload=payload, organization_id=organization_id)
    session.add(row)
    return row
