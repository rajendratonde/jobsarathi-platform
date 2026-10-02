"""Maker-Checker inside Identity: four-eyes, own-access, version checks, decisions."""

from __future__ import annotations

import pytest
from identity_test_helpers import uniq
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _submit_role(api, world) -> dict:
    r = api.post("/v1/roles", world.maker, json={"name": uniq("Approver test "),
                                                 "permission_ids": [world.permissions["USER.VIEW"]]})
    assert r.status_code == 201 and r.json()["status"] == "PENDING_APPROVAL"
    return r.json()


def _detail(api, who, change) -> dict:
    return api.get(f"/v1/approvals/{change['approval_request']['id']}", who).json()


def test_maker_cannot_approve_own_request(api, world):
    change = _submit_role(api, world)
    detail = _detail(api, world.maker, change)
    assert detail["can_decide"] is False and detail["can_withdraw"] is True
    r = api.post(f"/v1/approvals/{detail['id']}/approve", world.maker,
                 json={"reviewed_version": detail["entity_version"]})
    assert r.status_code == 403 and r.json()["code"] == "SELF_APPROVAL"
    rejected = api.post(f"/v1/approvals/{detail['id']}/reject", world.maker,
                        json={"reviewed_version": detail["entity_version"], "reason": "I changed my mind"})
    assert rejected.status_code == 403 and rejected.json()["code"] == "SELF_APPROVAL"
    assert api.sql("SELECT status FROM approval_requests WHERE id = :i", i=detail["id"]) == [("PENDING",)]
    denied = api.sql("SELECT result FROM audit_logs WHERE action = 'APPROVAL.SELF_APPROVAL_BLOCKED' "
                     "AND entity_id = :i", i=detail["id"])
    assert denied and denied[0][0] == "DENIED"
    assert _detail(api, world.checker, change)["can_decide"] is True


def test_database_refuses_self_approval_even_if_code_is_bypassed(api, world, db):
    change = _submit_role(api, world)
    request_id = change["approval_request"]["id"]
    with pytest.raises(IntegrityError) as err, db.begin() as conn:
        conn.execute(text("UPDATE approval_requests SET status = 'APPROVED', decided_by = maker_user_id, "
                          "decided_at = now() WHERE id = :i"), {"i": request_id})
    assert "ck_approval_requests_four_eyes" in str(err.value)


def test_database_refuses_approval_by_the_affected_user(api, world, db):
    change = _submit_role(api, world)
    request_id = change["approval_request"]["id"]
    with pytest.raises(IntegrityError) as err, db.begin() as conn:
        conn.execute(text("UPDATE approval_requests SET subject_user_id = :s, status = 'APPROVED', decided_by = :s, "
                          "decided_at = now() WHERE id = :i"), {"s": world.checker.user_id, "i": request_id})
    assert "ck_approval_requests_not_own_access" in str(err.value)


def test_user_cannot_approve_a_change_to_their_own_access(api, world):
    """With the (data-driven) assignment policy on, the person receiving a role cannot approve it."""
    api.sql("UPDATE approval_policies SET is_enabled = true WHERE entity_type = 'USER_ROLE_ASSIGNMENT'")
    try:
        role_id = api.make_role(world, ["USER.VIEW"])
        r = api.post(f"/v1/users/{world.checker.user_id}/roles", world.maker,
                     json={"role_id": role_id, "scope_type": "ORGANIZATION",
                           "membership_id": api.sql("SELECT id FROM organization_memberships WHERE user_id = :u "
                                                    "AND organization_id = :o", u=world.checker.user_id,
                                                    o=world.platform_org)[0][0].__str__()})
        assert r.status_code == 201 and r.json()["status"] == "PENDING_APPROVAL", r.json()
        detail = _detail(api, world.checker, r.json())
        assert detail["subject_user_id"] == world.checker.user_id and detail["can_decide"] is False
        own = api.post(f"/v1/approvals/{detail['id']}/approve", world.checker,
                       json={"reviewed_version": detail["entity_version"]})
        assert own.status_code == 403 and own.json()["code"] == "SELF_APPROVAL"
        assignment = api.sql("SELECT status FROM user_role_assignments WHERE id = :i", i=detail["entity_id"])
        assert assignment == [("PENDING_APPROVAL",)]  # a pending assignment grants nothing
        withdrawn = api.post(f"/v1/approvals/{detail['id']}/withdraw", world.maker)
        assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "WITHDRAWN"
        assert api.sql("SELECT status FROM user_role_assignments WHERE id = :i",
                       i=detail["entity_id"]) == [("REVOKED",)]
    finally:
        api.sql("UPDATE approval_policies SET is_enabled = false WHERE entity_type = 'USER_ROLE_ASSIGNMENT'")
        api.refresh_admins(world)


def test_stale_approval_is_superseded(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    version = api.role(world.maker, role_id)["version"]
    rename = api.put(f"/v1/roles/{role_id}", world.maker, json={"name": uniq("First rename "), "version": version})
    permissions = api.put(f"/v1/roles/{role_id}/permissions", world.maker,
                          json={"permission_ids": [world.permissions["ROLE.VIEW"]], "version": version})
    assert rename.json()["status"] == permissions.json()["status"] == "PENDING_APPROVAL"
    api.approve(world.checker, permissions.json())  # the role's version moves on
    detail = _detail(api, world.checker, rename.json())
    r = api.post(f"/v1/approvals/{detail['id']}/approve", world.checker,
                 json={"reviewed_version": detail["entity_version"]})
    assert r.status_code == 409 and r.json()["code"] == "STALE_VERSION"
    after = _detail(api, world.checker, rename.json())
    assert after["status"] == "SUPERSEDED" and after["actions"][-1]["action"] == "SUPERSEDED"
    assert not api.role(world.maker, role_id)["name"].startswith("First rename")


def test_reviewed_version_must_match(api, world):
    change = _submit_role(api, world)
    detail = _detail(api, world.checker, change)
    r = api.post(f"/v1/approvals/{detail['id']}/approve", world.checker,
                 json={"reviewed_version": detail["entity_version"] + 1})
    assert r.status_code == 409 and r.json()["code"] == "STALE_VERSION"


def test_one_pending_request_per_record(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    version = api.role(world.maker, role_id)["version"]
    first = api.put(f"/v1/roles/{role_id}", world.maker, json={"name": uniq("A "), "version": version})
    assert first.json()["status"] == "PENDING_APPROVAL"
    second = api.put(f"/v1/roles/{role_id}", world.maker, json={"description": "other", "version": version})
    assert second.status_code == 409 and second.json()["code"] == "APPROVAL_PENDING"


def test_reject_needs_a_reason_and_keeps_the_role_a_draft(api, world):
    change = _submit_role(api, world)
    detail = _detail(api, world.checker, change)
    short = api.post(f"/v1/approvals/{detail['id']}/reject", world.checker,
                     json={"reviewed_version": detail["entity_version"], "reason": "no"})
    assert short.status_code == 422
    r = api.post(f"/v1/approvals/{detail['id']}/reject", world.checker,
                 json={"reviewed_version": detail["entity_version"], "reason": "Too broad for a recruiter"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert r.json()["decision_reason"] == "Too broad for a recruiter"
    assert api.role(world.maker, change["entity_id"])["status"] == "DRAFT"


def test_only_the_maker_can_withdraw(api, world):
    change = _submit_role(api, world)
    request_id = change["approval_request"]["id"]
    assert api.post(f"/v1/approvals/{request_id}/withdraw", world.checker).status_code == 403
    assert api.post(f"/v1/approvals/{request_id}/withdraw", world.maker).json()["status"] == "WITHDRAWN"


def test_organization_scoped_checker_cannot_decide_platform_requests(api, world):
    checker_role = api.make_role(world, ["ROLE.APPROVE", "MAKER_CHECKER.VIEW"])
    org_checker = api.create_user(world.maker, world.org1)
    r = api.assign(world.maker, org_checker, checker_role, "ORGANIZATION")
    assert r.status_code == 201
    api.relogin(org_checker, world.org1)
    change = _submit_role(api, world)
    r = api.post(f"/v1/approvals/{change['approval_request']['id']}/approve", org_checker,
                 json={"reviewed_version": 1})
    assert r.status_code == 403
    queue = api.get("/v1/approvals", org_checker).json()["items"]
    assert all(item["organization_id"] == world.org1 for item in queue)


def test_decisions_are_audited_with_maker_and_checker(api, world):
    change = _submit_role(api, world)
    api.approve(world.checker, change)
    rows = api.sql("SELECT action, actor_user_id::text, metadata->>'maker_user_id' FROM audit_logs "
                   "WHERE entity_id = :e ORDER BY occurred_at", e=change["entity_id"])
    actions = [r[0] for r in rows]
    assert "ROLE.DRAFTED" in actions and "APPROVAL.SUBMITTED" in actions and "APPROVAL.APPROVED" in actions
    approved = next(r for r in rows if r[0] == "APPROVAL.APPROVED")
    assert approved[1] == world.checker.user_id and approved[2] == world.maker.user_id
