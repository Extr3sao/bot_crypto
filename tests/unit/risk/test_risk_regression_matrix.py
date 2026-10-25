"""Risk regression matrix — GATE STRAT-HARDEN-002 §6.

The independent verifier (STRAT-VERIFY-001) confirmed four runtime-enforced
gates by probing a live ``PaperBroker`` -> ``Runtime._sync_risk_positions`` ->
``RiskManager`` path, but found the builder had added essentially no permanent
tests (one exact-cap assertion). This module turns the verified semantics into
permanent regression coverage so a future change cannot silently re-inert them:

* ``max_asset_exposure_pct`` — the per-asset clamp (DEF-RISK-EXPOSURE-001);
* ``max_weekly_loss_pct``   — the weekly loss veto (DEF-RISK-INERT-002);
* ``max_daily_drawdown_pct``— the daily drawdown veto (DEF-RISK-INERT-002);
* ``consecutive_loss_cooldown`` — time-based, and it must LIFT (DEF-RISK-INERT-002).

Everything is exercised through the public runtime-facing surface
(``check_signal`` / ``sync_open_positions`` / ``record_trade_result`` /
``restore_state``), not private helpers, so the tests describe behaviour the
runtime actually depends on.
"""

from __future__ import annotations

import pytest

from trading_bot.config.risk import Risk
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

EQUITY = 10_000.0


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


def _mgr(**overrides) -> RiskManager:
    clock = overrides.pop("_clock", None)
    return RiskManager(risk=_risk(**overrides), equity=EQUITY, _clock=clock)


def _signal(symbol: str = "BTC/USDT") -> Signal:
    return Signal(
        symbol=symbol,
        side="buy",
        strategy_name="s",
        timeframe="5m",
        confidence=0.6,
        price=100.0,
        stop_loss_pct=0.5,
        take_profit_pct=0.75,
    )


def _pos(notional: float, *, asset: str | None = None, side: str = "long") -> dict[str, object]:
    out: dict[str, object] = {"notional_usdt": notional, "side": side}
    if asset is not None:
        out["asset"] = asset
    return out


# --------------------------------------------------------------------------- #
# Per-asset exposure clamp — DEF-RISK-EXPOSURE-001
# --------------------------------------------------------------------------- #
#
# equity 10_000, max_asset_exposure_pct 10 -> per-asset budget 1_000 USDT.
# The unclamped, risk-based notional is max_order_notional_usdt = 500.


def test_per_asset_zero_exposure_allows_the_full_order() -> None:
    mgr = _mgr()
    check = mgr.check_signal(_signal())
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == 500.0


def test_per_asset_below_cap_is_unaffected() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(400.0)})
    check = mgr.check_signal(_signal())
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == 500.0


def test_per_asset_existing_plus_new_is_clamped_to_remaining_budget() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(900.0)})
    check = mgr.check_signal(_signal())
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == pytest.approx(100.0)


def test_per_asset_exact_cap_leaves_no_room_and_blocks() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(1000.0)})
    check = mgr.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "position_sizing"


def test_per_asset_above_cap_blocks() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(1500.0)})
    check = mgr.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "position_sizing"


def test_multiple_positions_same_asset_are_summed() -> None:
    mgr = _mgr()
    mgr.sync_open_positions(
        {
            "BTC/USDT": _pos(300.0, asset="BTC"),
            "BTCUSDT-PERP": _pos(300.0, asset="BTC"),
        }
    )
    check = mgr.check_signal(_signal())
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == pytest.approx(400.0)


def test_a_different_asset_does_not_consume_the_budget() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(900.0, asset="BTC")})
    check = mgr.check_signal(_signal("ETH/USDT"))
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == 500.0


def test_same_asset_long_and_short_are_not_netted() -> None:
    mgr = _mgr()
    mgr.sync_open_positions(
        {
            "LONG": _pos(400.0, asset="BTC", side="long"),
            "SHORT": _pos(400.0, asset="BTC", side="short"),
        }
    )
    check = mgr.check_signal(_signal())
    # 800 consumed -> 200 remaining; netting would have left 1_000 -> 500.
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == pytest.approx(200.0)


def test_missing_book_is_reported_as_zero_exposure() -> None:
    """No synchronised book -> the clamp sees zero (the pre-hot-wire default)."""
    mgr = _mgr()
    assert mgr.exposure_by_asset() == {}
    check = mgr.check_signal(_signal())
    assert check.approved


def test_book_sync_is_adopted_and_replaces_the_previous_book() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(900.0)})
    assert mgr.exposure_by_asset()["BTC"] == pytest.approx(900.0)
    # A fresh sync (stale-book refresh) replaces, not accumulates.
    mgr.sync_open_positions({"BTC/USDT": _pos(100.0)})
    assert mgr.exposure_by_asset()["BTC"] == pytest.approx(100.0)


def test_restart_restores_the_book_so_the_clamp_still_sees_it() -> None:
    """A restart must not resurrect pre-restart exposure into the void."""
    mgr = _mgr()
    mgr.restore_state(
        daily_pnl=0.0,
        weekly_pnl=0.0,
        trades_today=0,
        consecutive_losses=0,
        peak_equity=EQUITY,
        open_positions={"BTC/USDT": _pos(900.0)},
        kill_switch_active=False,
    )
    check = mgr.check_signal(_signal())
    assert check.approved
    assert check.position_size is not None
    assert check.position_size.notional_usdt == pytest.approx(100.0)


# --------------------------------------------------------------------------- #
# Weekly loss veto — DEF-RISK-INERT-002
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("weekly_pnl", "blocked"),
    [
        (0.0, False),
        (-299.99, False),
        (-300.0, True),
        (-450.0, True),
    ],
)
def test_weekly_loss_limit_boundary(weekly_pnl: float, blocked: bool) -> None:
    mgr = _mgr()
    mgr.weekly_pnl = weekly_pnl
    check = mgr.check_signal(_signal())
    if blocked:
        assert not check.approved
        assert check.blocked_by == "weekly_loss_limit"
    else:
        assert check.approved


# --------------------------------------------------------------------------- #
# Daily drawdown veto — DEF-RISK-INERT-002
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("equity", "blocked"),
    [
        (10_000.0, False),  # 0 %
        (9_800.01, False),  # just under 2 %
        (9_800.0, True),  # exactly 2 %
        (9_700.0, True),  # 3 %
    ],
)
def test_daily_drawdown_boundary(equity: float, blocked: bool) -> None:
    mgr = _mgr()
    mgr.day_peak_equity = 10_000.0
    mgr.equity = equity
    check = mgr.check_signal(_signal())
    if blocked:
        assert not check.approved
        assert check.blocked_by in {"daily_drawdown", "max_drawdown"}
    else:
        assert check.approved


# --------------------------------------------------------------------------- #
# Consecutive-loss cooldown — DEF-RISK-INERT-002
# --------------------------------------------------------------------------- #


def test_consecutive_loss_cooldown_blocks_then_lifts() -> None:
    now = {"t": 1_000_000.0}
    mgr = _mgr(_clock=lambda: now["t"])
    for _ in range(3):
        mgr.record_trade_result(-10.0)
    assert mgr.consecutive_losses == 3

    # Immediately after the last loss: blocked.
    check = mgr.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "consecutive_loss_cooldown"

    # 59 minutes later: still blocked.
    now["t"] += 59 * 60
    check = mgr.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "consecutive_loss_cooldown"

    # 120 minutes later: the cooldown has lifted (the position cap is clean).
    now["t"] += 61 * 60
    check = mgr.check_signal(_signal())
    assert check.approved


def test_consecutive_loss_cooldown_zero_is_a_permanent_block() -> None:
    mgr = _mgr(consecutive_loss_cooldown_minutes=0, _clock=lambda: 1_000_000.0)
    for _ in range(3):
        mgr.record_trade_result(-10.0)
    check = mgr.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "consecutive_loss_cooldown"


def test_a_winning_trade_clears_the_loss_streak() -> None:
    mgr = _mgr()
    for _ in range(3):
        mgr.record_trade_result(-10.0)
    assert mgr.consecutive_losses == 3
    mgr.record_trade_result(50.0)
    assert mgr.consecutive_losses == 0
    check = mgr.check_signal(_signal())
    assert check.approved


# --------------------------------------------------------------------------- #
# Cross-cutting: the clamp and the loss vetoes compose
# --------------------------------------------------------------------------- #


def test_risk_remains_the_final_veto_after_a_full_book() -> None:
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(1000.0)})
    check = mgr.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "position_sizing"


# --------------------------------------------------------------------------- #
# The book survives a state round-trip — DEF-VERIFY-011
# --------------------------------------------------------------------------- #


def test_extract_state_carries_the_real_open_book() -> None:
    # DEF-VERIFY-011: extract_state used to hardcode ``open_positions: {}`` so a
    # restore rebuilt an empty book and the exposure clamps were blind.
    mgr = _mgr()
    mgr.sync_open_positions({"BTC/USDT": _pos(1000.0, asset="BTC")})
    state = mgr.extract_state()
    assert state["open_positions"], "extract_state dropped the open book"
    row = state["open_positions"]["BTC/USDT"]
    assert row["notional_usdt"] == 1000.0
    assert row["asset"] == "BTC"


def test_a_restored_book_still_enforces_the_per_asset_clamp() -> None:
    source = _mgr()
    source.sync_open_positions({"BTC/USDT": _pos(1000.0, asset="BTC")})
    state = source.extract_state()

    restored = _mgr()
    restored.restore_state(**state)
    assert set(restored.open_positions) == {"BTC/USDT"}
    check = restored.check_signal(_signal())
    assert not check.approved
    assert check.blocked_by == "position_sizing"


def test_an_empty_book_still_extracts_as_empty() -> None:
    state = _mgr().extract_state()
    assert state["open_positions"] == {}
    # round-trips cleanly: a fresh manager restores to an empty book
    fresh = _mgr()
    fresh.restore_state(**state)
    assert fresh.open_positions == {}
