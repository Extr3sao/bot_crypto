"""CAP-001 orchestration — agentic market intelligence capability spike.

A *capability* run, not an alpha run.  It proves that Trading Agentic can carry
the deterministic shell of the V3 paradigm: a timestamped ``MarketSnapshot``
contract, an immutable decision record sealed before the outcome, and the
evaluator primitives that later measure incremental agent value.

It does **not** claim alpha, does not create an RFC, does not release the freeze
and does not touch ``ECONOMIC_STATE.json``.  No LLM runs in this script: the held
payload is a clearly labelled synthetic fixture, and the sealed record exists
only to demonstrate the sealing/verification mechanism.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import agentic_contracts as ac  # noqa: E402
from trading_bot.research import tradingview_mcp_adapter as tva  # noqa: E402

OUT = REPO / "reports" / "agentic-spike-cap001"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"
FIXTURE = REPO / "tests" / "fixtures" / "tradingview_mcp_sample.json"
ECONOMIC_STATE = DOCS / "ECONOMIC_STATE.json"

#: §1 — the documents the spike must read before touching anything.
REQUIRED_DOCUMENTS: tuple[str, ...] = (
    "docs/research/ECONOMIC_STATE.json",
    "docs/research/BUSINESS_REENTRY_POLICY.json",
    "docs/research/FINAL_BUSINESS_DECISION.json",
)

#: §2 — things this spike is never allowed to do.
NOT_ALLOWED: tuple[str, ...] = (
    "new strategy",
    "new signal",
    "new backtest",
    "parameter tuning",
    "broker integration",
    "paper run",
    "live order",
    "credentials",
    "research daemon",
    "scheduled alpha search",
    "create RFC-045",
    "edit ECONOMIC_STATE.json",
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_value(value: Any, indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                out.append(f"{pad}- **{key}**:")
                out.extend(_render_value(item, indent + 1))
            else:
                out.append(f"{pad}- **{key}**: {item}")
        return out
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, sub in item.items():
                    marker = f"{pad}- " if first else f"{pad}  "
                    if isinstance(sub, (dict, list)):
                        out.append(f"{marker}**{key}**:")
                        out.extend(_render_value(sub, indent + 1))
                    else:
                        out.append(f"{marker}**{key}**: {sub}")
                    first = False
            else:
                out.append(f"{pad}- {item}")
        return out
    out.append(f"{pad}{value}")
    return out


def render(title: str, payload: Any) -> str:
    lines = [f"# {title}", ""]
    lines.extend(_render_value(payload, 0))
    lines.append("")
    return "\n".join(lines)


def md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


# --------------------------------------------------------------------------- #
# entry gate
# --------------------------------------------------------------------------- #


def entry_gate() -> dict[str, Any]:
    state_before = file_digest(ECONOMIC_STATE)
    economic = json.loads(ECONOMIC_STATE.read_text(encoding="utf-8"))
    documents = []
    for relative in REQUIRED_DOCUMENTS:
        path = REPO / relative
        documents.append({"path": relative, "present": path.is_file()})
    return {
        "pwd": str(REPO),
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": git(["rev-parse", "HEAD"]),
        "head_short": git(["rev-parse", "--short", "HEAD"]),
        "worktree_dirty": bool(git(["status", "--porcelain"])),
        "documents": documents,
        "freeze_seen": economic.get("alpha_research_freeze"),
        "next_alpha_rfc_allowed_seen": economic.get("next_alpha_rfc_allowed"),
        "economic_state_digest_before": state_before,
        "window": now_utc(),
    }


# --------------------------------------------------------------------------- #
# artefacts
# --------------------------------------------------------------------------- #


def build_snapshot_artifact(fixture: dict[str, Any]) -> tuple[ac.MarketSnapshot, dict[str, Any]]:
    tools = tva.assert_read_only_tools(fixture["tools_used"])
    snapshot = tva.build_snapshot(
        asset=fixture["asset"],
        snapshot_at=int(fixture["snapshot_at"]),
        ohlcv_by_interval=fixture["ohlcv"],
        technicals_payload=fixture["technicals_rating"],
        news_payload=fixture["news"],
        macro_payload=fixture["economic_calendar"],
        market_regime=fixture["market_regime"],
        reference_symbol=fixture["reference_symbol"],
        relative_strength_value=float(fixture["relative_strength"]),
        source_timestamps=fixture["source_timestamps"],
    )
    problems = ac.validate_snapshot(snapshot)
    payload = snapshot.to_dict()
    payload["_contract_fields_expected"] = list(ac.MARKET_SNAPSHOT_FIELDS)
    payload["_contract_fields_present"] = sorted(snapshot.to_dict().keys())
    payload["_validation_problems"] = problems
    payload["_usable"] = ac.snapshot_is_usable(snapshot)
    payload["_source"] = "SYNTHETIC_FIXTURE"
    payload["_synthetic"] = True
    payload["_tools_used"] = list(tools)
    payload["_evidence_snapshot_hash"] = ac.payload_digest(snapshot.to_dict())
    return snapshot, payload


def build_boundaries_artifact() -> dict[str, Any]:
    return {
        "spike_id": ac.SPIKE_ID,
        "spike_name": ac.SPIKE_NAME,
        "governance_framing": ac.GOVERNANCE_FRAMING,
        "authority_map": ac.AUTHORITY_MAP,
        "tradingview_is_accounting_source_of_truth": ac.TRADINGVIEW_IS_ACCOUNTING_SOURCE_OF_TRUTH,
        "non_deterministic_domains": list(ac.NON_DETERMINISTIC_DOMAINS),
        "deterministic_domains": list(ac.DETERMINISTIC_DOMAINS),
        "llm_sizing_forbidden": ac.LLM_SIZING_FORBIDDEN,
        "llm_leverage_forbidden": ac.LLM_LEVERAGE_FORBIDDEN,
        "forbidden_proposal_fields": list(ac.FORBIDDEN_PROPOSAL_FIELDS),
        "read_only_mcp_tools": list(ac.READ_ONLY_MCP_TOOLS),
        "write_mcp_tools_forbidden": list(ac.WRITE_MCP_TOOLS),
        "mcp_constraints": ac.MCP_CONSTRAINTS,
        "forbidden_during_roadmap": list(ac.FORBIDDEN_DURING_ROADMAP),
        "gates": list(ac.GATES),
        "budget_before_g3": ac.BUDGET_BEFORE_G3,
        "universe_v1": list(ac.UNIVERSE_V1),
        "timeframes_v1": list(ac.TIMEFRAMES_V1),
        "kpi_values": ac.KPI_VALUES,
        "immediate_kpi_target": ac.IMMEDIATE_KPI_TARGET,
    }


def build_decision_artifact(snapshot_hash: str, snapshot_at: int) -> dict[str, Any]:
    """Seal one *illustrative* record to exercise sealing and tamper detection."""
    agent_output = {
        "_illustrative": True,
        "_note": "no LLM was invoked in this spike; this exercises the sealing mechanism only",
        "asset": "BINANCE:BTCUSDT",
        "direction": "NO_TRADE",
        "thesis": "illustrative payload for the immutable-record mechanism",
    }
    record = ac.seal_decision_record(
        timestamp=snapshot_at,
        prompt_version="CAP-001-MECHANISM-DEMO-NOT-AN-LLM-RUN",
        evidence_snapshot_hash=snapshot_hash,
        agent_output=agent_output,
        critic_output=None,
        decision="NO_TRADE",
    )
    ledger = ac.DecisionLedger()
    ledger.append(record)
    # A real tamper keeps the sealed hash but changes the content behind it.
    tampered = dataclasses.replace(record, decision="LONG")
    return {
        "llm_invoked": False,
        "agent_decision_real": False,
        "records": [record.to_dict()],
        "record_hash": record.decision_hash,
        "record_verified": record.is_verified(),
        "ledger_digest": ledger.digest(),
        "tamper_detection": {
            "original_decision": record.decision,
            "altered_decision": tampered.decision,
            "altered_recomputed_hash": tampered.recomputed_hash(),
            "hash_changes_on_alteration": tampered.recomputed_hash() != record.decision_hash,
            "detected_indices": ac.detect_tampering([tampered, record]),
        },
    }


def build_gate_audit(snapshot_problems: list[str], snapshot_usable: bool) -> dict[str, Any]:
    return {
        "gate": "G_TV_CONTEXT",
        "status": ac.G_TV_CONTEXT,
        "status_reason": (
            "no TradingView account, subscription or OAuth authorization is available, so the "
            "snapshot is built from a synthetic fixture and cannot be certified as real"
        ),
        "gate_criteria": (
            "reconstruct a consistent and timestamped MarketSnapshot from real TradingView data"
        ),
        "contract_checks": {
            "fields_expected": len(ac.MARKET_SNAPSHOT_FIELDS),
            "validation_problems": snapshot_problems,
            "snapshot_usable": snapshot_usable,
            "synthetic_only": True,
        },
        "blocking_requirements": [
            "TradingView Essential or above subscription",
            "OAuth 2.1 authorization of the official MCP server in an LLM client",
            "explicit user authorization to use the account for this experiment",
        ],
        "gate_statuses": {"G0_TV_CONTEXT": ac.G_TV_CONTEXT, **{gate: "NOT_STARTED" for gate in ac.GATES[1:]}},
        "would_pass_with_real_data": "BEFORE_DATA",
    }


def build_final_report(
    *,
    gate: dict[str, Any],
    snapshot_artifact: dict[str, Any],
    decision: dict[str, Any],
    boundaries: dict[str, Any],
    economic_state_digest_after: str,
) -> dict[str, Any]:
    return {
        "spike": f"{ac.SPIKE_ID} {ac.SPIKE_NAME}",
        "governance_framing": ac.GOVERNANCE_FRAMING,
        "alpha_research_freeze": ac.ALPHA_RESEARCH_FREEZE,
        "next_alpha_rfc_allowed": ac.NEXT_ALPHA_RFC_ALLOWED,
        "rfc_created": ac.RFC_CREATED,
        "alpha_claimed": ac.ALPHA_CLAIMED,
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "snapshot_contract_fields": len(ac.MARKET_SNAPSHOT_FIELDS),
        "snapshot_valid": not snapshot_artifact["_validation_problems"],
        "snapshot_usable": snapshot_artifact["_usable"],
        "snapshot_source": "SYNTHETIC_FIXTURE",
        "data_freshness": snapshot_artifact["data_freshness"]["level"],
        "multi_timeframe": [tf["interval"] for tf in snapshot_artifact["multi_timeframe"]],
        "mcp_tools_used": snapshot_artifact["_tools_used"],
        "write_tools_used": [],
        "llm_invoked": decision["llm_invoked"],
        "decision_ledger_records": len(decision["records"]),
        "immutability_check": "PASS" if decision["record_verified"] else "FAIL",
        "tamper_detection_works": decision["tamper_detection"]["hash_changes_on_alteration"],
        "g_tv_context": gate["status"],
        "g_tv_context_reason": gate["status_reason"],
        "strategy_edge": ac.KPI_VALUES["STRATEGY_EDGE"],
        "agentic_decision_edge": ac.KPI_VALUES["AGENTIC_DECISION_EDGE"],
        "portfolio_edge": ac.KPI_VALUES["PORTFOLIO_EDGE"],
        "immediate_kpi_target": ac.IMMEDIATE_KPI_TARGET,
        "budget_before_g3": boundaries["budget_before_g3"],
        "economic_state_digest_unchanged": economic_state_digest_after,
        "hard_stop": (
            "NO RFC-045. NO alpha claim. NO trade. G_TV_CONTEXT stays NOT_VERIFIED until a "
            "credentialled, user-authorized real TradingView snapshot can be built."
        ),
    }


def final_report_md(report: dict[str, Any], gate: dict[str, Any], verification: dict[str, Any]) -> str:
    lines = [f"{ac.SPIKE_ID} {ac.SPIKE_NAME}", ""]
    for key, value in report.items():
        if key == "spike":
            continue
        lines.append(f"{key.upper().replace('_', ' ')} = {value}")
    lines.append("")
    lines.append("## G_TV_CONTEXT")
    lines.append("")
    lines.extend(md_table(["requirement", "state"], [[item, "MISSING"] for item in gate["blocking_requirements"]]))
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
# docs
# --------------------------------------------------------------------------- #


def contract_md(boundaries: dict[str, Any], snapshot_artifact: dict[str, Any]) -> str:
    lines = [
        "# AGENTIC MARKET INTELLIGENCE CONTRACT (CAP-001)",
        "",
        f"- spike: {boundaries['spike_id']} — {boundaries['spike_name']}",
        f"- governance framing: {boundaries['governance_framing']}",
        f"- alpha research freeze: {ac.ALPHA_RESEARCH_FREEZE} (unchanged by this spike)",
        f"- next alpha RFC allowed: {ac.NEXT_ALPHA_RFC_ALLOWED} (unchanged by this spike)",
        f"- alpha claimed: {ac.ALPHA_CLAIMED}",
        "",
        "## MarketSnapshot contract",
        "",
    ]
    lines.extend(md_table(["field", "meaning"], [
        ["timestamp", "unix seconds UTC of the snapshot"],
        ["asset", "EXCHANGE:TICKER, e.g. BINANCE:BTCUSDT"],
        ["price_state", "last, change_pct, bar_interval, bar_count"],
        ["multi_timeframe", "one entry per interval (technicals are single-interval per call)"],
        ["technical_state", "RSI/MACD/ADX/momentum/SMA/EMA + Recommend aggregate"],
        ["relative_strength", "symbol vs reference"],
        ["volume_state", "last volume and its ratio to the trailing average"],
        ["market_regime", "analyst-supplied regime label (non-deterministic domain)"],
        ["news", "symbol headlines (title, published, provider, urgency)"],
        ["macro_events", "calendar events (name, country, when, importance, actual)"],
        ["evidence", "mechanically collected evidence items with their MCP source"],
        ["data_freshness", "snapshot_at, source timestamps, age_seconds, level, degraded"],
    ]))
    lines.extend([
        "",
        "## Authority",
        "",
    ])
    lines.extend(md_table(["subject", "authority"], [[k, v] for k, v in boundaries["authority_map"].items()]))
    lines.extend([
        "",
        "## Determinism split",
        "",
        "Non-deterministic (the agent owns these):",
        "",
    ])
    lines.extend(f"- {item}" for item in boundaries["non_deterministic_domains"])
    lines.extend(["", "Deterministic (never delegated to an LLM):", ""])
    lines.extend(f"- {item}" for item in boundaries["deterministic_domains"])
    lines.extend([
        "",
        "## Real MCP constraints",
        "",
    ])
    lines.extend(md_table(["constraint", "detail"], [[k, v] for k, v in boundaries["mcp_constraints"].items()]))
    lines.extend([
        "",
        "## Gate status",
        "",
        f"- G_TV_CONTEXT = {ac.G_TV_CONTEXT}",
        "- every later gate = NOT_STARTED",
        "",
        "## Snapshot produced in this spike",
        "",
        f"- source: {snapshot_artifact['_source']}",
        f"- usable: {snapshot_artifact['_usable']}",
        f"- freshness: {snapshot_artifact['data_freshness']['level']}",
        f"- evidence items: {len(snapshot_artifact['evidence'])}",
        "",
    ])
    return "\n".join(lines)


def spike_md(
    gate: dict[str, Any], snapshot_artifact: dict[str, Any], decision: dict[str, Any], boundaries: dict[str, Any]
) -> str:
    lines = [
        "# CAP-001 — AGENTIC MARKET INTELLIGENCE CAPABILITY SPIKE",
        "",
        "A capability spike, not an alpha run. It builds the deterministic shell of the V3",
        "paradigm (timestamped snapshot contract, immutable decision record, evaluator",
        "primitives) without claiming edge, without trading and without releasing the freeze.",
        "",
        "## What was built",
        "",
        f"- MarketSnapshot contract: {len(ac.MARKET_SNAPSHOT_FIELDS)} fields",
        "- deterministic TradingView MCP payload -> snapshot adapter (read-only tools only)",
        "- immutable decision record with a sealed hash and tamper detection",
        "- evaluator primitives: incremental edge vs 4 baselines, hit rate, expectancy,",
        "  profit factor, max drawdown, Brier calibration",
        "",
        "## What was NOT done",
        "",
    ]
    lines.extend(f"- {item}" for item in NOT_ALLOWED)
    lines.extend([
        "",
        "## G_TV_CONTEXT",
        "",
        f"- status: {gate['status']}",
        f"- reason: {gate['status_reason']}",
        "- blocking requirements:",
    ])
    lines.extend(f"  - {item}" for item in gate["blocking_requirements"])
    lines.extend([
        "",
        "## Snapshot (synthetic fixture)",
        "",
    ])
    lines.extend(md_table(
        ["field", "value"],
        [
            ["asset", snapshot_artifact["asset"]],
            ["timestamp", snapshot_artifact["timestamp"]],
            ["multi_timeframe", ", ".join(tf["interval"] for tf in snapshot_artifact["multi_timeframe"])],
            ["market_regime", snapshot_artifact["market_regime"]],
            ["freshness", snapshot_artifact["data_freshness"]["level"]],
            ["usable", snapshot_artifact["_usable"]],
            ["evidence items", len(snapshot_artifact["evidence"])],
        ],
    ))
    lines.extend([
        "",
        "## Immutable decision record",
        "",
        f"- llm_invoked: {decision['llm_invoked']}",
        f"- illustrative record: {decision['agent_decision_real'] is False}",
        f"- record verified: {decision['record_verified']}",
        f"- hash changes when the decision is altered: {decision['tamper_detection']['hash_changes_on_alteration']}",
        "- tampered indices detected: " + str(decision["tamper_detection"]["detected_indices"]),
        "",
        "## Budget before G3",
        "",
    ])
    lines.extend(md_table(["limit", "value"], [[k, str(v)] for k, v in boundaries["budget_before_g3"].items()]))
    lines.extend([
        "",
        "## Next step",
        "",
        "Authorize a TradingView account so G_TV_CONTEXT can be evaluated against real data.",
        "Until then the gate stays NOT_VERIFIED and no RFC is created.",
        "",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    gate_state = entry_gate()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshot, snapshot_artifact = build_snapshot_artifact(fixture)
    decision = build_decision_artifact(snapshot_artifact["_evidence_snapshot_hash"], snapshot.timestamp)
    boundaries = build_boundaries_artifact()
    gate = build_gate_audit(snapshot_artifact["_validation_problems"], snapshot_artifact["_usable"])
    digest_after = file_digest(ECONOMIC_STATE)
    report = build_final_report(
        gate=gate,
        snapshot_artifact=snapshot_artifact,
        decision=decision,
        boundaries=boundaries,
        economic_state_digest_after=digest_after,
    )
    report["economic_state_unchanged_in_run"] = (
        digest_after == gate_state["economic_state_digest_before"]
    )
    report["entry_gate"] = {
        "branch": gate_state["branch"],
        "head_short": gate_state["head_short"],
        "documents_present": all(doc["present"] for doc in gate_state["documents"]),
        "freeze_seen": gate_state["freeze_seen"],
        "next_alpha_rfc_allowed_seen": gate_state["next_alpha_rfc_allowed_seen"],
    }

    write_json(OUT / "CAP001_MARKET_SNAPSHOT.json", snapshot_artifact)
    write_md(OUT / "CAP001_MARKET_SNAPSHOT.md", render("CAP-001 — MarketSnapshot (synthetic fixture)", snapshot_artifact))
    write_json(OUT / "CAP001_AGENTIC_BOUNDARIES.json", boundaries)
    write_md(OUT / "CAP001_AGENTIC_BOUNDARIES.md", render("CAP-001 — agentic boundaries", boundaries))
    write_json(OUT / "CAP001_GATE_AUDIT.json", gate)
    write_md(OUT / "CAP001_GATE_AUDIT.md", render("CAP-001 — gate audit", gate))
    write_json(OUT / "CAP001_DECISION_RECORD.json", decision)
    write_md(OUT / "CAP001_DECISION_RECORD.md", render("CAP-001 — sealed decision record", decision))
    write_json(OUT / "CAP001_ENTRY_GATE.json", gate_state)

    write_json(DOCS / "AGENTIC_MARKET_INTELLIGENCE_CONTRACT.json", boundaries)
    write_md(DOCS / "AGENTIC_MARKET_INTELLIGENCE_CONTRACT.md", contract_md(boundaries, snapshot_artifact))
    write_md(DOCS / "CAP001_CAPABILITY_SPIKE.md", spike_md(gate, snapshot_artifact, decision, boundaries))

    verification = {
        "status": "PENDING",
        "passed": 0,
        "total": 0,
        "mismatches": 0,
        "false_success": 0,
    }
    write_json(REPORTS / "CAP001_FINAL_REPORT.json", {**report, "verification": verification})
    write_md(REPORTS / "CAP001_FINAL_REPORT.md", final_report_md(report, gate, verification))

    print(f"{ac.SPIKE_ID} {ac.SPIKE_NAME}")
    print(f"entry_condition_met = {report['entry_gate']['documents_present']}")
    print(f"snapshot_valid = {report['snapshot_valid']} usable = {report['snapshot_usable']}")
    print(f"snapshot_source = {report['snapshot_source']}")
    print(f"G_TV_CONTEXT = {report['g_tv_context']}")
    print(f"llm_invoked = {report['llm_invoked']}")
    print(f"immutability_check = {report['immutability_check']}")
    print(f"freeze_unchanged = {report['economic_state_unchanged_in_run']}")
    print(f"hard_stop = {report['hard_stop']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
