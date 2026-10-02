"""Reference list use cases: read, validate, create, edit, (de)activate.

Rules (v5 section 19):
* values are never deleted: deactivate instead; codes are never changed or reused
* a code is unique within its list for ever (lookup_values: within list_code)
* city names are unique per state (case-insensitive)
* a new or edited child needs an active parent; public reads hide children whose parent is inactive
* when a list's approval policy is on, every change is a proposal applied on approval
  (proposed_changes), with the record's version checked again at approval time
"""

from __future__ import annotations

import re
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from js_approval import NEW_RECORD_VERSION
from js_audit import AuditResult, record_audit
from js_auth.context import Authorized
from js_core.errors import Conflict, FieldError, NotFound, ValidationFailed, VersionConflict
from js_outbox import add_event
from reference_service.lists import ReferenceListDef, get_list
from reference_service.models import ApprovalRequest, AuditLog, OutboxEvent
from reference_service.runtime import Runtime

CODE = re.compile(r"^[A-Z0-9][A-Z0-9_]{0,49}$")
EDITABLE = ("name", "name_hi", "sort_order")


def _now() -> datetime:
    return datetime.now(UTC)


def record_version(row: Any) -> int:
    """v5 reference tables have no version column: a fingerprint of the last change stands in
    for it (optimistic locking and the Maker-Checker version check). No schema change."""
    marker = f"{row.updated_at.timestamp():.6f}|{row.is_active}"
    return zlib.crc32(marker.encode()) & 0x7FFFFFFF


# ------------------------------------------------------------------ parents and serialization
def _parent_rows(session: Session, d: ReferenceListDef, ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not d.parent or not ids:
        return {}
    parent_model = get_list(d.parent.list_key).model
    return {p.id: p for p in session.scalars(select(parent_model).where(parent_model.id.in_(ids)))}


def to_public(d: ReferenceListDef, row: Any, parents: dict[uuid.UUID, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"code": row.code, "name": row.name, "name_hi": row.name_hi, "sort_order": row.sort_order}
    for column in d.columns:
        if column != "list_code":
            item[column] = getattr(row, column)
    if d.parent:
        parent = parents.get(getattr(row, d.parent.column))
        item[d.parent.field] = parent.code if parent else None
    return item


def to_admin(d: ReferenceListDef, row: Any, parents: dict[uuid.UUID, Any], pending: dict[uuid.UUID, Any]) -> dict:
    item = to_public(d, row, parents)
    if "list_code" in d.columns:
        item["list_code"] = row.list_code
    request = pending.get(row.id)
    item.update({"id": str(row.id), "is_active": row.is_active, "version": record_version(row),
                 "updated_at": row.updated_at.isoformat(),
                 "pending_request": None if request is None else {
                     "id": str(request.id), "request_number": request.request_number,
                     "action_type": request.action_type, "summary": request.change_summary}})
    return item


def pending_requests(session: Session, d: ReferenceListDef, ids: list[uuid.UUID] | None = None) -> dict:
    stmt = select(ApprovalRequest).where(ApprovalRequest.entity_type == d.entity_type,
                                         ApprovalRequest.status == "PENDING")
    if ids is not None:
        stmt = stmt.where(ApprovalRequest.entity_id.in_(ids))
    return {r.entity_id: r for r in session.scalars(stmt)}


# ------------------------------------------------------------------ public read
def public_values(session: Session, d: ReferenceListDef, *, q: str | None = None,
                  parent_code: str | None = None, list_code: str | None = None) -> list[dict[str, Any]]:
    m = d.model
    stmt = select(m).where(m.is_active.is_(True))
    if list_code is not None:
        stmt = stmt.where(m.list_code == list_code)
    if d.parent:
        parent_model = get_list(d.parent.list_key).model
        column = getattr(m, d.parent.column)
        # a child whose parent is inactive is hidden; a child without a parent (optional) stays
        stmt = stmt.outerjoin(parent_model, parent_model.id == column).where(
            or_(column.is_(None), parent_model.is_active.is_(True)))
        if parent_code:
            stmt = stmt.where(parent_model.code == parent_code)
    if q and d.searchable:
        stmt = stmt.where(m.name.ilike(f"%{q.strip()}%"))  # served by the trigram index
    rows = session.scalars(stmt.order_by(m.sort_order, m.name)).all()
    parents = _parent_rows(session, d, {getattr(r, d.parent.column) for r in rows if d.parent} - {None})
    return [to_public(d, r, parents) for r in rows]


def list_fingerprint(session: Session, d: ReferenceListDef, list_code: str | None = None) -> str:
    """Changes whenever any value in the list (or a parent list) changes: the ETag base."""
    parts = []
    for model in [d.model] + ([get_list(d.parent.list_key).model] if d.parent else []):
        stmt = select(func.count(), func.max(model.updated_at))
        if list_code is not None and model is d.model:
            stmt = stmt.where(model.list_code == list_code)
        count, latest = session.execute(stmt).one()
        parts.append(f"{count}:{latest.timestamp() if latest else 0}")
    return "|".join(parts)


# ------------------------------------------------------------------ validation
def _bad(field: str, code: str, message: str) -> ValidationFailed:
    return ValidationFailed(errors=[FieldError(field=field, code=code, message=message)])


def _resolve_parent(session: Session, d: ReferenceListDef, data: dict) -> uuid.UUID | None:
    assert d.parent is not None
    code = data.get(d.parent.field)
    if not code:
        if d.parent.required:
            raise _bad(d.parent.field, "REQUIRED", "Choose a value.")
        return None
    parent_model = get_list(d.parent.list_key).model
    parent = session.scalar(select(parent_model).where(parent_model.code == code))
    if parent is None:
        raise _bad(d.parent.field, "UNKNOWN_CODE", f"'{code}' does not exist.")
    if not parent.is_active:
        raise _bad(d.parent.field, "INACTIVE", f"'{code}' is inactive.")
    return parent.id


def clean(session: Session, d: ReferenceListDef, data: dict, *, creating: bool, row: Any | None = None) -> dict:
    """Validated column values for the model (parent codes resolved to ids)."""
    values: dict[str, Any] = {}
    if creating:
        code = (data.get("code") or "").strip().upper()
        if not CODE.match(code):
            raise _bad("code", "INVALID_CODE", "Use capital letters, digits and underscores (max 50).")
        values["code"] = code
    elif data.get("code") not in (None, row.code if row else None):
        raise _bad("code", "IMMUTABLE", "A code never changes. Deactivate this value and add a new one.")
    if creating or "name" in data:
        name = (data.get("name") or "").strip()
        if not 1 <= len(name) <= 150:
            raise _bad("name", "LENGTH", "Enter a name of 1 to 150 characters.")
        values["name"] = name
    if "name_hi" in data:
        name_hi = (data.get("name_hi") or "").strip() or None
        if name_hi and len(name_hi) > 150:
            raise _bad("name_hi", "LENGTH", "Use at most 150 characters.")
        values["name_hi"] = name_hi
    if "sort_order" in data or creating:
        sort_order = data.get("sort_order", 0)
        if not isinstance(sort_order, int) or not 0 <= sort_order <= 1_000_000:
            raise _bad("sort_order", "RANGE", "Use a whole number from 0 to 1,000,000.")
        values["sort_order"] = sort_order
    for extra in d.extras:
        if extra.kind == "parent":
            if creating or extra.name in data:
                values[d.parent.column] = _resolve_parent(session, d, data)  # type: ignore[union-attr]
            continue
        if not creating and extra.name not in data:
            continue
        if not creating and extra.immutable:
            if data[extra.name] != getattr(row, extra.name):
                raise _bad(extra.name, "IMMUTABLE", "This cannot be changed.")
            continue
        value = data.get(extra.name)
        if value is None:
            if extra.required:
                raise _bad(extra.name, "REQUIRED", f"{extra.label} is required.")
        elif extra.kind == "int" and (not isinstance(value, int) or not 0 <= value <= 32767 * 1000):
            raise _bad(extra.name, "RANGE", f"{extra.label} must be a whole number of 0 or more.")
        elif extra.kind == "text":
            value = str(value).strip().upper()
            if not CODE.match(value):
                raise _bad(extra.name, "INVALID_CODE", "Use capital letters, digits and underscores.")
        values[extra.name] = value
    if d.key == "education_levels" and "level_rank" in values and values["level_rank"] > 32767:
        raise _bad("level_rank", "RANGE", "Level rank is too large.")
    if d.key == "experience_bands":
        low = values.get("min_months", getattr(row, "min_months", None))
        high = values.get("max_months", getattr(row, "max_months", None)) if "max_months" in values or row else None
        if low is not None and high is not None and high <= low:
            raise _bad("max_months", "RANGE", "Maximum months must be more than minimum months.")
    return values


def check_unique(session: Session, d: ReferenceListDef, values: dict, *, row_id: uuid.UUID | None = None) -> None:
    m = d.model
    if "code" in values:
        stmt = select(m.id).where(m.code == values["code"])
        if "list_code" in d.columns:
            stmt = stmt.where(m.list_code == values["list_code"])
        if session.scalar(stmt):
            raise Conflict("This code is already used in this list (codes are never reused).", code="CODE_TAKEN")
        pending = session.scalars(select(ApprovalRequest.proposed_changes).where(
            ApprovalRequest.entity_type == d.entity_type, ApprovalRequest.status == "PENDING",
            ApprovalRequest.action_type == "CREATE"))
        for proposal in pending:
            if (proposal or {}).get("code") == values["code"] and (
                    "list_code" not in d.columns or proposal.get("list_code") == values.get("list_code")):
                raise Conflict("A pending request already proposes this code.", code="CODE_PENDING")
    if d.key == "cities" and ("name" in values or "state_id" in values):
        current = session.get(m, row_id) if row_id else None
        name = values.get("name", current.name if current else "")
        state_id = values.get("state_id", current.state_id if current else None)
        stmt = select(m.id).where(m.state_id == state_id, func.lower(m.name) == name.lower())
        if row_id:
            stmt = stmt.where(m.id != row_id)
        if session.scalar(stmt):
            raise Conflict("This state already has a city with this name.", code="NAME_TAKEN")


# ------------------------------------------------------------------ apply (direct or on approval)
def _serial(values: dict) -> dict:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in values.items()}


def _audit(session: Session, *, action: str, d: ReferenceListDef, entity_id: uuid.UUID, actor: uuid.UUID,
           before: dict | None = None, after: dict | None = None, metadata: dict | None = None,
           result: AuditResult = AuditResult.SUCCESS) -> None:
    record_audit(session, AuditLog, action=action, entity_type=d.entity_type, entity_id=entity_id,
                 actor_user_id=actor, before=before, after=after, metadata=metadata, result=result)


def _event(session: Session, d: ReferenceListDef, row: Any, change: str) -> None:
    add_event(session, OutboxEvent, aggregate_type="REFERENCE_VALUE", aggregate_id=row.id,
              event_type="ReferenceValueChanged",
              payload={"list": d.key, "code": row.code, "change": change, "is_active": row.is_active})


def apply_create(session: Session, d: ReferenceListDef, values: dict, actor: uuid.UUID, *,
                 entity_id: uuid.UUID | None = None, request: Any | None = None) -> Any:
    values = {k: (uuid.UUID(v) if k.endswith("_id") and isinstance(v, str) else v) for k, v in values.items()}
    if request is not None:  # at approval time the code may have been taken by a direct change meanwhile
        m = d.model
        stmt = select(m.id).where(m.code == values["code"])
        if "list_code" in d.columns:
            stmt = stmt.where(m.list_code == values["list_code"])
        if session.scalar(stmt):
            raise Conflict("This code was created by another change in the meantime.", code="CODE_TAKEN")
    row = d.model(**({"id": entity_id} if entity_id else {}), **values, created_by=actor, updated_by=actor)
    session.add(row)
    session.flush()
    _audit(session, action="REFERENCE.CREATED", d=d, entity_id=row.id, actor=actor, after=_serial(values),
           metadata=_approval_meta(request))
    _event(session, d, row, "CREATED")
    return row


def apply_update(session: Session, d: ReferenceListDef, row: Any, values: dict, actor: uuid.UUID, *,
                 request: Any | None = None) -> Any:
    values = {k: (uuid.UUID(v) if k.endswith("_id") and isinstance(v, str) else v) for k, v in values.items()}
    before = {k: getattr(row, k) for k in values}
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by, row.updated_at = actor, _now()
    session.flush()
    _audit(session, action="REFERENCE.UPDATED", d=d, entity_id=row.id, actor=actor, before=_serial(before),
           after=_serial(values), metadata=_approval_meta(request))
    _event(session, d, row, "UPDATED")
    return row


def apply_status(session: Session, d: ReferenceListDef, row: Any, is_active: bool, actor: uuid.UUID, *,
                 request: Any | None = None) -> Any:
    row.is_active, row.updated_by, row.updated_at = is_active, actor, _now()
    session.flush()
    _audit(session, action="REFERENCE.ACTIVATED" if is_active else "REFERENCE.DEACTIVATED", d=d, entity_id=row.id,
           actor=actor, before={"is_active": not is_active}, after={"is_active": is_active},
           metadata=_approval_meta(request))
    _event(session, d, row, "ACTIVATED" if is_active else "DEACTIVATED")
    return row


def _approval_meta(request: Any | None) -> dict | None:
    if request is None:
        return None
    return {"approval_request": request.request_number, "maker_user_id": str(request.maker_user_id)}


# ------------------------------------------------------------------ commands
@dataclass
class ChangeResult:
    status: str                  # APPLIED | PENDING_APPROVAL | UNCHANGED
    entity_id: uuid.UUID
    row: Any | None = None
    approval_request: Any | None = None


def _submit(rt: Runtime, session: Session, caller: Authorized, d: ReferenceListDef, *, entity_id: uuid.UUID,
            version: int, action_type: str, proposed: dict, summary: str) -> ChangeResult:
    request = rt.approvals.submit(
        session, entity_type=d.entity_type, entity_id=entity_id, entity_version=version, action_type=action_type,
        maker=caller.auth.user_id, maker_permissions=caller.permissions, organization_id=None,
        proposed_changes=_serial(proposed), change_summary=summary, acting_organization_id=caller.auth.organization_id)
    _audit(session, action="APPROVAL.SUBMITTED", d=d, entity_id=entity_id, actor=caller.auth.user_id,
           metadata={"approval_request": request.request_number, "action_type": action_type, "summary": summary})
    return ChangeResult("PENDING_APPROVAL", entity_id, approval_request=request)


def _locked_row(session: Session, d: ReferenceListDef, row_id: uuid.UUID, version: int | None) -> Any:
    row = session.scalar(select(d.model).where(d.model.id == row_id).with_for_update())
    if row is None:
        raise NotFound("Value not found.")
    if version is None:
        raise _bad("version", "REQUIRED", "Send the version you are editing.")
    if record_version(row) != version:
        raise VersionConflict(details={"current_version": record_version(row)})
    return row


def create(rt: Runtime, session: Session, caller: Authorized, list_key: str, data: dict) -> ChangeResult:
    d = get_list(list_key)
    values = clean(session, d, data, creating=True)
    check_unique(session, d, values)
    if rt.approvals.is_required(session, d.entity_type, None):
        from js_core.ids import uuid7
        return _submit(rt, session, caller, d, entity_id=uuid7(), version=NEW_RECORD_VERSION, action_type="CREATE",
                       proposed=values, summary=f"Add {values['code']} ({values['name']}) to {d.label}")
    row = apply_create(session, d, values, caller.auth.user_id)
    return ChangeResult("APPLIED", row.id, row)


def update(rt: Runtime, session: Session, caller: Authorized, list_key: str, row_id: uuid.UUID,
           version: int | None, data: dict) -> ChangeResult:
    d = get_list(list_key)
    row = _locked_row(session, d, row_id, version)
    values = {k: v for k, v in clean(session, d, data, creating=False, row=row).items() if getattr(row, k) != v}
    if not values:
        return ChangeResult("UNCHANGED", row.id, row)
    check_unique(session, d, values, row_id=row.id)
    if rt.approvals.is_required(session, d.entity_type, None):
        return _submit(rt, session, caller, d, entity_id=row.id, version=version, action_type="UPDATE",  # type: ignore[arg-type]
                       proposed=values, summary=f"Edit {row.code} in {d.label}: {', '.join(sorted(values))}")
    apply_update(session, d, row, values, caller.auth.user_id)
    return ChangeResult("APPLIED", row.id, row)


def set_status(rt: Runtime, session: Session, caller: Authorized, list_key: str, row_id: uuid.UUID,
               version: int | None, is_active: bool) -> ChangeResult:
    d = get_list(list_key)
    row = _locked_row(session, d, row_id, version)
    if row.is_active == is_active:
        return ChangeResult("UNCHANGED", row.id, row)
    if is_active and d.parent and getattr(row, d.parent.column):
        parent = session.get(get_list(d.parent.list_key).model, getattr(row, d.parent.column))
        if parent is not None and not parent.is_active:
            raise _bad(d.parent.field, "INACTIVE", "Activate the parent value first.")
    if rt.approvals.is_required(session, d.entity_type, None):
        return _submit(rt, session, caller, d, entity_id=row.id, version=version, action_type="STATUS_CHANGE",  # type: ignore[arg-type]
                       proposed={"is_active": is_active},
                       summary=f"{'Activate' if is_active else 'Deactivate'} {row.code} in {d.label}")
    apply_status(session, d, row, is_active, caller.auth.user_id)
    return ChangeResult("APPLIED", row.id, row)
