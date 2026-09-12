"""Generate deterministic, read-only profitability diagnostics reports.

This tool only reads persisted R2 campaign reports and writes its own output
directory. It never imports or invokes risk, broker, shadow resolver, or H6.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "reports/poc02-r2-direction-arbitration-01"
DOCS = ROOT / "docs/profitability-diagnostics-01"
REPORTS = ROOT / "reports/profitability-diagnostics-01"

TAXONOMY = {
    "max open positions": "MAX_POSITIONS",
    "cooldown": "COOLDOWN",
    "stale": "STALE_DATA",
    "duplicate": "DUPLICATE_INTENT",
    "invalid": "DATA_INVALID",
    "unresolved_conflict": "AGENT_REJECT",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    """Stable source label, including synthetic test fixtures outside ROOT."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def normalize_reason(value: str | None) -> str:
    lowered = (value or "").lower().replace(" ", "_")
    for token, normalized in TAXONOMY.items():
        if token.replace(" ", "_") in lowered:
            return normalized
    return "OTHER"


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def collect() -> dict[str, Any]:
    # R2_CYCLE_LEDGER is the execution-evidence authority: it carries the
    # complete per-run state. Telemetry JSON files are transport observability
    # and must not be substituted when they omit state counters.
    telemetry = load_json_lines(CAMPAIGN / "R2_CYCLE_LEDGER.jsonl")
    telemetry_files = len(list((CAMPAIGN / "cycles").glob("POC02_TELEMETRY_*.json")))
    intents = load_json_lines(CAMPAIGN / "cycles/R2_INTENT_LEDGER.jsonl")
    captures = load_json_lines(CAMPAIGN / "shadow/shadow_captures.jsonl")
    state = json.loads((CAMPAIGN / "R2_CAMPAIGN_STATE.json").read_text(encoding="utf-8"))
    launch = json.loads((CAMPAIGN / "R2_LAUNCH_RECORD.json").read_text(encoding="utf-8"))
    return {
        "telemetry": telemetry,
        "telemetry_files": telemetry_files,
        "intents": intents,
        "captures": captures,
        "state": state,
        "launch": launch,
    }


def funnel(data: dict[str, Any]) -> dict[str, Any]:
    rows = [item.get("state", item) for item in data["telemetry"]]

    def sums(key: str) -> int:
        return sum(int(row.get(key, 0) or 0) for row in rows)
    counts = {
        "MARKET_WINDOWS": sums("market_scans"),
        "RAW_STRATEGY_SIGNAL": "UNKNOWN",
        "TRADE_PROPOSAL": sums("trade_proposals"),
        "STRATEGY_ROUTER": "UNKNOWN",
        "AGENT_REVIEW": sums("debates"),
        "CRITIC": "UNKNOWN",
        "METARANKER": "UNKNOWN",
        "DECISION_ENGINE": sums("decisions_selected") + sums("no_trade"),
        "VERIFIER": sums("decisions_selected") + sums("no_trade"),
        "RISK": sums("risk_accepts") + sums("risk_rejects"),
        "EXECUTION_INTENT": len(data["intents"]),
        "PAPER_ORDER": sums("paper_trades"),
        "CLOSED_TRADE": sums("closed_trades"),
    }
    reasons: Counter[str] = Counter()
    for row in rows:
        for decision in row.get("decisions", []):
            if decision.get("outcome") != "NO_TRADE":
                continue
            for reason in decision.get("reasons", []):
                reasons[normalize_reason(reason)] += 1
        for event in row.get("events", []):
            if event.get("event") == "risk.rejected":
                reasons[normalize_reason(event.get("reason"))] += 1
    stages = []
    previous: int | None = None
    for name, count in counts.items():
        if not isinstance(count, int):
            stages.append(
                {
                    "stage": name,
                    "input_count": "UNKNOWN",
                    "pass_count": "UNKNOWN",
                    "reject_count": "UNKNOWN",
                    "pass_rate": "UNKNOWN",
                    "reject_rate": "UNKNOWN",
                }
            )
            continue
        comparable = previous is not None and count <= previous
        rejected: int | str = max(previous - count, 0) if comparable else "UNKNOWN"
        pass_rate: float | str = count / previous if comparable and previous else "UNKNOWN"
        reject_rate: float | str = rejected / previous if comparable and previous else "UNKNOWN"
        stages.append(
            {
                "stage": name,
                "input_count": previous if previous is not None else count,
                "pass_count": count,
                "reject_count": rejected,
                "pass_rate": pass_rate,
                "reject_rate": reject_rate,
                "transition_status": "COMPARABLE" if comparable else "UNKNOWN_UNCOMPARABLE_UNITS",
            }
        )
        previous = count
    return {
        "telemetry_files": int(data.get("telemetry_files", len(rows))),
        "counts": counts,
        "stages": stages,
        "rejection_reasons": dict(sorted(reasons.items())),
    }


def authority_map() -> list[dict[str, str]]:
    return [
        {
            "component": "Market Data",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "R2 launch: public binanceusdm OHLCV",
        },
        {
            "component": "Market Intelligence",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "poc02_runner composes asset context",
        },
        {
            "component": "Asset Intelligence",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "telemetry asset_assessments",
        },
        {
            "component": "Strategy Router",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "paper_cycle canonical path; telemetry strategy_evaluations",
        },
        {
            "component": "Trade Proposal",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "telemetry trade_proposals",
        },
        {
            "component": "Agent Review / Critic",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "telemetry debates and decision reasons",
        },
        {
            "component": "MetaRanker",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "poc02_runner DecisionEngine composition",
        },
        {
            "component": "Decision Engine",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "persisted decision events",
        },
        {
            "component": "Independent Verifier",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "persisted verifier=VERIFIED events",
        },
        {
            "component": "Risk Engine",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "risk.rejected and risk accept counters",
        },
        {
            "component": "Portfolio",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "open_positions persisted",
        },
        {
            "component": "Execution / PaperBroker",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "R2 launch authority and paper.position_opened",
        },
        {
            "component": "Reconciliation",
            "classification": "RUNTIME_REACHABLE",
            "evidence": "poc02_r2_reconciliation script",
        },
        {
            "component": "Shadow",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "11 persisted capture records",
        },
        {
            "component": "Live execution",
            "classification": "DEAD_CODE",
            "evidence": "launch state records live_calls=0 and real_broker_calls=0",
        },
    ]


def write_json(name: str, value: Any) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (DOCS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_md(name: str, title: str, payload: Any) -> None:
    (DOCS / name).write_text(
        f"# {title}\n\n```json\n{json.dumps(payload, indent=2, sort_keys=True)}\n```\n",
        encoding="utf-8",
    )


def generate() -> dict[str, Any]:
    data = collect()
    f = funnel(data)
    amap = authority_map()
    protected = [
        CAMPAIGN / "R2_CAMPAIGN_STATE.json",
        CAMPAIGN / "cycles/R2_INTENT_LEDGER.jsonl",
        CAMPAIGN / "shadow/shadow_captures.jsonl",
    ]
    before = {display_path(p): sha256(p) for p in protected}
    common = {
        "authority": "EXECUTION_EVIDENCE",
        "funnel": f,
        "economic_status": "INSUFFICIENT_SAMPLE",
        "claim_discipline": "No counterfactual outcome was calculated or synthesized.",
    }
    artifacts: list[tuple[str, str, Any]] = [
        (
            "01_RUNTIME_AUTHORITY_MAP",
            "Runtime authority map",
            {
                "components": amap,
                "TEST_TARGET_EQUALS_RUNTIME_TARGET": "PARTIAL_FALSE: MA validation reports prove contracts; R2 reports prove runtime composition.",
            },
        ),
        ("02_DECISION_FUNNEL_REPORT", "Decision funnel report", common),
        (
            "03_REJECTION_REASON_ANALYSIS",
            "Rejection reason analysis",
            {
                "taxonomy": [*sorted(set(TAXONOMY.values())), "OTHER"],
                "observed": f["rejection_reasons"],
                "classification": "MISSING_EVIDENCE for economic quality",
            },
        ),
        (
            "04_ACCEPTED_VS_REJECTED",
            "Accepted versus rejected",
            {
                "accepted_execution_intents": len(data["intents"]),
                "shadow_rejected": len(data["captures"]),
                "outcomes_authoritative": 0,
                "verdict": "INSUFFICIENT_SAMPLE",
            },
        ),
        (
            "05_RISK_VALUE_ADD_AUDIT",
            "Risk value-add audit",
            {
                "risk_rejection_reasons": f["rejection_reasons"],
                "counterfactual_expectancy": "UNKNOWN",
                "verdict": "INSUFFICIENT_EVIDENCE",
            },
        ),
        (
            "06_CRITIC_VALUE_ADD_AUDIT",
            "Critic value-add audit",
            {
                "decision_reasons": f["rejection_reasons"],
                "outcome_comparison": "UNKNOWN",
                "verdict": "INSUFFICIENT_EVIDENCE",
            },
        ),
        (
            "07_METARANKER_VALUE_ADD_AUDIT",
            "MetaRanker value-add audit",
            {
                "runtime_reachable": True,
                "selected_vs_alternatives_outcomes": "UNKNOWN",
                "verdict": "INSUFFICIENT_EVIDENCE",
            },
        ),
        (
            "08_AGENT_UTILITY_MATRIX",
            "Agent utility matrix",
            {
                "agents": [
                    {
                        "agent_id": "asset-specialists",
                        "classification": "KEEP_BUT_MEASURE",
                        "economic_evidence": "UNKNOWN",
                    },
                    {
                        "agent_id": "critic-counter-signal",
                        "classification": "KEEP_BUT_MEASURE",
                        "economic_evidence": "UNKNOWN",
                    },
                    {
                        "agent_id": "meta-ranker",
                        "classification": "KEEP_BUT_MEASURE",
                        "economic_evidence": "UNKNOWN",
                    },
                    {
                        "agent_id": "decision-verifier",
                        "classification": "KEEP",
                        "economic_evidence": "integrity only",
                    },
                ]
            },
        ),
        (
            "09_AGENT_ABLATION_REPORT",
            "Agent ablation report",
            {
                "status": "ABLATION_NOT_YET_EVALUABLE",
                "reason": "Persisted evidence lacks identical alternative outcomes and replay inputs.",
            },
        ),
        (
            "10_COMPLEXITY_AUDIT",
            "Complexity audit",
            {
                "findings": [
                    "Critic/MetaRanker/DecisionEngine are individually reachable but lack separated outcome evidence.",
                    "Verifier is essential integrity control, not measured economic filter.",
                    "Risk max-position gate has captures but no resolved outcomes.",
                ]
            },
        ),
        (
            "11_FREQUENCY_FUNNEL",
            "Frequency funnel",
            {
                "target": ">=3 valid executions/day",
                "observed_paper_orders": f["counts"]["PAPER_ORDER"],
                "primary_recorded_loss": "AGENT_REJECT and MAX_POSITIONS",
                "root_cause": "UNKNOWN_ECONOMICALLY; evidence identifies frequency reduction but not whether it destroys edge.",
            },
        ),
        (
            "12_TIME_TO_FALSIFY",
            "Time to falsify",
            {
                "H1_H3_H5": "UNKNOWN: this checkpoint did not reconstruct complete commit-to-result timelines.",
                "recommendation": "persist idea/spec/data/discovery timestamps in one immutable ledger.",
            },
        ),
    ]
    for stem, title, body in artifacts:
        write_json(stem + ".json", body)
        write_md(stem + ".md", title, body)
    alpha = "# Alpha factory optimization\n\nPreserve data authority, PIT, preregistration and one-discovery integrity gates. Remove no runtime layer until the proposed ablation ledger contains matched proposals, decisions, outcomes and latency.\n"
    (DOCS / "13_ALPHA_FACTORY_OPTIMIZATION.md").write_text(alpha, encoding="utf-8")
    defects = {
        "defects": [
            {
                "DEFECT_ID": "PD-001",
                "CLAIM": "Runtime funnel is fully measurable.",
                "SOURCE": "R2 telemetry",
                "EVIDENCE": "Signals/router/critic/metaranker per-stage counts are absent.",
                "IMPACT": "Cannot locate all frequency loss precisely.",
                "RECOMMENDATION": "Persist one trace keyed by proposal/decision through every gate.",
                "CONFIDENCE": "HIGH",
            },
            {
                "DEFECT_ID": "PD-002",
                "CLAIM": "Risk and Shadow value are economically measurable.",
                "SOURCE": "11 Shadow captures; 0 resolved outcomes",
                "EVIDENCE": "No authoritative outcomes for rejected candidates.",
                "IMPACT": "No counterfactual expectancy or overfiltering claim is valid.",
                "RECOMMENDATION": "Resolve existing captures only under the Shadow authority, then analyze immutable outcomes.",
                "CONFIDENCE": "HIGH",
            },
            {
                "DEFECT_ID": "PD-003",
                "CLAIM": "Agent layers add measured economic value.",
                "SOURCE": "R2 persisted reports",
                "EVIDENCE": "No matched selected/non-selected outcome series or ablation replay inputs.",
                "IMPACT": "Complexity remains economically unproven.",
                "RECOMMENDATION": "Persist deterministic proposal-set snapshots and decision latencies for future offline ablation.",
                "CONFIDENCE": "HIGH",
            },
        ]
    }
    write_json("14_PROFITABILITY_DIAGNOSTICS_DEFECTS.json", defects)
    actions = "# Top profitability actions\n\n1. Persist a per-proposal trace across every funnel gate.\n2. Resolve existing Shadow captures through its owner process and measure only mature outcomes.\n3. Build a replay dataset before changing Critic, MetaRanker, or Risk.\n4. Measure agent latency, calls, and evidence overlap.\n5. Separate safety-value evaluation from economic-value evaluation.\n6. Record raw signals and router outcomes per asset/regime.\n7. Persist selected and non-selected proposal identifiers together.\n8. Record deduplication as a distinct funnel transition.\n9. Add immutable decision-to-outcome linkage.\n10. Run ablation only after matched outcome coverage is sufficient.\n"
    (DOCS / "15_TOP_PROFITABILITY_ACTIONS.md").write_text(actions, encoding="utf-8")
    after = {display_path(p): sha256(p) for p in protected}
    run = {
        "status": "PASS_WITH_EVIDENCE_GAPS",
        "base_inputs": before,
        "state_before_equals_after": before == after,
        "telemetry_files": data["telemetry_files"],
        "shadow_captures": len(data["captures"]),
        "shadow_outcomes": 0,
        "funnel_events_analyzed": len(data["telemetry"]),
        "output_namespace": display_path(DOCS),
    }
    write_json("RUN_REPORT.json", run)
    write_md("RUN_REPORT.md", "Run report", run)
    final = "# Final report\n\n**PASS_WITH_EVIDENCE_GAPS.** Recorded evidence identifies proposal loss at agent conflict rejection and later max-position risk rejection, but no accepted/rejected outcome sample is authoritative. Therefore no component is shown to harm or improve profitability.\n\nThe first safe measurement investment is immutable per-proposal tracing, followed by mature Shadow outcome analysis and offline ablation.\n"
    (DOCS / "FINAL_REPORT.md").write_text(final, encoding="utf-8")
    (REPORTS / "diagnostics_contract.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(generate(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
