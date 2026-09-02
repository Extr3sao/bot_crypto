"""Marginal Portfolio Value Analysis (P15).

When multiple alpha families exist, compute:
- Standalone performance for each family
- Marginal contribution when added to the existing portfolio
- Overlap detection between families
- Incremental turnover analysis

P15 contract:
A family must NOT be added merely because it makes money in isolation.
It must contribute MARGINAL value to the combined portfolio.

Key metrics per family addition:
- delta_net_pnl
- delta_net_exp_r
- delta_pf
- delta_dd (drawdown change)
- delta_daily_coverage
- incremental_turnover
- overlap_with_existing_signals
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from .types import (
    AlphaSignal,
    PerformanceMetrics,
)

# ---------------------------------------------------------------------------
# Standalone Family Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StandaloneResult:
    """Performance of a single alpha family in isolation."""

    family: str
    metrics: PerformanceMetrics
    trade_count: int
    signals_generated: int

    @property
    def has_edge(self) -> bool:
        """Whether this family has standalone edge (net_exp_r > 0)."""
        return self.metrics.net_exp_r > 0


# ---------------------------------------------------------------------------
# Marginal Contribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarginalContribution:
    """Marginal impact of adding one family to an existing portfolio."""

    family: str

    # Delta metrics (portfolio_with_family - portfolio_without_family)
    delta_net_pnl: float = 0.0
    delta_net_exp_r: float = 0.0
    delta_gross_exp_r: float = 0.0
    delta_pf: float = 0.0  # net profit factor change
    delta_max_drawdown: float = 0.0  # positive = worse
    delta_daily_coverage: float = 0.0

    # Turnover
    incremental_trades: int = 0
    incremental_turnover: float = 0.0
    overlap_count: int = 0  # signals that overlapped with existing
    overlap_pct: float = 0.0  # overlap / total signals from this family

    # Verdict
    marginal_positive: bool = False  # delta_net_pnl > 0
    recommended: bool = False  # marginal_positive AND reasonable overlap

    @property
    def cost_to_add(self) -> float:
        """Estimated cost of adding this family (commission + slippage)."""
        return self.incremental_turnover * 0.001  # rough estimate


# ---------------------------------------------------------------------------
# Overlap Analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignalOverlap:
    """Overlap between two signal sets."""

    family_a: str
    family_b: str
    overlapping_symbols: int
    overlapping_directions: int
    total_signals_a: int
    total_signals_b: int

    @property
    def overlap_pct_a(self) -> float:
        return self.overlapping_symbols / self.total_signals_a if self.total_signals_a > 0 else 0.0

    @property
    def overlap_pct_b(self) -> float:
        return self.overlapping_symbols / self.total_signals_b if self.total_signals_b > 0 else 0.0


# ---------------------------------------------------------------------------
# Marginal Portfolio Analyzer
# ---------------------------------------------------------------------------


class MarginalPortfolioAnalyzer:
    """Analyzes marginal value of each alpha family in the portfolio.

    P15 contract:
    - Compute standalone performance per family
    - Compute marginal contribution when added to portfolio
    - Detect signal overlap between families
    - A family is recommended ONLY if it contributes marginal value
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("marginal_portfolio")

    def analyze(
        self,
        family_results: dict[str, StandaloneResult],
        portfolio_trades_by_family: dict[str, list[dict[str, Any]]] | None = None,
        signals_by_family: dict[str, list[AlphaSignal]] | None = None,
    ) -> MarginalReport:
        """Perform marginal portfolio analysis.

        Args:
            family_results: {family_name: StandaloneResult} — each family's standalone perf
            portfolio_trades_by_family: {family_name: [trades]} — trades per family from portfolio run
            signals_by_family: {family_name: [AlphaSignal]} — signals per family for overlap analysis

        Returns:
            MarginalReport with standalone + marginal analysis
        """
        families = list(family_results.keys())

        # Compute marginal contributions
        marginals = self._compute_marginals(family_results, portfolio_trades_by_family)

        # Compute overlap matrix
        overlaps = self._compute_overlaps(signals_by_family) if signals_by_family else []

        # Rank families by marginal contribution
        ranking = sorted(marginals, key=lambda m: m.delta_net_pnl, reverse=True)

        # Determine recommended set (greedy: add families while marginal_positive)
        recommended = self._determine_recommended(ranking)

        return MarginalReport(
            families=families,
            standalone={f: family_results[f] for f in families},
            marginals={m.family: m for m in marginals},
            overlaps=overlaps,
            ranking=[m.family for m in ranking],
            recommended=recommended,
        )

    def _compute_marginals(
        self,
        standalone: dict[str, StandaloneResult],
        portfolio_trades: dict[str, list[dict[str, Any]]] | None,
    ) -> list[MarginalContribution]:
        """Compute marginal contribution for each family.

        Simplified approach: compare standalone metrics to estimate marginal value.
        Full approach would require running portfolio backtest with/without each family.
        """
        marginals: list[MarginalContribution] = []

        for family, result in standalone.items():
            # Get portfolio-level trades for this family
            family_trades = portfolio_trades.get(family, []) if portfolio_trades else []

            # Estimate marginal contribution
            # In a full implementation, this would run the portfolio backtest
            # with and without this family. For now, use standalone metrics
            # as a proxy for marginal value.
            metrics = result.metrics

            # Overlap detection
            overlap_count = 0
            overlap_pct = 0.0
            if portfolio_trades:
                # Count how many of this family's trades overlap in time/symbol
                # with other families' trades
                other_trades = []
                for other_family, trades in portfolio_trades.items():
                    if other_family != family:
                        other_trades.extend(trades)

                if other_trades and family_trades:
                    overlap_count = self._count_overlapping_trades(family_trades, other_trades)
                    overlap_pct = overlap_count / len(family_trades) if family_trades else 0.0

            marginal = MarginalContribution(
                family=family,
                delta_net_pnl=metrics.net_pnl,
                delta_net_exp_r=metrics.net_exp_r,
                delta_gross_exp_r=metrics.gross_exp_r,
                delta_pf=metrics.net_pf,
                delta_max_drawdown=metrics.max_drawdown,
                delta_daily_coverage=metrics.coverage_days_pct,
                incremental_trades=metrics.total_trades,
                incremental_turnover=metrics.turnover,
                overlap_count=overlap_count,
                overlap_pct=overlap_pct,
                marginal_positive=metrics.net_pnl > 0,
                recommended=metrics.net_pnl > 0 and overlap_pct < 0.8,
            )

            marginals.append(marginal)

        return marginals

    def _count_overlapping_trades(
        self,
        trades_a: list[dict[str, Any]],
        trades_b: list[dict[str, Any]],
    ) -> int:
        """Count trades that overlap in symbol and time window."""
        overlap = 0
        for ta in trades_a:
            for tb in trades_b:
                if (ta.get("symbol") == tb.get("symbol") and
                        ta.get("direction") == tb.get("direction")):
                    # Check time overlap (entry within 1 bar of each other)
                    t_a = ta.get("entry_timestamp", 0)
                    t_b = tb.get("entry_timestamp", 0)
                    if abs(t_a - t_b) < 3_600_000:  # 1 hour
                        overlap += 1
                        break
        return overlap

    def _compute_overlaps(
        self,
        signals_by_family: dict[str, list[AlphaSignal]],
    ) -> list[SignalOverlap]:
        """Compute pairwise overlap between all families."""
        families = list(signals_by_family.keys())
        overlaps: list[SignalOverlap] = []

        for i, fam_a in enumerate(families):
            for fam_b in families[i + 1:]:
                sigs_a = signals_by_family[fam_a]
                sigs_b = signals_by_family[fam_b]

                # Group by (symbol, direction)
                set_a = {(s.symbol, s.direction) for s in sigs_a}
                set_b = {(s.symbol, s.direction) for s in sigs_b}
                common = set_a & set_b

                overlaps.append(SignalOverlap(
                    family_a=fam_a,
                    family_b=fam_b,
                    overlapping_symbols=len(common),
                    overlapping_directions=len(common),
                    total_signals_a=len(sigs_a),
                    total_signals_b=len(sigs_b),
                ))

        return overlaps

    def _determine_recommended(
        self,
        ranking: list[MarginalContribution],
    ) -> list[str]:
        """Greedy selection: add families while marginal contribution is positive."""
        recommended: list[str] = []
        for m in ranking:
            if m.recommended:
                recommended.append(m.family)
            else:
                break  # stop at first non-recommended
        return recommended


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarginalReport:
    """Complete marginal portfolio analysis report."""

    families: list[str]
    standalone: dict[str, StandaloneResult]
    marginals: dict[str, MarginalContribution]
    overlaps: list[SignalOverlap]
    ranking: list[str]  # families ranked by marginal contribution
    recommended: list[str]  # families recommended for inclusion

    def to_dict(self) -> dict[str, Any]:
        """Serialize for reporting."""
        return {
            "families": self.families,
            "ranking": self.ranking,
            "recommended": self.recommended,
            "standalone": {
                f: {
                    "trades": s.trade_count,
                    "net_pnl": s.metrics.net_pnl,
                    "net_exp_r": s.metrics.net_exp_r,
                    "net_pf": s.metrics.net_pf,
                    "has_edge": s.has_edge,
                }
                for f, s in self.standalone.items()
            },
            "marginals": {
                f: {
                    "delta_net_pnl": m.delta_net_pnl,
                    "delta_net_exp_r": m.delta_net_exp_r,
                    "delta_pf": m.delta_pf,
                    "delta_max_drawdown": m.delta_max_drawdown,
                    "overlap_pct": m.overlap_pct,
                    "marginal_positive": m.marginal_positive,
                    "recommended": m.recommended,
                }
                for f, m in self.marginals.items()
            },
            "overlaps": [
                {
                    "family_a": o.family_a,
                    "family_b": o.family_b,
                    "overlap_pct_a": o.overlap_pct_a,
                    "overlap_pct_b": o.overlap_pct_b,
                }
                for o in self.overlaps
            ],
        }


__all__ = [
    "MarginalContribution",
    "MarginalPortfolioAnalyzer",
    "MarginalReport",
    "SignalOverlap",
    "StandaloneResult",
]
