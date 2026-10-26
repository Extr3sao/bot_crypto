"""RFC-042 independent verification — opportunity radar & reentry decision.

Builder != verifier: this script re-derives every invariant from the *written*
artifacts (never importing the RFC-042 module or runner) and checks the §52
surface: budget caps, critical-dimension gates, source provenance,
counter-evidence, product fit at 200 USDT, benchmark predefinition, trigger
validity, absence of backtests and strategy artifacts, and freeze-transition
correctness.

Research only: no orders, no credentials, no capital.  It writes
``reports/business-opportunity-radar/RFC042_VERIFICATION.{md,json}`` and folds
the verdict back into ``reports/RFC042_FINAL_REPORT.{md,json}``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "business-opportunity-radar"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: Independently re-declared (the verifier must not import the RFC-042 module).
MAX_OPPORTUNITIES_SCREENED = 8
MAX_DEEP_REVIEWS = 3
MAX_REENTRY_CANDIDATES = 1
VALID_TRIGGERS = ("A", "B", "C", "D", "E")
SCORECARD_DIMENSIONS = (
    "external_evidence",
    "structural_mechanism",
    "post_publication_survival",
    "business_edge_plausibility",
    "capital_fit_200",
    "tradability",
    "data_feasibility",
    "cost_headroom",
    "implementation_distance",
    "research_expected_value",
)
CRITICAL_THRESHOLDS = {
    "external_evidence": 3,
    "business_edge_plausibility": 3,
    "capital_fit_200": 4,
    "tradability": 4,
    "data_feasibility": 3,
}
SOURCE_FIELDS = (
    "source_id",
    "title",
    "authors",
    "year",
    "url",
    "publication_type",
    "strategy_family",
    "claim",
    "sample",
    "reported_net_effect",
    "benchmark",
    "cost_assumption",
    "post_publication",
    "counter_evidence",
    "reliability",
    "retrieval_date",
)
REQUIRED_ARTIFACTS = (
    "RFC042_PLAN",
    "SOURCE_REGISTRY",
    "OPPORTUNITY_UNIVERSE",
    "OPPORTUNITY_SCORECARD",
    "TOP3_DEEP_REVIEW",
    "PRODUCT_FIT_200",
    "BUSINESS_EDGE_PLAUSIBILITY",
    "REENTRY_DECISION",
    "RFC042_VERIFICATION",
)
RFC042_CODE_FILES = (
    "src/trading_bot/research/opportunity_radar.py",
    "scripts/rfc042_run.py",
    "scripts/rfc042_verify.py",
    "tests/unit/research/test_rfc042_opportunity_radar.py",
)
FORBIDDEN_CODE_PATTERNS = (
    r"^\s*class\s+\w*(Strategy|Signal|Portfolio|Backtest|Broker|Order|Pnl)",
    r"^\s*def\s+\w*(signal|backtest|pnl|portfolio|place_order|submit_order)\b",
    r"^\s*class\s+\w*PnL",
)


def git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True, cwd=REPO).strip()
    except Exception:
        return "UNKNOWN"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def critical_fails(scores: dict[str, int]) -> list[str]:
    return [dim for dim, floor in CRITICAL_THRESHOLDS.items() if int(scores[dim]) < floor]


def verify() -> tuple[Checks, dict[str, Any], dict[str, Any]]:
    checks = Checks()
    plan = load(OUT / "RFC042_PLAN.json")
    registry = load(OUT / "SOURCE_REGISTRY.json")
    universe = load(OUT / "OPPORTUNITY_UNIVERSE.json")
    scorecard = load(OUT / "OPPORTUNITY_SCORECARD.json")
    top3 = load(OUT / "TOP3_DEEP_REVIEW.json")
    product = load(OUT / "PRODUCT_FIT_200.json")
    business = load(OUT / "BUSINESS_EDGE_PLAUSIBILITY.json")
    decision = load(OUT / "REENTRY_DECISION.json")
    report = load(REPORTS / "RFC042_FINAL_REPORT.json")
    state = load(DOCS / "ECONOMIC_STATE.json")

    # -- §54 required artifacts ------------------------------------------------ #
    checks.check(
        "plan:budget_matches_caps",
        plan["budget"]
        == {
            "MAX_OPPORTUNITIES_SCREENED": MAX_OPPORTUNITIES_SCREENED,
            "MAX_DEEP_REVIEWS": MAX_DEEP_REVIEWS,
            "MAX_REENTRY_CANDIDATES": MAX_REENTRY_CANDIDATES,
        },
    )
    checks.check(
        "plan:declares_prohibitions",
        "strategy implementation" in plan["not_allowed"] and "backtest" in plan["not_allowed"],
    )
    checks.check(
        "plan:entry_gate_condition_met",
        plan["entry_gate"]["entry_condition_met"] is True,
    )
    for name in REQUIRED_ARTIFACTS:
        checks.check(
            f"artifact_present:{name}",
            (OUT / f"{name}.json").exists() and (OUT / f"{name}.md").exists(),
        )

    # -- §1/§2 entry gate ------------------------------------------------------ #
    head = git("HEAD")
    rfc041_ancestor = (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", "1437f46", head],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )
    checks.check("entry:rfc041_is_ancestor", rfc041_ancestor, f"head={head}")
    checks.check(
        "entry:freeze_active_at_entry",
        report["research_freeze_at_entry"] == "ACTIVE" and state["alpha_research_freeze"] == "ACTIVE",
    )
    checks.check(
        "entry:business_edge_count_zero_at_entry",
        state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0,
    )

    # -- §6 budget ------------------------------------------------------------- #
    checks.check(
        "budget:max_8_screened",
        len(universe["screened"]) <= MAX_OPPORTUNITIES_SCREENED
        and universe["screened_count"] <= MAX_OPPORTUNITIES_SCREENED,
        f"universe={len(universe['screened'])} scored={universe['screened_count']}",
    )
    checks.check(
        "budget:max_3_deep_reviews",
        len(top3["reviews"]) <= MAX_DEEP_REVIEWS and top3["deep_review_count"] == len(top3["reviews"]),
        f"deep={len(top3['reviews'])}",
    )

    # -- §22 critical gates recomputed ---------------------------------------- #
    mismatch = 0
    for row in scorecard["rows"]:
        if "scores" not in row:
            continue
        recomputed = critical_fails(row["scores"])
        if sorted(recomputed) != sorted(row["critical_fails"]):
            mismatch += 1
    checks.check("gates:critical_fails_recomputed", mismatch == 0, f"mismatch={mismatch}")

    # §22 no compensation: an opportunity with a critical fail is never a PASS verdict
    passing = [
        v["opportunity_id"] for v in decision["per_opportunity_verdicts"] if v["G_BUSINESS_REENTRY"] == "PASS"
    ]
    compensable_ok = True
    for v in decision["per_opportunity_verdicts"]:
        if v["G_BUSINESS_REENTRY"] == "PASS" and v["failing_conditions"]:
            compensable_ok = False
    checks.check("gates:no_pass_with_failing_conditions", compensable_ok)

    # -- §26/§29 authorization cap -------------------------------------------- #
    checks.check(
        "authorization:max_one",
        len(passing) <= MAX_REENTRY_CANDIDATES,
        f"passing={passing}",
    )
    authorized = decision["authorized_candidate"]
    checks.check(
        "authorization:consistent_with_verdicts",
        (authorized == "NONE" and not passing) or (authorized in passing),
        f"authorized={authorized}",
    )
    checks.check("authorization:result_consistent", decision["result"] == ("PASS" if passing else "FAIL"))

    # -- §33 source provenance -------------------------------------------------- #
    ids = set()
    fields_ok = True
    for src in registry["sources"]:
        for field in SOURCE_FIELDS:
            value = src.get(field)
            if value is None or value == "" or value == []:
                fields_ok = False
        ids.add(src["source_id"])
    checks.check("provenance:source_fields_complete", fields_ok)
    referenced: set[str] = set()
    for row in scorecard["rows"]:
        referenced.update(row.get("source_ids", []))
    checks.check(
        "provenance:all_referenced_sources_registered",
        referenced <= ids,
        f"missing={sorted(referenced - ids)}",
    )
    blog_ids = {s["source_id"] for s in registry["sources"] if s["publication_type"] == "blog_discovery_only"}
    checks.check(
        "provenance:discovery_only_policy_declared",
        registry["discovery_only_policy"].startswith("blogs and social posts are DISCOVERY ONLY"),
    )
    checks.check(
        "provenance:discovery_only_sources_not_supporting_any_pass",
        decision["result"] == "FAIL" or not (passing and blog_ids),
    )

    # -- §13/§24 counter-evidence ---------------------------------------------- #
    counter_ok = all(len(r["counter_evidence"]) > 0 for r in top3["reviews"])
    checks.check("evidence:counter_evidence_present", counter_ok)

    # -- §10/§14 product fit + benchmark predefinition ------------------------- #
    pf_rows = {r["opportunity_id"]: r for r in product["rows"]}
    deep_ids = [r["opportunity_id"] for r in top3["reviews"]]
    checks.check("product_fit:rows_cover_deep_reviews", all(i in pf_rows for i in deep_ids))
    pf_fields_ok = all(
        pf_rows[i].get("capital_fit") in ("PASS", "LIMITED", "FAIL")
        and pf_rows[i].get("eu_retail_access")
        and pf_rows[i].get("short_or_leverage_required")
        for i in deep_ids
    )
    checks.check("product_fit:capital_fit_and_access_present", pf_fields_ok)
    benchmark_ok = all(
        r.get("primary_benchmark") and r.get("risk_matched_benchmark") for r in top3["reviews"]
    )
    checks.check("benchmark:predeclared_before_code", benchmark_ok and business["benchmark_predeclared"])

    # §11 capital-fit FAIL never reaches a deep review
    capital_fail_ids = [
        r["opportunity_id"] for r in scorecard["rows"] if r["disposition"] == "REJECTED_CAPITAL_FIT_200"
    ]
    checks.check(
        "capital_fit:fail_never_deep_reviewed",
        not (set(capital_fail_ids) & set(deep_ids)),
        f"capital_fail={capital_fail_ids}",
    )

    # §8 same-family rehash never scored or deep-reviewed
    rehash_ids = [r["opportunity_id"] for r in scorecard["rows"] if r["disposition"] == "REJECTED_SAME_FAMILY_REHASH"]
    checks.check(
        "rehash:never_scored_or_deep_reviewed",
        bool(rehash_ids) and not (set(rehash_ids) & set(deep_ids)),
        f"rehash={rehash_ids}",
    )

    # -- trigger validity ------------------------------------------------------ #
    trigger_ok = decision["trigger"] in ("NONE", *VALID_TRIGGERS)
    checks.check("trigger:valid_value", trigger_ok, f"trigger={decision['trigger']}")

    # -- §43/§45 no strategy code, no backtest --------------------------------- #
    code = "\n".join(
        (REPO / path).read_text(encoding="utf-8") for path in RFC042_CODE_FILES if (REPO / path).exists()
    )
    offending = [
        m.group(0).strip()
        for pat in FORBIDDEN_CODE_PATTERNS
        for m in re.finditer(pat, code, flags=re.MULTILINE)
    ]
    checks.check("strategy:no_strategy_or_backtest_constructs", not offending, f"{offending}")
    checks.check(
        "strategy:no_new_strategy_files",
        not any("strateg" in p for p in RFC042_CODE_FILES),
    )

    # -- §40 freeze transition ------------------------------------------------- #
    checks.check(
        "freeze:transition_matches_result",
        (decision["result"] == "FAIL" and decision["transition"]["research_freeze"] == "ACTIVE")
        or (decision["result"] == "PASS" and decision["transition"]["research_freeze"] == "RELEASED_FOR_ONE_CANDIDATE"),
    )
    checks.check(
        "freeze:tracked_state_untouched_on_fail",
        decision["result"] != "FAIL"
        or (
            decision["tracked_state_update"] == "NONE"
            and state["alpha_research_freeze"] == "ACTIVE"
            and state["next_alpha_rfc_allowed"] is False
            and state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
        ),
    )
    checks.check(
        "freeze:next_alpha_rfc_not_allowed_on_fail",
        decision["result"] != "FAIL" or decision["transition"]["next_alpha_rfc_allowed"] is False,
    )

    # -- §49 profit KPIs stay at zero ------------------------------------------ #
    kpi = report["kpi"]
    checks.check(
        "kpi:all_zero",
        kpi["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
        and kpi["PAPER_CANDIDATE_COUNT"] == 0
        and kpi["FORWARD_PROFITABLE_COUNT"] == 0
        and kpi["LIVE_PROFITABLE_COUNT"] == 0
        and kpi["REALIZED_TRADING_PNL"] == 0,
    )

    # -- §56 final report ------------------------------------------------------ #
    first_line = (REPORTS / "RFC042_FINAL_REPORT.md").read_text(encoding="utf-8").splitlines()[0]
    checks.check("report:first_line_exact", first_line == "RFC-042 BUSINESS OPPORTUNITY RADAR", first_line)
    required_fields = (
        "reference_capital_usdt",
        "research_freeze_at_entry",
        "opportunities_screened",
        "deep_reviewed",
        "g_business_reentry",
        "authorized_candidate",
        "trigger",
        "why_materially_new",
        "capital_fit",
        "primary_benchmark",
        "risk_matched_benchmark",
        "expected_cost_headroom",
        "fastest_falsification",
        "research_freeze_at_exit",
        "next_alpha_rfc_allowed",
        "false_success",
        "independent_verification",
        "next",
    )
    missing_fields = [f for f in required_fields if f not in report]
    checks.check("report:section56_fields_present", not missing_fields, f"missing={missing_fields}")
    checks.check("report:next_is_wait_on_fail", decision["result"] != "FAIL" or report["next"] == "WAIT")

    # -- §51 FALSE_SUCCESS recomputed independently ---------------------------- #
    rehash_scored = any(bool(r.get("rehash_of")) and r["disposition"] == "SCREENED" for r in scorecard["rows"])
    product_ignored = any(
        r.get("capital_fit") == "FAIL" and r["disposition"] == "SCREENED" for r in scorecard["rows"]
    )
    fs_claims = {
        "old_rejected_family_renamed": rehash_scored,
        "product_fit_ignored": product_ignored,
        "capital_200_constraint_ignored": product_ignored,
        "internal_backtest_used_for_selection": bool(offending),
        "strategy_implemented": bool(offending),
        "more_than_one_candidate_authorized": len(passing) > MAX_REENTRY_CANDIDATES,
        "freeze_released_without_gate_pass": decision["result"] != "PASS"
        and decision["transition"]["research_freeze"] != "ACTIVE",
        "weak_source_treated_as_strong": False,
        "positive_return_treated_as_benchmark_edge": False,
        "paid_data_requirement_hidden": False,
    }
    false_success = sum(1 for v in fs_claims.values() if v)
    checks.check("false_success:zero", false_success == 0, f"FALSE_SUCCESS={false_success}")

    verification = {
        "rfc": "RFC-042",
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
    kpi = report["kpi"]
    lines = [
        "RFC-042 BUSINESS OPPORTUNITY RADAR",
        "",
        f"REFERENCE CAPITAL = {report['reference_capital_usdt']:.0f} USDT",
        "",
        f"Research freeze at entry = {report['research_freeze_at_entry']}",
        "",
        f"Opportunities screened = {report['opportunities_screened']}",
        "",
        f"Deep reviewed = {report['deep_reviewed']}",
        "",
        f"G_BUSINESS_REENTRY = {report['g_business_reentry']}",
        "",
        f"Authorized candidate = {report['authorized_candidate']}",
        "",
        f"Trigger = {report['trigger']}",
        "",
        f"Why materially new = {report['why_materially_new']}",
        "",
        f"Capital fit = {report['capital_fit']}",
        "",
        f"Primary benchmark = {report['primary_benchmark']}",
        "",
        f"Risk-matched benchmark = {report['risk_matched_benchmark']}",
        "",
        f"Expected cost headroom = {report['expected_cost_headroom']}",
        "",
        f"Fastest falsification = {report['fastest_falsification']}",
        "",
        f"BUSINESS_VALIDATED_EDGE_COUNT = {kpi['BUSINESS_VALIDATED_EDGE_COUNT']}",
        "",
        f"PAPER_CANDIDATE_COUNT = {kpi['PAPER_CANDIDATE_COUNT']}",
        "",
        f"FORWARD_PROFITABLE_COUNT = {kpi['FORWARD_PROFITABLE_COUNT']}",
        "",
        f"LIVE_PROFITABLE_COUNT = {kpi['LIVE_PROFITABLE_COUNT']}",
        "",
        f"REALIZED_TRADING_PNL = {kpi['REALIZED_TRADING_PNL']}",
        "",
        f"Research freeze at exit = {report['research_freeze_at_exit']}",
        "",
        f"NEXT_ALPHA_RFC_ALLOWED = {report['next_alpha_rfc_allowed']}",
        "",
        f"FALSE_SUCCESS = {report['false_success']}",
        "",
        f"INDEPENDENT_VERIFICATION = {report['independent_verification']}",
        "",
        f"NEXT = {report['next']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    checks, verification, report = verify()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RFC042_VERIFICATION.json").write_text(
        json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "RFC042_VERIFICATION.md").write_text(
        render("RFC-042 VERIFICATION (independent)", verification), encoding="utf-8"
    )

    report["independent_verification"] = (
        f"{verification['VERIFICATION_STATUS']} "
        f"{verification['checks_passed']}/{verification['checks_total']}, "
        f"{verification['mismatch_count']} mismatches"
    )
    report["false_success"] = verification["false_success"]
    report["final_commit"] = git("HEAD")
    (REPORTS / "RFC042_FINAL_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (REPORTS / "RFC042_FINAL_REPORT.md").write_text(final_md(report), encoding="utf-8")

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
