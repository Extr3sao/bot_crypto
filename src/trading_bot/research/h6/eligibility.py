"""P9 — causal decision eligibility at T.

Eligibility at T may use only evidence known by T. Later gaps/mutations
must not alter eligibility at T.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from trading_bot.research.h6.feature_engine import (
    CompletedHourOI,
    ObservedOI,
)


@dataclass(frozen=True, slots=True)
class HourWindow:
    """Half-open completed-hour window ``[start, end)``.

    V4 repairs V3-FEATURE-001 / V3-FEATURE-002. V3 returned a bare tuple from a
    ``_hour_close_boundaries`` helper while the caller read ``.start`` / ``.end``
    (AttributeError for every non-empty snapshot list), and used INCLUSIVE bounds
    which yield 13 grid points for an hour on a 5-minute grid aligned to :00
    instead of the required 12.

    One explicit representation, one explicit boundary rule:
    the frozen contract requires exactly 12 distinct 5m snapshots per completed
    hour, which is ``[T-1h, T)`` — the snapshot stamped exactly at T belongs to the
    NEXT hour, never to the hour it closes.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not self.end > self.start:
            raise ValueError(f"invalid hour window: start={self.start!r} end={self.end!r}")

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def contains(self, when: datetime) -> bool:
        """Half-open membership: start <= when < end."""
        return self.start <= when < self.end

    def as_tuple(self) -> tuple[datetime, datetime]:
        return self.start, self.end


def _hour_close_boundaries(hour_close_time: datetime) -> HourWindow:
    """The completed-hour window that CLOSES at ``hour_close_time``."""
    return HourWindow(start=hour_close_time - timedelta(hours=1), end=hour_close_time)


def _distinct_by_time(snapshots: Iterable[ObservedOI]) -> list[ObservedOI]:
    """Distinct snapshots by timestamp.

    A repeated timestamp with an identical payload is a harmless duplicate and
    collapses to one observation. A repeated timestamp with a *conflicting* payload
    is ambiguous provider data: the hour cannot be aggregated causally, so the
    aggregation fails closed (``ValueError``) instead of silently picking a winner.
    """
    seen: dict[datetime, ObservedOI] = {}
    for s in snapshots:
        prior = seen.get(s.oi_time)
        if prior is not None and (
            prior.sum_open_interest != s.sum_open_interest
            or prior.sum_open_interest_value != s.sum_open_interest_value
        ):
            raise ValueError(
                "conflicting duplicate 5m OI snapshot at "
                f"{s.oi_time.isoformat()} "
                f"(sum_open_interest {prior.sum_open_interest!r} vs {s.sum_open_interest!r})"
            )
        seen[s.oi_time] = s
    return list(seen.values())


def build_completed_hour_oi(
    snapshots: Iterable[ObservedOI],
    *,
    hour_close_time: datetime,
) -> CompletedHourOI:
    """Aggregate exactly the 5m snapshots belonging to one completed hour.

    Window is half-open ``[hour_close_time - 1h, hour_close_time)``. A snapshot
    stamped exactly at ``hour_close_time`` is NOT part of this hour. Snapshots
    strictly after the window are invisible.

    Non-empty input must never crash (V3-FEATURE-001).
    """
    window = _hour_close_boundaries(hour_close_time)
    within = [s for s in snapshots if window.contains(s.oi_time)]
    distinct = _distinct_by_time(within)
    if len(distinct) == 0:
        return CompletedHourOI(
            hour_close_time=hour_close_time,
            oi_last_snapshot=0.0,
            snapshot_count=0,
        )
    last = sorted(distinct, key=lambda s: s.oi_time)[-1]
    return CompletedHourOI(
        hour_close_time=hour_close_time,
        oi_last_snapshot=last.sum_open_interest,
        snapshot_count=len(distinct),
    )


def completed_hour_oi_window(
    snapshots: Iterable[ObservedOI],
    *,
    hour_close_time: datetime,
) -> tuple[CompletedHourOI, list[ObservedOI]]:
    """As ``build_completed_hour_oi`` but also returns the snapshots retained.

    Used by tests and diagnostics to prove which observations were admitted and
    which were excluded (e.g. the snapshot stamped exactly at the boundary).
    """
    window = _hour_close_boundaries(hour_close_time)
    within = [s for s in snapshots if window.contains(s.oi_time)]
    distinct = sorted(_distinct_by_time(within), key=lambda s: s.oi_time)
    if not distinct:
        return (
            CompletedHourOI(hour_close_time=hour_close_time, oi_last_snapshot=0.0, snapshot_count=0),
            [],
        )
    return (
        CompletedHourOI(
            hour_close_time=hour_close_time,
            oi_last_snapshot=distinct[-1].sum_open_interest,
            snapshot_count=len(distinct),
        ),
        distinct,
    )


def completed_hour_changes_before(
    completed_hours: Iterable[CompletedHourOI],
    *,
    strictly_before_decision_time: datetime,
) -> list[tuple[datetime, float]]:
    """Return hourly OI changes strictly before the decision time.

    Each change is keyed by its completed hour close time and uses two
    consecutive completed-hour OI aggregates.
    """
    ordered = sorted(
        [h for h in completed_hours if h.hour_close_time < strictly_before_decision_time],
        key=lambda h: h.hour_close_time,
    )
    changes: list[tuple[datetime, float]] = []
    for prev, curr in _pairwise(ordered):
        changes.append((curr.hour_close_time, curr.oi_last_snapshot - prev.oi_last_snapshot))
    return changes


def _pairwise(seq: Sequence[CompletedHourOI]) -> Iterable[tuple[CompletedHourOI, CompletedHourOI]]:
    for i in range(len(seq) - 1):
        yield seq[i], seq[i + 1]


def decision_eligibility_at_t(
    decision_time: datetime,
    current_hour_oi: CompletedHourOI,
    previous_hour_oi: CompletedHourOI | None,
    completed_hour_changes_before: Sequence[tuple[datetime, float]],
    *,
    last_observation_time: datetime | None = None,
    stale_cutoff_seconds: int = 600,
) -> tuple[bool, str]:
    """Return (eligible, reason) using only evidence known by decision_time.

    This function intentionally does NOT use ARCHIVE_DAY_VALIDITY for
    historical trading decisions. It only enforces causal safety:
    completed price bar exists, OI completeness, previous-hour
    reference, rolling history sufficiency, stale-observation guard,
    duplicate/conflict protection handled upstream.
    """
    if current_hour_oi.snapshot_count != 12:
        return False, "CURRENT_HOUR_OI_COMPLETENESS != 12"

    if previous_hour_oi is None:
        return False, "previous_hour_oi missing"

    if previous_hour_oi.snapshot_count != 12:
        return False, "PREVIOUS_HOUR_OI_COMPLETENESS != 12"

    if len(completed_hour_changes_before) < 336:
        return False, f"insufficient_rolling_history ({len(completed_hour_changes_before)} < 336)"

    if last_observation_time is not None:
        delta = (decision_time - last_observation_time).total_seconds()
        if delta > stale_cutoff_seconds:
            return False, f"stale_observation ({delta}s > {stale_cutoff_seconds}s)"

    return True, "eligible"
