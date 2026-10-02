"""Small client for the Identity API used by the tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from js_auth.service_tokens import sign_service_token

PASSWORD = "Changed-2026-pw"


def uniq(prefix: str = "u") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@dataclass
class Person:
    user_id: str
    email: str
    headers: dict[str, str] = field(default_factory=dict)
    membership_id: str | None = None


@dataclass
class World:
    maker: Person            # platform admin A (bootstrap)
    checker: Person          # platform admin B
    platform_org: str
    org1: str
    org2: str
    roles: dict[str, str]    # role_code -> id
    permissions: dict[str, str]  # permission_code -> id


class Api:
    def __init__(self, client: TestClient, db: Engine) -> None:
        self.c = client
        self.db = db

    # ------------------------------------------------------------ raw helpers
    def get(self, path: str, who: Person | dict | None = None, **kw):
        return self.c.get(path, headers=self._h(who), **kw)

    def post(self, path: str, who: Person | dict | None = None, **kw):
        return self.c.post(path, headers=self._h(who), **kw)

    def put(self, path: str, who: Person | dict | None = None, **kw):
        return self.c.put(path, headers=self._h(who), **kw)

    def patch(self, path: str, who: Person | dict | None = None, **kw):
        return self.c.patch(path, headers=self._h(who), **kw)

    def delete(self, path: str, who: Person | dict | None = None, **kw):
        return self.c.request("DELETE", path, headers=self._h(who), **kw)

    @staticmethod
    def _h(who) -> dict:
        if who is None:
            return {}
        return who.headers if isinstance(who, Person) else who

    def sql(self, statement: str, **params) -> list[Any]:
        with self.db.begin() as conn:
            result = conn.execute(text(statement), params)
            return list(result) if result.returns_rows else []

    # ------------------------------------------------------------ auth
    def login(self, email: str, password: str) -> dict:
        r = self.post("/v1/auth/password/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.json()
        return r.json()

    def sign_in(self, email: str, temporary: str, *, organization: str | None = None) -> dict[str, str]:
        """First sign-in with a temporary password: change it, then optionally choose an organization."""
        token = self.login(email, temporary)["access_token"]
        r = self.post("/v1/auth/password/change", {"Authorization": f"Bearer {token}"},
                      json={"current_password": temporary, "new_password": PASSWORD})
        assert r.status_code == 200, r.json()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        if organization:
            headers = self.switch(headers, organization)
        return headers

    def relogin(self, person: Person, organization: str | None = None) -> Person:
        headers = {"Authorization": f"Bearer {self.login(person.email, PASSWORD)['access_token']}"}
        if organization:
            headers = self.switch(headers, organization)
        person.headers = headers
        return person

    def switch(self, headers: dict, organization: str) -> dict[str, str]:
        r = self.post("/v1/me/organization/switch", headers, json={"organization_id": organization})
        assert r.status_code == 200, r.json()
        return {"Authorization": f"Bearer {r.json()['token']['access_token']}"}

    def otp_sign_in(self, mobile: str) -> dict:
        r = self.post("/v1/auth/otp/request", json={"mobile": mobile})
        assert r.status_code == 201, r.json()
        code = self.get("/v1/dev/otp", params={"mobile": mobile}).json()["code"]
        r2 = self.post("/v1/auth/otp/verify", json={"challenge_id": r.json()["challenge_id"], "mobile": mobile,
                                                    "code": code})
        assert r2.status_code == 200, r2.json()
        return r2.json()

    def permissions(self, who: Person | dict) -> dict[str, str]:
        r = self.get("/v1/me/permissions", who)
        assert r.status_code == 200, r.json()
        return r.json()["permissions"]

    # ------------------------------------------------------------ directory
    def create_user(self, admin: Person, organization: str, name: str = "Test User") -> Person:
        email = f"{uniq()}@example.test"
        r = self.post("/v1/users", admin, json={"display_name": name, "email": email, "organization_id": organization})
        assert r.status_code == 201, r.json()
        body = r.json()
        person = Person(user_id=body["user"]["id"], email=email, membership_id=body["membership_id"])
        person.headers = self.sign_in(email, body["temporary_password"], organization=organization)
        return person

    def create_org(self, owner_user_id: str, employer_key, name: str | None = None) -> str:
        token = sign_service_token(employer_key, issuer="employer", audience="identity")
        r = self.post("/v1/internal/organizations", {"X-Service-Token": token},
                      json={"name": name or uniq("Org "), "owner_user_id": owner_user_id})
        assert r.status_code == 201, r.json()
        return r.json()["organization_id"]

    def assign(self, admin: Person, user: Person, role_id: str, scope: str, membership_id: str | None = None):
        return self.post(f"/v1/users/{user.user_id}/roles", admin,
                         json={"role_id": role_id, "scope_type": scope,
                               "membership_id": membership_id if membership_id is not None else user.membership_id})

    def add_member(self, admin: Person, organization: str, person: Person) -> str:
        r = self.post(f"/v1/organizations/{organization}/members", admin, json={"email": person.email})
        assert r.status_code == 201, r.json()
        return r.json()["membership_id"]

    # ------------------------------------------------------------ RBAC and approvals
    def approve(self, checker: Person, change: dict) -> dict:
        request_id = change["approval_request"]["id"]
        detail = self.get(f"/v1/approvals/{request_id}", checker).json()
        assert "entity_version" in detail, detail
        r = self.post(f"/v1/approvals/{request_id}/approve", checker,
                      json={"reviewed_version": detail["entity_version"]})
        assert r.status_code == 200, r.json()
        return r.json()

    def make_role(self, world: World, permission_codes: list[str], *, name: str | None = None) -> str:
        """Create a role through Maker-Checker (maker submits, checker approves)."""
        ids = [world.permissions[c] for c in permission_codes]
        r = self.post("/v1/roles", world.maker, json={"name": name or uniq("Role "), "permission_ids": ids})
        assert r.status_code == 201, r.json()
        change = r.json()
        assert change["status"] == "PENDING_APPROVAL", change
        self.approve(world.checker, change)
        return change["entity_id"]

    def refresh_admins(self, world: World) -> None:
        """After a change that touched what the platform admins hold, they sign in again."""
        self.relogin(world.maker, world.platform_org)
        self.relogin(world.checker, world.platform_org)

    def role(self, admin: Person, role_id: str) -> dict:
        r = self.get(f"/v1/roles/{role_id}", admin)
        assert r.status_code == 200, r.json()
        return r.json()

    def refresh_permissions_map(self, admin: Person) -> dict[str, str]:
        return {p["permission_code"]: p["id"] for p in self.get("/v1/permissions", admin).json()}

    def build_world(self, employer_key, bootstrap_password: str) -> World:
        from identity_service.bootstrap import main

        email = f"{uniq('admin')}@jobsarathi.test"
        assert main(["--email", email, "--name", "Platform Admin A", "--role-code", "PLATFORM_ADMIN"]) == 0
        maker_id = self.sql("SELECT user_id FROM auth_identities WHERE identifier = :e", e=email)[0][0]
        maker = Person(user_id=str(maker_id), email=email)
        maker.headers = self.sign_in(email, bootstrap_password)
        platform_org = str(self.sql("SELECT id FROM organizations WHERE is_platform")[0][0])
        roles = {r["role_code"]: r["id"] for r in self.get("/v1/roles", maker, params={"size": 100}).json()["items"]}
        checker = self.create_user(maker, platform_org, "Platform Admin B")
        r = self.assign(maker, checker, roles["PLATFORM_ADMIN"], "ALL")
        assert r.status_code == 201 and r.json()["status"] == "APPLIED", r.json()
        # Creating organizations owned by the maker raises the maker's authz_version: sign in afterwards.
        org1 = self.create_org(maker.user_id, employer_key)
        org2 = self.create_org(maker.user_id, employer_key)
        self.relogin(checker, platform_org)
        self.relogin(maker, platform_org)
        return World(maker=maker, checker=checker, platform_org=platform_org, org1=org1, org2=org2, roles=roles,
                     permissions=self.refresh_permissions_map(maker))
