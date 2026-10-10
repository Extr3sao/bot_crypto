"""Contracts for the RFC-048 futures risk plane.

These are pure data + vocabulary. No computation lives here, so both the builder
(``engine``/``margin``/``sizing``) and the integration adapter can depend on
them without depending on each other's arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "ContractType",
    "CostStatus",
    "DecisionLog",
    "Direction",
    "InstrumentNotSupported",
    "PositionMode",
    "RejectionCode",
    "RiskDecision",
    "RiskDecisionCode",
]


class ContractType(StrEnum):
    """Instrument families this RFC distinguishes. No aliasing is permitted."""

    SPOT = "SPOT"
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"
    DELIVERY_FUTURE = "DELIVERY_FUTURE"


class PositionMode(StrEnum):
    """Collateral mode. Cross is declared unsupported until its dependencies are
    validated (RFC-048 §10: "no declarar seguro el margen cruzado sin validar
    todas sus dependencias")."""

    ISOLATED = "ISOLATED"
    CROSS = "CROSS"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class CostStatus(StrEnum):
    """Honest cost state. Absence of data is never a zero cost."""

    COST_KNOWN = "COST_KNOWN"
    COST_ESTIMATED = "COST_ESTIMATED"
    COST_UNKNOWN = "COST_UNKNOWN"


class RiskDecisionCode(StrEnum):
    """The only decisions this engine is allowed to emit (§11).

    None of them authorises a live order: ``APPROVE_SIMULATION`` and
    ``REDUCE_SIMULATED_SIZE`` are simulation verdicts with
    ``order_authorised = False``.
    """

    APPROVE_SIMULATION = "APPROVE_SIMULATION"
    REDUCE_SIMULATED_SIZE = "REDUCE_SIMULATED_SIZE"
    NO_TRADE = "NO_TRADE"
    RISK_VETO = "RISK_VETO"
    DATA_INVALID = "DATA_INVALID"
    UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"


class RejectionCode(StrEnum):
    """Machine-readable reasons. Every refusal must name at least one."""

    INSTRUMENT_NOT_SUPPORTED = "INSTRUMENT_NOT_SUPPORTED"
    CONTRACT_TYPE_NOT_IMPLEMENTED = "CONTRACT_TYPE_NOT_IMPLEMENTED"
    POSITION_MODE_NOT_SUPPORTED = "POSITION_MODE_NOT_SUPPORTED"
    VENUE_OR_PRODUCT_NOT_ELIGIBLE = "VENUE_OR_PRODUCT_NOT_ELIGIBLE"
    STALE_DATA = "STALE_DATA"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    MISSING_MARK_PRICE = "MISSING_MARK_PRICE"
    INCOMPLETE_MARGIN_MODEL = "INCOMPLETE_MARGIN_MODEL"
    LIQUIDATION_RISK_UNKNOWN = "LIQUIDATION_RISK_UNKNOWN"
    PARTIAL_LIQUIDATION_UNSUPPORTED = "PARTIAL_LIQUIDATION_UNSUPPORTED"
    STOP_MISSING = "STOP_MISSING"
    STOP_TOO_CLOSE = "STOP_TOO_CLOSE"
    GAP_RESERVE_MISSING = "GAP_RESERVE_MISSING"
    COST_UNKNOWN = "COST_UNKNOWN"
    FUNDING_UNKNOWN = "FUNDING_UNKNOWN"
    INSUFFICIENT_EQUITY = "INSUFFICIENT_EQUITY"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    RISK_BUDGET_EXCEEDED = "RISK_BUDGET_EXCEEDED"
    BELOW_MIN_NOTIONAL = "BELOW_MIN_NOTIONAL"
    ABOVE_MAX_NOTIONAL = "ABOVE_MAX_NOTIONAL"
    INVALID_QUANTITY_STEP = "INVALID_QUANTITY_STEP"
    LEVERAGE_ABOVE_ALLOWED = "LEVERAGE_ABOVE_ALLOWED"
    LIQUIDATION_BEFORE_STOP = "LIQUIDATION_BEFORE_STOP"
    LIQUIDATION_BUFFER_TOO_SMALL = "LIQUIDATION_BUFFER_TOO_SMALL"
    GAP_BEYOND_STOP = "GAP_BEYOND_STOP"
    ADVERSE_FUNDING = "ADVERSE_FUNDING"
    BRACKET_CHANGE = "BRACKET_CHANGE"
    FEES_EXCEED_HORIZON_EDGE = "FEES_EXCEED_HORIZON_EDGE"
    LOSS_ABOVE_MARGIN = "LOSS_ABOVE_MARGIN"
    SHORT_UNBOUNDED = "SHORT_UNBOUNDED"
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
    CORRELATED_POSITIONS = "CORRELATED_POSITIONS"
    SHARED_COLLATERAL_CONFLICT = "SHARED_COLLATERAL_CONFLICT"
    MARGIN_UTILIZATION_LIMIT = "MARGIN_UTILIZATION_LIMIT"
    PORTFOLIO_SNAPSHOT_STALE = "PORTFOLIO_SNAPSHOT_STALE"
    MAX_POSITIONS = "MAX_POSITIONS"
    KILL_SWITCH = "KILL_SWITCH"
    LIVE_ROUTE_ATTEMPTED = "LIVE_ROUTE_ATTEMPTED"
    EXECUTION_NOT_PERMITTED = "EXECUTION_NOT_PERMITTED"


class InstrumentNotSupported(RuntimeError):
    """Raised when a contract type or position mode has no verified model."""

    def __init__(self, instrument_id: str, reason: str) -> None:
        super().__init__(f"INSTRUMENT_NOT_SUPPORTED {instrument_id}: {reason}")
        self.instrument_id = instrument_id
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The futures risk verdict (§11). Never an order authorisation."""

    decision_id: str
    run_id: str
    instrument_id: str
    proposed_direction: Direction
    requested_notional: float
    approved_notional: float
    requested_leverage: float
    effective_leverage: float
    required_margin: float
    risk_budget: float
    modeled_worst_loss: float
    liquidation_buffer_bps: float | None
    fees_estimate: float
    funding_estimate: float
    data_timestamp_ms: int
    decision_timestamp_ms: int
    policy_version: str
    decision: RiskDecisionCode
    rejection_reasons: tuple[RejectionCode, ...] = ()
    evidence: tuple[str, ...] = ()
    # -- execution shape (simulation only) ------------------------------------
    quantity: float = 0.0
    entry_price: float = 0.0
    stop_price: float | None = None
    liquidation_price: float | None = None
    maintenance_margin: float = 0.0
    cost_status: CostStatus = CostStatus.COST_UNKNOWN
    margin_utilization_pct: float | None = None
    gross_exposure_after: float | None = None
    net_exposure_after: float | None = None
    concentration_pct_after: float | None = None
    portfolio_snapshot_id: str = ""
    position_mode: PositionMode = PositionMode.ISOLATED
    #: A live order is never authorised by this contract; the field exists so the
    #: report can carry the invariant instead of implying it.
    order_authorised: bool = False

    @property
    def approved(self) -> bool:
        return self.decision in (
            RiskDecisionCode.APPROVE_SIMULATION,
            RiskDecisionCode.REDUCE_SIMULATED_SIZE,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "proposed_direction": self.proposed_direction.value,
            "requested_notional": self.requested_notional,
            "approved_notional": self.approved_notional,
            "requested_leverage": self.requested_leverage,
            "effective_leverage": self.effective_leverage,
            "required_margin": self.required_margin,
            "risk_budget": self.risk_budget,
            "modeled_worst_loss": self.modeled_worst_loss,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "fees_estimate": self.fees_estimate,
            "funding_estimate": self.funding_estimate,
            "data_timestamp_ms": self.data_timestamp_ms,
            "decision_timestamp_ms": self.decision_timestamp_ms,
            "policy_version": self.policy_version,
            "decision": self.decision.value,
            "rejection_reasons": [r.value for r in self.rejection_reasons],
            "evidence": list(self.evidence),
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "liquidation_price": self.liquidation_price,
            "maintenance_margin": self.maintenance_margin,
            "cost_status": self.cost_status.value,
            "margin_utilization_pct": self.margin_utilization_pct,
            "gross_exposure_after": self.gross_exposure_after,
            "net_exposure_after": self.net_exposure_after,
            "concentration_pct_after": self.concentration_pct_after,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "position_mode": self.position_mode.value,
            "order_authorised": self.order_authorised,
        }


@dataclass(frozen=True, slots=True)
class DecisionLog:
    """Wrapper so a caller can carry a decision plus the numbers behind it."""

    decision: RiskDecision
    detail: dict[str, Any] = field(default_factory=dict)
