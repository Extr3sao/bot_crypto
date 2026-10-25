"""RFC-044 independent verification — profitability reentry watch.

Builder != verifier: this script re-derives every governance invariant from the
*written* artifacts (never importing the RFC-044 module or runner) and checks the
§56 surface: freeze stays ACTIVE, no strategy/backtest/broker/live code, at most
one authorized candidate, registry consistency, decision-ledger consistency,
duplicate-family rejection, the 200-USDT capital contract and unchanged profit
KPIs.  It also confirms §55's exact final-report surface and recomputes §57
FALSE_SUCCESS from scratch.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "reentry-watch"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: Independently re-declared (the verifier must not import the RFC-044 module).
REFERENCE_CAPITAL_USDT = 200.0
VALID_TRIGGER_TYPES = (
    "A_NEW_EXTERNAL_EVIDENCE",
    "B_NEW_STRUCTURAL_MECHANISM",
    "C_MATERIAL_CAPITAL_CHANGE",
    "D_MATERIAL_INSTRUMENT_OR_BROKER_CHANGE",
    "E_NEW_DATA_UNLOCKING_EXISTING_SUPPORTED_HYPOTHESIS",
)
INVALID_EVENT_KINDS = (
    "new_indicator",
    "different_moving_average",
    "different_threshold",
    "different_crypto_symbol",
    "more_agents",
    "llm_prediction",
    "ml_on_old_features",
    "same_family_with_new_name",
    "parameter_tuning",
    "social_media_strategy_claim_alone",
)
SOURCE_QUALITY_LEVELS = ("A", "B", "C", "D")
HIGH_QUALITY_SOURCES = ("A", "B")
POST_PUBLICATION_CLASSES = ("SURVIVES", "WEAKENED", "DECAYED", "CONTRADICTORY", "UNKNOWN")
CRITICAL_GATE_THRESHOLDS = {
    "evidence": 3,
    "business_plausibility": 3,
    "capital_fit": 4,
    "tradability": 4,
    "data_feasibility": 3,
}
MAX_PENDING_OPPORTUNITIES = 10
MAX_DEEP_REVIEW = 2
MAX_AUTHORIZED_CANDIDATES = 1
MAX_PARAMETER_VARIANTS = 1
G_BUSINESS_REENTRY_CONDITIONS = (
    "VALID_TRIGGER",
    "MATERIALLY_NEW",
    "STRONG_EVIDENCE",
    "PRODUCT_FIT",
    "CAPITAL_FIT",
    "TRADABILITY",
    "DATA_FEASIBLE",
    "BENCHMARK_CASE",
    "CHEAP_FALSIFICATION_DEFINED",
)
OPPORTUNITY_FIELDS = (
    "OPPORTUNITY_ID",
    "DATE",
    "SOURCE",
    "CLAIM",
    "MECHANISM",
    "MARKET",
    "INSTRUMENT",
    "CAPITAL_REQUIREMENT",
    "EXPECTED_TURNOVER",
    "KNOWN_COSTS",
    "PRIMARY_BENCHMARK",
    "COUNTER_EVIDENCE",
    "TRIGGER_TYPE",
)
REENTRY_LEASE_FIELDS = (
    "candidate_id",
    "trigger",
    "source_basis",
    "capital",
    "instrument",
    "primary_benchmark",
    "risk_matched_benchmark",
    "cost_model_requirement",
    "fastest_kill_test",
    "max_parameter_variants",
    "expires_on_completion",
)
KILL_TEST_BASES = (
    "external_evidence",
    "arithmetic",
    "product_rules",
    "cost_estimates",
    "data_feasibility",
)
FALSE_SUCCESS_TRIGGERS = (
    "idle_time_treated_as_event",
    "new_strategy_invented",
    "old_family_renamed",
    "weak_source_unlocks_research",
    "capital_constraint_ignored",
    "benchmark_missing",
    "strategy_implemented",
    "freeze_released_without_pass",
    "more_than_one_candidate_authorized",
)
LEDGER_ENTRY_FIELDS = ("review_id", "date", "opportunity", "trigger", "decision", "reason")

REQUIRED_ARTIFACTS = (
    "RFC044_PLAN",
    "CURRENT_REENTRY_STATE",
    "REENTRY_GATE_AUDIT",
    "RFC044_VERIFICATION",
)
TRACKED_PAIRS = (
    "REENTRY_EVIDENCE_REGISTRY",
    "REENTRY_DECISION_LEDGER",
)
TRACKED_SINGLE = ("BUSINESS_REENTRY_CHECKLIST",)

RFC044_CODE_FILES = (
    "src/trading_bot/research/reentry_watch.py",
    "scripts/rfc044_run.py",
    "scripts/rfc044_verify.py",
    "tests/unit/research/test_rfc044_reentry_watch.py",
)
FORBIDDEN_CODE_PATTERNS = (
    r"^\s*class\s+\w*(Strategy|Signal|Portfolio|Backtest|Broker|OrderBook|ExecutionEngine)",
    r"^\s*def\s+(backtest|run_backtest|simulate|place_order|submit_order|generate_signal)\b",
    r"^\s*class\s+\w*PnL",
)

FIRST_LINE = "RFC-044 PROFITABILITY REENTRY WATCH"
REQUIRED_REPORT_FIELDS = (
    "reference_capital_usdt",
    "current_milestone",
    "business_validated_edges",
    "paper_candidates",
    "forward_profitable",
    "live_profitable",
    "realized_trading_pnl",
    "research_freeze",
    "new_qualified_event",
    "g_business_reentry",
    "authorized_candidate",
    "next_alpha_rfc_allowed",
    "next_economic_milestone",
    "next",
)

KPI_TO_STATE = {
    "BUSINESS_VALIDATED_EDGE_COUNT": "BUSINESS_VALIDATED_EDGE_COUNT",
    "PAPER_CANDIDATE_COUNT": "PAPER_CANDIDATE_COUNT",
    "FORWARD_PROFITABLE_COUNT": "FORWARD_PROFITABLE_COUNT",
    "LIVE_PROFITABLE_COUNT": "LIVE_PROFITABLE_COUNT",
}


def git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True, cwd=REPO).strip()
    except Exception:
        return "UNKNOWN"


def is_ancestor(rev: str, head: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", rev, head],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def family_tokens(text: object) -> frozenset[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(text).lower())
    stop = {"the", "a", "an", "and", "or", "of", "for", "in", "to", "with", "strategy", "system"}
    return frozenset(t for t in cleaned.split() if t and t not in stop)


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append({"name": name, "ok": bool(ok), "detail": detail})

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [r for r in self.rows if not r["ok"]]

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r["ok"])


def scan_forbidden_code() -> list[str]:
    hits: list[str] = []
    for rel in RFC044_CODE_FILES:
        path = REPO / rel
        if not path.exists():
            hits.append(f"missing:{rel}")
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in FORBIDDEN_CODE_PATTERNS:
                if re.search(pattern, line):
                    hits.append(f"{rel}:{lineno}:{line.strip()}")
    return hits


def verify() -> tuple[Checks, dict[str, Any], dict[str, Any]]:
    checks = Checks()
    plan = load(OUT / "RFC044_PLAN.json")
    state = load(OUT / "CURRENT_REENTRY_STATE.json")
    audit = load(OUT / "REENTRY_GATE_AUDIT.json")
    registry = load(DOCS / "REENTRY_EVIDENCE_REGISTRY.json")
    ledger = load(DOCS / "REENTRY_DECISION_LEDGER.json")
    report = load(REPORTS / "RFC044_FINAL_REPORT.json")
    economic = load(DOCS / "ECONOMIC_STATE.json")
    archive = load(DOCS / "CANDIDATE_ARCHIVE.json")

    # -- §51/§53/§54 required artifacts -------------------------------------- #
    for name in REQUIRED_ARTIFACTS:
        checks.check(
            f"artifact_present:{name}",
            (OUT / f"{name}.json").exists() and (OUT / f"{name}.md").exists(),
        )
    for name in TRACKED_PAIRS:
        checks.check(
            f"tracked_pair_present:{name}",
            (DOCS / f"{name}.json").exists() and (DOCS / f"{name}.md").exists(),
        )
    for name in TRACKED_SINGLE:
        checks.check(f"tracked_doc_present:{name}", (DOCS / f"{name}.md").exists())
    checks.check("inbox_present", (DOCS / "reentry-inbox" / "README.md").exists())
    checks.check(
        "final_report_present",
        (REPORTS / "RFC044_FINAL_REPORT.json").exists()
        and (REPORTS / "RFC044_FINAL_REPORT.md").exists(),
    )

    # -- §1 entry gate -------------------------------------------------------- #
    head = git("HEAD")
    checks.check("entry:rfc042_is_ancestor", is_ancestor("03ce3f1", head), f"head={head}")
    checks.check("entry:rfc043_is_ancestor", is_ancestor("ecb4c5c", head), f"head={head}")
    checks.check("entry:condition_met", plan["entry_gate"]["entry_condition_met"] is True)
    checks.check(
        "entry:documents_read",
        len(plan["entry_gate"]["documents_read"]) >= 6,
        f"read={len(plan['entry_gate']['documents_read'])}",
    )
    checks.check("entry:hard_rule_ok", plan["entry_gate"]["hard_rule_ok"] is True)

    # -- §5/§6 events --------------------------------------------------------- #
    checks.check(
        "plan:valid_triggers_complete",
        tuple(plan["valid_triggers"].keys()) == VALID_TRIGGER_TYPES,
    )
    checks.check(
        "plan:invalid_events_complete",
        tuple(plan["invalid_events"]) == INVALID_EVENT_KINDS,
    )
    checks.check(
        "plan:source_quality_complete",
        tuple(plan["source_quality"].keys()) == SOURCE_QUALITY_LEVELS,
    )
    checks.check(
        "plan:post_publication_classes",
        tuple(plan["post_publication_classes"]) == POST_PUBLICATION_CLASSES,
    )

    # -- §18 critical gates --------------------------------------------------- #
    checks.check(
        "plan:critical_gates",
        {k: int(v) for k, v in plan["critical_gates"].items()} == CRITICAL_GATE_THRESHOLDS,
    )

    # -- §19-§21/§25 budgets -------------------------------------------------- #
    checks.check(
        "plan:budgets",
        int(plan["budgets"]["MAX_PENDING_OPPORTUNITIES"]) == MAX_PENDING_OPPORTUNITIES
        and int(plan["budgets"]["MAX_DEEP_REVIEW"]) == MAX_DEEP_REVIEW
        and int(plan["budgets"]["MAX_AUTHORIZED_CANDIDATES"]) == MAX_AUTHORIZED_CANDIDATES
        and int(plan["budgets"]["MAX_PARAMETER_VARIANTS"]) == MAX_PARAMETER_VARIANTS,
        f"{plan['budgets']}",
    )

    # -- §22 gate conditions -------------------------------------------------- #
    checks.check(
        "plan:gate_conditions_complete",
        tuple(plan["g_business_reentry_conditions"]) == G_BUSINESS_REENTRY_CONDITIONS,
    )

    # -- §16 kill tests ------------------------------------------------------- #
    checks.check("plan:kill_test_bases", tuple(plan["kill_test_bases"]) == KILL_TEST_BASES)

    # -- §41-§42 no daemon / no schedule ------------------------------------- #
    no_daemon = plan["no_daemon"]
    checks.check(
        "plan:no_daemon_no_schedule",
        no_daemon["daemon_allowed"] is False
        and no_daemon["scheduled_alpha_search_allowed"] is False
        and no_daemon["reentry_mode"] == "EVENT_DRIVEN",
    )

    # -- §60 hard stop -------------------------------------------------------- #
    checks.check("plan:hard_stop_declared", "RFC-045" in plan["hard_stop"])

    # -- §45/§47/§48 current state ------------------------------------------- #
    checks.check(
        "state:capital_is_200",
        float(state["reference_capital_usdt"]) == REFERENCE_CAPITAL_USDT == 200.0,
    )
    checks.check(
        "state:freeze_active",
        state["alpha_research_freeze"] == "ACTIVE",
        f"freeze={state['alpha_research_freeze']}",
    )
    checks.check("state:new_qualified_event_no", state["new_qualified_event"] == "NO")
    checks.check(
        "state:no_action",
        state["decision"]["decision"] == "NO_ACTION"
        and state["decision"]["authorized_candidate"] == "NONE"
        and state["decision"]["next"] == "WAIT"
        and state["decision"]["next_alpha_rfc_allowed"] == "NO",
        f"{state['decision']}",
    )
    checks.check("state:active_candidates_zero", int(state["active_candidates"]) == 0)
    checks.check(
        "state:profit_kpis_zero",
        all(int(v) == 0 for v in state["profit_kpis"].values()),
        f"{state['profit_kpis']}",
    )

    # -- §48 profit KPIs unchanged vs canonical economic state --------------- #
    kpi_ok = all(
        int(state["profit_kpis"][mine]) == int(economic["kpi"][theirs])
        for mine, theirs in KPI_TO_STATE.items()
    )
    checks.check("state:profit_kpis_unchanged_vs_economic_state", kpi_ok)

    # -- §22/§23 gate audit --------------------------------------------------- #
    checks.check(
        "audit:not_evaluated",
        audit["G_BUSINESS_REENTRY"] == "NOT_EVALUATED",
        f"{audit['G_BUSINESS_REENTRY']}",
    )
    checks.check(
        "audit:absent_opportunity_fails",
        audit["gate_result_for_absent_opportunity"]["G_BUSINESS_REENTRY"] == "FAIL"
        and len(audit["gate_result_for_absent_opportunity"]["failing_conditions"])
        == len(G_BUSINESS_REENTRY_CONDITIONS),
    )
    checks.check("audit:no_runner_up", audit["no_runner_up"] is True)
    checks.check("audit:profit_kpis_unchanged", audit["profit_kpis_unchanged"] is True)
    checks.check("audit:capital_respected", audit["capital_respected"] is True)

    # -- §36/§37 registry consistency ---------------------------------------- #
    checks.check(
        "registry:item_fields_declared",
        all(
            f in registry["required_item_fields"]
            for f in ("citation", "url", "claim", "summary", "counter_evidence", "retrieval_date")
        )
        and isinstance(registry["items"], list),
    )
    checks.check(
        "registry:empty_and_consistent",
        registry["items"] == [],
        f"items={len(registry['items'])}",
    )
    checks.check(
        "registry:no_bulk_copies_note",
        "never bulk copies" in registry["description"],
    )

    # -- §38/§39 ledger consistency ------------------------------------------ #
    entries = ledger["entries"]
    checks.check(
        "ledger:entries_have_fields",
        all(all(str(e.get(f, "")).strip() for f in LEDGER_ENTRY_FIELDS) for e in entries),
    )
    by_id = {str(e["review_id"]): e for e in entries}
    checks.check("ledger:rfc042_no_reentry", by_id.get("RFC042", {}).get("decision") == "NO_REENTRY")
    checks.check("ledger:rfc044_no_action", by_id.get("RFC044", {}).get("decision") == "NO_ACTION")

    # -- §14 duplicate-family rejection (independent) ------------------------ #
    archived = {str(c["candidate_id"]): family_tokens(c.get("family", "")) for c in archive["candidates"]}
    registry_families = {family_tokens(i.get("MECHANISM", "")) for i in registry["items"]}
    rehash = any(tokens and tokens in set(archived.values()) for tokens in registry_families)
    checks.check(
        "duplicate:no_rehash_registered",
        not rehash,
        f"archived_families={len(archived)}",
    )
    checks.check(
        "duplicate:archive_loaded",
        len(archived) >= 8,
        f"candidates={len(archived)}",
    )

    # -- §56 no strategy / no backtest / no broker / no live ----------------- #
    hits = scan_forbidden_code()
    checks.check("code:no_strategy_backtest_broker", not hits, ";".join(hits))
    checks.check(
        "code:no_live_authorization",
        float(state.get("reference_capital_usdt", 0.0)) == 200.0
        and int(economic.get("live_capital_authorized", 0)) == 0,
    )

    # -- §21 one-candidate maximum ------------------------------------------- #
    checks.check(
        "lease:one_candidate_max",
        int(plan["budgets"]["MAX_AUTHORIZED_CANDIDATES"]) == 1
        and int(plan["budgets"]["MAX_PARAMETER_VARIANTS"]) == 1
        and int(state["authorized_candidates"]) <= 1,
    )

    # -- §55 final report surface -------------------------------------------- #
    md_path = REPORTS / "RFC044_FINAL_REPORT.md"
    first_line = md_path.read_text(encoding="utf-8").splitlines()[0] if md_path.exists() else ""
    checks.check("report:first_line_exact", first_line == FIRST_LINE, f"{first_line!r}")
    missing = [f for f in REQUIRED_REPORT_FIELDS if f not in report]
    checks.check("report:fields_present", not missing, f"missing={missing}")
    checks.check(
        "report:values",
        report["new_qualified_event"] == "NO"
        and report["g_business_reentry"] == "NOT_EVALUATED"
        and report["authorized_candidate"] == "NONE"
        and report["next_alpha_rfc_allowed"] == "NO"
        and report["next"] == "WAIT"
        and report["current_milestone"] == "M0",
        f"{report.get('authorized_candidate')}/{report.get('next')}",
    )
    checks.check(
        "report:milestone_0_to_1",
        report["next_economic_milestone"] == "BUSINESS_VALIDATED_EDGE 0 -> 1",
    )
    checks.check("report:hard_stop", "RFC-045" in report["hard_stop"])

    # -- §57 FALSE_SUCCESS recomputed independently -------------------------- #
    fs_claims = {
        "idle_time_treated_as_event": state["new_qualified_event"] == "YES",
        "new_strategy_invented": bool(hits),
        "old_family_renamed": bool(rehash),
        "weak_source_unlocks_research": any(
            str(i.get("source_quality", "")).upper() in ("C", "D")
            and str(i.get("decision", "")) == "REENTRY"
            for i in registry["items"]
        ),
        "capital_constraint_ignored": float(state["reference_capital_usdt"]) != 200.0,
        "benchmark_missing": any(
            not str(i.get("PRIMARY_BENCHMARK", "")).strip() for i in registry["items"]
        ),
        "strategy_implemented": bool(hits),
        "freeze_released_without_pass": state["alpha_research_freeze"] != "ACTIVE"
        and audit["G_BUSINESS_REENTRY"] != "PASS",
        "more_than_one_candidate_authorized": int(state["authorized_candidates"]) > 1,
    }
    false_success = sum(1 for v in fs_claims.values() if v)
    checks.check("false_success:zero", false_success == 0, f"FALSE_SUCCESS={false_success}")

    verification = {
        "rfc": "RFC-044",
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "VERIFICATION_STATUS": "PASS" if not checks.failed else "FAIL",
        "checks_total": checks.total,
        "checks_passed": checks.passed,
        "mismatch_count": len(checks.failed),
        "critical_fails": [r["name"] for r in checks.failed],
        "false_success_claims": fs_claims,
        "false_success": false_success,
        "details": checks.rows,
        "source_commit": report.get("source_commit", ""),
    }
    return checks, verification, report


def render(title: str, payload: Any) -> str:
    def walk(value: Any, indent: int) -> list[str]:
        pad = "  " * indent
        out: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    out.append(f"{pad}- **{key}**:")
                    out.extend(walk(item, indent + 1))
                else:
                    out.append(f"{pad}- **{key}**: {item}")
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    first = True
                    for key, sub in item.items():
                        marker = f"{pad}- " if first else f"{pad}  "
                        if isinstance(sub, (dict, list)):
                            out.append(f"{marker}**{key}**:")
                            out.extend(walk(sub, indent + 1))
                        else:
                            out.append(f"{marker}**{key}**: {sub}")
                        first = False
                else:
                    out.append(f"{pad}- {item}")
        else:
            out.append(f"{pad}{value}")
        return out

    return "\n".join([f"# {title}", "", *walk(payload, 0), ""])


def final_md(report: dict[str, Any]) -> str:
    lines = [
        FIRST_LINE,
        "",
        f"REFERENCE CAPITAL = {int(report['reference_capital_usdt'])} USDT",
        "",
        f"CURRENT MILESTONE = {report['current_milestone']}",
        "",
        f"BUSINESS VALIDATED EDGES = {report['business_validated_edges']}",
        "",
        f"PAPER CANDIDATES = {report['paper_candidates']}",
        "",
        f"FORWARD PROFITABLE = {report['forward_profitable']}",
        "",
        f"LIVE PROFITABLE = {report['live_profitable']}",
        "",
        f"REALIZED TRADING PNL = {report['realized_trading_pnl']}",
        "",
        f"RESEARCH FREEZE = {report['research_freeze']}",
        "",
        f"NEW QUALIFIED EVENT = {report['new_qualified_event']}",
        "",
        f"G_BUSINESS_REENTRY = {report['g_business_reentry']}",
        "",
        f"AUTHORIZED CANDIDATE = {report['authorized_candidate']}",
        "",
        f"NEXT ALPHA RFC ALLOWED = {report['next_alpha_rfc_allowed']}",
        "",
        f"NEXT ECONOMIC MILESTONE = {report['next_economic_milestone']}",
        "",
        f"NEXT = {report['next']}",
        "",
        f"DECISION = {report['decision']}",
        "",
        f"FALSE_SUCCESS = {report['false_success']}",
        "",
        f"INDEPENDENT VERIFICATION = {report['independent_verification']}",
        "",
        f"HARD STOP = {report['hard_stop']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    checks, verification, report = verify()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RFC044_VERIFICATION.json").write_text(
        json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "RFC044_VERIFICATION.md").write_text(
        render("RFC-044 VERIFICATION (independent)", verification), encoding="utf-8"
    )

    report["independent_verification"] = (
        f"{verification['VERIFICATION_STATUS']} "
        f"{verification['checks_passed']}/{verification['checks_total']}, "
        f"{verification['mismatch_count']} mismatches"
    )
    report["false_success"] = verification["false_success"]
    report["final_commit"] = git("HEAD")
    (REPORTS / "RFC044_FINAL_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (REPORTS / "RFC044_FINAL_REPORT.md").write_text(final_md(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "VERIFICATION_STATUS": verification["VERIFICATION_STATUS"],
                "checks": f"{verification['checks_passed']}/{verification['checks_total']}",
                "mismatch_count": verification["mismatch_count"],
                "FALSE_SUCCESS": verification["false_success"],
                "failed": verification["critical_fails"],
            },
            indent=2,
        )
    )
    return 0 if not checks.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
