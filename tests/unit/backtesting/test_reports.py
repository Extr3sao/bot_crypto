"""Tests for fold-level backtest reports (TSK-104 F3a)."""

from __future__ import annotations

import datetime

import pytest

from trading_bot.backtesting.reports import FoldReport, build_fold_report
from trading_bot.backtesting.types import BacktestResult, EquityPoint, Fill, Trade


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


def _trade(
    *,
    order_id: str,
    pnl: float,
    bars_held: int,
    entry_commission: float = 1.0,
    exit_commission: float = 1.5,
    entry_slippage: float = 0.2,
    exit_slippage: float = 0.3,
) -> Trade:
    entry_fill = _fill(
        order_id=f"{order_id}-buy",
        side="buy",
        price=100.0,
        commission=entry_commission,
        slippage=entry_slippage,
        timestamp=1_700_000_000_000,
    )
    exit_fill = _fill(
        order_id=f"{order_id}-sell",
        side="sell",
        price=100.0 + pnl,
        commission=exit_commission,
        slippage=exit_slippage,
        timestamp=1_700_000_300_000,
    )
    return Trade(
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        pnl=pnl,
        pnl_pct=pnl / 100.0,
        bars_held=bars_held,
    )


def _result_with_trades(trades: list[Trade]) -> BacktestResult:
    return BacktestResult(
        strategy_name="demo-strategy",
        symbol="BTC/USDT",
        timeframe="1h",
        start=datetime.datetime(2026, 1, 1),
        end=datetime.datetime(2026, 1, 31),
        initial_capital=10_000.0,
        final_equity=10_250.0,
        trades=trades,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
            EquityPoint(timestamp=1_700_000_300_000, equity=10_250.0, drawdown_pct=0.10),
        ],
        metrics={
            "total_trades": float(len(trades)),
            "win_rate": 1 / 3,
            "profit_factor": 0.5,
            "final_equity": 10_250.0,
            "max_drawdown": 0.10,
            "cagr": 0.12,
            "calmar_ratio": 1.2,
            "sharpe_ratio": 0.9,
            "sortino_ratio": 1.1,
            "avg_trade_pnl": -10.0,
            "expectancy": -10.0,
        },
    )


def test_build_fold_report_returns_frozen_summary() -> None:
    report = build_fold_report(_result_with_trades([_trade(order_id="t1", pnl=10.0, bars_held=2)]))
    assert isinstance(report, FoldReport)
    with pytest.raises(AttributeError):
        report.symbol = "ETH/USDT"  # type: ignore[misc]


def test_build_fold_report_copies_core_fields_and_metrics() -> None:
    result = _result_with_trades([_trade(order_id="t1", pnl=10.0, bars_held=2)])
    report = build_fold_report(result)
    assert report.strategy_name == result.strategy_name
    assert report.symbol == result.symbol
    assert report.timeframe == result.timeframe
    assert report.initial_capital == result.initial_capital
    assert report.final_equity == result.final_equity
    assert report.win_rate == result.metrics["win_rate"]
    assert report.profit_factor == result.metrics["profit_factor"]
    assert report.max_drawdown == result.metrics["max_drawdown"]
    assert report.expectancy == result.metrics["expectancy"]


def test_build_fold_report_computes_trade_derived_fields() -> None:
    trades = [
        _trade(order_id="t1", pnl=-10.0, bars_held=2),
        _trade(order_id="t2", pnl=-20.0, bars_held=4),
        _trade(order_id="t3", pnl=15.0, bars_held=6),
    ]
    report = build_fold_report(_result_with_trades(trades))
    assert report.total_trades == 3
    assert report.avg_bars_held == pytest.approx(4.0)
    assert report.best_trade_pnl == 15.0
    assert report.worst_trade_pnl == -20.0
    assert report.max_consecutive_losses == 2
    assert report.reward_risk_ratio == pytest.approx(1.0)
    assert report.total_commissions == pytest.approx(7.5)
    assert report.total_slippage == pytest.approx(1.5)


def test_build_fold_report_no_trades_returns_zero_trade_summary() -> None:
    result = _result_with_trades([])
    report = build_fold_report(result)
    assert report.total_trades == 0
    assert report.avg_bars_held == 0.0
    assert report.best_trade_pnl == 0.0
    assert report.worst_trade_pnl == 0.0
    assert report.max_consecutive_losses == 0
    assert report.reward_risk_ratio == 0.0
    assert report.total_commissions == 0.0
    assert report.total_slippage == 0.0


def test_build_fold_report_reward_risk_is_inf_when_no_losses() -> None:
    trades = [
        _trade(order_id="t1", pnl=5.0, bars_held=1),
        _trade(order_id="t2", pnl=15.0, bars_held=3),
    ]
    report = build_fold_report(_result_with_trades(trades))
    assert report.reward_risk_ratio == float("inf")
    assert report.max_consecutive_losses == 0
