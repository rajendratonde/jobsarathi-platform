from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntegrationStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class IntegrationResult:
    status: IntegrationStatus
    reference: str | None = None
    retriable: bool = False
    detail: str | None = None  # never contains credentials or message bodies

    @property
    def ok(self) -> bool:
        return self.status is IntegrationStatus.OK


DISABLED = IntegrationResult(IntegrationStatus.DISABLED, detail="Integration switched off (MIDDLEWARE_ENABLED=false)")
