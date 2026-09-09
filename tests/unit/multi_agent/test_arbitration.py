"""Adversarial tests for deterministic direction arbitration (TRACK E).

Covers every required scenario plus the natural runtime reproduction (DIR-01)
and NO_FORCED_DIRECTION (DIR-12/E1). All inputs are deterministic fixtures;
the arbitration contract itself is LLM-free by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.multi_agent.arbitration import (
    REASON_BELOW_FLOOR,
    REASON_HIGHER_SCORE,
    REASON_SCORE_TIE,
    REASON_SOLE_CANDIDATE,
    SELECTED_LONG,
    SELECTED_NONE,
    SELECTED_SHORT,
    ArbitrationError,
    DirectionArbiter,
    GroupVerificationStatus,
    OpportunityGroupVerifier,
)
from trading_bot.multi_agent.contracts import TraceContext, TradeDirection, TradeProposal
from trading_bot.multi_agent.specialists import _evidence as make_evidence

NOW = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
RUN = "run-arb-test"
TRACE = "trace-arb-test"


def _trace(artifact: str) -> TraceContext:
    return TraceContext(
        run_id=RUN,
        trace_id=TRACE,
        correlation_id=artifact,
        causation_id=artifact,
    )


def _foreign_trace(artifact: str) -> TraceContext:
    return TraceContext(
        run_id="run-foreign",
        trace_id="trace-foreign",
        correlation_id=artifact,
        causation_id=artifact,
    )


def _proposal(
    *,
    direction: str,
    asset: str = "BTC",
    strategy: str = "momentum",
    confidence: float = 0.6,
    run_id: str = RUN,
    created_at: datetime | None = None,
    data_time: datetime | None = None,
) -> TradeProposal:
    created = created_at or NOW
    data = data_time or created
    pid = f"proposal:{direction}:{strategy}:{asset}:{int(data.timestamp()*1000)}:{confidence}"
    evidence = make_evidence(
        evidence_id=f"evidence:{pid}",
        run_id=run_id,
        producer="strategy-expert-momentum",
        evidence_type="strategy_signal",
        source_ref=f"asset-context:{asset}",
        claim_ref=pid,
        observed_at=data,
        available_at=data,
        trace=_trace(pid) if run_id == RUN else _foreign_trace(pid),
        payload={"direction": direction, "confidence": confidence},
    )
    return TradeProposal(
        schema_version="ma-2-v1",
        proposal_id=pid,
        run_id=run_id,
        trace_id=TRACE if run_id == RUN else "trace-foreign",
        asset=asset,
        direction=TradeDirection(direction),
        strategy=strategy,
        timeframe="5m",
        regime="TREND_UP" if direction == "LONG" else "TREND_DOWN",
        evidence_refs=(evidence.evidence_id,),
        invalidation="structural invalidation",
        confidence=confidence,
        data_time=data,
        created_at=created,
        expires_at=created + timedelta(minutes=15),
        trace=_trace(pid) if run_id == RUN else _foreign_trace(pid),
    )


def _registry(*proposals: TradeProposal) -> dict[str, object]:
    """Evidence registry keyed by evidence id (minimal duck-typed surface)."""
    registry: dict[str, object] = {}
    for proposal in proposals:
        for ref in proposal.evidence_refs:
            evidence = make_evidence(
                evidence_id=ref,
                run_id=proposal.run_id,
                producer="strategy-expert-momentum",
                evidence_type="strategy_signal",
                source_ref=f"asset-context:{proposal.asset}",
                claim_ref=proposal.proposal_id,
                observed_at=proposal.data_time,
                available_at=proposal.data_time,
                trace=_trace(proposal.proposal_id)
        if proposal.run_id == RUN
        else _foreign_trace(proposal.proposal_id),
                payload={"proposal": proposal.proposal_id},
            )
            registry[ref] = evidence
    return registry


ARBITER = DirectionArbiter()


def _form_and_select(proposals: list[TradeProposal], *, run_id: str = RUN):
    by_id = {p.proposal_id: p for p in proposals}
    groups = ARBITER.form_groups(
        run_id=run_id,
        trace_id=TRACE,
        proposals=by_id,
        evidence_registry=_registry(*proposals),
        decision_time=NOW,
    )
    assert len(groups) == 1
    resolved = ARBITER.select_direction(groups[0], proposals=by_id)
    return resolved, by_id


# ---------------------------------------------------------------------------
# DIR-01 — natural runtime conflict reproduction (real POC02 path shape)
# ---------------------------------------------------------------------------


def test_poc02_natural_conflict_reproduction() -> None:
    """Both directions of one evaluation deadlock the natural pipeline (POC02 form).

    Mirrors the committed POC02 runtime shape: equal-confidence mirror pair in a
    regime that does not coherently admit both sides. The debate burns all
    rounds on mirror challenges and regime-revision churn; the counter-signal
    CHALLENGE stands on both lineages and no admissible selection exists.
    """
    from trading_bot.demo.paper_multi_agent import _setup_bus
    from trading_bot.multi_agent.debate import (
        DebatePosition,
        DebateSession,
    )
    from trading_bot.multi_agent.opportunity import OpportunityBoard

    long_p = _proposal(direction="LONG", confidence=0.7)
    short_p = _proposal(direction="SHORT", confidence=0.7)
    by_id = {p.proposal_id: p for p in (long_p, short_p)}
    registry = _registry(long_p, short_p)

    bus = _setup_bus(RUN, TRACE, NOW)
    board = OpportunityBoard(run_id=RUN, now=NOW)
    for proposal in by_id.values():
        for ref in proposal.evidence_refs:
            board.add_evidence(registry[ref])  # type: ignore[index]
        board.add(
            proposal,
            source_agent_id="strategy-expert-momentum",
            source_agent_version="1.0.0",
        )
    snapshot = board.snapshot()
    assert len(snapshot.conflicts) == 1  # the natural conflict exists

    positions = [
        DebatePosition(
            proposal_id=p.proposal_id,
            owner_agent_id="strategy-expert-momentum",
            asset=p.asset,
            direction=p.direction,
            strategy=p.strategy,
            claim=f"{p.strategy} {p.direction.value}",
            evidence_refs=p.evidence_refs,
        )
        for p in by_id.values()
    ]
    session = DebateSession(
        debate_id=f"debate:{NOW.timestamp()}",
        bus=bus,
        positions=positions,
        proposals=by_id,
        # POC02's real windows alternate regimes; the mirror SHORT of a
        # TREND_UP window is regime-incoherent, exactly as observed.
        regime_by_asset={"BTC": "TREND_UP"},
        evidence_registry=registry,
        max_rounds=3,
    )
    report = session.run()
    # The debate terminates WITHOUT resolution: mirror counter-signal
    # challenges stand on both lineages through the final round.
    assert report.termination_reason.value == "MAX_ROUNDS"
    assert any(
        c.critic_agent_id == "critic-counter-signal" and c.stance.value == "CHALLENGE"
        for c in report.critiques
    )

    from trading_bot.multi_agent.decision import DecisionEngine

    proposals_all = dict(by_id)
    proposals_all.update(session.revised_proposals)
    package = DecisionEngine(run_id=RUN).decide(
        snapshot=snapshot,
        proposals=proposals_all,
        evidence_registry=registry,
        reports=(report,),
        now=NOW,
    )
    # No selection can carry the standing mirror conflict to Risk in POC02's
    # committed composition: the selected package fails independent
    # verification (stripped/ignored counter-side) or no selection exists.
    from trading_bot.demo.paper_multi_agent import DecisionToCandidateAdapter

    adapter = DecisionToCandidateAdapter()
    candidate = adapter.adapt(
        package,
        proposals=proposals_all,
        evidence_registry=registry,
        reports=(report,),
        now=NOW,
        prices={"BTC": 100.0},
        snapshot=snapshot,
    )
    assert candidate is None  # POC02 never reached Risk — reproduced end to end


# ---------------------------------------------------------------------------
# TRACK E — required scenarios
# ---------------------------------------------------------------------------


def test_strong_long_weak_short_long_proceeds() -> None:
    long_p = _proposal(direction="LONG", confidence=0.9)
    short_p = _proposal(direction="SHORT", confidence=0.3)
    resolved, _by_id = _form_and_select([long_p, short_p])
    assert resolved.selected_direction == SELECTED_LONG
    assert resolved.selection_reason == REASON_HIGHER_SCORE
    # losing side preserved in provenance
    assert resolved.short_candidate_ref == short_p.proposal_id
    assert resolved.counter_evidence == tuple(sorted(short_p.evidence_refs))


def test_weak_long_strong_short_short_proceeds() -> None:
    long_p = _proposal(direction="LONG", confidence=0.3)
    short_p = _proposal(direction="SHORT", confidence=0.9)
    resolved, _by_id = _form_and_select([long_p, short_p])
    assert resolved.selected_direction == SELECTED_SHORT
    assert resolved.long_candidate_ref == long_p.proposal_id


def test_equal_unresolved_is_none() -> None:
    long_p = _proposal(direction="LONG", confidence=0.6)
    short_p = _proposal(direction="SHORT", confidence=0.6)
    resolved, _by_id = _form_and_select([long_p, short_p])
    assert resolved.selected_direction == SELECTED_NONE
    assert resolved.selection_reason == REASON_SCORE_TIE
    assert resolved.confidence == 0.0


def test_both_below_signal_floor_is_none() -> None:
    arbiter = DirectionArbiter(min_direction_score=0.8)
    long_p = _proposal(direction="LONG", confidence=0.5)
    short_p = _proposal(direction="SHORT", confidence=0.5)
    by_id = {p.proposal_id: p for p in (long_p, short_p)}
    groups = arbiter.form_groups(
        run_id=RUN,
        trace_id=TRACE,
        proposals=by_id,
        evidence_registry=_registry(long_p, short_p),
        decision_time=NOW,
    )
    resolved = arbiter.select_direction(groups[0], proposals=by_id)
    assert resolved.selected_direction == SELECTED_NONE
    assert resolved.selection_reason == REASON_BELOW_FLOOR


def test_cross_strategy_conflict_is_never_grouped() -> None:
    """LONG from strategy A vs SHORT from strategy B = genuine conflict preserved."""
    long_p = _proposal(direction="LONG", strategy="momentum")
    short_p = _proposal(direction="SHORT", strategy="trend")
    by_id = {p.proposal_id: p for p in (long_p, short_p)}
    groups = ARBITER.form_groups(
        run_id=RUN,
        trace_id=TRACE,
        proposals=by_id,
        evidence_registry=_registry(long_p, short_p),
        decision_time=NOW,
    )
    assert len(groups) == 2  # separate evaluations — no arbitration between them
    assert all(g.selected_direction == SELECTED_NONE for g in groups)


def test_forged_direction_score_rejected_by_verifier() -> None:
    long_p = _proposal(direction="LONG", confidence=0.9)
    short_p = _proposal(direction="SHORT", confidence=0.3)
    resolved, by_id = _form_and_select([long_p, short_p])
    registry = _registry(long_p, short_p)
    # Forge: inflate the recorded score of the losing side.
    from dataclasses import replace

    forged_scores = tuple(
        replace(s, score=0.99) if s.direction == SELECTED_SHORT else s
        for s in resolved.direction_scores
    )
    forged = replace(resolved, direction_scores=forged_scores)
    verifier = OpportunityGroupVerifier()
    verdict = verifier.verify(
        forged, proposals=by_id, evidence_registry=registry, now=NOW
    )
    assert verdict.verdict is GroupVerificationStatus.REJECTED
    assert any(name == "direction_score_integrity" and status == "FAIL" for name, status, _ in verdict.checks)


def test_cross_run_candidate_rejected() -> None:
    long_p = _proposal(direction="LONG", confidence=0.9)
    short_p = _proposal(direction="SHORT", run_id="run-foreign")
    by_id = {p.proposal_id: p for p in (long_p, short_p)}
    with pytest.raises(ArbitrationError):
        ARBITER.form_groups(
            run_id=RUN,
            trace_id=TRACE,
            proposals=by_id,
            evidence_registry=_registry(long_p, short_p),
            decision_time=NOW,
        )


def test_future_evidence_rejected() -> None:
    future = NOW + timedelta(minutes=5)
    long_p = _proposal(direction="LONG", data_time=future, created_at=future)
    by_id = {long_p.proposal_id: long_p}
    with pytest.raises(ArbitrationError):
        ARBITER.form_groups(
            run_id=RUN,
            trace_id=TRACE,
            proposals=by_id,
            evidence_registry=_registry(long_p),
            decision_time=NOW,
        )


def test_same_group_replay_deterministic() -> None:
    long_p = _proposal(direction="LONG", confidence=0.9)
    short_p = _proposal(direction="SHORT", confidence=0.3)
    first, _by_id = _form_and_select([long_p, short_p])
    second, _ = _form_and_select([long_p, short_p])
    assert first.to_dict() == second.to_dict()
    assert first.group_id == second.group_id


def test_verifier_passes_on_intact_group() -> None:
    long_p = _proposal(direction="LONG", confidence=0.9)
    short_p = _proposal(direction="SHORT", confidence=0.3)
    resolved, by_id = _form_and_select([long_p, short_p])
    verifier = OpportunityGroupVerifier()
    verdict = verifier.verify(
        resolved,
        proposals=by_id,
        evidence_registry=_registry(long_p, short_p),
        now=NOW,
    )
    assert verdict.passed
    assert all(status == "PASS" for _, status, _ in verdict.checks)


def test_sole_direction_selects_directly() -> None:
    long_p = _proposal(direction="LONG", confidence=0.6)
    resolved, _by_id = _form_and_select([long_p])
    assert resolved.selected_direction == SELECTED_LONG
    assert resolved.selection_reason == REASON_SOLE_CANDIDATE
    assert resolved.counter_evidence == ()


# ---------------------------------------------------------------------------
# E1 / DIR-12 — NO_FORCED_DIRECTION
# ---------------------------------------------------------------------------


def test_no_forced_direction() -> None:
    """The arbiter can never manufacture a direction: NONE paths stay NONE."""
    # exact tie → NONE
    long_p = _proposal(direction="LONG", confidence=0.5)
    short_p = _proposal(direction="SHORT", confidence=0.5)
    resolved, _ = _form_and_select([long_p, short_p])
    assert resolved.selected_direction == SELECTED_NONE
    # empty group cannot appear (form_groups only creates groups with members)
    # sole-candidate with zero confidence still selects the only admissible
    # direction — but a below-floor floor keeps NONE:
    arbiter = DirectionArbiter(min_direction_score=0.99)
    zero = _proposal(direction="LONG", confidence=0.0)
    by_id = {zero.proposal_id: zero}
    groups = arbiter.form_groups(
        run_id=RUN,
        trace_id=TRACE,
        proposals=by_id,
        evidence_registry=_registry(zero),
        decision_time=NOW,
    )
    resolved_zero = arbiter.select_direction(groups[0], proposals=by_id)
    assert resolved_zero.selected_direction == SELECTED_NONE
