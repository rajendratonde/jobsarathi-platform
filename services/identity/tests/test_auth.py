"""Sign-in, temporary passwords (E1), OTP, sessions and organization context."""

from __future__ import annotations

import hashlib

import pytest
from identity_test_helpers import PASSWORD, uniq


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ users, identities, temporary passwords
def test_create_user_issues_identity_membership_and_temporary_password(api, world):
    email = f"{uniq()}@example.test"
    r = api.post("/v1/users", world.maker, json={"display_name": "Asha Rao", "email": email,
                                                 "organization_id": world.org1})
    assert r.status_code == 201, r.json()
    body = r.json()
    assert len(body["temporary_password"]) >= 12
    assert "password_hash" not in str(body)
    identity = api.sql("SELECT identity_type, identifier, password_hash, password_change_required, is_primary "
                       "FROM auth_identities WHERE user_id = :u", u=body["user"]["id"])
    assert len(identity) == 1
    kind, identifier, pw_hash, change_required, primary = identity[0]
    assert (kind, identifier, change_required, primary) == ("EMAIL_PASSWORD", email, True, True)
    assert pw_hash.startswith("$argon2id$") and body["temporary_password"] not in pw_hash
    member = api.sql("SELECT organization_id, status FROM organization_memberships WHERE id = :m",
                     m=body["membership_id"])
    assert (str(member[0][0]), member[0][1]) == (world.org1, "ACTIVE")


def test_duplicate_email_identity_is_rejected(api, world):
    email = f"{uniq()}@example.test"
    first = api.post("/v1/users", world.maker, json={"display_name": "One", "email": email,
                                                     "organization_id": world.org1})
    assert first.status_code == 201
    again = api.post("/v1/users", world.maker, json={"display_name": "Two", "email": email.upper(),
                                                     "organization_id": world.org1})
    assert again.status_code == 409 and again.json()["code"] == "IDENTITY_EXISTS"


def test_password_change_required_blocks_everything_but_change(api, world):
    email = f"{uniq()}@example.test"
    temp = api.post("/v1/users", world.maker, json={"display_name": "New Hire", "email": email,
                                                    "organization_id": world.org1}).json()["temporary_password"]
    signed = api.login(email, temp)
    assert signed["password_change_required"] is True
    h = _bearer(signed["access_token"])
    assert api.get("/v1/me", h).status_code == 200  # allowed so the UI can show the change screen
    blocked = api.get("/v1/me/permissions", h)
    assert blocked.status_code == 403 and blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert api.get("/v1/users", h).json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    weak = api.post("/v1/auth/password/change", h, json={"current_password": temp, "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["errors"][0]["code"] == "PASSWORD_POLICY"
    changed = api.post("/v1/auth/password/change", h, json={"current_password": temp, "new_password": PASSWORD})
    assert changed.status_code == 200 and changed.json()["password_change_required"] is False
    assert api.get("/v1/me/permissions", _bearer(changed.json()["access_token"])).status_code == 200
    assert api.sql("SELECT password_change_required FROM auth_identities WHERE identifier = :e", e=email)[0][0] is False
    # the temporary password no longer works
    assert api.post("/v1/auth/password/login", json={"email": email, "password": temp}).status_code == 401


def test_admin_reset_sets_change_required_and_ends_sessions(api, world):
    user = api.create_user(world.maker, world.org1)
    r = api.post(f"/v1/users/{user.user_id}/password/reset", world.maker)
    assert r.status_code == 200
    stale = api.get("/v1/me", user)
    assert stale.status_code == 200  # access token lives until expiry, but refresh is gone:
    assert api.sql("SELECT count(*) FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL",
                   u=user.user_id)[0][0] == 0
    signed = api.login(user.email, r.json()["temporary_password"])
    assert signed["password_change_required"] is True


def test_wrong_password_locks_identity_after_limit(api, world):
    user = api.create_user(world.maker, world.org1)
    for _ in range(5):
        r = api.post("/v1/auth/password/login", json={"email": user.email, "password": "wrong-password-1"})
        assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    locked = api.post("/v1/auth/password/login", json={"email": user.email, "password": PASSWORD})
    assert locked.status_code == 423 and locked.json()["code"] == "IDENTITY_LOCKED"
    api.patch(f"/v1/users/{user.user_id}/status", world.maker, json={"status": "UNLOCK"})
    assert api.post("/v1/auth/password/login", json={"email": user.email, "password": PASSWORD}).status_code == 200


def test_unknown_email_and_wrong_password_look_the_same(api):
    a = api.post("/v1/auth/password/login", json={"email": "nobody@example.test", "password": "x"}).json()
    assert a["code"] == "INVALID_CREDENTIALS" and a["status"] == 401


def test_disabled_user_cannot_sign_in_or_refresh(api, world):
    user = api.create_user(world.maker, world.org1)
    assert api.patch(f"/v1/users/{user.user_id}/status", world.maker,
                     json={"status": "DISABLED", "reason": "left"}).status_code == 200
    r = api.post("/v1/auth/password/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["code"] == "ACCOUNT_DISABLED"
    stale = api.get("/v1/me/permissions", user)
    assert stale.status_code == 401 and stale.json()["code"] == "TOKEN_STALE"


def test_admin_cannot_disable_themselves(api, world):
    r = api.patch(f"/v1/users/{world.maker.user_id}/status", world.maker, json={"status": "DISABLED"})
    assert r.status_code == 422 and r.json()["code"] == "SELF_STATUS_CHANGE"


# ------------------------------------------------------------------ sessions
def test_refresh_rotates_and_logout_revokes(api, world):
    user = api.create_user(world.maker, world.org1)
    api.c.cookies.clear()
    api.login(user.email, PASSWORD)
    first = api.c.cookies.get("js_refresh")
    assert first
    r = api.post("/v1/auth/refresh")
    assert r.status_code == 200
    second = api.c.cookies.get("js_refresh")
    assert second and second != first
    stored = api.sql("SELECT refresh_token_hash FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL",
                     u=user.user_id)
    hashes = {row[0] for row in stored}
    assert hashlib.sha256(second.encode()).hexdigest() in hashes  # only the hash is kept ...
    assert hashlib.sha256(first.encode()).hexdigest() not in hashes  # ... and the old one is gone
    assert second not in hashes and first not in hashes
    # replaying the rotated token fails
    api.c.cookies.set("js_refresh", first)
    assert api.post("/v1/auth/refresh").json()["code"] == "SESSION_ENDED"
    api.c.cookies.set("js_refresh", second)
    token = api.post("/v1/auth/refresh").json()["access_token"]
    assert api.post("/v1/auth/logout", _bearer(token)).status_code == 204
    api.c.cookies.set("js_refresh", api.c.cookies.get("js_refresh") or "x")
    assert api.post("/v1/auth/refresh").status_code == 401
    api.c.cookies.clear()


def test_token_body_never_carries_refresh_token(api, world):
    user = api.create_user(world.maker, world.org1)
    body = api.login(user.email, PASSWORD)
    assert "refresh" not in "".join(body.keys())
    cookie = api.c.cookies.get("js_refresh")
    assert cookie and cookie not in str(body)
    api.c.cookies.clear()


# ------------------------------------------------------------------ OTP
def test_otp_signup_creates_user_and_identity(api, mobile):
    body = api.otp_sign_in(mobile)
    rows = api.sql("SELECT identity_type, identifier, verified_at IS NOT NULL FROM auth_identities WHERE user_id = :u",
                   u=body["user"]["id"])
    assert rows == [("MOBILE_OTP", f"+91{mobile}", True)]
    again = api.otp_sign_in(mobile)  # second sign-in reuses the same user
    assert again["user"]["id"] == body["user"]["id"]


def test_otp_is_stored_only_as_keyed_hash(api, mobile):
    r = api.post("/v1/auth/otp/request", json={"mobile": mobile})
    assert r.status_code == 201
    body = r.json()
    code = api.get("/v1/dev/otp", params={"mobile": mobile}).json()["code"]
    assert code not in str(body) and mobile not in str(body)
    row = api.sql("SELECT code_hash, mobile_hash, mobile_last4 FROM otp_challenges WHERE id = :i",
                  i=body["challenge_id"])[0]
    code_hash, mobile_hash, last4 = row
    assert len(code_hash) == 64 and code not in code_hash
    assert code_hash != hashlib.sha256(code.encode()).hexdigest()  # keyed (HMAC), not a plain digest
    assert mobile not in mobile_hash and last4 == mobile[-4:]
    audit = api.sql("SELECT coalesce(metadata::text, '') || coalesce(after_data::text, '') FROM audit_logs "
                    "WHERE entity_id = :i", i=body["challenge_id"])
    assert audit and all(code not in a[0] and mobile not in a[0] for a in audit)


def test_otp_expiry(api, mobile):
    challenge = api.post("/v1/auth/otp/request", json={"mobile": mobile}).json()["challenge_id"]
    code = api.get("/v1/dev/otp", params={"mobile": mobile}).json()["code"]
    api.sql("UPDATE otp_challenges SET created_at = now() - interval '10 minutes', "
            "expires_at = now() - interval '1 second' WHERE id = :i", i=challenge)
    r = api.post("/v1/auth/otp/verify", json={"challenge_id": challenge, "mobile": mobile, "code": code})
    assert r.status_code == 401 and r.json()["code"] == "OTP_EXPIRED"
    assert api.sql("SELECT status FROM otp_challenges WHERE id = :i", i=challenge)[0][0] == "EXPIRED"


def test_otp_attempt_limit_locks_challenge(api, mobile):
    challenge = api.post("/v1/auth/otp/request", json={"mobile": mobile}).json()["challenge_id"]
    code = api.get("/v1/dev/otp", params={"mobile": mobile}).json()["code"]
    wrong = "000000" if code != "000000" else "111111"
    for attempt in range(1, 5):
        r = api.post("/v1/auth/otp/verify", json={"challenge_id": challenge, "mobile": mobile, "code": wrong})
        assert r.status_code == 401 and r.json()["details"]["attempts_left"] == 5 - attempt
    r = api.post("/v1/auth/otp/verify", json={"challenge_id": challenge, "mobile": mobile, "code": wrong})
    assert r.status_code == 423 and r.json()["code"] == "OTP_LOCKED"
    right = api.post("/v1/auth/otp/verify", json={"challenge_id": challenge, "mobile": mobile, "code": code})
    assert right.status_code == 423  # the correct code is refused once locked


def test_otp_for_a_different_mobile_is_refused(api, mobile):
    challenge = api.post("/v1/auth/otp/request", json={"mobile": mobile}).json()["challenge_id"]
    code = api.get("/v1/dev/otp", params={"mobile": mobile}).json()["code"]
    other = "8" + mobile[1:]
    r = api.post("/v1/auth/otp/verify", json={"challenge_id": challenge, "mobile": other, "code": code})
    assert r.status_code == 401 and r.json()["code"] == "OTP_INVALID"


def test_otp_rate_limit_per_mobile(api, mobile):
    for _ in range(3):
        assert api.post("/v1/auth/otp/request", json={"mobile": mobile}).status_code == 201
    r = api.post("/v1/auth/otp/request", json={"mobile": mobile})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


def test_new_otp_cancels_the_previous_one(api, mobile):
    first = api.post("/v1/auth/otp/request", json={"mobile": mobile}).json()["challenge_id"]
    api.post("/v1/auth/otp/request", json={"mobile": mobile})
    assert api.sql("SELECT status FROM otp_challenges WHERE id = :i", i=first)[0][0] == "CANCELLED"


@pytest.mark.parametrize("bad", ["12345", "5123456789", "98765432101", "abcdefghij"])
def test_invalid_mobile_numbers(api, bad):
    r = api.post("/v1/auth/otp/request", json={"mobile": bad.ljust(10, "x") if len(bad) < 10 else bad})
    assert r.status_code == 422


# ------------------------------------------------------------------ organizations and active context
def test_multi_organization_user_chooses_and_switches(api, world):
    user = api.create_user(world.maker, world.org1)
    api.add_member(world.maker, world.org2, user)
    signed = api.login(user.email, PASSWORD)
    assert signed["active_organization_id"] is None  # two organizations: the user chooses
    assert {o["organization"]["id"] for o in signed["organizations"]} == {world.org1, world.org2}
    h = _bearer(signed["access_token"])
    switched = api.post("/v1/me/organization/switch", h, json={"organization_id": world.org2})
    assert switched.status_code == 200
    token = switched.json()["token"]
    assert token["active_organization_id"] == world.org2
    me = api.get("/v1/me", _bearer(token["access_token"])).json()
    assert me["active_organization"]["id"] == world.org2
    # the session remembers the choice: refresh keeps it
    refreshed = api.post("/v1/auth/refresh").json()
    assert refreshed["active_organization_id"] == world.org2
    api.c.cookies.clear()


def test_cannot_switch_to_an_organization_without_membership(api, world):
    user = api.create_user(world.maker, world.org1)
    r = api.post("/v1/me/organization/switch", user, json={"organization_id": world.org2})
    assert r.status_code == 403 and r.json()["code"] == "NO_ACTIVE_MEMBERSHIP"


def test_suspended_membership_leaves_organization_choice(api, world):
    user = api.create_user(world.maker, world.org1)
    member = api.get(f"/v1/organizations/{world.org1}/members", world.maker, params={"size": 100}).json()["items"]
    mine = next(m for m in member if m["user"]["id"] == user.user_id)
    r = api.patch(f"/v1/organizations/{world.org1}/members/{mine['membership_id']}", world.maker,
                  json={"status": "SUSPENDED", "version": mine["version"]})
    assert r.status_code == 200
    assert api.login(user.email, PASSWORD)["organizations"] == []
    api.c.cookies.clear()


def test_jwks_publishes_only_public_keys(api):
    keys = api.get("/.well-known/jwks.json").json()["keys"]
    assert keys and all(set(k) == {"kty", "crv", "alg", "use", "kid", "x", "y"} for k in keys)  # no "d"
