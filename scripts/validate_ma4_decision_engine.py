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

CP-MA-004.1 additions (cross-run authority / ADR-MA-0006):
 13. foreign-run DebateReport rejected (and its revisions with it)
 14. foreign-run evidence with forged current trace_id rejected
 15. sibling cross-run contamination rejected (board proposals, assessments)
 16. verifier rejects cross-run tampered evidence/reports/proposals

CP-MA-004.2 additions (selected evidence authority binding):
 17. package-side evidence strip/swap tamper rejected; exact terminal
     proposal binding independently reconstructed (never package-trusted)
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace as dataclasses_replace
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
from trading_bot.multi_agent.decision import (
    DECISION_ENGINE_ID,
    DECISION_VERIFIER_ID,
    DecisionError,
)
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


# ---------------------------------------------------------------------------
# CP-MA-004.1 — cross-run authority (ADR-MA-0006)
# ---------------------------------------------------------------------------

FOREIGN_RUN = "foreign-run"


def check_foreign_debate_report_rejected() -> None:
    """DEF-MA4-001: a foreign-run DebateReport must fail closed (and its
    revisions with it); the identical current-run report must still select."""
    sol = _proposal("p:sol", confidence=0.91)
    report = _report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))
    control = _decide([sol], reports=[report])
    try:
        _decide([sol], reports=[report.model_copy(update={"run_id": FOREIGN_RUN})])
        ok, detail = False, "foreign-run report accepted"
    except DecisionError as exc:
        ok = True
        detail = str(exc)
    check(
        "foreign_debate_report_rejected",
        ok and control.outcome is DecisionOutcome.SELECTED,
        detail,
    )


def check_foreign_evidence_forged_trace_rejected() -> None:
    """DEF-MA4-002: run authority is first-class — a foreign-run evidence
    artifact with a forged current-run trace_id must never become material."""
    sol = _proposal("p:sol", confidence=0.91)
    engine = DecisionEngine(run_id=TRACE.run_id)
    registry = _registry_for([sol])

    # Case B: foreign run + forged current trace (the original defect vector).
    forged = registry["ev:p:sol"].model_copy(
        update={"run_id": FOREIGN_RUN, "trace": TRACE}
    )
    package = engine.decide(
        snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
        proposals={"p:sol": sol},
        evidence_registry={"ev:p:sol": forged},
        now=CLOCK,
    )
    cand = next(c for c in package.candidate_set if c.final_proposal_id == "p:sol")
    case_b = cand.eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE and (
        package.outcome is DecisionOutcome.NO_TRADE
    )

    # Case C: foreign run + foreign trace (plain authority violation).
    foreign = registry["ev:p:sol"].model_copy(
        update={"run_id": FOREIGN_RUN, "trace": TRACE.model_copy(update={"run_id": FOREIGN_RUN})}
    )
    package_c = engine.decide(
        snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
        proposals={"p:sol": sol},
        evidence_registry={"ev:p:sol": foreign},
        now=CLOCK,
    )
    cand_c = next(c for c in package_c.candidate_set if c.final_proposal_id == "p:sol")
    case_c = cand_c.eligibility is DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE
    check(
        "foreign_evidence_forged_trace_rejected",
        case_b and case_c,
        f"forged={cand.eligibility.value} plain={cand_c.eligibility.value}",
    )


def check_sibling_cross_run_contamination() -> None:
    """Sibling artifacts: board-path proposals and AssetAssessments carry run
    authority too — both must fail closed on a foreign run."""
    from trading_bot.multi_agent.opportunity import Opportunity

    sol = _proposal("p:sol", confidence=0.91)
    engine = DecisionEngine(run_id=TRACE.run_id)
    registry = _registry_for([sol])

    ok = True
    detail_parts: list[str] = []
    # Sibling 1: foreign-run proposal via the OpportunityBoard path.
    try:
        engine.decide(
            snapshot=OpportunitySnapshot(
                opportunities=(
                    Opportunity(
                        proposal=sol.model_copy(update={"run_id": FOREIGN_RUN}),
                        evidence_refs=("ev:p:sol",),
                        source_agent_id="s",
                        source_agent_version="1",
                    ),
                ),
                conflicts=(),
            ),
            proposals={"p:sol": sol},
            evidence_registry=registry,
            now=CLOCK,
        )
        ok = False
        detail_parts.append("board proposal accepted")
    except DecisionError as exc:
        detail_parts.append(f"board: {exc}")

    # Sibling 2: foreign-run AssetAssessment feeding MetaRanker.
    assessment = AssetAssessment(
        asset="SOL",
        timestamp=1_768_046_400_000,
        regime="TREND_UP",
        trend_quality=0.9,
        volatility_quality=0.8,
        liquidity_quality=0.9,
        relative_strength=0.85,
        market_quality=0.8,
        confidence=0.9,
        evidence=(),
        trace=TRACE,
        agent_id="asset-expert-sol",
        agent_version="1.0.0",
    )
    try:
        engine.decide(
            snapshot=OpportunitySnapshot(opportunities=(), conflicts=()),
            proposals={"p:sol": sol},
            evidence_registry=registry,
            assessments={"SOL": dataclasses_replace(assessment, trace=TRACE.model_copy(update={"run_id": FOREIGN_RUN}))},
            now=CLOCK,
        )
        ok = False
        detail_parts.append("assessment accepted")
    except DecisionError as exc:
        detail_parts.append(f"assessment: {exc}")
    check("sibling_cross_run_contamination_rejected", ok, " | ".join(detail_parts))


def check_verifier_cross_run_rejection() -> None:
    """Verifier independence under cross-run tampering: poisoned evidence,
    reports and proposals must each be REJECTED; the clean package verifies."""
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    report = _report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))
    package = _decide([sol, btc], reports=[report])
    proposals = {p.proposal_id: p for p in (sol, btc)}
    registry = _registry_for([sol, btc])
    now = CLOCK + timedelta(minutes=1)

    control = DecisionPackageVerifier().verify(
        package, proposals=proposals, evidence_registry=registry, reports=[report], now=now
    )

    poisoned_registry = dict(registry)
    poisoned_registry["ev:p:sol"] = registry["ev:p:sol"].model_copy(update={"run_id": FOREIGN_RUN})
    via_evidence = DecisionPackageVerifier().verify(
        package, proposals=proposals, evidence_registry=poisoned_registry, reports=[report], now=now
    )

    via_report = DecisionPackageVerifier().verify(
        package,
        proposals=proposals,
        evidence_registry=registry,
        reports=[report.model_copy(update={"run_id": FOREIGN_RUN})],
        now=now,
    )

    poisoned_proposals = dict(proposals)
    poisoned_proposals["p:sol"] = sol.model_copy(update={"run_id": FOREIGN_RUN})
    via_proposal = DecisionPackageVerifier().verify(
        package, proposals=poisoned_proposals, evidence_registry=registry, reports=[report], now=now
    )
    check(
        "verifier_cross_run_rejection",
        control.passed
        and not via_evidence.passed
        and not via_report.passed
        and not via_proposal.passed,
        f"control={control.verdict.value} evidence={via_evidence.verdict.value} "
        f"report={via_report.verdict.value} proposal={via_proposal.verdict.value}",
    )


def check_selected_evidence_authority_binding() -> None:
    """CP-MA-004.2 (CERT-MA4-001-RETRY-001): the verifier must independently
    reconstruct the selected candidate's evidence authority from the canonical
    terminal TradeProposal — never trusting the package's own lists. Full
    stripping (the certification defect vector), partial stripping and
    swapping (with registered, current-run, trace-consistent evidence) must
    all REJECT; the clean package must still VERIFY."""
    sol = _proposal("p:sol", confidence=0.91)
    btc = _proposal("p:btc", asset="BTC", strategy="breakout", confidence=0.83)
    report = _report(("p:sol",), outcome=DebateOutcome.SUPPORTED, critiques=(_support("p:sol"),))
    package = _decide([sol, btc], reports=[report])
    proposals = {p.proposal_id: p for p in (sol, btc)}
    registry = _registry_for([sol, btc])
    verifier = DecisionPackageVerifier()
    selected_id = package.selected_candidate_id
    assert selected_id is not None

    def verdict(pkg: DecisionPackage, reg: Mapping[str, AgentEvidence]) -> str:
        return verifier.verify(
            pkg, proposals=proposals, evidence_registry=reg, reports=[report], now=CLOCK
        ).verdict.value

    clean = verdict(package, registry)

    def retarget(package: DecisionPackage, **update: object) -> DecisionPackage:
        return package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update=update)
                    if c.final_proposal_id == selected_id
                    else c
                    for c in package.candidate_set
                )
            }
        )

    stripped = verdict(retarget(package, supporting_evidence_refs=()), registry)

    # Partial stripping needs a terminal proposal committing TWO evidence
    # items: strip one of two and the set no longer matches the authority.
    multi = _proposal("p:multi", confidence=0.9).model_copy(
        update={"evidence_refs": ("ev:multi-a", "ev:multi-b")}
    )
    multi_registry = {
        **_registry_for([multi]),
        "ev:multi-a": _evidence("ev:multi-a", "strategy-expert-momentum"),
        "ev:multi-b": _evidence("ev:multi-b", "strategy-expert-momentum"),
    }
    multi_package = _decide([multi], reports=[])
    multi_selected = multi_package.selected_candidate_id
    assert multi_selected is not None
    multi_partial = (
        multi_package.model_copy(
            update={
                "candidate_set": tuple(
                    c.model_copy(update={"supporting_evidence_refs": ("ev:multi-a",)})
                    if c.final_proposal_id == multi_selected
                    else c
                    for c in multi_package.candidate_set
                )
            }
        )
    )
    partial = verifier.verify(
        multi_partial,
        proposals={"p:multi": multi},
        evidence_registry=multi_registry,
        reports=[],
        now=CLOCK,
    ).verdict.value
    multi_clean = verifier.verify(
        multi_package,
        proposals={"p:multi": multi},
        evidence_registry=multi_registry,
        reports=[],
        now=CLOCK,
    ).verdict.value

    swap_registry = {**registry, "ev:uncommitted": _evidence("ev:uncommitted", "strategy-expert-breakout")}
    swapped = verdict(
        retarget(package, supporting_evidence_refs=("ev:uncommitted",)), swap_registry
    )
    added = verdict(
        retarget(package, supporting_evidence_refs=("ev:p:sol", "ev:uncommitted")), swap_registry
    )
    ok = (
        clean == "VERIFIED"
        and multi_clean == "VERIFIED"
        and stripped == "REJECTED"
        and partial == "REJECTED"
        and swapped == "REJECTED"
        and added == "REJECTED"
    )
    check(
        "selected_evidence_authority_binding",
        ok,
        f"clean={clean} multi_clean={multi_clean} stripped={stripped} "
        f"partial={partial} swapped={swapped} added={added}",
    )


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
    check_foreign_debate_report_rejected()
    check_foreign_evidence_forged_trace_rejected()
    check_sibling_cross_run_contamination()
    check_verifier_cross_run_rejection()
    check_selected_evidence_authority_binding()
    check_execution_capability_zero()
    check_dynamic_boundary()

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print(f"\nMA-4 validator: {passed}/{total} PASS, {failed} FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
