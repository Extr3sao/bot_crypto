"""DecisionEngine matrix + specialist agent reviews."""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.autonomous.agents import AgentRegistry, ReviewInputs, RiskAdversaryAgent
from trading_bot.autonomous.contracts import (
    AdmissionStatus,
    AgentCapability,
    DecisionMode,
    ReviewType,
    RiskReview,
    RiskVerdict,
    VerificationResult,
    VerifierVerdict,
)
from trading_bot.autonomous.decision import DecisionEngine, DecisionRequest

from .helpers import make_admitted_ledger, make_ledger
from .test_contracts import _proposal


def _request(
    *,
    ledger: Any,
    strategy_id: str,
    gross: float = 4.0,
    cost: float = 21.1,
    verification: VerifierVerdict = VerifierVerdict.PASS,
    risk: RiskVerdict = RiskVerdict.NOT_APPLICABLE,
    notional: float | None = None,
    shadow_enabled: bool = True,
) -> DecisionRequest:
    entry = ledger.entry(strategy_id)
    net = gross - cost
    proposal = _proposal(
        strategy_id=strategy_id,
        expected_gross_edge_bps=gross,
        expected_cost_bps=cost,
        expected_net_edge_bps=net,
        admission_status=entry.status,
    )
    return DecisionRequest(
        run_id="run-1",
        decision_id="d-1",
        asset="BTC",
        symbol="BTC/USDT",
        market_time_ms=1_000,
        decision_time_ms=2_000,
        regime="RANGE",
        admission=entry,
        proposal=proposal,
        verification=VerificationResult(decision_id="d-1", verdict=verification),
        risk=RiskReview(
            verdict=risk,
            reason="test_risk_veto" if risk is RiskVerdict.VETO else "",
            notional_usdt=notional,
        ),
        shadow_evaluation_enabled=shadow_enabled,
    )


def test_cost_killed_research_candidate_becomes_shadow() -> None:
    ledger = make_ledger(gross_bps=4.0)
    result = DecisionEngine().decide(_request(ledger=ledger, strategy_id="ema_crossover@5m"))
    assert result.mode is DecisionMode.SHADOW_TRADE
    assert result.classification == "COST_KILLED"
    assert result.order_authorised is False
    assert result.shadow is not None and result.shadow.marked_shadow is True


def test_positive_net_but_unadmitted_is_shadow_not_paper() -> None:
    ledger = make_ledger(gross_bps=50.0)
    result = DecisionEngine().decide(
        _request(ledger=ledger, strategy_id="ema_crossover@5m", gross=50.0, cost=21.1)
    )
    assert result.mode is DecisionMode.SHADOW_TRADE
    assert result.classification == "NOT_ADMITTED"
    assert result.order_authorised is False


def test_admitted_candidate_with_positive_net_is_paper() -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine().decide(
        _request(
            ledger=ledger,
            strategy_id="ema_crossover@5m",
            gross=50.0,
            cost=21.1,
            risk=RiskVerdict.PASS,
            notional=250.0,
        )
    )
    assert result.mode is DecisionMode.TRADE_PAPER
    assert result.order_authorised is True
    assert result.notional_usdt == 250.0


def test_admitted_but_risk_not_pass_fails_closed() -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine().decide(
        _request(ledger=ledger, strategy_id="ema_crossover@5m", gross=50.0, cost=21.1)
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "RISK_VETO"


def test_risk_veto_wins_over_economics() -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine().decide(
        _request(
            ledger=ledger,
            strategy_id="ema_crossover@5m",
            gross=50.0,
            cost=21.1,
            risk=RiskVerdict.VETO,
        )
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "RISK_VETO"


def test_negative_gross_edge_is_no_trade_not_shadow() -> None:
    ledger = make_ledger(gross_bps=-4.56)
    result = DecisionEngine().decide(
        _request(ledger=ledger, strategy_id="ema_crossover@5m", gross=-4.56, cost=21.1)
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "NO_GROSS_EDGE"


def test_verifier_failure_fails_closed() -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine().decide(
        _request(
            ledger=ledger,
            strategy_id="ema_crossover@5m",
            gross=50.0,
            cost=21.1,
            verification=VerifierVerdict.FAIL,
            risk=RiskVerdict.PASS,
        )
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "VERIFIER_FAIL"


def test_unknown_strategy_is_no_trade() -> None:
    ledger = make_ledger()
    result = DecisionEngine().decide(_request(ledger=ledger, strategy_id="ghost@5m"))
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "UNKNOWN_STRATEGY"


def test_shadow_can_be_disabled_explicitly() -> None:
    ledger = make_ledger(gross_bps=4.0)
    result = DecisionEngine().decide(
        _request(ledger=ledger, strategy_id="ema_crossover@5m", shadow_enabled=False)
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "COST_KILLED"


# -- agents -----------------------------------------------------------------


def _inputs(**overrides: Any) -> ReviewInputs:
    ledger = overrides.pop("ledger", None) or make_ledger(gross_bps=4.0)
    proposal = overrides.pop("proposal", None)
    if proposal is None:
        proposal = _proposal(
            expected_gross_edge_bps=4.0, expected_cost_bps=21.1, expected_net_edge_bps=-17.1
        )
    base: dict[str, Any] = {
        "run_id": "run-1",
        "decision_id": "d-1",
        "asset": "BTC",
        "symbol": "BTC/USDT",
        "decision_time_ms": 2_000,
        "regime": "RANGE",
        "bars_in_window": 120,
        "data_quality": {"bars_in_window": 120},
        "data_fingerprint": "sha256:abc",
        "window_end_ts": 2_000,
        "context_issues": (),
        "admission": ledger.entry("ema_crossover@5m"),
        "proposal": proposal,
        "performance": None,
    }
    base.update(overrides)
    return ReviewInputs(**base)  # type: ignore[arg-type]


def test_default_registry_reviews_every_agent_exactly_once() -> None:
    registry = AgentRegistry()
    messages = registry.review(_inputs())
    assert sorted(m.agent_id for m in messages) == sorted(registry.agent_ids())
    assert all(m.review_type is not ReviewType.VETO for m in messages)


def test_cost_agent_critiques_when_gross_does_not_cover_cost() -> None:
    messages = {m.agent_id: m for m in AgentRegistry().review(_inputs())}
    cost = messages["cost-economics"]
    assert cost.review_type is ReviewType.CRITIQUE
    assert cost.payload["classification"] == "COST_KILLED"


def test_context_agent_vetoes_on_future_bar() -> None:
    messages = {m.agent_id: m for m in AgentRegistry().review(_inputs(window_end_ts=9_999))}
    assert messages["data-integrity"].review_type is ReviewType.VETO


def test_provenance_agent_critiques_unadmitted_strategy() -> None:
    messages = {m.agent_id: m for m in AgentRegistry().review(_inputs())}
    assert messages["evidence-provenance"].review_type is ReviewType.CRITIQUE
    assert messages["evidence-provenance"].payload["classification"] == "NOT_ADMITTED"


def test_risk_adversary_warns_without_realised_history() -> None:
    message = RiskAdversaryAgent().review(_inputs())
    assert message is not None
    assert message.review_type is ReviewType.RISK_WARNING
    assert any("no realised outcome history" in e for e in message.evidence)


class _FakeCapability:
    """Duck-typed capability that bypasses construction validation."""

    agent_id = "rogue"
    capabilities = ("modify_risk_limits",)
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()


def test_rogue_agent_cannot_register() -> None:
    class RogueAgent:
        capability = _FakeCapability()

        def review(self, inputs: ReviewInputs) -> None:
            return None

    with pytest.raises(ValueError, match="forbidden capabilities"):
        AgentRegistry(agents=(RogueAgent(),))  # type: ignore[arg-type]


def test_agent_capability_constructor_rejects_forbidden_action() -> None:
    with pytest.raises(ValueError, match="forbidden capabilities"):
        AgentCapability(agent_id="rogue", capabilities=("execute_order",), inputs=(), outputs=())


def test_failing_agent_yields_a_veto_not_silence() -> None:
    class BrokenAgent:
        capability = AgentCapability(
            agent_id="broken", capabilities=("inspect",), inputs=(), outputs=()
        )

        def review(self, inputs: ReviewInputs) -> Any:
            raise RuntimeError("agent exploded")

    registry = AgentRegistry(agents=(BrokenAgent(),))  # type: ignore[arg-type]
    messages = registry.review(_inputs())
    assert len(messages) == 1
    assert messages[0].review_type is ReviewType.VETO


def test_agent_veto_short_circuits_the_decision() -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    request = _request(
        ledger=ledger,
        strategy_id="ema_crossover@5m",
        gross=50.0,
        cost=21.1,
        risk=RiskVerdict.PASS,
    )
    from dataclasses import replace

    from trading_bot.autonomous.contracts import AgentMessage

    veto = AgentMessage(
        run_id="run-1",
        decision_id="d-1",
        agent_id="data-integrity",
        review_type=ReviewType.VETO,
        asset="BTC",
        statement="unsafe context",
    )
    result = DecisionEngine().decide(replace(request, agent_messages=(veto,)))
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "AGENT_VETO"
    assert ledger.entry("ema_crossover@5m").status is AdmissionStatus.PAPER_CANDIDATE
