"""Risk-reject analysis metrics — by rejection reason (Track B3/B4).

SHADOW-AND-LEGACY-VALIDATION-01. Consumes the
:class:`trading_bot.shadow.outcome.ShadowOutcomeLedger` and produces
per-reason observational metrics:

    candidate_count, resolved_shadow_count, wins, losses,
    expectancy, profit_factor, drawdown, plus strategy / regime /
    health-state distributions.

Strictly analytical: nothing here mutates RiskManager, PaperBroker, or any
campaign accounting. Metrics classify blocks only when evidence exists;
otherwise the status is ``INSUFFICIENT_EVIDENCE`` (never inferred).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from trading_bot.shadow.outcome import ShadowOutcomeLedger, ShadowTrade

__all__ = [
    "RejectReasonAnalysis",
    "RejectReasonMetrics",
]


@dataclass(frozen=True, slots=True)
class RejectReasonMetrics:
    """Aggregated shadow outcome for one risk rejection reason."""

    reason: str
    candidate_count: int
    resolved_shadow_count: int
    wins: int
    losses: int
    expectancy_net: float  # mean net pnl per resolved shadow trade
    profit_factor: float | None  # None when no losses (degenerate)
    max_drawdown_sum: float  # cumulative worst consecutive net loss run (sum of losses)
    strategy_distribution: dict[str, int]
    regime_distribution: dict[str, int]
    health_state_distribution: dict[str, int]

    @property
    def status(self) -> str:
        """Analytical classification — evidence-backed or honest gap."""
        if self.resolved_shadow_count == 0:
            return "INSUFFICIENT_EVIDENCE"
        return "EVIDENCE_AVAILABLE"


class RejectReasonAnalysis:
    """Compute per-reason metrics from a shadow outcome ledger."""

    def __init__(self, ledger: ShadowOutcomeLedger) -> None:
        self._trades: tuple[ShadowTrade, ...] = ledger.trades

    def by_reason(self) -> dict[str, RejectReasonMetrics]:
        grouped: dict[str, list[ShadowTrade]] = {}
        for trade in self._trades:
            grouped.setdefault(trade.risk_rejection_reason, []).append(trade)

        metrics: dict[str, RejectReasonMetrics] = {}
        for reason, trades in grouped.items():
            wins = sum(1 for t in trades if t.net_pnl > 0)
            losses = sum(1 for t in trades if t.net_pnl < 0)
            gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
            gross_loss = sum(-t.net_pnl for t in trades if t.net_pnl < 0)
            expectancy = sum(t.net_pnl for t in trades) / len(trades)
            pf: float | None = None
            if gross_loss > 0:
                pf = gross_win / gross_loss

            # Drawdown over the shadow PnL sequence (in ledger order):
            # peak-to-trough on cumulative net pnl.
            equity = 0.0
            peak = 0.0
            max_dd = 0.0
            for t in trades:
                equity += t.net_pnl
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)

            metrics[reason] = RejectReasonMetrics(
                reason=reason,
                candidate_count=len(trades),
                resolved_shadow_count=len(trades),
                wins=wins,
                losses=losses,
                expectancy_net=expectancy,
                profit_factor=pf,
                max_drawdown_sum=max_dd,
                strategy_distribution=_counts(t.strategy_id for t in trades),
                regime_distribution=_counts(t.regime_signature for t in trades),
                health_state_distribution=_counts(
                    t.strategy_health_state for t in trades
                ),
            )
        return metrics

    def classify_block(
        self,
        metrics: RejectReasonMetrics,
        *,
        min_sample: int = 20,
        min_expectancy: float = 0.0,
    ) -> str:
        """Analytical label for one rejection reason. Never auto-relaxes risk.

        - GOOD_CANDIDATE_BLOCKED: positive expectancy with adequate sample.
        - LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED: non-positive expectancy
          with adequate sample.
        - INSUFFICIENT_EVIDENCE: sample below the pre-declared minimum.
        """
        if metrics.resolved_shadow_count < min_sample:
            return "INSUFFICIENT_EVIDENCE"
        if metrics.expectancy_net > min_expectancy:
            return "GOOD_CANDIDATE_BLOCKED"
        return "LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED"

    def summary(self) -> dict[str, Any]:
        return {
            reason: {
                "candidate_count": m.candidate_count,
                "resolved_shadow_count": m.resolved_shadow_count,
                "wins": m.wins,
                "losses": m.losses,
                "expectancy_net": m.expectancy_net,
                "profit_factor": m.profit_factor,
                "max_drawdown_sum": m.max_drawdown_sum,
                "status": m.status,
                "classification": self.classify_block(m),
                "strategy_distribution": dict(m.strategy_distribution),
                "regime_distribution": dict(m.regime_distribution),
                "health_state_distribution": dict(m.health_state_distribution),
            }
            for reason, m in self.by_reason().items()
        }


def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
