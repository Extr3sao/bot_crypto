"""RFC-048 — Deterministic Futures Risk & Leverage Engine (offline plane).

This package is the *only* place where a futures position's size, margin,
liquidation risk and cost may be decided. It is deliberately separate from the
spot authority (``trading_bot.risk.manager.RiskManager``), which keeps sizing
spot signals and is not modified by RFC-048.

Hard rules enforced here:

* the agent plane may *propose* a direction and a leverage; it can never set
  leverage, size, margin or risk limits — the engine takes the minimum of every
  applicable limit;
* a worst-case loss that includes costs, adverse slippage and a gap reserve must
  fit inside the risk budget, or the position is refused;
* unknown costs are never zero costs: a missing component makes the position
  ``COST_UNKNOWN`` and it is refused;
* an incomplete liquidation model yields ``LIQUIDATION_RISK_UNKNOWN`` and blocks
  approval;
* nothing in this package can send an order, read a credential or reach a live
  venue. The only ``Order``-like object is a simulation verdict.
"""

from __future__ import annotations

from .contracts import (
    ContractType,
    CostStatus,
    Direction,
    InstrumentNotSupported,
    PositionMode,
    RejectionCode,
    RiskDecision,
    RiskDecisionCode,
)
from .costs import CostBreakdown, FundingContext, FuturesCostModel
from .engine import FuturesRiskEngine, FuturesRiskPolicy, RiskProposal, ScenarioRequest
from .instruments import (
    InstrumentRegistry,
    InstrumentSpec,
    MaintenanceBracket,
    load_instrument_registry,
)
from .margin import LiquidationAssessment, MarginModel, StressScenario
from .portfolio import MarginLedger, PortfolioSnapshot, PortfolioState
from .sizing import SizingResult, risk_bounded_sizing

__all__ = [
    "ContractType",
    "CostBreakdown",
    "CostStatus",
    "Direction",
    "FundingContext",
    "FuturesCostModel",
    "FuturesRiskEngine",
    "FuturesRiskPolicy",
    "InstrumentNotSupported",
    "InstrumentRegistry",
    "InstrumentSpec",
    "LiquidationAssessment",
    "MaintenanceBracket",
    "MarginLedger",
    "MarginModel",
    "PortfolioSnapshot",
    "PortfolioState",
    "PositionMode",
    "RejectionCode",
    "RiskDecision",
    "RiskDecisionCode",
    "RiskProposal",
    "ScenarioRequest",
    "SizingResult",
    "StressScenario",
    "load_instrument_registry",
    "risk_bounded_sizing",
]
