from __future__ import annotations

import datetime

import pytest

from trading_bot.backtesting import BacktestResult, EquityPoint, Fill, Trade, build_fold_report
from trading_bot.paper import (
    build_expectation_from_backtest_result,
    build_expectation_from_fold_report,
)


def _fill(
    *,
    order_id: str,
    side: str,
    price: float,
    commission: float,
    slippage: float,
    timestamp: int,
) -> Fill:
    return Fill(
        order_id=order_id,
        symbol="BTC/USDT",
        side=side,  # type: ignore[arg-type]
        qty_filled=1.0,
        fill_price=price,
        commission=commission,
        slippage=slippage,
        timestamp=timestamp,
    )


def _trade(*, order_id: str, pnl: float, bars_held: int) -> Trade:
    return Trade(
        entry_fill=_fill(
            order_id=f"{order_id}-buy",
            side="buy",
            price=100.0,
            commission=1.0,
            slippage=0.2,
            timestamp=1_700_000_000_000,
        ),
        exit_fill=_fill(
            order_id=f"{order_id}-sell",
            side="sell",
            price=100.0 + pnl,
            commission=1.0,
            slippage=0.3,
            timestamp=1_700_000_300_000,
        ),
        pnl=pnl,
        pnl_pct=pnl / 100.0,
        bars_held=bars_held,
    )


def _backtest_result(total_trades: int) -> BacktestResult:
    trades = [_trade(order_id=f"t{i}", pnl=10.0, bars_held=2) for i in range(total_trades)]
    return BacktestResult(
        strategy_name="demo-strategy",
        symbol="BTC/USDT",
        timeframe="1h",
        start=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        end=datetime.datetime(2026, 1, 31, tzinfo=datetime.UTC),
        initial_capital=10_000.0,
        final_equity=10_250.0,
        trades=trades,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
            EquityPoint(timestamp=1_700_000_300_000, equity=10_250.0, drawdown_pct=0.1),
        ],
        metrics={
            "total_trades": float(total_trades),
            "win_rate": 0.6,
            "profit_factor": 1.2,
            "final_equity": 10_250.0,
            "max_drawdown": 0.1,
            "cagr": 0.12,
            "calmar_ratio": 1.2,
            "sharpe_ratio": 0.9,
            "sortino_ratio": 1.1,
            "avg_trade_pnl": 5.0,
            "expectancy": 5.0,
        },
    )


def test_build_expectation_from_fold_report_maps_trade_activity_to_signal_proxy() -> None:
    expectation = build_expectation_from_fold_report(
        build_fold_report(_backtest_result(4)),
        expected_median_spread_bps=6.5,
        active_snapshots_per_trade=1.5,
        min_active_ratio=0.4,
        max_scanner_errors=2,
    )
    assert expectation.expected_active_snapshots == 6
    assert expectation.expected_median_spread_bps == 6.5
    assert expectation.expected_realized_pnl == 250.0
    assert expectation.min_active_ratio == 0.4
    assert expectation.min_win_rate_closed == 0.30
    assert expectation.max_scanner_errors == 2


def test_build_expectation_from_backtest_result_uses_fold_report_bridge() -> None:
    expectation = build_expectation_from_backtest_result(
        _backtest_result(3),
        expected_median_spread_bps=4.5,
    )
    assert expectation.expected_active_snapshots == 3
    assert expectation.expected_median_spread_bps == 4.5
    assert expectation.expected_realized_pnl == 250.0


@pytest.mark.parametrize(
    ("expected_median_spread_bps", "active_snapshots_per_trade"),
    [(-1.0, 1.0), (4.0, -0.5)],
)
def test_build_expectation_validates_non_negative_inputs(
    expected_median_spread_bps: float,
    active_snapshots_per_trade: float,
) -> None:
    with pytest.raises(ValueError):
        build_expectation_from_backtest_result(
            _backtest_result(1),
            expected_median_spread_bps=expected_median_spread_bps,
            active_snapshots_per_trade=active_snapshots_per_trade,
        )
