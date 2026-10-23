"""Metric aggregation for the ARP-002 campaign (pure, deterministic).

Mirrors the shapes the ARP-001 diagnostics and ``multi_family_backtest.aggregate``
already use, so the campaign's numbers are comparable to the frozen baselines.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from typing import Any

from .simulate import Trade

__all__ = ["concentration", "max_drawdown_bps", "summarize"]

NOTIONAL_USD = 500.0
BPS = 10000.0


def max_drawdown_bps(nets: Sequence[float]) -> float:
    """Peak-to-trough drawdown of the non-compounding net trade sequence, in bps."""
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst / NOTIONAL_USD * BPS, 3)


def concentration(nets: Sequence[float]) -> dict[str, Any]:
    pos = sorted((n for n in nets if n > 0), reverse=True)
    total_pos = sum(pos)
    if not pos or total_pos <= 0:
        return {
            "positive_trades": 0,
            "total_positive_net": 0.0,
            "top1_share": None,
            "top5_share": None,
            "top10pct_share": None,
        }
    k10 = max(1, len(nets) // 10)
    return {
        "positive_trades": len(pos),
        "total_positive_net": round(total_pos, 2),
        "top1_share": round(sum(pos[:1]) / total_pos, 4),
        "top5_share": round(sum(pos[:5]) / total_pos, 4),
        "top10pct_share": round(sum(pos[:k10]) / total_pos, 4),
    }


def summarize(
    trades: Sequence[Trade], *, cost_bps_rt: float, notional: float = NOTIONAL_USD
) -> dict[str, Any]:
    """§11 metrics for one split/scenario."""
    n = len(trades)
    nets = [t.net for t in trades]
    gross = sum(t.gross for t in trades)
    fees = sum(t.fees for t in trades)
    net = sum(nets)
    wins = [t.net for t in trades if t.net > 0]
    losses = [t.net for t in trades if t.net <= 0]

    def bps(usd: float) -> float:
        return round(usd / notional * BPS, 3)

    net_bps_each = [t.net / notional * BPS for t in trades]
    sharpe = None
    if n >= 30:
        sd = statistics.pstdev(net_bps_each)
        if sd > 0:
            sharpe = round(statistics.fmean(net_bps_each) / sd, 4)
    return {
        "trades": n,
        "gross_usd": round(gross, 2),
        "fees_usd": round(fees, 2),
        "net_usd": round(net, 2),
        "expectancy_gross_bps": bps(gross / n) if n else None,
        "expectancy_cost_bps": bps(fees / n) if n else None,
        "expectancy_net_bps": bps(net / n) if n else None,
        "cost_bps_rt": round(cost_bps_rt, 4),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "avg_win_usd": round(statistics.fmean(wins), 4) if wins else None,
        "avg_loss_usd": round(statistics.fmean(losses), 4) if losses else None,
        "payoff": round(statistics.fmean(wins) / abs(statistics.fmean(losses)), 4)
        if wins and losses
        else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        "avg_mfe_pct": round(statistics.fmean([t.mfe_pct for t in trades]), 4) if n else None,
        "avg_mae_pct": round(statistics.fmean([t.mae_pct for t in trades]), 4) if n else None,
        "avg_duration_min": round(statistics.fmean([t.duration_min for t in trades]), 2)
        if n
        else None,
        "median_duration_min": round(statistics.median([t.duration_min for t in trades]), 2)
        if n
        else None,
        "max_drawdown_bps": max_drawdown_bps(nets),
        "sharpe_per_trade": sharpe,
        "exit_mix": dict(Counter(t.reason for t in trades)),
        "concentration": concentration(nets),
    }
