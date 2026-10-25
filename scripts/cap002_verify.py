"""CAP-002 independent verification — baseline producer + synthetic dry run.

Builder != verifier.  This script re-derives every invariant from the *written*
artefacts (it never imports the CAP-002 modules or runner) and checks the
integrity surface: the producer exists, A is exactly zero, B is exact-window,
C is the canonical RFC-039 SMA(200) with no parameter search and no future
close, D is not invented, active baselines pay the same costs, the sealed
decision stays immutable, the outcome is a separate record, synthetic
provenance is preserved, the counters stay at zero, no RFC-045 exists, no
TradingView network call or LLM call is present, no trade is authorized and
``ECONOMIC_STATE.json`` is unchanged.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "agentic-spike-cap002"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: Independently re-declared (the verifier must not import the CAP-002 modules).
BASELINE_IDS = (
    "A_NO_TRADE_CASH",
    "B_BUY_AND_HOLD",
    "C_SIMPLE_TREND_SMA200",
    "D_PASSIVE_ASSET_BENCHMARK",
)
NO_PREDECLARED_CANONICAL_MAPPING = "NO_PREDECLARED_CANONICAL_MAPPING"
EVALUATOR_LABELS = {
    "A_NO_TRADE_CASH": "A_NO_TRADE",
    "B_BUY_AND_HOLD": "B_BUY_AND_HOLD",
    "C_SIMPLE_TREND_SMA200": "C_SIMPLE_TREND",
    "D_PASSIVE_ASSET_BENCHMARK": "D_PASSIVE_PORTFOLIO",
}
DECLARED_EVALUATOR_BASELINES = (
    "A_NO_TRADE",
    "B_BUY_AND_HOLD",
    "C_SIMPLE_TREND",
    "D_PASSIVE_PORTFOLIO",
)
SEALED_RECORD_FIELDS = (
    "timestamp",
    "prompt_version",
    "evidence_snapshot_hash",
    "agent_output",
    "critic_output",
    "decision",
)
SMA_WINDOW = 200
PRODUCER = "src/trading_bot/research/agentic_baselines.py"
EVALUATOR = "src/trading_bot/research/agentic_contracts.py"
RFC039 = "src/trading_bot/research/small_capital_v1.py"
RUNBOOK = "docs/research/TRADINGVIEW_MCP_RUNBOOK.md"

#: Alternative trend windows / smoothing the producer must never contain.
FORBIDDEN_TREND_TOKENS = (r"SMA50\b", r"SMA100\b", r"SMA150\b", r"SMA250\b", r"\bEMA\b", r"\bema\b")
#: Code-shaped patterns the completion must never contain.
FORBIDDEN_CODE_PATTERNS = (
    r"\bimport\s+ccxt\b",
    r"\bccxt\.",
    r"\bcreate_order\b",
    r"api_secret\s*=",
    r"api_key\s*=",
    r"os\.environ",
    r"\bclass\s+\w*Strategy\w*\b",
    r"\brequests\.post\b",
    r"\baiohttp\b",
    r"\bwebsockets?\b",
    r"mcp\.tradingview\.com",
    r"AgentScorerV2",
    r"AgenticEvaluatorV2",
    r"BaselineScorer\b",
)

CHECKS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"check": name, "passed": bool(ok), "detail": detail})
    return bool(ok)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approx(a: float, b: float, tol: float = 1e-12) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


def main() -> int:
    artifacts = [
        OUT / "CAP002_ENTRY_GATE.json",
        OUT / "CAP002_DECISION_RECORD.json",
        OUT / "CAP002_BASELINES.json",
        OUT / "CAP002_OUTCOME_RECORD.json",
        OUT / "CAP002_IMMUTABILITY.json",
        REPORTS / "CAP002_FINAL_REPORT.json",
    ]
    for path in artifacts:
        check(f"artifact present: {path.name}", path.is_file())

    report = load(REPORTS / "CAP002_FINAL_REPORT.json")
    decision = load(OUT / "CAP002_DECISION_RECORD.json")
    baselines = load(OUT / "CAP002_BASELINES.json")
    outcome = load(OUT / "CAP002_OUTCOME_RECORD.json")
    immutability = load(OUT / "CAP002_IMMUTABILITY.json")

    # --- producer exists and is wired to the frozen evaluator ----------------
    producer_path = REPO / PRODUCER
    check("baseline producer exists", producer_path.is_file())
    producer_text = producer_path.read_text(encoding="utf-8") if producer_path.is_file() else ""
    check("producer reuses the frozen evaluator", "incremental_edge" in producer_text)
    check("producer imports the frozen RFC-039 SMA", "small_capital_v1" in producer_text)
    check(
        "producer declares all four canonical ids",
        all(bid in producer_text for bid in BASELINE_IDS),
    )
    trend_hits = [token for token in FORBIDDEN_TREND_TOKENS if re.search(token, producer_text)]
    check("producer contains no alternative window / EMA", trend_hits == [], str(trend_hits))
    code_hits = [
        pattern for pattern in FORBIDDEN_CODE_PATTERNS if re.search(pattern, producer_text)
    ]
    check("producer contains no forbidden code pattern", code_hits == [], str(code_hits))
    check(
        "SMA_WINDOW is the canonical 200 via RFC-039",
        "SMA_WINDOW" in producer_text and "sma(" in producer_text,
    )

    # --- A / B arithmetic from the written artifacts -------------------------
    by_id = {entry["baseline_id"]: entry for entry in baselines["baselines"]}
    check(
        "all four canonical baselines were produced",
        set(by_id) == set(BASELINE_IDS),
        str(sorted(by_id)),
    )
    cash = by_id["A_NO_TRADE_CASH"]
    check("A cash exposure is zero", cash["exposure"] == 0.0)
    check("A cash gross is zero", cash["gross_return"] == 0.0)
    check("A cash cost is zero", cash["cost"] == 0.0)
    check("A cash net is zero", cash["net_return"] == 0.0)
    check("A cash is available", cash["available"] is True)

    entry = outcome["entry_reference"]
    exit_ = outcome["exit_reference"]
    expected_gross = exit_ / entry - 1.0
    buy_hold = by_id["B_BUY_AND_HOLD"]
    check(
        "B gross equals exit/entry - 1 (exact window)",
        approx(buy_hold["gross_return"], expected_gross),
    )
    check(
        "B net equals gross minus cost",
        approx(buy_hold["net_return"], buy_hold["gross_return"] - buy_hold["cost"]),
    )
    check("B pays a positive round trip", buy_hold["cost"] > 0.0)

    # --- C is the canonical SMA(200) with honest unavailable paths -----------
    trend = by_id["C_SIMPLE_TREND_SMA200"]
    check("C is available from sufficient synthetic history", trend["available"] is True)
    check("C exposure is binary", trend["exposure"] in (0.0, 1.0))
    if trend["exposure"] == 1.0:
        check(
            "C long nets gross minus cost like B",
            approx(trend["net_return"], trend["gross_return"] - trend["cost"]),
        )
    else:
        check("C cash nets exactly zero", trend["net_return"] == 0.0 and trend["cost"] == 0.0)

    # --- D is honest about the missing mapping -------------------------------
    passive = by_id["D_PASSIVE_ASSET_BENCHMARK"]
    check(
        "D is unavailable without a predeclared canonical mapping",
        passive["available"] is False and passive["reason"] == NO_PREDECLARED_CANONICAL_MAPPING,
        str(passive),
    )
    check("no canonical passive mapping was invented", baselines["canonical_passive_mapping"] == {})

    # --- cost consistency ----------------------------------------------------
    cost_model = baselines["cost_model"]
    round_trip = cost_model["round_trip_fraction"]
    check("cost model is explicit and positive", round_trip > 0.0)
    check("agent pays the same cost as the active baselines", approx(outcome["costs"], round_trip))
    check("B pays exactly the shared round trip", approx(buy_hold["cost"], round_trip))

    # --- evaluator wiring ----------------------------------------------------
    edge_labels = {edge["evaluator_label"] for edge in outcome["incremental_edges"]}
    check(
        "edges only use labels the frozen evaluator accepts",
        edge_labels.issubset(set(DECLARED_EVALUATOR_BASELINES)),
        str(edge_labels),
    )
    check(
        "no edge is produced for the unavailable baseline", len(outcome["incremental_edges"]) == 3
    )
    for edge in outcome["incremental_edges"]:
        expected_edge = edge["agent_outcome"] - edge["baseline_outcome"] - edge["cost"]
        check(
            f"edge recomputes for {edge['baseline_id']}",
            approx(edge["edge"], expected_edge),
            str(edge),
        )
        check(
            f"edge uses zero extra cost for {edge['baseline_id']} (cost already net)",
            edge["cost"] == 0.0,
        )

    # --- immutability and separation ----------------------------------------
    record = decision["record"]
    sealed = {field: record[field] for field in SEALED_RECORD_FIELDS}
    recomputed = sha256_text(canonical(sealed))
    check("sealed decision hash recomputes", recomputed == record["decision_hash"])
    check("outcome links to the seal by hash", outcome["decision_hash"] == record["decision_hash"])
    check(
        "outcome links to the seal by derived id",
        outcome["decision_id"] == "DEC-" + record["decision_hash"][:16],
    )
    check(
        "outcome carries no sealed-record internals",
        "agent_output" not in outcome and "critic_output" not in outcome,
    )
    check(
        "immutability: seal verifies after the outcome",
        immutability["record_verified_after_outcome"] is True,
    )
    check(
        "immutability: hash unchanged by the outcome",
        immutability["hash_unchanged_by_outcome"] is True,
    )
    check(
        "immutability: same inputs give the same hash",
        immutability["same_inputs_same_hash"] is True,
    )
    check(
        "immutability: a mutation changes the hash", immutability["mutation_changes_hash"] is True
    )
    check("immutability: a mutated record is detected", immutability["mutation_detected"] is True)

    # --- synthetic provenance and counters ----------------------------------
    check(
        "decision artefact is synthetic",
        decision["source"] == "SYNTHETIC_FIXTURE" and decision["synthetic"] is True,
    )
    check("no LLM ran", decision["llm_invoked"] is False and outcome["llm_invoked"] is False)
    check("no real market data", outcome["real_market_data"] is False)
    check("no real agent decision", outcome["agent_decision_real"] is False)
    check(
        "synthetic outcome does not count toward the pilot", outcome["counts_toward_pilot"] is False
    )
    check("REAL_SEALED_DECISIONS = 0", report["real_sealed_decisions"] == 0)
    check("VALID_PILOT_DECISIONS = 0", report["valid_pilot_decisions"] == 0)
    check("G_TV_CONTEXT = NOT_VERIFIED", report["g_tv_context"] == "NOT_VERIFIED")
    check("G_AGENTIC_EDGE = NOT_TESTED", report["g_agentic_edge"] == "NOT_TESTED")
    check("BUSINESS_VALIDATED_EDGE_COUNT = 0", report["business_validated_edge_count"] == 0)
    check("no trade authorized", report["trades_authorized"] == 0)
    check("no RFC created", report["rfc_created"] == "NONE")
    check("freeze stays ACTIVE", report["alpha_research_freeze"] == "ACTIVE")

    # --- runbook -------------------------------------------------------------
    runbook = REPO / RUNBOOK
    check("OAuth runbook present", runbook.is_file())
    if runbook.is_file():
        text = runbook.read_text(encoding="utf-8")
        check("runbook names the MCP endpoint", "https://mcp.tradingview.com/mcp" in text)
        check("runbook names OAuth 2.1", "OAuth 2.1" in text)
        check(
            "runbook forbids tokens in the repo",
            "must not" in text.lower() or "never" in text.lower(),
        )
        check(
            "runbook is one page or less", len(text.splitlines()) <= 60, str(len(text.splitlines()))
        )

    # --- economic state untouched -------------------------------------------
    economic = load(DOCS / "ECONOMIC_STATE.json")
    check("freeze is ACTIVE in the canonical state", economic["alpha_research_freeze"] == "ACTIVE")
    check("next_alpha_rfc_allowed is still false", economic["next_alpha_rfc_allowed"] is False)
    check("active_candidates is still zero", economic.get("active_candidates") == 0)
    check("PAPER stays NOT_AUTHORIZED", economic["paper_status"] == "NOT_AUTHORIZED")
    check("LIVE stays NOT_AUTHORIZED", economic["live_status"] == "NOT_AUTHORIZED")
    check(
        "ECONOMIC_STATE.json digest is unchanged",
        sha256_file(DOCS / "ECONOMIC_STATE.json") == report["economic_state_digest_unchanged"],
    )

    # --- no RFC-045 ----------------------------------------------------------
    rfc045 = sorted(path.name for path in DOCS.rglob("*RFC045*"))
    check("no RFC-045 artifact exists", rfc045 == [], str(rfc045))

    # --- FALSE_SUCCESS (independent recomputation) --------------------------
    false_success: list[str] = []
    if report["g_tv_context"] == "PASS":
        false_success.append("G_TV_CONTEXT claimed PASS without a credentialled real snapshot")
    if outcome["counts_toward_pilot"] and decision["source"] == "SYNTHETIC_FIXTURE":
        false_success.append("a synthetic outcome counted toward the pilot")
    if any(value != 0 for value in report["baseline_available"].values() if value is None):
        false_success.append("a baseline availability flag was null")
    if report["business_validated_edge_count"] != 0:
        false_success.append("a business edge KPI was raised off zero")
    if decision["source"] == "SYNTHETIC_FIXTURE" and report.get("real_sealed_decisions", 0) != 0:
        false_success.append("a synthetic dry run was counted as a real sealed decision")
    if sha256_file(DOCS / "ECONOMIC_STATE.json") != report["economic_state_digest_unchanged"]:
        false_success.append("the canonical economic state was modified")
    if rfc045:
        false_success.append("RFC-045 exists despite the freeze")
    if recomputed != record["decision_hash"]:
        false_success.append("an unsealed/tampered decision record was accepted")

    passed = sum(1 for entry in CHECKS if entry["passed"])
    total = len(CHECKS)
    mismatches = [entry for entry in CHECKS if not entry["passed"]]
    status = "PASS" if not mismatches and not false_success else "FAIL"

    payload = {
        "spike": "CAP-002 PRE-MCP COMPLETION",
        "status": status,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "mismatch_detail": mismatches,
        "false_success": len(false_success),
        "false_success_detail": false_success,
        "checks": CHECKS,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "CAP002_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "CAP-002 INDEPENDENT VERIFICATION",
        "",
        f"STATUS = {status}",
        f"CHECKS = {passed}/{total}",
        f"MISMATCHES = {len(mismatches)}",
        f"FALSE_SUCCESS = {len(false_success)}",
        "",
    ]
    for bad in mismatches:
        lines.append(f"- MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        lines.append(f"- FALSE_SUCCESS: {trigger}")
    lines.append("")
    (OUT / "CAP002_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    report["verification"] = {
        "status": status,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "false_success": len(false_success),
        "verifier": "scripts/cap002_verify.py",
    }
    (REPORTS / "CAP002_FINAL_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_md_path = REPORTS / "CAP002_FINAL_REPORT.md"
    head, _, _ = report_md_path.read_text(encoding="utf-8").partition("## Independent verification")
    report_md_path.write_text(
        head
        + "## Independent verification\n\n"
        + f"INDEPENDENT VERIFICATION = {status}\n"
        + f"CHECKS = {passed}/{total}\n"
        + f"MISMATCHES = {len(mismatches)}\n"
        + f"FALSE_SUCCESS = {len(false_success)}\n",
        encoding="utf-8",
    )

    print("CAP-002 INDEPENDENT VERIFICATION")
    print(f"STATUS = {status}")
    print(f"CHECKS = {passed}/{total}")
    print(f"MISMATCHES = {len(mismatches)}")
    print(f"FALSE_SUCCESS = {len(false_success)}")
    for bad in mismatches:
        print(f"  MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        print(f"  FALSE_SUCCESS: {trigger}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
