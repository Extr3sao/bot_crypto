"""H6 V4 — completed-hour aggregation contract (section 15 / 16).

V3-FEATURE-001: ``_hour_close_boundaries`` returned a bare tuple while the caller read
``.start`` / ``.end``, so ``build_completed_hour_oi`` raised ``AttributeError`` for any
non-empty snapshot list.

V3-FEATURE-002: inclusive bounds produced 13 grid points for an hour on a 5-minute grid
aligned to :00 instead of the required 12.

The frozen contract for a completed hour ending at T is the half-open window
``[T - 1h, T)``: the snapshot stamped exactly at T belongs to the NEXT hour.

No economics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_bot.research.h6.eligibility import (
    HourWindow,
    _hour_close_boundaries,
    build_completed_hour_oi,
    completed_hour_oi_window,
)
from trading_bot.research.h6.feature_engine import ObservedOI

T = datetime(2024, 6, 5, 12, 0, tzinfo=timezone.utc)


def snapshots(*, count: int, last: datetime, value_base: float = 1000.0, step_min: int = 5) -> list[ObservedOI]:
    """``count`` snapshots ending at ``last`` (inclusive), spaced ``step_min`` apart."""
    return [
        ObservedOI(
            oi_time=last - timedelta(minutes=step_min * i),
            sum_open_interest=value_base + i,
            sum_open_interest_value=(value_base + i) * 50,
        )
        for i in range(count)
    ]


def hour_grid_ending_at(t: datetime) -> list[ObservedOI]:
    """Exactly the 12 frozen 5m stamps of ``[t - 1h, t)``."""
    return [
        ObservedOI(
            oi_time=t - timedelta(minutes=5 * (i + 1)),
            sum_open_interest=1000.0 + i,
            sum_open_interest_value=(1000.0 + i) * 50,
        )
        for i in range(12)
    ]


# ---------------------------------------------------------------- window shape


def test_window_is_half_open_and_one_hour() -> None:
    w = _hour_close_boundaries(T)
    assert isinstance(w, HourWindow)
    assert w.start == T - timedelta(hours=1)
    assert w.end == T
    assert w.seconds == 3600.0


def test_window_membership_excludes_the_close_stamp() -> None:
    w = _hour_close_boundaries(T)
    assert w.contains(T - timedelta(hours=1)) is True   # left edge included
    assert w.contains(T - timedelta(microseconds=1)) is True
    assert w.contains(T) is False                        # right edge excluded
    assert w.contains(T + timedelta(minutes=5)) is False


def test_invalid_window_rejected() -> None:
    with pytest.raises(ValueError):
        HourWindow(start=T, end=T)
    with pytest.raises(ValueError):
        HourWindow(start=T, end=T - timedelta(hours=1))


# ---------------------------------------------------------------- 12 valid


def test_twelve_valid_snapshots_are_eligible_and_non_empty_input_does_not_crash() -> None:
    """V3-FEATURE-001 regression guard: non-empty input must not raise."""
    agg = build_completed_hour_oi(hour_grid_ending_at(T), hour_close_time=T)
    assert agg.snapshot_count == 12
    assert agg.hour_close_time == T
    # last snapshot of [T-1h, T) is the T-5m stamp
    assert agg.oi_last_snapshot == 1000.0


def test_twelve_returns_exactly_twelve_retained_snapshots() -> None:
    agg, retained = completed_hour_oi_window(hour_grid_ending_at(T), hour_close_time=T)
    assert agg.snapshot_count == 12
    assert len(retained) == 12
    assert all(T - timedelta(hours=1) <= s.oi_time < T for s in retained)


# ---------------------------------------------------------------- 11 incomplete


def test_eleven_snapshots_are_incomplete() -> None:
    agg = build_completed_hour_oi(hour_grid_ending_at(T)[:-1], hour_close_time=T)
    assert agg.snapshot_count == 11


def test_empty_input_does_not_crash() -> None:
    agg = build_completed_hour_oi([], hour_close_time=T)
    assert agg.snapshot_count == 0


# ---------------------------------------------------------------- 13 snapshots


def test_thirteen_including_t_excludes_t_deterministically() -> None:
    """A grid that improperly also supplies the stamp at T must still yield 12.

    V3-FEATURE-002 regression guard: inclusive bounds would give 13.
    """
    with_close_stamp = hour_grid_ending_at(T) + [
        ObservedOI(
            oi_time=T,
            sum_open_interest=99999.0,
            sum_open_interest_value=99999.0 * 50,
        )
    ]
    agg = build_completed_hour_oi(with_close_stamp, hour_close_time=T)
    assert agg.snapshot_count == 12
    assert agg.oi_last_snapshot == 1000.0  # the T stamp did NOT influence the aggregate

    agg2, retained = completed_hour_oi_window(with_close_stamp, hour_close_time=T)
    assert agg2.snapshot_count == 12
    assert all(s.oi_time < T for s in retained)


def test_snapshot_exactly_t_is_classified_into_the_next_hour() -> None:
    rows = [
        ObservedOI(oi_time=T, sum_open_interest=7777.0, sum_open_interest_value=0.0),
        ObservedOI(oi_time=T - timedelta(minutes=5), sum_open_interest=111.0, sum_open_interest_value=0.0),
    ]
    # the T stamp belongs to the NEXT hour, not to the hour that closes at T
    assert build_completed_hour_oi(rows, hour_close_time=T).oi_last_snapshot == 111.0
    # and IS the last stamp of the hour that closes at T+1h
    assert build_completed_hour_oi(rows, hour_close_time=T + timedelta(hours=1)).oi_last_snapshot == 7777.0


# ---------------------------------------------------------------- duplicates


def test_duplicate_timestamp_same_value_is_deduplicated() -> None:
    rows = hour_grid_ending_at(T) + [
        ObservedOI(
            oi_time=T - timedelta(minutes=5),
            sum_open_interest=1000.0,
            sum_open_interest_value=1000.0 * 50,
        )
    ]
    agg = build_completed_hour_oi(rows, hour_close_time=T)
    assert agg.snapshot_count == 12  # duplicate collapses, does not inflate to 13


def test_conflicting_duplicate_timestamp_fails_closed() -> None:
    rows = hour_grid_ending_at(T) + [
        ObservedOI(
            oi_time=T - timedelta(minutes=5),
            sum_open_interest=424242.0,  # conflicting payload for a stamp already present
            sum_open_interest_value=1.0,
        )
    ]
    with pytest.raises(ValueError):
        build_completed_hour_oi(rows, hour_close_time=T)


# ---------------------------------------------------------------- future


def test_future_snapshots_are_invisible() -> None:
    rows = hour_grid_ending_at(T) + [
        ObservedOI(
            oi_time=T + timedelta(minutes=5),
            sum_open_interest=88888.0,
            sum_open_interest_value=0.0,
        )
    ]
    agg = build_completed_hour_oi(rows, hour_close_time=T)
    assert agg.snapshot_count == 12
    assert agg.oi_last_snapshot == 1000.0


def test_boundaries_helper_and_builder_agree() -> None:
    w = _hour_close_boundaries(T)
    assert w.as_tuple() == (T - timedelta(hours=1), T)
    assert build_completed_hour_oi(hour_grid_ending_at(T), hour_close_time=T).snapshot_count == 12
