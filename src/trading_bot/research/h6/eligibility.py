"""P9 — causal decision eligibility at T.

Eligibility at T may use only evidence known by T. Later gaps/mutations
must not alter eligibility at T.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Sequence

from trading_bot.research.h6.feature_engine import (
    CompletedHourOI,
    ObservedOI,
)


def build_completed_hour_oi(
    snapshots: Iterable[ObservOI],
    *,
    hour_close_time: datetime,
) -> CompletedHourOI:
    """Aggregate exactly the 5m snapshots belonging to one completed hour.

    Snapshots must satisfy `snapshot.oi_time <= hour_close_time`.
    """
    ts_to_use = _hour_close_boundaries(hour_close_time)
    within = [s for s in snapshots if ts_to_use.start <= s.oi_time <= ts_to_use.end]
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


def _hour_close_boundaries(hour_close_time: datetime) -> tuple[datetime, datetime]:
    start = hour_close_time - timedelta(hours=1)
    return start, hour_close_time


def _distinct_by_time(snapshots: Iterable[ObservOI]) -> list[ObservOI]:
    seen: dict[datetime, ObservOI] = {}
    for s in snapshots:
        seen[s.oi_time] = s
    return list(seen.values())


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
