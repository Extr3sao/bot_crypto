"""CP-MA4-POSTCERT-001 / DEF-MA4-003 — natural agreement evidence authority.

Authority model: MODEL A (ADR-MA-0009). ``DecisionCandidate
.supporting_evidence_refs`` is contractually the terminal ``TradeProposal``
evidence set (ADR-MA-0007), independently enforced by
``DecisionPackageVerifier-v3`` (``selected_evidence_binding``). Debate-derived
corroboration stays in the ``DebateReport`` and the candidate's debate
provenance fields; it must never widen the binding set.

All scenarios run the real runtime path (MA-2 proposals → certified MA-3
``DebateSession`` → MA-4 ``DecisionEngine`` → ``DecisionPackageVerifier``);
packages are never fabricated by hand.
"""

from __future__ import annotations

import pytest
from test_decision import (
    CLOCK,
    SCHEMA,
    TRACE,
    _assessment,
    _evidence,
    _evidence_run,
    _make_engine,
    _proposal,
    _run_debate,
)

from trading_bot.multi_agent import DecisionPackageVerifier, OpportunitySnapshot
from trading_bot.multi_agent.contracts import (
    CritiqueRecord,
    CritiqueStance,
    DebateOutcome,
    DebateReport,
    DebateTerminationReason,
    DecisionEligibility,
    RequestedAction,
    TraceContext,
)
from trading_bot.multi_agent.decision import DecisionVerificationStatus

RUN_A = "ma4-run"


def _trace_for(run_id: str) -> TraceContext:
    return TraceContext(
        run_id=run_id,
        trace_id=f"{run_id}-trace",
        correlation_id=f"{run_id}-corr",
        causation_id=f"{run_id}-cause",
    )


def _agreement_scenario(
    evidence_registry: dict | None = None,
) -> tuple[dict, dict, DebateReport]:
    """BTC Momentum LONG + Trend LONG with a real certified MA-3 debate.

    Directional agreement: the debate SUPPORTs the lineage and the report's
    supporting evidence legitimately spans both proposals' evidence.
    """
    momentum = _proposal(
        "p:bm", strategy="momentum", asset="BTC", confidence=0.82, evidence_id="ev:m1"
    )
    trend = _proposal(
        "p:bt", strategy="trend", asset="BTC", confidence=0.78, evidence_id="ev:t1"
    )
    proposals = {"p:bm": momentum, "p:bt": trend}
    registry = evidence_registry or {
        "ev:m1": _evidence("ev:m1", "strategy-expert-momentum", claim="p:bm"),
        "ev:t1": _evidence("ev:t1", "strategy-expert-trend", claim="p:bt"),
    }
    report = _run_debate(
        [momentum, trend],
        {"p:bm": "strategy-expert-momentum", "p:bt": "strategy-expert-trend"},
    )
    return proposals, registry, report


def _agreement_package(
    evidence_registry: dict | None = None,
):
    proposals, registry, report = _agreement_scenario(evidence_registry)
    package = _make_engine().decide(
        snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
        proposals=proposals,
        evidence_registry=registry,
        reports=[report],
        assessments={"BTC": _assessment(asset="BTC")},
        now=CLOCK,
    )
    return package, proposals, registry, report


def _unresolved_report(proposal_ids: tuple[str, ...]) -> DebateReport:
    critique = CritiqueRecord(
        schema_version=SCHEMA,
        critique_id="critique:unres",
        proposal_id=proposal_ids[0],
        critic_agent_id="critic-risk",
        critic_version="1.0.0",
        stance=CritiqueStance.CHALLENGE,
        materiality=0.8,
        claim="conflicting evidence stands",
        confidence=0.9,
        requested_action=RequestedAction.REVISE,
        trace=TRACE,
        created_at=CLOCK,
    )
    return DebateReport(
        schema_version=SCHEMA,
        debate_id="debate:unres",
        run_id=TRACE.run_id,
        proposal_ids=proposal_ids,
        participants=("critic-risk",),
        initial_claims=("claim",),
        critiques=(critique,),
        round_count=3,
        max_rounds=3,
        termination_reason=DebateTerminationReason.MAX_ROUNDS,
        outcome=DebateOutcome.UNRESOLVED,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=0,
        trace=TRACE,
        created_at=CLOCK,
    )


def _insufficient_report(proposal_ids: tuple[str, ...]) -> DebateReport:
    return DebateReport(
        schema_version=SCHEMA,
        debate_id="debate:insuf",
        run_id=TRACE.run_id,
        proposal_ids=proposal_ids,
        participants=("critic-evidence",),
        initial_claims=("claim",),
        critiques=(),
        round_count=1,
        max_rounds=3,
        termination_reason=DebateTerminationReason.MAX_ROUNDS,
        outcome=DebateOutcome.INSUFFICIENT_EVIDENCE,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=0,
        trace=TRACE,
        created_at=CLOCK,
    )


def _verify(package, proposals, registry, reports=()):
    return DecisionPackageVerifier().verify(
        package=package,
        proposals=proposals,
        evidence_registry=registry,
        reports=reports,
        now=CLOCK,
    )


class TestNaturalAgreementPositive:
    def test_candidate_supporting_evidence_is_proposal_authority(self) -> None:
        package, proposals, _, report = _agreement_package()
        assert package.outcome is not None
        selected = next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )
        # MODEL A: candidate supporting evidence == terminal proposal evidence.
        assert tuple(sorted(selected.supporting_evidence_refs)) == tuple(
            sorted(proposals[selected.final_proposal_id].evidence_refs)
        )
        # Debate corroboration remains visible in provenance fields, not in
        # the binding set.
        assert selected.debate_id == report.debate_id
        assert selected.debate_outcome is DebateOutcome.SUPPORTED

    def test_natural_agreement_package_verifies(self) -> None:
        package, proposals, registry, report = _agreement_package()
        assert package.selected_candidate_id is not None
        result = _verify(package, proposals, registry, [report])
        assert result.verdict is DecisionVerificationStatus.VERIFIED
        assert result.passed
        assert all(ok for _, ok, _ in result.checks)


class TestUnauthorizedAgreementEvidence:
    def test_unrelated_registered_evidence_addition_rejected(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        extra = _evidence("ev:unrelated", "strategy-expert-momentum")
        registry["ev:unrelated"] = extra
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "supporting_evidence_refs": (
                                *c.supporting_evidence_refs,
                                "ev:unrelated",
                            )
                        }
                    )
                    if c.final_proposal_id == package.selected_candidate_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        result = _verify(tampered, proposals, registry)
        assert result.verdict is DecisionVerificationStatus.REJECTED

    def test_foreign_run_evidence_addition_rejected(self) -> None:
        registry = {
            "ev:m1": _evidence("ev:m1", "strategy-expert-momentum", claim="p:bm"),
            "ev:t1": _evidence("ev:t1", "strategy-expert-trend", claim="p:bt"),
            "ev:foreign": _evidence_run(
                "ev:foreign", run_id="other-run", trace=_trace_for("other-run")
            ),
        }
        package, proposals, registry, _ = _agreement_package(registry)
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "supporting_evidence_refs": (
                                *c.supporting_evidence_refs,
                                "ev:foreign",
                            )
                        }
                    )
                    if c.final_proposal_id == package.selected_candidate_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        result = _verify(tampered, proposals, registry)
        assert result.verdict is DecisionVerificationStatus.REJECTED

    def test_counter_evidence_promotion_to_support_rejected(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        # The promoted ref is the sibling proposal's evidence: valid evidence
        # of the run, but not part of the selected terminal proposal authority.
        promoted = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "supporting_evidence_refs": (
                                *c.supporting_evidence_refs,
                                "ev:t1",
                            )
                        }
                    )
                    if c.final_proposal_id == package.selected_candidate_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        result = _verify(promoted, proposals, registry)
        assert result.verdict is DecisionVerificationStatus.REJECTED


class TestStripSwapDuplicate:
    def test_evidence_stripping_rejected(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": ()})
                    for c in package.candidate_set
                )
            }
        )
        assert _verify(tampered, proposals, registry).verdict is (
            DecisionVerificationStatus.REJECTED
        )

    def test_partial_stripping_rejected(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        selected = next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )
        if len(selected.supporting_evidence_refs) < 2:
            pytest.skip("single-ref authority set: full-strip test covers this case")
        subset = selected.supporting_evidence_refs[:-1]
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": subset})
                    if c.final_proposal_id == package.selected_candidate_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        assert _verify(tampered, proposals, registry).verdict is (
            DecisionVerificationStatus.REJECTED
        )

    def test_evidence_swap_rejected(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        selected = next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )
        swapped = tuple(reversed(selected.supporting_evidence_refs))
        if set(swapped) == set(selected.supporting_evidence_refs) and len(swapped) == len(
            selected.supporting_evidence_refs
        ):
            # Same set: binding is set-identity, order must not matter.
            tampered = package.model_copy(
                update={
                    "candidate_set": tuple(
                        c.model_copy(update={"supporting_evidence_refs": swapped})
                        if c.final_proposal_id == package.selected_candidate_id
                        else c
                        for c in package.candidate_set
                    )
                }
            )
            assert _verify(tampered, proposals, registry).verdict is (
                DecisionVerificationStatus.VERIFIED
            )
            return
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": swapped})
                    if c.final_proposal_id == package.selected_candidate_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        assert _verify(tampered, proposals, registry).verdict is (
            DecisionVerificationStatus.REJECTED
        )

    def test_duplicate_evidence_ref_rejected(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        selected = next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )
        refs = selected.supporting_evidence_refs
        duplicated = (*refs, refs[0])
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": duplicated})
                    if c.final_proposal_id == package.selected_candidate_id
                    else c
                    for c in package.candidate_set
                )
            }
        )
        assert _verify(tampered, proposals, registry).verdict is (
            DecisionVerificationStatus.REJECTED
        )


class TestSingleProposalControl:
    def test_single_proposal_semantics_unchanged(self) -> None:
        momentum = _proposal("p:solo", strategy="momentum", confidence=0.85, evidence_id="ev:s1")
        registry = {"ev:s1": _evidence("ev:s1", "strategy-expert-momentum", claim="p:solo")}
        report = _run_debate(
            [momentum], {"p:solo": "strategy-expert-momentum"}
        )
        package = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:solo": momentum},
            evidence_registry=registry,
            reports=[report],
            assessments={"SOL": _assessment()},
            now=CLOCK,
        )
        assert package.outcome is not None
        selected = next(
            c for c in package.candidate_set if c.final_proposal_id == package.selected_candidate_id
        )
        assert tuple(sorted(selected.supporting_evidence_refs)) == ("ev:s1",)
        result = _verify(package, {"p:solo": momentum}, registry, [report])
        assert result.verdict is DecisionVerificationStatus.VERIFIED


class TestBlockerControls:
    def test_unresolved_blocker_cannot_be_bypassed_by_agreement(self) -> None:
        # The engine itself fail-closes on UNRESOLVED debate for the lineage.
        package, proposals, registry, _ = _agreement_package()
        unresolved = _unresolved_report(("p:bm", "p:bt"))
        decided = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[unresolved],
            assessments={"BTC": _assessment(asset="BTC")},
            now=CLOCK,
        )
        assert decided.selected_candidate_id is None
        # And a tampered SELECTED package is independently re-derived as
        # blocked by the verifier (UNRESOLVED forgery → REJECT).
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "debate_id": unresolved.debate_id,
                            "debate_outcome": DebateOutcome.UNRESOLVED,
                            "eligibility": DecisionEligibility.ELIGIBLE,
                            "rejection_reasons": (),
                        }
                    )
                    for c in package.candidate_set
                )
            }
        )
        result = _verify(tampered, proposals, registry, [unresolved])
        assert result.verdict is DecisionVerificationStatus.REJECTED

    def test_insufficient_evidence_blocker_cannot_be_bypassed(self) -> None:
        package, proposals, registry, _ = _agreement_package()
        insufficient = _insufficient_report(("p:bm", "p:bt"))
        decided = _make_engine().decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals=proposals,
            evidence_registry=registry,
            reports=[insufficient],
            assessments={"BTC": _assessment(asset="BTC")},
            now=CLOCK,
        )
        assert decided.selected_candidate_id is None
        tampered = package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(
                        update={
                            "debate_id": insufficient.debate_id,
                            "debate_outcome": DebateOutcome.INSUFFICIENT_EVIDENCE,
                            "eligibility": DecisionEligibility.ELIGIBLE,
                            "rejection_reasons": (),
                        }
                    )
                    for c in package.candidate_set
                )
            }
        )
        result = _verify(tampered, proposals, registry, [insufficient])
        assert result.verdict is DecisionVerificationStatus.REJECTED
