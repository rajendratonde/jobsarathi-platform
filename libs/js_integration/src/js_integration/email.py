"""Email sending: provider-neutral.

Modes (EMAIL_MODE):
  disabled  - default; send() answers DISABLED
  dev_log   - writes recipient and subject (never the body) to the log; local/dev/test only
  smtp      - generic SMTP: host, port, username, password secret reference, security, from, reply-to, timeout

No email provider is chosen (T5). Templates and delivery logs are application
data and are NOT part of the Foundation (see docs/foundation.md, "Email").
The SMTP password is always resolved from a secret reference and is never
returned, logged or included in an error message.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, make_msgid
from enum import StrEnum
from typing import Protocol

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from js_core import secrets
from js_core.config import Environment
from js_integration.guards import forbid_dev_sink
from js_integration.result import DISABLED, IntegrationResult, IntegrationStatus

log = logging.getLogger("js_integration.email")


class SmtpSecurity(StrEnum):
    STARTTLS = "STARTTLS"  # usually port 587
    SSL = "SSL"            # implicit TLS, usually port 465
    NONE = "NONE"          # local test servers only


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMAIL_", extra="ignore")

    mode: str = "disabled"  # disabled | dev_log | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password_ref: SecretStr | None = None  # env:NAME or file:/path, never a literal in code
    smtp_security: SmtpSecurity = SmtpSecurity.STARTTLS
    from_email: str | None = None
    from_name: str | None = None
    reply_to: str | None = None
    timeout_seconds: int = 10

    def describe(self) -> dict:
        """Safe view for an admin screen or health check: no secret, only whether one is set."""
        return {"mode": self.mode, "smtp_host": self.smtp_host, "smtp_port": self.smtp_port,
                "smtp_username": self.smtp_username, "smtp_password_set": self.smtp_password_ref is not None,
                "smtp_security": self.smtp_security.value, "from_email": self.from_email, "from_name": self.from_name,
                "reply_to": self.reply_to, "timeout_seconds": self.timeout_seconds}


@dataclass(frozen=True)
class EmailMessage:
    to: list[str]
    subject: str
    text_body: str
    html_body: str | None = None
    cc: list[str] = field(default_factory=list)
    reply_to: str | None = None


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> IntegrationResult: ...


class DisabledEmailSender:
    def send(self, message: EmailMessage) -> IntegrationResult:
        return DISABLED


class LogEmailSender:
    """Development sink: proves the call happened without sending anything."""

    def send(self, message: EmailMessage) -> IntegrationResult:
        log.info("email (dev_log, not sent)", extra={"to_count": len(message.to), "subject": message.subject})
        return IntegrationResult(IntegrationStatus.OK, reference="dev-log")


class SmtpEmailSender:
    def __init__(self, settings: EmailSettings) -> None:
        if not settings.smtp_host or not settings.from_email:
            raise ValueError("EMAIL_SMTP_HOST and EMAIL_FROM_EMAIL are required for EMAIL_MODE=smtp")
        self.settings = settings
        self._password = secrets.resolve(settings.smtp_password_ref)

    def _mime(self, message: EmailMessage) -> MimeMessage:
        s = self.settings
        mime = MimeMessage()
        mime["From"] = formataddr((s.from_name or "", s.from_email))
        mime["To"] = ", ".join(message.to)
        if message.cc:
            mime["Cc"] = ", ".join(message.cc)
        reply_to = message.reply_to or s.reply_to
        if reply_to:
            mime["Reply-To"] = reply_to
        mime["Subject"] = message.subject
        mime["Message-ID"] = make_msgid(domain=s.from_email.split("@")[-1])
        mime.set_content(message.text_body)
        if message.html_body:
            mime.add_alternative(message.html_body, subtype="html")
        return mime

    def send(self, message: EmailMessage) -> IntegrationResult:
        s = self.settings
        mime = self._mime(message)
        try:
            context = ssl.create_default_context()
            if s.smtp_security is SmtpSecurity.SSL:
                client = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.timeout_seconds, context=context)
            else:
                client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.timeout_seconds)
            with client:
                if s.smtp_security is SmtpSecurity.STARTTLS:
                    client.starttls(context=context)
                if s.smtp_username and self._password:
                    client.login(s.smtp_username, self._password.get_secret_value())
                client.send_message(mime)
            return IntegrationResult(IntegrationStatus.OK, reference=mime["Message-ID"])
        except smtplib.SMTPAuthenticationError:
            log.warning("SMTP authentication failed")
            return IntegrationResult(IntegrationStatus.FAILED, retriable=False, detail="SMTP authentication failed")
        except (smtplib.SMTPException, OSError) as exc:
            log.warning("SMTP send failed: %s", type(exc).__name__)
            return IntegrationResult(IntegrationStatus.FAILED, retriable=True, detail=type(exc).__name__)


def build_email_sender(settings: EmailSettings, *, middleware_enabled: bool, env: Environment) -> EmailSender:
    forbid_dev_sink(settings.mode, env, "Email")
    if settings.mode == "dev_log":
        return LogEmailSender()
    if not middleware_enabled or settings.mode == "disabled":
        return DisabledEmailSender()
    if settings.mode == "smtp":
        return SmtpEmailSender(settings)
    raise ValueError(f"Unknown EMAIL_MODE {settings.mode!r}")
