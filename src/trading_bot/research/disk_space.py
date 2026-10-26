"""CAP-004C — free-space guard for a long-running evidence campaign.

The campaign's failure mode was never a bad decision: it was that a cycle could
run out of room (or of address space) *while writing evidence*, so a real
settlement produced no record.  A storage problem must therefore be observable
BEFORE the expensive work, and it must be expressed as a storage state — never as
an economic one.

Three states, derived from the measured behaviour of this host (238 GiB volume,
±4 GiB of transient oscillation caused by activity outside the repository):

* ``HEALTHY``  — more than :data:`HEALTHY_FREE_BYTES` free.
* ``WARNING``  — between :data:`CRITICAL_FREE_BYTES` and ``HEALTHY_FREE_BYTES``.
* ``CRITICAL`` — below :data:`CRITICAL_FREE_BYTES`: the campaign must stop
  creating new sealed decisions and spend its remaining room protecting the
  evidence it already has (settle, evaluate, verify, flush).

Prediction is reported as a number of days only when the measured growth rate is
stable enough to justify it; otherwise it is reported as ``UNKNOWN``/``VOLATILE``
rather than invented.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import itertools
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CRITICAL",
    "CRITICAL_FREE_BYTES",
    "DISK_EVENTS_FILENAME",
    "DISK_STATE_FILENAME",
    "HEALTHY",
    "HEALTHY_FREE_BYTES",
    "WARNING",
    "DiskSpaceGuard",
    "GrowthSample",
    "disk_report",
    "estimate_days_to_threshold",
    "growth_rate",
    "transition_event",
    "volume_anchor",
]

HEALTHY = "HEALTHY"
WARNING = "WARNING"
CRITICAL = "CRITICAL"

GIB = 1024**3
HEALTHY_FREE_BYTES = 5 * GIB
CRITICAL_FREE_BYTES = 2 * GIB

DISK_STATE_FILENAME = "DISK_STATE.json"
DISK_EVENTS_FILENAME = "disk_events.jsonl"

#: A growth rate is only turned into a forecast when it is this stable: the
#: standard deviation of the per-interval deltas must stay below this fraction of
#: their mean.  Otherwise the honest answer is UNKNOWN.
STABILITY_MAX_COEFFICIENT_OF_VARIATION = 0.5


@dataclass(frozen=True)
class GrowthSample:
    """One observation of a growing tree: ``(timestamp, bytes)``."""

    timestamp: int
    bytes: int
    label: str = ""


def volume_anchor(path: Path) -> Path:
    """The nearest existing ancestor of ``path``.

    Free space is a property of the VOLUME, so it can be measured before the
    directory exists (a first cycle, or a test using a temporary tree).  Asking
    the OS about a path that does not exist yet is an error, not an answer.
    """
    current = Path(path).resolve()
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    return current


def _status_for(free_bytes: int, *, warning_bytes: int, critical_bytes: int) -> str:
    if free_bytes < critical_bytes:
        return CRITICAL
    if free_bytes < warning_bytes:
        return WARNING
    return HEALTHY


def disk_report(
    path: Path,
    *,
    warning_bytes: int = HEALTHY_FREE_BYTES,
    critical_bytes: int = CRITICAL_FREE_BYTES,
) -> dict[str, Any]:
    """Current storage state at ``path``, with the thresholds that produced it."""
    usage = shutil.disk_usage(volume_anchor(path))
    free = int(usage.free)
    total = int(usage.total)
    return {
        "path": str(path),
        "free_bytes": free,
        "free_gib": round(free / GIB, 4),
        "total_bytes": total,
        "total_gib": round(total / GIB, 4),
        "used_percent": round((total - free) / total * 100, 2) if total else None,
        "warning_free_bytes": int(warning_bytes),
        "critical_free_bytes": int(critical_bytes),
        "status": _status_for(free, warning_bytes=warning_bytes, critical_bytes=critical_bytes),
    }


def estimate_days_to_threshold(
    *,
    free_bytes: int,
    threshold_bytes: int,
    growth_bytes_per_day: float | None,
) -> float | None:
    """Days until ``threshold_bytes`` free remains.  ``None`` = not predictable."""
    if growth_bytes_per_day is None or growth_bytes_per_day <= 0:
        return None
    if free_bytes <= threshold_bytes:
        return 0.0
    return round((free_bytes - threshold_bytes) / growth_bytes_per_day, 3)


def growth_rate(
    samples: Sequence[GrowthSample],
    *,
    after: int | None = None,
    max_coefficient_of_variation: float = STABILITY_MAX_COEFFICIENT_OF_VARIATION,
) -> dict[str, Any]:
    """Bytes/day implied by consecutive samples, with an explicit stability flag.

    Only intervals with a positive time delta are used.  If the deltas are not
    stable the status is ``VOLATILE`` and ``bytes_per_day`` is ``None``: a forecast
    built on an unstable rate would be a number invented for the report.

    ``after`` is a *discontinuity*: a timestamp at which the measured quantity was
    redefined (a certified migration compacted the tree).  Samples at or before it
    describe a different series, and mixing them into one rate would report a
    migration as negative growth.  They are dropped — and counted, so the report can
    show that they were dropped rather than silently mislaid.
    """
    ordered = sorted(samples, key=lambda item: item.timestamp)
    discarded = 0
    if after is not None:
        kept = [item for item in ordered if item.timestamp > after]
        discarded = len(ordered) - len(kept)
        ordered = kept
    deltas: list[float] = []
    intervals: list[float] = []
    for previous, current in itertools.pairwise(ordered):
        span = current.timestamp - previous.timestamp
        if span <= 0:
            continue
        intervals.append(float(span))
        deltas.append((current.bytes - previous.bytes) / span * 86_400)
    if not deltas:
        return {
            "status": "UNKNOWN",
            "reason": "fewer than two usable samples",
            "bytes_per_day": None,
            "samples": len(ordered),
            "since": after,
            "discarded_samples": discarded,
        }
    mean = sum(deltas) / len(deltas)
    variance = sum((item - mean) ** 2 for item in deltas) / len(deltas)
    deviation = variance**0.5
    if mean <= 0:
        # No growth — but only call it stationary if it really is flat.  A tree
        # that jumped up and back down has a mean of zero and is not stable.
        flat = deviation <= abs(mean) or deviation == 0
        return {
            "status": "STATIONARY" if flat else "VOLATILE",
            "bytes_per_day": 0.0 if flat else None,
            "mean_bytes_per_day": round(mean, 3),
            "stddev_bytes_per_day": round(deviation, 3),
            "samples": len(ordered),
            "since": after,
            "discarded_samples": discarded,
            "interval_seconds": intervals,
        }
    coefficient = deviation / mean if mean else None
    stable = coefficient is not None and coefficient <= max_coefficient_of_variation
    return {
        "status": "MEASURED" if stable else "VOLATILE",
        "bytes_per_day": round(mean, 3) if stable else None,
        "mean_bytes_per_day": round(mean, 3),
        "stddev_bytes_per_day": round(deviation, 3),
        "coefficient_of_variation": None if coefficient is None else round(coefficient, 4),
        "samples": len(ordered),
        "since": after,
        "discarded_samples": discarded,
        "interval_seconds": intervals,
    }


def transition_event(
    *, previous_status: str | None, status: str, report: Mapping[str, Any], timestamp: int
) -> dict[str, Any] | None:
    """The event to emit when the state changes, exactly once per transition.

    ``None`` means "no transition": the same state as last cycle is *not* an event,
    which is what keeps the operational log bounded.
    """
    if previous_status == status or status == HEALTHY:
        if status == HEALTHY and previous_status not in (None, HEALTHY):
            return {
                "event": "DISK_RECOVERED",
                "status": status,
                "previous_status": previous_status,
                "timestamp": int(timestamp),
                "free_bytes": report.get("free_bytes"),
                "free_gib": report.get("free_gib"),
            }
        return None
    return {
        "event": "DISK_WARNING" if status == WARNING else "DISK_CRITICAL",
        "status": status,
        "previous_status": previous_status,
        "timestamp": int(timestamp),
        "free_bytes": report.get("free_bytes"),
        "free_gib": report.get("free_gib"),
        "warning_free_bytes": report.get("warning_free_bytes"),
        "critical_free_bytes": report.get("critical_free_bytes"),
    }


class DiskSpaceGuard:
    """Read-only view of free space, plus the one policy the campaign needs."""

    def __init__(
        self,
        path: Path,
        *,
        warning_bytes: int = HEALTHY_FREE_BYTES,
        critical_bytes: int = CRITICAL_FREE_BYTES,
    ) -> None:
        self.path = Path(path)
        self.warning_bytes = int(warning_bytes)
        self.critical_bytes = int(critical_bytes)

    def report(
        self, *, samples: Iterable[GrowthSample] = (), after: int | None = None
    ) -> dict[str, Any]:
        payload = disk_report(
            self.path, warning_bytes=self.warning_bytes, critical_bytes=self.critical_bytes
        )
        rate = growth_rate(list(samples), after=after)
        payload["growth"] = rate
        payload["estimated_days_to_warning"] = estimate_days_to_threshold(
            free_bytes=int(payload["free_bytes"]),
            threshold_bytes=self.warning_bytes,
            growth_bytes_per_day=rate.get("bytes_per_day"),
        )
        payload["estimated_days_to_critical"] = estimate_days_to_threshold(
            free_bytes=int(payload["free_bytes"]),
            threshold_bytes=self.critical_bytes,
            growth_bytes_per_day=rate.get("bytes_per_day"),
        )
        return payload

    def status(self) -> str:
        usage = shutil.disk_usage(volume_anchor(self.path))
        return _status_for(
            int(usage.free), warning_bytes=self.warning_bytes, critical_bytes=self.critical_bytes
        )

    def allows_new_decision(self) -> tuple[bool, str | None]:
        """A new sealed decision is refused only in ``CRITICAL``.

        Already-sealed decisions keep their higher integrity priority: settling and
        evaluating them is a *preservation* activity, so it is never blocked here.
        """
        if self.status() == CRITICAL:
            return False, "NO_NEW_DECISION_DISK_CRITICAL"
        return True, None
