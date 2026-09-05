"""Independent MA-4 Decision Engine validator (CP-MA-004).

Builder results do not self-certify: this script re-derives every claim from
the committed contracts and fixtures. Each check prints PASS/FAIL; the script
exits non-zero if any check fails.

Checks (minimum per CP-MA-004):
  1. best admissible candidate selected
  2. higher raw score cannot bypass eligibility
  3. INSUFFICIENT_EVIDENCE blocks selection
  4. UNRESOLVED material conflict blocks selection
  5. revision can alter winner
  6. NO_TRADE works (empty board)
  7. rejected alternatives retained
  8. same evidence not double-counted
  9. ordering does not alter result
 10. decision replay deterministic (x3, canonical JSON)
 11. decision package independently verifies (builder != verifier)
 12. execution capability = 0 (structural + payload scan)
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from trading_bot.multi_agent import (
    DecisionEngine,
    DecisionPackageVerifier,
    DecisionReason,
    OpportunitySnapshot,
)
from trading_bot.multi_agent.contracts import (
    AgentEvidence,
    CritiqueRecord,
    CritiqueStance,
    DebateOutcome,
    DebateReport,
    DebateTerminationReason,
    DecisionEligibility,
    DecisionOutcome,
    DecisionPackage,
    ProposalRevision,
    RequestedAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.decision import DECISION_ENGINE_ID, DECISION_VERIFIER_ID
from trading_bot.multi_agent.specialists import AssetAssessment

SCHEMA = "ma-3-v1"
CLOCK = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
TRACE = TraceContext(
    run_id="ma4-validate",
    trace_id="ma4-trace",
    correlation_id="ma4-corr",
    causation_id="ma4-cause",
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Fixture helpers (independent of the unit-test suite)
# ---------------------------------------------------------------------------


def _evidence(evidence_id: str, producer: str) -> AgentEvidence:
    return AgentEvidence(
        schema_version=SCHEMA,
        evidence_id=evidence_id,
        run_id=TRACE.run_id,
        producer_agent_id=producer,
        evidence_type="strategy_signal",
        source_ref=f"ctx:{evidence_id}",
        claim_refs=("claim",),
        observed_at=CLOCK,
        available_at=CLOCK,
        content_hash="a" * 64,
        metadata=(),
        trace=TRACE,
    )


def _proposal(
    proposal_id: str,
    *,
    asset: str = "SOL",
    strategy: str = "momentum",
    direction: TradeDirection = TradeDirection.LONG,
    confidence: float = 0.8,
) -> TradeProposal:
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
        evidence_refs=(f"ev:{proposal_id}",),
        invalidation="structural stop",
        confidence=confidence,
        data_time=CLOCK,
        created_at=CLOCK,
        expires_at=CLOCK + timedelta(minutes=15),
        trace=TRACE,
    )


def _registry_for(proposals: list[TradeProposal]) -> dict[str, AgentEvidence]:
    producers = {"momentum": "strategy-expert-momentum", "breakout": "strategy-expert-breakout", "trend": "strategy-expert-trend", "mean_reversion": "strategy-expert-mean_reversion"}
    return {
        ref: _evidence(ref, producers.get(p.strategy, "strategy-expert-momentum"))
        for p in proposals
        for ref in p.evidence_refs
    }


def _report(
    proposal_ids: tuple[str, ...],
    *,
    outcome: DebateOutcome,
    critiques: tuple[CritiqueRecord, ...] = (),
    revisions: tuple[ProposalRevision, ...] = (),
    debate_id: str = "debate:v",
) -> DebateReport:
    counter = tuple(
        sorted({ref for c in critiques for ref in c.counter_evidence_refs})
    )
    return DebateReport(
        schema_version=SCHEMA,
        debate_id=debate_id,
        run_id=TRACE.run_id,
        proposal_ids=proposal_ids,
        participants=("critic-evidence", "critic-regime", "critic-counter-signal"),
        initial_claims=tuple(f"claim-{pid}" for pid in proposal_ids),
        critiques=critiques,
        counter_evidence=counter,
        unique_supporting_evidence_count=0,
        unique_counter_evidence_count=len(set(counter)),
        revisions=revisions,
        round_count=1,
        max_rounds=3,
        termination_reason=DebateTerminationReason.RESOLVED
        if outcome is not DebateOutcome.UNRESOLVED
        else DebateTerminationReason.UNRESOLVED,
        outcome=outcome,
        trace=TRACE,
        created_at=CLOCK,
    )


def _support(pid: str, critic: str = "critic-evidence") -> CritiqueRecord:
    return CritiqueRecord(
        schema_version=SCHEMA,
        critique_id=f"critique:sup:{pid}",
        proposal_id=pid,
        critic_agent_id=critic,
        critic_version="1.0.0",
        stance=CritiqueStance.SUPPORT,
        materiality=0.0,
        claim="evidence checks out",
        confidence=0.9,
        requested_action=RequestedAction.NONE,
        trace=TRACE,
        created_at=CLOCK,
    )


def _challenge(
    pid: str,
    *,
    materiality: float,
    critic: str = "critic-regime",
    critique_id: str | None = None,
) -> CritiqueRecord:
    return CritiqueRecord(
        schema_version=SCHEMA,
        critique_id=critique_id or f"critique:chg:{pid}",
        proposal_id=pid,
        critic_agent_id=critic,
        critic_version="1.0.0",
        stance=CritiqueStance.CHALLENGE,
        materiality=materiality,
        claim="counter-evidence stands",
        counter_evidence_refs=(f"ev:counter:{pid}",),
        confidence=0.8,
        requested_action=RequestedAction.REVISE,
        trace=TRACE,
        created_at=CLOCK,
    )


def _decide(
    proposals: list[TradeProposal],
    reports: Sequence[DebateReport] = (),
    assessments: Mapping[str, AssetAssessment] | None = None,
) -> DecisionPackage:
    engine = DecisionEngine(run_id=TRACE.run_id)
    return engine.decide(
        snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
        proposals={p.proposal_id: p for p in proposals},
        evidence_registry=_registry_for(proposals),
        reports=list(reports),
        assessments=assessments or {},
        now=CLOCK,
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_best_admissible_selected() -> None:
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    eth = _proposal("p:eth", asset="ETH", strategy="trend", confidence=0.79)
    package = _decide(
        [sol, btc, eth],
        reports=[_report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))],
    )
    check(
        "best_admissible_candidate_selected",
        package.outcome is DecisionOutcome.SELECTED
        and package.selected_candidate_id == "p:sol",
        f"selected={package.selected_candidate_id}",
    )


def check_higher_raw_score_cannot_bypass() -> None:
    stale_high = _proposal("p:high", confidence=0.99).model_copy(
        update={
            "created_at": CLOCK - timedelta(hours=30),
            "data_time": CLOCK - timedelta(hours=30),
        }
    )
    fresh_low = _proposal("p:low", confidence=0.7)
    package = _decide([stale_high, fresh_low])
    by_id = {c.final_proposal_id: c for c in package.candidate_set}
    check(
        "higher_raw_score_cannot_bypass_eligibility",
        package.selected_candidate_id == "p:low"
        and by_id["p:high"].eligibility is DecisionEligibility.INELIGIBLE_STALE,
        f"selected={package.selected_candidate_id} high={by_id['p:high'].eligibility.value}",
    )


def check_insufficient_evidence_blocks() -> None:
    p = _proposal("p:ins").model_copy(update={"evidence_refs": ()})
    engine = DecisionEngine(run_id=TRACE.run_id)
    package = engine.decide(
        snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
        proposals={"p:ins": p},
        evidence_registry={},
        reports=[],
        now=CLOCK,
    )
    by_id = {c.final_proposal_id: c for c in package.candidate_set}
    check(
        "insufficient_evidence_blocks_selection",
        package.outcome is DecisionOutcome.NO_TRADE
        and by_id["p:ins"].eligibility is DecisionEligibility.INELIGIBLE_INSUFFICIENT_EVIDENCE,
        f"eligibility={by_id['p:ins'].eligibility.value}",
    )


def check_unresolved_conflict_blocks() -> None:
    long_p = _proposal("p:long", confidence=0.95)
    short_p = _proposal("p:short", strategy="mean_reversion", direction=TradeDirection.SHORT, confidence=0.9)
    report = _report(
        ("p:long", "p:short"),
        outcome=DebateOutcome.UNRESOLVED,
        critiques=(
            _challenge("p:long", materiality=0.4),
            _challenge("p:short", materiality=0.4, critic="critic-counter-signal"),
        ),
        debate_id="debate:conflict",
    )
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.7)
    package = _decide([long_p, short_p, btc], reports=[report])
    by_id = {c.final_proposal_id: c for c in package.candidate_set}
    check(
        "unresolved_material_conflict_blocks_selection",
        package.selected_candidate_id == "p:btc"
        and by_id["p:long"].eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT
        and by_id["p:short"].eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT,
        f"selected={package.selected_candidate_id}",
    )


def check_revision_changes_winner() -> None:
    sol = _proposal("p:sol", confidence=0.9)
    revised = sol.model_copy(update={"proposal_id": "p:sol:r-1", "confidence": 0.55})
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.84)
    revision = ProposalRevision(
        schema_version=SCHEMA,
        original_proposal_id="p:sol",
        revised_proposal_id="p:sol:r-1",
        triggering_critique_ids=("critique:chg:p:sol",),
        revision_reason="material counter-evidence",
        trace=TRACE,
        created_at=CLOCK,
    )
    report = _report(
        ("p:sol",),
        outcome=DebateOutcome.REVISED,
        critiques=(
            _challenge("p:sol", materiality=0.35),
            _support("p:sol:r-1", critic="critic-evidence"),
        ),
        revisions=(revision,),
    )
    package = _decide([sol, revised, btc], reports=[report])
    check(
        "revision_can_alter_winner",
        package.selected_candidate_id == "p:btc",
        f"selected={package.selected_candidate_id}",
    )


def check_no_trade() -> None:
    package = _decide([])
    check(
        "no_trade_first_class",
        package.outcome is DecisionOutcome.NO_TRADE
        and package.selected_candidate_id is None
        and package.decision_reasons == (DecisionReason.NO_VALID_CANDIDATES,),
    )


def check_rejected_alternatives_retained() -> None:
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    package = _decide(
        [sol, btc],
        reports=[_report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))],
    )
    rejected = {a.final_proposal_id: a for a in package.rejected_alternatives}
    check(
        "rejected_alternatives_retained",
        set(rejected) == {"p:btc"}
        and rejected["p:btc"].rejection_reasons == (DecisionReason.LOWER_RANKED_ALTERNATIVE,)
        and len(package.candidate_set) == 2,
    )


def check_no_double_counting() -> None:
    p = _proposal("p:x", confidence=0.8)
    package = _decide([p])
    candidate = package.candidate_set[0]
    meta = candidate.score_breakdown.component("meta_ranker_score")
    check(
        "same_evidence_not_double_counted",
        meta is not None
        and abs(meta - candidate.meta_score) < 1e-9
        and candidate.score_breakdown.component("counter_evidence_materiality") == 0.0
        and abs(candidate.decision_score - meta) < 1e-9,
        f"meta={meta} decision={candidate.decision_score}",
    )


def check_order_independence() -> None:
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    reports = [_report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))]
    forward = _decide([sol, btc], reports=reports)
    backward = _decide([btc, sol], reports=list(reversed(reports)))
    check(
        "ordering_does_not_alter_result",
        forward.to_dict() == backward.to_dict(),
    )


def check_replay_determinism() -> None:
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    reports = [_report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))]
    payloads = [
        json.dumps(_decide([sol, btc], reports=reports).to_dict(), sort_keys=True)
        for _ in range(3)
    ]
    check(
        "decision_replay_deterministic",
        len(set(payloads)) == 1,
    )


def check_independent_verification() -> None:
    sol = _proposal("p:sol", confidence=0.91)
    package = _decide([sol], reports=[_report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))])
    meta = package.verification_metadata
    separation = (
        meta.builder_agent_id == DECISION_ENGINE_ID
        and meta.verifier_agent_id == DECISION_VERIFIER_ID
        and meta.builder_agent_id != meta.verifier_agent_id
    )
    result = DecisionPackageVerifier().verify(
        package,
        proposals={"p:sol": sol},
        evidence_registry=_registry_for([sol]),
        now=CLOCK + timedelta(minutes=1),
    )
    # Tampering must be caught.
    tampered = package.model_copy(update={"outcome": DecisionOutcome.NO_TRADE, "selected_candidate_id": None})
    tamper_result = DecisionPackageVerifier().verify(
        tampered,
        proposals={"p:sol": sol},
        evidence_registry=_registry_for([sol]),
        now=CLOCK,
    )
    check(
        "decision_package_independently_verifies",
        separation and result.passed and not tamper_result.passed,
        f"verifier={result.verdict.value} tampered={tamper_result.verdict.value}",
    )


def check_execution_capability_zero() -> None:
    # Structural: no wall-clock calls in decision source files.
    banned = {"now", "utcnow", "today", "time"}
    wall_clock_hits: list[str] = []
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
                wall_clock_hits.append(f"{path}:{node.lineno}")
    # Structural: no execution imports in decision modules.
    banned_imports = ("paper", "execution", "broker", "risk", "exchange")
    import_hits: list[str] = []
    for path in (
        Path("src/trading_bot/multi_agent/decision.py"),
        Path("src/trading_bot/multi_agent/contracts/decision.py"),
    ):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and any(
                token in stripped for token in banned_imports
            ):
                import_hits.append(f"{path}: {stripped}")
    # Payload: no execution fields in a full package.
    sol = _proposal("p:sol", confidence=0.91)
    package = _decide([sol])
    payload = json.dumps(package.to_dict())
    payload_clean = not any(
        token in payload
        for token in ("position_size", "leverage", "broker", "order_id", "credential", "api_key")
    )
    check(
        "execution_capability_zero",
        not wall_clock_hits and not import_hits and payload_clean,
        f"wall_clock={wall_clock_hits} imports={import_hits}",
    )


# ---------------------------------------------------------------------------
# Dynamic boundary: run a full decision with execution modules blocked
# ---------------------------------------------------------------------------


def check_dynamic_boundary() -> None:
    import builtins

    saved_builtins_import = builtins.__import__
    blocked = ("trading_bot.paper", "trading_bot.execution", "trading_bot.broker", "trading_bot.risk")

    def guard(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> ModuleType:
        for prefix in blocked:
            if name == prefix or name.startswith(prefix + "."):
                raise ImportError(f"blocked during validation: {name}")
        return saved_builtins_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guard
    try:
        sol = _proposal("p:sol", confidence=0.91)
        package = _decide([sol], reports=[_report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))])
        verifier_result = DecisionPackageVerifier().verify(
            package,
            proposals={"p:sol": sol},
            evidence_registry=_registry_for([sol]),
            now=CLOCK + timedelta(minutes=1),
        )
        ok = package.outcome is DecisionOutcome.SELECTED and verifier_result.passed
        detail = f"outcome={package.outcome.value} verifier={verifier_result.verdict.value}"
    except ImportError as exc:
        ok = False
        detail = f"import blocked unexpectedly: {exc}"
    finally:
        builtins.__import__ = saved_builtins_import
    check("dynamic_execution_boundary", ok, detail)


def main() -> int:
    check_best_admissible_selected()
    check_higher_raw_score_cannot_bypass()
    check_insufficient_evidence_blocks()
    check_unresolved_conflict_blocks()
    check_revision_changes_winner()
    check_no_trade()
    check_rejected_alternatives_retained()
    check_no_double_counting()
    check_order_independence()
    check_replay_determinism()
    check_independent_verification()
    check_execution_capability_zero()
    check_dynamic_boundary()

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print(f"\nMA-4 validator: {passed}/{total} PASS, {failed} FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
