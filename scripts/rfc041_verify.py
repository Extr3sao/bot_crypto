"""RFC-041 independent verification — candidate statuses, KPI arithmetic and state.

Builder != verifier: this script re-derives every invariant from the *written*
artifacts (never from the RFC-041 module) and checks machine-readable consistency
across CANDIDATE_ARCHIVE, ECONOMIC_STATE, ECONOMIC_SCOREBOARD,
FINAL_BUSINESS_DECISION and the RFC041 final report (§70).

Research only: no orders, no credentials, no live capital.  Writes
``reports/business-freeze/RFC041_VERIFICATION.{md,json}`` and folds the verdict
back into ``reports/RFC041_FINAL_REPORT.{md,json}``.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "business-freeze"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: Independently re-declared (the verifier must not import the RFC-041 module).
EVIDENCE_LADDER: tuple[str, ...] = (
    "NO_EDGE",
    "STATISTICAL_HISTORICAL_EFFECT",
    "HISTORICAL_NET_EDGE",
    "EXECUTABLE_VALIDATED_EDGE",
    "BUSINESS_VALIDATED_EDGE",
)

EXPECTED_STATUSES: dict[str, str] = {
    "EXT-TSMOM-001": "INVALIDATED_TRADABILITY",
    "EXT-TSMOM-002": "REJECTED_HISTORICAL_PLAUSIBILITY",
    "EXT-TSMOM-003": "REJECTED_VALIDATION",
    "EXT-XMOM-001": "REJECTED_ROBUSTNESS",
    "MF-TREND-001": "RESEARCH_ASSET",
    "SC-TREND-001": "VALIDATED_DEFENSIVE",
    "SC-DUALMOM-002": "REJECTED_BUSINESS_EDGE",
    "SC-CANDIDATE-003": "NOT_AUTHORIZED",
}


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


def _rank(level: str) -> int:
    return EVIDENCE_LADDER.index(level)


def verify() -> dict[str, Any]:
    c = Checks()
    archive = load(DOCS / "CANDIDATE_ARCHIVE.json")
    state = load(DOCS / "ECONOMIC_STATE.json")
    scoreboard = load(DOCS / "ECONOMIC_SCOREBOARD.json")
    decision = load(DOCS / "FINAL_BUSINESS_DECISION.json")
    policy = load(DOCS / "BUSINESS_REENTRY_POLICY.json")
    final = load(REPORTS / "RFC041_FINAL_REPORT.json")
    reentry = load(OUT / "REENTRY_GATE.json")

    # -- 1. candidate statuses (§9-§20) ---------------------------------- #
    by_id = {x["candidate_id"]: x for x in archive["candidates"]}
    status_ok = all(by_id.get(cid, {}).get("final_status") == st for cid, st in EXPECTED_STATUSES.items())
    c.check("candidate_statuses_exact", status_ok, f"ids={sorted(by_id)}")
    c.check("candidate_count_is_eight", len(archive["candidates"]) == 8)
    c.check("sc_candidate_003_not_authorized", by_id["SC-CANDIDATE-003"]["final_status"] == "NOT_AUTHORIZED")

    # -- 2. KPI arithmetic recomputed from the archive ------------------- #
    hist = sum(_rank(x["evidence_level"]) >= _rank("HISTORICAL_NET_EDGE") for x in archive["candidates"])
    exe = sum(_rank(x["evidence_level"]) >= _rank("EXECUTABLE_VALIDATED_EDGE") for x in archive["candidates"])
    biz = sum(_rank(x["evidence_level"]) >= _rank("BUSINESS_VALIDATED_EDGE") for x in archive["candidates"])
    c.check("kpi_historical_net_recomputed", state["kpi"]["HISTORICAL_NET_EDGE_COUNT"] == hist, f"{hist}")
    c.check("kpi_executable_recomputed", state["kpi"]["EXECUTABLE_VALIDATED_EDGE_COUNT"] == exe, f"{exe}")
    c.check("kpi_business_recomputed_zero", state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == biz == 0)
    c.check("kpi_paper_zero", state["kpi"]["PAPER_CANDIDATE_COUNT"] == 0)
    c.check("kpi_forward_zero", state["kpi"]["FORWARD_PROFITABLE_COUNT"] == 0)
    c.check("kpi_live_zero", state["kpi"]["LIVE_PROFITABLE_COUNT"] == 0)

    # -- 3. zero active candidates / freeze active ----------------------- #
    c.check("zero_active_candidates", state["active_candidates"] == 0 and scoreboard["active_candidates"] == 0)
    c.check("freeze_active", state["alpha_research_freeze"] == "ACTIVE" == scoreboard["research_freeze"])
    c.check("no_paper_candidate", scoreboard["paper_candidate_count"] == 0 and decision["answer_ready_to_trade_for_profit"] == "NO")
    c.check("no_live_authorization", state["live_status"] == "NOT_AUTHORIZED" and state["live_capital_authorized"] == 0)
    c.check("no_new_alpha_candidate", biz == 0 and state["next_alpha_rfc_allowed"] is False)

    # -- 4. reentry conditions present (§27-§39) ------------------------- #
    c.check("reentry_five_triggers", set(policy["triggers"]) == {"A", "B", "C", "D", "E"})
    c.check("reentry_reject_conditions_present", len(policy["reject_conditions"]) >= 9)
    c.check("reentry_budget_frozen", policy["budget"] == {"MAX_FAMILIES": 3, "MAX_FINALISTS": 2, "MAX_IMPLEMENTED": 1})
    c.check("reentry_gate_logic_rejects_only", reentry["selftest"]["reject_only_proposal_passed"] is False)
    c.check("reentry_gate_logic_rejects_weak_product", reentry["selftest"]["weak_product_proposal_passed"] is False)
    c.check("freeze_blocks_next_alpha_rfc", reentry["next_alpha_rfc_allowed_now"] is False)
    c.check("next_rfc_requires_reentry_pass", "G_BUSINESS_REENTRY" in policy["next_rfc_requires"])

    # -- 5. stale status corrections (§61/§62) --------------------------- #
    stale = load(OUT / "STALE_STATUS_AUDIT.json")
    c.check("stale_entries_present", stale["entry_count"] >= 5)
    superseded_docs = all(
        "SUPERSEDED" in (DOCS / name).read_text(encoding="utf-8")
        for name in ("MANAGED_FUTURES_TREND_V1.md", "SMALL_CAPITAL_STRATEGY_V1.md", "PROJECT_ECONOMIC_STATUS.md")
    )
    c.check("stale_docs_marked_superseded", superseded_docs)
    c.check("sc_trend_ball_right", by_id["SC-TREND-001"]["disposition_class"] == "FUTURE_DEFENSIVE_OVERLAY_CANDIDATE")
    c.check("mf_trend_not_product_fit", by_id["MF-TREND-001"]["product_fit_200"] == "FAIL")

    # -- 6. machine-readable consistency -------------------------------- #
    c.check("kpi_state_vs_scoreboard", state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == scoreboard["business_edge_count"] == 0)
    c.check("decision_vs_state", decision["current_decision"] == state["current_decision"])
    c.check("state_vs_final_report", final["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"])
    c.check("schema_fields_present", all(k in state for k in ("schema_version", "updated_at", "source_commit", "decision_id")))
    c.check("decision_id_canonical", state["decision_id"] == "BUSINESS-FREEZE-2026-001")

    # -- 7. false success ------------------------------------------------- #
    fs = final["false_success"]["FALSE_SUCCESS"]
    c.check("false_success_zero", fs == 0, f"false_success={fs}")

    # -- 8. entry gate ---------------------------------------------------- #
    c.check("entry_gate_met", final["entry_gate"]["entry_condition_met"] is True)
    c.check("entry_head_is_rfc040", final["entry_gate"]["head_matches_rfc040"] is True)

    result = {
        "rfc": "RFC-041",
        "as_of_commit": git(),
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks_total": c.total,
        "checks_passed": c.passed,
        "checks_failed": len(c.failed),
        "mismatch_count": len(c.failed),
        "VERIFICATION_STATUS": "PASS" if not c.failed else "FAIL",
        "false_success": fs,
        "recomputed_kpi": {
            "HISTORICAL_NET_EDGE_COUNT": hist,
            "EXECUTABLE_VALIDATED_EDGE_COUNT": exe,
            "BUSINESS_VALIDATED_EDGE_COUNT": biz,
        },
        "checks": c.rows,
    }
    return result


def _render_md(result: dict[str, Any]) -> str:
    lines = [
        "# RFC-041 INDEPENDENT VERIFICATION",
        "",
        f"as_of_commit = {result['as_of_commit']}",
        f"generated_at = {result['generated_at']}",
        f"VERIFICATION_STATUS = {result['VERIFICATION_STATUS']}",
        "",
        f"checks_total = {result['checks_total']}",
        f"checks_passed = {result['checks_passed']}",
        f"checks_failed = {result['checks_failed']}",
        f"FALSE_SUCCESS = {result['false_success']}",
        "",
        "## Recomputed KPI",
    ]
    for k, v in result["recomputed_kpi"].items():
        lines.append(f"- {k} = {v}")
    lines.append("")
    lines.append("## Checks")
    for row in result["checks"]:
        mark = "PASS" if row["ok"] else "FAIL"
        detail = f" ({row['detail']})" if row["detail"] else ""
        lines.append(f"- [{mark}] {row['name']}{detail}")
    lines += [
        "",
        "Builder != verifier: re-derived from written artifacts, never from the RFC-041 module.",
        "Research evidence only. No live trading, no orders, no paid data.",
    ]
    return "\n".join(lines) + "\n"


def patch_final_report(result: dict[str, Any]) -> None:
    path_json = REPORTS / "RFC041_FINAL_REPORT.json"
    obj = load(path_json)
    obj["independent_verification"] = {
        "VERIFICATION_STATUS": result["VERIFICATION_STATUS"],
        "mismatch_count": result["mismatch_count"],
        "checks_total": result["checks_total"],
        "checks_passed": result["checks_passed"],
    }
    path_json.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    path_md = REPORTS / "RFC041_FINAL_REPORT.md"
    text = path_md.read_text(encoding="utf-8")
    text = text.replace(
        "INDEPENDENT VERIFICATION = PENDING",
        f"INDEPENDENT VERIFICATION = {result['VERIFICATION_STATUS']}",
    )
    path_md.write_text(text, encoding="utf-8")



def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result = verify()
    (OUT / "RFC041_VERIFICATION.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "RFC041_VERIFICATION.md").write_text(_render_md(result), encoding="utf-8")
    patch_final_report(result)
    print(json.dumps({
        "VERIFICATION_STATUS": result["VERIFICATION_STATUS"],
        "checks_total": result["checks_total"],
        "checks_passed": result["checks_passed"],
        "mismatch_count": result["mismatch_count"],
        "recomputed_kpi": result["recomputed_kpi"],
        "FALSE_SUCCESS": result["false_success"],
    }, indent=2))
    return 0 if result["VERIFICATION_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
