"""Maker-Checker engine. One instance per service; one handler per entity type."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from js_auth.context import Authorized, EffectivePermissions, Scope
from js_core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed


class SelfApproval(PermissionDenied):
    code, message = "SELF_APPROVAL", "You cannot approve or reject a change you submitted, or one that changes your own access."


class StaleVersion(Conflict):
    code, message = "STALE_VERSION", "The record changed after it was submitted. The request is now superseded."


class ApprovalPending(Conflict):
    code, message = "APPROVAL_PENDING", "This record already has a change waiting for approval."


class ApprovalHandler(Protocol):
    """Implemented by the service for each approvable entity type."""

    def load_for_update(self, session: Session, entity_id: uuid.UUID) -> Any: ...
    def apply_approval(self, session: Session, entity: Any, request: Any, checker: uuid.UUID) -> None: ...
    def apply_rejection(self, session: Session, entity: Any, request: Any, checker: uuid.UUID) -> None: ...
    def apply_withdrawal(self, session: Session, entity: Any, request: Any, actor: uuid.UUID) -> None: ...


# A proposal to create a record that does not exist yet is submitted with version 0; it
# stays valid only while the record still does not exist.
NEW_RECORD_VERSION = 0


def version_of(handler: Any, entity: Any) -> int:
    """The entity's optimistic-lock version; a handler may supply one for tables without a version column."""
    custom = getattr(handler, "version_of", None)
    return int(custom(entity)) if custom else int(entity.version)


@dataclass(frozen=True)
class ApprovalModels:
    policy: type
    request: type
    action: type
    number_sequence: str  # PostgreSQL sequence for request_number
    number_prefix: str    # e.g. "APR-I-"


def _now() -> datetime:
    return datetime.now(UTC)


class ApprovalEngine:
    def __init__(self, models: ApprovalModels) -> None:
        self.m = models
        self.handlers: dict[str, ApprovalHandler] = {}

    def register(self, entity_type: str, handler: ApprovalHandler) -> None:
        self.handlers[entity_type] = handler

    # ------------------------------------------------------------- policy
    def policy(self, session: Session, entity_type: str, organization_id: uuid.UUID | None) -> Any | None:
        policy_model = self.m.policy
        rows = session.scalars(select(policy_model).where(policy_model.entity_type == entity_type)).all()
        specific = [p for p in rows if p.organization_id == organization_id and organization_id is not None]
        default = [p for p in rows if p.organization_id is None]
        chosen = (specific or default or [None])[0]
        return chosen

    def is_required(self, session: Session, entity_type: str, organization_id: uuid.UUID | None) -> bool:
        policy = self.policy(session, entity_type, organization_id)
        return bool(policy and policy.is_enabled)

    # ------------------------------------------------------------- submit
    def submit(self, session: Session, *, entity_type: str, entity_id: uuid.UUID, entity_version: int,
               action_type: str, maker: uuid.UUID, maker_permissions: EffectivePermissions,
               organization_id: uuid.UUID | None, subject_user_id: uuid.UUID | None = None,
               proposed_changes: dict | None = None, change_summary: str | None = None,
               comment: str | None = None, acting_organization_id: uuid.UUID | None = None,
               maker_permission: str | None = None) -> Any:
        """``maker_permission`` overrides the policy's maker permission for one action (e.g. ROLE.CREATE)."""
        policy = self.policy(session, entity_type, organization_id)
        if policy is None or not policy.is_enabled:
            raise Conflict(f"No approval policy is enabled for {entity_type}.", code="APPROVAL_NOT_REQUIRED")
        if not maker_permissions.has(maker_permission or policy.maker_permission_code):
            raise PermissionDenied()
        req = self.m.request
        if session.scalar(select(req.id).where(req.entity_type == entity_type, req.entity_id == entity_id,
                                             req.status == "PENDING")):
            raise ApprovalPending()
        number = session.execute(text(f"SELECT nextval('{self.m.number_sequence}')")).scalar_one()
        request = req(request_number=f"{self.m.number_prefix}{number:06d}", policy_id=policy.id,
                    entity_type=entity_type, entity_id=entity_id, entity_version=entity_version,
                    action_type=action_type, organization_id=organization_id, subject_user_id=subject_user_id,
                    proposed_changes=proposed_changes, change_summary=(change_summary or "")[:500] or None,
                    maker_user_id=maker, maker_comment=comment, status="PENDING")
        session.add(request)
        session.flush()
        self._action(session, request, "SUBMITTED", maker, acting_organization_id, entity_version, comment)
        return request

    # ------------------------------------------------------------- decide
    def _load_pending(self, session: Session, request_id: uuid.UUID) -> Any:
        req = self.m.request
        request = session.scalar(select(req).where(req.id == request_id).with_for_update())
        if request is None:
            raise NotFound("Approval request not found.")
        if request.status != "PENDING":
            raise Conflict(f"This request is already {request.status.lower()}.", code="APPROVAL_CLOSED")
        return request

    def _check_checker(self, session: Session, request: Any, checker: Authorized) -> None:
        user = checker.auth.user_id
        if user == request.maker_user_id or (request.subject_user_id and user == request.subject_user_id):
            raise SelfApproval()
        policy = session.get(self.m.policy, request.policy_id)
        scope = checker.permissions.scope_for(policy.checker_permission_code)
        if scope is None:
            raise PermissionDenied()
        # Platform-level requests (no organization) need ALL scope; organization requests need
        # ALL or ORGANIZATION scope in that organization.
        in_scope = scope is Scope.ALL or (scope is Scope.ORGANIZATION and request.organization_id is not None
                                          and checker.auth.organization_id == request.organization_id)
        if not in_scope:
            raise PermissionDenied("You cannot decide requests for this organization.")

    def _check_version(self, session: Session, request: Any, entity: Any, reviewed_version: int,
                       checker: Authorized) -> None:
        handler = self.handlers[request.entity_type]
        if entity is None and request.action_type == "CREATE" and request.entity_version == NEW_RECORD_VERSION:
            current = NEW_RECORD_VERSION  # creation proposal: the record is made on approval
        elif entity is None:
            current = None
        else:
            current = version_of(handler, entity)
        if current != request.entity_version or reviewed_version != request.entity_version:
            request.status = "SUPERSEDED"
            self._action(session, request, "SUPERSEDED", checker.auth.user_id, checker.auth.organization_id,
                         reviewed_version, "Record version changed after submission")
            session.commit()
            raise StaleVersion()

    def approve(self, session: Session, request_id: uuid.UUID, *, checker: Authorized, reviewed_version: int,
                comment: str | None = None) -> Any:
        request = self._load_pending(session, request_id)
        self._check_checker(session, request, checker)
        handler = self.handlers[request.entity_type]
        entity = handler.load_for_update(session, request.entity_id)
        self._check_version(session, request, entity, reviewed_version, checker)
        handler.apply_approval(session, entity, request, checker.auth.user_id)
        request.status, request.decided_by, request.decided_at = "APPROVED", checker.auth.user_id, _now()
        self._action(session, request, "APPROVED", checker.auth.user_id, checker.auth.organization_id,
                     reviewed_version, comment)
        return request

    def reject(self, session: Session, request_id: uuid.UUID, *, checker: Authorized, reviewed_version: int,
               reason: str) -> Any:
        if not reason or len(reason.strip()) < 5:
            raise ValidationFailed(errors=[FieldError(field="reason", code="TOO_SHORT",
                                                      message="Give a reason of at least 5 characters.")])
        request = self._load_pending(session, request_id)
        self._check_checker(session, request, checker)
        handler = self.handlers[request.entity_type]
        entity = handler.load_for_update(session, request.entity_id)
        self._check_version(session, request, entity, reviewed_version, checker)
        handler.apply_rejection(session, entity, request, checker.auth.user_id)
        request.status, request.decided_by, request.decided_at = "REJECTED", checker.auth.user_id, _now()
        request.decision_reason = reason.strip()
        self._action(session, request, "REJECTED", checker.auth.user_id, checker.auth.organization_id,
                     reviewed_version, reason.strip())
        return request

    def withdraw(self, session: Session, request_id: uuid.UUID, *, actor: uuid.UUID,
                 acting_organization_id: uuid.UUID | None) -> Any:
        request = self._load_pending(session, request_id)
        if request.maker_user_id != actor:
            raise PermissionDenied("Only the person who submitted a request can withdraw it.")
        handler = self.handlers[request.entity_type]
        entity = handler.load_for_update(session, request.entity_id)
        handler.apply_withdrawal(session, entity, request, actor)
        request.status = "WITHDRAWN"
        self._action(session, request, "WITHDRAWN", actor, acting_organization_id, None, None)
        return request

    def _action(self, session: Session, request: Any, action: str, actor: uuid.UUID,
                organization_id: uuid.UUID | None, version: int | None, comment: str | None) -> None:
        session.add(self.m.action(approval_request_id=request.id, action=action, actor_user_id=actor,
                                  acting_organization_id=organization_id, reviewed_version=version, comment=comment))

    def pending_for(self, session: Session, entity_type: str, entity_id: uuid.UUID) -> Any | None:
        req = self.m.request
        return session.scalar(select(req).where(req.entity_type == entity_type, req.entity_id == entity_id,
                                              req.status == "PENDING"))


EntityLoader = Callable[[Session, uuid.UUID], Any]
