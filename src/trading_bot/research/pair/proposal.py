"""RFC-030 §9/§10/§26/§27/§28 — pair proposal, execution plan and leg lifecycle.

These are pure, deterministic data contracts. They carry no clock and no I/O, so
two runs over the same inputs produce byte-identical plans. The execution states
make an important guarantee explicit: a pair is only ``PAIR_FILLED`` when **both**
legs satisfy the execution contract; a single filled leg is never recorded as a
full pair (§26, §29).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .instruments import LegInstrumentContract

__all__ = [
    "FailurePolicy",
    "LegImbalance",
    "LegState",
    "PairExecutionPlan",
    "PairExecutionStatus",
    "PairTradeProposal",
]


class PairExecutionStatus(StrEnum):
    """§26 — the only legal states of a pair's execution."""

    PENDING = "PENDING"
    LONG_FILLED_SHORT_PENDING = "LONG_FILLED_SHORT_PENDING"
    SHORT_FILLED_LONG_PENDING = "SHORT_FILLED_LONG_PENDING"
    PARTIAL_LONG = "PARTIAL_LONG"
    PARTIAL_SHORT = "PARTIAL_SHORT"
    BOTH_FILLED = "BOTH_FILLED"
    PAIR_FAILED = "PAIR_FAILED"

    @property
    def is_filled(self) -> bool:
        """True only when both legs are fully filled — never for a one-leg state."""
        return self is PairExecutionStatus.BOTH_FILLED


class LegState(StrEnum):
    """Independent lifecycle of one leg."""

    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    FAILED = "FAILED"


class FailurePolicy(StrEnum):
    """§28 — allowed research/PAPER policies. No unlimited retries, no silent leg."""

    ABORT_PAIR = "ABORT_PAIR"
    CLOSE_FILLED_LEG = "CLOSE_FILLED_LEG"
    RETRY_WITHIN_TIMEOUT = "RETRY_WITHIN_TIMEOUT"


@dataclass(frozen=True, slots=True)
class LegImbalance:
    """§27 — deterministic leg-imbalance metrics (thresholds come from config)."""

    target_long_notional: float
    actual_long_notional: float
    target_short_notional: float
    actual_short_notional: float
    net_imbalance: float
    beta_imbalance: float
    max_allowed_imbalance: float

    def __post_init__(self) -> None:
        if self.max_allowed_imbalance < 0.0:
            raise ValueError("max_allowed_imbalance must be >= 0")

    @property
    def within_tolerance(self) -> bool:
        return abs(self.net_imbalance) <= self.max_allowed_imbalance + 1e-9

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "target_long_notional": self.target_long_notional,
            "actual_long_notional": self.actual_long_notional,
            "target_short_notional": self.target_short_notional,
            "actual_short_notional": self.actual_short_notional,
            "net_imbalance": self.net_imbalance,
            "beta_imbalance": self.beta_imbalance,
            "max_allowed_imbalance": self.max_allowed_imbalance,
            "within_tolerance": self.within_tolerance,
        }


@dataclass(frozen=True, slots=True)
class PairTradeProposal:
    """§9 — a two-leg market-neutral trade proposal (decision-time only)."""

    proposal_id: str
    strategy_id: str
    decision_time: int
    long_leg: LegInstrumentContract
    short_leg: LegInstrumentContract
    long_target_notional: float
    short_target_notional: float
    expected_beta: float
    beta_tolerance: float
    evidence: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    invalidation: str = ""
    cost_estimate_bps: float = 0.0
    data_fingerprints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.long_leg.side.value != "LONG" or self.short_leg.side.value != "SHORT":
            raise ValueError("a proposal must pair a LONG leg with a SHORT leg")
        if self.long_target_notional < 0.0 or self.short_target_notional < 0.0:
            raise ValueError("target notionals must be >= 0")
        if self.beta_tolerance < 0.0:
            raise ValueError("beta_tolerance must be >= 0")

    @property
    def gross_target_exposure(self) -> float:
        """§20 — gross = long notional + short notional (never 'leverage')."""
        return self.long_target_notional + self.short_target_notional

    @property
    def net_target_exposure(self) -> float:
        """§21 — net = long notional - short notional (signed)."""
        return self.long_target_notional - self.short_target_notional

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "strategy_id": self.strategy_id,
            "decision_time": self.decision_time,
            "long_leg": self.long_leg.as_dict(),
            "short_leg": self.short_leg.as_dict(),
            "long_target_notional": self.long_target_notional,
            "short_target_notional": self.short_target_notional,
            "gross_target_exposure": self.gross_target_exposure,
            "net_target_exposure": self.net_target_exposure,
            "expected_beta": self.expected_beta,
            "beta_tolerance": self.beta_tolerance,
            "evidence": list(self.evidence),
            "counter_evidence": list(self.counter_evidence),
            "invalidation": self.invalidation,
            "cost_estimate_bps": self.cost_estimate_bps,
            "data_fingerprints": list(self.data_fingerprints),
        }


@dataclass(frozen=True, slots=True)
class PairExecutionPlan:
    """§10 — deterministic, replayable execution plan for one proposal."""

    execution_id: str
    proposal: PairTradeProposal
    execution_sequence: tuple[str, ...]
    long_target_qty: float
    short_target_qty: float
    expected_fees: float
    expected_spread: float
    expected_slippage: float
    borrow_requirement: float
    funding_assumption: float
    maximum_allowed_leg_imbalance: float
    timeout_ms: int
    failure_policy: FailurePolicy
    metadata: tuple[tuple[str, str], ...] = field(default=())

    def __post_init__(self) -> None:
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be > 0")
        if self.long_target_qty < 0.0 or self.short_target_qty < 0.0:
            raise ValueError("target quantities must be >= 0")
        if self.maximum_allowed_leg_imbalance < 0.0:
            raise ValueError("maximum_allowed_leg_imbalance must be >= 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "proposal": self.proposal.as_dict(),
            "execution_sequence": list(self.execution_sequence),
            "long_target_qty": self.long_target_qty,
            "short_target_qty": self.short_target_qty,
            "expected_fees": self.expected_fees,
            "expected_spread": self.expected_spread,
            "expected_slippage": self.expected_slippage,
            "borrow_requirement": self.borrow_requirement,
            "funding_assumption": self.funding_assumption,
            "maximum_allowed_leg_imbalance": self.maximum_allowed_leg_imbalance,
            "timeout_ms": self.timeout_ms,
            "failure_policy": self.failure_policy.value,
            "metadata": {k: v for k, v in self.metadata},
        }
