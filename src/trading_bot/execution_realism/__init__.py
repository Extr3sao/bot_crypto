"""execution_realism — diagnostic/authority contracts for EXECUTION-REALISM-AND-COST-AUTHORITY-01.

This package is RESEARCH/DIAGNOSTIC ONLY. It does NOT wire into PaperBroker
or live execution. All contracts are pure, deterministic, network-free, and
safe for unit tests.

Authority hierarchy enforced by this workstream:
  REAL_EXECUTION_EVIDENCE > EXCHANGE_DATA > OFFICIAL_EXCHANGE_DOC >
  RUNTIME_SOURCE > TESTS > ARCH/RFC > ASSUMPTION

Do not import H6, do not touch H6 thresholds, do not execute H6.
"""

from .cost_authority import (
    CostComponent,
    CostScenario,
    CostScenarioKind,
    ExchangeExecutionProfile,
    ExecutionCostAuthority,
)
from .funding import funding_cost_bps, funding_cost_usdt
from .realism_estimate import ExecutionRealismEstimate

__all__ = [
    "CostComponent",
    "CostScenario",
    "CostScenarioKind",
    "ExchangeExecutionProfile",
    "ExecutionCostAuthority",
    "ExecutionRealismEstimate",
    "funding_cost_bps",
    "funding_cost_usdt",
]
