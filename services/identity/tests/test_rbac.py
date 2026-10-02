"""Data-driven RBAC: roles, permissions, assignments, scopes, organization isolation."""

from __future__ import annotations

import pytest
from identity_test_helpers import uniq
from js_auth.keys import generate_private_key_pem


def _assign_ok(api, world, person, role_id, scope, membership_id=None):
    r = api.assign(world.maker, person, role_id, scope, membership_id)
    assert r.status_code == 201, r.json()
    assert r.json()["status"] == "APPLIED"
    return r.json()["entity_id"]


# ------------------------------------------------------------------ roles and permissions through Maker-Checker
def test_role_creation_requires_a_checker(api, world):
    r = api.post("/v1/roles", world.maker, json={"name": uniq("Recruiter "), "permission_ids":
                                                 [world.permissions["USER.VIEW"]]})
    assert r.status_code == 201
    change = r.json()
    assert change["status"] == "PENDING_APPROVAL" and change["approval_request"]["request_number"].startswith("APR-I-")
    role = api.role(world.maker, change["entity_id"])
    assert role["status"] == "PENDING_APPROVAL" and role["permission_codes"] == []
    user = api.create_user(world.maker, world.org1)
    pending = api.assign(world.maker, user, role["id"], "ORGANIZATION")
    assert pending.status_code == 409 and pending.json()["code"] == "ROLE_NOT_ACTIVE"
    api.approve(world.checker, change)
    role = api.role(world.maker, change["entity_id"])
    assert role["status"] == "ACTIVE" and role["permission_codes"] == ["USER.VIEW"]


def test_role_permission_change_applies_only_after_approval(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    role = api.role(world.maker, role_id)
    r = api.put(f"/v1/roles/{role_id}/permissions", world.maker,
                json={"permission_ids": [world.permissions["ROLE.VIEW"]], "version": role["version"]})
    assert r.json()["status"] == "PENDING_APPROVAL"
    assert api.role(world.maker, role_id)["permission_codes"] == ["USER.VIEW"]  # unchanged while pending
    api.approve(world.checker, r.json())
    assert api.role(world.maker, role_id)["permission_codes"] == ["ROLE.VIEW"]  # added one, removed one
    matrix = api.get("/v1/rbac/matrix", world.maker, params={"role_id": role_id}).json()
    granted = {c["permission_code"] for row in matrix["rows"] for c in row["cells"] if c and c["granted"]}
    assert granted == {"ROLE.VIEW"}
    assert {col["action_code"] for col in matrix["columns"]} >= {"VIEW", "EDIT", "APPROVE"}


def test_role_needs_a_version_and_rejects_a_stale_one(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    missing = api.put(f"/v1/roles/{role_id}", world.maker, json={"name": uniq("Renamed ")})
    assert missing.status_code == 422
    stale = api.put(f"/v1/roles/{role_id}", world.maker, json={"name": uniq("Renamed "), "version": 999})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    version = api.role(world.maker, role_id)["version"]
    via_header = api.put(f"/v1/roles/{role_id}", {**world.maker.headers, "If-Match": f'"{version}"'},
                         json={"name": uniq("Renamed ")})
    assert via_header.status_code == 200 and via_header.json()["status"] == "PENDING_APPROVAL"


def test_system_role_is_protected(api, world):
    admin_role = api.role(world.maker, world.roles["PLATFORM_ADMIN"])
    for call in (lambda: api.patch(f"/v1/roles/{admin_role['id']}/status", world.maker,
                                   json={"status": "DISABLED", "version": admin_role["version"]}),
                 lambda: api.delete(f"/v1/roles/{admin_role['id']}",
                                    {**world.maker.headers, "If-Match": str(admin_role["version"])}),
                 lambda: api.put(f"/v1/roles/{admin_role['id']}/permissions", world.maker,
                                 json={"permission_ids": [], "version": admin_role["version"]})):
        r = call()
        assert r.status_code == 422 and r.json()["code"] == "SYSTEM_ROLE", r.json()


def test_role_names_carry_no_power(api, world):
    """A role called 'Super Admin' grants exactly its permissions: none."""
    role_id = api.make_role(world, [], name=f"Super Admin {uniq()}")
    user = api.create_user(world.maker, world.platform_org)
    _assign_ok(api, world, user, role_id, "ALL")
    api.relogin(user, world.platform_org)
    assert api.permissions(user) == {}
    assert api.get("/v1/users", user).status_code == 403


# ------------------------------------------------------------------ assignments and scopes
def test_role_assignment_applies_only_in_its_organization(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    org2_membership = api.add_member(world.maker, world.org2, user)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")  # org1 membership
    api.relogin(user, world.org1)
    assert api.permissions(user) == {"USER.VIEW": "ORGANIZATION"}
    api.relogin(user, world.org2)
    assert api.permissions(user) == {}
    assert org2_membership


def test_own_organization_and_all_scopes(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    in_org1 = api.create_user(world.maker, world.org1, "Org1 Member")
    in_org2 = api.create_user(world.maker, world.org2, "Org2 Member")

    own = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, own, role_id, "OWN")
    api.relogin(own, world.org1)
    assert [u["id"] for u in api.get("/v1/users", own).json()["items"]] == [own.user_id]
    assert api.get(f"/v1/users/{in_org1.user_id}", own).status_code == 404

    org = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, org, role_id, "ORGANIZATION")
    api.relogin(org, world.org1)
    ids = {u["id"] for u in api.get("/v1/users", org, params={"size": 100}).json()["items"]}
    assert in_org1.user_id in ids and in_org2.user_id not in ids
    assert api.get(f"/v1/users/{in_org2.user_id}", org).status_code == 404

    wide = api.create_user(world.maker, world.platform_org)
    _assign_ok(api, world, wide, role_id, "ALL")
    api.relogin(wide, world.platform_org)
    assert api.get(f"/v1/users/{in_org2.user_id}", wide).status_code == 200
    everyone = api.get("/v1/users", wide).json()["total"]
    assert everyone == api.sql("SELECT count(*) FROM users WHERE deleted_at IS NULL")[0][0]


def test_all_scope_only_on_platform_membership_and_inactive_scopes_refused(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    r = api.assign(world.maker, user, role_id, "ALL")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "ALL_NEEDS_PLATFORM"
    for scope in ("CITY", "REGION"):
        r = api.assign(world.maker, user, role_id, scope)
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "SCOPE_INACTIVE"


def test_duplicate_assignment_and_self_assignment_refused(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    again = api.assign(world.maker, user, role_id, "ORGANIZATION")
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_ASSIGNED"
    me = api.post(f"/v1/users/{world.maker.user_id}/roles", world.maker,
                  json={"role_id": role_id, "scope_type": "OWN", "membership_id": None})
    assert me.status_code == 403 and me.json()["code"] == "SELF_ASSIGNMENT"


def test_nobody_can_grant_more_than_they_hold(api, world):
    delegate = api.make_role(world, ["ROLE.ASSIGN", "USER.VIEW", "ROLE.VIEW"])
    bigger = api.make_role(world, ["USER.VIEW", "USER.CREATE"])
    same = api.make_role(world, ["USER.VIEW"])
    org_admin = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, org_admin, delegate, "ORGANIZATION")
    api.relogin(org_admin, world.org1)
    target = api.create_user(world.maker, world.org1)
    r = api.assign(org_admin, target, bigger, "ORGANIZATION")
    assert r.status_code == 403 and r.json()["code"] == "CANNOT_GRANT_MORE"
    assert r.json()["details"]["lacking"] == ["USER.CREATE"]
    assert api.assign(org_admin, target, same, "ORGANIZATION").status_code == 201


# ------------------------------------------------------------------ disabled and deleted links
def test_disabled_role_stops_granting_at_once(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    api.relogin(user, world.org1)
    assert api.get("/v1/users", user).status_code == 200
    role = api.role(world.maker, role_id)
    change = api.patch(f"/v1/roles/{role_id}/status", world.maker,
                       json={"status": "DISABLED", "version": role["version"]}).json()
    assert change["status"] == "PENDING_APPROVAL"
    assert api.get("/v1/users", user).status_code == 200  # still active until approved
    api.approve(world.checker, change)
    stale = api.get("/v1/users", user)
    assert stale.status_code == 401 and stale.json()["code"] == "TOKEN_STALE"
    api.relogin(user, world.org1)
    assert api.permissions(user) == {}


def _new_permission(api, world) -> tuple[str, str]:
    module = next(m for m in api.get("/v1/modules", world.maker).json() if m["module_code"] == "ACCESS_CONTROL")
    code = uniq("TEST").upper().replace("-", "")
    code = "".join(ch for ch in code if ch.isalpha() or ch == "_")[:20]
    res = api.post("/v1/resources", world.maker, json={"module_id": module["id"], "resource_code": code,
                                                       "name": "Test resource"})
    assert res.status_code == 201, res.json()
    view = next(a for a in api.get("/v1/actions", world.maker).json() if a["action_code"] == "VIEW")
    change = api.post("/v1/permissions", world.maker, json={"resource_id": res.json()["id"], "action_id": view["id"]})
    assert change.status_code == 201 and change.json()["status"] == "PENDING_APPROVAL"
    api.approve(world.checker, change.json())
    permission_id = change.json()["entity_id"]
    world.permissions[f"{code}.VIEW"] = permission_id
    # A new permission is held by nobody, so nobody could assign it ("cannot grant more").
    # The system role may gain permissions (never lose them): add it there through Maker-Checker.
    admin_role = api.role(world.maker, world.roles["PLATFORM_ADMIN"])
    grow = api.put(f"/v1/roles/{admin_role['id']}/permissions", world.maker,
                   json={"permission_ids": admin_role["permission_ids"] + [permission_id],
                         "version": admin_role["version"]})
    assert grow.status_code == 200, grow.json()
    api.approve(world.checker, grow.json())
    api.refresh_admins(world)
    return f"{code}.VIEW", permission_id


def test_disabled_permission_stops_granting(api, world):
    code, permission_id = _new_permission(api, world)
    role_id = api.make_role(world, [code])
    user = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    api.relogin(user, world.org1)
    assert code in api.permissions(user)
    change = api.patch(f"/v1/permissions/{permission_id}/status", world.maker, json={"is_active": False}).json()
    api.approve(world.checker, change)
    api.refresh_admins(world)
    assert api.get("/v1/me/permissions", user).json()["code"] == "TOKEN_STALE"
    api.relogin(user, world.org1)
    assert code not in api.permissions(user)


def test_identity_permissions_cannot_be_disabled(api, world):
    r = api.patch(f"/v1/permissions/{world.permissions['ROLE.APPROVE']}/status", world.maker,
                  json={"is_active": False})
    assert r.status_code == 422 and r.json()["code"] == "PERMISSION_PROTECTED"


def test_deleted_or_revoked_links_never_grant(api, world):
    code, permission_id = _new_permission(api, world)
    role_id = api.make_role(world, [code, "USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    assignment = _assign_ok(api, world, user, role_id, "ORGANIZATION")
    api.relogin(user, world.org1)
    assert set(api.permissions(user)) == {code, "USER.VIEW"}

    # soft-deleted permission
    api.approve(world.checker, api.delete(f"/v1/permissions/{permission_id}", world.maker).json())
    api.refresh_admins(world)
    api.relogin(user, world.org1)
    assert set(api.permissions(user)) == {"USER.VIEW"}
    listed = {p["permission_code"] for p in api.get("/v1/permissions", world.maker).json()}
    assert code not in listed

    # revoked assignment
    assert api.delete(f"/v1/users/{user.user_id}/roles/{assignment}", world.maker).status_code == 204
    api.relogin(user, world.org1)
    assert api.permissions(user) == {}
    status = api.sql("SELECT status, revoked_at IS NOT NULL FROM user_role_assignments WHERE id = :i", i=assignment)
    assert status == [("REVOKED", True)]

    # soft-deleted role (no holders left), then restore as DISABLED
    role = api.role(world.maker, role_id)
    deleted = api.delete(f"/v1/roles/{role_id}", {**world.maker.headers, "If-Match": str(role["version"])}).json()
    api.approve(world.checker, deleted)
    names = {r["id"] for r in api.get("/v1/roles", world.maker, params={"size": 100}).json()["items"]}
    assert role_id not in names
    with_deleted = api.get("/v1/roles", world.maker, params={"size": 100, "include_deleted": True}).json()["items"]
    assert any(r["id"] == role_id and r["deleted_at"] for r in with_deleted)
    assert api.assign(world.maker, user, role_id, "ORGANIZATION").status_code == 404
    role = api.role(world.maker, role_id)
    restored = api.post(f"/v1/roles/{role_id}/restore", world.maker, json={"version": role["version"]}).json()
    api.approve(world.checker, restored)
    assert api.role(world.maker, role_id)["status"] == "DISABLED"


def test_role_in_use_cannot_be_deleted(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    version = api.role(world.maker, role_id)["version"]
    r = api.delete(f"/v1/roles/{role_id}", {**world.maker.headers, "If-Match": str(version)})
    assert r.status_code == 422 and r.json()["code"] == "ROLE_IN_USE"


def test_deleted_membership_revokes_its_assignments(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    members = api.get(f"/v1/organizations/{world.org1}/members", world.maker, params={"size": 100}).json()["items"]
    mine = next(m for m in members if m["user"]["id"] == user.user_id)
    r = api.delete(f"/v1/organizations/{world.org1}/members/{mine['membership_id']}",
                   {**world.maker.headers, "If-Match": str(mine["version"])})
    assert r.status_code == 204
    assert api.sql("SELECT status FROM user_role_assignments WHERE user_id = :u", u=user.user_id) == [("REVOKED",)]
    assert api.sql("SELECT deleted_at IS NOT NULL FROM organization_memberships WHERE id = :m",
                   m=mine["membership_id"]) == [(True,)]
    after = api.get(f"/v1/organizations/{world.org1}/members", world.maker, params={"size": 100}).json()["items"]
    assert user.user_id not in {m["user"]["id"] for m in after}


def test_suspended_organization_grants_nothing(api, world, employer_key):
    org = api.create_org(world.maker.user_id, employer_key)
    api.refresh_admins(world)
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, org)
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    api.relogin(user, org)
    assert api.permissions(user) == {"USER.VIEW": "ORGANIZATION"}
    version = api.get(f"/v1/organizations/{org}", world.maker).json()["version"]
    assert api.patch(f"/v1/organizations/{org}/status", world.maker,
                     json={"status": "SUSPENDED", "version": version}).status_code == 200
    assert api.get("/v1/me/permissions", user).json()["code"] == "TOKEN_STALE"
    api.refresh_admins(world)  # the owner (maker) is a member too


# ------------------------------------------------------------------ authz_version
def test_authz_version_rises_and_stale_tokens_must_refresh(api, world):
    role_id = api.make_role(world, ["USER.VIEW"])
    user = api.create_user(world.maker, world.org1)
    before = api.sql("SELECT authz_version FROM users WHERE id = :u", u=user.user_id)[0][0]
    _assign_ok(api, world, user, role_id, "ORGANIZATION")
    after = api.sql("SELECT authz_version FROM users WHERE id = :u", u=user.user_id)[0][0]
    assert after == before + 1
    r = api.get("/v1/me/permissions", user)
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_STALE"
    api.c.cookies.clear()
    api.relogin(user, world.org1)
    body = api.get("/v1/me/permissions", user).json()
    assert body["authz_version"] == after and body["permissions"] == {"USER.VIEW": "ORGANIZATION"}


# ------------------------------------------------------------------ organization isolation and denial
@pytest.fixture()
def org1_admin(api, world):
    role_id = api.make_role(world, ["USER.VIEW", "USER.CREATE", "USER.EDIT", "USER.DISABLE", "ROLE.VIEW",
                                    "ROLE.ASSIGN", "ORGANIZATION.VIEW", "AUDIT.VIEW"])
    admin = api.create_user(world.maker, world.org1, "Org1 Admin")
    _assign_ok(api, world, admin, role_id, "ORGANIZATION")
    api.relogin(admin, world.org1)
    return admin


def test_cross_organization_access_is_denied(api, world, org1_admin):
    outsider = api.create_user(world.maker, world.org2, "Org2 Only")
    assert api.get(f"/v1/users/{outsider.user_id}", org1_admin).status_code == 404
    assert api.get(f"/v1/organizations/{world.org2}", org1_admin).status_code == 404
    assert api.get(f"/v1/organizations/{world.org2}/members", org1_admin).status_code == 404
    add = api.post(f"/v1/organizations/{world.org2}/members", org1_admin, json={"email": org1_admin.email})
    assert add.status_code == 403
    create = api.post("/v1/users", org1_admin, json={"display_name": "Xavier", "email": f"{uniq()}@example.test",
                                                     "organization_id": world.org2})
    assert create.status_code == 403
    role_id = api.make_role(world, ["USER.VIEW"])
    assign = api.assign(org1_admin, outsider, role_id, "ORGANIZATION")
    assert assign.status_code == 404  # the outsider is not even visible
    orgs = api.get("/v1/organizations", org1_admin).json()["items"]
    assert [o["id"] for o in orgs] == [world.org1]
    reset = api.post(f"/v1/users/{outsider.user_id}/password/reset", org1_admin)
    assert reset.status_code == 404
    platform_only = api.patch(f"/v1/users/{outsider.user_id}/status", org1_admin, json={"status": "DISABLED"})
    assert platform_only.status_code == 403  # status changes need ALL scope


def test_org_admin_sees_only_own_organization_audit(api, world, org1_admin):
    rows = api.get("/v1/audit-logs", org1_admin, params={"size": 100}).json()["items"]
    assert rows and all(r["organization_id"] == world.org1 for r in rows)


def test_last_access_admin_cannot_be_removed(api, world, employer_key):
    org = api.create_org(world.maker.user_id, employer_key)
    api.refresh_admins(world)
    role_id = api.make_role(world, ["ROLE.ASSIGN", "USER.VIEW"])
    first = api.create_user(world.maker, org)
    _assign_ok(api, world, first, role_id, "ORGANIZATION")
    members = api.get(f"/v1/organizations/{org}/members", world.maker, params={"size": 100}).json()["items"]
    mine = next(m for m in members if m["user"]["id"] == first.user_id)
    r = api.patch(f"/v1/organizations/{org}/members/{mine['membership_id']}", world.maker,
                  json={"status": "SUSPENDED", "version": mine["version"]})
    assert r.status_code == 422 and r.json()["code"] == "LAST_ACCESS_ADMIN"
    second = api.create_user(world.maker, org)
    _assign_ok(api, world, second, role_id, "ORGANIZATION")
    r = api.patch(f"/v1/organizations/{org}/members/{mine['membership_id']}", world.maker,
                  json={"status": "SUSPENDED", "version": mine["version"]})
    assert r.status_code == 200


def test_unauthenticated_and_unauthorized(api, world):
    assert api.get("/v1/users").status_code == 401
    assert api.get("/v1/users", {"Authorization": "Bearer not-a-token"}).json()["code"] == "UNAUTHENTICATED"
    # a token signed by someone else's key
    import jwt
    forged = jwt.encode({"sub": world.maker.user_id, "typ": "access", "aud": "jobsarathi-api",
                         "iss": "jobsarathi-identity", "iat": 0, "exp": 9999999999, "av": 1},
                        generate_private_key_pem(), algorithm="ES256", headers={"kid": "unknown"})
    assert api.get("/v1/users", {"Authorization": f"Bearer {forged}"}).status_code == 401
    nobody = api.create_user(world.maker, world.org1)
    r = api.get("/v1/users", nobody)
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_DENIED"
    assert api.post("/v1/roles", nobody, json={"name": "x" * 5}).status_code == 403
    assert api.get("/v1/approvals", nobody).status_code == 403
    assert api.get("/v1/audit-logs", nobody).status_code == 403
