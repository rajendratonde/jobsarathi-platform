"""Integration client: disabled by default, dev sinks never in production, SMTP secrets never exposed."""

from __future__ import annotations

import smtplib
from unittest import mock

import pytest

from js_core.config import Environment
from js_integration import (
    EmailMessage,
    EmailSettings,
    IntegrationStatus,
    SmsSettings,
    build_email_sender,
    build_sms_sender,
)
from js_integration.guards import UnsafeIntegrationConfig

MSG = EmailMessage(to=["candidate@example.com"], subject="Hello", text_body="Body")


def test_email_disabled_by_default():
    sender = build_email_sender(EmailSettings(), middleware_enabled=False, env=Environment.LOCAL)
    assert sender.send(MSG).status is IntegrationStatus.DISABLED


def test_middleware_off_wins_over_smtp_mode():
    settings = EmailSettings(mode="smtp", smtp_host="smtp.example.test", from_email="no-reply@example.test")
    sender = build_email_sender(settings, middleware_enabled=False, env=Environment.STAGING)
    assert sender.send(MSG).status is IntegrationStatus.DISABLED


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_dev_sinks_refused_outside_development(env):
    with pytest.raises(UnsafeIntegrationConfig):
        build_email_sender(EmailSettings(mode="dev_log"), middleware_enabled=True, env=env)
    with pytest.raises(UnsafeIntegrationConfig):
        build_sms_sender(SmsSettings(mode="dev_log"), middleware_enabled=True, env=env)


def test_dev_log_sink_does_not_send(caplog):
    sender = build_email_sender(EmailSettings(mode="dev_log"), middleware_enabled=False, env=Environment.LOCAL)
    assert sender.send(MSG).status is IntegrationStatus.OK


def test_smtp_requires_host_and_from():
    with pytest.raises(ValueError):
        build_email_sender(EmailSettings(mode="smtp"), middleware_enabled=True, env=Environment.LOCAL)


def test_smtp_send_uses_secret_reference_and_never_exposes_it(monkeypatch):
    monkeypatch.setenv("TEST_SMTP_PASSWORD", "s3cr3t-value")
    settings = EmailSettings(mode="smtp", smtp_host="smtp.example.test", smtp_port=587, smtp_username="mailer",
                             smtp_password_ref="env:TEST_SMTP_PASSWORD", from_email="no-reply@example.test",
                             from_name="JobSarathi", reply_to="help@example.test")
    assert "s3cr3t" not in repr(settings) and "s3cr3t" not in str(settings.describe())
    assert settings.describe()["smtp_password_set"] is True
    sender = build_email_sender(settings, middleware_enabled=True, env=Environment.STAGING)
    with mock.patch("smtplib.SMTP") as smtp:
        client = smtp.return_value
        client.__enter__.return_value = client  # like the real smtplib.SMTP
        result = sender.send(MSG)
    assert result.status is IntegrationStatus.OK
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("mailer", "s3cr3t-value")
    sent = client.send_message.call_args.args[0]
    assert sent["From"] == "JobSarathi <no-reply@example.test>" and sent["Reply-To"] == "help@example.test"


def test_smtp_failure_reports_without_secret(monkeypatch):
    monkeypatch.setenv("TEST_SMTP_PASSWORD", "s3cr3t-value")
    settings = EmailSettings(mode="smtp", smtp_host="smtp.example.test", smtp_username="mailer",
                             smtp_password_ref="env:TEST_SMTP_PASSWORD", from_email="no-reply@example.test")
    sender = build_email_sender(settings, middleware_enabled=True, env=Environment.STAGING)
    with mock.patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = smtp.return_value
        smtp.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        result = sender.send(MSG)
    assert result.status is IntegrationStatus.FAILED and not result.retriable
    assert "s3cr3t" not in (result.detail or "")


def test_sms_has_no_provider_yet():
    assert build_sms_sender(SmsSettings(), middleware_enabled=True, env=Environment.LOCAL).send(
        "+919999999999", "OTP", {}).status is IntegrationStatus.DISABLED
    with pytest.raises(ValueError, match="T5"):
        build_sms_sender(SmsSettings(mode="provider"), middleware_enabled=True, env=Environment.LOCAL)
