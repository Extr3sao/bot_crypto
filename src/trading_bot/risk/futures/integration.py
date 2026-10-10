"""WP-048-08 — how the futures engine plugs into the REAL decision boundary.

This adapter touches no new authority: it converts a futures ``RiskDecision``
into the existing ``trading_bot.autonomous.contracts.RiskReview`` and hands it to
the existing ``DecisionEngine`` together with a real ``DecisionRequest``. That is
the same object graph the autonomous paper runtime builds, so reachability is
demonstrated on the production contracts rather than on a private harness.

Two deliberate properties:

* the review is ``advisory`` — a simulation verdict can never authorise an order,
  and ``DecisionEngine`` itself refuses an advisory review on an order-authorising
  packet, so this adapter cannot be used to smuggle a futures approval into the
  paper book;
* the ``UNSUPPORTED_INSTRUMENT`` decision maps to a VETO with the reason spelled
  out, so a refused contract type is visible in the trace instead of silently
  becoming a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_bot.autonomous.contracts import (
    AdmissionEntry,
    AdmissionStatus,
    CostBreakdown,
    DecisionMode,
    EdgeEvidence,
    RiskReview,
    RiskVerdict,
    TradeProposal,
    VerificationResult,
    VerifierVerdict,
)
from trading_bot.autonomous.decision import DecisionRequest, DecisionResult

from .contracts import RiskDecision, RiskDecisionCode

__all__ = [
    "INTEGRATION_VERSION",
    "build_decision_request",
    "build_decision_request_from_review",
    "run_engine_through_runtime",
    "run_through_decision_engine",
    "safe_review",
    "to_review_from_error",
    "to_risk_review",
]

INTEGRATION_VERSION = "RFC048-DECISION-ENGINE-ADAPTER-v1"

#: Futures decisions → the deterministic verdict vocabulary of the runtime.
_VERDICT_BY_DECISION: dict[RiskDecisionCode, RiskVerdict] = {
    RiskDecisionCode.APPROVE_SIMULATION: RiskVerdict.PASS,
    RiskDecisionCode.REDUCE_SIMULATED_SIZE: RiskVerdict.ADJUST,
    RiskDecisionCode.NO_TRADE: RiskVerdict.VETO,
    RiskDecisionCode.RISK_VETO: RiskVerdict.VETO,
    RiskDecisionCode.DATA_INVALID: RiskVerdict.VETO,
    RiskDecisionCode.UNSUPPORTED_INSTRUMENT: RiskVerdict.VETO,
}

_RULE_BY_DECISION: dict[RiskDecisionCode, str] = {
    RiskDecisionCode.APPROVE_SIMULATION: "futures_risk_budget",
    RiskDecisionCode.REDUCE_SIMULATED_SIZE: "futures_risk_budget",
    RiskDecisionCode.NO_TRADE: "futures_risk_gate",
    RiskDecisionCode.RISK_VETO: "futures_liquidation_and_margin",
    RiskDecisionCode.DATA_INVALID: "futures_data_validity",
    RiskDecisionCode.UNSUPPORTED_INSTRUMENT: "futures_instrument_capability",
}


def to_risk_review(
    decision: RiskDecision, *, instrument_status: str = "PRODUCT_ELIGIBILITY_UNKNOWN"
) -> RiskReview:
    """Map a futures decision onto the runtime's ``RiskReview`` contract."""
    verdict = _VERDICT_BY_DECISION[decision.decision]
    reason_codes = ",".join(r.value for r in decision.rejection_reasons)
    reason = (
        f"{decision.decision.value}"
        + (f":{reason_codes}" if reason_codes else "")
        + f" (policy {decision.policy_version})"
    )
    return RiskReview(
        verdict=verdict,
        reason=reason,
        notional_usdt=(
            decision.approved_notional
            if decision.decision is not RiskDecisionCode.NO_TRADE
            else None
        ),
        source=f"FuturesRiskEngine[{INTEGRATION_VERSION}]",
        # Advisory by construction: RFC-048 authorises simulation scenarios only,
        # and the runtime refuses an advisory review on an order-authorising
        # packet, so this can never place an order.
        advisory=True,
        evaluated=True,
        rule=_RULE_BY_DECISION[decision.decision],
        inputs={
            "decision_id": decision.decision_id,
            "instrument_id": decision.instrument_id,
            "decision": decision.decision.value,
            "requested_leverage": decision.requested_leverage,
            "effective_leverage": decision.effective_leverage,
            "approved_notional": decision.approved_notional,
            "required_margin": decision.required_margin,
            "liquidation_buffer_bps": decision.liquidation_buffer_bps,
            "cost_status": decision.cost_status.value,
            "instrument_regulatory_status": instrument_status,
            "order_authorised": decision.order_authorised,
        },
    )


def build_decision_request_from_review(
    *,
    review: RiskReview,
    stop_price: float | None,
    cost_scenario_id: str,
    size_usd_hint: float,
    instrument_status: str = "PRODUCT_ELIGIBILITY_UNKNOWN",
    strategy_id: str,
    run_id: str,
    decision_id: str,
    asset: str,
    symbol: str,
    direction: str,
    entry_reference: float,
    expected_gross_edge_bps: float,
    expected_cost_bps: float,
    market_time_ms: int,
    holistic_time_ms: int,
    admission_status: AdmissionStatus = AdmissionStatus.RESEARCH_REQUIRED,
    admitted_for_paper: bool = False,
    edge_source_doc: str = "",
    regime: str | None = None,
) -> DecisionRequest:
    """Assemble the real ``DecisionRequest`` around ANY review.

    This is the seam the fail-safe path needs: a review produced by an engine
    error must be able to sit on a real packet, so the runtime can fail closed
    instead of crashing or (worse) reporting a pass.

    The default admission is ``RESEARCH_REQUIRED`` / not admitted: the futures
    engine must be reachable from the decision boundary WITHOUT creating an
    admission that would let a paper order follow.
    """
    proposal = TradeProposal(
        run_id=run_id,
        decision_id=decision_id,
        asset=asset,
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="rfc048-offline",
        family="futures_risk_probe",
        direction=direction,
        timeframe="5m",
        market_time_ms=market_time_ms,
        decision_time_ms=holistic_time_ms,
        entry_reference=entry_reference,
        structural_stop=stop_price,
        horizon_minutes=60.0,
        expected_gross_edge_bps=expected_gross_edge_bps,
        expected_cost_bps=expected_cost_bps,
        expected_net_edge_bps=expected_gross_edge_bps - expected_cost_bps,
        cost=CostBreakdown(
            scenario_id=cost_scenario_id,
            cost_model_version="FUTURES_COST_MODEL_RFC048_V1",
            size_usd=size_usd_hint,
            horizon_minutes=60.0,
            spread_bps=0.0,
            spread_knowledge="MEASURED_SNAPSHOT",
            fee_bps=0.0,
            slippage_bps=0.0,
            impact_bps=0.0,
            funding_bps=0.0,
            round_trip_bps=expected_cost_bps,
            created_at_ms=holistic_time_ms,
        ),
        edge_evidence=EdgeEvidence(
            source_doc=edge_source_doc or "data/rfc048/RFC048_SYNTHETIC_EDGE.md",
            metric="synthetic_probe_edge_bps",
            value_bps=expected_gross_edge_bps,
            knowledge="ASSUMPTION",
            sample_trades=0,
            note=(
                "offline probe: this edge is an assumption used to exercise the risk "
                "boundary, not a measured strategy result and never a selection input"
            ),
            evidence_class="ASSUMPTION",
            period="n/a",
            timeframe="5m",
            status="NOT_A_TRADING_SIGNAL",
        ),
        admission_status=admission_status,
        regime=regime,
        confidence=0.0,
        evidence=("rfc048:offline_risk_probe",),
        counter_evidence=("RFC-046 discovery campaign failed; no strategy is admitted for paper",),
    )
    admission = AdmissionEntry(
        strategy_id=strategy_id,
        family="futures_risk_probe",
        status=admission_status,
        admitted_for_paper=admitted_for_paper,
        expected_gross_edge_bps=expected_gross_edge_bps,
        edge_evidence=None,
        source_doc=edge_source_doc or "data/rfc048/RFC048_SYNTHETIC_EDGE.md",
        rationale="RFC-048 offline reachability probe (no admission requested)",
    )
    return DecisionRequest(
        run_id=run_id,
        decision_id=decision_id,
        asset=asset,
        symbol=symbol,
        market_time_ms=market_time_ms,
        decision_time_ms=holistic_time_ms,
        regime=regime,
        admission=admission,
        proposal=proposal,
        verification=VerificationResult(
            decision_id=decision_id,
            verdict=VerifierVerdict.PASS,
            verifier_version="rfc048-offline-probe",
        ),
        risk=review,
    )


def build_decision_request(
    *,
    decision: RiskDecision,
    instrument_status: str = "PRODUCT_ELIGIBILITY_UNKNOWN",
    strategy_id: str,
    run_id: str,
    decision_id: str,
    asset: str,
    symbol: str,
    direction: str,
    entry_reference: float,
    expected_gross_edge_bps: float,
    expected_cost_bps: float,
    market_time_ms: int,
    holistic_time_ms: int,
    admission_status: AdmissionStatus = AdmissionStatus.RESEARCH_REQUIRED,
    admitted_for_paper: bool = False,
    edge_source_doc: str = "",
    regime: str | None = None,
) -> DecisionRequest:
    """Assemble the real ``DecisionRequest`` from a futures decision."""
    return build_decision_request_from_review(
        review=to_risk_review(decision, instrument_status=instrument_status),
        stop_price=decision.stop_price,
        cost_scenario_id=decision.decision_id,
        size_usd_hint=decision.approved_notional or decision.requested_notional,
        instrument_status=instrument_status,
        strategy_id=strategy_id,
        run_id=run_id,
        decision_id=decision_id,
        asset=asset,
        symbol=symbol,
        direction=direction,
        entry_reference=entry_reference,
        expected_gross_edge_bps=expected_gross_edge_bps,
        expected_cost_bps=expected_cost_bps,
        market_time_ms=market_time_ms,
        holistic_time_ms=holistic_time_ms,
        admission_status=admission_status,
        admitted_for_paper=admitted_for_paper,
        edge_source_doc=edge_source_doc,
        regime=regime,
    )


def to_review_from_error(exc: BaseException) -> RiskReview:
    """Turn an engine failure into a BINDING veto (fail-safe, not fail-open).

    The review is deliberately NOT advisory: an advisory veto can never block
    anything, so an engine error that did not know what to do would become an
    error the runtime is allowed to ignore. It is also ``evaluated=False``: no
    verdict was produced, and the trace must not claim one was.
    (RFC-048V §02: an engine error produces a safe rejection.)
    """
    return RiskReview(
        verdict=RiskVerdict.VETO,
        reason=f"FUTURES_ENGINE_ERROR:{type(exc).__name__}: {exc}",
        notional_usdt=None,
        source=f"FuturesRiskEngine[{INTEGRATION_VERSION}]",
        advisory=False,
        evaluated=False,
        rule="futures_engine_fail_safe",
        inputs={
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "order_authorised": False,
        },
    )


def safe_review(
    evaluate: Callable[[], RiskDecision],
    *,
    instrument_status: str = "PRODUCT_ELIGIBILITY_UNKNOWN",
) -> RiskReview:
    """Run the engine and never let a failure escape as anything but a veto."""
    try:
        return to_risk_review(evaluate(), instrument_status=instrument_status)
    except Exception as exc:  # failing safe is the whole point
        return to_review_from_error(exc)


def run_engine_through_runtime(
    *,
    evaluate: Callable[[], RiskDecision],
    build: Callable[[RiskReview], DecisionRequest],
) -> DecisionResult:
    """Engine + fail-safe + the REAL ``DecisionEngine``, in one call.

    ``build`` receives the review (a real verdict or a fail-safe veto) and must
    return the packet the runtime would evaluate. The result always has
    ``order_authorised=False`` unless a formal admission genuinely passed the
    runtime's own gates.
    """
    return run_through_decision_engine(build(safe_review(evaluate)))


def run_through_decision_engine(request: DecisionRequest) -> DecisionResult:
    """Run the REAL ``DecisionEngine`` on the packet and return its verdict."""
    from trading_bot.autonomous.decision import DecisionEngine

    engine = DecisionEngine()
    return engine.decide(request)


def decision_mode_probe(result: DecisionResult) -> dict[str, Any]:
    """Compact, JSON-safe record of what the runtime actually decided."""
    return {
        "mode": result.mode.value,
        "classification": result.classification,
        "reason": result.reason,
        "order_authorised": result.order_authorised,
        "notional_usdt": result.notional_usdt,
        "is_no_trade": result.mode is DecisionMode.NO_TRADE,
        "no_trade_kind": (result.no_trade_kind.value if result.no_trade_kind is not None else None),
    }
