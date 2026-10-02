"""Audit coverage, secret handling, internal routes and configuration guards."""

from __future__ import annotations

import uuid

import pytest
from identity_test_helpers import PASSWORD, uniq
from js_auth.context import Scope, widest
from js_auth.service_tokens import sign_service_token
from pydantic import ValidationError

from identity_service.config import Settings
from identity_service.security import (
    OtpHasher,
    check_password_policy,
    hash_password,
    normalize_mobile,
    temporary_password,
    verify_password,
)
from js_core.config import Environment
from js_core.errors import ValidationFailed


# ------------------------------------------------------------------ audit
def test_security_relevant_actions_are_audited(api, world, mobile):
    user = api.create_user(world.maker, world.org1)
    api.post("/v1/auth/password/login", json={"email": user.email, "password": "wrong-password-9"})
    api.otp_sign_in(mobile)
    role_id = api.make_role(world, ["USER.VIEW"])
    assignment = api.assign(world.maker, user, role_id, "ORGANIZATION").json()["entity_id"]
    api.delete(f"/v1/users/{user.user_id}/roles/{assignment}", world.maker)
    actions = {row[0] for row in api.sql("SELECT DISTINCT action FROM audit_logs")}
    expected = {
        "USER.CREATED", "MEMBERSHIP.CREATED", "AUTH.LOGIN_SUCCEEDED", "AUTH.LOGIN_FAILED", "AUTH.PASSWORD_CHANGED",
        "AUTH.OTP_REQUESTED", "AUTH.OTP_VERIFIED", "USER.REGISTERED", "ROLE.DRAFTED", "ROLE.CREATED",
        "APPROVAL.SUBMITTED", "APPROVAL.APPROVED", "ROLE_ASSIGNMENT.CREATED", "ROLE_ASSIGNMENT.REVOKED",
        "AUTH.ORGANIZATION_SWITCHED", "ORGANIZATION.CREATED", "USER.BOOTSTRAPPED",
    }
    assert expected <= actions, expected - actions
    row = api.sql("SELECT correlation_id, actor_user_id::text FROM audit_logs WHERE action = 'ROLE_ASSIGNMENT.REVOKED' "
                  "AND entity_id = :e", e=assignment)[0]
    assert row[0] and row[1] == world.maker.user_id


def test_audit_never_contains_credentials(api, world, mobile):
    email = f"{uniq()}@example.test"
    temp = api.post("/v1/users", world.maker, json={"display_name": "Secret Check", "email": email,
                                                    "organization_id": world.org1}).json()["temporary_password"]
    api.sign_in(email, temp)
    reset = api.post(f"/v1/users/{api.sql('SELECT user_id FROM auth_identities WHERE identifier = :e', e=email)[0][0]}"
                     "/password/reset", world.maker).json()["temporary_password"]
    challenge = api.post("/v1/auth/otp/request", json={"mobile": mobile}).json()
    code = api.get("/v1/dev/otp", params={"mobile": mobile}).json()["code"]
    everything = " ".join(str(r) for r in api.sql(
        "SELECT before_data::text, after_data::text, metadata::text FROM audit_logs"))
    for secret in (temp, reset, PASSWORD, mobile):
        assert secret not in everything
    assert f"\"{code}\"" not in everything and "$argon2" not in everything
    assert challenge["challenge_id"]


def test_audit_search_filters_and_pages(api, world):
    r = api.get("/v1/audit-logs", world.maker, params={"action": "AUTH.", "size": 5})
    body = r.json()
    assert r.status_code == 200 and len(body["items"]) <= 5 and body["total"] >= len(body["items"])
    assert all(item["action"].startswith("AUTH.") for item in body["items"])
    assert api.get("/v1/audit-logs", world.maker, params={"size": 101}).status_code == 422


# ------------------------------------------------------------------ nothing secret leaves the API
SECRET_MARKERS = ("password_hash", "code_hash", "mobile_hash", "refresh_token_hash", "$argon2")


def test_responses_never_expose_hashes(api, world):
    user = api.create_user(world.maker, world.org1)
    bodies = [api.get(path, world.maker).text for path in (
        f"/v1/users/{user.user_id}", "/v1/users", "/v1/me", f"/v1/users/{user.user_id}/roles",
        f"/v1/organizations/{world.org1}/members", "/v1/audit-logs?size=100", "/v1/approvals?status=")]
    for body in bodies:
        for marker in SECRET_MARKERS:
            assert marker not in body
    detail = api.get(f"/v1/users/{user.user_id}", world.maker).json()
    assert detail["identities"][0]["identifier"].startswith(user.email[0]) and "***@" in \
        detail["identities"][0]["identifier"]


def test_openapi_has_no_secret_fields(api):
    schema = api.get("/openapi.json").text
    for marker in ("password_hash", "code_hash", "mobile_hash", "refresh_token_hash", "otp_secret", "private_key"):
        assert marker not in schema


# ------------------------------------------------------------------ internal routes
def test_internal_routes_need_a_valid_service_token(api, world, employer_key):
    path = f"/v1/internal/authz/users/{world.maker.user_id}"
    assert api.get(path).status_code == 401
    assert api.get(path, {"X-Service-Token": "garbage"}).status_code == 401
    from cryptography.hazmat.primitives.asymmetric import ec
    impostor = sign_service_token(ec.generate_private_key(ec.SECP256R1()), issuer="employer", audience="identity")
    assert api.get(path, {"X-Service-Token": impostor}).status_code == 401
    good = sign_service_token(employer_key, issuer="employer", audience="identity")
    r = api.get(path, {"X-Service-Token": good}, params={"organization_id": world.platform_org})
    assert r.status_code == 200 and r.json()["permissions"]["ROLE.APPROVE"] == "ALL"
    wrong_audience = sign_service_token(employer_key, issuer="employer", audience="job")
    assert api.get(path, {"X-Service-Token": wrong_audience}).status_code == 401
    assert api.get(f"/v1/internal/authz/users/{uuid.uuid4()}", {"X-Service-Token": good}).status_code == 404


def test_services_declare_permissions_they_enforce(api, world, employer_key):
    token = sign_service_token(employer_key, issuer="employer", audience="identity")
    r = api.post("/v1/internal/permissions/declare", {"X-Service-Token": token},
                 json={"codes": ["USER.VIEW", "COMPANY.VERIFY"]})
    assert r.status_code == 200
    assert r.json() == {"declared": ["USER.VIEW"], "unknown": ["COMPANY.VERIFY"]}  # never auto-created
    assert api.sql("SELECT count(*) FROM permissions WHERE permission_code = 'COMPANY.VERIFY'")[0][0] == 0


# ------------------------------------------------------------------ settings guards (no database)
@pytest.mark.parametrize("env", ["staging", "production"])
def test_dev_otp_sink_is_refused_outside_development(env):
    with pytest.raises(ValidationError, match="OTP_DEV_SINK"):
        Settings(app_env=Environment(env), otp_dev_sink=True, log_format="json")


def test_production_requires_secure_refresh_cookie():
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
        Settings(app_env=Environment.PRODUCTION, refresh_cookie_secure=False, otp_dev_sink=False, log_format="json")


def test_configuration_errors_never_echo_input_values():
    with pytest.raises(ValidationError) as err:
        Settings(app_env=Environment.PRODUCTION, otp_dev_sink=True, log_format="json",
                 jwt_private_key_ref="super-secret-value")
    assert "super-secret-value" not in str(err.value) and "input_value" not in str(err.value)


def test_otp_secret_required_outside_development():
    with pytest.raises(RuntimeError, match="OTP_SECRET_REF"):
        OtpHasher.from_settings(None, Environment.PRODUCTION)


# ------------------------------------------------------------------ credential helpers (no database)
def test_password_hashing_is_argon2id_and_salted():
    a, b = hash_password("Same-password-1"), hash_password("Same-password-1")
    assert a.startswith("$argon2id$") and a != b
    assert verify_password(a, "Same-password-1") and not verify_password(a, "same-password-1")
    assert not verify_password(None, "anything")


def test_password_policy():
    with pytest.raises(ValidationFailed):
        check_password_policy("onlyletters", min_length=10)
    with pytest.raises(ValidationFailed):
        check_password_policy("ravi.kumar2026", min_length=10, forbidden=("ravi.kumar",))
    check_password_policy("Good-pass-2026", min_length=10)
    assert len(temporary_password()) == 14


def test_otp_hash_is_keyed_and_bound_to_challenge():
    one, two = OtpHasher(b"k" * 32), OtpHasher(b"z" * 32)
    cid = uuid.uuid4()
    assert one.code_hash(cid, "123456") != two.code_hash(cid, "123456")
    assert one.code_hash(cid, "123456") != one.code_hash(uuid.uuid4(), "123456")
    assert one.code_matches(cid, "123456", one.code_hash(cid, "123456"))
    with pytest.raises(ValueError):
        OtpHasher(b"short")


@pytest.mark.parametrize(("raw", "expected"), [("9876543210", "+919876543210"), ("+91 98765 43210", "+919876543210"),
                                               ("09876543210", "+919876543210")])
def test_mobile_normalisation(raw, expected):
    assert normalize_mobile(raw) == expected


def test_scope_ranking_ignores_inactive_scopes():
    assert widest(None, Scope.OWN) is Scope.OWN
    assert widest(Scope.OWN, Scope.ALL) is Scope.ALL
    assert widest(Scope.ORGANIZATION, Scope.OWN) is Scope.ORGANIZATION
    assert widest(Scope.OWN, Scope.CITY) is Scope.OWN and not Scope.REGION.active
