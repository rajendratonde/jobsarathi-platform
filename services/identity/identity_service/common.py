"""Helpers shared by the Identity use cases: audit, events, lookups, version and scope checks."""

from __future__ import annotations

import uuid
from typing import Any

from js_auth.context import Authorized, Scope
from sqlalchemy import select
from sqlalchemy.orm import Session

from identity_service.models import AuditLog, OutboxEvent
from js_audit import ActorType, AuditResult, record_audit
from js_core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed, VersionConflict
from js_outbox import add_event


def audit(session: Session, *, action: str, entity_type: str, entity_id: uuid.UUID | None = None,
          actor: uuid.UUID | None = None, organization_id: uuid.UUID | None = None,
          result: AuditResult = AuditResult.SUCCESS, before: dict | None = None, after: dict | None = None,
          metadata: dict | None = None, actor_type: ActorType = ActorType.USER) -> None:
    """Never pass credentials, OTP codes, hashes or tokens here; values are masked again on write."""
    record_audit(session, AuditLog, action=action, entity_type=entity_type, entity_id=entity_id,
                 actor_user_id=actor,
                 actor_type=actor_type if (actor or actor_type is not ActorType.USER) else ActorType.SYSTEM,
                 organization_id=organization_id, result=result, before=_json(before), after=_json(after),
                 metadata=_json(metadata))


def event(session: Session, *, aggregate_type: str, aggregate_id: uuid.UUID, event_type: str, payload: dict,
          organization_id: uuid.UUID | None = None) -> None:
    add_event(session, OutboxEvent, aggregate_type=aggregate_type, aggregate_id=aggregate_id, event_type=event_type,
              payload=_json(payload) or {}, organization_id=organization_id)


def _json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def get_or_404[T](session: Session, model: type[T], entity_id: uuid.UUID, *, label: str,
               include_deleted: bool = False, for_update: bool = False) -> T:
    stmt = select(model).where(model.id == entity_id)  # type: ignore[attr-defined]
    if for_update:
        stmt = stmt.with_for_update()
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    obj = session.scalar(stmt)
    if obj is None:
        raise NotFound(f"{label} not found.")
    return obj


def check_version(entity: Any, expected: int | None) -> None:
    if expected is None:
        raise ValidationFailed(errors=[FieldError(field="version", code="REQUIRED",
                                                  message="Send the version you are editing (If-Match).")])
    if entity.version != expected:
        raise VersionConflict(details={"current_version": entity.version})


def require_all_scope(caller: Authorized) -> None:
    if caller.scope is not Scope.ALL:
        raise PermissionDenied("This needs platform-wide access.")


def require_organization(caller: Authorized, organization_id: uuid.UUID | None) -> None:
    """ORGANIZATION scope reaches only the active organization; ALL reaches every one."""
    if not caller.allows_organization(organization_id):
        raise PermissionDenied("You cannot act for this organization.")


def parse_if_match(value: str | None) -> int | None:
    if not value:
        return None
    raw = value.strip().removeprefix("W/").strip('"')
    try:
        return int(raw)
    except ValueError:
        raise ValidationFailed(errors=[FieldError(field="If-Match", code="INVALID",
                                                  message="If-Match must be the record version.")]) from None
