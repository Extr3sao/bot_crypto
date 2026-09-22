"""P19 — external verification state detection.

Builder self-tests do NOT convert PENDING -> PASS.
"""

from __future__ import annotations

from enum import StrEnum

from trading_bot.research.h6.external_verifier_report import (
    external_report_exists,
    read_external_verdict,
)


class ExternalVerificationState(StrEnum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


def external_verification_state() -> ExternalVerificationState:
    if not external_report_exists():
        return ExternalVerificationState.PENDING
    verdict = read_external_verdict()
    if verdict == "PASS":
        return ExternalVerificationState.PASS
    if verdict in ("FAIL", "BLOCKED"):
        return ExternalVerificationState(verdict)
    return ExternalVerificationState.PENDING
