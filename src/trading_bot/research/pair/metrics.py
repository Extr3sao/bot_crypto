"""RFC-030 §19/§30/§32 — true equity metrics for a pair book.

The ambiguous historical ``max_drawdown_bps`` (a drawdown of a *reference notional*)
is deliberately **not** reused here. Instead the equity is the explicit capital
model of :class:`~trading_bot.research.pair.ledger.PortfolioState`::

    equity_t = initial_capital + realized_net_t + unrealized_t

and the drawdown is the peak-to-trough decline of that equity curve. A return or a
drawdown is only reported when the capital model makes it mathematically valid
(``initial_capital > 0`` and a positive running peak); otherwise it is ``None``,
never a fabricated zero.

Research/PAPER only. Deterministic, no clock, no RNG.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .ledger import PairLedger, PairLedgerEntry

__all__ = ["EquityMetrics", "equity_metrics", "max_drawdown"]


def max_drawdown(curve: Sequence[float]) -> tuple[float, float]:
    """Peak-to-trough drawdown of an equity curve.

    Returns ``(fraction, absolute)`` where ``fraction`` is the largest decline from a
    running peak expressed as a fraction of that peak (``0.10`` = 10 %). Both are
    ``0.0`` when the curve never declines; ``fraction`` is ``0.0`` when the peak is
    not positive (an undefined fraction is never reported as a real number).
    """
    if not curve:
        return 0.0, 0.0
    peak = curve[0]
    worst_frac = 0.0
    worst_abs = 0.0
    for value in curve:
        peak = max(peak, value)
        dd_abs = peak - value
        if dd_abs > worst_abs:
            worst_abs = dd_abs
        if peak > 0.0:
            frac = dd_abs / peak
            if frac > worst_frac:
                worst_frac = frac
    return worst_frac, worst_abs


@dataclass(frozen=True, slots=True)
class EquityMetrics:
    """§32 — the mandatory pair-book metric set (true equity, not a notional proxy)."""

    n_periods: int
    initial_capital: float
    final_equity: float
    equity_return: float | None
    max_drawdown_fraction: float | None
    max_drawdown_abs: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    mean_net_pnl: float
    turnover_ratio: float | None
    mean_gross_exposure: float
    mean_net_exposure: float
    mean_beta_before: float
    mean_beta_after: float
    mean_holding_days: float
    sharpe_per_period: float | None
    sortino_per_period: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_periods": self.n_periods,
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            "equity_return": self.equity_return,
            "max_drawdown_fraction": self.max_drawdown_fraction,
            "max_drawdown_abs": self.max_drawdown_abs,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "profit_factor": self.profit_factor,
            "mean_net_pnl": self.mean_net_pnl,
            "turnover_ratio": self.turnover_ratio,
            "mean_gross_exposure": self.mean_gross_exposure,
            "mean_net_exposure": self.mean_net_exposure,
            "mean_beta_before": self.mean_beta_before,
            "mean_beta_after": self.mean_beta_after,
            "mean_holding_days": self.mean_holding_days,
            "sharpe_per_period": self.sharpe_per_period,
            "sortino_per_period": self.sortino_per_period,
        }


def _per_period_returns(entries: Sequence[PairLedgerEntry], initial_capital: float) -> list[float]:
    if initial_capital <= 0.0:
        return []
    return [e.pair_net_pnl / initial_capital for e in entries]


def equity_metrics(
    ledger: PairLedger,
    *,
    unrealized_pnl: float = 0.0,
    periods_per_year: float = 52.0,
) -> EquityMetrics:
    """Recompute the §32 metric set from the raw ledger entries."""
    entries = ledger.entries
    initial = ledger.initial_capital
    curve: list[float] = [initial]
    running = initial
    for e in entries:
        running += e.pair_net_pnl
        curve.append(running)
    final_equity = running + unrealized_pnl
    curve[-1] += unrealized_pnl

    dd_frac, dd_abs = max_drawdown(curve)
    nets = [e.pair_net_pnl for e in entries]
    gross_profit = math.fsum(x for x in nets if x > 0.0)
    gross_loss = math.fsum(-x for x in nets if x < 0.0)

    rets = _per_period_returns(entries, initial)
    sharpe: float | None = None
    sortino: float | None = None
    if len(rets) >= 2:
        mean = statistics.fmean(rets)
        sd = statistics.stdev(rets)
        if sd > 1e-15:
            sharpe = mean / sd * math.sqrt(periods_per_year)
        downside = [r for r in rets if r < 0.0]
        if len(downside) >= 2:
            dsd = statistics.stdev(downside)
            if dsd > 1e-15:
                sortino = mean / dsd * math.sqrt(periods_per_year)

    n = len(entries)
    return EquityMetrics(
        n_periods=n,
        initial_capital=initial,
        final_equity=final_equity,
        equity_return=(final_equity / initial - 1.0) if initial > 0.0 else None,
        max_drawdown_fraction=dd_frac if initial > 0.0 else None,
        max_drawdown_abs=dd_abs,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0.0 else None,
        mean_net_pnl=(statistics.fmean(nets) if nets else 0.0),
        turnover_ratio=(
            ledger.total_gross_exposure / initial if initial > 0.0 else None
        ),
        mean_gross_exposure=(statistics.fmean([e.gross_exposure for e in entries]) if n else 0.0),
        mean_net_exposure=(statistics.fmean([e.net_exposure for e in entries]) if n else 0.0),
        mean_beta_before=(statistics.fmean([e.beta_before for e in entries]) if n else 0.0),
        mean_beta_after=(statistics.fmean([e.beta_after for e in entries]) if n else 0.0),
        mean_holding_days=(statistics.fmean([e.holding_days for e in entries]) if n else 0.0),
        sharpe_per_period=sharpe,
        sortino_per_period=sortino,
    )
