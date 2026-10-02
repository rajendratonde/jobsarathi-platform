"""Integration client (Implementation Blueprint §15).

Business services reach external providers only through this package. With
``MIDDLEWARE_ENABLED=false`` (the default) every call answers DISABLED at once.
No vendor is implemented: email uses generic SMTP, SMS has no provider yet.
"""

from js_integration.email import (
    EmailMessage,
    EmailSender,
    EmailSettings,
    SmtpSecurity,
    build_email_sender,
)
from js_integration.result import IntegrationResult, IntegrationStatus
from js_integration.sms import SmsSender, SmsSettings, build_sms_sender

__all__ = [
    "IntegrationResult", "IntegrationStatus",
    "EmailMessage", "EmailSender", "EmailSettings", "SmtpSecurity", "build_email_sender",
    "SmsSender", "SmsSettings", "build_sms_sender",
]
