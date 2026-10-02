"""Approval queue (Maker-Checker) and audit search."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from identity_service.api.admin import Paging, paginate
from identity_service.api.schemas import ApprovalActionOut, ApprovalDetailOut, ApprovalOut, AuditOut, DecideIn, RejectIn
from identity_service.common import audit
from identity_service.models import ApprovalAction, ApprovalPolicy, ApprovalRequest, AuditLog
from identity_service.runtime import Runtime, caller, db_session, require, runtime
from js_approval.service import SelfApproval, StaleVersion
from js_audit import AuditResult
from js_auth.context import Authorized, Scope
from js_core.errors import NotFound
from js_core.responses import Page

router = APIRouter()
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]


def _scoped(stmt, who: Authorized):
    if who.scope is Scope.ALL:
        return stmt
    if who.scope is Scope.ORGANIZATION:
        return stmt.where(ApprovalRequest.organization_id == who.auth.organization_id)
    return stmt.where(ApprovalRequest.maker_user_id == who.auth.user_id)


def _can_decide(session: Session, who: Authorized, request: ApprovalRequest) -> bool:
    if request.status != "PENDING" or who.auth.user_id in {request.maker_user_id, request.subject_user_id}:
        return False
    policy = session.get(ApprovalPolicy, request.policy_id)
    scope = who.permissions.scope_for(policy.checker_permission_code) if policy else None
    if scope is None:
        return False
    return scope is Scope.ALL or (scope is Scope.ORGANIZATION and request.organization_id is not None
                                  and request.organization_id == who.auth.organization_id)


@router.get("/approvals", response_model=Page[ApprovalOut], tags=["approvals"])
def list_approvals(session: Db, paging: Paging, status_: str | None = Query(default="PENDING", alias="status"),
                   entity_type: str | None = None,
                   who: Authorized = Depends(require("MAKER_CHECKER.VIEW"))) -> Page[ApprovalOut]:
    stmt = _scoped(select(ApprovalRequest), who)
    if status_:
        stmt = stmt.where(ApprovalRequest.status == status_)
    if entity_type:
        stmt = stmt.where(ApprovalRequest.entity_type == entity_type)
    rows, total = paginate(session, stmt, paging, [ApprovalRequest.submitted_at.desc()])
    return Page(items=[ApprovalOut.model_validate(r[0]) for r in rows], page=paging.page, size=paging.size,
                total=total)


def _detail(session: Session, who: Authorized, request: ApprovalRequest) -> ApprovalDetailOut:
    actions = session.scalars(select(ApprovalAction).where(ApprovalAction.approval_request_id == request.id)
                              .order_by(ApprovalAction.acted_at)).all()
    out = ApprovalDetailOut.model_validate(request)
    out.actions = [ApprovalActionOut.model_validate(a) for a in actions]
    out.can_decide = _can_decide(session, who, request)
    out.can_withdraw = request.status == "PENDING" and request.maker_user_id == who.auth.user_id
    return out


@router.get("/approvals/{request_id}", response_model=ApprovalDetailOut, tags=["approvals"])
def get_approval(request_id: uuid.UUID, session: Db,
                 who: Authorized = Depends(require("MAKER_CHECKER.VIEW"))) -> ApprovalDetailOut:
    request = session.scalar(_scoped(select(ApprovalRequest).where(ApprovalRequest.id == request_id), who))
    if request is None:
        raise NotFound("Approval request not found.")
    return _detail(session, who, request)


def _decide(rt: Runtime, session: Session, who: Authorized, request_id: uuid.UUID, decision: str, **kw):
    engine = rt.approvals
    try:
        if decision == "APPROVED":
            request = engine.approve(session, request_id, checker=who, **kw)
        else:
            request = engine.reject(session, request_id, checker=who, **kw)
    except SelfApproval:
        session.rollback()
        audit(session, action="APPROVAL.SELF_APPROVAL_BLOCKED", entity_type="APPROVAL_REQUEST", entity_id=request_id,
              actor=who.auth.user_id, organization_id=who.auth.organization_id, result=AuditResult.DENIED,
              metadata={"decision": decision})
        session.commit()
        raise
    except StaleVersion:
        audit(session, action="APPROVAL.SUPERSEDED", entity_type="APPROVAL_REQUEST", entity_id=request_id,
              actor=who.auth.user_id, organization_id=who.auth.organization_id, result=AuditResult.FAILURE,
              metadata={"reviewed_version": kw.get("reviewed_version")})
        session.commit()
        raise
    audit(session, action=f"APPROVAL.{decision}", entity_type=request.entity_type, entity_id=request.entity_id,
          actor=who.auth.user_id, organization_id=request.organization_id,
          metadata={"approval_request": request.request_number, "maker_user_id": request.maker_user_id,
                    "action_type": request.action_type})
    session.commit()
    return _detail(session, who, request)


@router.post("/approvals/{request_id}/approve", response_model=ApprovalDetailOut, tags=["approvals"])
def approve(request_id: uuid.UUID, body: DecideIn, rt: Rt, session: Db,
            who: Authorized = Depends(caller)) -> ApprovalDetailOut:
    """The checker needs the policy's checker permission; makers and the affected user are refused."""
    return _decide(rt, session, who, request_id, "APPROVED", reviewed_version=body.reviewed_version,
                   comment=body.comment)


@router.post("/approvals/{request_id}/reject", response_model=ApprovalDetailOut, tags=["approvals"])
def reject(request_id: uuid.UUID, body: RejectIn, rt: Rt, session: Db,
           who: Authorized = Depends(caller)) -> ApprovalDetailOut:
    return _decide(rt, session, who, request_id, "REJECTED", reviewed_version=body.reviewed_version,
                   reason=body.reason)


@router.post("/approvals/{request_id}/withdraw", response_model=ApprovalDetailOut, tags=["approvals"])
def withdraw(request_id: uuid.UUID, rt: Rt, session: Db, who: Authorized = Depends(caller)) -> ApprovalDetailOut:
    request = rt.approvals.withdraw(session, request_id, actor=who.auth.user_id,
                                    acting_organization_id=who.auth.organization_id)
    audit(session, action="APPROVAL.WITHDRAWN", entity_type=request.entity_type, entity_id=request.entity_id,
          actor=who.auth.user_id, organization_id=request.organization_id,
          metadata={"approval_request": request.request_number})
    session.commit()
    return _detail(session, who, request)


# ------------------------------------------------------------------ audit
@router.get("/audit-logs", response_model=Page[AuditOut], tags=["audit"])
def audit_logs(session: Db, paging: Paging, actor_user_id: uuid.UUID | None = None,
               action: str | None = Query(default=None, max_length=60),
               entity_type: str | None = Query(default=None, max_length=50), entity_id: uuid.UUID | None = None,
               result: str | None = None, from_: datetime | None = Query(default=None, alias="from"),
               to: datetime | None = None,
               who: Authorized = Depends(require("AUDIT.VIEW"))) -> Page[AuditOut]:
    stmt = select(AuditLog)
    if who.scope is Scope.ORGANIZATION:
        stmt = stmt.where(AuditLog.organization_id == who.auth.organization_id)
    elif who.scope is Scope.OWN:
        stmt = stmt.where(AuditLog.actor_user_id == who.auth.user_id)
    for column, value in ((AuditLog.actor_user_id, actor_user_id), (AuditLog.entity_type, entity_type),
                          (AuditLog.entity_id, entity_id), (AuditLog.result, result)):
        if value is not None:
            stmt = stmt.where(column == value)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if from_:
        stmt = stmt.where(AuditLog.occurred_at >= from_)
    if to:
        stmt = stmt.where(AuditLog.occurred_at < to)
    rows, total = paginate(session, stmt, paging, [AuditLog.occurred_at.desc(), AuditLog.id.desc()])
    return Page(items=[AuditOut.model_validate(r[0]) for r in rows], page=paging.page, size=paging.size, total=total)
