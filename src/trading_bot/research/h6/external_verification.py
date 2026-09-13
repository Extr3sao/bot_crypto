"""P19 — external verification state detection.

Builder self-tests do NOT convert PENDING -> PASS.
"""

from __future__ import annotations

from enum import StrEnum

# V4 repair (V3-AUTH-001): the report location is no longer a module literal. It comes
# from runtime_authority and is resolved against the repository root, never the CWD.
from trading_bot.research.h6.external_verifier_report import (
    external_report_exists,
    report_path,
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
