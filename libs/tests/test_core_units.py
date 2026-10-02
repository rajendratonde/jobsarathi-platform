"""Unit tests: IDs, configuration, secrets, logging, sorting."""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import SecretStr, ValidationError

from js_core import context, secrets
from js_core.config import DatabaseSettings, Environment, ServiceSettings
from js_core.errors import ValidationFailed
from js_core.ids import uuid7
from js_core.logging import ContextFilter, JsonFormatter, mask
from js_core.responses import parse_sort


def test_uuid7_version_variant_and_order():
    ids = [uuid7() for _ in range(5000)]
    assert all(i.version == 7 for i in ids)
    assert all((i.int >> 62) & 0b11 == 0b10 for i in ids)
    assert ids == sorted(ids), "UUIDv7 values must sort in creation order"
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("field,value,message", [
    ("run_migrations_on_start", True, "RUN_MIGRATIONS_ON_START"),
    ("cors_origins", ["*"], "CORS_ORIGINS"),
    ("log_format", "text", "JSON"),
])
def test_production_guards(field, value, message):
    with pytest.raises(ValidationError, match=message):
        ServiceSettings(service_name="x", app_env=Environment.PRODUCTION, **{field: value})


def test_docs_hidden_in_production_by_default():
    assert ServiceSettings(service_name="x", app_env=Environment.LOCAL).show_docs is True
    assert ServiceSettings(service_name="x", app_env=Environment.PRODUCTION).show_docs is False


def test_middleware_disabled_by_default():
    assert ServiceSettings(service_name="x").middleware_enabled is False


def test_database_url_escapes_and_resolves_references(monkeypatch, tmp_path):
    monkeypatch.setenv("SVC_PW", "p@ss:w/rd%")
    db = DatabaseSettings(host="h", port=5432, name="identity_db", user="identity_service_role",
                          password="env:SVC_PW", migration_user="identity_migration_role",
                          migration_password=SecretStr(f"file:{tmp_path / 'pw'}"))
    (tmp_path / "pw").write_text("m1gr@te\n", encoding="utf-8")
    assert db.runtime_url() == "postgresql+psycopg://identity_service_role:p%40ss%3Aw%2Frd%25@h:5432/identity_db?sslmode=prefer"
    assert "m1gr%40te@" in db.migration_url()
    assert "env:" not in repr(db) and "p@ss" not in repr(db), "secrets must not appear in repr"


def test_unknown_or_missing_secret_reference_fails_loudly():
    with pytest.raises(secrets.SecretResolutionError, match="TBD"):
        secrets.resolve("aws-sm:jobsarathi/db")
    with pytest.raises(secrets.SecretResolutionError):
        secrets.resolve("env:JOBSARATHI_DOES_NOT_EXIST")


def test_mask_nested_sensitive_keys():
    data = {"name": "Raj", "password": "x", "nested": {"smtp_password": "y", "token": "z", "ok": 1},
            "list": [{"otp": "123456"}]}
    assert mask(data) == {"name": "Raj", "password": "***", "nested": {"smtp_password": "***", "token": "***", "ok": 1},
                          "list": [{"otp": "***"}]}


def test_json_log_line_has_context_and_masks_extras():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.password = "secret-value"
    record.status = 200
    token = context.correlation_id_var.set("corr-abcdefgh")
    try:
        ContextFilter("identity", "test").filter(record)
        line = json.loads(JsonFormatter().format(record))
    finally:
        context.correlation_id_var.reset(token)
    assert line["message"] == "hello world"
    assert line["service"] == "identity" and line["correlation_id"] == "corr-abcdefgh"
    assert line["password"] == "***" and line["status"] == 200


def test_correlation_id_acceptance():
    assert context.accept_correlation_id("abc-12345678") == "abc-12345678"
    assert context.accept_correlation_id("bad\nvalue-123") is None
    assert context.accept_correlation_id("short") is None


def test_parse_sort_allow_list():
    assert parse_sort("-applied_at,title", {"applied_at", "title"}, "-applied_at") == [("applied_at", True), ("title", False)]
    assert parse_sort(None, {"created_at"}, "-created_at") == [("created_at", True)]
    with pytest.raises(ValidationFailed):
        parse_sort("password_hash", {"title"}, "title")
