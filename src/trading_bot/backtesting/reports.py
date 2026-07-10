"""Fold-level reporting for backtests (TSK-104 F3b bridge).

This module bridges the per-fold ``BacktestResult`` payload to the
``FoldReport`` shape that ``walk_forward_aggregate`` consumes. Tests
in ``tests/unit/backtesting/test_walk_forward_reports.py`` instantiate
``FoldReport`` directly via the 24-field dataclass defined here.

Contract:
- ``FoldReport`` is frozen + ``slots`` (matches sibling dataclasses in
  ``types.py`` and ``walk_forward_reports.py``). Pure-data structure;
  no behavior.
- ``build_fold_report`` accepts a ``BacktestResult`` and returns a
  ``FoldReport``. It maps the ``Metrics`` TypedDict fields onto the
  dataclass slots and bridges the F2 advanced metrics that did NOT
  live on the F1 ``Metrics`` TypedDict (``avg_bars_held``,
  ``best_trade_pnl``, ``worst_trade_pnl``, ``max_consecutive_losses``,
  ``reward_risk_ratio``, ``total_commissions``, ``total_slippage``)
  by defaulting to 0.0 / 0 when absent. Callers that compute those
  metrics themselves can override via keyword arg.

TODO(TSK-200): post-merge quality-gates fix deferred batch.
The mypy . audit on HEAD 66659d8 reports 194 errors across 23 files
(largest clusters: tests/unit/scanner/test_universe_scanner.py 124,
tests/bdd/conftest.py 54, tests/unit/scanner/test_filters.py 25).
Out of scope for the gate-fix commit; tracked under TSK-200.
See: tasks/decisions.md and the next gate-fix sprint planning entry.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from .types import BacktestResult


@dataclass(frozen=True, slots=True)
class FoldReport:
    """Per-fold snapshot used by walk-forward aggregation.

    24 fixed slots. Match the field order used in
    ``tests/unit/backtesting/test_walk_forward_reports.py::_fold_report``.
    """

    strategy_name: str
    symbol: str
    timeframe: str
    start: datetime.datetime
    end: datetime.datetime
    initial_capital: float
    final_equity: float
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    avg_trade_pnl: float
    max_drawdown: float
    cagr: float
    calmar_ratio: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_bars_held: float
    best_trade_pnl: float
    worst_trade_pnl: float
    max_consecutive_losses: int
    reward_risk_ratio: float
    total_commissions: float
    total_slippage: float


def build_fold_report(
    result: BacktestResult,
    *,
    avg_bars_held: float = 0.0,
    best_trade_pnl: float = 0.0,
    worst_trade_pnl: float = 0.0,
    max_consecutive_losses: int = 0,
    reward_risk_ratio: float = 0.0,
    total_commissions: float = 0.0,
    total_slippage: float = 0.0,
) -> FoldReport:
    """Build a FoldReport from a BacktestResult.

    TSK-104 F3b contract: callers wanting walk-forward-style reporting
    on a single backtest run use this bridge. The 7 advanced fields
    not present on the F1 ``Metrics`` TypedDict are passed through as
    keyword arguments (defaults to 0); callers that already compute
    them can override.
    """
    metrics = result.metrics
    return FoldReport(
        strategy_name=result.strategy_name,
        symbol=result.symbol,
        timeframe=result.timeframe,
        start=result.start,
        end=result.end,
        initial_capital=result.initial_capital,
        final_equity=result.final_equity,
        total_trades=int(metrics["total_trades"]),
        win_rate=float(metrics["win_rate"]),
        profit_factor=float(metrics["profit_factor"]),
        expectancy=float(metrics["expectancy"]),
        avg_trade_pnl=float(metrics["avg_trade_pnl"]),
        max_drawdown=float(metrics["max_drawdown"]),
        cagr=float(metrics["cagr"]),
        calmar_ratio=float(metrics["calmar_ratio"]),
        sharpe_ratio=float(metrics["sharpe_ratio"]),
        sortino_ratio=float(metrics["sortino_ratio"]),
        avg_bars_held=avg_bars_held,
        best_trade_pnl=best_trade_pnl,
        worst_trade_pnl=worst_trade_pnl,
        max_consecutive_losses=max_consecutive_losses,
        reward_risk_ratio=reward_risk_ratio,
        total_commissions=total_commissions,
        total_slippage=total_slippage,
    )


__all__ = ["FoldReport", "build_fold_report"]
