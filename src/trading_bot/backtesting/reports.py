"""Fold-level reporting helpers for backtest results (TSK-104 F3a).

Transforms a ``BacktestResult`` into a compact immutable summary that is
ready to render in Markdown/CSV/JSON reports without re-scanning the raw
trade list in downstream layers.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from .types import BacktestResult


@dataclass(frozen=True, slots=True)
class FoldReport:
    """Summary of one backtest fold/run."""

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


def build_fold_report(result: BacktestResult) -> FoldReport:
    """Build a fold report from a completed backtest run."""
    trades = result.trades
    pnls = [trade.pnl for trade in trades]
    wins = [trade.pnl for trade in trades if trade.pnl > 0.0]
    losses = [abs(trade.pnl) for trade in trades if trade.pnl <= 0.0]

    avg_bars_held = sum(trade.bars_held for trade in trades) / len(trades) if trades else 0.0
    best_trade_pnl = max(pnls, default=0.0)
    worst_trade_pnl = min(pnls, default=0.0)
    reward_risk_ratio = _compute_reward_risk_ratio(wins, losses)
    total_commissions = sum(
        trade.entry_fill.commission + trade.exit_fill.commission for trade in trades
    )
    total_slippage = sum(trade.entry_fill.slippage + trade.exit_fill.slippage for trade in trades)

    return FoldReport(
        strategy_name=result.strategy_name,
        symbol=result.symbol,
        timeframe=result.timeframe,
        start=result.start,
        end=result.end,
        initial_capital=result.initial_capital,
        final_equity=result.final_equity,
        total_trades=len(trades),
        win_rate=result.metrics["win_rate"],
        profit_factor=result.metrics["profit_factor"],
        expectancy=result.metrics["expectancy"],
        avg_trade_pnl=result.metrics["avg_trade_pnl"],
        max_drawdown=result.metrics["max_drawdown"],
        cagr=result.metrics["cagr"],
        calmar_ratio=result.metrics["calmar_ratio"],
        sharpe_ratio=result.metrics["sharpe_ratio"],
        sortino_ratio=result.metrics["sortino_ratio"],
        avg_bars_held=float(avg_bars_held),
        best_trade_pnl=float(best_trade_pnl),
        worst_trade_pnl=float(worst_trade_pnl),
        max_consecutive_losses=_max_consecutive_losses(pnls),
        reward_risk_ratio=float(reward_risk_ratio),
        total_commissions=float(total_commissions),
        total_slippage=float(total_slippage),
    )


def _compute_reward_risk_ratio(wins: list[float], losses: list[float]) -> float:
    if not wins and not losses:
        return 0.0
    if wins and not losses:
        return float("inf")
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return avg_win / avg_loss if avg_loss > 0.0 else 0.0


def _max_consecutive_losses(pnls: list[float]) -> int:
    max_streak = 0
    current_streak = 0
    for pnl in pnls:
        if pnl <= 0.0:
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
        else:
            current_streak = 0
    return max_streak


__all__ = ["FoldReport", "build_fold_report"]
