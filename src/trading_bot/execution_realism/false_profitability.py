"""FalseProfitabilityDetector — offline diagnostic §32.

Classifies a strategy result under a given execution cost authority without
executing or re-running the strategy.

Do NOT use on H6 before H6 is legally executed and external V2 verification passes.
Allowed inputs: synthetic fixtures + already-authorized historical results (H1/H3/carry-deep).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProfitabilityVerdict(str, Enum):
    ROBUST_POSITIVE = "ROBUST_POSITIVE"  # positive even at STRESSED/SEVERE
    COST_SENSITIVE = "COST_SENSITIVE"  # positive at BASE but negative at STRESSED
    NEGATIVE_AFTER_COSTS = "NEGATIVE_AFTER_COSTS"  # negative at BASE
    INSUFFICIENT_EXECUTION_EVIDENCE = "INSUFFICIENT_EXECUTION_EVIDENCE"  # cost unknown
    GROSS_NEGATIVE = "GROSS_NEGATIVE"  # already negative before costs


@dataclass(frozen=True, slots=True)
class StrategyCostInput:
    """Minimal strategy summary needed for cost realism classification."""

    gross_edge_bps: float | None  # per-trade gross edge in bps of notional (None => unknown)
    gross_pf: float | None = None  # for context only
    n_trades: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionCostInput:
    """Cost authority summary needed for classification."""

    base_cost_bps: float | None
    stressed_cost_bps: float | None = None
    severe_cost_bps: float | None = None
    is_unknown: bool = False  # True when historical spread/slippage authority unavailable


def classify(
    strategy: StrategyCostInput,
    costs: ExecutionCostInput,
) -> ProfitabilityVerdict:
    if costs.is_unknown or costs.base_cost_bps is None:
        return ProfitabilityVerdict.INSUFFICIENT_EXECUTION_EVIDENCE
    if strategy.gross_edge_bps is None:
        return ProfitabilityVerdict.INSUFFICIENT_EXECUTION_EVIDENCE
    if strategy.gross_edge_bps <= 0:
        return ProfitabilityVerdict.GROSS_NEGATIVE

    net_base = strategy.gross_edge_bps - costs.base_cost_bps
    if net_base <= 0:
        return ProfitabilityVerdict.NEGATIVE_AFTER_COSTS

    # If no stressed bound, we can only say cost-sensitive at best
    if costs.stressed_cost_bps is None:
        return ProfitabilityVerdict.COST_SENSITIVE

    net_stressed = strategy.gross_edge_bps - costs.stressed_cost_bps
    if net_stressed <= 0:
        return ProfitabilityVerdict.COST_SENSITIVE

    # Optionally check severe
    if costs.severe_cost_bps is not None:
        net_severe = strategy.gross_edge_bps - costs.severe_cost_bps
        if net_severe <= 0:
            return ProfitabilityVerdict.COST_SENSITIVE

    return ProfitabilityVerdict.ROBUST_POSITIVE
