"""CAP-001 independent verification — agentic market intelligence capability spike.

Builder != verifier.  This script re-derives every invariant from the *written*
artifacts (never importing the CAP-001 modules or runner) and checks the
integrity surface: freeze untouched, no alpha claim, no RFC created, no trade,
synthetic data never presented as live, read-only MCP tools only, the sealed
decision record recomputed from scratch, honest gate status, zeroed KPIs and an
unchanged ``ECONOMIC_STATE.json``.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "agentic-spike-cap001"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: Independently re-declared (the verifier must not import the CAP-001 modules).
SPIKE_ID = "CAP-001"
SPIKE_NAME = "AGENTIC MARKET INTELLIGENCE CAPABILITY SPIKE"
GOVERNANCE_FRAMING = "CAPABILITY_SPIKE_OUTSIDE_ALPHA_FREEZE"
SNAPSHOT_FIELDS = (
    "timestamp",
    "asset",
    "price_state",
    "multi_timeframe",
    "technical_state",
    "relative_strength",
    "volume_state",
    "market_regime",
    "news",
    "macro_events",
    "evidence",
    "data_freshness",
)
READ_ONLY_TOOLS = (
    "get_ohlcv",
    "get_technicals_rating",
    "run_screener",
    "get_symbol_data",
    "get_symbol_data_batch",
    "get_news",
    "get_economic_data",
    "get_economic_calendar",
    "get_dividends_calendar",
    "get_earnings_calendar",
    "search_symbols",
    "list_watchlists",
    "get_watchlist",
)
WRITE_TOOLS = (
    "create_alert",
    "update_alert",
    "delete_alert",
    "stop_alerts",
    "restart_alerts",
    "create_watchlist",
    "delete_watchlist",
    "add_to_watchlist",
    "remove_from_watchlist",
    "update_watchlist",
)
AUTHORITY_MAP = {
    "tradingview": "INTELLIGENCE_SOURCE",
    "historical_bars": "OUR_DATASETS",
    "fills": "BROKER_OR_EXCHANGE",
    "pnl": "PORTFOLIO_ACCOUNTING",
}
NON_DETERMINISTIC_DOMAINS = (
    "market_interpretation",
    "regime_interpretation",
    "opportunity_detection",
    "news_context_reasoning",
    "evidence_weighting",
    "trade_thesis",
    "no_trade_judgment",
    "confidence",
)
DETERMINISTIC_DOMAINS = (
    "max_risk",
    "max_exposure",
    "position_sizing",
    "capital_allocation_limits",
    "stop_constraints",
    "fees",
    "accounting",
    "pnl",
    "reconciliation",
    "execution_permissions",
)
UNIVERSE_V1 = (
    "BINANCE:BTCUSDT",
    "BINANCE:ETHUSDT",
    "SP:SPX",
    "NASDAQ:NDX",
    "TVC:GOLD",
    "TVC:US10Y",
    "FX:EURUSD",
)
TIMEFRAMES_V1 = ("1h", "4h", "1D")
FORBIDDEN_TIMEFRAMES = ("1m", "5m", "15m", "30m")
EVIDENCE_KINDS = (
    "price_structure",
    "technical",
    "volume",
    "relative_strength",
    "news",
    "macro",
    "fundamental",
)
BUDGET_BEFORE_G3 = {
    "MAX_AI_AGENTS": 2,
    "MAX_TRADINGVIEW_CONNECTORS": 1,
    "MAX_SHADOW_ENGINES": 1,
    "MAX_EVALUATORS": 1,
}
FORBIDDEN_DURING_ROADMAP = (
    "tsmom_campaign",
    "xmom_campaign",
    "rsi_strategy",
    "macd_strategy",
    "mean_reversion",
    "pine_strategy_mining",
    "hyperparameter_optimization",
)
NEW_SOURCE_FILES = (
    "src/trading_bot/research/agentic_contracts.py",
    "src/trading_bot/research/tradingview_mcp_adapter.py",
)
#: Code-shaped patterns the capability spike must never contain.
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
)

CHECKS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"check": name, "passed": bool(ok), "detail": detail})
    return bool(ok)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def main() -> int:
    artifacts = [
        OUT / "CAP001_MARKET_SNAPSHOT.json",
        OUT / "CAP001_AGENTIC_BOUNDARIES.json",
        OUT / "CAP001_GATE_AUDIT.json",
        OUT / "CAP001_DECISION_RECORD.json",
        OUT / "CAP001_ENTRY_GATE.json",
        REPORTS / "CAP001_FINAL_REPORT.json",
        DOCS / "AGENTIC_MARKET_INTELLIGENCE_CONTRACT.json",
        DOCS / "AGENTIC_MARKET_INTELLIGENCE_CONTRACT.md",
        DOCS / "CAP001_CAPABILITY_SPIKE.md",
    ]
    for path in artifacts:
        check(f"artifact present: {path.name}", path.is_file())

    report = load(REPORTS / "CAP001_FINAL_REPORT.json")
    snapshot = load(OUT / "CAP001_MARKET_SNAPSHOT.json")
    boundaries = load(OUT / "CAP001_AGENTIC_BOUNDARIES.json")
    gate = load(OUT / "CAP001_GATE_AUDIT.json")
    decision = load(OUT / "CAP001_DECISION_RECORD.json")
    entry = load(OUT / "CAP001_ENTRY_GATE.json")

    # --- report surface -----------------------------------------------------
    report_md = (REPORTS / "CAP001_FINAL_REPORT.md").read_text(encoding="utf-8").splitlines()
    check(
        "final report starts with the exact spike header",
        report_md[0] == f"{SPIKE_ID} {SPIKE_NAME}",
    )
    check("governance framing", report["governance_framing"] == GOVERNANCE_FRAMING)
    check("freeze stays ACTIVE", report["alpha_research_freeze"] == "ACTIVE")
    check("next alpha RFC stays NO", report["next_alpha_rfc_allowed"] == "NO")
    check("no RFC created", report["rfc_created"] == "NONE")
    check("no alpha claimed", report["alpha_claimed"] == "NONE")
    check("no trade authorized", report["trades_authorized"] == 0)
    check(
        "snapshot contract declares 12 fields",
        report["snapshot_contract_fields"] == len(SNAPSHOT_FIELDS),
    )
    check("multi-timeframe is 1h/4h/1D", report["multi_timeframe"] == list(TIMEFRAMES_V1))

    # --- snapshot -----------------------------------------------------------
    expected_keys = set(SNAPSHOT_FIELDS)
    present = {key for key in snapshot if not key.startswith("_")}
    check(
        "snapshot carries every contract field",
        expected_keys.issubset(present),
        str(sorted(expected_keys - present)),
    )
    check("snapshot has no undeclared top-level field", not (present - expected_keys))
    check("snapshot validation is clean", snapshot["_validation_problems"] == [])
    check("snapshot is marked usable", snapshot["_usable"] is True)
    check("snapshot source is the synthetic fixture", snapshot["_source"] == "SYNTHETIC_FIXTURE")
    check("snapshot is flagged synthetic", snapshot["_synthetic"] is True)
    tf_intervals = [tf["interval"] for tf in snapshot["multi_timeframe"]]
    check("timeframe order matches the contract order", tf_intervals == list(TIMEFRAMES_V1))
    check(
        "no forbidden intraday timeframe present",
        not any(tf in FORBIDDEN_TIMEFRAMES for tf in tf_intervals),
    )
    check("freshness is computed, not asserted", snapshot["data_freshness"]["level"] == "FRESH")
    check(
        "freshness age is consistent with the source timestamps",
        snapshot["data_freshness"]["age_seconds"]
        == snapshot["data_freshness"]["snapshot_at"]
        - snapshot["data_freshness"]["newest_source_at"],
    )
    kinds = {item["kind"] for item in snapshot["evidence"]}
    check(
        "every evidence kind is declared", kinds.issubset(set(EVIDENCE_KINDS)), str(sorted(kinds))
    )
    check(
        "evidence carries an MCP source",
        all(item["source"].startswith("tradingview_mcp.") for item in snapshot["evidence"]),
    )

    # --- MCP surface --------------------------------------------------------
    used = snapshot["_tools_used"]
    check(
        "only read-only MCP tools were used",
        all(tool in READ_ONLY_TOOLS for tool in used),
        str(used),
    )
    check("no write MCP tool was used", not any(tool in WRITE_TOOLS for tool in used))
    check("report records zero write tools", report["write_tools_used"] == [])

    # --- boundaries ---------------------------------------------------------
    check("authority map is exact", boundaries["authority_map"] == AUTHORITY_MAP)
    check(
        "TradingView is not the accounting source of truth",
        boundaries["tradingview_is_accounting_source_of_truth"] is False,
    )
    check(
        "non-deterministic domains are complete",
        tuple(boundaries["non_deterministic_domains"]) == NON_DETERMINISTIC_DOMAINS,
    )
    check(
        "deterministic domains are complete",
        tuple(boundaries["deterministic_domains"]) == DETERMINISTIC_DOMAINS,
    )
    check("LLM sizing is forbidden", boundaries["llm_sizing_forbidden"] is True)
    check("LLM leverage is forbidden", boundaries["llm_leverage_forbidden"] is True)
    check(
        "read-only tool list is exact", tuple(boundaries["read_only_mcp_tools"]) == READ_ONLY_TOOLS
    )
    check("write tool list is exact", tuple(boundaries["write_mcp_tools_forbidden"]) == WRITE_TOOLS)
    check("budget before G3 is exact", boundaries["budget_before_g3"] == BUDGET_BEFORE_G3)
    check(
        "forbidden roadmap list is complete",
        tuple(boundaries["forbidden_during_roadmap"]) == FORBIDDEN_DURING_ROADMAP,
    )
    check(
        "universe has the 7 declared instruments", tuple(boundaries["universe_v1"]) == UNIVERSE_V1
    )
    check(
        "V1 timeframes exclude intraday noise", tuple(boundaries["timeframes_v1"]) == TIMEFRAMES_V1
    )
    check("all three KPIs are zero", all(value == 0 for value in boundaries["kpi_values"].values()))

    # --- decision record ----------------------------------------------------
    check("no LLM was invoked in the spike", decision["llm_invoked"] is False)
    check("the held decision is explicitly illustrative", decision["agent_decision_real"] is False)
    record = decision["records"][0]
    sealed = {
        "timestamp": record["timestamp"],
        "prompt_version": record["prompt_version"],
        "evidence_snapshot_hash": record["evidence_snapshot_hash"],
        "agent_output": record["agent_output"],
        "critic_output": record["critic_output"],
        "decision": record["decision"],
    }
    recomputed = sha256_text(canonical(sealed))
    check("sealed decision hash recomputes", recomputed == record["decision_hash"])
    check(
        "the ledger holds one record",
        report["decision_ledger_records"] == len(decision["records"]) == 1,
    )
    check("immutability check is PASS", report["immutability_check"] == "PASS")
    check(
        "a decision change changes the hash",
        decision["tamper_detection"]["hash_changes_on_alteration"] is True,
    )
    check(
        "the tampered record is detected and the original is not",
        decision["tamper_detection"]["detected_indices"] == [0],
        str(decision["tamper_detection"]["detected_indices"]),
    )
    check(
        "evidence snapshot hash binds the snapshot",
        record["evidence_snapshot_hash"]
        == sha256_text(canonical({key: snapshot[key] for key in SNAPSHOT_FIELDS})),
    )

    # --- gate honesty -------------------------------------------------------
    check("G_TV_CONTEXT is not PASS", gate["status"] != "PASS")
    check("G_TV_CONTEXT is exactly NOT_VERIFIED", gate["status"] == "NOT_VERIFIED")
    check("report agrees on G_TV_CONTEXT", report["g_tv_context"] == gate["status"])
    check(
        "every later gate is NOT_STARTED",
        all(v == "NOT_STARTED" for k, v in gate["gate_statuses"].items() if k != "G0_TV_CONTEXT"),
    )
    check("gate lists the missing credentials", len(gate["blocking_requirements"]) >= 2)
    check(
        "synthetic data is declared in the gate audit",
        gate["contract_checks"]["synthetic_only"] is True,
    )

    # --- economic state untouched ------------------------------------------
    economic = load(DOCS / "ECONOMIC_STATE.json")
    check(
        "freeze is still ACTIVE in the canonical state",
        economic["alpha_research_freeze"] == "ACTIVE",
    )
    check("next_alpha_rfc_allowed is still false", economic["next_alpha_rfc_allowed"] is False)
    check("research status is still paused", economic["research_status"] == "PAUSED")
    check(
        "ECONOMIC_STATE.json digest is unchanged",
        sha256_file(DOCS / "ECONOMIC_STATE.json") == report["economic_state_digest_unchanged"],
    )
    check("entry gate saw the freeze", entry["freeze_seen"] == "ACTIVE")
    check("entry gate saw the RFC block", entry["next_alpha_rfc_allowed_seen"] is False)

    # --- no RFC created -----------------------------------------------------
    rfc045 = sorted(path.name for path in DOCS.rglob("*RFC045*"))
    check("no RFC-045 artifact exists", rfc045 == [], str(rfc045))

    # --- source surface -----------------------------------------------------
    for relative in NEW_SOURCE_FILES:
        path = REPO / relative
        check(f"source present: {relative}", path.is_file())
        text = path.read_text(encoding="utf-8")
        hits = [pattern for pattern in FORBIDDEN_CODE_PATTERNS if re.search(pattern, text)]
        check(f"no forbidden code pattern in {Path(relative).name}", hits == [], str(hits))

    contract_doc = (DOCS / "AGENTIC_MARKET_INTELLIGENCE_CONTRACT.md").read_text(encoding="utf-8")
    check("contract doc names the spike", SPIKE_ID in contract_doc)
    check(
        "contract doc states the freeze",
        "ALPHA_RESEARCH_FREEZE" in contract_doc or "alpha research freeze" in contract_doc.lower(),
    )

    # --- FALSE_SUCCESS (independent recomputation) --------------------------
    false_success: list[str] = []
    if gate["status"] == "PASS" and snapshot["_synthetic"]:
        false_success.append("G_TV_CONTEXT claimed PASS on synthetic data")
    if any(value != 0 for value in boundaries["kpi_values"].values()):
        false_success.append("a profit KPI was raised off zero")
    if any(tool in WRITE_TOOLS for tool in used):
        false_success.append("a write MCP tool was used")
    if report["alpha_claimed"] != "NONE":
        false_success.append("alpha was claimed")
    if report["rfc_created"] != "NONE":
        false_success.append("an RFC was created")
    if recomputed != record["decision_hash"]:
        false_success.append("an unsealed/tampered decision record was accepted")
    if report["snapshot_source"] != "SYNTHETIC_FIXTURE" and snapshot["_synthetic"]:
        false_success.append("synthetic data was relabelled as real")
    if sha256_file(DOCS / "ECONOMIC_STATE.json") != report["economic_state_digest_unchanged"]:
        false_success.append("the canonical economic state was modified")
    if rfc045:
        false_success.append("RFC-045 exists despite the freeze")

    passed = sum(1 for entry in CHECKS if entry["passed"])
    total = len(CHECKS)
    mismatches = [entry for entry in CHECKS if not entry["passed"]]
    status = "PASS" if not mismatches and not false_success else "FAIL"

    payload = {
        "spike": f"{SPIKE_ID} {SPIKE_NAME}",
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
    (OUT / "CAP001_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        f"{SPIKE_ID} INDEPENDENT VERIFICATION",
        "",
        f"STATUS = {status}",
        f"CHECKS = {passed}/{total}",
        f"MISMATCHES = {len(mismatches)}",
        f"FALSE_SUCCESS = {len(false_success)}",
        "",
    ]
    if mismatches:
        lines.append("## Mismatches")
        lines.append("")
        for bad in mismatches:
            lines.append(f"- {bad['check']} — {bad['detail']}")
        lines.append("")
    if false_success:
        lines.append("## FALSE_SUCCESS")
        lines.append("")
        for trigger in false_success:
            lines.append(f"- {trigger}")
        lines.append("")
    (OUT / "CAP001_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    # Fold the verdict back into the report surface (run -> verify finalises it).
    report["verification"] = {
        "status": status,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "false_success": len(false_success),
        "verifier": "scripts/cap001_verify.py",
    }
    (REPORTS / "CAP001_FINAL_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_md_path = REPORTS / "CAP001_FINAL_REPORT.md"
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

    print(f"{SPIKE_ID} INDEPENDENT VERIFICATION")
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
