"""Reference list administration (REFERENCE.EDIT, ALL scope). No delete: deactivate."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from js_auth.context import Authorized
from js_core.errors import FieldError, ValidationFailed
from js_core.responses import Page, PageParams, page_params
from reference_service import service
from reference_service.lists import LISTS, get_list
from reference_service.models import ApprovalPolicy
from reference_service.runtime import Runtime, db_session, require, runtime

router = APIRouter(prefix="/admin/reference", tags=["reference (admin)"])
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]
Paging = Annotated[PageParams, Depends(page_params)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
Editor = Depends(require("REFERENCE.EDIT", platform=True))


class ValueIn(BaseModel):
    """Common fields plus the list's extra fields (state_code, level_rank, ...), checked per list."""

    model_config = ConfigDict(extra="allow")
    code: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=150)
    name_hi: str | None = Field(default=None, max_length=150)
    sort_order: int | None = None
    version: int | None = None


class StatusIn(BaseModel):
    is_active: bool
    version: int | None = None


class ChangeOut(BaseModel):
    status: str
    entity_id: uuid.UUID
    approval_request: dict[str, Any] | None = None
    value: dict[str, Any] | None = None


def _version(body: int | None, header: str | None) -> int | None:
    if body is not None:
        return body
    if not header:
        return None
    try:
        return int(header.strip().removeprefix("W/").strip('"'))
    except ValueError:
        raise ValidationFailed(errors=[FieldError(field="If-Match", code="INVALID",
                                                  message="If-Match must be the record version.")]) from None


def _change_out(session: Session, list_key: str, result: service.ChangeResult) -> ChangeOut:
    d = get_list(list_key)
    value = None
    if result.row is not None:
        parents = service._parent_rows(session, d, {getattr(result.row, d.parent.column)} - {None}) if d.parent else {}
        value = service.to_admin(d, result.row, parents, service.pending_requests(session, d, [result.row.id]))
    request = result.approval_request
    return ChangeOut(status=result.status, entity_id=result.entity_id, value=value,
                     approval_request=None if request is None else {
                         "id": str(request.id), "request_number": request.request_number, "status": request.status})


def _payload(body: ValueIn) -> dict:
    data = body.model_dump(exclude_unset=True)
    data.pop("version", None)
    return data


@router.get("")
def lists(session: Db, _: Authorized = Editor) -> list[dict]:
    """Every list with its fields, counts and whether changes need approval: drives the admin UI."""
    policies = {p.entity_type: p.is_enabled for p in session.scalars(
        select(ApprovalPolicy).where(ApprovalPolicy.organization_id.is_(None)))}
    out = []
    for d in LISTS.values():
        active, total = session.execute(
            select(func.count().filter(d.model.is_active.is_(True)), func.count()).select_from(d.model)).one()
        out.append({"list": d.key, "label": d.label, "requires_approval": policies.get(d.entity_type, False),
                    "active": active, "total": total, "searchable": d.searchable,
                    "fields": [{"name": e.name, "label": e.label, "kind": e.kind, "required": e.required,
                                "immutable": e.immutable,
                                "parent_list": d.parent.list_key if e.kind == "parent" and d.parent else None}
                               for e in d.extras]})
    return out


@router.get("/{list_key}", response_model=Page[dict])
def list_values(list_key: str, session: Db, paging: Paging, q: str | None = Query(default=None, max_length=100),
                state: str = Query(default="all", pattern="^(all|active|inactive)$"),
                _: Authorized = Editor) -> Page[dict]:
    d = get_list(list_key)
    m = d.model
    stmt = select(m)
    if state != "all":
        stmt = stmt.where(m.is_active.is_(state == "active"))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(m.name).like(like), func.lower(m.code).like(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = [m.list_code, m.sort_order, m.name] if "list_code" in d.columns else [m.sort_order, m.name]
    rows = session.scalars(stmt.order_by(*order).offset(paging.offset).limit(paging.size)).all()
    parents = service._parent_rows(session, d, {getattr(r, d.parent.column) for r in rows} - {None}) if d.parent else {}
    pending = service.pending_requests(session, d, [r.id for r in rows])
    return Page(items=[service.to_admin(d, r, parents, pending) for r in rows], page=paging.page, size=paging.size,
                total=total)


@router.post("/{list_key}", response_model=ChangeOut, status_code=status.HTTP_201_CREATED)
def create_value(list_key: str, body: ValueIn, rt: Rt, session: Db, caller: Authorized = Editor) -> ChangeOut:
    result = service.create(rt, session, caller, list_key, _payload(body))
    session.commit()
    return _change_out(session, list_key, result)


@router.put("/{list_key}/{value_id}", response_model=ChangeOut)
def update_value(list_key: str, value_id: uuid.UUID, body: ValueIn, rt: Rt, session: Db, if_match: IfMatch = None,
                 caller: Authorized = Editor) -> ChangeOut:
    result = service.update(rt, session, caller, list_key, value_id, _version(body.version, if_match), _payload(body))
    session.commit()
    return _change_out(session, list_key, result)


@router.patch("/{list_key}/{value_id}/status", response_model=ChangeOut)
def set_status(list_key: str, value_id: uuid.UUID, body: StatusIn, rt: Rt, session: Db, if_match: IfMatch = None,
               caller: Authorized = Editor) -> ChangeOut:
    result = service.set_status(rt, session, caller, list_key, value_id, _version(body.version, if_match),
                                body.is_active)
    session.commit()
    return _change_out(session, list_key, result)
