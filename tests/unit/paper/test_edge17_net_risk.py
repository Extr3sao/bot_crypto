"""WP-EDGE-017/P0.3 — the cost is inside the book before risk reads the result.

WP-EDGE-016 ran the lane with ``commission_bps=0, slippage_bps=0`` and
subtracted the venue cost from a report afterwards. RiskManager therefore
approved 146 trades against a frictionless -53.38 USDT while the same fills cost
-239.75 USDT net. These tests pin the fix to the objects that make the decision:
the broker charges, the closed trade reconstructs its own net, and the engine's
equity — which every gate and the sizing read — is the net one.
"""

from __future__ import annotations

import pytest

from trading_bot.config.risk import DefensiveBlocks, Risk
from trading_bot.paper.broker import BrokerCost, ClosedTrade, PaperBroker
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

POLICY = Risk(
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
    blocks=DefensiveBlocks(),
)


def _signal(price: float = 100.0, *, notional: float = 500.0) -> Signal:
    return Signal(
        symbol="BTC/USDT",
        side="buy",
        strategy_name="test",
        timeframe="1h",
        confidence=1.0,
        price=price,
        stop_loss_pct=0.5,
        take_profit_pct=0.75,
        metadata={"notional_usdt": notional},
    )


def _broker(**kwargs: object) -> PaperBroker:
    return PaperBroker(equity=10_000.0, book_id="TESTBOOK", clock=lambda: 1.0, **kwargs)  # type: ignore[arg-type]


# -- the broker charges, and says what it charged ---------------------------------------


def test_commission_spread_and_slippage_move_the_fill_and_the_pnl() -> None:
    broker = _broker(commission_bps=10.0, spread_bps=4.0, slippage_bps=2.0)
    position = broker.execute_signal(_signal(100.0))
    assert position is not None

    # a buy pays half the spread plus slippage on the way in
    assert position.entry_price == pytest.approx(100.0 * (1 + 4.0 / 10_000.0))
    assert position.entry_commission == pytest.approx(500.0 * 10.0 / 10_000.0)

    trade = broker._close_position("BTC/USDT", 100.0, "signal")

    # ... and on the way out, so a round trip at an unchanged price is a loss
    assert trade.reference_entry_price == pytest.approx(100.0)
    assert trade.reference_exit_price == pytest.approx(100.0)
    assert trade.reference_gross_pnl == pytest.approx(0.0)
    assert trade.execution_cost_usdt > 0
    assert trade.pnl < 0
    assert trade.pnl == pytest.approx(
        trade.reference_gross_pnl
        - trade.execution_cost_usdt
        - trade.entry_commission
        - trade.exit_commission
    )


def test_every_closed_trade_reconciles_its_net_against_named_costs() -> None:
    broker = _broker(commission_bps=10.0, spread_bps=4.0, slippage_bps=2.0)
    for index in range(5):
        broker.execute_signal(_signal(100.0 + index))
        broker._close_position("BTC/USDT", 100.4 + index, "signal")

    for trade in broker.closed_trades:
        assert trade.pnl == pytest.approx(trade.gross_pnl - trade.total_cost_usdt + trade.execution_cost_usdt)
        assert trade.pnl == pytest.approx(
            trade.reference_gross_pnl
            - trade.execution_cost_usdt
            - trade.entry_commission
            - trade.exit_commission
        )
    snapshot = broker.accounting_snapshot({"BTC/USDT": 100.0})
    assert snapshot["identities"]["closed_trade_costs_are_named"] is True
    assert snapshot["cash"] == pytest.approx(10_000.0 + snapshot["realised_pnl"])


def test_a_cost_schedule_prices_each_symbol_rather_than_one_global_bps() -> None:
    schedule = {
        "BTC/USDT": BrokerCost(commission_bps=10.0, half_spread_bps=0.2, slippage_bps=0.3),
        "SOL/USDT": BrokerCost(commission_bps=10.0, half_spread_bps=0.8, slippage_bps=1.2),
    }
    broker = _broker(cost_schedule=lambda symbol, notional: schedule[symbol])

    btc = broker.execute_signal(_signal(100.0))
    sol = broker.execute_signal(
        Signal(
            symbol="SOL/USDT",
            side="buy",
            strategy_name="test",
            timeframe="1h",
            confidence=1.0,
            price=100.0,
            stop_loss_pct=0.5,
            take_profit_pct=0.75,
            metadata={"notional_usdt": 500.0},
        )
    )
    assert btc is not None and sol is not None
    assert sol.entry_price > btc.entry_price, "the wider pair must cross a wider spread"


def test_zero_cost_configuration_is_unchanged() -> None:
    """The default broker still reproduces the old, frictionless arithmetic."""
    broker = _broker(commission_bps=0.0, slippage_bps=0.0)
    broker.execute_signal(_signal(100.0))
    trade = broker._close_position("BTC/USDT", 101.0, "take_profit")
    assert trade.pnl == pytest.approx(trade.reference_gross_pnl)
    assert trade.execution_cost_usdt == pytest.approx(0.0)
    assert trade.entry_commission == 0.0 and trade.exit_commission == 0.0


# -- risk decides on the net number -----------------------------------------------------


def test_a_gross_winner_that_is_a_net_loser_moves_the_daily_loss_gate() -> None:
    """+5 bps of price, 24 bps of round-trip cost: gross wins, net loses."""
    broker = _broker(
        commission_bps=10.0,
        cost_schedule=lambda symbol, notional: BrokerCost(
            commission_bps=10.0, half_spread_bps=1.0, slippage_bps=1.0
        ),
    )
    broker.execute_signal(_signal(100.0))
    trade = broker._close_position("BTC/USDT", 100.05, "signal")

    assert trade.reference_gross_pnl > 0, "the price move alone is a profit"
    assert trade.pnl < 0, "the book is poorer after paying for it"

    risk = RiskManager(risk=POLICY, equity=10_000.0, _clock=lambda: 1.0)
    risk.record_trade_result(trade.pnl)
    risk.mark_equity(broker.accounting_snapshot({})["equity_mark_to_market"])

    assert risk.daily_pnl == pytest.approx(trade.pnl)
    assert risk.daily_pnl < 0
    assert risk.equity == pytest.approx(10_000.0 + trade.pnl)
    assert risk.equity < 10_000.0


def test_net_equity_is_what_sizes_the_next_order() -> None:
    # a policy whose binding clamp is the exposure budget rather than the per-order
    # cap, so the size is a direct function of equity
    wide = POLICY.model_copy(update={"max_order_notional_usdt": 5_000.0, "max_asset_exposure_pct": 10.0})
    risk = RiskManager(risk=wide, equity=10_000.0, _clock=lambda: 1.0)
    before = risk.check_signal(_signal(100.0)).position_size
    assert before is not None and before.notional_usdt == pytest.approx(1_000.0)

    risk.record_trade_result(-50.0)  # a loss the gross book would not have shown
    after = risk.check_signal(_signal(100.0)).position_size
    assert after is not None
    assert risk.equity == pytest.approx(9_950.0)
    assert after.notional_usdt == pytest.approx(995.0), "10% of the *net* equity, not of 10 000"


def test_mark_equity_assigns_and_does_not_double_count() -> None:
    risk = RiskManager(risk=POLICY, equity=10_000.0, _clock=lambda: 1.0)
    risk.record_trade_result(-100.0)
    assert risk.equity == pytest.approx(9_900.0)

    risk.mark_equity(9_900.0)  # the broker's own net figure for the same moment
    assert risk.equity == pytest.approx(9_900.0), "marking must not add the loss twice"

    risk.mark_equity(10_500.0)  # unrealized leg marks the book up
    assert risk.equity == pytest.approx(10_500.0)
    assert risk.peak_equity == pytest.approx(10_500.0)
    assert risk.day_peak_equity == pytest.approx(10_500.0)


def test_the_weekly_limit_binds_on_net_losses_only() -> None:
    """The same six fills are flat gross and -720 net; only the net series blocks."""
    net_risk = RiskManager(risk=POLICY, equity=10_000.0, _clock=lambda: 1.0)
    gross_risk = RiskManager(risk=POLICY, equity=10_000.0, _clock=lambda: 1.0)
    for _ in range(6):
        net_risk.record_trade_result(-120.0)
        net_risk.reset_daily()  # keep the daily gate out of the way
        gross_risk.record_trade_result(0.0)
        gross_risk.reset_daily()

    assert net_risk.weekly_pnl == pytest.approx(-720.0)
    assert gross_risk.weekly_pnl == pytest.approx(0.0)
    blocked = net_risk.check_signal(_signal(100.0))
    assert blocked.approved is False
    assert blocked.blocked_by == "weekly_loss_limit"
    assert gross_risk.check_signal(_signal(100.0)).approved is True


def test_closed_trade_exposes_the_costs_it_paid() -> None:
    trade = ClosedTrade(
        symbol="BTC/USDT",
        side="buy",
        entry_price=100.0,
        exit_price=100.0,
        quantity=5.0,
        pnl=-1.5,
        exit_reason="signal",
        opened_at=0.0,
        closed_at=1.0,
        gross_pnl=0.5,
        entry_commission=1.0,
        exit_commission=1.0,
        execution_cost_usdt=0.5,
        reference_gross_pnl=1.0,
    )
    assert trade.total_cost_usdt == pytest.approx(2.5)
    assert trade.pnl == pytest.approx(-1.5)
