"""WP-STRAT-09 — bar-close evaluation cadence (DEF-FRESH-BUDGET-001).

These tests pin two things at once:

* the cadence functions place a decision just after a sealed bar's close, and
* the **freshness budget is unchanged** — the cadence keeps the decision inside
  the gate's own reckoning, it never widens the gate.

The key test rebuilds the exact WP-STRAT-08 observation (decision 194 s after a
5m close ⇒ ``decision - bar_open = 494 s > 450 s`` ⇒ ``stale_context``) and shows
the bar-close cadence lands at ``decision - bar_open = 305 s < 450 s`` ⇒ fresh,
while ``stale_threshold_for_timeframe("5m")`` still returns 450 000 ms.
"""

from __future__ import annotations

import pytest

from trading_bot.autonomous.cadence import (
    CADENCE_BAR_CLOSE,
    CADENCE_INTERVAL,
    bar_close_ms,
    max_settlement_ms,
    next_bar_close_ms,
    seconds_until_next_evaluation,
    validate_settlement,
)
from trading_bot.autonomous.pit import closed_bar_slice
from trading_bot.market_data.types import OHLCV
from trading_bot.research.router_gates import (
    DEFAULT_FRESHNESS_GRACE_BARS,
    RouterGates,
    stale_threshold_for_timeframe,
)

FIVE_MIN_MS = 5 * 60 * 1000
ONE_MIN_MS = 60 * 1000
FIFTEEN_MIN_MS = 15 * 60 * 1000


# --- grid arithmetic -------------------------------------------------------


def test_bar_close_is_the_latest_grid_point_at_or_below_now() -> None:
    # A close sits exactly on the interval grid; `bar_close_ms` never returns a
    # future close.
    assert bar_close_ms(0, FIVE_MIN_MS) == 0
    assert bar_close_ms(FIVE_MIN_MS, FIVE_MIN_MS) == FIVE_MIN_MS
    assert bar_close_ms(FIVE_MIN_MS + 1, FIVE_MIN_MS) == FIVE_MIN_MS
    assert bar_close_ms(2 * FIVE_MIN_MS - 1, FIVE_MIN_MS) == FIVE_MIN_MS


def test_next_bar_close_is_strictly_after_now() -> None:
    assert next_bar_close_ms(0, FIVE_MIN_MS) == FIVE_MIN_MS
    assert next_bar_close_ms(FIVE_MIN_MS, FIVE_MIN_MS) == 2 * FIVE_MIN_MS
    assert next_bar_close_ms(FIVE_MIN_MS + 1, FIVE_MIN_MS) == 2 * FIVE_MIN_MS


def test_seconds_until_next_evaluation_targets_close_plus_settlement() -> None:
    # 10 s after a close, the next evaluation is one interval minus 10 s, plus
    # the 5 s settlement delay.
    now = FIVE_MIN_MS + 10_000
    sleep = seconds_until_next_evaluation(now, FIVE_MIN_MS, 5.0)
    assert sleep == pytest.approx((FIVE_MIN_MS - 10_000 + 5_000) / 1000.0)


def test_seconds_until_next_evaluation_never_negative() -> None:
    # Already past the target ⇒ wake immediately (clamped at zero).
    now = FIVE_MIN_MS + 7_000
    assert seconds_until_next_evaluation(now, FIVE_MIN_MS, 5.0) >= 0.0


# --- the budget is UNCHANGED ----------------------------------------------


def test_freshness_budget_is_unchanged() -> None:
    """OLD_FRESHNESS_THRESHOLD == NEW_FRESHNESS_THRESHOLD (§12)."""
    assert DEFAULT_FRESHNESS_GRACE_BARS == 1.5
    assert stale_threshold_for_timeframe("5m") == 450_000
    assert stale_threshold_for_timeframe("1m") == 90_000
    assert stale_threshold_for_timeframe("15m") == 1_350_000


def test_settlement_ceiling_is_derived_from_the_gate_grace() -> None:
    # interval * (grace - 1): the largest delay that still lands inside budget.
    assert max_settlement_ms(FIVE_MIN_MS) == 150_000
    assert max_settlement_ms(ONE_MIN_MS) == 30_000
    assert max_settlement_ms(FIFTEEN_MIN_MS) == 450_000


# --- the cadence keeps the gate's own reckoning fresh ----------------------


def _lag_ms(decision_ms: int, bar_open_ms: int) -> int:
    return decision_ms - bar_open_ms


def test_bar_close_cadence_is_fresh_where_the_legacy_phase_was_stale() -> None:
    """Reproduce DEF-FRESH-BUDGET-001 and show the cadence fix, not a wider gate."""
    gates = RouterGates(require_confirmed=False, timeframe="5m")
    budget = gates.stale_after_ms()
    assert budget == 450_000

    close_ms = 1000 * FIVE_MIN_MS  # a bar [close-300s, close) just sealed
    bar_open_ms = close_ms - FIVE_MIN_MS

    # Observed legacy phase: 194 s after the close ⇒ 494 s behind the bar open.
    legacy_decision = close_ms + 194_000
    assert _lag_ms(legacy_decision, bar_open_ms) == 494_000
    assert _lag_ms(legacy_decision, bar_open_ms) > budget  # ⇒ stale_context

    # Bar-close cadence: 5 s after the close ⇒ 305 s behind the bar open.
    cadence_decision = close_ms + 5_000
    assert _lag_ms(cadence_decision, bar_open_ms) == 305_000
    assert _lag_ms(cadence_decision, bar_open_ms) <= budget  # ⇒ fresh


@pytest.mark.parametrize("interval_ms", [ONE_MIN_MS, FIVE_MIN_MS, FIFTEEN_MIN_MS])
@pytest.mark.parametrize("settlement", [0.0, 1.0, 5.0])
def test_cadence_decision_is_fresh_for_every_timeframe(
    interval_ms: int, settlement: float
) -> None:
    timeframe = {ONE_MIN_MS: "1m", FIVE_MIN_MS: "5m", FIFTEEN_MIN_MS: "15m"}[interval_ms]
    budget = RouterGates(require_confirmed=False, timeframe=timeframe).stale_after_ms()
    close_ms = 7 * interval_ms
    bar_open_ms = close_ms - interval_ms
    decision_ms = close_ms + int(settlement * 1000)
    assert _lag_ms(decision_ms, bar_open_ms) <= budget


# --- settlement validation -------------------------------------------------


def test_validate_settlement_accepts_a_delay_inside_the_budget() -> None:
    assert validate_settlement(FIVE_MIN_MS, 5.0) == 5_000
    assert validate_settlement(FIVE_MIN_MS, 0.0) == 0


def test_validate_settlement_rejects_a_delay_that_outruns_the_budget() -> None:
    # 150 s is the ceiling for a 5m bar; at/over it the cycle would be stale.
    with pytest.raises(ValueError, match="budget ceiling"):
        validate_settlement(FIVE_MIN_MS, 150.0)
    with pytest.raises(ValueError, match="budget ceiling"):
        validate_settlement(FIVE_MIN_MS, 200.0)


def test_validate_settlement_rejects_negative() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        validate_settlement(FIVE_MIN_MS, -1.0)


def test_cadence_constants_are_distinct() -> None:
    assert CADENCE_INTERVAL == "interval"
    assert CADENCE_BAR_CLOSE == "bar-close"


# --- PIT safety at the cadence boundary ------------------------------------


def _bar(ts: int, symbol: str = "BTC/USDT") -> OHLCV:
    return OHLCV(
        symbol=symbol, timestamp=ts, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0
    )


def test_bar_close_aligned_decision_uses_the_sealed_bar_only() -> None:
    # Bars open on the interval grid; the bar opened at 2*I seals at 3*I and only
    # then becomes usable. A cadence decision at close + 5 s must not see it.
    bars = [_bar(k * FIVE_MIN_MS) for k in range(4)]
    decision = 3 * FIVE_MIN_MS + 5_000
    usable = closed_bar_slice(bars, decision, interval_ms=FIVE_MIN_MS)
    stamps = [b.timestamp for b in usable]
    assert stamps == [0, FIVE_MIN_MS, 2 * FIVE_MIN_MS]
    assert 3 * FIVE_MIN_MS not in stamps


def test_phase_never_changes_which_bar_is_usable() -> None:
    # Cadence changes WHEN we decide, never WHAT we may use: the same sealed set
    # is returned just after a close and near the end of the bar.
    bars = [_bar(k * FIVE_MIN_MS) for k in range(5)]
    just_after = closed_bar_slice(bars, 3 * FIVE_MIN_MS + 1, interval_ms=FIVE_MIN_MS)
    almost_next = closed_bar_slice(
        bars, 3 * FIVE_MIN_MS + 299_000, interval_ms=FIVE_MIN_MS
    )
    assert [b.timestamp for b in just_after] == [b.timestamp for b in almost_next]


def test_htf_bar_is_not_exposed_by_a_shorter_cadence_decision() -> None:
    # A 1h bar opened at 0 is only available after 3_600_000 ms; a 5m-cadence
    # decision shortly after 300_000 ms must not see it (HTF PIT safety).
    hourly = [_bar(0)]
    assert closed_bar_slice(hourly, FIVE_MIN_MS + 5_000, interval_ms=3_600_000) == []
