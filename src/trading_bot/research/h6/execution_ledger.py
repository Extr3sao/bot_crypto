"""P16 — exactly-once ledger integration for H6.

Uses existing ResearchExecutionLedger semantics: durable STARTED,
then COMPLETED or FAILED. Synthetic tests only. No real H6 STARTED
record is created in this checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class H6ExecutionAttempt:
    attempt_id: str
    started_at: datetime
    status: str
    recovery_of: str | None = None
    recovered_by: str | None = None


class H6ExecutionLedger:
    """Prepared exactly-once semantics for future H6 execution.

    This checkpoint does NOT allocate a real H6 attempt.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, H6ExecutionAttempt] = {}

    def record_started(self, attempt_id: str) -> H6ExecutionAttempt:
        if attempt_id in self._attempts:
            raise ValueError(f"duplicate STARTED: {attempt_id}")
        started_at = datetime.now(UTC)
        attempt = H6ExecutionAttempt(
            attempt_id=attempt_id,
            started_at=started_at,
            status="STARTED",
        )
        self._attempts[attempt_id] = attempt
        return attempt

    def complete(self, attempt_id: str, recovered_by: str | None = None) -> H6ExecutionAttempt:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise KeyError(attempt_id)
        if attempt.status != "STARTED":
            raise ValueError(f"invalid transition for {attempt_id}: {attempt.status}")
        completed = H6ExecutionAttempt(
            attempt_id=attempt_id,
            started_at=attempt.started_at,
            status="COMPLETED",
            recovery_of=attempt.recovery_of,
            recovered_by=recovered_by,
        )
        self._attempts[attempt_id] = completed
        return completed

    def fail(self, attempt_id: str, recovered_by: str | None = None) -> H6ExecutionAttempt:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise KeyError(attempt_id)
        if attempt.status != "STARTED":
            raise ValueError(f"invalid transition for {attempt_id}: {attempt.status}")
        failed = H6ExecutionAttempt(
            attempt_id=attempt_id,
            started_at=attempt.started_at,
            status="FAILED",
            recovery_of=attempt.recovery_of,
            recovered_by=recovered_by,
        )
        self._attempts[attempt_id] = failed
        return failed

    def exists(self, attempt_id: str) -> bool:
        return attempt_id in self._attempts

    def by_id(self, attempt_id: str) -> H6ExecutionAttempt:
        return self._attempts[attempt_id]
