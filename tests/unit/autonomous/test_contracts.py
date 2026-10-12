"""Contract tests: the frozen shapes that make false success impossible."""

from __future__ import annotations

import pytest

from trading_bot.autonomous.contracts import (
    AdmissionStatus,
    AgentCapability,
    AgentMessage,
    CostBreakdown,
    DecisionMode,
    DecisionTrace,
    EdgeEvidence,
    NoTradeKind,
    OutcomeRecord,
    OutcomeStatus,
    ReviewType,
    RiskReview,
    RiskVerdict,
    ShadowTradeDecision,
    TradeProposal,
    VerificationResult,
    VerifierVerdict,
)

from .helpers import make_ledger


def _cost() -> CostBreakdown:
    return CostBreakdown(
        scenario_id="BINANCE_SPOT_STANDARD_TAKER",
        cost_model_version="COST_MODEL_V3",
        size_usd=1_000.0,
        horizon_minutes=5.0,
        spread_bps=1.0,
        spread_knowledge="OBSERVED",
        fee_bps=20.0,
        slippage_bps=1.0,
        impact_bps=0.1,
        funding_bps=0.0,
        round_trip_bps=21.1,
        components=(
            {
                "name": "exchange_fee_entry",
                "value_bps": 10.0,
                "knowledge": "KNOWN",
                "source_id": "SRC-01",
                "note": "unit-test",
            },
            {
                "name": "exchange_fee_exit",
                "value_bps": 10.0,
                "knowledge": "KNOWN",
                "source_id": "SRC-01",
                "note": "unit-test",
            },
            {
                "name": "spread",
                "value_bps": 1.0,
                "knowledge": "OBSERVED",
                "source_id": "SRC-07",
                "note": "unit-test",
            },
            {
                "name": "slippage",
                "value_bps": 0.1,
                "knowledge": "ESTIMATED",
                "source_id": "MODEL-V3",
                "note": "unit-test",
            },
        ),
    )


def _proposal(**overrides: object) -> TradeProposal:
    base: dict[str, object] = {
        "run_id": "run-1",
        "decision_id": "d-1",
        "asset": "BTC",
        "symbol": "BTC/USDT",
        "strategy_id": "ema_crossover@5m",
        "strategy_version": "5m",
        "family": "ema_crossover",
        "direction": "LONG",
        "timeframe": "5m",
        "market_time_ms": 1_000,
        "decision_time_ms": 2_000,
        "entry_reference": 100.0,
        "structural_stop": 99.0,
        "horizon_minutes": 5.0,
        "expected_gross_edge_bps": 4.0,
        "expected_cost_bps": 21.1,
        "expected_net_edge_bps": -17.1,
        "cost": _cost(),
        "edge_evidence": EdgeEvidence(
            source_doc="docs/TEST_EVIDENCE.json",
            metric="gross_bps_per_trade",
            value_bps=4.0,
            knowledge="ESTIMATED",
            sample_trades=1000,
        ),
        "admission_status": AdmissionStatus.COST_KILLED,
        "evidence": ("admission_ledger:test",),
    }
    base.update(overrides)
    return TradeProposal(**base)  # type: ignore[arg-type]


def test_proposal_requires_consistent_arithmetic() -> None:
    with pytest.raises(ValueError, match="must equal gross - cost"):
        _proposal(expected_net_edge_bps=0.0)


def test_proposal_rejects_future_market_time() -> None:
    with pytest.raises(ValueError, match="point-in-time violation"):
        _proposal(market_time_ms=3_000, decision_time_ms=2_000)


def test_proposal_requires_evidence() -> None:
    with pytest.raises(ValueError, match="without evidence"):
        _proposal(evidence=())


def test_proposal_round_trip_is_lossless() -> None:
    proposal = _proposal()
    rebuilt = TradeProposal.from_dict(proposal.to_dict())
    assert rebuilt == proposal
    assert isinstance(rebuilt.cost.components, tuple)


def test_shadow_decision_must_be_marked_shadow() -> None:
    with pytest.raises(ValueError, match="marked SHADOW"):
        ShadowTradeDecision(
            run_id="run-1",
            decision_id="d-1",
            timestamp_ms=2_000,
            asset="BTC",
            strategy_id="ema_crossover@5m",
            strategy_version="5m",
            direction="LONG",
            hypothetical_entry=100.0,
            expected_edge_bps=4.0,
            expected_cost_bps=21.1,
            expected_net_edge_bps=-17.1,
            regime="RANGE",
            evidence=(),
            counter_evidence=(),
            confidence=0.5,
            rejection_reason="COST_KILLED",
            admission_status=AdmissionStatus.COST_KILLED,
            decision_time_ms=2_000,
            marked_shadow=False,
        )


def _trace(**overrides: object) -> DecisionTrace:
    base: dict[str, object] = {
        "run_id": "run-1",
        "decision_id": "d-1",
        "asset": "BTC",
        "symbol": "BTC/USDT",
        "market_time_ms": 1_000,
        "decision_time_ms": 2_000,
        "mode": DecisionMode.NO_TRADE,
        "reason": "no_proposal",
        "classification": "NO_PROPOSAL",
        "regime": "RANGE",
        "strategies_considered": (),
        "market_context": {},
        "asset_context": {},
        "proposal": None,
        "agent_messages": (),
        "evidence": (),
        "counter_evidence": (),
        "verification": VerificationResult(
            decision_id="d-1", verdict=VerifierVerdict.NOT_RUN
        ).to_dict(),
        "risk": RiskReview(verdict=RiskVerdict.NOT_APPLICABLE).to_dict(),
        "shadow": None,
        "cost_model_version": "COST_MODEL_V3",
        "order_created": False,
        "orders_created": 0,
    }
    base.update(overrides)
    return DecisionTrace(**base)  # type: ignore[arg-type]


def test_shadow_trace_cannot_carry_an_order() -> None:
    with pytest.raises(ValueError, match="SHADOW_TRADE must never create an order"):
        _trace(mode=DecisionMode.SHADOW_TRADE, order_created=True, shadow={"mode": "SHADOW_TRADE"})


def test_shadow_trace_requires_the_shadow_contract() -> None:
    with pytest.raises(ValueError, match="must carry the shadow decision contract"):
        _trace(mode=DecisionMode.SHADOW_TRADE)


def test_no_trade_trace_cannot_carry_an_order() -> None:
    with pytest.raises(ValueError, match="NO_TRADE must never create an order"):
        _trace(order_created=True, orders_created=1)


def test_an_excluded_asset_trace_cannot_carry_a_proposal() -> None:
    """DEF-WP00-01 — a universe exclusion never reasoned about a proposal.

    Same rule as ``NO_TRADE_DATA``: the asset was refused before any strategy
    saw it, so a trace claiming otherwise would describe a decision that never
    happened.
    """
    with pytest.raises(ValueError, match="cannot carry a trade proposal"):
        _trace(
            classification="UNIVERSE_FILTERED",
            no_trade_kind=NoTradeKind.NO_TRADE_UNIVERSE.value,
            proposal=_proposal().to_dict(),
        )


def test_an_unknown_no_trade_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown no_trade_kind"):
        _trace(no_trade_kind="NO_TRADE_MADE_UP")


def test_agent_capability_refuses_forbidden_capabilities() -> None:
    with pytest.raises(ValueError, match="forbidden capabilities"):
        AgentCapability(
            agent_id="rogue",
            capabilities=("execute_order",),
            inputs=(),
            outputs=(),
        )


def test_agent_message_confidence_bounds() -> None:
    with pytest.raises(ValueError, match="confidence"):
        AgentMessage(
            run_id="run-1",
            decision_id="d-1",
            agent_id="x",
            review_type=ReviewType.OBSERVATION,
            asset="BTC",
            statement="s",
            confidence=1.5,
        )


def test_outcome_requires_strictly_later_timestamp() -> None:
    with pytest.raises(ValueError, match="anti-lookahead"):
        OutcomeRecord(
            run_id="run-1",
            decision_id="d-1",
            asset="BTC",
            symbol="BTC/USDT",
            strategy_id="ema_crossover@5m",
            mode=DecisionMode.SHADOW_TRADE,
            direction="LONG",
            decision_time_ms=2_000,
            outcome_time_ms=2_000,
            horizon_minutes=5.0,
            entry_reference=100.0,
            outcome_price=101.0,
            gross_return_bps=100.0,
            estimated_cost_bps=21.1,
            net_hypothetical_bps=78.9,
            mfe_bps=120.0,
            mae_bps=-10.0,
            direction_correct=True,
            status=OutcomeStatus.RESOLVED,
        )


def test_ledger_paper_admission_requires_evidence() -> None:
    from trading_bot.autonomous.contracts import AdmissionEntry

    with pytest.raises(ValueError, match="without edge evidence"):
        AdmissionEntry(
            strategy_id="x@5m",
            family="x",
            status=AdmissionStatus.PAPER_CANDIDATE,
            admitted_for_paper=True,
            expected_gross_edge_bps=30.0,
            edge_evidence=None,
            source_doc="docs/x.json",
            rationale="test",
        )


def test_ledger_unknown_strategy_is_not_admitted() -> None:
    ledger = make_ledger()
    entry = ledger.entry("does-not-exist@5m")
    assert entry.status is AdmissionStatus.UNKNOWN
    assert entry.admitted_for_paper is False
    assert entry.expected_gross_edge_bps is None
    assert ledger.is_paper_admitted("does-not-exist@5m") is False
