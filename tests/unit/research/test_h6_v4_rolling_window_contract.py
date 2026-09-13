"""H6 V4 — the rolling window must be the FROZEN window, not "whatever was passed".

Defect this file pins (found while building the PIT gate): the engine enforced only the
observation MINIMUM (``min_observations`` = 336) and ``build_feature_state`` derived the
hour range from ``len(observations) // 12 + 2``.  Nothing enforced the preregistered
``length_hours`` = 720, so a caller handing over more history silently changed the
statistic: ``prepare_decision_from_data_root`` passes the entire causal store, which made
median/MAD -- and therefore robust_z and the signal -- a function of how much history
existed rather than of the frozen 720-hour trailing window.

No economics: these tests assert window/feature geometry only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_bot.research.h6.contracts import SignalDirection
from trading_bot.research.h6.feature_engine import (
    CompletedHourPrice,
    frozen_rolling_window,
)
from trading_bot.research.h6.frozen_contract_snapshot import load_frozen_h6_snapshot
from trading_bot.research.h6.preparation import prepare_decision

T0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
STEP_MS = 300_000
HOUR_MS = 3_600_000
SYMBOL = "BTCUSDT"


def _hourly_delta(h: int) -> float:
    """Deterministic, varying hourly OI change so MAD > 0 and z is well defined."""
    return 12.0 + 3.0 * ((h % 7) - 3)


def _rows(hours: int) -> tuple[list[dict], datetime]:
    """``hours`` completed hours of 5m snapshots, plus the decision time after them.

    Hour ``h`` spans ``[T0 + h, T0 + h + 1)`` and closes at ``T0 + h + 1`` with OI level
    ``levels[h]``, so the realised hourly change is exactly ``_hourly_delta(h)``.
    """
    levels = [1000.0]
    for h in range(1, hours + 1):
        levels.append(levels[-1] + _hourly_delta(h))
    rows: list[dict] = []
    for h in range(hours):
        for k in range(12):
            ts = int((T0 + timedelta(hours=h)).timestamp() * 1000) + k * STEP_MS
            rows.append(
                {
                    "timestamp_ms": ts,
                    "sum_open_interest": levels[h],
                    "sum_open_interest_value": levels[h] * 10.0,
                    "source_file": "synthetic",
                    "source_sha256": "0" * 64,
                    "unit_semantics": "synthetic",
                }
            )
    return rows, T0 + timedelta(hours=hours)


def _decide(rows: list[dict], at: datetime):
    return prepare_decision(
        rows,
        symbol=SYMBOL,
        decision_time=at,
        price=CompletedHourPrice(bucket_close_time=at, open=100.0, close=101.0),
    )


def test_window_length_is_read_from_the_frozen_spec() -> None:
    spec = load_frozen_h6_snapshot()
    window_hours, min_observations = frozen_rolling_window()
    assert window_hours == spec.rolling_window_length_hours == 720
    assert min_observations == spec.rolling_min_observations
    assert window_hours != min_observations


def test_window_is_capped_at_the_frozen_length_despite_longer_history() -> None:
    rows, at = _rows(2000)
    decision = _decide(rows, at)
    assert decision.rolling_changes == 720
    assert decision.feature_state.decision_eligible is True


def test_old_history_outside_the_window_cannot_move_the_decision() -> None:
    rows, at = _rows(2000)
    base = _decide(rows, at)

    mutated = [dict(r) for r in rows]
    for r in mutated[:120]:  # the oldest ~10 hours, far outside the 720 h window
        r["sum_open_interest"] = float(r["sum_open_interest"]) * 7.0
        r["sum_open_interest_value"] = float(r["sum_open_interest_value"]) * 7.0
    after = _decide(mutated, at)

    assert after.feature_state.to_dict() == base.feature_state.to_dict()
    assert after.signal.to_dict() == base.signal.to_dict()


def test_decision_equals_the_trailing_window_only_call() -> None:
    rows, at = _rows(2000)
    full = _decide(rows, at)

    # keep only the trailing 722 hours of rows: the same window the full call may use
    keep_from = int((at - timedelta(hours=722)).timestamp() * 1000)
    trailing = [r for r in rows if r["timestamp_ms"] >= keep_from]
    assert 0 < len(trailing) < len(rows)
    limited = _decide(trailing, at)

    assert limited.rolling_changes == full.rolling_changes == 720
    assert limited.feature_state.to_dict() == full.feature_state.to_dict()
    assert limited.signal.to_dict() == full.signal.to_dict()


def test_minimum_observations_is_still_enforced_below_the_window() -> None:
    rows, at = _rows(200)
    decision = _decide(rows, at)
    min_observations = frozen_rolling_window()[1]
    assert decision.rolling_changes < min_observations
    assert decision.feature_state.decision_eligible is False
    assert decision.signal.direction == SignalDirection.NO_TRADE


def test_short_history_is_not_padded_with_fabricated_hours() -> None:
    """A history shorter than the window must not be padded with zero-level hours.

    If the aggregation were materialised over the full 720 h window regardless of the
    data, hours with no observations would enter the series as OI level 0.0 and inject a
    large spurious delta right where the data begins.
    """
    rows, at = _rows(400)
    decision = _decide(rows, at)
    # 400 completed hours of rows, min the one closing exactly at the decision time
    assert decision.rolling_changes == 398
    assert decision.feature_state.rolling_mad_delta_oi > 0.0
    assert decision.feature_state.decision_eligible is True


def test_window_holds_only_strictly_trailing_completed_hours() -> None:
    rows, at = _rows(800)
    decision = _decide(rows, at)
    # 800 hours of rows close at T0+1h .. T0+800h; T0+800h closes exactly at the
    # decision time and is therefore excluded, leaving 799 hours -> 798 changes, which
    # the 720 cap then trims to exactly 720.
    assert decision.rolling_changes == 720
    assert decision.current_hour_oi.snapshot_count == 12
    assert decision.previous_hour_oi is not None
    assert decision.previous_hour_oi.snapshot_count == 12
