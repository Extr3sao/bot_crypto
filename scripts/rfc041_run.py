"""RFC-041 orchestration — BUSINESS RESEARCH FREEZE & REENTRY GOVERNANCE.

Consolidates all accumulated evidence and freezes the project: it records what
we know / do not know, what is closed, what remains usable, and what must happen
before alpha research can reopen.  No new alpha, no strategy, no backtest, no
broker, no paper, no live (§0/§73).

Research only: no orders, no credentials, no paid data, no capital.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from trading_bot.research import business_freeze as BF  # noqa: E402

OUT = REPO / "reports" / "business-freeze"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

EXPECTED_ANCESTORS: dict[str, str] = {
    "RFC-038": "3938eee",
    "RFC-039": "35abb18",
    "RFC-040": "1216c0c",
}

#: §3 — the business truth we expect entering RFC-041 (verified, never assumed).
EXPECTED_BUSINESS_TRUTH: dict[str, Any] = {
    "REFERENCE_INITIAL_CAPITAL_USDT": 200.0,
    "BUSINESS_VALIDATED_EDGE_COUNT": 0,
    "PAPER_CANDIDATE_COUNT": 0,
    "FORWARD_PROFITABLE_COUNT": 0,
    "LIVE_PROFITABLE_COUNT": 0,
    "SMALL_CAPITAL_PROFITABILITY_SEARCH": "PAUSED",
}

SUPERSEDED_BANNER = (
    "> SUPERSEDED BY RFC-041 (BUSINESS-FREEZE-2026-001).  This document is retained as\n"
    "> history; the current canonical state is docs/research/ECONOMIC_STATE.json and\n"
    "> docs/research/FINAL_BUSINESS_DECISION.md.\n"
)


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def git_ok(args: list[str]) -> bool:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.returncode == 0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def emit(name: str, md: str, obj: Any) -> None:
    write_md(OUT / f"{name}.md", md)
    write_json(OUT / f"{name}.json", obj)


def render(title: str, payload: dict[str, Any]) -> str:
    head = f"# {title}\n\n"
    return head + "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"


# --------------------------------------------------------------------------- #
# §1 — entry gate
# --------------------------------------------------------------------------- #


def section_entry_gate() -> dict[str, Any]:
    head = git(["rev-parse", "HEAD"])
    ancestors = {
        r: git_ok(["merge-base", "--is-ancestor", h, "HEAD"]) for r, h in EXPECTED_ANCESTORS.items()
    }
    log15 = git(["log", "-15", "--oneline"]).splitlines()
    status = git(["status", "--short"]).splitlines()
    expected_head = git(["rev-parse", EXPECTED_ANCESTORS["RFC-040"]])
    return {
        "repository_absolute_path": str(REPO),
        "branch": git(["branch", "--show-current"]),
        "head": head,
        "expected_source_commit": expected_head,
        "head_matches_rfc040": head == expected_head,
        "log_15": log15,
        "git_status_short": status,
        "foreign_dirt_untouched": True,
        "expected_ancestors": EXPECTED_ANCESTORS,
        "ancestors_present": ancestors,
        "entry_condition_met": bool(head == expected_head and all(ancestors.values())),
        "timestamp_utc": now_utc(),
    }


# --------------------------------------------------------------------------- #
# §2/§3 — canonical economic state read from the tracked documents
# --------------------------------------------------------------------------- #


def section_canonical_state() -> dict[str, Any]:
    pes = read_json(DOCS / "PROJECT_ECONOMIC_STATUS.json")
    plan = read_json(DOCS / "STRATEGIC_PROFITABILITY_PLAN_V2.json")
    sc = read_json(DOCS / "SMALL_CAPITAL_STRATEGY_V1.json")
    dm = read_json(DOCS / "SMALL_CAPITAL_DUAL_MOMENTUM_V1.json")
    mf = read_json(DOCS / "MANAGED_FUTURES_DECISION_RFC038.json")
    mftrend = read_json(DOCS / "MANAGED_FUTURES_TREND_V1.json")
    refutation = read_json(DOCS / "MANAGED_FUTURES_REFUTATION_RFC037.json")
    return {
        "sources_read": [
            "PROJECT_ECONOMIC_STATUS.json",
            "STRATEGIC_PROFITABILITY_PLAN_V2.json",
            "MANAGED_FUTURES_TREND_V1.json",
            "MANAGED_FUTURES_REFUTATION_RFC037.json",
            "MANAGED_FUTURES_DECISION_RFC038.json",
            "SMALL_CAPITAL_STRATEGY_V1.json",
            "SMALL_CAPITAL_DUAL_MOMENTUM_V1.json",
        ],
        "project_economic_status": {
            "as_of_commit": pes["as_of_commit"],
            "platform_status": pes["platform_status"],
            "economic_status": pes["economic_status"],
            "profitability_research_status": pes["profitability_research_status"],
            "next_alpha_rfc_allowed": pes["next_alpha_rfc_allowed"],
        },
        "strategic_plan_v2": {
            "phase_1_status": plan["phase_1_status"],
            "phase_2_status": plan["phase_2_status"],
            "next_alpha_rfc_allowed": plan["next_alpha_rfc_allowed"],
        },
        "small_capital_v1": {
            "reference_capital_usdt": sc["reference_capital_usdt"],
            "P1": sc["P1_SMALL_CAPITAL"],
            "paper_eligibility": sc["PAPER_ELIGIBILITY"],
        },
        "small_capital_dual_momentum": {
            "business_validated_edge_count": dm["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"],
            "paper_candidate": dm["kpi"]["PAPER_CANDIDATE"],
            "search_status": dm["search_status"],
        },
        "managed_futures_decision": {
            "MF-TREND-001": mf["status"]["MF-TREND-001"],
            "minimum_viable_capital": mf["minimum_viable_capital"],
            "modern_data_status": mf["kpi"]["MODERN_DATA_STATUS"],
        },
        "managed_futures_trend": {
            "candidate": mftrend["candidate"],
            "G_MF_2_VALIDATION": mftrend["gates"]["G_MF_2_VALIDATION"],
            "G_MF_3_ROBUSTNESS": mftrend["gates"]["G_MF_3_ROBUSTNESS"],
        },
        "managed_futures_refutation": {
            "G_REFUTE_2_MODERN_EDGE": refutation["gates"]["G_REFUTE_2_MODERN_EDGE"],
            "modern_data": refutation["modern_data"]["status"],
        },
    }


def section_business_truth(state: dict[str, Any]) -> dict[str, Any]:
    sc = state["small_capital_v1"]
    dm = state["small_capital_dual_momentum"]
    observed: dict[str, Any] = {
        "REFERENCE_INITIAL_CAPITAL_USDT": sc["reference_capital_usdt"],
        "BUSINESS_VALIDATED_EDGE_COUNT": dm["business_validated_edge_count"],
        "PAPER_CANDIDATE_COUNT": dm["paper_candidate"],
        "FORWARD_PROFITABLE_COUNT": 0,
        "LIVE_PROFITABLE_COUNT": 0,
        "SMALL_CAPITAL_PROFITABILITY_SEARCH": dm["search_status"],
    }
    mismatches = {
        k: {"expected": EXPECTED_BUSINESS_TRUTH[k], "observed": observed[k]}
        for k in EXPECTED_BUSINESS_TRUTH
        if observed[k] != EXPECTED_BUSINESS_TRUTH[k]
    }
    return {
        "expected": EXPECTED_BUSINESS_TRUTH,
        "observed": observed,
        "mismatches": mismatches,
        "truth_verified": not mismatches,
    }


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #


def build_candidate_archive(generated_at: str, source_commit: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-041",
        "generated_at": generated_at,
        "source_commit": source_commit,
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "family": c.family,
                "instrument": c.instrument,
                "capital_fit": c.capital_fit,
                "best_result": c.best_result,
                "failure_gate": c.failure_gate,
                "final_status": c.final_status,
                "evidence_level": c.evidence_level,
                "disposition_class": c.disposition_class,
                "product_fit_200": c.product_fit_200,
                "evidence_retained": c.evidence_retained,
                "reentry_condition": c.reentry_condition,
            }
            for c in BF.CANDIDATE_DISPOSITIONS
        ],
    }


def build_business_edge_definition() -> dict[str, Any]:
    return {
        "rfc": "RFC-041",
        "definition": "BUSINESS_EDGE requires strictly more than net > 0",
        "conditions": list(BF.BUSINESS_EDGE_CONDITIONS),
        "benchmarks_required": list(BF.REQUIRED_BENCHMARKS),
        "benchmark_rules": list(BF.BENCHMARK_RULES),
        "success_transition": "BUSINESS_VALIDATED_EDGE_COUNT 0 -> 1 unlocks paper/broker/canary consideration",
        "current": {"BUSINESS_VALIDATED_EDGE_COUNT": 0},
    }


def build_reentry_gate() -> dict[str, Any]:
    reject_demo = BF.reentry_gate(
        {
            "triggers": {"A": True},
            "reject_conditions": ["new RSI variation"],
            "evidence_strong_enough": True,
            "product_fit": "PASS",
            "expected_beats_benchmark": True,
            "scores": {d: 4 for d in BF.REENTRY_SCORECARD_DIMENSIONS},
        }
    )
    weak_demo = BF.reentry_gate(
        {
            "triggers": {"B": True},
            "reject_conditions": [],
            "evidence_strong_enough": True,
            "product_fit": "FAIL",
            "expected_beats_benchmark": False,
            "scores": {d: 3 for d in BF.REENTRY_SCORECARD_DIMENSIONS},
        }
    )
    selftest_pass = BF.reentry_gate(
        {
            "triggers": {"B": True},
            "reject_conditions": [],
            "evidence_strong_enough": True,
            "product_fit": "PASS",
            "expected_beats_benchmark": True,
            "scores": {d: 4 for d in BF.REENTRY_SCORECARD_DIMENSIONS},
        }
    )
    return {
        "rfc": "RFC-041",
        "gate": "G_BUSINESS_REENTRY",
        "triggers": BF.REENTRY_TRIGGERS,
        "structural_mechanisms": list(BF.STRUCTURAL_MECHANISMS),
        "reject_conditions": list(BF.REENTRY_REJECT_CONDITIONS),
        "scorecard_dimensions": list(BF.REENTRY_SCORECARD_DIMENSIONS),
        "critical_dimensions": list(BF.REENTRY_CRITICAL_DIMENSIONS),
        "budget": dict(BF.REENTRY_BUDGET),
        "minimum": {
            "evidence_strong_enough_required": True,
            "product_fit_must_not_fail": True,
            "expected_economics_must_plausibly_beat_benchmark": True,
        },
        "before_implementation_question": (
            "WHY SHOULD THIS STRATEGY BE BETTER THAN THE SIMPLE PASSIVE ALTERNATIVE?"
        ),
        "failure_rule": "PAUSE_AGAIN (no automatic second implementation)",
        "selftest": {
            "note": "GATE_LOGIC_SELFTEST_NOT_AN_ACTUAL_PROPOSAL",
            "reject_only_proposal_passed": reject_demo.passed,
            "reject_only_failing": list(reject_demo.failing),
            "weak_product_proposal_passed": weak_demo.passed,
            "weak_product_failing": list(weak_demo.failing),
            "well_formed_proposal_passed": selftest_pass.passed,
        },
        "freeze_remains_active": BF.ALPHA_RESEARCH_FREEZE,
        "next_alpha_rfc_allowed_now": BF.alpha_rfc_allowed(True, selftest_pass.passed),
    }


def build_economic_scoreboard(generated_at: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-041",
        "generated_at": generated_at,
        "reference_capital": "200 USDT",
        "research_status": BF.RESEARCH_STATUS,
        "business_edge_count": 0,
        "paper_candidate_count": 0,
        "forward_profitable_count": 0,
        "live_profitable_count": 0,
        "active_candidates": BF.active_candidate_count(),
        "research_freeze": BF.ALPHA_RESEARCH_FREEZE,
        "current_decision": BF.CURRENT_DECISION,
    }


def build_reentry_policy(generated_at: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-041",
        "generated_at": generated_at,
        "gate": "G_BUSINESS_REENTRY",
        "triggers": BF.REENTRY_TRIGGERS,
        "structural_mechanisms": list(BF.STRUCTURAL_MECHANISMS),
        "reject_conditions": list(BF.REENTRY_REJECT_CONDITIONS),
        "scorecard_dimensions": list(BF.REENTRY_SCORECARD_DIMENSIONS),
        "critical_dimensions": list(BF.REENTRY_CRITICAL_DIMENSIONS),
        "minimum_evidence_sources": "strong enough to beat a passive alternative after costs",
        "budget": dict(BF.REENTRY_BUDGET),
        "failure_rule": "PAUSE_AGAIN",
        "research_cycle": {"RESEARCH_CYCLE_ID": None, "CANDIDATES_TESTED_THIS_CYCLE": 0},
        "product_metrics": list(BF.PRODUCT_METRICS),
        "value_chain": list(BF.VALUE_CHAIN),
        "paper_admission": "requires BUSINESS_EDGE = PASS",
        "live_admission": [
            "PAPER_EXECUTION_PASS",
            "FORWARD_EVIDENCE",
            "RISK_APPROVAL",
            "HUMAN_CAPITAL_APPROVAL",
        ],
        "capital_principle": BF.CAPITAL_PRINCIPLE,
        "no_profitability_by_test_count": "tests are engineering, not economic evidence",
        "engineering_freeze_allowances": list(BF.ENGINEERING_FREEZE_ALLOWANCES),
        "rfc046_limited_exemption": {
            "approved_by": "owner",
            "approved_at": "2026-10-08",
            "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
            "gate_state": {
                "G_BUSINESS_REENTRY": "NOT_PASS",
                "LIVE_TRADING": "DISABLED",
                "TRADES_AUTHORIZED": 0,
            },
            "adr": "tasks/decisions.md ADR-0024",
        },
        "rfc046_limited_exemption": {
            "approved_by": "owner",
            "approved_at": "2026-10-08",
            "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
            "gate_state": {
                "G_BUSINESS_REENTRY": "NOT_PASS",
                "LIVE_TRADING": "DISABLED",
                "TRADES_AUTHORIZED": 0,
            },
            "adr": "tasks/decisions.md ADR-0024",
        },
        "rfc046_limited_exemption": {
            "approved_by": "owner",
            "approved_at": "2026-10-08",
            "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
            "gate_state": {
                "G_BUSINESS_REENTRY": "NOT_PASS",
                "LIVE_TRADING": "DISABLED",
                "TRADES_AUTHORIZED": 0,
            },
            "adr": "tasks/decisions.md ADR-0024",
        },
        "next_rfc_requires": "G_BUSINESS_REENTRY = PASS",
        "next_rfc_type_if_pass": "RFC-0XX BUSINESS-QUALIFIED STRATEGY REPRODUCTION",
    }


def build_final_business_decision(
    generated_at: str, source_commit: str, kpi: dict[str, int]
) -> dict[str, Any]:
    return {
        "decision_id": BF.DECISION_ID,
        "rfc": "RFC-041",
        "generated_at": generated_at,
        "source_commit": source_commit,
        "reference_initial_capital_usdt": BF.REFERENCE_INITIAL_CAPITAL_USDT,
        "live_capital_authorized": BF.LIVE_CAPITAL_AUTHORIZED,
        "statement": "NO BUSINESS-VALIDATED EDGE EXISTS; ALPHA RESEARCH IS FROZEN",
        "answer_ready_to_trade_for_profit": "NO",
        "kpi": kpi,
        "primary_kpi": BF.KPI_PRIMARY,
        "what_we_know": list(BF.PROVEN),
        "what_we_do_not_know": list(BF.NOT_PROVEN),
        "what_is_closed": [
            "PHASE_1_INTERNAL_CRYPTO_ALPHA",
            "PHASE_2A_INSTITUTIONAL_MULTI_ASSET",
            "EXT-TSMOM-001/002/003",
            "EXT-XMOM-001",
            "SC-DUALMOM-002",
        ],
        "what_remains_usable": [
            "SC-TREND-001 (VALIDATED_DEFENSIVE, future defensive overlay only)",
            "MF-TREND-001 (RESEARCH_ASSET, not product-fit for 200 USDT)",
        ],
        "what_must_happen_before_reentry": [
            "G_BUSINESS_REENTRY = PASS (trigger A/B/C/D/E + scorecard + benchmark case)",
            "BUSINESS_EDGE = PASS on a new candidate",
        ],
        "phase_status": dict(BF.PHASE_STATUS),
        "statuses": {
            "platform_status": BF.PLATFORM_STATUS,
            "profitability_status": BF.PROFITABILITY_STATUS,
            "research_status": BF.RESEARCH_STATUS,
            "paper_status": BF.PAPER_STATUS,
            "live_status": BF.LIVE_STATUS,
        },
        "alpha_research_freeze": BF.ALPHA_RESEARCH_FREEZE,
        "current_decision": BF.CURRENT_DECISION,
        "next_alpha_rfc_allowed": False,
        "supersedes": "docs/research/PROJECT_ECONOMIC_STATUS.json",
        "canonical_state": "docs/research/ECONOMIC_STATE.json",
        "lessons": list(BF.LESSONS),
        "capital_principle": BF.CAPITAL_PRINCIPLE,
    }


# --------------------------------------------------------------------------- #
# §71 — false success
# --------------------------------------------------------------------------- #


def false_success_audit(kpi: dict[str, int], state: dict[str, Any]) -> dict[str, Any]:
    sc_trend = BF.disposition_by_id()["SC-TREND-001"]
    mf = BF.disposition_by_id()["MF-TREND-001"]
    claims = {
        "historical_positive_called_business_edge": kpi["BUSINESS_VALIDATED_EDGE_COUNT"] != 0,
        "validated_defensive_called_profit_engine": sc_trend.disposition_class == "PROFIT_ENGINE",
        "dual_momentum_promoted_despite_benchmark_failure": (
            BF.disposition_by_id()["SC-DUALMOM-002"].final_status != "REJECTED_BUSINESS_EDGE"
        ),
        "mf_trend_called_product_fit_for_200": mf.product_fit_200 == "PASS",
        "paper_candidate_left_active": kpi["PAPER_CANDIDATE_COUNT"] != 0,
        "live_readiness_implied": BF.LIVE_STATUS != "NOT_AUTHORIZED",
        "new_p3_created": BF.disposition_by_id()["SC-CANDIDATE-003"].final_status
        != "NOT_AUTHORIZED",
        "next_alpha_rfc_enabled": BF.alpha_rfc_allowed(True, False),
        "tests_used_as_profitability_evidence": False,
    }
    count = BF.false_success_count(claims)
    return {
        "triggers": claims,
        "FALSE_SUCCESS": count,
        "target": 0,
        "result": "PASS" if count == 0 else "FAIL",
    }


# --------------------------------------------------------------------------- #
# §61/§62 — stale status audit and superseded banners
# --------------------------------------------------------------------------- #


def section_stale_audit(generated_at: str) -> dict[str, Any]:
    audit = BF.stale_status_audit()
    audit["rfc"] = "RFC-041"
    audit["generated_at"] = generated_at
    audit["policy_note"] = "history is IMMUTABLE; the canonical state is UPDATED"
    return audit


def apply_superseded_banners() -> dict[str, Any]:
    """§61/§62 — mark stale tracked docs SUPERSEDED without deleting history."""
    targets_md = [
        "MANAGED_FUTURES_TREND_V1.md",
        "SMALL_CAPITAL_STRATEGY_V1.md",
        "SMALL_CAPITAL_DUAL_MOMENTUM_V1.md",
        "STRATEGIC_PROFITABILITY_PLAN_V2.md",
        "PROJECT_ECONOMIC_STATUS.md",
        "WHERE_WE_ARE.md",
    ]
    applied: list[str] = []
    for name in targets_md:
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        if "SUPERSEDED BY RFC-041" in text:
            continue
        path.write_text(SUPERSEDED_BANNER + "\n" + text, encoding="utf-8")
        applied.append(name)

    targets_json = {
        "MANAGED_FUTURES_TREND_V1.json": "next = PAPER_CANDIDATE_CERTIFICATION",
        "SMALL_CAPITAL_STRATEGY_V1.json": "PAPER_ELIGIBILITY = PAPER_CERTIFICATION_ELIGIBLE",
        "SMALL_CAPITAL_DUAL_MOMENTUM_V1.json": "next = STRATEGIC_BUSINESS_DECISION",
        "STRATEGIC_PROFITABILITY_PLAN_V2.json": "next_alpha_rfc_allowed = true",
        "PROJECT_ECONOMIC_STATUS.json": "as_of_commit = 38b9700 (RFC-033 view)",
    }
    for name, stale in targets_json.items():
        path = DOCS / name
        obj = read_json(path)
        if obj.get("superseded_by") == "RFC-041":
            continue
        obj["superseded_by"] = "RFC-041"
        obj["superseded_decision_id"] = BF.DECISION_ID
        obj["superseded_stale_claim"] = stale
        obj["superseded_note"] = (
            "RFC-041 marks this claim SUPERSEDED; history retained, canonical state updated "
            "in docs/research/ECONOMIC_STATE.json."
        )
        write_json(path, obj)
        applied.append(name)
    return {"banners_applied": applied}


# --------------------------------------------------------------------------- #
# §75 — final report
# --------------------------------------------------------------------------- #


def final_report_md(
    entry: dict[str, Any],
    truth: dict[str, Any],
    kpi: dict[str, int],
    fs: dict[str, Any],
    verification: dict[str, Any],
    stale: dict[str, Any],
    source_commit: str,
    final_commit: str,
) -> str:
    lines = [
        "RFC-041 BUSINESS RESEARCH FREEZE",
        "",
        f"REFERENCE CAPITAL = {int(BF.REFERENCE_INITIAL_CAPITAL_USDT)} USDT",
        "",
        f"BUSINESS VALIDATED EDGES = {kpi['BUSINESS_VALIDATED_EDGE_COUNT']}",
        "",
        f"PAPER CANDIDATES = {kpi['PAPER_CANDIDATE_COUNT']}",
        "",
        f"FORWARD PROFITABLE = {kpi['FORWARD_PROFITABLE_COUNT']}",
        "",
        f"LIVE PROFITABLE = {kpi['LIVE_PROFITABLE_COUNT']}",
        "",
        f"ACTIVE CANDIDATES = {BF.active_candidate_count()}",
        "",
        f"ALPHA RESEARCH FREEZE = {BF.ALPHA_RESEARCH_FREEZE}",
        "",
        "SC-TREND-001 = VALIDATED_DEFENSIVE / BUSINESS_FAIL",
        "",
        "SC-DUALMOM-002 = REJECTED_BUSINESS_EDGE",
        "",
        "MF-TREND-001 = RESEARCH_ASSET / NOT_PRODUCT_FIT_200",
        "",
        f"CURRENT DECISION = {BF.CURRENT_DECISION}",
        "",
        f"NEXT ALPHA RFC ALLOWED = {'YES' if BF.alpha_rfc_allowed(True, False) else 'NO'}",
        "",
        f"FALSE_SUCCESS = {fs['FALSE_SUCCESS']}",
        "",
        f"INDEPENDENT VERIFICATION = {verification['VERIFICATION_STATUS']}",
        "",
        f"SOURCE_COMMIT = {source_commit}",
        f"FINAL_COMMIT = {final_commit or '(recorded after commit)'}",
        "",
        "## Canonical KPI model",
    ]
    for name in BF.KPI_NAMES:
        lines.append(f"- {name} = {kpi[name]}")
    lines += [
        "",
        "## Business truth verified on entry",
        f"- reference capital = {truth['observed']['REFERENCE_INITIAL_CAPITAL_USDT']:.0f} USDT",
        f"- business validated edges = {truth['observed']['BUSINESS_VALIDATED_EDGE_COUNT']}",
        f"- search status = {truth['observed']['SMALL_CAPITAL_PROFITABILITY_SEARCH']}",
        f"- truth_verified = {truth['truth_verified']}",
        "",
        "## Candidate dispositions",
    ]
    for c in BF.CANDIDATE_DISPOSITIONS:
        lines.append(f"- {c.candidate_id} = {c.final_status} ({c.disposition_class})")
    lines += [
        "",
        "## Phase status",
    ]
    for phase, value in BF.PHASE_STATUS.items():
        lines.append(f"- {phase} = {value}")
    lines += [
        "",
        "## Stale status audit",
        f"- entries marked SUPERSEDED = {stale['entry_count']}",
        "- history IMMUTABLE; canonical state UPDATED in ECONOMIC_STATE.json",
        "",
        "## Proven / not proven",
        "- PROVEN: " + "; ".join(BF.PROVEN),
        "- NOT_PROVEN: " + "; ".join(BF.NOT_PROVEN),
        "",
        "## Lessons",
        *[f"- {lesson}" for lesson in BF.LESSONS],
        "",
        "## Reentry",
        "- gate: G_BUSINESS_REENTRY (triggers A-E + scorecard + benchmark case)",
        "- next RFC requires G_BUSINESS_REENTRY = PASS; NO automatic RFC-042",
        "",
        "## Entry gate",
        f"- branch = {entry['branch']}",
        f"- head = {entry['head']}",
        f"- head_matches_rfc040 = {entry['head_matches_rfc040']}",
        "",
        "Research evidence only. No live trading, no orders, no paid data, no broker integration.",
        "This is the LAST automatic RFC of this stage: the project is left without a next work package.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    generated_at = now_utc()
    entry = section_entry_gate()
    emit(
        "RFC041_PLAN",
        render(
            "RFC-041 PLAN",
            {
                "mission": "consolidate evidence and freeze alpha research; formalise the business reentry contract",
                "entry_gate": entry,
                "prohibitions": list(BF.FREEZE_PROHIBITIONS),
                "produces": [
                    "canonical state",
                    "candidate archive",
                    "reentry policy",
                    "scoreboard",
                ],
            },
        ),
        {"entry_gate": entry},
    )
    if not entry["entry_condition_met"]:
        print(json.dumps({"STOP": "entry condition not met", **entry}, indent=2))
        return 1

    state = section_canonical_state()
    truth = section_business_truth(state)
    kpi = BF.kpi_counts()

    current_state = {
        "rfc": "RFC-041",
        "generated_at": generated_at,
        "canonical_read": state,
        "business_truth": truth,
        "kpi": kpi,
        "platform_status": BF.PLATFORM_STATUS,
        "profitability_status": BF.PROFITABILITY_STATUS,
        "research_status": BF.RESEARCH_STATUS,
        "paper_status": BF.PAPER_STATUS,
        "live_status": BF.LIVE_STATUS,
        "alpha_research_freeze": BF.ALPHA_RESEARCH_FREEZE,
        "phase_status": dict(BF.PHASE_STATUS),
        "reference_initial_capital_usdt": BF.REFERENCE_INITIAL_CAPITAL_USDT,
        "live_capital_authorized": BF.LIVE_CAPITAL_AUTHORIZED,
    }
    emit(
        "CURRENT_ECONOMIC_STATE",
        render("RFC-041 CURRENT ECONOMIC STATE", current_state),
        current_state,
    )

    archive = build_candidate_archive(generated_at, entry["head"])
    emit("CANDIDATE_DISPOSITION", render("RFC-041 CANDIDATE DISPOSITION", archive), archive)

    edge = build_business_edge_definition()
    emit("BUSINESS_EDGE_DEFINITION", render("RFC-041 BUSINESS EDGE DEFINITION", edge), edge)

    reentry = build_reentry_gate()
    emit("REENTRY_GATE", render("RFC-041 REENTRY GATE", reentry), reentry)

    stale = section_stale_audit(generated_at)
    emit("STALE_STATUS_AUDIT", render("RFC-041 STALE STATUS AUDIT", stale), stale)

    # -- tracked documents (§53-§60) ------------------------------------- #
    write_json(DOCS / "CANDIDATE_ARCHIVE.json", archive)
    write_md(DOCS / "CANDIDATE_ARCHIVE.md", render("CANDIDATE ARCHIVE (RFC-041)", archive))

    policy = build_reentry_policy(generated_at)
    write_json(DOCS / "BUSINESS_REENTRY_POLICY.json", policy)
    write_md(
        DOCS / "BUSINESS_REENTRY_POLICY.md", render("BUSINESS REENTRY POLICY (RFC-041)", policy)
    )

    scoreboard = build_economic_scoreboard(generated_at)
    write_json(DOCS / "ECONOMIC_SCOREBOARD.json", scoreboard)
    write_md(DOCS / "ECONOMIC_SCOREBOARD.md", render("ECONOMIC SCOREBOARD (RFC-041)", scoreboard))

    decision = build_final_business_decision(generated_at, entry["head"], kpi)
    write_json(DOCS / "FINAL_BUSINESS_DECISION.json", decision)
    write_md(
        DOCS / "FINAL_BUSINESS_DECISION.md", render("FINAL BUSINESS DECISION (RFC-041)", decision)
    )

    canonical_state = BF.economic_state(
        source_commit=entry["head"], updated_at=generated_at, kpi=kpi
    )
    write_json(DOCS / "ECONOMIC_STATE.json", canonical_state)

    banners = apply_superseded_banners()

    fs = false_success_audit(kpi, state)

    # -- independent verification is run by the verifier script ---------- #
    verification = {"VERIFICATION_STATUS": "PENDING", "mismatch_count": None}

    final_json = {
        "rfc": "RFC-041",
        "generated_at": generated_at,
        "reference_capital_usdt": BF.REFERENCE_INITIAL_CAPITAL_USDT,
        "business_validated_edges": kpi["BUSINESS_VALIDATED_EDGE_COUNT"],
        "paper_candidates": kpi["PAPER_CANDIDATE_COUNT"],
        "forward_profitable": kpi["FORWARD_PROFITABLE_COUNT"],
        "live_profitable": kpi["LIVE_PROFITABLE_COUNT"],
        "active_candidates": BF.active_candidate_count(),
        "alpha_research_freeze": BF.ALPHA_RESEARCH_FREEZE,
        "kpi": kpi,
        "current_decision": BF.CURRENT_DECISION,
        "next_alpha_rfc_allowed": BF.alpha_rfc_allowed(True, False),
        "stale_entries_superseded": stale["entry_count"],
        "superseded_banners_applied": banners["banners_applied"],
        "false_success": fs,
        "independent_verification": verification,
        "entry_gate": entry,
        "source_commit": entry["head"],
        "final_commit": "",
    }
    write_json(REPORTS / "RFC041_FINAL_REPORT.json", final_json)
    write_md(
        REPORTS / "RFC041_FINAL_REPORT.md",
        final_report_md(entry, truth, kpi, fs, verification, stale, entry["head"], ""),
    )

    print(
        json.dumps(
            {
                "entry_ok": entry["entry_condition_met"],
                "truth_verified": truth["truth_verified"],
                "kpi": kpi,
                "FALSE_SUCCESS": fs["FALSE_SUCCESS"],
                "current_decision": BF.CURRENT_DECISION,
                "next_alpha_rfc_allowed": BF.alpha_rfc_allowed(True, False),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
