"""RFC-035 - INDEPENDENT VERIFIER (builder != verifier, §89).

Deliberately imports NEITHER ``rfc035_run`` NOR ``strategic_profitability_v2``.
It reads the *generated* artifacts under ``reports/profitability-v2/`` plus the
final report and the tracked plan, and independently re-derives:

    source-registry completeness, scorecard arithmetic, critical-dimension rules,
    top-5 derivation, finalist derivation, authorization count <= 2, absence of
    any strategy implementation, G_REENTRY correctness, and canonical status
    consistency.

Then it writes ``RFC035_VERIFICATION.{md,json}``.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "profitability-v2"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

REQUIRED_ARTIFACTS = [
    "RFC035_PLAN",
    "SOURCE_REGISTRY",
    "STRATEGY_UNIVERSE",
    "STRATEGY_SCORECARD",
    "TOP5_REVIEW",
    "DATA_FEASIBILITY_MATRIX",
    "ECONOMIC_HEADROOM_MATRIX",
    "TRADABILITY_MATRIX",
    "POST_PUBLICATION_REVIEW",
    "FINAL_DECISION_MATRIX",
]

SCORECARD_DIMENSIONS = (
    "evidence_strength",
    "economic_headroom",
    "post_publication_survival",
    "data_feasibility",
    "tradability",
    "implementation_simplicity",
    "orthogonality",
    "portability",
)
CRITICAL_DIMENSIONS = ("evidence_strength", "data_feasibility", "tradability")

SOURCE_FIELDS = (
    "source_id",
    "title",
    "authors",
    "publication",
    "year",
    "url",
    "source_type",
    "strategy_family",
    "asset_class",
    "sample",
    "reported_effect",
    "cost_assumption",
    "oos_evidence",
    "post_publication_evidence",
    "independent_replication",
    "reliability",
)

STRONG_SOURCE_TYPES = {
    "peer_reviewed_paper",
    "academic_working_paper",
    "independent_replication",
    "exchange_index_research",
    "established_quant_research",
}

FREE_OR_LOW = {"FREE_EXISTING", "FREE_NEW", "LOW_COST"}
DECISIONS = {
    "AUTHORIZE_P1",
    "AUTHORIZE_P2",
    "WATCHLIST",
    "DEFER_DATA",
    "REJECT_ECONOMICS",
    "REJECT_EVIDENCE",
    "REJECT_TRADABILITY",
    "REJECT_COMPLEXITY",
}

MAX_TOP5, MAX_FINALISTS, MAX_AUTHORIZED = 5, 3, 2


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append({"check": name, "pass": bool(ok), "detail": detail})

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r["pass"])

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [r for r in self.rows if not r["pass"]]

    @property
    def total(self) -> int:
        return len(self.rows)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    except Exception:
        return "UNKNOWN"


def verify() -> dict[str, Any]:
    c = Checks()
    plan = _load(OUT / "RFC035_PLAN.json")
    registry = _load(OUT / "SOURCE_REGISTRY.json")
    scorecard = _load(OUT / "STRATEGY_SCORECARD.json")
    top5 = _load(OUT / "TOP5_REVIEW.json")
    decision = _load(OUT / "FINAL_DECISION_MATRIX.json")
    final = _load(REPORTS / "RFC035_FINAL_REPORT.json")
    tracked_path = DOCS / "STRATEGIC_PROFITABILITY_PLAN_V2.json"
    tracked_exists = tracked_path.exists()
    tracked = _load(tracked_path) if tracked_exists else {}

    # -- artifact presence ------------------------------------------------ #
    missing = [
        name
        for name in REQUIRED_ARTIFACTS
        if not (OUT / f"{name}.md").exists() or not (OUT / f"{name}.json").exists()
    ]
    c.check("all_required_artifacts_present", not missing, f"missing={missing}")
    c.check("final_report_present", (REPORTS / "RFC035_FINAL_REPORT.md").exists())
    c.check("tracked_plan_present", tracked_exists)

    # -- source registry completeness ------------------------------------ #
    sources = registry.get("sources", [])
    incomplete = [
        s.get("source_id")
        for s in sources
        if any(not str(s.get(f, "")).strip() for f in SOURCE_FIELDS)
    ]
    c.check("source_registry_complete_fields", not incomplete, f"incomplete={incomplete}")
    c.check("source_count_sufficient", len(sources) >= 20, f"count={len(sources)}")
    strong_ids = {
        s["source_id"] for s in sources if s.get("source_type") in STRONG_SOURCE_TYPES
    }
    c.check("strong_sources_exist", len(strong_ids) >= 10, f"strong={len(strong_ids)}")
    counter = [s for s in sources if s.get("evidence_role") == "counter"]
    c.check("counter_evidence_present", len(counter) >= 3, f"counter={len(counter)}")

    # -- scorecard arithmetic -------------------------------------------- #
    families = {f["family_id"]: f for f in scorecard.get("families", [])}
    score_ok = True
    for f in families.values():
        for dim in SCORECARD_DIMENSIONS:
            v = f["scores"].get(dim)
            if not isinstance(v, int) or not (0 <= v <= 5):
                score_ok = False
    c.check("scorecard_arithmetic_valid", score_ok)
    c.check(
        "scorecard_dimensions_complete",
        all(set(f["scores"]) == set(SCORECARD_DIMENSIONS) for f in families.values()),
    )

    # -- critical-dimension rules ---------------------------------------- #
    def weak_critical(fid: str) -> list[str]:
        s = families[fid]["scores"]
        return [d for d in CRITICAL_DIMENSIONS if s[d] <= 1]

    top5_ids = top5.get("top5", [])
    finalists = final.get("finalists", [])
    authorized = final.get("authorized_reproductions", [])
    c.check(
        "no_top5_with_weak_critical_dimension",
        all(not weak_critical(fid) for fid in top5_ids),
    )
    c.check(
        "no_finalist_with_weak_critical_dimension",
        all(not weak_critical(fid) for fid in finalists),
    )

    # -- top5 / finalist / authorization derivation ---------------------- #
    eligible = [fid for fid in families if not weak_critical(fid)]
    c.check("top5_size_valid", 1 <= len(top5_ids) <= MAX_TOP5, f"n={len(top5_ids)}")
    c.check("top5_subset_eligible", set(top5_ids) <= set(eligible))
    c.check("finalists_size_valid", 1 <= len(finalists) <= MAX_FINALISTS, f"n={len(finalists)}")
    c.check("finalists_subset_top5", set(finalists) <= set(top5_ids))
    c.check(
        "authorized_within_cap",
        len(authorized) <= MAX_AUTHORIZED,
        f"n={len(authorized)}",
    )
    c.check("authorized_subset_finalists", set(authorized) <= set(finalists))

    # -- decision values exact ------------------------------------------- #
    rows = decision.get("rows", [])
    c.check(
        "decision_values_exact",
        all(r.get("decision") in DECISIONS for r in rows),
        f"values={sorted({r.get('decision') for r in rows})}",
    )

    # -- reentry gate recomputation (independent) ------------------------ #
    headroom = _load(OUT / "ECONOMIC_HEADROOM_MATRIX.json")
    hr_by = {f["family_id"]: f for f in headroom.get("families", [])}
    data_cost = {
        f["family_id"]: f["data_cost_class"]
        for f in _load(OUT / "DATA_FEASIBILITY_MATRIX.json").get("families", [])
    }

    def passes_reentry(fid: str) -> bool:
        s = families[fid]["scores"]
        ratio = hr_by[fid]["headroom_ratio"]
        net_exc = hr_by[fid].get("net_evidence_exception", False)
        return (
            s["evidence_strength"] >= 4
            and ratio is not None
            and (ratio >= 1.5 or net_exc)
            and s["tradability"] >= 3
            and s["data_feasibility"] >= 3
            and data_cost.get(fid) in FREE_OR_LOW
            and s["implementation_simplicity"] >= 3
        )

    qualifying = [fid for fid in families if passes_reentry(fid)]
    expected_gate = "PASS" if qualifying else "FAIL"
    c.check(
        "g_reentry_recomputation_matches",
        final.get("g_reentry") == expected_gate,
        f"declared={final.get('g_reentry')} recomputed={expected_gate}",
    )
    c.check(
        "authorized_only_if_qualifying",
        all(fid in qualifying for fid in authorized),
        f"qualifying={qualifying}",
    )

    # -- canonical status consistency ------------------------------------ #
    status = final.get("current_status")
    c.check(
        "status_paused_or_reentry_approved",
        status in {"PAUSED", "REENTRY_APPROVED"},
        f"status={status}",
    )
    if final.get("g_reentry") == "PASS":
        c.check("pass_implies_reentry_approved", status == "REENTRY_APPROVED")
        c.check("pass_enables_next_alpha_rfc", final.get("next_alpha_rfc_allowed") is True)
    else:
        c.check("fail_keeps_paused", status == "PAUSED")
        c.check("fail_keeps_next_alpha_rfc_false", final.get("next_alpha_rfc_allowed") is False)
    c.check("entry_status_was_paused", plan.get("entry_profitability_research_status") == "PAUSED")
    c.check(
        "phase_1_closed",
        plan.get("phase_1_status") == "CLOSED",
    )

    # -- no implementation created --------------------------------------- #
    marker = final.get("economic_marker", {})
    c.check(
        "economic_marker_execution_zeros",
        all(
            marker.get(k) == 0
            for k in (
                "executable_validated_edge_count",
                "robust_edge_count",
                "paper_candidate_count",
                "forward_profitable_count",
                "live_profitable_count",
            )
        ),
        f"marker={marker}",
    )
    plan_text = (OUT / "RFC035_PLAN.md").read_text(encoding="utf-8").lower()
    forbidden = ["def backtest", "def run_strategy", "realized_pnl", "net_sharpe_ours"]
    c.check(
        "no_implementation_in_artifacts",
        not any(tok in plan_text for tok in forbidden),
    )
    c.check(
        "next_rfc_is_reproduction_not_implemented",
        final.get("next_rfc_type") in {None, "EXTERNAL_STRATEGY_REPRODUCTION"},
    )

    # -- tracked plan consistency ---------------------------------------- #
    if tracked_exists:
        c.check(
            "tracked_plan_gate_matches",
            tracked.get("g_reentry") == final.get("g_reentry"),
        )
        c.check(
            "tracked_plan_top5_matches",
            tracked.get("top5") == final.get("top5"),
        )

    # -- false success --------------------------------------------------- #
    fs = final.get("false_success", -1)
    c.check("false_success_is_zero", fs == 0, f"false_success={fs}")

    result = {
        "rfc": "RFC-035",
        "as_of_commit": _git(),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks_total": c.total,
        "checks_passed": c.passed,
        "checks_failed": len(c.failed),
        "verification_status": "PASS" if not c.failed else "FAIL",
        "false_success": fs if isinstance(fs, int) and fs >= 0 else "UNKNOWN",
        "g_reentry_recomputed": expected_gate,
        "authorized_reproduced": authorized,
        "checks": c.rows,
    }
    return result


def _render_md(result: dict[str, Any]) -> str:
    lines = [
        "# RFC-035 INDEPENDENT VERIFICATION",
        "",
        f"as_of_commit = {result['as_of_commit']}",
        f"generated_at = {result['generated_at']}",
        f"verification_status = {result['verification_status']}",
        f"checks_passed = {result['checks_passed']} / {result['checks_total']}",
        f"checks_failed = {result['checks_failed']}",
        f"false_success = {result['false_success']}",
        f"g_reentry_recomputed = {result['g_reentry_recomputed']}",
        "",
        "| check | pass | detail |",
        "| --- | --- | --- |",
    ]
    for r in result["checks"]:
        lines.append(f"| {r['check']} | {'PASS' if r['pass'] else 'FAIL'} | {r['detail']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    result = verify()
    (OUT / "RFC035_VERIFICATION.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "RFC035_VERIFICATION.md").write_text(_render_md(result), encoding="utf-8")
    print(
        f"verification_status={result['verification_status']} "
        f"passed={result['checks_passed']}/{result['checks_total']} "
        f"false_success={result['false_success']}"
    )
    for r in result["checks"]:
        if not r["pass"]:
            print(f"  FAIL: {r['check']} {r['detail']}")
    return 0 if result["verification_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
