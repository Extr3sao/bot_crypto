"""G1 — the risk contract the supervisor slice lands, pinned against ``main``.

The slice changes ``risk/manager.py`` and ``paper/broker.py``.  Neither the audit
nor this integration may edit a limit, a size or a leverage to make the supervisor
fit, so this module does two things and nothing else:

1. **Parity.** For every input ``main`` accepted, the sizing arithmetic must be
   bit-for-bit the same.  The reference implementation below is a literal copy of
   ``main``'s ``_compute_position_size`` (``e67194e7``), kept in the test so a
   future edit to the manager cannot quietly move the numbers both sides.
2. **The contract deltas, named.** The slice introduces three behaviours that are
   *not* arithmetic parity, and each one is asserted here rather than assumed:
   an invalid stop is refused instead of clamped, a stop shorter than the round
   trip can be refused, and the weekly veto lifts on a new UTC Monday instead of
   never.  The last is the only one that loosens anything; it is listed in
   ``RISK_CONTRACT_DELTA.md`` for the risk-manager's signature.

Nothing here is a property of the verifier: these are the manager's own outputs.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.config.risk import Risk
from trading_bot.risk.manager import RiskManager, week_start_ms_for
from trading_bot.strategies.types import Signal

EQUITY = 10_000.0
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


def _at(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1000)


MONDAY = _at(2026, 10, 12)  # a Monday, 00:00 UTC
SUNDAY_LATE = MONDAY - HOUR_MS


def _risk(**overrides) -> Risk:
    base = dict(
        max_risk_per_trade_pct=0.25,
        max_daily_loss_pct=5.0,
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


def _mgr(*, clock_ms: int = MONDAY + 9 * HOUR_MS, **overrides) -> RiskManager:
    now_s = clock_ms / 1000.0
    return RiskManager(risk=_risk(**overrides), equity=EQUITY, _clock=lambda: now_s)


def _signal(
    *,
    stop: float | None = 1.0,
    target: float | None = 2.0,
    price: float = 100.0,
    symbol: str = "BTC/USDT",
) -> Signal:
    return Signal(
        symbol=symbol,
        side="buy",
        strategy_name="g1_contract",
        timeframe="5m",
        confidence=0.9,
        price=price,
        stop_loss_pct=stop,
        take_profit_pct=target,
        metadata={"notional_usdt": 500.0},
    )


def _main_reference_notional(
    *, equity: float, risk: Risk, stop_loss_pct: float | None, price: float
) -> float | None:
    """``main``'s formula, copied verbatim from ``e67194e7``.

    Only the no-open-position branch is reproduced: the exposure clamps are
    unchanged by the slice and are covered by ``test_risk_regression_matrix.py``.
    """

    if price <= 0:
        return None
    risk_amount = equity * (risk.max_risk_per_trade_pct / 100.0)
    stop = stop_loss_pct or risk.default_stop_loss_pct
    notional = risk_amount / (stop / 100.0) if stop > 0 else risk_amount
    notional = max(risk.min_order_notional_usdt, min(notional, risk.max_order_notional_usdt))
    if notional < risk.min_order_notional_usdt:
        return None
    return notional


# ---------------------------------------------------------------------------
# 1. parity — same inputs, same money
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stop", [0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 3.5, 5.0])
@pytest.mark.parametrize("price", [0.5, 100.0, 84_000.0])
def test_sizing_is_identical_to_main_for_every_accepted_stop(stop: float, price: float) -> None:
    mgr = _mgr()
    signal = _signal(stop=stop, price=price)
    check = mgr.check_signal(signal)
    assert check.approved is True, check.reason
    size = check.position_size
    assert size is not None

    expected = _main_reference_notional(
        equity=EQUITY, risk=mgr.risk, stop_loss_pct=stop, price=price
    )
    assert expected is not None
    assert size.notional_usdt == round(expected, 2)
    assert size.quantity == pytest.approx(expected / price, rel=0, abs=1e-12)
    assert size.stop_loss_pct == stop
    assert size.take_profit_pct == 2.0
    assert size.risk_amount_usdt == round(EQUITY * 0.0025, 2)


def test_the_notional_ceiling_still_binds_exactly_where_main_bound_it() -> None:
    """A tight order-notional cap is a cap, not a suggestion — unchanged."""

    mgr = _mgr(max_order_notional_usdt=100.0)
    check = mgr.check_signal(_signal(stop=0.1))
    assert check.approved is True
    assert check.position_size is not None
    assert check.position_size.notional_usdt == 100.0
    assert check.position_size.sizing_basis == "MAX_ORDER_NOTIONAL_CLAMP"


def test_a_declared_stop_is_never_widened() -> None:
    for stop in (0.05, 0.2, 0.9, 4.0):
        check = _mgr().check_signal(_signal(stop=stop))
        assert check.approved is True, (stop, check.reason)
        resolution = check.stop_resolution
        assert resolution is not None
        assert resolution.effective_stop_pct == stop
        assert resolution.stop_distance_bps == pytest.approx(stop * 100.0)
        assert resolution.source == "SIGNAL"
        assert "unchanged" in resolution.reason


def test_money_at_stop_never_exceeds_the_risk_budget() -> None:
    for stop in (0.1, 0.5, 1.0, 3.0):
        check = _mgr().check_signal(_signal(stop=stop))
        resolution = check.stop_resolution
        assert resolution is not None
        assert resolution.risk_at_stop_usdt <= resolution.risk_budget_usdt + 1e-9
        assert resolution.risk_at_stop_usdt == pytest.approx(
            round(check.position_size.notional_usdt * stop / 100.0, 8)
        )


# ---------------------------------------------------------------------------
# 2. delta A — an unusable stop is refused, not clamped, and not defaulted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stop", [0.0, -1.0, 100.0, 150.0, float("nan"), float("inf")])
def test_an_unusable_stop_is_refused_instead_of_reaching_the_default(stop: float) -> None:
    """``main`` did ``signal.stop_loss_pct or default`` and then clamped.

    A zero was therefore *silently replaced* by the policy default, and a 150 %
    stop was clamped into the band.  Both are refusals now: the stop a strategy
    declared is either usable as declared or the trade does not happen.
    """

    mgr = _mgr()
    check = mgr.check_signal(_signal(stop=stop))
    assert check.approved is False
    assert check.blocked_by == "invalid_stop"
    assert check.position_size is None
    assert "not a usable distance" in (check.reason or "")


def test_no_stop_is_the_only_case_that_gets_the_policy_default() -> None:
    mgr = _mgr()
    check = mgr.check_signal(_signal(stop=None))
    assert check.approved is True
    resolution = check.stop_resolution
    assert resolution is not None
    assert resolution.source == "POLICY_DEFAULT"
    assert resolution.effective_stop_pct == mgr.risk.default_stop_loss_pct
    assert "policy default applied and labelled" in resolution.reason
    assert check.position_size is not None
    assert check.position_size.stop_loss_pct == mgr.risk.default_stop_loss_pct


def test_an_unusable_target_is_refused_rather_than_defaulted() -> None:
    check = _mgr().check_signal(_signal(target=0.0))
    assert check.approved is False
    assert check.blocked_by == "invalid_stop"
    assert "take_profit_pct" in (check.reason or "")


# ---------------------------------------------------------------------------
# 3. delta B — a stop shorter than its own round trip can be refused
# ---------------------------------------------------------------------------


def test_stop_inside_costs_is_reported_off_and_refused_on_request() -> None:
    # 0.30 % stop = 30 bps; the injected schedule says one round trip costs 40 bps.
    cost = lambda symbol, notional: 40.0  # noqa: E731 - a fixture, not a helper

    off = RiskManager(risk=_risk(), equity=EQUITY, _clock=lambda: MONDAY / 1000.0, cost_bps_for=cost)
    report = RiskManager(
        risk=_risk(),
        equity=EQUITY,
        _clock=lambda: MONDAY / 1000.0,
        cost_bps_for=cost,
        stop_cost_policy="REPORT",
    )
    reject = RiskManager(
        risk=_risk(),
        equity=EQUITY,
        _clock=lambda: MONDAY / 1000.0,
        cost_bps_for=cost,
        stop_cost_policy="REJECT",
    )

    # OFF keeps the historical behaviour and does not even measure.
    off_check = off.check_signal(_signal(stop=0.3))
    assert off_check.approved is True
    assert off_check.stop_resolution is not None
    assert off_check.stop_resolution.round_trip_cost_bps is None
    assert off_check.stop_resolution.stop_clears_costs is None

    # REPORT publishes the comparison and still trades.
    report_check = report.check_signal(_signal(stop=0.3))
    assert report_check.approved is True
    assert report_check.stop_resolution is not None
    assert report_check.stop_resolution.round_trip_cost_bps == 40.0
    assert report_check.stop_resolution.stop_clears_costs is False

    # REJECT refuses it, naming the two numbers.
    reject_check = reject.check_signal(_signal(stop=0.3))
    assert reject_check.approved is False
    assert reject_check.blocked_by == "stop_inside_costs"
    assert "30.00 bps" in (reject_check.reason or "")
    assert "40.00 bps" in (reject_check.reason or "")

    # A stop that does clear its costs is approved under the same policy.
    wide = reject.check_signal(_signal(stop=1.0))
    assert wide.approved is True
    assert wide.stop_resolution is not None
    assert wide.stop_resolution.stop_clears_costs is True


# ---------------------------------------------------------------------------
# 4. delta C — the weekly veto lifts on a new UTC Monday (the only loosening)
# ---------------------------------------------------------------------------


def test_the_week_starts_on_the_utc_monday_that_contains_the_instant() -> None:
    assert week_start_ms_for(MONDAY) == MONDAY
    assert week_start_ms_for(SUNDAY_LATE) == MONDAY - 7 * DAY_MS
    assert week_start_ms_for(MONDAY + 7 * DAY_MS - 1) == MONDAY
    assert week_start_ms_for(MONDAY + 7 * DAY_MS) == MONDAY + 7 * DAY_MS


def _voted_week(*, clock_ms: int = MONDAY + 9 * HOUR_MS) -> RiskManager:
    """A manager whose weekly loss already crosses the 3 % veto."""

    mgr = RiskManager(
        risk=_risk(max_daily_loss_pct=10.0, max_daily_drawdown_pct=20.0, max_total_drawdown_pct=50.0),
        equity=EQUITY,
        _clock=lambda: clock_ms / 1000.0,
    )
    mgr.record_trade_result(-350.0)  # 3.5 % of equity > 3 % weekly limit
    assert mgr.weekly_pnl == pytest.approx(-350.0)
    return mgr


def test_the_weekly_veto_holds_for_the_rest_of_its_week() -> None:
    mgr = _voted_week()
    for offset_h in (0, 1, 24, 24 * 5):
        mgr._clock = lambda hours=offset_h: (MONDAY + 9 * HOUR_MS + hours * HOUR_MS) / 1000.0  # type: ignore[method-assign]
        check = mgr.check_signal(_signal())
        assert check.approved is False, f"approved {offset_h}h after the losing trade"
        assert check.blocked_by == "weekly_loss_limit"


def test_the_weekly_veto_lifts_only_after_the_utc_monday_boundary() -> None:
    # The loss belongs to the week that opened on 2026-10-05 and closed on the 12th.
    mgr = _voted_week(clock_ms=SUNDAY_LATE)
    assert mgr.check_signal(_signal()).blocked_by == "weekly_loss_limit"

    mgr._clock = lambda: MONDAY / 1000.0  # 2026-10-12T00:00Z, a new week
    check = mgr.check_signal(_signal())
    assert check.approved is True, check.reason
    assert mgr.weekly_pnl == 0.0


def test_a_clock_that_moves_backwards_never_clears_the_week() -> None:
    mgr = _voted_week()
    mgr._clock = lambda: (MONDAY + 7 * DAY_MS) / 1000.0
    assert mgr.roll_week() is True
    assert mgr.weekly_pnl == 0.0

    mgr.record_trade_result(-350.0)
    mgr._clock = lambda: (MONDAY + 6 * DAY_MS) / 1000.0  # backwards
    assert mgr.roll_week() is False
    assert mgr.weekly_pnl == pytest.approx(-350.0)


def test_the_weekly_anchor_survives_a_state_round_trip() -> None:
    mgr = _voted_week()
    state = mgr.extract_state()
    assert state["weekly_start_ms"] == week_start_ms_for(MONDAY + 9 * HOUR_MS)

    restored = RiskManager(risk=mgr.risk, equity=EQUITY, _clock=lambda: MONDAY / 1000.0)
    restored.restore_state(
        daily_pnl=state["daily_pnl"],
        weekly_pnl=state["weekly_pnl"],
        trades_today=state["trades_today"],
        consecutive_losses=state["consecutive_losses"],
        peak_equity=state["peak_equity"],
        weekly_start_ms=state["weekly_start_ms"],
        open_positions=state["open_positions"],
        kill_switch_active=state["kill_switch_active"],
    )
    assert restored.weekly_start_ms == state["weekly_start_ms"]
    assert restored.check_signal(_signal()).blocked_by == "weekly_loss_limit"


def test_the_weekly_limit_is_still_read_from_the_same_policy_field() -> None:
    """The reset changes *when* the accumulator clears, never the threshold."""

    strict = _voted_week()
    lenient = RiskManager(
        risk=_risk(
            max_weekly_loss_pct=10.0,
            max_daily_loss_pct=10.0,
            max_daily_drawdown_pct=20.0,
            max_total_drawdown_pct=50.0,
        ),
        equity=EQUITY,
        _clock=lambda: (MONDAY + 9 * HOUR_MS) / 1000.0,
    )
    lenient.record_trade_result(-350.0)
    assert strict.check_signal(_signal()).blocked_by == "weekly_loss_limit"
    assert lenient.check_signal(_signal()).approved is True
    assert math.isclose(
        strict.risk.max_weekly_loss_pct, 3.0, rel_tol=0, abs_tol=0
    ), "the test may not silently move the threshold it is asserting"


# ---------------------------------------------------------------------------
# 5. nothing else moved: the veto order and the untouched limits
# ---------------------------------------------------------------------------


def test_the_kill_switch_still_wins_over_every_other_gate() -> None:
    mgr = _mgr()
    mgr.activate_kill_switch("test")
    check = mgr.check_signal(_signal())
    assert check.blocked_by == "kill_switch"


def test_the_week_roll_does_not_reset_the_daily_accumulator() -> None:
    mgr = _voted_week()
    mgr.reset_daily()
    daily_before = mgr.daily_pnl
    mgr._clock = lambda: (MONDAY + 7 * DAY_MS) / 1000.0
    mgr.roll_week()
    assert mgr.weekly_pnl == 0.0
    # reset_daily zeroes the daily accumulator; the point is that the roll does not
    # touch the daily one either way.
    assert mgr.daily_pnl == daily_before


def test_no_leverage_is_invented_by_the_manager() -> None:
    check = _mgr().check_signal(_signal())
    resolution = check.stop_resolution
    assert resolution is not None
    for attribute in ("leverage", "requested_leverage", "effective_leverage"):
        assert not hasattr(resolution, attribute), (
            f"{attribute} appeared on StopResolution: the manager does not size on leverage"
        )


def test_the_average_of_the_two_mondays_is_not_a_boundary() -> None:
    """Guard against an off-by-one at the exact boundary (midnight Sunday)."""

    mgr = _voted_week(clock_ms=SUNDAY_LATE)
    mgr._clock = lambda: (MONDAY - 1) / 1000.0  # 1 ms before Monday
    assert mgr.check_signal(_signal()).blocked_by == "weekly_loss_limit"
    mgr._clock = lambda: MONDAY / 1000.0  # the boundary itself
    assert mgr.check_signal(_signal()).approved is True
    assert week_start_ms_for(MONDAY - 1) == MONDAY - 7 * DAY_MS
    assert timedelta(milliseconds=week_start_ms_for(MONDAY) - (MONDAY - 7 * DAY_MS)) == timedelta(
        days=7
    )
