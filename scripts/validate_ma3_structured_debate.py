#!/usr/bin/env python3
"""Independent MA-3 structured debate validator.

Verifies:
- conflict creates debate (deterministic DebateRouter)
- challenge exists (structured, bus-carried CritiqueRecords)
- counter-evidence survives (adversarial critic output preserved)
- evidence requests are traceable (request/response on the certified bus)
- proposal revision is immutable (canonical lineage, original preserved)
- same evidence is not double-counted (canonical evidence deduplication)
- loop terminates (NO_NEW_EVIDENCE anti-loop before/within max rounds)
- unresolved remains unresolved (first-class debate state, not failure)
- deterministic replay (identical inputs -> identical DebateReport)
- execution capability = 0 (critics deny risk/broker/live surface)
- single temporal authority (no wall-clock in debate decision logic)

Builder results do not self-certify MA-3. Must be runnable from a clean
checkout with no trading side-effects.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure src is on the path for clean-checkout execution
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from trading_bot.multi_agent import (  # noqa: E402
    Blackboard,
    CapabilityRegistry,
    OpportunityBoard,
    OpportunitySnapshot,
    TraceContext,
    register_debate_agents,
    register_swarm_agents,
)
from trading_bot.multi_agent.bus import AgentBus  # noqa: E402
from trading_bot.multi_agent.contracts import (  # noqa: E402
    AgentCapability,
    AgentEvidence,
    AgentMessageType,
    CritiqueStance,
    DebateOutcome,
    DebateRouteReason,
    DebateTerminationReason,
    ForbiddenAction,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.debate import (  # noqa: E402
    MAX_DEBATE_ROUNDS,
    DebateLedger,
    DebatePosition,
    DebateRouter,
    DebateSession,
)
from trading_bot.multi_agent.registry.agent_registry import (  # noqa: E402
    AgentRegistry,
)

REPORT_PATH = _root / "reports" / "multi_agent" / "ma3" / "VALIDATION_REPORT.json"

# Fixed validation clock — never uses datetime.now for decision logic
VALIDATION_CLOCK = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

PASS = "PASS"
FAIL = "FAIL"
results: dict[str, str] = {}
details: dict[str, Any] = {}

SCHEMA = "ma-3-v1"

TRACE = TraceContext(
    run_id="ma3-validator",
    trace_id="ma3-validator-trace",
    correlation_id="ma3-validator-corr",
    causation_id="ma3-validator-cause",
)


def _sha256_hex(payload: str = "") -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


import hashlib  # noqa: E402


def _evidence(evidence_id: str, producer: str, claim: str) -> AgentEvidence:
    return AgentEvidence(
        schema_version=SCHEMA,
        evidence_id=evidence_id,
        run_id=TRACE.run_id,
        producer_agent_id=producer,
        evidence_type="strategy_signal",
        source_ref=f"ctx:{evidence_id}",
        claim_refs=(claim,),
        observed_at=VALIDATION_CLOCK,
        available_at=VALIDATION_CLOCK,
        content_hash=_sha256_hex(evidence_id),
        metadata=(),
        trace=TRACE,
    )


def _proposal(
    proposal_id: str,
    *,
    direction: TradeDirection,
    strategy: str,
    evidence_id: str,
    confidence: float = 0.8,
) -> TradeProposal:
    return TradeProposal(
        schema_version=SCHEMA,
        proposal_id=proposal_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset="SOL",
        direction=direction,
        strategy=strategy,
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(evidence_id,),
        invalidation="structural stop",
        confidence=confidence,
        data_time=VALIDATION_CLOCK,
        created_at=VALIDATION_CLOCK,
        expires_at=VALIDATION_CLOCK + timedelta(minutes=15),
        trace=TRACE,
    )


def _position(proposal: TradeProposal, owner: str) -> DebatePosition:
    return DebatePosition(
        proposal_id=proposal.proposal_id,
        owner_agent_id=owner,
        asset=proposal.asset,
        direction=proposal.direction,
        strategy=proposal.strategy,
        claim=f"{proposal.strategy} {proposal.direction.value} {proposal.asset}",
        evidence_refs=proposal.evidence_refs,
    )


def _bus() -> AgentBus:
    reg = AgentRegistry()
    cap = CapabilityRegistry()
    register_swarm_agents(reg, cap)
    register_debate_agents(reg, cap)
    return AgentBus(
        agent_registry=reg,
        capability_registry=cap,
        blackboard=Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id),
        clock=lambda: VALIDATION_CLOCK,
    )


def _conflict_debate() -> tuple[DebateSession, AgentBus]:
    """Momentum LONG vs MeanReversion SHORT on SOL (MA-3K canonical case)."""
    long_p = _proposal(
        "p:long",
        direction=TradeDirection.LONG,
        strategy="momentum",
        evidence_id="ev:long",
    )
    short_p = _proposal(
        "p:short",
        direction=TradeDirection.SHORT,
        strategy="mean_reversion",
        evidence_id="ev:short",
        confidence=0.7,
    )
    evidence = {
        "ev:long": _evidence("ev:long", "strategy-expert-momentum", "p:long"),
        "ev:short": _evidence("ev:short", "strategy-expert-mean_reversion", "p:short"),
    }
    bus = _bus()
    session = DebateSession(
        debate_id="debate:conflict",
        bus=bus,
        positions=[
            _position(long_p, "strategy-expert-momentum"),
            _position(short_p, "strategy-expert-mean_reversion"),
        ],
        proposals={"p:long": long_p, "p:short": short_p},
        regime_by_asset={"SOL": "TREND_UP"},
        evidence_registry=evidence,
        max_rounds=MAX_DEBATE_ROUNDS,
    )
    return session, bus


def _conflict_snapshot() -> OpportunitySnapshot:
    return _snapshot_with(("p:long", "p:short"))


def _clean_snapshot() -> OpportunitySnapshot:
    return _snapshot_with(("p:long",))


def _snapshot_with(proposal_ids: tuple[str, ...]) -> OpportunitySnapshot:
    specs = {
        "p:long": (
            TradeDirection.LONG,
            "momentum",
            "ev:long",
            "strategy-expert-momentum",
        ),
        "p:short": (
            TradeDirection.SHORT,
            "mean_reversion",
            "ev:short",
            "strategy-expert-mean_reversion",
        ),
    }
    board = OpportunityBoard(run_id=TRACE.run_id, now=VALIDATION_CLOCK)
    for pid in proposal_ids:
        direction, strategy, ev_id, owner = specs[pid]
        board.add_evidence(_evidence(ev_id, owner, pid))
        board.add(
            _proposal(
                pid,
                direction=direction,
                strategy=strategy,
                evidence_id=ev_id,
                confidence=0.7 if pid == "p:short" else 0.8,
            ),
            source_agent_id=owner,
            source_agent_version="1.0.0",
        )
    return board.snapshot()


def _check(name: str, passed: bool, detail: str = "") -> None:
    results[name] = PASS if passed else FAIL
    if detail:
        details[name] = detail
    symbol = "[OK]" if passed else "[!!]"
    print(f"  {symbol} MA3-{name}: {PASS if passed else FAIL}{f' ({detail})' if detail else ''}")


def validate() -> bool:
    print("\n=== MA-3 Independent Validator ===\n")

    # --- 1. Conflict creates debate (deterministic router, no LLM) ---
    router = DebateRouter()
    long_pos = _position(
        _proposal(
            "p:long",
            direction=TradeDirection.LONG,
            strategy="momentum",
            evidence_id="ev:long",
        ),
        "strategy-expert-momentum",
    )
    short_pos = _position(
        _proposal(
            "p:short",
            direction=TradeDirection.SHORT,
            strategy="mean_reversion",
            evidence_id="ev:short",
            confidence=0.7,
        ),
        "strategy-expert-mean_reversion",
    )
    route = router.route(
        _conflict_snapshot(),
        positions={"p:long": long_pos, "p:short": short_pos},
        regime_by_asset={"SOL": "TREND_UP"},
    )
    clean_route = DebateRouter().route(
        _clean_snapshot(),
        positions={"p:long": long_pos},
        regime_by_asset={"SOL": "TREND_UP"},
        evidence_registry={"ev:long": _evidence("ev:long", "strategy-expert-momentum", "p:long")},
    )
    conflict_routed = (
        route.decision.value == "DEBATE_REQUIRED"
        and DebateRouteReason.DIRECTIONAL_CONFLICT in route.reasons
        and clean_route.decision.value == "NO_DEBATE"
    )
    _check(
        "conflict_creates_debate",
        conflict_routed,
        f"conflict -> {route.decision.value}, uncontested -> {clean_route.decision.value}",
    )

    # --- 2. Challenge exists (structured, bus-carried) ---
    session, bus = _conflict_debate()
    report = session.run()
    challenges = [c for c in report.critiques if c.stance is CritiqueStance.CHALLENGE]
    critique_messages = [
        m for m in bus.accepted_messages if m.message_type is AgentMessageType.CRITIQUE
    ]
    structured = all(dict(m.payload).get("critique_id") is not None for m in critique_messages)
    _check(
        "challenge_exists",
        len(challenges) > 0 and len(critique_messages) > 0 and structured,
        f"{len(challenges)} challenges, {len(critique_messages)} CRITIQUE messages",
    )

    # --- 3. Counter-evidence survives ---
    counter_critiques = [
        c
        for c in report.critiques
        if c.critic_agent_id == "critic-counter-signal" and c.stance is CritiqueStance.CHALLENGE
    ]
    counter_refs = {ref for c in counter_critiques for ref in c.counter_evidence_refs}
    counter_survives = (
        len(counter_critiques) >= 1
        and len(counter_refs) > 0
        and counter_refs == set(report.counter_evidence)
    )
    _check(
        "counter_evidence_survives",
        counter_survives,
        f"{len(counter_refs)} counter refs in report, "
        f"{len(counter_critiques)} adversarial critiques",
    )

    # --- 4. Evidence requests are traceable; never invented ---
    missing_p = _proposal(
        "p:missing",
        direction=TradeDirection.LONG,
        strategy="breakout",
        evidence_id="ev:ghost",
    )
    bus2 = _bus()
    session2 = DebateSession(
        debate_id="debate:missing",
        bus=bus2,
        positions=[_position(missing_p, "strategy-expert-breakout")],
        proposals={"p:missing": missing_p},
        regime_by_asset={"SOL": "TREND_UP"},
        evidence_registry={},  # ref unresolvable -> PROVIDE_EVIDENCE
        max_rounds=MAX_DEBATE_ROUNDS,
    )
    report2 = session2.run()
    request_messages = [
        m for m in bus2.accepted_messages if m.message_type is AgentMessageType.EVIDENCE_REQUEST
    ]
    response_messages = [
        m for m in bus2.accepted_messages if m.message_type is AgentMessageType.EVIDENCE_RESPONSE
    ]
    no_invention = (
        # No evidence item may enter the ledger from the missing-evidence
        # debate except the critique's own audit-evidence binding (which is
        # registered bus evidence attributing the CRITIQUE, never new market
        # evidence attributed to the proposal owner).
        all(
            owner not in attributed
            for _, attributed in session2.ledger.attribution()
            for owner in ("strategy-expert-breakout",)
        )
    )
    requests_traceable = (
        len(report2.evidence_requests) > 0
        and len(request_messages) > 0
        and len(response_messages) > 0
        and report2.outcome is DebateOutcome.INSUFFICIENT_EVIDENCE
        and no_invention
    )
    _check(
        "evidence_requests_traceable",
        requests_traceable,
        f"{len(report2.evidence_requests)} requests, "
        f"{len(response_messages)} responses, "
        f"outcome={report2.outcome.value}, invented_evidence=0",
    )

    # --- 5. Proposal revision is immutable with lineage ---
    reg_p = _proposal(
        "p:rev",
        direction=TradeDirection.SHORT,
        strategy="momentum",
        evidence_id="ev:rev",
        confidence=0.86,
    )
    bus3 = _bus()
    session3 = DebateSession(
        debate_id="debate:rev",
        bus=bus3,
        positions=[_position(reg_p, "strategy-expert-momentum")],
        proposals={"p:rev": reg_p},
        regime_by_asset={"SOL": "TREND_UP"},
        evidence_registry={"ev:rev": _evidence("ev:rev", "strategy-expert-momentum", "p:rev")},
        max_rounds=MAX_DEBATE_ROUNDS,
    )
    report3 = session3.run()
    original: TradeProposal = reg_p
    revision_ok = (
        len(report3.revisions) == 1
        and report3.revisions[0].original_proposal_id == "p:rev"
        and report3.revisions[0].revised_proposal_id != "p:rev"
        and len(report3.revisions[0].triggering_critique_ids) >= 1
        and original.confidence == 0.86  # original object never mutated
        and original.proposal_id == "p:rev"
        and "p:rev" in report3.proposal_ids  # original remains auditable
        and session3.revised_proposals[report3.revisions[0].revised_proposal_id].confidence < 0.86
        and report3.outcome is DebateOutcome.REVISED
    )
    _check(
        "revision_immutable",
        revision_ok,
        f"{report3.revisions[0].original_proposal_id} -> "
        f"{report3.revisions[0].revised_proposal_id}, "
        f"original preserved (confidence {original.confidence})",
    )

    # --- 6. Same evidence is not double-counted ---
    ledger = DebateLedger()
    shared = _evidence("ev:shared", "strategy-expert-momentum", "p:x")
    for agent in ("critic-evidence", "critic-regime", "critic-counter-signal"):
        ledger.add(shared, agent)
    dedup_ok = ledger.unique_count() == 1 and dict(ledger.attribution())[shared.evidence_id] == (
        "critic-counter-signal",
        "critic-evidence",
        "critic-regime",
    )
    _check(
        "evidence_not_double_counted",
        dedup_ok,
        "3 attributions -> 1 unique evidence item",
    )

    # --- 7. Loop terminates (no-new-evidence anti-loop) ---
    session4, _ = _conflict_debate()
    report4 = session4.run()
    loop_ok = report4.round_count <= MAX_DEBATE_ROUNDS and report4.termination_reason in (
        DebateTerminationReason.NO_NEW_EVIDENCE,
        DebateTerminationReason.MAX_ROUNDS,
    )
    _check(
        "loop_terminates",
        loop_ok,
        f"rounds={report4.round_count}/{MAX_DEBATE_ROUNDS}, "
        f"termination={report4.termination_reason.value}",
    )

    # --- 8. Unresolved remains unresolved (first-class) ---
    session5, _ = _conflict_debate()
    report5 = session5.run()
    unresolved_ok = (
        report4.outcome is DebateOutcome.UNRESOLVED
        and report5.outcome is DebateOutcome.UNRESOLVED
        and report4.termination_reason
        is report5.termination_reason
        is DebateTerminationReason.NO_NEW_EVIDENCE
        and len(report4.proposal_ids) == 2  # both conflicting proposals preserved
    )
    _check(
        "unresolved_remains_unresolved",
        unresolved_ok,
        f"outcome={report4.outcome.value} reproduced across independent runs",
    )

    # --- 9. Deterministic replay ---
    reports: list[Any] = []
    message_orders: list[list[str]] = []
    for _ in range(2):
        s, b = _conflict_debate()
        reports.append(s.run())
        message_orders.append(
            [f"{m.message_id}|{m.sender}|{m.receiver}" for m in b.accepted_messages]
        )
    replay_ok = (
        reports[0].model_dump_json() == reports[1].model_dump_json()
        and message_orders[0] == message_orders[1]
    )
    _check(
        "deterministic_replay",
        replay_ok,
        "identical DebateReport and message ordering across replay",
    )

    # --- 10. Single temporal authority ---
    debate_src = (_root / "src" / "trading_bot" / "multi_agent" / "debate.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(debate_src)
    wall_clock_calls = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"now", "utcnow", "today", "time"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"datetime", "date", "time"}
        ):
            wall_clock_calls += 1
    temporal_ok = (
        wall_clock_calls == 0
        and report.created_at == VALIDATION_CLOCK
        and all(c.created_at == VALIDATION_CLOCK for c in report.critiques)
    )
    _check(
        "single_temporal_authority",
        temporal_ok,
        f"wall_clock_calls_in_debate_logic={wall_clock_calls}, "
        "timestamps derive from injected bus clock",
    )

    # --- 11. Execution capability = 0 ---
    reg = AgentRegistry()
    cap_reg = CapabilityRegistry()
    manifests = register_debate_agents(reg, cap_reg)
    caps_ok = True
    for manifest in manifests:
        perms = cap_reg.permissions_for(manifest.agent_id, manifest.agent_version)
        for forbidden_cap in (
            AgentCapability.EXECUTE,
            AgentCapability.PRODUCTION_ACTION,
            AgentCapability.RISK_OVERRIDE,
            AgentCapability.DIRECT_BROKER_ACCESS,
        ):
            if forbidden_cap in perms:
                caps_ok = False
                details[f"capability_violation_{manifest.agent_id}"] = forbidden_cap.value
        for action in (
            ForbiddenAction.PLACE_LIVE_ORDER,
            ForbiddenAction.CHANGE_RISK_LIMIT,
            ForbiddenAction.OVERRIDE_RISK_REJECTION,
        ):
            if action in manifest.forbidden_actions:
                continue
            caps_ok = False
            details[f"forbidden_action_missing_{manifest.agent_id}"] = action.value
    forbidden_prefixes = (
        "trading_bot.paper",
        "trading_bot.risk",
        "trading_bot.execution",
        "trading_bot.config",
    )
    tree = ast.parse(debate_src)
    import_violations = []
    for node in ast.walk(tree):
        mod = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            mod = node.module
        if mod and any(mod.startswith(p) for p in forbidden_prefixes):
            import_violations.append(mod)
    _check(
        "execution_capability_zero",
        caps_ok and not import_violations,
        f"{len(manifests)} critics verified, no forbidden capabilities, "
        f"{len(import_violations)} execution imports",
    )

    # --- Summary ---
    total = len(results)
    passed_count = sum(1 for v in results.values() if v == PASS)
    failed = total - passed_count
    print(f"\n{'=' * 40}")
    print(f"Result: {passed_count}/{total} PASS, {failed} FAIL")
    print(f"{'=' * 40}\n")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "validator": "ma3-structured-debate",
        "total": total,
        "passed": passed_count,
        "failed": failed,
        "results": results,
        "details": details,
    }
    REPORT_PATH.write_text(json.dumps(report_payload, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")

    return failed == 0


if __name__ == "__main__":
    success = validate()
    sys.exit(0 if success else 1)
