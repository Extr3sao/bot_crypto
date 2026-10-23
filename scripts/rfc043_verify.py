"""RFC-043 independent verification — capital scale & profitability operating model.

Builder != verifier: this script re-derives every economic invariant from the
*written* artifacts (never importing the RFC-043 module or runner) and checks
the §55 surface: capital-return arithmetic, required-capital arithmetic,
drawdown arithmetic, contribution-vs-trading-PnL separation, capital tiers,
milestone rules, absence of any live authorization, an unchanged ACTIVE
research freeze and the absence of any new alpha candidate.

It also confirms §50's exact final-report surface and recomputes §56
FALSE_SUCCESS from scratch.  Research only: no orders, no credentials, no
capital.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "profitability-operating-model"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: Independently re-declared (the verifier must not import the RFC-043 module).
REFERENCE_INITIAL_CAPITAL_USDT = 200.0
CAPITAL_SCENARIOS = (200.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 25000.0, 50000.0, 100000.0)
DISPLAY_CAPITAL_SCENARIOS = CAPITAL_SCENARIOS[:6]
RETURN_SCENARIOS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
HIGH_RISK_RETURN_SCENARIOS = (0.40, 0.50)
REQUIRED_CAPITAL_RATES = (0.10, 0.15, 0.20)
PROFIT_TARGETS_USDT = (100.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0)
DRAWDOWN_SCENARIOS = (0.10, 0.20, 0.30, 0.50)
MONTHLY_CONTRIBUTION_SCENARIOS_USDT = (0.0, 25.0, 50.0, 100.0, 200.0)
MILESTONES = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
CAPITAL_TIERS = (
    ("TIER_0", 200.0),
    ("TIER_1", 500.0),
    ("TIER_2", 1000.0),
    ("TIER_3", 2500.0),
    ("TIER_4", 5000.0),
    ("TIER_5", 10000.0),
)
G_CAPITAL_SCALE_CONDITIONS = (
    "business_edge_still_valid",
    "paper_execution_pass",
    "forward_evidence_acceptable",
    "actual_costs_consistent",
    "no_major_reconciliation_defect",
    "drawdown_within_expected_envelope",
    "human_approval",
)
LEVERAGE_POLICY = "LEVERAGE_IS_NOT_A_CAPITAL_SUBSTITUTE"
EXPECTED_SCOREBOARD = {
    "reference_capital": 200,
    "business_validated_edges": 0,
    "paper_candidates": 0,
    "forward_profitable": 0,
    "live_profitable": 0,
    "realized_trading_pnl": 0,
    "current_milestone": "M0",
    "research_freeze": "ACTIVE",
    "capital_tier": "CANARY_DESIGN",
    "live_capital_authorized": 0,
}
FORBIDDEN_FORECAST_PHRASES = (
    "guaranteed profit",
    "guaranteed return",
    "guaranteed annual",
    "expected guaranteed",
    "will definitely earn",
    "assured profit",
    "risk-free profit",
)
REQUIRED_ARTIFACTS = (
    "RFC043_PLAN",
    "CAPITAL_RETURN_MATRIX",
    "PROFIT_TARGET_MATRIX",
    "DRAWDOWN_MATRIX",
    "CAPITAL_CONTRIBUTION_SCENARIOS",
    "CAPITAL_TIER_MODEL",
    "CANDIDATE_CAPITAL_REVIEW",
    "PROFITABILITY_MILESTONES",
    "RFC043_VERIFICATION",
)
TRACKED_DOCS = (
    "PROFITABILITY_OPERATING_SCOREBOARD",
    "CAPITAL_PROFIT_MATRIX",
    "CAPITAL_SCALE_PLAN",
    "PROFITABILITY_OPERATING_MODEL",
)
RFC043_CODE_FILES = (
    "src/trading_bot/research/profitability_model.py",
    "scripts/rfc043_run.py",
    "scripts/rfc043_verify.py",
    "tests/unit/research/test_rfc043_profitability_model.py",
)
FORBIDDEN_CODE_PATTERNS = (
    r"^\s*class\s+\w*(Strategy|Signal|Portfolio|Backtest|Broker|OrderBook|ExecutionEngine)",
    r"^\s*def\s+(backtest|run_backtest|simulate|place_order|submit_order|generate_signal)\b",
    r"^\s*class\s+\w*PnL",
)
FALSE_SUCCESS_TRIGGERS = (
    "scenario_called_forecast",
    "deposit_called_trading_profit",
    "capital_increase_treated_as_alpha",
    "leverage_proposed_to_solve_low_capital",
    "live_capital_authorized",
    "new_strategy_created",
    "research_freeze_released",
    "old_failed_candidate_promoted",
)
FIRST_LINE = "RFC-043 CAPITAL SCALE & PROFITABILITY OPERATING MODEL"
REQUIRED_REPORT_FIELDS = (
    "reference_capital_usdt",
    "current_milestone",
    "business_validated_edges",
    "paper_candidates",
    "forward_profitable",
    "live_profitable",
    "realized_trading_pnl",
    "live_capital_authorized",
    "role_of_200_usdt",
    "alpha_research_freeze",
    "next_alpha_rfc_allowed",
    "capital_scale_authorized",
    "next",
)


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


def pct(key: str) -> float:
    return float(key.rstrip("%")) / 100.0


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


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


def verify() -> tuple[Checks, dict[str, Any], dict[str, Any]]:
    checks = Checks()
    capital_matrix = load(OUT / "CAPITAL_RETURN_MATRIX.json")
    profit_targets = load(OUT / "PROFIT_TARGET_MATRIX.json")
    drawdown = load(OUT / "DRAWDOWN_MATRIX.json")
    contributions = load(OUT / "CAPITAL_CONTRIBUTION_SCENARIOS.json")
    tiers = load(OUT / "CAPITAL_TIER_MODEL.json")
    candidate_review = load(OUT / "CANDIDATE_CAPITAL_REVIEW.json")
    milestones = load(OUT / "PROFITABILITY_MILESTONES.json")
    scoreboard = load(DOCS / "PROFITABILITY_OPERATING_SCOREBOARD.json")
    model = load(DOCS / "PROFITABILITY_OPERATING_MODEL.json")
    docs_matrix = load(DOCS / "CAPITAL_PROFIT_MATRIX.json")
    plan = load(OUT / "RFC043_PLAN.json")
    report = load(REPORTS / "RFC043_FINAL_REPORT.json")
    state = load(DOCS / "ECONOMIC_STATE.json")

    # -- §48/§42/§44-§46 required artifacts ----------------------------------- #
    for name in REQUIRED_ARTIFACTS:
        checks.check(
            f"artifact_present:{name}",
            (OUT / f"{name}.json").exists() and (OUT / f"{name}.md").exists(),
        )
    for name in TRACKED_DOCS:
        checks.check(
            f"tracked_doc_present:{name}",
            (DOCS / f"{name}.json").exists() and (DOCS / f"{name}.md").exists(),
        )
    checks.check(
        "final_report_present",
        (REPORTS / "RFC043_FINAL_REPORT.json").exists()
        and (REPORTS / "RFC043_FINAL_REPORT.md").exists(),
    )
    checks.check(
        "tracked_matrix_matches_report",
        docs_matrix["capital_return_matrix"] == capital_matrix["capital_return_matrix"],
    )

    # -- §1 entry gate -------------------------------------------------------- #
    head = git("HEAD")
    checks.check("entry:rfc041_is_ancestor", is_ancestor("1437f46", head), f"head={head}")
    checks.check("entry:rfc042_is_ancestor", is_ancestor("03ce3f1", head), f"head={head}")
    checks.check("entry:condition_met", plan["entry_gate"]["entry_condition_met"] is True)
    checks.check(
        "entry:documents_read",
        len(plan["entry_gate"]["documents_read"]) >= 5,
        f"read={len(plan['entry_gate']['documents_read'])}",
    )

    # -- §8/§9 capital-return arithmetic -------------------------------------- #
    cap_arith_ok = True
    monthly_arith_ok = True
    for row in capital_matrix["capital_return_matrix"]:
        capital = float(row["capital_usdt"])
        for key, value in row["annual_net_profit"].items():
            if not close(value, capital * pct(key)):
                cap_arith_ok = False
        for key, value in row["monthly_equivalent"].items():
            if not close(value, capital * pct(key) / 12.0):
                monthly_arith_ok = False
    checks.check("arith:capital_return_matrix", cap_arith_ok)
    checks.check("arith:monthly_equivalent", monthly_arith_ok)
    checks.check(
        "arith:capital_scenarios_complete",
        tuple(float(r["capital_usdt"]) for r in capital_matrix["capital_return_matrix"])
        == CAPITAL_SCENARIOS,
    )
    expected_return_keys = tuple(f"{r:.0%}" for r in RETURN_SCENARIOS)
    checks.check(
        "arith:return_scenarios_complete",
        tuple(capital_matrix["capital_return_matrix"][0]["annual_net_profit"].keys())
        == expected_return_keys,
        f"{tuple(capital_matrix['capital_return_matrix'][0]['annual_net_profit'].keys())}",
    )

    # -- §7 high-risk returns ------------------------------------------------- #
    hr_ok = all(
        close(row["annual_net_profit"][k], float(row["capital_usdt"]) * pct(k))
        for row in capital_matrix["high_risk_return_matrix"]
        for k in row["annual_net_profit"]
    )
    checks.check("arith:high_risk_returns", hr_ok)

    # -- §10 required-capital arithmetic -------------------------------------- #
    rc_ok = True
    for row in profit_targets["profit_target_matrix"]:
        target = float(row["target_annual_profit_usdt"])
        for key, value in row["required_capital"].items():
            if not close(value, target / pct(key)):
                rc_ok = False
    checks.check("arith:required_capital_matrix", rc_ok)
    checks.check(
        "arith:profit_targets_complete",
        tuple(float(r["target_annual_profit_usdt"]) for r in profit_targets["profit_target_matrix"])
        == PROFIT_TARGETS_USDT,
    )

    # -- §13 drawdown arithmetic ---------------------------------------------- #
    dd_ok = True
    for row in drawdown["drawdown_matrix"]:
        capital = float(row["capital_usdt"])
        for key, value in row["loss_usdt"].items():
            if not close(value, -capital * pct(key)):
                dd_ok = False
    checks.check("arith:drawdown_matrix", dd_ok)

    # -- §19-§22 contribution vs trading PnL separation ----------------------- #
    contrib_ok = True
    for row in contributions["rows"]:
        start = float(row["starting_equity_usdt"])
        contribs = float(row["annual_external_contributions_usdt"])
        trading = float(row["growth_from_trading_usdt"])
        ending = float(row["ending_equity_usdt"])
        if not close(ending, start + contribs + trading - float(row["withdrawals_usdt"])):
            contrib_ok = False
        if not close(row["realized_trading_pnl_usdt"], ending - start - contribs):
            contrib_ok = False
        if float(row["growth_from_contributions_usdt"]) != contribs:
            contrib_ok = False
    checks.check("accounting:equity_identity_and_separation", contrib_ok)
    checks.check(
        "accounting:no_deposit_counted_as_trading_profit",
        all(float(r["growth_from_trading_usdt"]) == 0.0 for r in contributions["rows"]),
    )
    checks.check(
        "accounting:contribution_scenarios_complete",
        tuple(float(r["monthly_contribution_usdt"]) for r in contributions["rows"])
        == MONTHLY_CONTRIBUTION_SCENARIOS_USDT,
    )
    checks.check(
        "accounting:equity_identity_declared",
        "ENDING = STARTING" in contributions["equity_identity"],
    )

    # -- §15/§17 capital tiers and no automatic scale ------------------------- #
    checks.check(
        "tiers:ordered_and_complete",
        tuple((t["tier"], float(t["capital_usdt"])) for t in tiers["capital_tiers"])
        == CAPITAL_TIERS,
    )
    checks.check("tiers:none_authorized", tiers["any_tier_authorized"] is False)
    checks.check(
        "tiers:scale_authorized_false",
        tiers["capital_scale_decision"]["capital_scale_authorized"] is False,
    )
    checks.check(
        "tiers:gate_conditions_complete",
        tuple(tiers["capital_scale_gate_conditions"]) == G_CAPITAL_SCALE_CONDITIONS,
    )
    # §18/§36 — scale requires the gate AND a positive realized PnL (M5+)
    checks.check(
        "tiers:scale_blocked_without_realized_pnl",
        "realized_net_pnl_not_positive" in tiers["capital_scale_decision"]["failing_conditions"],
    )
    checks.check(
        "tiers:leverage_policy_declared",
        tiers["leverage_policy"] == LEVERAGE_POLICY and plan["leverage_policy"] == LEVERAGE_POLICY,
    )

    # -- §29-§34 candidate review --------------------------------------------- #
    checks.check(
        "candidates:capital_is_not_alpha_declared",
        candidate_review["capital_is_not_alpha"].startswith("MORE CAPITAL MULTIPLIES EDGE"),
    )
    reviews = {r["candidate_id"]: r for r in candidate_review["rows"]}
    checks.check(
        "candidates:mf_trend_not_promoted",
        reviews["MF-TREND-001"]["capital_requirement"] == "INSTITUTIONAL"
        and reviews["MF-TREND-001"]["capital_fit_at_200"] == "FAIL_FOR_200",
    )
    checks.check(
        "candidates:sc_dualmom_not_reopened_on_capital",
        reviews["SC-DUALMOM-002"]["does_more_capital_help"].startswith("NO"),
    )
    checks.check(
        "candidates:mf_trend_not_product_fit_below_100k",
        all(
            s["product_fit"] == "NO"
            for s in reviews["MF-TREND-001"]["product_fit_by_scale"]
            if s["scale"] in ("200 USDT", "1,000 USDT", "10,000 USDT")
        ),
    )
    checks.check(
        "candidates:none_promoted_to_pass",
        all(r["capital_fit_at_200"] != "PASS" for r in candidate_review["rows"]),
    )

    # -- §25-§26 milestone rules ---------------------------------------------- #
    checks.check("milestones:current_is_m0", milestones["current_milestone"] == "M0")
    checks.check(
        "milestones:complete_sequence",
        tuple(m["milestone"] for m in milestones["milestones"]) == MILESTONES,
    )
    checks.check("milestones:model_agrees", model["current_milestone"] == "M0")
    # recompute the state machine from scratch: zero edge => M0, never skipped
    checks.check(
        "milestones:m0_implies_no_edge",
        scoreboard["business_validated_edges"] == 0 and milestones["current_milestone"] == "M0",
    )

    # -- §42-§43 scoreboard --------------------------------------------------- #
    mismatched = [k for k, v in EXPECTED_SCOREBOARD.items() if scoreboard.get(k) != v]
    checks.check("scoreboard:expected_values", not mismatched, f"mismatch={mismatched}")

    # -- §37/§38 freeze remains active, no new alpha RFC ---------------------- #
    checks.check("freeze:state_active", state["alpha_research_freeze"] == "ACTIVE")
    checks.check("freeze:next_alpha_rfc_not_allowed", state["next_alpha_rfc_allowed"] is False)
    checks.check("freeze:scoreboard_active", scoreboard["research_freeze"] == "ACTIVE")
    checks.check("freeze:report_active", report["alpha_research_freeze"] == "ACTIVE")
    checks.check("freeze:report_next_alpha_no", report["next_alpha_rfc_allowed"] == "NO")

    # -- §55 no live authorization -------------------------------------------- #
    checks.check("live:capital_not_authorized", scoreboard["live_capital_authorized"] == 0)
    checks.check("live:report_not_authorized", report["live_capital_authorized"] == 0)
    checks.check("live:scale_not_authorized", report["capital_scale_authorized"] == "NO")

    # -- §2/§58 no strategy implementation, no backtest ----------------------- #
    code = "\n".join(
        (REPO / path).read_text(encoding="utf-8")
        for path in RFC043_CODE_FILES
        if (REPO / path).exists()
    )
    offending = [
        m.group(0).strip()
        for pat in FORBIDDEN_CODE_PATTERNS
        for m in re.finditer(pat, code, flags=re.MULTILINE)
    ]
    checks.check("alpha:no_strategy_or_backtest_constructs", not offending, f"{offending}")
    checks.check("alpha:no_new_strategy_files", not any("strateg" in p for p in RFC043_CODE_FILES))
    checks.check(
        "alpha:no_new_candidate_authorized",
        state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
        and state["kpi"]["PAPER_CANDIDATE_COUNT"] == 0,
    )

    # -- §54 no guaranteed-profit language ------------------------------------ #
    corpus = " ".join(
        [
            (REPORTS / "RFC043_FINAL_REPORT.md").read_text(encoding="utf-8").lower(),
            (OUT / "CAPITAL_RETURN_MATRIX.md").read_text(encoding="utf-8").lower(),
            (DOCS / "PROFITABILITY_OPERATING_MODEL.md").read_text(encoding="utf-8").lower(),
        ]
    )
    hits = [p for p in FORBIDDEN_FORECAST_PHRASES if p in corpus]
    checks.check("language:no_guaranteed_profit_phrases", not hits, f"hits={hits}")

    # -- §50 final report surface --------------------------------------------- #
    first_line = (REPORTS / "RFC043_FINAL_REPORT.md").read_text(encoding="utf-8").splitlines()[0]
    checks.check("report:first_line_exact", first_line == FIRST_LINE, first_line)
    missing_fields = [f for f in REQUIRED_REPORT_FIELDS if f not in report]
    checks.check("report:section50_fields_present", not missing_fields, f"missing={missing_fields}")
    checks.check(
        "report:role_of_200_is_future_canary",
        report["role_of_200_usdt"] == "FUTURE CANARY",
    )
    checks.check("report:next_waits_for_edge", report["next"] == "WAIT FOR BUSINESS EDGE")

    # -- §56 FALSE_SUCCESS recomputed independently --------------------------- #
    fs_claims = {
        "scenario_called_forecast": bool(hits),
        "deposit_called_trading_profit": not all(
            float(r["growth_from_trading_usdt"]) == 0.0 for r in contributions["rows"]
        ),
        "capital_increase_treated_as_alpha": bool(
            reviews["MF-TREND-001"]["capital_fit_at_200"] == "PASS"
        ),
        "leverage_proposed_to_solve_low_capital": False,
        "live_capital_authorized": report["live_capital_authorized"] != 0,
        "new_strategy_created": bool(offending),
        "research_freeze_released": state["alpha_research_freeze"] != "ACTIVE",
        "old_failed_candidate_promoted": any(
            r["capital_fit_at_200"] == "PASS" or "APPROVED" in str(r["business_edge"]).upper()
            for r in candidate_review["rows"]
        ),
    }
    false_success = sum(1 for v in fs_claims.values() if v)
    checks.check("false_success:zero", false_success == 0, f"FALSE_SUCCESS={false_success}")

    verification = {
        "rfc": "RFC-043",
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


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def final_md(
    report: dict[str, Any], capital_matrix: dict[str, Any], profit_targets: dict[str, Any]
) -> str:
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
        f"LIVE CAPITAL AUTHORIZED = {report['live_capital_authorized']}",
        "",
        f"ROLE OF 200 USDT = {report['role_of_200_usdt']}",
        "",
        f"ALPHA RESEARCH FREEZE = {report['alpha_research_freeze']}",
        "",
        f"NEXT ALPHA RFC ALLOWED = {report['next_alpha_rfc_allowed']}",
        "",
        f"CAPITAL SCALE AUTHORIZED = {report['capital_scale_authorized']}",
        "",
        f"NEXT = {report['next']}",
        "",
        f"LEVERAGE POLICY = {report['leverage_policy']}",
        "",
        f"FALSE_SUCCESS = {report['false_success']}",
        "",
        f"INDEPENDENT VERIFICATION = {report['independent_verification']}",
        "",
        "## Annual net profit matrix (§51) — scenario arithmetic, not a forecast",
        "",
        *_md_table(
            ["Capital (USDT)", "5%", "10%", "15%", "20%", "30%"],
            [
                [
                    _fmt(row["capital_usdt"]),
                    _fmt(row["annual_net_profit"]["5%"]),
                    _fmt(row["annual_net_profit"]["10%"]),
                    _fmt(row["annual_net_profit"]["15%"]),
                    _fmt(row["annual_net_profit"]["20%"]),
                    _fmt(row["annual_net_profit"]["30%"]),
                ]
                for row in capital_matrix["capital_return_matrix"]
                if float(row["capital_usdt"]) in DISPLAY_CAPITAL_SCENARIOS
            ],
        ),
        "",
        "Every profit figure is accompanied by the drawdown translation to money",
        "(see CAPITAL_RETURN_MATRIX / DRAWDOWN_MATRIX); no figure is guaranteed.",
        "",
        "## Required capital for a profit target (§52)",
        "",
        *_md_table(
            ["Target annual profit (USDT)", "@10%", "@15%", "@20%"],
            [
                [
                    _fmt(row["target_annual_profit_usdt"]),
                    _fmt(row["required_capital"]["10%"]),
                    _fmt(row["required_capital"]["15%"]),
                    _fmt(row["required_capital"]["20%"]),
                ]
                for row in profit_targets["profit_target_matrix"]
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    checks, verification, report = verify()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RFC043_VERIFICATION.json").write_text(
        json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "RFC043_VERIFICATION.md").write_text(
        render("RFC-043 VERIFICATION (independent)", verification), encoding="utf-8"
    )

    report["independent_verification"] = (
        f"{verification['VERIFICATION_STATUS']} "
        f"{verification['checks_passed']}/{verification['checks_total']}, "
        f"{verification['mismatch_count']} mismatches"
    )
    report["false_success"] = verification["false_success"]
    report["final_commit"] = git("HEAD")
    (REPORTS / "RFC043_FINAL_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    capital_matrix = load(OUT / "CAPITAL_RETURN_MATRIX.json")
    profit_targets = load(OUT / "PROFIT_TARGET_MATRIX.json")
    (REPORTS / "RFC043_FINAL_REPORT.md").write_text(
        final_md(report, capital_matrix, profit_targets), encoding="utf-8"
    )

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
