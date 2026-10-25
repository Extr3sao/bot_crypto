"""RFC-030 — two-leg / market-neutral execution & accounting contracts.

Research/PAPER only. Nothing in this package can size, risk-check, execute or
promote a live strategy; no production runtime module imports it.

The package exists because a market-neutral result is not valid merely because
``long_pnl + short_pnl > 0``. Before any pair economic result can be trusted the
programme must model and reconcile, explicitly and deterministically:

* two coordinated legs with independent fill semantics (:mod:`simulator`);
* a short leg whose borrow/funding economics are **observed or blocked**, never
  silently assumed to be zero (:mod:`costs`);
* a pair ledger whose PnL reconciles to the leg-level arithmetic (:mod:`ledger`);
* a portfolio capital model with no ambiguous fixed-per-leg reference notional
  (:mod:`ledger`);
* a through-origin beta book with a fail-closed gate (:mod:`beta`).

The frozen EXP-ARP-023 contract lives in :mod:`instruments` as a *declaration*
only: it is ``BLOCKED`` because no authoritative historical borrow/funding series
exists in the corpus, and a guessed zero would be a false success.
"""

from __future__ import annotations

from .beta import (
    BetaBookResult,
    BetaDiagnostic,
    BetaGateDecision,
    BlockingReasons,
    PITUniverse,
    UniverseSnapshotLike,
    beta_book,
    beta_diagnostic,
    beta_gate,
    through_origin_beta,
)
from .borrow import (
    BorrowAvailability,
    BorrowDataQuality,
    BorrowGateDecision,
    BorrowRatePeriod,
    CoverageReport,
    ShortBorrowObservation,
    borrow_availability_gate,
    coverage_report,
    validate_pit,
)
from .costs import (
    PAIR_COST_MODEL_V1,
    CostKnowledge,
    PairCostBreakdown,
    PairCostModelV1,
    ShortLegCost,
)
from .instruments import (
    EXP_ARP_023_LONG_INSTRUMENT,
    EXP_ARP_023_SHORT_INSTRUMENT,
    InstrumentSubstitutionError,
    InstrumentType,
    LegInstrumentContract,
    Side,
    require_same_instrument,
)
from .ledger import (
    PairAccountingError,
    PairLedger,
    PairLedgerEntry,
    PortfolioState,
)
from .metrics import EquityMetrics, equity_metrics, max_drawdown
from .proposal import (
    FailurePolicy,
    LegImbalance,
    LegState,
    PairExecutionPlan,
    PairExecutionStatus,
    PairTradeProposal,
)
from .scenarios import (
    BoundScenario,
    ScenarioResult,
    borrow_cost_bounds,
)
from .simulator import (
    FillConfig,
    LegFill,
    PairExecutionResult,
    PairSimulator,
    SimulatedLegFill,
)
from .verifier import (
    FieldResidual,
    PairLedgerVerification,
    RawLedgerEntry,
    verify_ledger,
)

__all__ = [
    "EXP_ARP_023_LONG_INSTRUMENT",
    "EXP_ARP_023_SHORT_INSTRUMENT",
    "PAIR_COST_MODEL_V1",
    "BetaBookResult",
    "BetaDiagnostic",
    "BetaGateDecision",
    "BlockingReasons",
    "BorrowAvailability",
    "BorrowDataQuality",
    "BorrowGateDecision",
    "BorrowRatePeriod",
    "BoundScenario",
    "CostKnowledge",
    "CoverageReport",
    "EquityMetrics",
    "FailurePolicy",
    "FieldResidual",
    "FillConfig",
    "InstrumentSubstitutionError",
    "InstrumentType",
    "LegFill",
    "LegImbalance",
    "LegInstrumentContract",
    "LegState",
    "PITUniverse",
    "PairAccountingError",
    "PairCostBreakdown",
    "PairCostModelV1",
    "PairExecutionPlan",
    "PairExecutionResult",
    "PairExecutionStatus",
    "PairLedger",
    "PairLedgerEntry",
    "PairLedgerVerification",
    "PairSimulator",
    "PairTradeProposal",
    "PortfolioState",
    "RawLedgerEntry",
    "ScenarioResult",
    "ShortBorrowObservation",
    "ShortLegCost",
    "Side",
    "SimulatedLegFill",
    "UniverseSnapshotLike",
    "beta_book",
    "beta_diagnostic",
    "beta_gate",
    "borrow_availability_gate",
    "borrow_cost_bounds",
    "coverage_report",
    "equity_metrics",
    "max_drawdown",
    "require_same_instrument",
    "through_origin_beta",
    "validate_pit",
    "verify_ledger",
]
