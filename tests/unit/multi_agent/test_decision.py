"""MA-4 decision engine test matrix (CP-MA-004).

Covers: contracts, terminal revision resolution, eligibility gates,
MetaRanker reuse with score provenance, deterministic selection and
tie-breaks, rejected alternatives, NO_TRADE matrix, unresolved-conflict
fail-closed, revision changes winner, order independence, deterministic
replay, independent verifier, single temporal authority, and execution
boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from trading_bot.multi_agent import (
    AgentRegistry,
    Blackboard,
    CapabilityRegistry,
    DecisionCandidate,
    DecisionEngine,
    DecisionError,
    DecisionPackage,
    DecisionPackageVerifier,
    DecisionReason,
    OpportunitySnapshot,
    register_swarm_agents,
)
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.contracts import (
    AgentEvidence,
    CritiqueRecord,
    CritiqueStance,
    DebateOutcome,
    DebateReport,
    DebateTerminationReason,
    DecisionEligibility,
    DecisionOutcome,
    RequestedAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.contracts.decision import (
    DecisionScoreBreakdown,
    ScoreComponentSource,
)
from trading_bot.multi_agent.debate import DebateSession
from trading_bot.multi_agent.decision import (
    DECISION_ENGINE_ID,
    DECISION_SCHEMA_VERSION,
    DECISION_VERIFIER_ID,
    DecisionVerificationStatus,
    TerminalProposalResolver,
)
from trading_bot.multi_agent.opportunity import MetaRanker, Opportunity
from trading_bot.multi_agent.specialists import AssetAssessment

SCHEMA = "ma-3-v1"
CLOCK = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
TS = 1_768_046_400_000  # 2026-01-10 12:00 UTC in ms
TRACE = TraceContext(
    run_id="ma4-run",
    trace_id="ma4-trace",
    correlation_id="ma4-corr",
    causation_id="ma4-cause",
)

# ---------------------------------------------------------------------------
# Shared fixtures (aligned with the certified MA-3 test helpers)
# ---------------------------------------------------------------------------


def _bus(clock: datetime = CLOCK) -> AgentBus:
    reg = AgentRegistry()
    cap = CapabilityRegistry()
    register_swarm_agents(reg, cap)
    from trading_bot.multi_agent import register_debate_agents

    register_debate_agents(reg, cap)
    return AgentBus(
        agent_registry=reg,
        capability_registry=cap,
        blackboard=Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id),
        clock=lambda: clock,
    )


def _evidence(
    evidence_id: str,
    producer: str,
    *,
    claim: str | None = None,
    observed: datetime | None = None,
) -> AgentEvidence:
    t = observed or CLOCK
    return AgentEvidence(
        schema_version=SCHEMA,
        evidence_id=evidence_id,
        run_id=TRACE.run_id,
        producer_agent_id=producer,
        evidence_type="strategy_signal",
        source_ref=f"ctx:{evidence_id}",
        claim_refs=(claim or "claim",),
        observed_at=t,
        available_at=t,
        content_hash="a" * 64,
        metadata=(),
        trace=TRACE,
    )


def _proposal(
    proposal_id: str,
    *,
    direction: TradeDirection = TradeDirection.LONG,
    strategy: str = "momentum",
    asset: str = "SOL",
    confidence: float = 0.8,
    evidence_id: str | None = None,
    created: datetime | None = None,
    data_time: datetime | None = None,
    expires_at: datetime | None = None,
) -> TradeProposal:
    now = created or CLOCK
    return TradeProposal(
        schema_version=SCHEMA,
        proposal_id=proposal_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset=asset,
        direction=direction,
        strategy=strategy,
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(evidence_id or f"ev:{proposal_id}",),
        invalidation="structural stop",
        confidence=confidence,
        data_time=data_time or now,
        created_at=now,
        expires_at=expires_at if expires_at is not None else now + timedelta(minutes=15),
        trace=TRACE,
    )


def _assessment(
    asset: str = "SOL", regime: str = "TREND_UP", confidence: float = 0.9
) -> AssetAssessment:
    return AssetAssessment(
        asset=asset,
        timestamp=TS,
        regime=regime,
        trend_quality=0.9,
        volatility_quality=0.8,
        liquidity_quality=0.9,
        relative_strength=0.85,
        market_quality=0.8,
        confidence=confidence,
        evidence=(),
        trace=TRACE,
        agent_id="asset-expert-sol",
        agent_version="1.0.0",
    )


def _position(proposal: TradeProposal, owner: str):
    from trading_bot.multi_agent.contracts import DebatePosition

    return DebatePosition(
        proposal_id=proposal.proposal_id,
        owner_agent_id=owner,
        asset=proposal.asset,
        direction=proposal.direction,
        strategy=proposal.strategy,
        claim=f"{proposal.strategy} {proposal.direction.value} {proposal.asset}",
        evidence_refs=proposal.evidence_refs,
    )


def _run_debate(
    proposals: list[TradeProposal],
    owners: dict[str, str],
    *,
    max_rounds: int = 3,
    regime: str = "TREND_UP",
) -> DebateReport:
    """Run a bounded debate over the given proposals using certified MA-3."""
    bus = _bus()
    registry: dict[str, AgentEvidence] = {}
    for proposal in proposals:
        for ref in proposal.evidence_refs:
            registry.setdefault(
                ref, _evidence(ref, owners[proposal.proposal_id], claim=proposal.proposal_id)
            )
    positions = [_position(p, owners[p.proposal_id]) for p in proposals]
    session = DebateSession(
        debate_id=f"debate:{'-'.join(p.proposal_id for p in proposals)}",
        bus=bus,
        positions=positions,
        proposals={p.proposal_id: p for p in proposals},
        regime_by_asset={asset: regime for asset in {p.asset for p in proposals}},
        evidence_registry=registry,
        max_rounds=max_rounds,
    )
    return session.run()


def _make_engine() -> DecisionEngine:
    return DecisionEngine(run_id=TRACE.run_id)


# ---------------------------------------------------------------------------
# Contract gates (MA4-01, MA4-02)
# ---------------------------------------------------------------------------


class TestDecisionContracts:
    def test_no_trade_is_first_class_not_error(self) -> None:
        assert DecisionOutcome.NO_TRADE.value == "NO_TRADE"
        assert DecisionOutcome.NO_TRADE is not DecisionOutcome.REJECTED

    def test_score_breakdown_requires_provenance(self) -> None:
        with pytest.raises(ValidationError):
            DecisionScoreBreakdown(
                final_score=0.5,
                components=(("meta_ranker_score", 0.9, "NOT_A_SOURCE"),),
            )

    def test_score_breakdown_rejects_duplicate_component_names(self) -> None:
        with pytest.raises(ValidationError):
            DecisionScoreBreakdown(
                final_score=0.5,
                components=(
                    ("meta_ranker_score", 0.9, ScoreComponentSource.META_RANKER.value),
                    ("meta_ranker_score", 0.9, ScoreComponentSource.META_RANKER.value),
                ),
            )

    def test_package_rejects_selected_candidate_missing_from_set(self) -> None:
        candidate = _candidate()
        with pytest.raises(ValidationError):
            DecisionPackage(
                schema_version=DECISION_SCHEMA_VERSION,
                decision_id="decision:x",
                run_id=TRACE.run_id,
                decision_time=CLOCK,
                candidate_set=(candidate,),
                selected_candidate_id="decision:ghost",
                outcome=DecisionOutcome.SELECTED,
                decision_reasons=(DecisionReason.HIGHEST_ADMISSIBLE_SCORE,),
                verification_metadata=_verification_meta("decision:x"),
            )

    def test_package_no_trade_cannot_carry_selection(self) -> None:
        candidate = _candidate()
        with pytest.raises(ValidationError):
            DecisionPackage(
                schema_version=DECISION_SCHEMA_VERSION,
                decision_id="decision:x",
                run_id=TRACE.run_id,
                decision_time=CLOCK,
                candidate_set=(candidate,),
                selected_candidate_id=candidate.final_proposal_id,
                outcome=DecisionOutcome.NO_TRADE,
                decision_reasons=(DecisionReason.NO_VALID_CANDIDATES,),
                verification_metadata=_verification_meta("decision:x"),
            )

    def test_package_rejects_ineligible_selection(self) -> None:
        candidate = _candidate(eligibility=DecisionEligibility.INELIGIBLE_EXPIRED)
        with pytest.raises(ValidationError):
            DecisionPackage(
                schema_version=DECISION_SCHEMA_VERSION,
                decision_id="decision:x",
                run_id=TRACE.run_id,
                decision_time=CLOCK,
                candidate_set=(candidate,),
                selected_candidate_id=candidate.final_proposal_id,
                outcome=DecisionOutcome.SELECTED,
                decision_reasons=(DecisionReason.HIGHEST_ADMISSIBLE_SCORE,),
                verification_metadata=_verification_meta("decision:x"),
            )

    def test_package_rejects_duplicate_terminal_candidates(self) -> None:
        a = _candidate(final="same-final")
        b = _candidate(final="same-final")
        with pytest.raises(ValidationError):
            DecisionPackage(
                schema_version=DECISION_SCHEMA_VERSION,
                decision_id="decision:x",
                run_id=TRACE.run_id,
                decision_time=CLOCK,
                candidate_set=(a, b),
                outcome=DecisionOutcome.NO_TRADE,
                decision_reasons=(DecisionReason.NO_VALID_CANDIDATES,),
                verification_metadata=_verification_meta("decision:x"),
            )

    def test_builder_verifier_metadata_enforces_separation(self) -> None:
        from trading_bot.multi_agent.contracts import VerificationMetadata

        with pytest.raises(ValidationError):
            VerificationMetadata(
                artifact_id="artifact",
                builder_agent_id=DECISION_ENGINE_ID,
                verifier_agent_id=DECISION_ENGINE_ID,
            )


# ---------------------------------------------------------------------------
# MA-4B — terminal revision resolution
# ---------------------------------------------------------------------------


class TestTerminalResolution:
    def test_linear_chain_resolves_to_terminal(self) -> None:
        p1 = _proposal("p1", confidence=0.9)
        p2 = p1.model_copy(update={"proposal_id": "p2"})
        p3 = p1.model_copy(update={"proposal_id": "p3"})

        class _Rev:
            def __init__(self, original: str, revised: str) -> None:
                self.original_proposal_id = original
                self.revised_proposal_id = revised

        report = _report_with_revisions(
            ["p1", "p2", "p3"],
            [_Rev("p1", "p2"), _Rev("p2", "p3")],
        )
        proposals = {p.proposal_id: p for p in (p1, p2, p3)}
        resolution = TerminalProposalResolver().resolve([report], proposals)
        assert resolution.terminal_by_root["p1"] == "p3"
        assert resolution.invalid_roots == frozenset()

    def test_self_revision_rejected_fail_closed(self) -> None:
        """A→A cannot exist: the MA-3 contract layer rejects it (defense in
        depth), so a self-cycle can never reach the decision resolver."""
        from pydantic import ValidationError as PydanticValidationError

        from trading_bot.multi_agent.contracts import ProposalRevision

        with pytest.raises(PydanticValidationError):
            ProposalRevision(
                schema_version=SCHEMA,
                original_proposal_id="p1",
                revised_proposal_id="p1",
                triggering_critique_ids=("critique:x",),
                revision_reason="self",
                trace=TRACE,
                created_at=CLOCK,
            )

    def test_two_step_cycle_fail_closed(self) -> None:
        p1 = _proposal("p1")
        p2 = _proposal("p2")

        class _Rev:
            def __init__(self, original: str, revised: str) -> None:
                self.original_proposal_id = original
                self.revised_proposal_id = revised

        report = _report_with_revisions(
            ["p1", "p2"],
            [_Rev("p1", "p2"), _Rev("p2", "p1")],
        )
        proposals = {p.proposal_id: p for p in (p1, p2)}
        resolution = TerminalProposalResolver().resolve([report], proposals)
        assert "p1" in resolution.invalid_roots
        assert "p2" in resolution.invalid_roots

    def test_branch_fail_closed(self) -> None:
        p1 = _proposal("p1")
        p2 = _proposal("p2")
        p3 = _proposal("p3")

        class _Rev:
            def __init__(self, original: str, revised: str) -> None:
                self.original_proposal_id = original
                self.revised_proposal_id = revised

        report = _report_with_revisions(
            ["p1", "p2", "p3"],
            [_Rev("p1", "p2"), _Rev("p1", "p3")],
        )
        proposals = {p.proposal_id: p for p in (p1, p2, p3)}
        resolution = TerminalProposalResolver().resolve([report], proposals)
        assert "p1" in resolution.invalid_roots


class _ForcedRev:
    """Lineage edge that bypasses contract validation (resolver backstop test)."""

    def __init__(self, original: str, revised: str) -> None:
        self.original_proposal_id = original
        self.revised_proposal_id = revised


def _report_with_revisions(proposal_ids: list[str], revisions: list) -> DebateReport:
    """Minimal DebateReport carrying only revision lineage."""
    from trading_bot.multi_agent.contracts import ProposalRevision

    return DebateReport(
        schema_version=SCHEMA,
        debate_id="debate:test",
        run_id=TRACE.run_id,
        proposal_ids=tuple(proposal_ids),
        participants=("critic-evidence",),
        initial_claims=("claim",),
        revisions=tuple(
            ProposalRevision(
                schema_version=SCHEMA,
                original_proposal_id=r.original_proposal_id,
                revised_proposal_id=r.revised_proposal_id,
                triggering_critique_ids=("critique:x",),
                revision_reason="material counter-evidence",
                trace=TRACE,
                created_at=CLOCK,
            )
            for r in revisions
        ),
        round_count=1,
        max_rounds=3,
        termination_reason=DebateTerminationReason.RESOLVED,
        outcome=DebateOutcome.REVISED,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=0,
        trace=TRACE,
        created_at=CLOCK,
    )


def _candidate(
    *,
    final: str = "p1",
    eligibility: DecisionEligibility = DecisionEligibility.ELIGIBLE,
) -> DecisionCandidate:
    return DecisionCandidate(
        schema_version=DECISION_SCHEMA_VERSION,
        proposal_id=final,
        final_proposal_id=final,
        asset="SOL",
        strategy="momentum",
        direction="LONG",
        meta_rank=1,
        meta_score=0.9,
        eligibility=eligibility,
        decision_score=0.9,
        score_breakdown=DecisionScoreBreakdown(
            final_score=0.9,
            components=(("meta_ranker_score", 0.9, ScoreComponentSource.META_RANKER.value),),
        ),
        revision_lineage=(final,),
    )


def _verification_meta(artifact_id: str):
    from trading_bot.multi_agent.contracts import VerificationMetadata

    return VerificationMetadata(
        artifact_id=artifact_id,
        builder_agent_id=DECISION_ENGINE_ID,
        verifier_agent_id=DECISION_VERIFIER_ID,
    )


# ---------------------------------------------------------------------------
# MA-4Q — first decision E2E
# ---------------------------------------------------------------------------


class TestFirstDecisionE2E:
    def test_three_candidates_selected_rejected_reasons(self) -> None:
        sol = _proposal("p:sol", confidence=0.91, asset="SOL", strategy="momentum")
        btc = _proposal("p:btc", confidence=0.83, asset="BTC", strategy="breakout")
        eth = _proposal("p:eth", confidence=0.79, asset="ETH", strategy="trend")
        proposals = {p.proposal_id: p for p in (sol, btc, eth)}
        registry = {
            **{
                ref: _evidence(ref, "strategy-expert-momentum", claim="c")
                for ref in sol.evidence_refs
            },
            **{
                ref: _evidence(ref, "strategy-expert-breakout", claim="c")
                for ref in btc.evidence_refs
            },
            **{
                ref: _evidence(ref, "strategy-expert-trend", claim="c") for ref in eth.evidence_refs
            },
        }
        report_sol = _report_supported(("p:sol",))
        report_eth = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:eth",
            run_id=TRACE.run_id,
            proposal_ids=("p:eth",),
            participants=("critic-evidence",),
            initial_claims=("claim",),
            round_count=1,
            max_rounds=3,
            termination_reason=DebateTerminationReason.INSUFFICIENT_EVIDENCE,
            outcome=DebateOutcome.INSUFFICIENT_EVIDENCE,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=0,
            trace=TRACE,
            created_at=CLOCK,
        )
        snapshot = OpportunitySnapshot(opportunities=(), conflicts=())

        package = _make_engine().decide(
            snapshot=snapshot,
            proposals=proposals,
            evidence_registry=registry,
            reports=[report_sol, report_eth],
            assessments={
                "SOL": _assessment("SOL"),
                "BTC": _assessment("BTC", confidence=0.7),
                "ETH": _assessment("ETH", confidence=0.6),
            },
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.SELECTED
        assert package.selected_candidate_id == "p:sol"
        rejected = {a.final_proposal_id: a for a in package.rejected_alternatives}
        assert set(rejected) == {"p:btc", "p:eth"}
        assert rejected["p:btc"].rejection_reasons == (DecisionReason.LOWER_RANKED_ALTERNATIVE,)
        assert rejected["p:eth"].rejection_reasons == (DecisionReason.INSUFFICIENT_EVIDENCE,)
        # All three preserved in the candidate set.
        assert {c.final_proposal_id for c in package.candidate_set} == {
            "p:sol",
            "p:btc",
            "p:eth",
        }

    def test_candidate_fields_fully_populated(self) -> None:
        sol = _proposal("p:sol", confidence=0.91)
        proposals = {"p:sol": sol}
        registry = {ref: _evidence(ref, "strategy-expert-momentum") for ref in sol.evidence_refs}
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[_report_supported(("p:sol",))],
            assessments={"SOL": _assessment()},
            now=CLOCK,
        )
        candidate = package.candidate_set[0]
        assert candidate.proposal_id == "p:sol"
        assert candidate.final_proposal_id == "p:sol"
        assert candidate.meta_rank == 1
        assert candidate.debate_id == "debate:test"
        assert candidate.debate_outcome is DebateOutcome.SUPPORTED
        assert candidate.material_dissent is False
        assert candidate.revision_lineage == ("p:sol",)
        breakdown = dict(
            (name, (value, source)) for name, value, source in candidate.score_breakdown.components
        )
        assert breakdown["meta_ranker_score"][1] == ScoreComponentSource.META_RANKER.value
        assert candidate.supporting_evidence_refs


def _report_supported(proposal_ids: tuple[str, ...]) -> DebateReport:
    """DebateReport with a SUPPORT outcome and one audit critique."""
    critique = CritiqueRecord(
        schema_version=SCHEMA,
        critique_id="critique:sup",
        proposal_id=proposal_ids[0],
        critic_agent_id="critic-evidence",
        critic_version="1.0.0",
        stance=CritiqueStance.SUPPORT,
        materiality=0.0,
        claim="evidence checks out",
        confidence=0.9,
        requested_action=RequestedAction.NONE,
        trace=TRACE,
        created_at=CLOCK,
    )
    return DebateReport(
        schema_version=SCHEMA,
        debate_id="debate:test",
        run_id=TRACE.run_id,
        proposal_ids=proposal_ids,
        participants=("critic-evidence",),
        initial_claims=("claim",),
        critiques=(critique,),
        round_count=1,
        max_rounds=3,
        termination_reason=DebateTerminationReason.RESOLVED,
        outcome=DebateOutcome.SUPPORTED,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=0,
        trace=TRACE,
        created_at=CLOCK,
    )


# ---------------------------------------------------------------------------
# MA-4C — eligibility engine
# ---------------------------------------------------------------------------


class TestEligibilityEngine:
    def test_higher_raw_score_cannot_bypass_eligibility(self) -> None:
        stale = _proposal(
            "p:high",
            confidence=0.99,
            created=CLOCK - timedelta(hours=30),
            data_time=CLOCK - timedelta(hours=30),
            expires_at=CLOCK + timedelta(minutes=15),
        )
        fresh = _proposal("p:low", confidence=0.7)
        proposals = {"p:high": stale, "p:low": fresh}
        registry = {
            ref: _evidence(ref, "strategy-expert-momentum")
            for p in (stale, fresh)
            for ref in p.evidence_refs
        }
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p:low"
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:high"].eligibility is DecisionEligibility.INELIGIBLE_STALE
        assert by_id["p:high"].rejection_reasons == (DecisionReason.STALE,)

    def test_expired_candidate_ineligible(self) -> None:
        expired = _proposal(
            "p:x",
            created=CLOCK - timedelta(minutes=2),
            data_time=CLOCK - timedelta(minutes=2),
            expires_at=CLOCK - timedelta(minutes=1),
        )
        registry = {
            ref: _evidence(ref, "strategy-expert-momentum") for ref in expired.evidence_refs
        }
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:x": expired},
            evidence_registry=registry,
            now=CLOCK,
        )
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:x"].eligibility is DecisionEligibility.INELIGIBLE_EXPIRED

    def test_future_dated_candidate_ineligible(self) -> None:
        future = _proposal(
            "p:f",
            created=CLOCK + timedelta(hours=1),
            data_time=CLOCK + timedelta(hours=1),
            expires_at=CLOCK + timedelta(hours=2),
        )
        registry = {ref: _evidence(ref, "strategy-expert-momentum") for ref in future.evidence_refs}
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:f": future},
            evidence_registry=registry,
            now=CLOCK,
        )
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:f"].eligibility is DecisionEligibility.INELIGIBLE_FUTURE_DATED

    def test_invalid_evidence_reference_ineligible(self) -> None:
        p = _proposal("p:e", evidence_id="ev:ghost")
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:e": p},
            evidence_registry={},
            now=CLOCK,
        )
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:e"].eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE

    def test_future_evidence_available_at_rejected(self) -> None:
        p = _proposal("p:ef")
        evidence = _evidence(
            "ev:p:ef", "strategy-expert-momentum", observed=CLOCK + timedelta(hours=1)
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:ef": p},
            evidence_registry={evidence.evidence_id: evidence},
            now=CLOCK,
        )
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:ef"].eligibility is DecisionEligibility.INELIGIBLE_FUTURE_DATED

    def test_insufficient_evidence_debate_outcome_blocks(self) -> None:
        p = _proposal("p:ins")
        registry = {ref: _evidence(ref, "strategy-expert-momentum") for ref in p.evidence_refs}
        report = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:ins",
            run_id=TRACE.run_id,
            proposal_ids=("p:ins",),
            participants=("critic-evidence",),
            initial_claims=("claim",),
            round_count=1,
            max_rounds=3,
            termination_reason=DebateTerminationReason.INSUFFICIENT_EVIDENCE,
            outcome=DebateOutcome.INSUFFICIENT_EVIDENCE,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=0,
            trace=TRACE,
            created_at=CLOCK,
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:ins": p},
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.NO_TRADE
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:ins"].eligibility is DecisionEligibility.INELIGIBLE_INSUFFICIENT_EVIDENCE

    def test_invalid_trace_run_rejected(self) -> None:
        p = _proposal("p:t")
        foreign_trace = TraceContext(
            run_id="other-run",
            trace_id=TRACE.trace_id,
            correlation_id="c",
            causation_id="c",
        )
        p = p.model_copy(update={"trace": foreign_trace})
        registry = {ref: _evidence(ref, "strategy-expert-momentum") for ref in p.evidence_refs}
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:t": p},
            evidence_registry=registry,
            now=CLOCK,
        )
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:t"].eligibility is DecisionEligibility.INELIGIBLE_INVALID_TRACE


# ---------------------------------------------------------------------------
# MA-4D/E — MetaRanker reuse + provenance
# ---------------------------------------------------------------------------


class TestScoringProvenance:
    def test_meta_ranker_reuse_not_duplicated(self) -> None:
        p = _proposal("p:m", confidence=0.85)
        registry = {ref: _evidence(ref, "strategy-expert-momentum") for ref in p.evidence_refs}
        assessment = _assessment()
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:m": p},
            evidence_registry=registry,
            assessments={"SOL": assessment},
            now=CLOCK,
        )
        candidate = package.candidate_set[0]
        # Recompute the canonical MetaRanker V1 score directly and compare.
        expected = (
            MetaRanker()
            .score(
                __import__(
                    "trading_bot.multi_agent.opportunity", fromlist=["Opportunity"]
                ).Opportunity(
                    proposal=p,
                    evidence_refs=p.evidence_refs,
                    source_agent_id="unknown",
                    source_agent_version="0",
                ),
                assessment=assessment,
                conflicted=False,
            )
            .score
        )
        meta_component = candidate.score_breakdown.component("meta_ranker_score")
        assert meta_component == pytest.approx(expected)
        assert candidate.meta_score == pytest.approx(expected)

    def test_counter_evidence_penalty_has_debate_provenance(self) -> None:
        """A REVISED debate with one unanswered challenge applies the debate
        penalty without flipping eligibility to UNRESOLVED (revision resolves
        the standing conflict; the remaining critique is material dissent)."""
        p = _proposal("p:pen", confidence=0.9)
        revised = p.model_copy(update={"proposal_id": "p:pen:r-1", "confidence": 0.75})
        registry = {
            ref: _evidence(ref, "strategy-expert-momentum")
            for ref in (*p.evidence_refs, *revised.evidence_refs)
        }

        class _Rev:
            def __init__(self) -> None:
                self.original_proposal_id = "p:pen"
                self.revised_proposal_id = "p:pen:r-1"

        report = _report_with_revisions_and_answered_challenge(
            ("p:pen",), [_Rev()], answered_critique_id="critique:answered"
        )
        # Add a second, still-standing challenge so materiality is non-zero.
        standing = CritiqueRecord(
            schema_version=SCHEMA,
            critique_id="critique:standing",
            proposal_id="p:pen",
            critic_agent_id="critic-counter-signal",
            critic_version="1.0.0",
            stance=CritiqueStance.CHALLENGE,
            materiality=0.2,
            claim="independent counter-signal remains standing",
            counter_evidence_refs=("ev:counter2",),
            confidence=0.8,
            requested_action=RequestedAction.PROVIDE_EVIDENCE,
            trace=TRACE,
            created_at=CLOCK,
        )
        report = report.model_copy(
            update={
                "critiques": (*report.critiques, standing),
                "counter_evidence": (*report.counter_evidence, "ev:counter2"),
                "unique_counter_evidence_count": 2,
                "outcome": DebateOutcome.REVISED,
            }
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:pen": p, "p:pen:r-1": revised},
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        candidate = next(c for c in package.candidate_set if c.final_proposal_id == "p:pen:r-1")
        assert candidate.score_breakdown.component("counter_evidence_materiality") == 0.2
        assert candidate.meta_score - 0.2 == pytest.approx(candidate.decision_score)
        sources = {name: source for name, _, source in candidate.score_breakdown.components}
        assert sources["counter_evidence_materiality"] == ScoreComponentSource.DEBATE.value
        assert candidate.material_dissent is True
        assert "critic-counter-signal" in candidate.challenged_by

    def test_no_double_counting_of_revision_information(self) -> None:
        """Revision lowers confidence → lower MetaRanker score; the debate
        component must not also penalize an answered challenge."""
        original = _proposal("p:rev", confidence=0.9)
        revised = original.model_copy(update={"proposal_id": "p:rev2", "confidence": 0.7})
        registry = {
            ref: _evidence(ref, "strategy-expert-momentum")
            for ref in (*original.evidence_refs, *revised.evidence_refs)
        }

        class _Rev:
            def __init__(self) -> None:
                self.original_proposal_id = "p:rev"
                self.revised_proposal_id = "p:rev2"

        report = _report_with_revisions_and_answered_challenge(
            ("p:rev",), [_Rev()], answered_critique_id="critique:ans"
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:rev": original, "p:rev2": revised},
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p:rev2"
        candidate = package.candidate_set[0]
        # The challenge was answered by the revision: no standing materiality.
        assert candidate.score_breakdown.component("counter_evidence_materiality") == 0.0
        assert candidate.decision_score == pytest.approx(candidate.meta_score)
        assert candidate.material_dissent is True  # dissent preserved (MA-4F)


def _report_standing_challenge(
    proposal_ids: tuple[str, ...], *, materiality: float
) -> DebateReport:
    critique = CritiqueRecord(
        schema_version=SCHEMA,
        critique_id="critique:chg",
        proposal_id=proposal_ids[0],
        critic_agent_id="critic-regime",
        critic_version="1.0.0",
        stance=CritiqueStance.CHALLENGE,
        materiality=materiality,
        claim="regime inconsistent with direction",
        counter_evidence_refs=("ev:counter",),
        confidence=0.8,
        requested_action=RequestedAction.REVISE,
        trace=TRACE,
        created_at=CLOCK,
    )
    return DebateReport(
        schema_version=SCHEMA,
        debate_id="debate:test",
        run_id=TRACE.run_id,
        proposal_ids=proposal_ids,
        participants=("critic-regime",),
        initial_claims=("claim",),
        critiques=(critique,),
        counter_evidence=("ev:counter",),
        round_count=1,
        max_rounds=3,
        termination_reason=DebateTerminationReason.UNRESOLVED,
        outcome=DebateOutcome.UNRESOLVED,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=1,
        trace=TRACE,
        created_at=CLOCK,
    )


def _report_with_revisions_and_answered_challenge(
    proposal_ids: tuple[str, ...], revisions: list, *, answered_critique_id: str
) -> DebateReport:
    from trading_bot.multi_agent.contracts import ProposalRevision

    answered = CritiqueRecord(
        schema_version=SCHEMA,
        critique_id=answered_critique_id,
        proposal_id=proposal_ids[0],
        critic_agent_id="critic-regime",
        critic_version="1.0.0",
        stance=CritiqueStance.CHALLENGE,
        materiality=0.25,
        claim="material counter-evidence found",
        counter_evidence_refs=("ev:counter",),
        confidence=0.8,
        requested_action=RequestedAction.REVISE,
        trace=TRACE,
        created_at=CLOCK,
    )
    return DebateReport(
        schema_version=SCHEMA,
        debate_id="debate:test",
        run_id=TRACE.run_id,
        proposal_ids=proposal_ids,
        participants=("critic-regime",),
        initial_claims=("claim",),
        critiques=(answered,),
        revisions=tuple(
            ProposalRevision(
                schema_version=SCHEMA,
                original_proposal_id=r.original_proposal_id,
                revised_proposal_id=r.revised_proposal_id,
                triggering_critique_ids=(answered_critique_id,),
                revision_reason="material counter-evidence",
                trace=TRACE,
                created_at=CLOCK,
            )
            for r in revisions
        ),
        round_count=2,
        max_rounds=3,
        termination_reason=DebateTerminationReason.RESOLVED,
        outcome=DebateOutcome.REVISED,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=1,
        trace=TRACE,
        created_at=CLOCK,
    )


# ---------------------------------------------------------------------------
# MA-4S — unresolved conflict fail-closed
# ---------------------------------------------------------------------------


class TestUnresolvedConflict:
    def test_unresolved_long_short_blocks_both_sides(self) -> None:
        long_p = _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum")
        short_p = _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion")
        proposals = {"p:long": long_p, "p:short": short_p}
        registry = {
            ref: _evidence(ref, owner, claim="c")
            for p, owner in (
                (long_p, "strategy-expert-momentum"),
                (short_p, "strategy-expert-mean_reversion"),
            )
            for ref in p.evidence_refs
        }
        report_long = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:conf",
            run_id=TRACE.run_id,
            proposal_ids=("p:long", "p:short"),
            participants=("critic-evidence",),
            initial_claims=("a", "b"),
            round_count=3,
            max_rounds=3,
            termination_reason=DebateTerminationReason.UNRESOLVED,
            outcome=DebateOutcome.UNRESOLVED,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=0,
            trace=TRACE,
            created_at=CLOCK,
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[report_long],
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.NO_TRADE
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:long"].eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT
        assert by_id["p:short"].eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT
        assert DecisionReason.UNRESOLVED_CONFLICT in package.decision_reasons

    def test_unresolved_conflict_with_valid_alternative_selects_btc(self) -> None:
        long_p = _proposal("p:long", direction=TradeDirection.LONG, confidence=0.95)
        short_p = _proposal(
            "p:short", direction=TradeDirection.SHORT, strategy="mean_reversion", confidence=0.9
        )
        btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.7)
        proposals = {"p:long": long_p, "p:short": short_p, "p:btc": btc}
        registry = {
            ref: _evidence(ref, owner, claim="c")
            for p, owner in (
                (long_p, "strategy-expert-momentum"),
                (short_p, "strategy-expert-mean_reversion"),
                (btc, "strategy-expert-breakout"),
            )
            for ref in p.evidence_refs
        }
        report = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:conf",
            run_id=TRACE.run_id,
            proposal_ids=("p:long", "p:short"),
            participants=("critic-evidence",),
            initial_claims=("a", "b"),
            round_count=3,
            max_rounds=3,
            termination_reason=DebateTerminationReason.UNRESOLVED,
            outcome=DebateOutcome.UNRESOLVED,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=0,
            trace=TRACE,
            created_at=CLOCK,
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p:btc"
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:long"].eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT
        assert by_id["p:short"].eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT
        rejected = {a.final_proposal_id for a in package.rejected_alternatives}
        assert rejected == {"p:long", "p:short"}


# ---------------------------------------------------------------------------
# MA-4R — revision changes winner
# ---------------------------------------------------------------------------


class TestRevisionChangesWinner:
    def test_revision_demotes_original_and_btc_wins(self) -> None:
        sol = _proposal("p:sol", confidence=0.9)
        sol_revised = sol.model_copy(update={"proposal_id": "p:sol:r-1", "confidence": 0.7})
        btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.84)
        proposals = {"p:sol": sol, "p:sol:r-1": sol_revised, "p:btc": btc}
        registry = {
            ref: _evidence(ref, owner, claim="c")
            for p, owner in (
                (sol, "strategy-expert-momentum"),
                (sol_revised, "strategy-expert-momentum"),
                (btc, "strategy-expert-breakout"),
            )
            for ref in p.evidence_refs
        }

        class _Rev:
            def __init__(self) -> None:
                self.original_proposal_id = "p:sol"
                self.revised_proposal_id = "p:sol:r-1"

        report = _report_with_revisions_and_answered_challenge(
            ("p:sol",), [_Rev()], answered_critique_id="critique:rev"
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[report],
            assessments={"SOL": _assessment("SOL"), "BTC": _assessment("BTC", confidence=0.95)},
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p:btc"
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        sol_candidate = by_id["p:sol:r-1"]
        assert sol_candidate.proposal_id == "p:sol"
        assert sol_candidate.revision_lineage == ("p:sol", "p:sol:r-1")
        rejected = {a.final_proposal_id: a for a in package.rejected_alternatives}
        assert rejected["p:sol:r-1"].rejection_reasons == (DecisionReason.LOWER_RANKED_ALTERNATIVE,)


# ---------------------------------------------------------------------------
# MA-4H — NO_TRADE adversarial matrix
# ---------------------------------------------------------------------------


class TestNoTradeMatrix:
    def _decide(self, proposals: list[TradeProposal], registry=None, reports=()) -> DecisionPackage:
        reg = (
            registry
            if registry is not None
            else {
                ref: _evidence(ref, "strategy-expert-momentum")
                for p in proposals
                for ref in p.evidence_refs
            }
        )
        return _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={p.proposal_id: p for p in proposals},
            evidence_registry=reg,
            reports=list(reports),
            now=CLOCK,
        )

    def test_empty_board(self) -> None:
        package = self._decide([])
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert package.decision_reasons == (DecisionReason.NO_VALID_CANDIDATES,)
        assert package.selected_candidate_id is None

    def test_all_stale(self) -> None:
        stale = _proposal(
            "p:s",
            created=CLOCK - timedelta(hours=30),
            data_time=CLOCK - timedelta(hours=30),
        )
        package = self._decide([stale])
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert DecisionReason.STALE in package.decision_reasons

    def test_all_expired(self) -> None:
        expired = _proposal(
            "p:e",
            created=CLOCK - timedelta(minutes=2),
            data_time=CLOCK - timedelta(minutes=2),
            expires_at=CLOCK - timedelta(minutes=1),
        )
        package = self._decide([expired])
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert DecisionReason.EXPIRED in package.decision_reasons

    def test_all_insufficient_evidence(self) -> None:
        # No evidence refs at all: the evidence-completeness gate fires
        # (a missing *referenced* id is INVALID_EVIDENCE, tested separately).
        p = _proposal("p:i").model_copy(update={"evidence_refs": ()})
        package = self._decide([p], registry={})
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert DecisionReason.INSUFFICIENT_EVIDENCE in package.decision_reasons

    def test_all_unresolved(self) -> None:
        long_p = _proposal("p:l", direction=TradeDirection.LONG)
        short_p = _proposal("p:s2", direction=TradeDirection.SHORT, strategy="mean_reversion")
        report = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:conf",
            run_id=TRACE.run_id,
            proposal_ids=("p:l", "p:s2"),
            participants=("critic-evidence",),
            initial_claims=("a", "b"),
            round_count=1,
            max_rounds=3,
            termination_reason=DebateTerminationReason.UNRESOLVED,
            outcome=DebateOutcome.UNRESOLVED,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=0,
            trace=TRACE,
            created_at=CLOCK,
        )
        package = self._decide([long_p, short_p], reports=[report])
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert DecisionReason.UNRESOLVED_CONFLICT in package.decision_reasons

    def test_all_invalid_trace(self) -> None:
        p = _proposal("p:t")
        foreign = TraceContext(
            run_id="other", trace_id=TRACE.trace_id, correlation_id="c", causation_id="c"
        )
        p = p.model_copy(update={"trace": foreign})
        package = self._decide([p])
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert DecisionReason.INVALID_TRACE in package.decision_reasons

    def test_mixed_invalid_no_survivor(self) -> None:
        stale = _proposal(
            "p:a",
            created=CLOCK - timedelta(hours=30),
            data_time=CLOCK - timedelta(hours=30),
        )
        expired = _proposal(
            "p:b",
            created=CLOCK - timedelta(minutes=2),
            data_time=CLOCK - timedelta(minutes=2),
            expires_at=CLOCK - timedelta(minutes=1),
        )
        ghost = _proposal("p:c", evidence_id="ev:none")
        package = self._decide([stale, expired, ghost], registry={})
        assert package.outcome is DecisionOutcome.NO_TRADE
        assert len(package.candidate_set) == 3
        assert package.selected_candidate_id is None


# ---------------------------------------------------------------------------
# MA-4U/V — order independence + deterministic replay
# ---------------------------------------------------------------------------


def _three_candidates() -> tuple[
    dict[str, TradeProposal], dict[str, AgentEvidence], list[DebateReport]
]:
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    eth = _proposal("p:eth", asset="ETH", strategy="trend", confidence=0.79)
    proposals = {"p:sol": sol, "p:btc": btc, "p:eth": eth}
    registry = {
        ref: _evidence(ref, owner, claim="c")
        for p, owner in (
            (sol, "strategy-expert-momentum"),
            (btc, "strategy-expert-breakout"),
            (eth, "strategy-expert-trend"),
        )
        for ref in p.evidence_refs
    }
    return proposals, registry, [_report_supported(("p:sol",))]


class TestOrderIndependenceAndReplay:
    def test_proposal_order_permutation_same_package(self) -> None:
        proposals, registry, reports = _three_candidates()
        base = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK,
        )
        shuffled = dict(reversed(list(proposals.items())))
        permuted = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=shuffled,
            evidence_registry=dict(reversed(list(registry.items()))),
            reports=list(reversed(reports)),
            now=CLOCK,
        )
        assert base.to_dict() == permuted.to_dict()

    def test_deterministic_replay_three_runs_byte_identical(self) -> None:
        proposals, registry, reports = _three_candidates()
        payloads = []
        for _ in range(3):
            package = _make_engine().decide(
                snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
                proposals=proposals,
                evidence_registry=registry,
                reports=reports,
                now=CLOCK,
            )
            payloads.append(json.dumps(package.to_dict(), sort_keys=True))
        assert len(set(payloads)) == 1

    def test_score_tie_broken_by_stable_proposal_identity(self) -> None:
        a = _proposal("p:aaa", confidence=0.8)
        b = _proposal("p:bbb", confidence=0.8)
        registry = {
            ref: _evidence(ref, "strategy-expert-momentum")
            for p in (a, b)
            for ref in p.evidence_refs
        }
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:bbb": b, "p:aaa": a},
            evidence_registry=registry,
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p:aaa"


# ---------------------------------------------------------------------------
# MA-4P — independent verifier
# ---------------------------------------------------------------------------


class TestDecisionVerifier:
    def _verified_package(self) -> DecisionPackage:
        proposals, registry, reports = _three_candidates()
        return _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK,
        )

    def test_valid_package_verifies(self) -> None:
        proposals, registry, reports = _three_candidates()
        package = self._verified_package()
        result = DecisionPackageVerifier().verify(
            package,
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK + timedelta(minutes=1),
        )
        assert result.passed
        assert all(status == "PASS" for _, status, _ in result.checks)

    def test_builder_is_never_verifier(self) -> None:
        package = self._verified_package()
        meta = package.verification_metadata
        assert meta.builder_agent_id == DECISION_ENGINE_ID
        assert meta.verifier_agent_id == DECISION_VERIFIER_ID
        assert meta.builder_agent_id != meta.verifier_agent_id

    def test_tampered_package_rejected(self) -> None:
        package = self._verified_package()
        tampered = package.model_copy(
            update={
                "selected_candidate_id": None,
                "outcome": DecisionOutcome.NO_TRADE,
            }
        )
        result = DecisionPackageVerifier().verify(
            tampered,
            proposals={},
            evidence_registry={},
            now=CLOCK,
        )
        assert not result.passed
        assert any(status == "FAIL" for _, status, _ in result.checks)

    def test_verifier_rejects_expired_selection(self) -> None:
        package = self._verified_package()
        late = CLOCK + timedelta(hours=2)
        _, registry, reports = _three_candidates()
        result = DecisionPackageVerifier().verify(
            package,
            proposals={
                c.final_proposal_id: _proposal(c.final_proposal_id) for c in package.candidate_set
            },
            evidence_registry=registry,
            reports=reports,
            now=late,
        )
        assert not result.passed


# ---------------------------------------------------------------------------
# CP-MA-004.1 — cross-run isolation (RUN AUTHORITY / ADR-MA-0006)
#
# Run authority is first-class: trace_id is scoped inside run_id and a
# matching trace never overrides a run mismatch. Matrix A-H plus sibling
# artifacts and verifier cross-run rejection.
# ---------------------------------------------------------------------------


def _trace_for(run_id: str, trace_id: str | None = None) -> TraceContext:
    return TraceContext(
        run_id=run_id,
        trace_id=trace_id or f"{run_id}-trace",
        correlation_id="corr",
        causation_id="cause",
    )


def _evidence_run(
    evidence_id: str,
    *,
    run_id: str,
    trace: TraceContext,
    producer: str = "strategy-expert-momentum",
) -> AgentEvidence:
    return AgentEvidence(
        schema_version=SCHEMA,
        evidence_id=evidence_id,
        run_id=run_id,
        producer_agent_id=producer,
        evidence_type="strategy_signal",
        source_ref=f"ctx:{evidence_id}",
        claim_refs=("claim",),
        observed_at=CLOCK,
        available_at=CLOCK,
        content_hash="a" * 64,
        metadata=(),
        trace=trace,
    )


def _proposal_run(
    proposal_id: str,
    *,
    run_id: str,
    trace: TraceContext,
    confidence: float = 0.9,
) -> TradeProposal:
    return TradeProposal(
        schema_version=SCHEMA,
        proposal_id=proposal_id,
        run_id=run_id,
        trace_id=trace.trace_id,
        asset="SOL",
        direction=TradeDirection.LONG,
        strategy="momentum",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(f"ev:{proposal_id}",),
        invalidation="structural stop",
        confidence=confidence,
        data_time=CLOCK,
        created_at=CLOCK,
        expires_at=CLOCK + timedelta(minutes=15),
        trace=trace,
    )


class TestCrossRunIsolation:
    RUN_A = TRACE.run_id
    RUN_B = "run-b"

    def _board(self, *proposals: TradeProposal) -> OpportunitySnapshot:
        return OpportunitySnapshot(
            opportunities=tuple(
                Opportunity(
                    proposal=p,
                    evidence_refs=tuple(p.evidence_refs),
                    source_agent_id="strategy-expert-momentum",
                    source_agent_version="1.0.0",
                )
                for p in proposals
            ),
            conflicts=(),
        )

    def _current_engine(self) -> DecisionEngine:
        return DecisionEngine(run_id=self.RUN_A)

    # -- Matrix A-H ---------------------------------------------------------

    def test_matrix_A_foreign_proposal_fail_closed(self) -> None:
        p = _proposal_run("p:sol", run_id=self.RUN_B, trace=_trace_for(self.RUN_B))
        with pytest.raises(DecisionError):
            self._current_engine().decide(
                snapshot=self._board(p),
                proposals={p.proposal_id: p},
                evidence_registry={
                    "ev:p:sol": _evidence_run(
                        "ev:p:sol", run_id=self.RUN_B, trace=_trace_for(self.RUN_B)
                    )
                },
                now=CLOCK,
            )

    def test_matrix_B_foreign_debate_report_fail_closed(self) -> None:
        """DEF-MA4-001 regression: foreign report must not flip the decision."""
        p = _proposal_run("p:sol", run_id=self.RUN_A, trace=TRACE)
        foreign = _report_supported(("p:sol",)).model_copy(update={"run_id": self.RUN_B})
        with pytest.raises(DecisionError, match="debate report run does not match engine run"):
            self._current_engine().decide(
                snapshot=self._board(p),
                proposals={p.proposal_id: p},
                evidence_registry={
                    "ev:p:sol": _evidence_run("ev:p:sol", run_id=self.RUN_A, trace=TRACE)
                },
                reports=[foreign],
                now=CLOCK,
            )

    def test_matrix_C_foreign_evidence_ineligible(self) -> None:
        p = _proposal_run("p:sol", run_id=self.RUN_A, trace=TRACE)
        package = self._current_engine().decide(
            snapshot=self._board(),
            proposals={p.proposal_id: p},
            evidence_registry={
                "ev:p:sol": _evidence_run(
                    "ev:p:sol", run_id=self.RUN_B, trace=_trace_for(self.RUN_B)
                )
            },
            now=CLOCK,
        )
        cand = next(c for c in package.candidate_set if c.final_proposal_id == "p:sol")
        assert cand.eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE
        assert package.outcome is DecisionOutcome.NO_TRADE

    def test_matrix_D_forged_trace_foreign_evidence_rejected(self) -> None:
        """DEF-MA4-002 regression: matching trace_id never grants run authority."""
        p = _proposal_run("p:sol", run_id=self.RUN_A, trace=TRACE)
        forged = _evidence_run(
            "ev:p:sol", run_id=self.RUN_B, trace=_trace_for(self.RUN_B)
        ).model_copy(update={"trace": TRACE})
        package = self._current_engine().decide(
            snapshot=self._board(),
            proposals={p.proposal_id: p},
            evidence_registry={"ev:p:sol": forged},
            now=CLOCK,
        )
        cand = next(c for c in package.candidate_set if c.final_proposal_id == "p:sol")
        assert cand.eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE
        assert package.outcome is DecisionOutcome.NO_TRADE

    def test_matrix_E_current_run_foreign_trace_rejected(self) -> None:
        p = _proposal_run("p:sol", run_id=self.RUN_A, trace=TRACE)
        evidence = _evidence_run(
            "ev:p:sol", run_id=self.RUN_A, trace=_trace_for(self.RUN_A, "other-trace")
        )
        package = self._current_engine().decide(
            snapshot=self._board(),
            proposals={p.proposal_id: p},
            evidence_registry={"ev:p:sol": evidence},
            now=CLOCK,
        )
        cand = next(c for c in package.candidate_set if c.final_proposal_id == "p:sol")
        assert cand.eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE

    def test_matrix_F_foreign_revision_fail_closed(self) -> None:
        """Revisions are scoped inside their report: foreign report => fail closed."""
        p1 = _proposal_run("p1", run_id=self.RUN_A, trace=TRACE)
        p2 = p1.model_copy(update={"proposal_id": "p2"})
        report = _report_with_revisions(["p1", "p2"], [_ForcedRev("p1", "p2")]).model_copy(
            update={"run_id": self.RUN_B}
        )
        with pytest.raises(DecisionError, match="debate report run does not match engine run"):
            self._current_engine().decide(
                snapshot=self._board(p1),
                proposals={"p1": p1, "p2": p2},
                evidence_registry={"ev:p1": _evidence_run("ev:p1", run_id=self.RUN_A, trace=TRACE)},
                reports=[report],
                now=CLOCK,
            )

    def test_matrix_G_mixed_evidence_set_isolates_contamination(self) -> None:
        good = _proposal_run("p:good", run_id=self.RUN_A, trace=TRACE, confidence=0.9)
        bad = _proposal_run("p:bad", run_id=self.RUN_A, trace=TRACE, confidence=0.95)
        registry = {
            "ev:p:good": _evidence_run("ev:p:good", run_id=self.RUN_A, trace=TRACE),
            "ev:p:bad": _evidence_run("ev:p:bad", run_id=self.RUN_B, trace=_trace_for(self.RUN_B)),
        }
        package = self._current_engine().decide(
            snapshot=self._board(),
            proposals={"p:good": good, "p:bad": bad},
            evidence_registry=registry,
            now=CLOCK,
        )
        by_id = {c.final_proposal_id: c for c in package.candidate_set}
        assert by_id["p:bad"].eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE
        assert by_id["p:good"].eligibility is DecisionEligibility.ELIGIBLE
        assert package.outcome is DecisionOutcome.SELECTED
        assert package.selected_candidate_id == "p:good"

    def test_matrix_H_all_current_control_selects_and_verifies(self) -> None:
        proposals, registry, reports = _three_candidates()
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.SELECTED
        result = DecisionPackageVerifier().verify(
            package,
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK + timedelta(minutes=1),
        )
        assert result.passed

    # -- Sibling artifacts ---------------------------------------------------

    def test_foreign_snapshot_proposal_fail_closed(self) -> None:
        p_ok = _proposal_run("p:ok", run_id=self.RUN_A, trace=TRACE)
        p_foreign = _proposal_run("p:foreign", run_id=self.RUN_B, trace=_trace_for(self.RUN_B))
        with pytest.raises(DecisionError, match="board proposal run does not match engine run"):
            self._current_engine().decide(
                snapshot=self._board(p_foreign),
                proposals={"p:ok": p_ok},
                evidence_registry={
                    "ev:p:ok": _evidence_run("ev:p:ok", run_id=self.RUN_A, trace=TRACE)
                },
                now=CLOCK,
            )

    def test_foreign_assessment_fail_closed(self) -> None:
        import dataclasses

        p = _proposal_run("p:sol", run_id=self.RUN_A, trace=TRACE)
        foreign = dataclasses.replace(_assessment("SOL"), trace=_trace_for(self.RUN_B))
        with pytest.raises(DecisionError, match="assessment run does not match engine run"):
            self._current_engine().decide(
                snapshot=self._board(p),
                proposals={p.proposal_id: p},
                evidence_registry={
                    "ev:p:sol": _evidence_run("ev:p:sol", run_id=self.RUN_A, trace=TRACE)
                },
                assessments={"SOL": foreign},
                now=CLOCK,
            )

    # -- Verifier cross-run authority ---------------------------------------

    def _fresh_package(self) -> tuple:
        proposals, registry, reports = _three_candidates()
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK,
        )
        return package, proposals, registry, reports

    def test_verifier_rejects_foreign_run_evidence(self) -> None:
        package, proposals, registry, reports = self._fresh_package()
        selected = next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )
        ref = selected.supporting_evidence_refs[0]
        poisoned = dict(registry)
        poisoned[ref] = registry[ref].model_copy(update={"run_id": self.RUN_B})
        result = DecisionPackageVerifier().verify(
            package, proposals=proposals, evidence_registry=poisoned, reports=reports, now=CLOCK
        )
        assert not result.passed
        assert any(
            name == "run_authority_evidence" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_verifier_rejects_foreign_run_report(self) -> None:
        package, proposals, registry, reports = self._fresh_package()
        poisoned = [
            r.model_copy(update={"run_id": self.RUN_B}) if i == 0 else r
            for i, r in enumerate(reports)
        ]
        result = DecisionPackageVerifier().verify(
            package, proposals=proposals, evidence_registry=registry, reports=poisoned, now=CLOCK
        )
        assert not result.passed
        assert any(
            name == "run_authority_debate_reports" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_verifier_rejects_foreign_run_proposal(self) -> None:
        package, proposals, registry, reports = self._fresh_package()
        poisoned = dict(proposals)
        poisoned["p:sol"] = proposals["p:sol"].model_copy(update={"run_id": self.RUN_B})
        result = DecisionPackageVerifier().verify(
            package, proposals=poisoned, evidence_registry=registry, reports=reports, now=CLOCK
        )
        assert not result.passed
        assert any(
            name == "run_authority_proposals" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_verifier_rejects_reports_registry_foreign_run(self) -> None:
        package, proposals, registry, reports = self._fresh_package()
        unreferenced = _report_supported(("p:btc",)).model_copy(
            update={"debate_id": "debate:other", "run_id": self.RUN_B}
        )
        result = DecisionPackageVerifier().verify(
            package,
            proposals=proposals,
            evidence_registry=registry,
            reports=[*reports, unreferenced],
            now=CLOCK,
        )
        assert not result.passed
        assert any(
            name == "run_authority_reports_registry" and status == "FAIL"
            for name, status, _ in result.checks
        )

    # -- Deterministic replay after repair (CP-MA-004.2 §21) -----------------

    def test_replay_after_repair_valid_and_contaminated(self) -> None:
        proposals, registry, reports = _three_candidates()
        packages = [
            _make_engine().decide(
                snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
                proposals=proposals,
                evidence_registry=registry,
                reports=reports,
                now=CLOCK,
            )
            for _ in range(3)
        ]
        assert (
            packages[0].model_dump_json()
            == packages[1].model_dump_json()
            == packages[2].model_dump_json()
        )

        foreign = reports[0].model_copy(update={"run_id": self.RUN_B})
        rejections = 0
        for _ in range(3):
            with pytest.raises(DecisionError, match="debate report run does not match engine run"):
                _make_engine().decide(
                    snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
                    proposals=proposals,
                    evidence_registry=registry,
                    reports=[foreign],
                    now=CLOCK,
                )
            rejections += 1
        assert rejections == 3

    def test_replay_evidence_tamper_verification_deterministic(self) -> None:
        """Strip and swap tampers reject identically across 3 runs each."""
        package, proposals, registry, reports = TestSelectedEvidenceBinding()._decided()
        selected_id = package.selected_candidate_id
        verifier = DecisionPackageVerifier()

        def _verify(pkg, reg):
            return verifier.verify(
                pkg, proposals=proposals, evidence_registry=reg, reports=reports, now=CLOCK
            )

        # Full strip x3 (CERT-MA4-001-RETRY-001 vector).
        stripped = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": ()})
                    if c.final_proposal_id == selected_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        strip_results = [_verify(stripped, registry) for _ in range(3)]
        assert all(not r.passed for r in strip_results)
        assert len({json.dumps(r.to_dict(), sort_keys=True) for r in strip_results}) == 1

        # Swap x3 (registered, current-run, trace-consistent but uncommitted).
        extra = _evidence_run("ev:replay-swap", run_id=self.RUN_A, trace=TRACE)
        swap_registry = {**registry, "ev:replay-swap": extra}
        swapped = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "supporting_evidence_refs": (
                                *c.supporting_evidence_refs[:-1],
                                "ev:replay-swap",
                            )
                        }
                    )
                    if c.final_proposal_id == selected_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        swap_results = [_verify(swapped, swap_registry) for _ in range(3)]
        assert all(not r.passed for r in swap_results)
        assert len({json.dumps(r.to_dict(), sort_keys=True) for r in swap_results}) == 1

        # Clean control still verifies identically x3.
        clean_results = [_verify(package, registry) for _ in range(3)]
        assert all(r.passed for r in clean_results)
        assert len({json.dumps(r.to_dict(), sort_keys=True) for r in clean_results}) == 1


# ---------------------------------------------------------------------------
# CP-MA-004.2 - selected evidence authority binding (CERT-MA4-001-RETRY-001)
#
# Evidence authority originates from the canonical terminal TradeProposal;
# the package's own lists are never trusted as their own source of truth.
# Policy: SELECTED_AUTHORITY_CRITICAL (exact set binding), rejected
# candidates REJECTED_AUDIT_ONLY (registered + current-run subset).
# ---------------------------------------------------------------------------


class TestSelectedEvidenceBinding:
    RUN_A = TRACE.run_id
    RUN_B = "run-b"

    def _decided(self) -> tuple:
        proposals, registry, reports = _three_candidates()
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK,
        )
        return package, proposals, registry, reports

    def _verify(self, package, proposals, registry, reports):
        return DecisionPackageVerifier().verify(
            package, proposals=proposals, evidence_registry=registry, reports=reports, now=CLOCK
        )

    def _selected(self, package):
        return next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )

    def test_selected_candidate_exact_evidence_verified(self) -> None:
        """Control: untouched package binds exactly to the terminal proposal."""
        package, proposals, registry, reports = self._decided()
        result = self._verify(package, proposals, registry, reports)
        assert result.passed
        assert any(
            name == "selected_evidence_binding" and status == "PASS"
            for name, status, _ in result.checks
        )

    def test_selected_candidate_empty_evidence_rejected(self) -> None:
        """Full stripping - the exact CERT-MA4-001-RETRY-001 certification vector."""
        package, proposals, registry, reports = self._decided()
        stripped = tuple(
            c.model_copy(update={"supporting_evidence_refs": ()})
            if c.final_proposal_id == package.selected_candidate_id
            else c
            for c in package.candidate_set
        )
        tampered = package.model_copy(update={"candidate_set": stripped})
        result = self._verify(tampered, proposals, registry, reports)
        assert not result.passed
        assert any(
            name == "selected_evidence_binding" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_selected_candidate_partial_evidence_rejected(self) -> None:
        package, proposals, registry, reports = self._decided()
        selected = self._selected(package)
        assert len(selected.supporting_evidence_refs) >= 1
        partial = tuple(
            c.model_copy(update={"supporting_evidence_refs": c.supporting_evidence_refs[:-1]})
            if c.final_proposal_id == package.selected_candidate_id
            else c
            for c in package.candidate_set
        )
        tampered = package.model_copy(update={"candidate_set": partial})
        result = self._verify(tampered, proposals, registry, reports)
        assert not result.passed

    def test_selected_candidate_swapped_evidence_rejected(self) -> None:
        """Swapped ref is registered, current-run, trace-consistent - and still
        rejected because it is not evidence committed by the terminal proposal."""
        package, proposals, registry, reports = self._decided()
        extra = _evidence_run("ev:valid-but-uncommitted", run_id=self.RUN_A, trace=TRACE)
        registry = {**registry, "ev:valid-but-uncommitted": extra}
        swapped = tuple(
            c.model_copy(
                update={
                    "supporting_evidence_refs": (
                        *c.supporting_evidence_refs[:-1],
                        "ev:valid-but-uncommitted",
                    )
                }
            )
            if c.final_proposal_id == package.selected_candidate_id
            else c
            for c in package.candidate_set
        )
        tampered = package.model_copy(update={"candidate_set": swapped})
        result = self._verify(tampered, proposals, registry, reports)
        assert not result.passed

    def test_selected_candidate_added_evidence_rejected(self) -> None:
        package, proposals, registry, reports = self._decided()
        extra = _evidence_run("ev:added", run_id=self.RUN_A, trace=TRACE)
        registry = {**registry, "ev:added": extra}
        enriched = tuple(
            c.model_copy(
                update={
                    "supporting_evidence_refs": (
                        *c.supporting_evidence_refs,
                        "ev:added",
                    )
                }
            )
            if c.final_proposal_id == package.selected_candidate_id
            else c
            for c in package.candidate_set
        )
        tampered = package.model_copy(update={"candidate_set": enriched})
        result = self._verify(tampered, proposals, registry, reports)
        assert not result.passed

    def test_selected_candidate_duplicate_evidence_rejected(self) -> None:
        package, proposals, registry, reports = self._decided()
        selected = self._selected(package)
        refs = selected.supporting_evidence_refs
        assert len(refs) >= 1
        duplicated = tuple(
            c.model_copy(update={"supporting_evidence_refs": (*refs, refs[0])})
            if c.final_proposal_id == package.selected_candidate_id
            else c
            for c in package.candidate_set
        )
        tampered = package.model_copy(update={"candidate_set": duplicated})
        result = self._verify(tampered, proposals, registry, reports)
        assert not result.passed

    def test_selected_candidate_final_proposal_binding(self) -> None:
        """T14: package pointing at a non-terminal ancestor must be rejected."""
        p1 = _proposal("p1", confidence=0.9)
        p2 = p1.model_copy(update={"proposal_id": "p2"})
        report = _report_with_revisions_and_answered_challenge(
            ("p1", "p2"), [_ForcedRev("p1", "p2")], answered_critique_id="critique:chg"
        )
        registry = {
            "ev:p1": _evidence("ev:p1", "strategy-expert-momentum", claim="c"),
            "ev:p2": _evidence("ev:p2", "strategy-expert-momentum", claim="c"),
        }
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p1": p1, "p2": p2},
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p2"  # honest engine binds terminal
        ancestor = package.model_copy(
            update={
                "selected_candidate_id": "p1",
                "candidate_set": tuple(
                    c.model_copy(update={"final_proposal_id": "p1"}) for c in package.candidate_set
                ),
            }
        )
        result = self._verify(ancestor, {"p1": p1, "p2": p2}, registry, [report])
        assert not result.passed
        assert any(
            name == "final_proposal_binding" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_rejected_candidate_audit_allows_incomplete_refs(self) -> None:
        """REJECTED_AUDIT_ONLY: a rejected candidate keeps its refs; the audit
        requires registered + current-run, not exact terminal binding."""
        package, proposals, registry, reports = self._decided()
        rejected_ids = {c.final_proposal_id for c in package.candidate_set} - {
            package.selected_candidate_id
        }
        target = next(c for c in package.candidate_set if c.final_proposal_id in rejected_ids)
        subset = target.supporting_evidence_refs[:-1] or ()
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": subset})
                    if c.final_proposal_id == target.final_proposal_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        result = self._verify(tampered, proposals, registry, reports)
        assert result.passed  # audit-only policy: subset still verifies

    def test_binding_is_order_independent(self) -> None:
        """Canonical identity comparison: [E1, E2] == [E2, E1] when the
        terminal proposal legitimately commits two evidence items."""
        p = _proposal("p:multi", confidence=0.9).model_copy(
            update={"evidence_refs": ("ev:multi-a", "ev:multi-b")}
        )
        registry = {
            "ev:multi-a": _evidence_run("ev:multi-a", run_id=self.RUN_A, trace=TRACE),
            "ev:multi-b": _evidence_run("ev:multi-b", run_id=self.RUN_A, trace=TRACE),
        }
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:multi": p},
            evidence_registry=registry,
            reports=(),
            now=CLOCK,
        )
        selected = self._selected(package)
        assert len(selected.supporting_evidence_refs) == 2
        # Clean control verifies with canonical set equality.
        assert self._verify(package, {"p:multi": p}, registry, ()).passed
        # Input-order permutation of the same identities must also verify.
        permuted = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "supporting_evidence_refs": tuple(reversed(c.supporting_evidence_refs))
                        }
                    )
                    for c in package.candidate_set
                )
            }
        )
        assert self._verify(permuted, {"p:multi": p}, registry, ()).passed

    def test_binding_consistency_with_scores(self) -> None:
        """Score binding audit: meta component == meta_score and final ==
        meta - penalty still hold alongside the evidence binding (no redesign)."""
        package, proposals, registry, reports = self._decided()
        selected = self._selected(package)
        assert selected.score_breakdown.component("meta_ranker_score") == selected.meta_score
        assert selected.decision_score == selected.score_breakdown.final_score
        assert self._verify(package, proposals, registry, reports).passed


# ---------------------------------------------------------------------------
# CP-MA-004.3 - authoritative debate-derived blockers (CERT-MA4-001-RETRY-2-
# 001). The verifier never trusts package-side eligibility / rejection /
# decision claims for blocking debate state: it re-derives UNRESOLVED and
# INSUFFICIENT_EVIDENCE from the authoritative DebateReports (lineage-aware)
# and board conflicts from an optional authoritative snapshot.
# ---------------------------------------------------------------------------


class TestAuthoritativeDebateBlockers:
    STRONG_CRITIQUE = CritiqueRecord(
        schema_version=SCHEMA,
        critique_id="critique:chg",
        proposal_id="p:l",
        critic_agent_id="critic-regime",
        critic_version="1.0.0",
        stance=CritiqueStance.CHALLENGE,
        materiality=0.3,
        claim="material counter-signal",
        counter_evidence_refs=("ev:counter",),
        confidence=0.8,
        requested_action=RequestedAction.REVISE,
        trace=TRACE,
        created_at=CLOCK,
    )

    def _unresolved_package(self) -> tuple:
        """Honest SOL LONG vs SOL SHORT with UNRESOLVED debate -> NO_TRADE."""
        p_l = _proposal(
            "p:l", direction=TradeDirection.LONG, asset="SOL", strategy="momentum", confidence=0.95
        )
        p_s = _proposal(
            "p:s",
            direction=TradeDirection.SHORT,
            asset="SOL",
            strategy="mean_reversion",
            confidence=0.90,
        )
        report = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:unresolved",
            run_id=TRACE.run_id,
            proposal_ids=("p:l", "p:s"),
            participants=("critic-regime",),
            initial_claims=("claim",),
            critiques=(self.STRONG_CRITIQUE,),
            counter_evidence=("ev:counter",),
            round_count=1,
            max_rounds=3,
            termination_reason=DebateTerminationReason.UNRESOLVED,
            outcome=DebateOutcome.UNRESOLVED,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=1,
            trace=TRACE,
            created_at=CLOCK,
        )
        proposals = {"p:l": p_l, "p:s": p_s}
        registry = {
            "ev:p:l": _evidence_run("ev:p:l", run_id=TRACE.run_id, trace=TRACE),
            "ev:p:s": _evidence_run("ev:p:s", run_id=TRACE.run_id, trace=TRACE),
        }
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.NO_TRADE
        return package, proposals, registry, [report]

    def _insufficient_package(self) -> tuple:
        """Honest ETH proposal with INSUFFICIENT_EVIDENCE debate -> NO_TRADE."""
        p_eth = _proposal("p:eth", asset="ETH", strategy="trend", confidence=0.79)
        report = DebateReport(
            schema_version=SCHEMA,
            debate_id="debate:insufficient",
            run_id=TRACE.run_id,
            proposal_ids=("p:eth",),
            participants=("critic-evidence",),
            initial_claims=("claim",),
            round_count=1,
            max_rounds=3,
            termination_reason=DebateTerminationReason.INSUFFICIENT_EVIDENCE,
            outcome=DebateOutcome.INSUFFICIENT_EVIDENCE,
            unique_supporting_evidence_count=0,
            unique_counter_evidence_count=0,
            trace=TRACE,
            created_at=CLOCK,
        )
        proposals = {"p:eth": p_eth}
        registry = {"ev:p:eth": _evidence_run("ev:p:eth", run_id=TRACE.run_id, trace=TRACE)}
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.NO_TRADE
        return package, proposals, registry, [report]

    @staticmethod
    def _forge_consistent_selection(package, selected_id: str) -> DecisionPackage:
        """Fully internally-consistent forgery: flip eligibility, clear
        reasons, rewrite selection/reasons/alternatives (T15/T16 vector).
        The ONLY contradiction is against the authoritative DebateReports."""
        forged_candidates = tuple(
            c.model_copy(
                update={"eligibility": DecisionEligibility.ELIGIBLE, "rejection_reasons": ()}
            )
            if c.final_proposal_id == selected_id
            else c
            for c in package.candidate_set
        )
        return package.model_copy(
            update={
                "candidate_set": forged_candidates,
                "selected_candidate_id": selected_id,
                "outcome": DecisionOutcome.SELECTED,
                "decision_reasons": (DecisionReason.HIGHEST_ADMISSIBLE_SCORE,),
                "rejected_alternatives": tuple(
                    a for a in package.rejected_alternatives if a.final_proposal_id != selected_id
                ),
            }
        )

    def test_verifier_rejects_forged_eligible_selected_candidate_when_debate_unresolved(
        self,
    ) -> None:
        """T15 strong UNRESOLVED forgery (CERT-MA4-001-RETRY-2-001 vector)."""
        package, proposals, registry, reports = self._unresolved_package()
        forged = self._forge_consistent_selection(package, "p:l")
        result = DecisionPackageVerifier().verify(
            forged, proposals=proposals, evidence_registry=registry, reports=reports, now=CLOCK
        )
        assert not result.passed
        assert any(
            name == "authoritative_debate_blocker_rederivation" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_verifier_rejects_forged_eligible_selected_candidate_when_debate_insufficient_evidence(
        self,
    ) -> None:
        """T16 strong INSUFFICIENT_EVIDENCE forgery."""
        package, proposals, registry, reports = self._insufficient_package()
        forged = self._forge_consistent_selection(package, "p:eth")
        result = DecisionPackageVerifier().verify(
            forged, proposals=proposals, evidence_registry=registry, reports=reports, now=CLOCK
        )
        assert not result.passed
        assert any(
            name == "authoritative_debate_blocker_rederivation" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_verifier_accepts_genuinely_resolved_debate_candidate(self) -> None:
        """RESOLVED control: initial conflict -> revision -> REVISED terminal.
        The verifier distinguishes historical challenge from standing blocker
        and must not over-block, even with a conflicting snapshot present."""
        p1 = _proposal("p1", confidence=0.9)
        p2 = p1.model_copy(update={"proposal_id": "p2"})
        report = _report_with_revisions_and_answered_challenge(
            ("p1", "p2"), [_ForcedRev("p1", "p2")], answered_critique_id="critique:chg"
        )
        proposals = {"p1": p1, "p2": p2}
        registry = {
            "ev:p1": _evidence("ev:p1", "strategy-expert-momentum", claim="c"),
            "ev:p2": _evidence("ev:p2", "strategy-expert-momentum", claim="c"),
        }
        from trading_bot.multi_agent.opportunity import ConflictCase, Opportunity

        snapshot = OpportunitySnapshot(
            opportunities=(
                Opportunity(
                    proposal=p2,
                    evidence_refs=("ev:p2",),
                    source_agent_id="s",
                    source_agent_version="1",
                ),
            ),
            conflicts=(
                ConflictCase(
                    conflict_id="conflict:1",
                    asset="SOL",
                    proposal_ids=("p1", "p2"),
                    directions=("LONG", "SHORT"),
                ),
            ),
        )
        package = _make_engine().decide(
            snapshot=snapshot,
            proposals=proposals,
            evidence_registry=registry,
            reports=[report],
            now=CLOCK,
        )
        assert package.selected_candidate_id == "p2"
        result = DecisionPackageVerifier().verify(
            package,
            proposals=proposals,
            evidence_registry=registry,
            reports=[report],
            snapshot=snapshot,
            now=CLOCK,
        )
        assert result.passed
        assert any(
            name == "authoritative_debate_blocker_rederivation" and status == "PASS"
            for name, status, _ in result.checks
        )

    def test_verifier_does_not_trust_package_eligibility_for_debate_blockers(
        self,
    ) -> None:
        """The forbidden fallback pattern: a package claiming ELIGIBLE must
        not bypass the authoritative blocker. Assert the check keyed honestly
        (re-derivation) and that even a rejected-candidate-consistent
        eligibility flip cannot override it (covered by T15; here we assert
        the check itself never reads package claims to establish authority)."""
        package, proposals, registry, reports = self._unresolved_package()
        forged = self._forge_consistent_selection(package, "p:l")
        # The forgery is internally consistent: every package-side field
        # agrees with SELECTED/p:l+ELIGIBLE. Only external authority disagrees.
        result = DecisionPackageVerifier().verify(
            forged, proposals=proposals, evidence_registry=registry, reports=reports, now=CLOCK
        )
        assert result.verdict is DecisionVerificationStatus.REJECTED
        # And the honest NO_TRADE package verifies as a valid non-selection.
        honest = DecisionPackageVerifier().verify(
            package, proposals=proposals, evidence_registry=registry, reports=reports, now=CLOCK
        )
        assert honest.passed

    def test_verifier_rejects_forged_selection_with_board_conflict_without_debate(
        self,
    ) -> None:
        """Board-conflict-without-debate blocker re-derived from the snapshot:
        deleting the package-side conflict marker cannot resurrect a selection."""
        p_a = _proposal("p:a", direction=TradeDirection.LONG, asset="SOL", confidence=0.95)
        p_b = _proposal(
            "p:b",
            direction=TradeDirection.SHORT,
            asset="SOL",
            strategy="mean_reversion",
            confidence=0.90,
        )
        from trading_bot.multi_agent.opportunity import ConflictCase

        snapshot = OpportunitySnapshot(
            opportunities=(),
            conflicts=(
                ConflictCase(
                    conflict_id="conflict:2",
                    asset="SOL",
                    proposal_ids=("p:a", "p:b"),
                    directions=("LONG", "SHORT"),
                ),
            ),
        )
        proposals = {"p:a": p_a, "p:b": p_b}
        registry = {
            "ev:p:a": _evidence_run("ev:p:a", run_id=TRACE.run_id, trace=TRACE),
            "ev:p:b": _evidence_run("ev:p:b", run_id=TRACE.run_id, trace=TRACE),
        }
        package = _make_engine().decide(
            snapshot=snapshot,
            proposals=proposals,
            evidence_registry=registry,
            reports=(),
            now=CLOCK,
        )
        assert package.outcome is DecisionOutcome.NO_TRADE
        forged = self._forge_consistent_selection(package, "p:a")
        result = DecisionPackageVerifier().verify(
            forged,
            proposals=proposals,
            evidence_registry=registry,
            reports=(),
            snapshot=snapshot,
            now=CLOCK,
        )
        assert not result.passed
        assert any(
            name == "authoritative_debate_blocker_rederivation" and status == "FAIL"
            for name, status, _ in result.checks
        )

    def test_debate_blocker_replay_deterministic(self) -> None:
        """valid x3 VERIFIED identical; T15 x3 and T16 x3 REJECTED identical."""
        valid_pkg, v_proposals, v_registry, v_reports = self._unresolved_package()
        verifier = DecisionPackageVerifier()
        honest_results = [
            json.dumps(
                verifier.verify(
                    valid_pkg,
                    proposals=v_proposals,
                    evidence_registry=v_registry,
                    reports=v_reports,
                    now=CLOCK,
                ).to_dict(),
                sort_keys=True,
            )
            for _ in range(3)
        ]
        assert len(set(honest_results)) == 1 and '"VERIFIED"' in honest_results[0]

        t15 = self._forge_consistent_selection(valid_pkg, "p:l")
        t15_results = [
            json.dumps(
                verifier.verify(
                    t15,
                    proposals=v_proposals,
                    evidence_registry=v_registry,
                    reports=v_reports,
                    now=CLOCK,
                ).to_dict(),
                sort_keys=True,
            )
            for _ in range(3)
        ]
        assert len(set(t15_results)) == 1 and '"REJECTED"' in t15_results[0]

        insufficient_pkg, i_proposals, i_registry, i_reports = self._insufficient_package()
        t16 = self._forge_consistent_selection(insufficient_pkg, "p:eth")
        t16_results = [
            json.dumps(
                verifier.verify(
                    t16,
                    proposals=i_proposals,
                    evidence_registry=i_registry,
                    reports=i_reports,
                    now=CLOCK,
                ).to_dict(),
                sort_keys=True,
            )
            for _ in range(3)
        ]
        assert len(set(t16_results)) == 1 and '"REJECTED"' in t16_results[0]


# ---------------------------------------------------------------------------
# MA-4W/X — temporal authority + execution boundary
# ---------------------------------------------------------------------------


class TestBoundaryAndTemporal:
    def test_decision_path_has_no_wall_clock_calls(self) -> None:
        import ast
        from pathlib import Path

        # Precise check: no datetime.now/utcnow/date.today/time.time calls.
        banned = {"now", "utcnow", "today", "time"}
        for path in (
            Path("src/trading_bot/multi_agent/decision.py"),
            Path("src/trading_bot/multi_agent/contracts/decision.py"),
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in banned
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in {"datetime", "date", "time"}
                ):
                    pytest.fail(f"wall-clock call in {path}: {node.func.attr}")

    def test_package_carries_no_execution_fields(self) -> None:
        proposals, registry, reports = _three_candidates()
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=reports,
            now=CLOCK,
        )
        payload = json.dumps(package.to_dict())
        for banned in ("position_size", "leverage", "broker", "order_id", "credential", "api_key"):
            assert banned not in payload

    def test_run_mismatch_fail_closed(self) -> None:
        p = _proposal("p:foreign")
        with pytest.raises(DecisionError):
            DecisionEngine(run_id="different-run").decide(
                snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
                proposals={"p:foreign": p},
                evidence_registry={
                    ref: _evidence(ref, "strategy-expert-momentum") for ref in p.evidence_refs
                },
                now=CLOCK,
            )

    def test_naive_clock_rejected(self) -> None:
        p = _proposal("p:naive")
        with pytest.raises(DecisionError):
            _make_engine().decide(
                snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
                proposals={"p:naive": p},
                evidence_registry={},
                now=datetime(2026, 1, 10, 12, 0),  # no tzinfo
            )
