"""Reference Data behaviour: public read, administration, Maker-Checker, RBAC, audit."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

A = "/v1/admin/reference"


def uniq(prefix: str = "T") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"


def find(app_client, who, list_key: str, code: str) -> dict:
    items = app_client.get(f"{A}/{list_key}", headers=who.headers, params={"q": code, "size": 100}).json()["items"]
    return next(i for i in items if i["code"] == code)


# ------------------------------------------------------------------ public read
def test_public_read_needs_no_sign_in_and_hides_ids(app_client):
    r = app_client.get("/v1/reference/job_types")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {"FULL_TIME", "PART_TIME"} <= {i["code"] for i in items}
    assert all("id" not in i and "is_active" not in i for i in items)
    assert [i["sort_order"] for i in items] == sorted(i["sort_order"] for i in items)
    index = app_client.get("/v1/reference").json()["lists"]
    assert {li["list"] for li in index} >= {"states", "cities", "skills", "experience_bands"}
    assert "lookup_values" not in {li["list"] for li in index}


def test_etag_and_not_modified(app_client, editor):
    first = app_client.get("/v1/reference/work_modes")
    etag = first.headers["etag"]
    assert first.headers["cache-control"].startswith("public, max-age=")
    again = app_client.get("/v1/reference/work_modes", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    app_client.post(f"{A}/work_modes", headers=editor.headers, json={"code": uniq("WM"), "name": "Night shift"})
    changed = app_client.get("/v1/reference/work_modes", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_filters_parent_and_search(app_client):
    pune = app_client.get("/v1/reference/cities", params={"state": "MH"}).json()["items"]
    assert pune and all(c["state_code"] == "MH" for c in pune) and "PUNE" in {c["code"] for c in pune}
    roles = app_client.get("/v1/reference/job_roles", params={"category": "IT_SOFTWARE"}).json()["items"]
    assert roles and all(r["job_category_code"] == "IT_SOFTWARE" for r in roles)
    skills = app_client.get("/v1/reference/skills", params={"q": "pyth"}).json()["items"]
    assert [s["code"] for s in skills] == ["PYTHON"]
    bands = app_client.get("/v1/reference/experience_bands").json()["items"]
    assert any(b["max_months"] is None for b in bands)
    levels = app_client.get("/v1/reference/education_levels").json()["items"]
    assert all(isinstance(level["level_rank"], int) for level in levels)


def test_unknown_list_is_404(app_client):
    for path in ("/v1/reference/planets", "/v1/reference/lookup_values"):
        body = app_client.get(path).json()
        assert body["status"] == 404 and body["code"] == "UNKNOWN_LIST"


# ------------------------------------------------------------------ administration
def test_create_update_and_codes_never_change(app_client, editor, db):
    code = uniq("SK")
    r = app_client.post(f"{A}/skills", headers=editor.headers, json={"code": code.lower(), "name": "  Rust  ",
                                                                      "name_hi": "रस्ट", "sort_order": 5})
    assert r.status_code == 201 and r.json()["status"] == "APPLIED", r.json()
    value = r.json()["value"]
    assert value["code"] == code and value["name"] == "Rust" and value["is_active"] is True
    edit = app_client.put(f"{A}/skills/{value['id']}", headers=editor.headers,
                          json={"name": "Rust language", "version": value["version"]})
    assert edit.status_code == 200 and edit.json()["value"]["name"] == "Rust language"
    stale = app_client.put(f"{A}/skills/{value['id']}", headers=editor.headers,
                           json={"name": "Again", "version": value["version"]})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    fresh = edit.json()["value"]["version"]
    rename_code = app_client.put(f"{A}/skills/{value['id']}", headers=editor.headers,
                                 json={"code": "OTHER", "version": fresh})
    assert rename_code.status_code == 422 and rename_code.json()["errors"][0]["code"] == "IMMUTABLE"
    via_header = app_client.put(f"{A}/skills/{value['id']}", headers={**editor.headers, "If-Match": f'"{fresh}"'},
                                json={"sort_order": 7})
    assert via_header.status_code == 200
    with db.connect() as conn:
        assert conn.execute(text("SELECT created_by, updated_by FROM skills WHERE code = :c"), {"c": code}).one() == (
            editor.user_id, editor.user_id)


def test_codes_are_unique_for_ever(app_client, editor):
    code = uniq("JT")
    first = app_client.post(f"{A}/job_types", headers=editor.headers, json={"code": code, "name": "Seasonal"})
    value = first.json()["value"]
    app_client.patch(f"{A}/job_types/{value['id']}/status", headers=editor.headers,
                     json={"is_active": False, "version": value["version"]})
    again = app_client.post(f"{A}/job_types", headers=editor.headers, json={"code": code, "name": "Seasonal 2"})
    assert again.status_code == 409 and again.json()["code"] == "CODE_TAKEN"  # even when the old value is inactive


@pytest.mark.parametrize(("list_key", "body", "field", "code"), [
    ("skills", {"code": "bad code!", "name": "X"}, "code", "INVALID_CODE"),
    ("skills", {"code": "OK_CODE_1", "name": ""}, "name", "LENGTH"),
    ("skills", {"code": "OK_CODE_2", "name": "X", "sort_order": -1}, "sort_order", "RANGE"),
    ("cities", {"code": "NOWHERE", "name": "Nowhere"}, "state_code", "REQUIRED"),
    ("cities", {"code": "NOWHERE", "name": "Nowhere", "state_code": "ZZ"}, "state_code", "UNKNOWN_CODE"),
    ("education_levels", {"code": "CERT", "name": "Certificate"}, "level_rank", "REQUIRED"),
    ("experience_bands", {"code": "ODD", "name": "Odd", "min_months": 24, "max_months": 12}, "max_months", "RANGE"),
    ("lookup_values", {"code": "X", "name": "X"}, "list_code", "REQUIRED"),
])
def test_validation(app_client, editor, list_key, body, field, code):
    r = app_client.post(f"{A}/{list_key}", headers=editor.headers, json=body)
    assert r.status_code == 422, r.json()
    assert r.json()["errors"][0]["field"] == field and r.json()["errors"][0]["code"] == code


def test_city_names_unique_per_state(app_client, editor):
    r = app_client.post(f"{A}/cities", headers=editor.headers, json={"code": uniq("C"), "name": "pune", "state_code": "MH"})
    assert r.status_code == 409 and r.json()["code"] == "NAME_TAKEN"
    other_state = app_client.post(f"{A}/cities", headers=editor.headers,
                                  json={"code": uniq("C"), "name": "Pune", "state_code": "GJ"})
    assert other_state.status_code == 201


def test_database_backs_the_rules(db):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="ck_experience_bands_month_range"), db.begin() as conn:
        conn.execute(text("INSERT INTO experience_bands (id, code, name, min_months, max_months) "
                          "VALUES (gen_random_uuid(), 'DB_CHECK', 'x', 10, 5)"))
    with pytest.raises(IntegrityError, match="uq_states_code"), db.begin() as conn:
        conn.execute(text("INSERT INTO states (id, code, name) VALUES (gen_random_uuid(), 'MH', 'Duplicate')"))
    with pytest.raises(IntegrityError, match="fk_cities_state_id_states"), db.begin() as conn:
        conn.execute(text("DELETE FROM states WHERE code = 'MH'"))  # RESTRICT: referenced values cannot vanish


def test_lookup_values_are_unique_per_list(app_client, editor):
    list_code = uniq("NOTICE")
    for code in ("IMMEDIATE", "THIRTY_DAYS"):
        r = app_client.post(f"{A}/lookup_values", headers=editor.headers,
                            json={"list_code": list_code.lower(), "code": code, "name": code.title()})
        assert r.status_code == 201, r.json()
    dup = app_client.post(f"{A}/lookup_values", headers=editor.headers,
                          json={"list_code": list_code, "code": "IMMEDIATE", "name": "Again"})
    assert dup.status_code == 409
    other = app_client.post(f"{A}/lookup_values", headers=editor.headers,
                            json={"list_code": uniq("OTHER"), "code": "IMMEDIATE", "name": "Fine"})
    assert other.status_code == 201
    public = app_client.get(f"/v1/reference/lookups/{list_code}").json()["items"]
    assert [i["code"] for i in public] == ["IMMEDIATE", "THIRTY_DAYS"]


# ------------------------------------------------------------------ deactivation (no delete)
def test_deactivated_values_disappear_from_public_read_but_stay_in_admin(app_client, editor):
    code = uniq("IND")
    value = app_client.post(f"{A}/industries", headers=editor.headers, json={"code": code, "name": "Space"}).json()["value"]
    assert code in {i["code"] for i in app_client.get("/v1/reference/industries").json()["items"]}
    r = app_client.patch(f"{A}/industries/{value['id']}/status", headers=editor.headers,
                         json={"is_active": False, "version": value["version"]})
    assert r.status_code == 200 and r.json()["value"]["is_active"] is False
    assert code not in {i["code"] for i in app_client.get("/v1/reference/industries").json()["items"]}
    inactive = app_client.get(f"{A}/industries", headers=editor.headers, params={"state": "inactive", "size": 100})
    assert code in {i["code"] for i in inactive.json()["items"]}
    assert app_client.delete(f"{A}/industries/{value['id']}", headers=editor.headers).status_code == 405


def test_inactive_parent_hides_children_and_blocks_new_ones(app_client, editor):
    state_code = uniq("S")
    state = app_client.post(f"{A}/states", headers=editor.headers, json={"code": state_code, "name": "Test State"}).json()
    city_code = uniq("C")
    city = app_client.post(f"{A}/cities", headers=editor.headers,
                           json={"code": city_code, "name": "Test City", "state_code": state_code})
    assert city.status_code == 201
    app_client.patch(f"{A}/states/{state['entity_id']}/status", headers=editor.headers,
                     json={"is_active": False, "version": state["value"]["version"]})
    cities = {c["code"] for c in app_client.get("/v1/reference/cities").json()["items"]}
    assert city_code not in cities
    blocked = app_client.post(f"{A}/cities", headers=editor.headers,
                              json={"code": uniq("C"), "name": "Another", "state_code": state_code})
    assert blocked.status_code == 422 and blocked.json()["errors"][0]["code"] == "INACTIVE"


# ------------------------------------------------------------------ RBAC
def test_authorization_is_by_permission_and_scope(app_client, tokens, identity):
    assert app_client.get(f"{A}/skills").status_code == 401
    nobody = tokens.person({})
    r = app_client.get(f"{A}/skills", headers=nobody.headers)
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_DENIED"
    org_scoped = tokens.person({"REFERENCE.EDIT": "ORGANIZATION"})
    assert app_client.post(f"{A}/skills", headers=org_scoped.headers, json={"code": uniq(), "name": "X"}).status_code == 403
    approver_only = tokens.person({"REFERENCE.APPROVE": "ALL"})
    assert app_client.post(f"{A}/skills", headers=approver_only.headers,
                           json={"code": uniq(), "name": "X"}).status_code == 403
    forged = {"Authorization": "Bearer not-a-token"}
    assert app_client.get(f"{A}/skills", headers=forged).json()["code"] == "UNAUTHENTICATED"


def test_access_change_makes_tokens_stale(app_client, tokens, identity):
    editor = tokens.person({"REFERENCE.EDIT": "ALL"})
    assert app_client.get(f"{A}/skills", headers=editor.headers).status_code == 200
    identity.versions[editor.user_id] = 2  # Identity raised authz_version (role changed)
    r = app_client.get(f"{A}/skills", headers=editor.headers)
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_STALE"


def test_identity_unreachable_fails_closed(app_client, tokens, identity):
    editor = tokens.person({"REFERENCE.EDIT": "ALL"})
    identity.down = True
    try:
        r = app_client.get(f"{A}/skills", headers=editor.headers)
        assert r.status_code == 503 and r.json()["code"] == "AUTHZ_UNAVAILABLE"
        assert app_client.get("/v1/reference/skills").status_code == 200  # public read keeps working
    finally:
        identity.down = False


def test_admin_list_metadata_drives_the_ui(app_client, editor):
    lists = {li["list"]: li for li in app_client.get(A, headers=editor.headers).json()}
    assert lists["cities"]["fields"][0] == {"name": "state_code", "label": "State", "kind": "parent", "required": True,
                                            "immutable": False, "parent_list": "states"}
    assert lists["skills"]["requires_approval"] is False and lists["states"]["active"] >= 36


def test_pagination(app_client, editor):
    page1 = app_client.get(f"{A}/states", headers=editor.headers, params={"size": 10}).json()
    page4 = app_client.get(f"{A}/states", headers=editor.headers, params={"size": 10, "page": 4}).json()
    assert len(page1["items"]) == 10 and page1["total"] >= 36
    assert {i["code"] for i in page1["items"]}.isdisjoint({i["code"] for i in page4["items"]})
    assert app_client.get(f"{A}/states", headers=editor.headers, params={"size": 101}).status_code == 422


# ------------------------------------------------------------------ Maker-Checker
def _approve(app_client, who, request_id, version):
    return app_client.post(f"/v1/approvals/{request_id}/approve", headers=who.headers, json={"reviewed_version": version})


def test_create_is_a_proposal_until_a_checker_approves(app_client, editor, checker, approval_on):
    code = uniq("SK")
    r = app_client.post(f"{A}/skills", headers=editor.headers, json={"code": code, "name": "Kotlin"})
    assert r.status_code == 201 and r.json()["status"] == "PENDING_APPROVAL"
    request = r.json()["approval_request"]
    assert request["request_number"].startswith("APR-R-")
    assert code not in {s["code"] for s in app_client.get("/v1/reference/skills").json()["items"]}
    dup = app_client.post(f"{A}/skills", headers=editor.headers, json={"code": code, "name": "Kotlin again"})
    assert dup.status_code == 409 and dup.json()["code"] == "CODE_PENDING"

    own = _approve(app_client, editor, request["id"], 0)
    assert own.status_code == 403 and own.json()["code"] == "SELF_APPROVAL"
    detail = app_client.get(f"/v1/approvals/{request['id']}", headers=checker.headers).json()
    assert detail["can_decide"] is True and detail["entity_version"] == 0
    assert _approve(app_client, checker, request["id"], 0).json()["status"] == "APPROVED"
    assert code in {s["code"] for s in app_client.get("/v1/reference/skills").json()["items"]}
    assert find(app_client, editor, "skills", code)["id"] == r.json()["entity_id"]


def test_edit_and_deactivate_apply_only_after_approval(app_client, editor, checker, approval_on, db):
    with db.connect() as conn:
        row = conn.execute(text("SELECT id FROM skills WHERE code = 'SQL'")).scalar_one()
    value = find(app_client, editor, "skills", "SQL")
    r = app_client.put(f"{A}/skills/{row}", headers=editor.headers, json={"name": "SQL (databases)",
                                                                          "version": value["version"]})
    assert r.json()["status"] == "PENDING_APPROVAL"
    assert find(app_client, editor, "skills", "SQL")["name"] == "SQL"
    assert find(app_client, editor, "skills", "SQL")["pending_request"]["request_number"].startswith("APR-R-")
    second = app_client.patch(f"{A}/skills/{row}/status", headers=editor.headers,
                              json={"is_active": False, "version": value["version"]})
    assert second.status_code == 409 and second.json()["code"] == "APPROVAL_PENDING"  # one open request per value
    _approve(app_client, checker, r.json()["approval_request"]["id"], value["version"])
    assert find(app_client, editor, "skills", "SQL")["name"] == "SQL (databases)"


def test_stale_approval_is_superseded(app_client, editor, checker, db):
    code = uniq("PT")
    created = app_client.post(f"{A}/pay_types", headers=editor.headers, json={"code": code, "name": "Weekly"}).json()
    version = created["value"]["version"]
    with db.begin() as conn:
        conn.execute(text("UPDATE approval_policies SET is_enabled = true WHERE entity_type = 'PAY_TYPES'"))
    try:
        proposal = app_client.put(f"{A}/pay_types/{created['entity_id']}", headers=editor.headers,
                                  json={"name": "Per week", "version": version}).json()
        with db.begin() as conn:  # the value changes after submission (e.g. a direct database fix)
            conn.execute(text("UPDATE pay_types SET sort_order = sort_order + 1, updated_at = now() WHERE code = :c"),
                         {"c": code})
        r = _approve(app_client, checker, proposal["approval_request"]["id"], version)
        assert r.status_code == 409 and r.json()["code"] == "STALE_VERSION"
        detail = app_client.get(f"/v1/approvals/{proposal['approval_request']['id']}", headers=checker.headers).json()
        assert detail["status"] == "SUPERSEDED" and detail["actions"][-1]["action"] == "SUPERSEDED"
        assert find(app_client, editor, "pay_types", code)["name"] == "Weekly"
    finally:
        with db.begin() as conn:
            conn.execute(text("UPDATE approval_policies SET is_enabled = false WHERE entity_type = 'PAY_TYPES'"))


def test_reject_and_withdraw(app_client, editor, checker, approval_on):
    first = app_client.post(f"{A}/industries", headers=editor.headers, json={"code": uniq("I"), "name": "A"}).json()
    rid = first["approval_request"]["id"]
    short = app_client.post(f"/v1/approvals/{rid}/reject", headers=checker.headers,
                            json={"reviewed_version": 0, "reason": "no"})
    assert short.status_code == 422
    done = app_client.post(f"/v1/approvals/{rid}/reject", headers=checker.headers,
                           json={"reviewed_version": 0, "reason": "Duplicate of IT"})
    assert done.json()["status"] == "REJECTED" and done.json()["decision_reason"] == "Duplicate of IT"
    second = app_client.post(f"{A}/industries", headers=editor.headers, json={"code": uniq("I"), "name": "B"}).json()
    assert app_client.post(f"/v1/approvals/{second['approval_request']['id']}/withdraw",
                           headers=checker.headers).status_code == 403
    assert app_client.post(f"/v1/approvals/{second['approval_request']['id']}/withdraw",
                           headers=editor.headers).json()["status"] == "WITHDRAWN"


def test_checker_needs_approve_permission_with_all_scope(app_client, editor, tokens, approval_on):
    proposal = app_client.post(f"{A}/skills", headers=editor.headers, json={"code": uniq(), "name": "Go"}).json()
    org_checker = tokens.person({"REFERENCE.APPROVE": "ORGANIZATION", "MAKER_CHECKER.VIEW": "ALL"})
    r = _approve(app_client, org_checker, proposal["approval_request"]["id"], 0)
    assert r.status_code == 403
    editor_only = tokens.person({"REFERENCE.EDIT": "ALL", "MAKER_CHECKER.VIEW": "ALL"})
    assert _approve(app_client, editor_only, proposal["approval_request"]["id"], 0).status_code == 403


def test_database_refuses_self_approval(db, app_client, editor, approval_on):
    from sqlalchemy.exc import IntegrityError

    proposal = app_client.post(f"{A}/skills", headers=editor.headers, json={"code": uniq(), "name": "Elixir"}).json()
    with pytest.raises(IntegrityError, match="ck_approval_requests_four_eyes"), db.begin() as conn:
        conn.execute(text("UPDATE approval_requests SET status = 'APPROVED', decided_by = maker_user_id, "
                          "decided_at = now() WHERE id = :i"), {"i": proposal["approval_request"]["id"]})


# ------------------------------------------------------------------ audit and outbox
def test_changes_are_audited_and_published(app_client, editor, checker, db, approval_on):
    proposal = app_client.post(f"{A}/job_types", headers=editor.headers, json={"code": uniq("J"), "name": "Gig"}).json()
    _approve(app_client, checker, proposal["approval_request"]["id"], 0)
    with db.connect() as conn:
        rows = conn.execute(text("SELECT action, actor_user_id, metadata->>'maker_user_id' FROM audit_logs "
                                 "WHERE entity_id = :e ORDER BY occurred_at"), {"e": proposal["entity_id"]}).all()
        events = conn.execute(text("SELECT event_type, payload->>'change' FROM outbox_events WHERE aggregate_id = :e"),
                              {"e": proposal["entity_id"]}).all()
    assert [r[0] for r in rows] == ["APPROVAL.SUBMITTED", "REFERENCE.CREATED"]
    assert rows[1][1] == checker.user_id and rows[1][2] == str(editor.user_id)
    assert events == [("ReferenceValueChanged", "CREATED")]
    audit = app_client.get("/v1/audit-logs", headers=editor.headers, params={"entity_id": proposal["entity_id"]}).json()
    assert audit["total"] == 2


def test_approvals_list_scoping(app_client, editor, tokens, approval_on):
    mine = app_client.post(f"{A}/skills", headers=editor.headers, json={"code": uniq(), "name": "Zig"}).json()
    viewer = tokens.person({"MAKER_CHECKER.VIEW": "ORGANIZATION"})
    queue = app_client.get("/v1/approvals", headers=viewer.headers).json()
    assert queue["total"] == 0  # reference requests are platform-wide; others see only their own
    assert app_client.get(f"/v1/approvals/{mine['approval_request']['id']}", headers=viewer.headers).status_code == 404
