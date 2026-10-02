"""SMS / OTP delivery: provider-neutral.

Modes (SMS_MODE): ``disabled`` (default) or ``dev_log`` (local/dev/test only).
No provider adapter exists yet: the SMS provider and India DLT registration
are open decisions (Q1, T5). The dev sink writes only the last 4 digits of the
number; whether it may also show OTP codes to testers is decision Q2 and is
handled in the Identity phase, not here.
"""

from __future__ import annotations

import logging
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

from js_core.config import Environment
from js_integration.guards import forbid_dev_sink
from js_integration.result import DISABLED, IntegrationResult, IntegrationStatus

log = logging.getLogger("js_integration.sms")


class SmsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMS_", extra="ignore")
    mode: str = "disabled"  # disabled | dev_log  (a provider mode is added once T5/Q1 are decided)


class SmsSender(Protocol):
    def send(self, to_e164: str, template_id: str, params: dict[str, str]) -> IntegrationResult: ...


class DisabledSmsSender:
    def send(self, to_e164: str, template_id: str, params: dict[str, str]) -> IntegrationResult:
        return DISABLED


class LogSmsSender:
    def send(self, to_e164: str, template_id: str, params: dict[str, str]) -> IntegrationResult:
        log.info("sms (dev_log, not sent)", extra={"to_last4": to_e164[-4:], "template_id": template_id})
        return IntegrationResult(IntegrationStatus.OK, reference="dev-log")


def build_sms_sender(settings: SmsSettings, *, middleware_enabled: bool, env: Environment) -> SmsSender:
    forbid_dev_sink(settings.mode, env, "SMS")
    if settings.mode == "dev_log":
        return LogSmsSender()
    if settings.mode == "disabled" or not middleware_enabled:
        return DisabledSmsSender()
    raise ValueError(f"SMS_MODE {settings.mode!r} is not available: no SMS provider is decided yet (T5/Q1)")
