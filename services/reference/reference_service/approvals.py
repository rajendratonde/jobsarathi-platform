"""Maker-Checker handlers: one per reference list (entity_type = list key in capitals).

Changes are proposal-gated (v5): nothing touches the list until a different person
approves; then the stored proposal is applied by the same functions the direct path uses.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from js_approval import ApprovalEngine
from reference_service import service
from reference_service.lists import LISTS, ReferenceListDef


class ReferenceHandler:
    def __init__(self, definition: ReferenceListDef) -> None:
        self.d = definition

    def version_of(self, entity: Any) -> int:
        return service.record_version(entity)

    def load_for_update(self, session: Session, entity_id: uuid.UUID) -> Any | None:
        return session.scalar(select(self.d.model).where(self.d.model.id == entity_id).with_for_update())

    def apply_approval(self, session: Session, entity: Any | None, request: Any, checker: uuid.UUID) -> None:
        proposed = dict(request.proposed_changes or {})
        if request.action_type == "CREATE":
            service.apply_create(session, self.d, proposed, checker, entity_id=request.entity_id, request=request)
        elif request.action_type == "UPDATE":
            service.apply_update(session, self.d, entity, proposed, checker, request=request)
        elif request.action_type == "STATUS_CHANGE":
            service.apply_status(session, self.d, entity, bool(proposed["is_active"]), checker, request=request)
        else:
            raise ValueError(f"Unknown action {request.action_type}")

    def apply_rejection(self, session: Session, entity: Any | None, request: Any, checker: uuid.UUID) -> None:
        return None  # the proposal was never applied

    def apply_withdrawal(self, session: Session, entity: Any | None, request: Any, actor: uuid.UUID) -> None:
        return None


def register_handlers(engine: ApprovalEngine) -> None:
    for definition in LISTS.values():
        engine.register(definition.entity_type, ReferenceHandler(definition))
