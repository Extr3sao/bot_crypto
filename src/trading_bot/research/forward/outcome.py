"""The capture exit contract (§2-§4).

A capture that could not persist what it was asked to persist is a *failure*,
and a failure has to be visible to whatever started the process. Before this
module a capture whose writes had died recorded ``integrity.failures`` honestly
in its manifest and then exited 0, so a supervisor — and any operator reading
only exit codes — saw a clean completion. Honest data in a file nobody reads is
not an exit contract.

Three outcomes, never two
-------------------------

``COMPLETE``          the run ended the way it was configured to end (duration).
``CONTROLLED_STOP``   an operator, a stop file, or the disk guard ended it, and
                      the collector sealed its segments and wrote its manifest.
``FAILED``            a terminal persistence, invariant or book failure.

``COMPLETE`` and ``CONTROLLED_STOP`` are both exits with code 0, because both
mean "everything that we wrote is complete and accounted for". They stay
*separate values* in the manifest because "the run finished its two hours" and
"somebody pressed Ctrl-C" are different findings, and collapsing them is how a
report starts claiming a duration it never ran.

Failure is non-zero
-------------------

``FAILED`` exits 2. Exit codes are the only channel that survives a wrapper
script, a supervisor, or an operator who never opens the manifest, so the code
has to carry the same verdict the manifest carries. A non-zero exit is what makes
the supervisor restart the capture with backoff instead of treating a dead writer
as a completed run (§3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

__all__ = [
    "CONTROLLED_STOP_REASONS",
    "EXIT_COMPLETE",
    "EXIT_FAILED",
    "FAILURE_BOOK",
    "FAILURE_CORRUPTION",
    "FAILURE_MANIFEST",
    "FAILURE_STORAGE",
    "FAILURE_TIMESTAMP",
    "CaptureOutcome",
    "CaptureStatus",
    "classify_capture",
    "exit_code_for_status",
]

EXIT_COMPLETE: Final[int] = 0
EXIT_FAILED: Final[int] = 2


class CaptureStatus(StrEnum):
    """How a capture ended, as published in the manifest and as an exit code."""

    COMPLETE = "COMPLETE"
    CONTROLLED_STOP = "CONTROLLED_STOP"
    FAILED = "FAILED"


#: Reasons a run may end that are *not* failures. A disk-guard stop belongs here
#: because the guard exists to end the capture safely, and the capture does.
CONTROLLED_STOP_REASONS: Final[frozenset[str]] = frozenset(
    {
        "duration reached",
        "stop file",
        "signal",
        "disk budget",
        "disk guard",
        "operator stop",
        "controlled stop",
    }
)

FAILURE_STORAGE: Final[str] = "STORAGE_WRITE_FAILURE"
FAILURE_MANIFEST: Final[str] = "MANIFEST_FAILURE"
FAILURE_TIMESTAMP: Final[str] = "TIMESTAMP_INVARIANT"
FAILURE_BOOK: Final[str] = "BOOK_UNRECOVERABLE"
FAILURE_CORRUPTION: Final[str] = "COLLECTOR_CORRUPTION"

#: Kinds that mean "nothing after this point is trustworthy until a restart".
TERMINAL_FAILURE_KINDS: Final[frozenset[str]] = frozenset(
    {
        FAILURE_STORAGE,
        FAILURE_MANIFEST,
        FAILURE_TIMESTAMP,
        FAILURE_BOOK,
        FAILURE_CORRUPTION,
    }
)


def exit_code_for_status(status: str | CaptureStatus) -> int:
    """``0`` for a clean or controlled end, ``2`` for a failure. Nothing else."""
    value = CaptureStatus(str(status))
    return EXIT_FAILED if value is CaptureStatus.FAILED else EXIT_COMPLETE


@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    """The verdict for one capture run, and the evidence behind it."""

    status: CaptureStatus
    kind: str | None = None
    reason: str | None = None
    stop_reason: str | None = None

    @property
    def failed(self) -> bool:
        return self.status is CaptureStatus.FAILED

    @property
    def exit_code(self) -> int:
        return exit_code_for_status(self.status)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "failure_kind": self.kind,
            "failure_reason": self.reason,
            "stop_reason": self.stop_reason,
            "exit_code": self.exit_code,
        }

    def describe(self) -> str:
        if self.failed:
            return f"{self.status.value} ({self.kind}): {self.reason}"
        return f"{self.status.value} (stop reason: {self.stop_reason or 'unknown'})"


def classify_capture(
    *,
    stop_reason: str | None,
    fatal_kind: str | None = None,
    fatal_reason: str | None = None,
    clock_violations: int = 0,
    book_failed_streams: tuple[str, ...] = (),
) -> CaptureOutcome:
    """Decide what a finished run *was*, from what it recorded about itself.

    Ordered by how much they destroy: a persistence failure means the later data
    cannot be trusted, an unrecoverable book failure means a stream's derived
    state is wrong, and a timestamp-invariant failure means rows were rejected
    against the contract they were captured under. The first one that applies
    names the run, so a run that both lost its writer and dropped a symbol is
    reported as the storage failure that caused the rest.
    """
    if fatal_kind in TERMINAL_FAILURE_KINDS:
        return CaptureOutcome(
            status=CaptureStatus.FAILED,
            kind=fatal_kind,
            reason=fatal_reason or "no reason recorded",
            stop_reason=stop_reason,
        )
    if clock_violations > 0:
        return CaptureOutcome(
            status=CaptureStatus.FAILED,
            kind=FAILURE_TIMESTAMP,
            reason=(
                f"{clock_violations} event(s) violated the temporal guarantee "
                "(max_event_skew_ms); the rejected rows are not in the capture"
            ),
            stop_reason=stop_reason,
        )
    if book_failed_streams:
        return CaptureOutcome(
            status=CaptureStatus.FAILED,
            kind=FAILURE_BOOK,
            reason=(
                "book health FAILED at the end of the run for "
                + ", ".join(sorted(book_failed_streams))
            ),
            stop_reason=stop_reason,
        )
    if stop_reason is None or stop_reason in CONTROLLED_STOP_REASONS:
        status = (
            CaptureStatus.COMPLETE
            if stop_reason in (None, "duration reached")
            else CaptureStatus.CONTROLLED_STOP
        )
        return CaptureOutcome(status=status, stop_reason=stop_reason)
    # An unrecognised stop reason is not an excuse to claim success: the run
    # ended for a reason nobody declared, so it is reported as a controlled stop
    # *of unknown origin* rather than silently promoted to COMPLETE.
    return CaptureOutcome(
        status=CaptureStatus.CONTROLLED_STOP,
        reason=f"unrecognised stop reason {stop_reason!r}",
        stop_reason=stop_reason,
    )
