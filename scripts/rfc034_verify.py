"""RFC-034 — INDEPENDENT VERIFIER (builder != verifier, §77).

Deliberately imports NEITHER ``rfc034_run`` NOR ``economic_closure``.  It reads the
*generated* artifacts under ``reports/strategy-closure/`` plus the raw RFC final
reports, and independently re-derives:

    candidate statuses, mandatory-gate promotion, gate ordering, marker zeros,
    the research pause state, re-entry policy consistency, the
    verification-vs-economic separation, and FALSE_SUCCESS.

Then it writes ``RFC034_VERIFICATION.{md,json}``.  The RFC-032
``CandidateCertificationGate`` is imported on purpose: it is the *shared certified
contract* (§35), not the builder's closure logic.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.certification_gate import (
    MANDATORY_GATES,
    check_gate_order,
    evaluate_promotion,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "strategy-closure"
CLOSURE = REPO / "reports"
DOCS = REPO / "docs" / "research"

EXPECTED_STATUS = {
    "EXT-TSMOM-001": "INVALIDATED_TRADABILITY",
    "EXT-TSMOM-002": "REJECTED_HISTORICAL_PLAUSIBILITY",
    "EXT-TSMOM-003": "REJECTED_VALIDATION",
    "EXT-XMOM-001": "REJECTED_ROBUSTNESS",
}

EXPECTED_RFCS = {
    "RFC-010B",
    "RFC-020",
    "RFC-021",
    "RFC-022",
    "RFC-023",
    "RFC-024",
    "RFC-025",
    "RFC-026",
    "RFC-027",
    "RFC-028",
    "RFC-029",
    "RFC-030",
    "RFC-031",
    "RFC-032",
    "RFC-033",
}

REQUIRED_ARTIFACTS = [
    "RFC034_PLAN",
    "ECONOMIC_RESEARCH_LEDGER",
    "CANDIDATE_REGISTRY",
    "PROJECT_ECONOMIC_STATUS",
    "ALPHA_REENTRY_POLICY",
    "ALPHA_ADMISSION_SCORECARD",
    "EVIDENCE_ARCHIVE_INDEX",
    "PROJECT_SCORECARD",
]


def git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    except Exception:
        return "UNKNOWN"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    checks: dict[str, bool] = {}

    # 1. required artifacts exist (md + json)
    for name in REQUIRED_ARTIFACTS:
        checks[f"artifact_{name}_md"] = (OUT / f"{name}.md").exists()
        checks[f"artifact_{name}_json"] = (OUT / f"{name}.json").exists()
    checks["final_report_md"] = (CLOSURE / "RFC034_FINAL_REPORT.md").exists()
    checks["final_report_json"] = (CLOSURE / "RFC034_FINAL_REPORT.json").exists()
    checks["tracked_status_md"] = (DOCS / "PROJECT_ECONOMIC_STATUS.md").exists()
    checks["tracked_playbook_md"] = (DOCS / "ALPHA_RESEARCH_PLAYBOOK.md").exists()
    checks["tracked_where_md"] = (DOCS / "WHERE_WE_ARE.md").exists()

    status = load(OUT / "PROJECT_ECONOMIC_STATUS.json")
    registry = load(OUT / "CANDIDATE_REGISTRY.json")
    ledger = load(OUT / "ECONOMIC_RESEARCH_LEDGER.json")
    policy = load(OUT / "ALPHA_REENTRY_POLICY.json")
    final = load(CLOSURE / "RFC034_FINAL_REPORT.json")

    marker = status["economic_marker"]

    # 2. marker zeros (§1)
    checks["marker_statistical_effect_yes"] = marker["statistical_historical_effect"] == 1
    for key in (
        "executable_validated_net_edge",
        "robust_executable_net_edge",
        "executable_holdout_pass",
        "certified_paper_candidate",
        "forward_paper_profitable",
        "live_profitable",
    ):
        checks[f"marker_{key}_zero"] = marker[key] == 0

    # 3. pause state + status split (§1/§2)
    checks["status_paused"] = status["profitability_research_status"] == "PAUSED"
    checks["platform_research_capable"] = status["platform_status"] == "RESEARCH_CAPABLE"
    checks["economic_no_edge"] = status["economic_status"] == "NO_VALIDATED_EXECUTABLE_EDGE"
    checks["decision_pause"] = status["current_decision"] == "PAUSE_TRADING_PROJECT"
    checks["next_alpha_rfc_disallowed"] = status["next_alpha_rfc_allowed"] is False
    checks["active_candidates_zero"] = status["active_candidates"] == 0
    checks["final_marker_zeros"] = all(
        final["economic_marker"][k] == 0
        for k in (
            "executable_validated_net_edge",
            "robust_executable_net_edge",
            "executable_holdout_pass",
            "certified_paper_candidate",
            "forward_paper_profitable",
            "live_profitable",
        )
    )

    # 4. candidate statuses match expectations AND raw RFC reports (§77)
    by_id = {c["candidate_id"]: c for c in registry["candidates"]}
    for cid, expected in EXPECTED_STATUS.items():
        checks[f"status_{cid}"] = by_id.get(cid, {}).get("status") == expected

    raw031 = read(CLOSURE / "RFC031_FINAL_REPORT.md")
    raw030 = read(CLOSURE / "RFC030_FINAL_REPORT.md")
    raw032 = read(CLOSURE / "RFC032_FINAL_REPORT.md")
    raw033 = read(CLOSURE / "RFC033_FINAL_REPORT.md")
    checks["raw031_tradability_fail"] = "G_PC_1_TRADABILITY = FAIL" in raw031
    checks["raw030_xmom_robust_fail"] = (
        "EXT-XMOM-001 | HOLDOUT_PASS | PASS | PASS | PASS | FAIL" in raw030
    )
    checks["raw032_rem1_fail"] = "G_REM_1_HISTORICAL_PLAUSIBILITY = FAIL" in raw032
    checks["raw033_perp2_fail"] = "G_PERP_2 = FAIL" in raw033
    checks["raw032_median_zero"] = "HISTORICAL MEDIAN NET = 0.0 bps" in raw032
    checks["raw033_validation_negative"] = "Validation net = -563.799 bps/month" in raw033

    # 5. no promotable invalidated candidate (independent recompute via gate §35)
    no_promotable = True
    correct_flags = True
    order_ok = True
    for c in registry["candidates"]:
        result = evaluate_promotion(c["gates"])
        if result.promotable:
            no_promotable = False
        if bool(c["promotable"]) != bool(result.promotable):
            correct_flags = False
        if c["promotable"] and set(c["gates"]) != set(MANDATORY_GATES):
            correct_flags = False
        # An order violation (later PASS after earlier FAIL) is tolerable only
        # when the candidate is NOT promotable; it must never grant promotion.
        if not check_gate_order(c["gates"]).passed and c["promotable"]:
            order_ok = False
    checks["no_promotable_invalidated_candidate"] = no_promotable
    checks["promotable_flags_correct"] = correct_flags
    checks["gate_order_ok"] = order_ok

    # 6. no stale PAPER_CANDIDATE (§8)
    checks["no_paper_candidate_status"] = all(
        c["status"] != "PAPER_CANDIDATE" for c in registry["candidates"]
    )
    checks["registry_active_zero"] = registry["active_candidates"] == 0

    # 7. verification vs economic separation (§36-§40) — regression on RFC-033
    v033 = load(CLOSURE / "perp-tsmom" / "RFC033_VERIFICATION.json")
    verifier_checks = {
        "reproduction_exact": v033["reproduction_exact"],
        "hashes_present": bool(v033.get("source_commit")),
        "accounting_reconciled": (
            v033["discovery_independent"]["accounting_identity_max_abs"] == 0.0
            and v033["validation_independent"]["accounting_identity_max_abs"] == 0.0
        ),
        "contract_gate_present": "G_PERP_2_independent" in v033,
    }
    verification_status = "PASS" if all(verifier_checks.values()) else "FAIL"
    economic_result = "FAIL" if v033["G_PERP_2_independent"] == "FAIL" else "PASS"
    checks["verification_economic_separated"] = (
        verification_status == "PASS" and economic_result == "FAIL"
    )
    checks["strategy_loss_not_a_check"] = checks["verification_economic_separated"]

    # 8. re-entry policy consistency (§41-§43)
    states = policy["states"]
    checks["reentry_state_machine"] = (
        states[0] == "PAUSED" and states[-1] == "REPRODUCTION" and len(states) == 5
    )
    bounds = [h["upper_bound"] for h in policy["headroom_classes"]]
    checks["headroom_monotonic"] = bounds == sorted(bounds)
    checks["headroom_classes"] = [h["class"] for h in policy["headroom_classes"]] == [
        "REJECT",
        "TOO_THIN",
        "WEAK",
        "POTENTIALLY_RESEARCHABLE",
        "STRONG_HEADROOM",
    ]
    valid = set(policy["valid_reopen_triggers"])
    invalid = set(policy["invalid_reopen_triggers"])
    checks["reopen_triggers_disjoint"] = not (valid & invalid)
    checks["gate_order_canonical"] = (
        policy["gate_order"][0] == "DATA" and policy["gate_order"][-1] == "LIVE"
    )
    checks["budget_bounded"] = (
        policy["budget"]["max_strategies"] == 2
        and policy["budget"]["max_core_variants_per_strategy"] == 3
    )

    # 9. ledger covers all economic RFCs (§4)
    led_rfcs = {row["rfc"] for row in ledger["rows"]}
    checks["ledger_covers_all_rfcs"] = EXPECTED_RFCS.issubset(led_rfcs)

    # 10. verification semantics contract present in tracked status (§49)
    tracked = read(DOCS / "PROJECT_ECONOMIC_STATUS.md")
    checks["tracked_status_canonical"] = (
        "profitability_research_status = PAUSED" in tracked
        and "platform_status = RESEARCH_CAPABLE" in tracked
    )

    # FALSE_SUCCESS (§78): only incorrect claims / bypasses, never a strategy loss.
    false_success_triggers = {
        "invalidated_candidate_remains_promotable": not no_promotable,
        "failed_strategy_listed_as_validated": marker["executable_validated_net_edge"] != 0,
        "paper_candidate_without_mandatory_gates": bool(
            registry["candidates"]
            and any(
                c.get("status") == "PAPER_CANDIDATE" and not c.get("promotable")
                for c in registry["candidates"]
            )
        ),
        "economic_gate_confused_with_verifier_failure": not checks[
            "verification_economic_separated"
        ],
        "project_marked_ready_or_profitable": status["profitability_research_status"]
        not in ("PAUSED",),
        "future_alpha_loop_left_automatically_enabled": status["next_alpha_rfc_allowed"]
        is not False,
    }
    false_success = sum(1 for v in false_success_triggers.values() if v)

    checks_passed = sum(1 for v in checks.values() if v)
    checks_total = len(checks)
    verification_status_final = "PASS" if checks_passed == checks_total else "FAIL"

    payload = {
        "RFC": "RFC-034",
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": git("HEAD"),
        "verification_status": verification_status_final,
        "economic_result": "NOT_REACHED",
        "checks_total": checks_total,
        "checks_passed": checks_passed,
        "checks": checks,
        "false_success": false_success,
        "false_success_triggers": false_success_triggers,
        "independent_candidate_statuses": {
            cid: by_id.get(cid, {}).get("status") for cid in EXPECTED_STATUS
        },
        "verification_vs_economic_regression": {
            "rfc033_verification_status": verification_status,
            "rfc033_economic_result": economic_result,
            "false_success_from_strategy_loss": 0,
        },
        "agrees_with_builder": checks["no_promotable_invalidated_candidate"]
        and checks["promotable_flags_correct"],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RFC034_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "RFC034_VERIFICATION.md").write_text(
        "# RFC-034 — INDEPENDENT VERIFICATION\n\n"
        f"verification_status = {verification_status_final}\n\n"
        f"economic_result = NOT_REACHED\n\n"
        f"checks_passed = {checks_passed}/{checks_total}\n\n"
        f"FALSE_SUCCESS = {false_success}\n\n"
        f"agrees_with_builder = {payload['agrees_with_builder']}\n\n"
        "## Checks\n\n" + "\n".join(f"- {k}: {v}" for k, v in sorted(checks.items())) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "verification_status": verification_status_final,
                "checks_passed": checks_passed,
                "checks_total": checks_total,
                "false_success": false_success,
                "agrees_with_builder": payload["agrees_with_builder"],
            },
            indent=2,
        )
    )
    return 0 if (checks_passed == checks_total and false_success == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
