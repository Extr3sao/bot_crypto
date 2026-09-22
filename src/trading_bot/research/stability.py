"""Stability Analysis (P17).

Provides descriptive breakdowns of performance across:
- Chronological thirds (first/middle/last)
- Monthly periods
- Weekly periods (if sufficient data)
- By direction (LONG/SHORT)
- By family

These are DESCRIPTIVE only — they do NOT generate automatic filters.
Post-hoc descriptive differences are NOT operational rules (P7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import PerformanceMetrics


@dataclass(frozen=True, slots=True)
class PeriodMetrics:
    """Performance metrics for a single period."""

    period_label: str
    start_ts: int
    end_ts: int
    trades: int
    gross_pnl: float
    net_pnl: float
    gross_exp_r: float
    net_exp_r: float
    net_pf: float
    max_drawdown: float
    winning_trades: int
    losing_trades: int

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.trades if self.trades > 0 else 0.0


@dataclass(frozen=True, slots=True)
class StabilityReport:
    """Complete stability analysis for a set of trades."""

    chronological_thirds: list[PeriodMetrics]
    monthly: list[PeriodMetrics]
    by_direction: dict[str, PerformanceMetrics]
    by_family: dict[str, PerformanceMetrics]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for reporting."""
        return {
            "chronological_thirds": [_period_to_dict(p) for p in self.chronological_thirds],
            "monthly": [_period_to_dict(p) for p in self.monthly],
            "by_direction": {k: _metrics_to_dict(v) for k, v in self.by_direction.items()},
            "by_family": {k: _metrics_to_dict(v) for k, v in self.by_family.items()},
        }


class StabilityAnalyzer:
    """Descriptive stability analysis (P17).

    All outputs are DESCRIPTIVE. They do NOT generate filters or rules.
    """

    def analyze(
        self,
        trades: list[dict[str, Any]],
    ) -> StabilityReport:
        """Analyze stability of a trade set.

        Args:
            trades: List of trade dicts with at minimum:
                timestamp, direction, family, net_pnl, gross_pnl,
                entry_timestamp, exit_timestamp

        Returns:
            StabilityReport with descriptive breakdowns.
        """
        if not trades:
            return StabilityReport(
                chronological_thirds=[],
                monthly=[],
                by_direction={},
                by_family={},
            )

        # Sort by entry timestamp
        sorted_trades = sorted(trades, key=lambda t: t.get("entry_timestamp", 0))

        # Chronological thirds
        thirds = self._compute_thirds(sorted_trades)

        # Monthly
        monthly = self._compute_monthly(sorted_trades)

        # By direction
        by_dir: dict[str, list[dict[str, Any]]] = {}
        for t in sorted_trades:
            d = t.get("direction", "UNKNOWN")
            by_dir.setdefault(d, []).append(t)
        by_direction = {d: _compute_agg_metrics(ts) for d, ts in by_dir.items()}

        # By family
        by_fam: dict[str, list[dict[str, Any]]] = {}
        for t in sorted_trades:
            f = t.get("family", "unknown")
            by_fam.setdefault(f, []).append(t)
        by_family = {f: _compute_agg_metrics(ts) for f, ts in by_fam.items()}

        return StabilityReport(
            chronological_thirds=thirds,
            monthly=monthly,
            by_direction=by_direction,
            by_family=by_family,
        )

    def _compute_thirds(self, trades: list[dict[str, Any]]) -> list[PeriodMetrics]:
        """Split trades into chronological thirds."""
        n = len(trades)
        if n < 3:
            return [_period_from_trades("full", trades)]

        third_size = n // 3
        return [
            _period_from_trades("first_third", trades[:third_size]),
            _period_from_trades("middle_third", trades[third_size : 2 * third_size]),
            _period_from_trades("last_third", trades[2 * third_size :]),
        ]

    def _compute_monthly(self, trades: list[dict[str, Any]]) -> list[PeriodMetrics]:
        """Group trades by month."""
        import time

        monthly: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            ts = t.get("entry_timestamp", 0)
            # Convert epoch ms to YYYY-MM
            month_key = time.strftime("%Y-%m", time.gmtime(ts / 1000))
            monthly.setdefault(month_key, []).append(t)

        return [_period_from_trades(label, ts) for label, ts in sorted(monthly.items())]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _period_from_trades(label: str, trades: list[dict[str, Any]]) -> PeriodMetrics:
    """Compute PeriodMetrics from a list of trades."""
    if not trades:
        return PeriodMetrics(
            period_label=label,
            start_ts=0,
            end_ts=0,
            trades=0,
            gross_pnl=0,
            net_pnl=0,
            gross_exp_r=0,
            net_exp_r=0,
            net_pf=0,
            max_drawdown=0,
            winning_trades=0,
            losing_trades=0,
        )

    start_ts = min(t.get("entry_timestamp", 0) for t in trades)
    end_ts = max(t.get("exit_timestamp", 0) for t in trades)
    net_pnl = sum(t.get("net_pnl", 0) for t in trades)
    gross_pnl = sum(t.get("gross_pnl", 0) for t in trades)
    winning = sum(1 for t in trades if t.get("net_pnl", 0) > 0)
    losing = sum(1 for t in trades if t.get("net_pnl", 0) < 0)

    # Simple PF calculation
    gross_wins = sum(t.get("gross_pnl", 0) for t in trades if t.get("gross_pnl", 0) > 0)
    gross_losses = sum(t.get("gross_pnl", 0) for t in trades if t.get("gross_pnl", 0) < 0)
    net_pf = (
        gross_wins / abs(gross_losses)
        if gross_losses != 0
        else (float("inf") if gross_wins > 0 else 0.0)
    )

    return PeriodMetrics(
        period_label=label,
        start_ts=start_ts,
        end_ts=end_ts,
        trades=len(trades),
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        gross_exp_r=0.0,  # needs risk_per_trade to compute
        net_exp_r=0.0,
        net_pf=net_pf,
        max_drawdown=0.0,  # needs equity curve to compute
        winning_trades=winning,
        losing_trades=losing,
    )


def _compute_agg_metrics(trades: list[dict[str, Any]]) -> PerformanceMetrics:
    """Compute aggregate PerformanceMetrics from trade dicts."""
    if not trades:
        return PerformanceMetrics()

    net_pnl = sum(t.get("net_pnl", 0) for t in trades)
    gross_pnl = sum(t.get("gross_pnl", 0) for t in trades)
    commission = sum(t.get("commission", 0) for t in trades)
    slippage = sum(t.get("slippage", 0) for t in trades)
    winning = sum(1 for t in trades if t.get("net_pnl", 0) > 0)
    losing = sum(1 for t in trades if t.get("net_pnl", 0) < 0)

    gross_wins = sum(t.get("gross_pnl", 0) for t in trades if t.get("gross_pnl", 0) > 0)
    gross_losses = sum(t.get("gross_pnl", 0) for t in trades if t.get("gross_pnl", 0) < 0)
    net_wins = sum(t.get("net_pnl", 0) for t in trades if t.get("net_pnl", 0) > 0)
    net_losses = sum(t.get("net_pnl", 0) for t in trades if t.get("net_pnl", 0) < 0)

    gross_pf = (
        gross_wins / abs(gross_losses)
        if gross_losses != 0
        else (float("inf") if gross_wins > 0 else 0.0)
    )
    net_pf = (
        net_wins / abs(net_losses) if net_losses != 0 else (float("inf") if net_wins > 0 else 0.0)
    )

    return PerformanceMetrics(
        total_trades=len(trades),
        winning_trades=winning,
        losing_trades=losing,
        gross_pnl=gross_pnl,
        gross_win_sum=gross_wins,
        gross_loss_sum=gross_losses,
        total_commission=commission,
        total_slippage=slippage,
        net_pnl=net_pnl,
        net_win_sum=net_wins,
        net_loss_sum=net_losses,
        gross_pf=gross_pf,
        net_pf=net_pf,
    )


def _period_to_dict(p: PeriodMetrics) -> dict[str, Any]:
    """Serialize PeriodMetrics to dict."""
    return {
        "period_label": p.period_label,
        "start_ts": p.start_ts,
        "end_ts": p.end_ts,
        "trades": p.trades,
        "gross_pnl": p.gross_pnl,
        "net_pnl": p.net_pnl,
        "gross_exp_r": p.gross_exp_r,
        "net_exp_r": p.net_exp_r,
        "net_pf": p.net_pf,
        "max_drawdown": p.max_drawdown,
        "winning_trades": p.winning_trades,
        "losing_trades": p.losing_trades,
        "win_rate": p.win_rate,
    }


def _metrics_to_dict(m: PerformanceMetrics) -> dict[str, Any]:
    """Serialize PerformanceMetrics to dict."""
    import dataclasses

    return {f.name: getattr(m, f.name) for f in dataclasses.fields(m)}


__all__ = ["PeriodMetrics", "StabilityAnalyzer", "StabilityReport"]
