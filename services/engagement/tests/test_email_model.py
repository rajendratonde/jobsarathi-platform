"""Approved email data model (owner: Engagement). Data model only: no API, no provider."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from engagement_service.models import EmailSettings


@pytest.fixture()
def engine(migrated):
    eng = create_engine(migrated)
    yield eng
    eng.dispose()


def _insert_settings(conn, **values):
    row = {"id": uuid.uuid4(), "setting_code": f"S{uuid.uuid4().hex[:8]}", **values}
    cols = ", ".join(row)
    conn.execute(text(f"INSERT INTO email_settings ({cols}) VALUES ({', '.join(':' + c for c in row)})"), row)


def test_smtp_password_can_only_be_a_secret_reference(engine):
    with engine.begin() as conn:
        _insert_settings(conn, smtp_password_ref="env:SMTP_PASSWORD")
        _insert_settings(conn, smtp_password_ref="file:/run/secrets/smtp")
    for literal in ("hunter2", "aws-sm:smtp", "env:", "env:lower case"):
        with pytest.raises(IntegrityError, match="ck_email_settings_password_is_reference"), engine.begin() as conn:
            _insert_settings(conn, smtp_password_ref=literal)


def test_no_column_can_hold_a_plain_password():
    columns = {c.name for c in EmailSettings.__table__.columns}
    assert "smtp_password" not in columns and "password" not in columns
    assert "smtp_password_ref" in columns


def test_public_view_never_contains_credentials():
    settings = EmailSettings(setting_code="DEFAULT", delivery_mode="SMTP", smtp_host="smtp.example.test", smtp_port=587,
                             smtp_username="mailer", smtp_password_ref="env:SMTP_PASSWORD", from_email="no@x.test",
                             version=1, is_enabled=True, smtp_security="STARTTLS", timeout_seconds=10)
    view = settings.public_view()
    assert view["smtp_password_set"] is True and view["smtp_username_set"] is True
    assert "env:SMTP_PASSWORD" not in str(view) and "mailer" not in str(view)


def test_smtp_mode_needs_host_port_and_sender(engine):
    with pytest.raises(IntegrityError, match="ck_email_settings_smtp_complete"), engine.begin() as conn:
        _insert_settings(conn, delivery_mode="SMTP", smtp_host="smtp.example.test")
    with pytest.raises(IntegrityError, match="ck_email_settings_enabled_has_mode"), engine.begin() as conn:
        _insert_settings(conn, is_enabled=True)


def test_templates_soft_delete_and_unique_live_code(engine):
    code = f"WELCOME_{uuid.uuid4().hex[:6].upper()}"
    insert = text("INSERT INTO email_templates (id, template_code, name, subject, body_text) "
                  "VALUES (:id, :code, 'Welcome', 'Hello', 'Hi {{name}}')")
    first = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(insert, {"id": first, "code": code})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), "code": code})
    with pytest.raises(IntegrityError, match="deleted_by_required"), engine.begin() as conn:
        conn.execute(text("UPDATE email_templates SET deleted_at = now() WHERE id = :i"), {"i": first})
    with engine.begin() as conn:
        conn.execute(text("UPDATE email_templates SET deleted_at = now(), deleted_by = :u WHERE id = :i"),
                     {"u": uuid.uuid4(), "i": first})
        conn.execute(insert, {"id": uuid.uuid4(), "code": code})  # the code is free again


def test_delivery_logs_hold_no_body_and_are_idempotent(engine):
    columns = {c["name"] for c in inspect(engine).get_columns("email_delivery_logs")}
    assert not columns & {"body", "body_text", "body_html", "subject", "recipient", "recipient_email", "password"}
    row = {"id": uuid.uuid4(), "template_code": "WELCOME", "recipient_masked": "a***@example.test",
           "recipient_hash": "0" * 64, "source_service": "identity", "source_reference": f"evt-{uuid.uuid4().hex}",
           "delivery_mode": "DISABLED", "status": "SKIPPED"}
    insert = text("INSERT INTO email_delivery_logs (id, template_code, recipient_masked, recipient_hash, source_service, "
                  "source_reference, delivery_mode, status) VALUES (:id, :template_code, :recipient_masked, "
                  ":recipient_hash, :source_service, :source_reference, :delivery_mode, :status)")
    with engine.begin() as conn:
        conn.execute(insert, row)
    with pytest.raises(IntegrityError, match="uq_email_delivery_logs_source"), engine.begin() as conn:
        conn.execute(insert, {**row, "id": uuid.uuid4()})
    with pytest.raises(IntegrityError, match="ck_email_delivery_logs_failure_code"), engine.begin() as conn:
        conn.execute(insert, {**row, "id": uuid.uuid4(), "source_reference": None, "status": "FAILED"})
