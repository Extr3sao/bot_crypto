"""WP-EDGE-017F/P0.1 — the weekly loss window must actually roll over.

``RiskManager.record_trade_result`` accumulated ``weekly_pnl`` and nothing ever
reset it: ``reset_daily`` deliberately did not, and no week boundary existed, so
one bad week vetoed every signal for the rest of the run. These tests pin the
window to UTC Monday 00:00 (the ISO week the reports already use), drive it with
the injectable clock so the replay keeps causal timestamps, and cover the cases
the brief names: Monday, Sunday, a weekend with no trades, data gaps and a
restart from durable state.

They are written against the public surface the runtime uses
(``record_trade_result`` / ``reset_daily`` / ``check_signal`` /
``extract_state`` / ``restore_state``), never against a private helper.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.config.risk import Risk
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

EQUITY = 10_000.0
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


def _at(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Epoch milliseconds for a UTC instant, written as a calendar date."""
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp() * 1000)


#: 2026-10-12 is a Monday; 2026-10-11 the Sunday before it.
MONDAY = _at(2026, 10, 12)
SUNDAY_LATE = MONDAY - HOUR_MS
SUNDAY_EARLIER = MONDAY - 26 * HOUR_MS


def _risk(**overrides: float) -> Risk:
    base = dict(
        max_risk_per_trade_pct=0.25,
        max_daily_loss_pct=1.0,
        max_weekly_loss_pct=3.0,
        max_daily_drawdown_pct=2.0,
        max_total_drawdown_pct=5.0,
        max_open_positions=3,
        max_trades_per_day=20,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=10,
        max_total_exposure_pct=25,
        min_order_notional_usdt=20,
        max_order_notional_usdt=500,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=0.75,
    )
    base.update(overrides)
    return Risk(**base)


class Clock:
    """A mutable injectable clock: the replay sets it to the bar's timestamp."""

    def __init__(self, now_ms: int) -> None:
        self.now_ms = now_ms

    def __call__(self) -> float:
        return self.now_ms / 1000.0

    def set(self, now_ms: int) -> None:
        self.now_ms = now_ms


def _mgr(clock: Clock, **overrides: float) -> RiskManager:
    return RiskManager(risk=_risk(**overrides), equity=EQUITY, _clock=clock)


def _signal(symbol: str = "BTC/USDT") -> Signal:
    return Signal(
        symbol=symbol,
        side="buy",
        strategy_name="weekly-window-test",
        timeframe="5m",
        confidence=0.6,
        price=100.0,
        stop_loss_pct=0.5,
        take_profit_pct=0.75,
    )


# -- the boundary itself ------------------------------------------------------


def test_a_new_week_clears_the_weekly_accumulator() -> None:
    clock = Clock(SUNDAY_LATE)
    mgr = _mgr(clock)
    mgr.record_trade_result(-100.0)
    assert mgr.weekly_pnl == pytest.approx(-100.0)

    clock.set(MONDAY + 30 * 60_000)  # Monday 00:30 UTC
    mgr.reset_daily()  # the day boundary the replay applies at midnight
    mgr.record_trade_result(-1.0)

    assert mgr.weekly_pnl == pytest.approx(-1.0), "last week's loss must not carry over"
    assert mgr.daily_pnl == pytest.approx(-1.0)


def test_the_week_still_accumulates_on_sunday() -> None:
    clock = Clock(SUNDAY_EARLIER)
    mgr = _mgr(clock)
    mgr.record_trade_result(-100.0)
    clock.set(SUNDAY_LATE)
    mgr.record_trade_result(-50.0)
    assert mgr.weekly_pnl == pytest.approx(-150.0)


def test_the_boundary_is_monday_midnight_utc_not_sunday_midnight() -> None:
    clock = Clock(MONDAY - 1)  # Sunday 23:59:59.999
    mgr = _mgr(clock)
    mgr.record_trade_result(-100.0)
    clock.set(MONDAY)  # exactly Monday 00:00:00
    mgr.record_trade_result(-1.0)
    assert mgr.weekly_pnl == pytest.approx(-1.0)


def test_a_new_week_lifts_the_veto_before_any_trade() -> None:
    """Monday's first decision must not be judged by last week's loss."""
    clock = Clock(SUNDAY_LATE)
    # a 10% daily ceiling keeps the daily rule from masking the weekly one
    mgr = _mgr(clock, max_daily_loss_pct=10.0)
    mgr.record_trade_result(-400.0)  # 4% of equity: over the 3% weekly limit
    blocked = mgr.check_signal(_signal())
    assert blocked.approved is False
    assert blocked.blocked_by == "weekly_loss_limit"

    clock.set(MONDAY + 60_000)
    mgr.reset_daily()  # the daily veto from Sunday must not mask the weekly roll
    check = mgr.check_signal(_signal())

    assert check.approved is True, "the weekly veto must lift at the week boundary"


def test_a_weekend_without_trades_is_rolled_by_the_daily_reset() -> None:
    clock = Clock(_at(2026, 10, 9, 15))  # Friday
    mgr = _mgr(clock)
    mgr.record_trade_result(-200.0)
    assert mgr.weekly_pnl == pytest.approx(-200.0)

    clock.set(MONDAY)  # no trades all weekend; the day boundary runs first
    mgr.reset_daily()

    assert mgr.weekly_pnl == pytest.approx(0.0)
    assert mgr.trades_today == 0
    assert mgr.daily_pnl == pytest.approx(0.0)


def test_a_data_gap_of_several_weeks_clears_once_and_is_not_replayed() -> None:
    clock = Clock(_at(2026, 9, 21, 12))
    mgr = _mgr(clock)
    mgr.record_trade_result(-250.0)

    clock.set(_at(2026, 10, 14, 12))  # more than three weeks later
    mgr.record_trade_result(-10.0)

    assert mgr.weekly_pnl == pytest.approx(-10.0)
    assert mgr.weekly_start_ms == _at(2026, 10, 12)


def test_the_new_week_can_still_reach_its_own_limit() -> None:
    clock = Clock(MONDAY + HOUR_MS)
    # the daily rule is already proven elsewhere; isolate the weekly one here
    mgr = _mgr(clock, max_daily_loss_pct=10.0)
    mgr.record_trade_result(-301.0)  # 3.01% inside the new week
    check = mgr.check_signal(_signal())
    assert check.approved is False
    assert check.blocked_by == "weekly_loss_limit"


# -- persistence across a restart --------------------------------------------


def test_the_week_anchor_is_part_of_the_durable_state() -> None:
    clock = Clock(MONDAY + HOUR_MS)
    mgr = _mgr(clock)
    mgr.record_trade_result(-120.0)

    state = mgr.extract_state()

    assert state["weekly_start_ms"] == MONDAY
    assert state["weekly_pnl"] == pytest.approx(-120.0)


def test_a_restart_inside_the_same_week_keeps_the_accumulator() -> None:
    clock = Clock(MONDAY + HOUR_MS)
    mgr = _mgr(clock)
    mgr.record_trade_result(-120.0)
    state = mgr.extract_state()

    restarted_clock = Clock(MONDAY + 2 * HOUR_MS)
    restarted = _mgr(restarted_clock)
    restarted.restore_state(
        daily_pnl=float(state["daily_pnl"]),
        weekly_pnl=float(state["weekly_pnl"]),
        trades_today=int(state["trades_today"]),
        consecutive_losses=int(state["consecutive_losses"]),
        peak_equity=float(state["peak_equity"]),
        open_positions={},
        kill_switch_active=False,
        day_peak_equity=float(state["day_peak_equity"]),
        last_loss_ms=int(state["last_loss_ms"]),
        weekly_start_ms=int(state["weekly_start_ms"]),
    )

    assert restarted.weekly_pnl == pytest.approx(-120.0)
    restarted.reset_daily()  # the restored daily loss belongs to yesterday
    assert restarted.weekly_pnl == pytest.approx(-120.0), "a new day is not a new week"
    assert restarted.check_signal(_signal()).approved is True


def test_a_restart_in_a_later_week_clears_the_accumulator() -> None:
    clock = Clock(MONDAY + HOUR_MS)
    mgr = _mgr(clock)
    mgr.record_trade_result(-400.0)
    state = mgr.extract_state()

    restarted_clock = Clock(MONDAY + 7 * DAY_MS + HOUR_MS)  # next Monday
    restarted = _mgr(restarted_clock)
    restarted.restore_state(
        daily_pnl=0.0,
        weekly_pnl=float(state["weekly_pnl"]),
        trades_today=0,
        consecutive_losses=0,
        peak_equity=float(state["peak_equity"]),
        open_positions={},
        kill_switch_active=False,
        weekly_start_ms=int(state["weekly_start_ms"]),
    )

    assert restarted.weekly_pnl == pytest.approx(0.0)
    assert restarted.check_signal(_signal()).approved is True


def test_a_legacy_snapshot_without_a_week_anchor_rolls_on_the_next_week() -> None:
    """Snapshots written before this fix carry no anchor.

    They must not be able to veto forever: the anchor defaults to the week the
    restore happens in, and the accumulator clears at the next boundary.
    """
    clock = Clock(MONDAY + HOUR_MS)
    mgr = _mgr(clock)
    mgr.restore_state(
        daily_pnl=0.0,
        weekly_pnl=-400.0,
        trades_today=0,
        consecutive_losses=0,
        peak_equity=EQUITY,
        open_positions={},
        kill_switch_active=False,
    )
    assert mgr.weekly_pnl == pytest.approx(-400.0), "do not silently forgive a legacy loss"

    clock.set(MONDAY + 7 * DAY_MS)
    mgr.check_signal(_signal())
    assert mgr.weekly_pnl == pytest.approx(0.0)


def test_the_clock_never_moves_backwards_into_a_reset() -> None:
    """A restore with an earlier timestamp must not clear this week's loss."""
    clock = Clock(MONDAY + 2 * DAY_MS)
    mgr = _mgr(clock)
    mgr.record_trade_result(-90.0)

    clock.set(MONDAY + DAY_MS)  # backwards, e.g. a skewed clock on restart
    mgr.record_trade_result(-10.0)

    assert mgr.weekly_pnl == pytest.approx(-100.0)


def test_daily_limits_are_untouched_by_the_week_roll() -> None:
    clock = Clock(_at(2026, 10, 9, 20))  # Friday
    mgr = _mgr(clock)
    mgr.record_trade_result(-101.0)  # 1.01% of equity: over the daily limit
    assert mgr.check_signal(_signal()).blocked_by == "daily_loss_limit"

    clock.set(_at(2026, 10, 10, 0))  # Saturday, same week
    mgr.reset_daily()
    assert mgr.weekly_pnl == pytest.approx(-101.0), "the weekly window did not move"
    assert mgr.check_signal(_signal()).approved is True


def test_an_iso_week_is_seven_days_in_utc() -> None:
    clock = Clock(MONDAY)
    mgr = _mgr(clock)
    assert mgr.weekly_start_ms == MONDAY
    start = datetime.fromtimestamp(mgr.weekly_start_ms / 1000, tz=UTC)
    assert start.weekday() == 0  # Monday
    assert start.hour == 0 and start.minute == 0
    assert timedelta(days=7) == timedelta(seconds=7 * 86_400)
