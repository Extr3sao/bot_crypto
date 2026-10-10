"""WP-048-08 — the futures engine must be reachable from the REAL decision flow.

These tests use the runtime's own contracts (``RiskReview``, ``DecisionRequest``,
``DecisionEngine``) rather than a private harness, and they pin the property that
matters: the futures review can inform a decision and can never authorise an
order, because the runtime refuses an advisory review on an order-authorising
packet.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from trading_bot.autonomous.contracts import AdmissionStatus, EdgeEvidence, RiskVerdict
from trading_bot.autonomous.decision import DecisionEngine, DecisionMode
from trading_bot.risk.futures.contracts import (
    CostStatus,
    Direction,
    RejectionCode,
    RiskDecision,
    RiskDecisionCode,
)
from trading_bot.risk.futures.integration import (
    build_decision_request,
    decision_mode_probe,
    run_through_decision_engine,
    to_risk_review,
)

pytestmark = pytest.mark.unit


def make_decision(**overrides: object) -> RiskDecision:
    base = RiskDecision(
        decision_id="INT-DEC-001",
        run_id="INT-RUN-001",
        instrument_id="BINANCE_USDM_BTCUSDT_PERP",
        proposed_direction=Direction.LONG,
        requested_notional=400.0,
        approved_notional=82.5,
        requested_leverage=5.0,
        effective_leverage=5.0,
        required_margin=16.5,
        risk_budget=2.0,
        modeled_worst_loss=0.74,
        liquidation_buffer_bps=2093.37,
        fees_estimate=0.0825,
        funding_estimate=0.0,
        data_timestamp_ms=1_791_582_761_730,
        decision_timestamp_ms=1_791_582_762_730,
        policy_version="RFC048-FUTURES-RISK-POLICY-v1",
        decision=RiskDecisionCode.REDUCE_SIMULATED_SIZE,
        quantity=0.001,
        entry_price=82_500.04923188,
        stop_price=82_087.5489857206,
        liquidation_price=65_229.70760050753,
        maintenance_margin=0.33,
        cost_status=CostStatus.COST_ESTIMATED,
    )
    return replace(base, **overrides)


def build_request(decision: RiskDecision):
    return build_decision_request(
        decision=decision,
        instrument_status="PRODUCT_ELIGIBILITY_UNKNOWN",
        strategy_id="rfc048_offline_probe",
        run_id=decision.run_id,
        decision_id=decision.decision_id,
        asset="BTC",
        symbol="BTCUSDT",
        direction=decision.proposed_direction.value,
        entry_reference=decision.entry_price,
        expected_gross_edge_bps=40.0,
        expected_cost_bps=12.0,
        market_time_ms=decision.data_timestamp_ms,
        holistic_time_ms=decision.decision_timestamp_ms,
        admission_status=AdmissionStatus.RESEARCH_REQUIRED,
        admitted_for_paper=False,
    )


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (RiskDecisionCode.APPROVE_SIMULATION, RiskVerdict.PASS),
        (RiskDecisionCode.REDUCE_SIMULATED_SIZE, RiskVerdict.ADJUST),
        (RiskDecisionCode.NO_TRADE, RiskVerdict.VETO),
        (RiskDecisionCode.RISK_VETO, RiskVerdict.VETO),
        (RiskDecisionCode.DATA_INVALID, RiskVerdict.VETO),
        (RiskDecisionCode.UNSUPPORTED_INSTRUMENT, RiskVerdict.VETO),
    ],
)
def test_every_decision_maps_to_a_real_review(code: RiskDecisionCode, verdict: RiskVerdict) -> None:
    """No futures verdict may be lost on the way into the runtime vocabulary."""
    decision = make_decision(
        decision=code,
        rejection_reasons=()
        if code is RiskDecisionCode.APPROVE_SIMULATION
        else (RejectionCode.RISK_VETO if False else RejectionCode.COST_UNKNOWN,),
    )
    review = to_risk_review(decision)
    assert review.verdict is verdict
    assert review.evaluated is True
    assert review.rule
    assert review.advisory is True
    assert review.source.startswith("FuturesRiskEngine")
    if verdict is RiskVerdict.VETO:
        assert review.reason  # a veto must state its reason
    assert review.inputs["order_authorised"] is False


def test_review_is_advisory_and_cannot_authorise() -> None:
    """The runtime refuses an advisory review on an order-authorising packet."""
    decision = make_decision(decision=RiskDecisionCode.APPROVE_SIMULATION)
    review = to_risk_review(decision)
    assert review.binding is False

    request = build_request(decision)
    engine = DecisionEngine()
    result = engine.decide(request)
    # Not admitted for paper + not order-authorising ⇒ the advisory review is
    # legal and the runtime cannot place an order from it.
    assert result.order_authorised is False
    assert result.mode in {DecisionMode.SHADOW_TRADE, DecisionMode.NO_TRADE}
    probe = decision_mode_probe(result)
    assert probe["order_authorised"] is False


def test_advisory_futures_review_cannot_sit_on_an_order_authorising_packet() -> None:
    """An admitted candidate + positive net edge would raise, not silently trade.

    This is the property that keeps RFC-048 inside its governance envelope: the
    adapter is advisory, and the runtime itself refuses to let an advisory review
    sit on a packet that could produce an order.
    """
    decision = make_decision(decision=RiskDecisionCode.APPROVE_SIMULATION)
    request = build_request(decision)
    admitting = replace(
        request,
        admission=replace(
            request.admission,
            status=AdmissionStatus.PAPER_CANDIDATE,
            admitted_for_paper=True,
            edge_evidence=EdgeEvidence(
                source_doc="data/rfc048/RFC048_SYNTHETIC_EDGE.md",
                metric="synthetic_probe_edge_bps",
                value_bps=40.0,
                knowledge="ASSUMPTION",
                sample_trades=0,
                evidence_class="ASSUMPTION",
                status="NOT_A_TRADING_SIGNAL",
            ),
        ),
    )
    with pytest.raises(ValueError, match="advisory risk review"):
        DecisionEngine().decide(admitting)


def test_unsupported_instrument_is_visible_in_the_trace() -> None:
    """A refused contract type reaches the trace as a veto with its reason."""
    decision = make_decision(
        decision=RiskDecisionCode.UNSUPPORTED_INSTRUMENT,
        approved_notional=0.0,
        quantity=0.0,
        required_margin=0.0,
        rejection_reasons=(RejectionCode.CONTRACT_TYPE_NOT_IMPLEMENTED,),
    )
    review = to_risk_review(decision)
    assert review.verdict is RiskVerdict.VETO
    assert "CONTRACT_TYPE_NOT_IMPLEMENTED" in review.reason
    assert review.inputs["instrument_regulatory_status"] == "PRODUCT_ELIGIBILITY_UNKNOWN"


def test_a_binding_futures_veto_reaches_the_decision_engine() -> None:
    """A DATA_INVALID verdict from the futures gate becomes a NO_TRADE packet.

    The shipped adapter is advisory (so the probe can never order). The SAME
    verdict, converted to a binding review, must produce ``RISK_VETO`` — that is
    the behaviour a future RFC/ADR would rely on.
    """
    decision = make_decision(
        decision=RiskDecisionCode.DATA_INVALID,
        approved_notional=0.0,
        quantity=0.0,
        required_margin=0.0,
        rejection_reasons=(RejectionCode.STALE_DATA,),
    )
    request = build_request(decision)

    advisory_result = run_through_decision_engine(request)
    assert advisory_result.order_authorised is False

    binding_request = replace(request, risk=replace(request.risk, advisory=False))
    binding_result = run_through_decision_engine(binding_request)
    assert binding_result.mode is DecisionMode.NO_TRADE
    assert binding_result.classification == "RISK_VETO"
    assert binding_result.order_authorised is False
    assert binding_result.no_trade_kind is not None
