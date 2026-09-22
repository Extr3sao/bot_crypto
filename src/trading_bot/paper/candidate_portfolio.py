"""CandidatePortfolio — neutral operational contract (FASE 4).

Promoted from the research-only artifact in research/robustness.py (which
stays research-side and stays execution_wired=false). This module defines
the runtime contract the paper orchestrator consumes:

    TradeCandidate(s) → CandidatePortfolio (consolidated, pre-risk)

It carries NO capital allocation and NO execution authority: it is a
consolidated, ordered list of candidates with correlation/exposure
metadata for the Global Risk stage to judge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["CandidatePortfolio", "TradeCandidate", "build_portfolio"]


@dataclass(frozen=True, slots=True)
class TradeCandidate:
    """One routed, risk-pending trade candidate (per asset, per cycle)."""

    asset: str
    strategy_id: str
    family: str | None
    direction: str  # "LONG" | "SHORT"
    timestamp: int

    # Score/confidence from routing (0.0-1.0)
    score: float = 0.0

    # Price context
    entry_reference: float = 0.0
    structural_stop: float | None = None

    # Portfolio metadata (used by consolidation + risk)
    regime: str | None = None
    expected_risk_pct: float | None = None  # structural risk if stop is hit
    correlation_group: str | None = None  # e.g. "crypto-beta"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "strategy_id": self.strategy_id,
            "family": self.family,
            "direction": self.direction,
            "timestamp": self.timestamp,
            "score": self.score,
            "entry_reference": self.entry_reference,
            "structural_stop": self.structural_stop,
            "regime": self.regime,
            "expected_risk_pct": self.expected_risk_pct,
            "correlation_group": self.correlation_group,
        }


@dataclass
class CandidatePortfolio:
    """Consolidated pre-risk candidate set across assets (one cycle)."""

    candidates: list[TradeCandidate] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)  # {candidate, reason}
    warnings: list[str] = field(default_factory=list)

    # Consolidation metadata
    avg_pairwise_correlation: float = 0.0
    overlapping_exposure_pct: float = 0.0
    concentration_max_per_group: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected": list(self.rejected),
            "warnings": list(self.warnings),
            "avg_pairwise_correlation": self.avg_pairwise_correlation,
            "overlapping_exposure_pct": self.overlapping_exposure_pct,
            "concentration_max_per_group": self.concentration_max_per_group,
        }


def build_portfolio(
    candidates: list[TradeCandidate],
    *,
    max_per_correlation_group: int = 1,
    max_candidates: int = 3,
) -> CandidatePortfolio:
    """Consolidate candidates into a portfolio, fail-closed on concentration.

    Rules (deterministic, no capital allocation):
    - Highest score first.
    - At most ``max_per_correlation_group`` per correlation group
      (duplicated crypto beta guard); group defaults to the asset itself.
    - Hard cap of ``max_candidates`` overall.
    - Duplicates (same asset+strategy+direction) are dropped with a reason.
    """
    portfolio = CandidatePortfolio()
    seen: set[tuple[str, str, str]] = set()
    group_counts: dict[str, int] = {}

    ranked = sorted(candidates, key=lambda c: -float(c.score or 0.0))
    for cand in ranked:
        key = (cand.asset, cand.strategy_id, cand.direction)
        if key in seen:
            portfolio.rejected.append(
                {
                    "candidate": cand.to_dict(),
                    "reason": "duplicate_candidate",
                }
            )
            continue
        seen.add(key)

        group = cand.correlation_group or cand.asset
        count = group_counts.get(group, 0)
        if count >= max_per_correlation_group:
            portfolio.rejected.append(
                {
                    "candidate": cand.to_dict(),
                    "reason": f"correlation_group_limit:{group}",
                }
            )
            continue

        if len(portfolio.candidates) >= max_candidates:
            portfolio.rejected.append(
                {
                    "candidate": cand.to_dict(),
                    "reason": "portfolio_size_cap",
                }
            )
            continue

        group_counts[group] = count + 1
        portfolio.candidates.append(cand)

    # Consolidation metadata
    groups = list(group_counts)
    portfolio.concentration_max_per_group = max(group_counts.values()) if group_counts else 0
    if len(groups) == 1 and len(portfolio.candidates) > 1:
        portfolio.warnings.append(
            f"all candidates share correlation group '{groups[0]}' — duplicated crypto beta"
        )
        portfolio.overlapping_exposure_pct = 100.0
        portfolio.avg_pairwise_correlation = 1.0
    return portfolio
