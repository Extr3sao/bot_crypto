"""CAP-002 pre-MCP completion — end-to-end synthetic dry run (wiring only).

This script proves the *pipeline* is wired end to end once real data arrives:

    synthetic MarketSnapshot -> MarketHypothesis -> TradeProposal ->
    DecisionRecord -> SEAL -> synthetic future outcome -> baseline producer
    A/B/C/D -> CAP-001 evaluator -> AGENTIC_INCREMENTAL_EDGE -> OutcomeRecord

It proves **wiring only**.  It does not prove edge.  Every artefact is hard
marked ``source=SYNTHETIC_FIXTURE``, ``llm_invoked=false``,
``real_market_data=false``, ``agent_decision_real=false`` and
``counts_toward_pilot=false``, so ``REAL_SEALED_DECISIONS=0``,
``VALID_PILOT_DECISIONS=0``, ``G_TV_CONTEXT=NOT_VERIFIED`` and
``G_AGENTIC_EDGE=NOT_TESTED``.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cap001_run as c1  # noqa: E402

from trading_bot.research import agentic_baselines as ab  # noqa: E402
from trading_bot.research import agentic_contracts as ac  # noqa: E402

OUT = REPO / "reports" / "agentic-spike-cap002"
REPORTS = REPO / "reports"
FIXTURE = REPO / "tests" / "fixtures" / "tradingview_mcp_sample.json"

#: §1 — canonical provenance markers for a non-real dry run.
SYNTHETIC_SOURCE = "SYNTHETIC_FIXTURE"
PROMPT_VERSION = "CAP-002-SYNTHETIC-DRY-RUN-NOT-AN-LLM-RUN"
HORIZON_DAYS = 2


# --------------------------------------------------------------------------- #
# entry gate
# --------------------------------------------------------------------------- #


def entry_gate() -> dict[str, Any]:
    return c1.entry_gate()


# --------------------------------------------------------------------------- #
# synthetic decision flow
# --------------------------------------------------------------------------- #


def synthetic_future(entry: float, decision_time: int) -> dict[str, Any]:
    """One deterministic, clearly synthetic future path for the mechanism."""
    return {
        "entry_reference": entry,
        "exit_reference": entry * 1.03,
        "path": (entry * 1.01, entry * 0.99, entry * 1.02),
        "evaluation_time": decision_time + HORIZON_DAYS * 86_400,
    }


def synthetic_daily_bars(*, decision_time: int, count: int = 220) -> list[ab.DailyBar]:
    """Deterministic daily closes, all fully closed before ``decision_time``."""
    last_open = decision_time - 2 * 86_400
    start = last_open - (count - 1) * 86_400
    return [ab.DailyBar(open_time=start + index * 86_400, close=100.0 + index * 0.8) for index in range(count)]


def build_hypothesis(snapshot: ac.MarketSnapshot) -> ac.MarketHypothesis:
    return ac.MarketHypothesis(
        asset=snapshot.asset,
        horizon=f"{HORIZON_DAYS}d",
        direction="LONG",
        thesis="synthetic wiring demo (not a market view)",
        catalysts=("synthetic_fixture",),
        evidence=("synthetic multi-timeframe trend",),
        counter_evidence=("synthetic counter-evidence",),
        invalidation="synthetic invalidation",
        confidence=0.5,
        expected_holding_period=f"{HORIZON_DAYS}d",
    )


def build_proposal(snapshot: ac.MarketSnapshot, hypothesis: ac.MarketHypothesis) -> ac.TradeProposal:
    last = snapshot.price_state.last
    return ac.TradeProposal(
        asset=snapshot.asset,
        direction="LONG",
        horizon=hypothesis.horizon,
        claim="synthetic wiring demo",
        evidence=hypothesis.evidence,
        counter_evidence=hypothesis.counter_evidence,
        invalidation=hypothesis.invalidation,
        confidence=hypothesis.confidence,
        expected_reward_zone=ac.ExpectedZone(low=last, high=last * 1.05),
        expected_risk_zone=ac.ExpectedZone(low=last * 0.95, high=last),
        decision_time=snapshot.timestamp,
    )


def seal_decision(
    snapshot_hash: str, snapshot_at: int, hypothesis: ac.MarketHypothesis
) -> ac.DecisionRecord:
    return ac.seal_decision_record(
        timestamp=snapshot_at,
        prompt_version=PROMPT_VERSION,
        evidence_snapshot_hash=snapshot_hash,
        agent_output={
            "_synthetic": True,
            "_note": "no LLM ran; this exercises the sealed-decision mechanism only",
            "hypothesis": hypothesis.to_dict(),
        },
        critic_output={"_synthetic": True},
        decision="LONG",
    )


# --------------------------------------------------------------------------- #
# immutability
# --------------------------------------------------------------------------- #


def build_immutability_artifact(record: ac.DecisionRecord, outcome: ab.OutcomeRecord) -> dict[str, Any]:
    ledger = ac.DecisionLedger()
    ledger.append(record)
    tampered = dataclasses.replace(record, decision="SHORT")
    return {
        "sealed_hash": record.decision_hash,
        "sealed_verified": record.is_verified(),
        "ledger_digest": ledger.digest(),
        "same_inputs_same_hash": seal_decision("x" * 64, 1, _hypothesis_stub()).decision_hash
        == seal_decision("x" * 64, 1, _hypothesis_stub()).decision_hash,
        "mutation_changes_hash": tampered.recomputed_hash() != record.decision_hash,
        "mutation_detected": ac.detect_tampering([tampered, record]) == [0],
        "hash_unchanged_by_outcome": outcome.decision_hash == record.decision_hash,
        "record_verified_after_outcome": record.is_verified(),
    }


def _hypothesis_stub() -> ac.MarketHypothesis:
    return ac.MarketHypothesis(
        asset="synthetic",
        horizon="1d",
        direction="NO_TRADE",
        thesis="stub",
        catalysts=(),
        evidence=(),
        counter_evidence=(),
        invalidation="",
        confidence=0.0,
        expected_holding_period="n/a",
        no_trade_reason="stub",
    )


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #


def _false_success(outcome: ab.OutcomeRecord, immutability: dict[str, Any]) -> list[str]:
    triggers: list[str] = []
    if ac.G_TV_CONTEXT == "PASS":
        triggers.append("G_TV_CONTEXT claimed PASS without a credentialled real snapshot")
    if any(value != 0 for value in ac.KPI_VALUES.values()):
        triggers.append("a profit KPI was raised off zero")
    if outcome.counts_toward_pilot and outcome.source == SYNTHETIC_SOURCE:
        triggers.append("a synthetic outcome counted toward the pilot")
    if not immutability["record_verified_after_outcome"]:
        triggers.append("the sealed decision stopped verifying after the outcome")
    return triggers


def build_report(
    *,
    gate: dict[str, Any],
    snapshot_artifact: dict[str, Any],
    record: ac.DecisionRecord,
    outcome: ab.OutcomeRecord,
    immutability: dict[str, Any],
    economic_state_digest_after: str,
) -> dict[str, Any]:
    baselines = {b.baseline_id: b for b in outcome.baseline_outcomes}
    headline = outcome.edge_by_id(ab.BASELINE_ID_BUY_AND_HOLD)
    return {
        "spike": "CAP-002 PRE-MCP COMPLETION",
        "governance_framing": ac.GOVERNANCE_FRAMING,
        "alpha_research_freeze": ac.ALPHA_RESEARCH_FREEZE,
        "next_alpha_rfc_allowed": ac.NEXT_ALPHA_RFC_ALLOWED,
        "rfc_created": ac.RFC_CREATED,
        "alpha_claimed": ac.ALPHA_CLAIMED,
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "source": SYNTHETIC_SOURCE,
        "synthetic": True,
        "llm_invoked": False,
        "real_market_data": False,
        "agent_decision_real": False,
        "counts_toward_pilot": False,
        "real_sealed_decisions": 0,
        "valid_pilot_decisions": 0,
        "g_tv_context": ac.G_TV_CONTEXT,
        "g_agentic_edge": ab.G_AGENTIC_EDGE,
        "business_validated_edge_count": ac.KPI_VALUES["STRATEGY_EDGE"],
        "baseline_ids": list(ab.BASELINE_IDS),
        "baseline_available": {bid: baseline.available for bid, baseline in baselines.items()},
        "baseline_unavailable_reason": {
            bid: baseline.reason for bid, baseline in baselines.items() if not baseline.available
        },
        "agent_gross_return": outcome.gross_return,
        "agent_costs": outcome.costs,
        "agent_net_return": outcome.net_return,
        "agentic_incremental_edge_vs_b_buy_and_hold": None if headline is None else headline["edge"],
        "incremental_edges": [dict(edge) for edge in outcome.incremental_edges],
        "snapshot_source": snapshot_artifact["_source"],
        "snapshot_usable": snapshot_artifact["_usable"],
        "immutability": immutability,
        "economic_state_digest_unchanged": economic_state_digest_after,
        "gates": {gate_name: (ac.G_TV_CONTEXT if gate_name == "G0_TV_CONTEXT" else "NOT_STARTED") for gate_name in ac.GATES},
        "hard_stop": (
            "WIRING ONLY. No real data, no LLM, no edge claim. G_TV_CONTEXT stays NOT_VERIFIED until a "
            "credentialled, user-authorized real TradingView snapshot exists."
        ),
        "false_success": _false_success(outcome, immutability),
    }


def final_report_md(report: dict[str, Any], verification: dict[str, Any]) -> str:
    lines = ["CAP-002 PRE-MCP COMPLETION", ""]
    for key, value in report.items():
        lines.append(f"{key.upper().replace('_', ' ')} = {value}")
    lines.append("")
    lines.append("## Independent verification")
    lines.append("")
    lines.append(f"INDEPENDENT VERIFICATION = {verification['status']}")
    lines.append(f"CHECKS = {verification['passed']}/{verification['total']}")
    lines.append(f"MISMATCHES = {verification['mismatches']}")
    lines.append(f"FALSE_SUCCESS = {verification['false_success']}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    gate_state = entry_gate()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshot, snapshot_artifact = c1.build_snapshot_artifact(fixture)

    hypothesis = build_hypothesis(snapshot)
    proposal = build_proposal(snapshot, hypothesis)
    hypothesis_problems = ac.validate_hypothesis(hypothesis)
    proposal_problems = ac.validate_proposal(proposal)

    record = seal_decision(snapshot_artifact["_evidence_snapshot_hash"], snapshot.timestamp, hypothesis)
    future = synthetic_future(snapshot.price_state.last, snapshot.timestamp)
    bars = synthetic_daily_bars(decision_time=snapshot.timestamp)
    outcome = ab.build_outcome_record(
        record=record,
        asset=snapshot.asset,
        evaluation_time=future["evaluation_time"],
        entry_reference=future["entry_reference"],
        exit_reference=future["exit_reference"],
        path=future["path"],
        daily_bars=bars,
        source=SYNTHETIC_SOURCE,
    )
    immutability = build_immutability_artifact(record, outcome)
    digest_after = c1.file_digest(c1.ECONOMIC_STATE)

    decision_artifact = {
        "source": SYNTHETIC_SOURCE,
        "synthetic": True,
        "llm_invoked": False,
        "agent_decision_real": False,
        "counts_toward_pilot": False,
        "prompt_version": PROMPT_VERSION,
        "snapshot_hash": snapshot_artifact["_evidence_snapshot_hash"],
        "hypothesis": hypothesis.to_dict(),
        "proposal": proposal.to_dict(),
        "hypothesis_problems": hypothesis_problems,
        "proposal_problems": proposal_problems,
        "record": record.to_dict(),
        "record_verified": record.is_verified(),
    }
    baselines_artifact = {
        "source": SYNTHETIC_SOURCE,
        "synthetic": True,
        "cost_model": ab.DEFAULT_COST_MODEL.to_dict(),
        "canonical_passive_mapping": ab.CANONICAL_PASSIVE_BENCHMARK_MAPPING,
        "baselines": [baseline.to_dict() for baseline in outcome.baseline_outcomes],
    }

    report = build_report(
        gate=gate_state,
        snapshot_artifact=snapshot_artifact,
        record=record,
        outcome=outcome,
        immutability=immutability,
        economic_state_digest_after=digest_after,
    )
    report["economic_state_unchanged_in_run"] = digest_after == gate_state["economic_state_digest_before"]
    report["entry_gate"] = {
        "branch": gate_state["branch"],
        "head_short": gate_state["head_short"],
        "worktree_dirty": gate_state["worktree_dirty"],
        "freeze_seen": gate_state["freeze_seen"],
        "next_alpha_rfc_allowed_seen": gate_state["next_alpha_rfc_allowed_seen"],
    }

    c1.write_json(OUT / "CAP002_ENTRY_GATE.json", gate_state)
    c1.write_json(OUT / "CAP002_DECISION_RECORD.json", decision_artifact)
    c1.write_md(OUT / "CAP002_DECISION_RECORD.md", c1.render("CAP-002 sealed (synthetic) decision", decision_artifact))
    c1.write_json(OUT / "CAP002_BASELINES.json", baselines_artifact)
    c1.write_md(OUT / "CAP002_BASELINES.md", c1.render("CAP-002 baseline outcomes (synthetic)", baselines_artifact))
    c1.write_json(OUT / "CAP002_OUTCOME_RECORD.json", outcome.to_dict())
    c1.write_md(OUT / "CAP002_OUTCOME_RECORD.md", c1.render("CAP-002 outcome (synthetic)", outcome.to_dict()))
    c1.write_json(OUT / "CAP002_IMMUTABILITY.json", immutability)
    c1.write_md(OUT / "CAP002_IMMUTABILITY.md", c1.render("CAP-002 immutability checks", immutability))

    verification = {"status": "PENDING", "passed": 0, "total": 0, "mismatches": 0, "false_success": 0}
    c1.write_json(REPORTS / "CAP002_FINAL_REPORT.json", {**report, "verification": verification})
    c1.write_md(REPORTS / "CAP002_FINAL_REPORT.md", final_report_md(report, verification))

    print("CAP-002 PRE-MCP COMPLETION")
    print(f"snapshot_source = {report['snapshot_source']} usable = {report['snapshot_usable']}")
    print(f"baseline_available = {report['baseline_available']}")
    print(f"baseline_unavailable_reason = {report['baseline_unavailable_reason']}")
    print(f"agent_net_return = {outcome.net_return}")
    print(f"agentic_incremental_edge_vs_b_buy_and_hold = {report['agentic_incremental_edge_vs_b_buy_and_hold']}")
    print(f"immutability = {immutability}")
    print(f"real_sealed_decisions = {report['real_sealed_decisions']}")
    print(f"valid_pilot_decisions = {report['valid_pilot_decisions']}")
    print(f"G_TV_CONTEXT = {report['g_tv_context']}")
    print(f"G_AGENTIC_EDGE = {report['g_agentic_edge']}")
    print(f"freeze_unchanged = {report['economic_state_unchanged_in_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
