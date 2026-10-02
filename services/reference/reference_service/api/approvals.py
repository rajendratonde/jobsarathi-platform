"""Reference Data approval queue and audit search. Same shapes as Identity's, so one UI serves both."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from js_approval.service import SelfApproval, StaleVersion
from js_audit import AuditResult, record_audit
from js_auth.context import Authorized, Scope
from js_core.errors import NotFound
from js_core.responses import Page, PageParams, page_params
from reference_service.models import ApprovalAction, ApprovalPolicy, ApprovalRequest, AuditLog
from reference_service.runtime import Runtime, caller, db_session, require, runtime

router = APIRouter()
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]
Paging = Annotated[PageParams, Depends(page_params)]


class DecideIn(BaseModel):
    reviewed_version: int
    comment: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    reviewed_version: int
    reason: str = Field(min_length=1, max_length=1000)


def _out(request: ApprovalRequest) -> dict[str, Any]:
    return {k: getattr(request, k) for k in (
        "id", "request_number", "entity_type", "entity_id", "entity_version", "action_type", "organization_id",
        "subject_user_id", "proposed_changes", "change_summary", "maker_user_id", "maker_comment", "submitted_at",
        "status", "decided_by", "decided_at", "decision_reason")}


def _can_decide(session: Session, who: Authorized, request: ApprovalRequest) -> bool:
    if request.status != "PENDING" or who.auth.user_id in {request.maker_user_id, request.subject_user_id}:
        return False
    policy = session.get(ApprovalPolicy, request.policy_id)
    return bool(policy) and who.permissions.scope_for(policy.checker_permission_code) is Scope.ALL


def _detail(session: Session, who: Authorized, request: ApprovalRequest) -> dict[str, Any]:
    actions = session.scalars(select(ApprovalAction).where(ApprovalAction.approval_request_id == request.id)
                              .order_by(ApprovalAction.acted_at)).all()
    return {**_out(request),
            "actions": [{"action": a.action, "actor_user_id": a.actor_user_id, "reviewed_version": a.reviewed_version,
                         "comment": a.comment, "acted_at": a.acted_at} for a in actions],
            "can_decide": _can_decide(session, who, request),
            "can_withdraw": request.status == "PENDING" and request.maker_user_id == who.auth.user_id}


@router.get("/approvals", response_model=Page[dict], tags=["approvals"])
def list_approvals(session: Db, paging: Paging, status_: str | None = Query(default="PENDING", alias="status"),
                   entity_type: str | None = None,
                   who: Authorized = Depends(require("MAKER_CHECKER.VIEW"))) -> Page[dict]:
    stmt = select(ApprovalRequest)
    if who.scope is not Scope.ALL:  # reference requests are platform-wide: others see only their own
        stmt = stmt.where(ApprovalRequest.maker_user_id == who.auth.user_id)
    if status_:
        stmt = stmt.where(ApprovalRequest.status == status_)
    if entity_type:
        stmt = stmt.where(ApprovalRequest.entity_type == entity_type)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(ApprovalRequest.submitted_at.desc())
                           .offset(paging.offset).limit(paging.size)).all()
    return Page(items=[_out(r) for r in rows], page=paging.page, size=paging.size, total=total)


def _load(session: Session, who: Authorized, request_id: uuid.UUID) -> ApprovalRequest:
    request = session.get(ApprovalRequest, request_id)
    if request is None or (who.scope is not Scope.ALL and request.maker_user_id != who.auth.user_id):
        raise NotFound("Approval request not found.")
    return request


@router.get("/approvals/{request_id}", tags=["approvals"])
def get_approval(request_id: uuid.UUID, session: Db, who: Authorized = Depends(require("MAKER_CHECKER.VIEW"))) -> dict:
    return _detail(session, who, _load(session, who, request_id))


def _audit(session: Session, who: Authorized, action: str, request_id: uuid.UUID, result=AuditResult.SUCCESS,
           metadata: dict | None = None) -> None:
    record_audit(session, AuditLog, action=action, entity_type="APPROVAL_REQUEST", entity_id=request_id,
                 actor_user_id=who.auth.user_id, organization_id=who.auth.organization_id, result=result,
                 metadata=metadata)


def _decide(rt: Runtime, session: Session, who: Authorized, request_id: uuid.UUID, decision: str, **kw) -> dict:
    try:
        if decision == "APPROVED":
            request = rt.approvals.approve(session, request_id, checker=who, **kw)
        else:
            request = rt.approvals.reject(session, request_id, checker=who, **kw)
    except SelfApproval:
        session.rollback()
        _audit(session, who, "APPROVAL.SELF_APPROVAL_BLOCKED", request_id, AuditResult.DENIED, {"decision": decision})
        session.commit()
        raise
    except StaleVersion:
        _audit(session, who, "APPROVAL.SUPERSEDED", request_id, AuditResult.FAILURE,
               {"reviewed_version": kw.get("reviewed_version")})
        session.commit()
        raise
    except Exception:
        session.rollback()
        raise
    _audit(session, who, f"APPROVAL.{decision}", request_id,
           metadata={"approval_request": request.request_number, "maker_user_id": str(request.maker_user_id),
                     "entity_type": request.entity_type, "action_type": request.action_type})
    session.commit()
    return _detail(session, who, request)


@router.post("/approvals/{request_id}/approve", tags=["approvals"])
def approve(request_id: uuid.UUID, body: DecideIn, rt: Rt, session: Db, who: Authorized = Depends(caller)) -> dict:
    return _decide(rt, session, who, request_id, "APPROVED", reviewed_version=body.reviewed_version,
                   comment=body.comment)


@router.post("/approvals/{request_id}/reject", tags=["approvals"])
def reject(request_id: uuid.UUID, body: RejectIn, rt: Rt, session: Db, who: Authorized = Depends(caller)) -> dict:
    return _decide(rt, session, who, request_id, "REJECTED", reviewed_version=body.reviewed_version,
                   reason=body.reason)


@router.post("/approvals/{request_id}/withdraw", tags=["approvals"])
def withdraw(request_id: uuid.UUID, rt: Rt, session: Db, who: Authorized = Depends(caller)) -> dict:
    request = rt.approvals.withdraw(session, request_id, actor=who.auth.user_id,
                                    acting_organization_id=who.auth.organization_id)
    _audit(session, who, "APPROVAL.WITHDRAWN", request_id, metadata={"approval_request": request.request_number})
    session.commit()
    return _detail(session, who, request)


@router.get("/audit-logs", response_model=Page[dict], tags=["audit"])
def audit_logs(session: Db, paging: Paging, entity_type: str | None = Query(default=None, max_length=50),
               entity_id: uuid.UUID | None = None, action: str | None = Query(default=None, max_length=60),
               from_: datetime | None = Query(default=None, alias="from"), to: datetime | None = None,
               _: Authorized = Depends(require("AUDIT.VIEW", platform=True))) -> Page[dict]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if from_:
        stmt = stmt.where(AuditLog.occurred_at >= from_)
    if to:
        stmt = stmt.where(AuditLog.occurred_at < to)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
                           .offset(paging.offset).limit(paging.size)).all()
    return Page(items=[{"id": r.id, "occurred_at": r.occurred_at, "actor_user_id": r.actor_user_id,
                        "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
                        "result": r.result, "before_data": r.before_data, "after_data": r.after_data,
                        "metadata": r.metadata_, "correlation_id": r.correlation_id} for r in rows],
                page=paging.page, size=paging.size, total=total)
