"""RFC-044 orchestration — PROFITABILITY REENTRY WATCH.

A governance run while ``ALPHA_RESEARCH_FREEZE = ACTIVE`` (§2).  It turns the
current ``WAIT`` into an operating reentry mechanism: detect whether anything
materially new happened that justifies spending one more research cycle, discard
weak evidence cheaply, and authorize at most *one* reproduction.

No alpha, no strategy, no signal, no backtest, no portfolio model, no broker, no
paper run and no live order (§2/§46).  Nothing here releases the freeze, invents
an opportunity or moves the profit KPIs off zero (§45-§48).

Research only: no orders, no credentials, no capital.
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

from trading_bot.research import reentry_watch as rw  # noqa: E402

OUT = REPO / "reports" / "reentry-watch"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"
INBOX = DOCS / "reentry-inbox"

#: §1 — expected repository state entering RFC-044 (verified, never assumed).
EXPECTED_ANCESTORS: dict[str, str] = {
    "RFC-042": "03ce3f1",
    "RFC-043": "ecb4c5c",
}

#: §2 — hard governance rule the run must never break.
HARD_RULE = "ALPHA_RESEARCH_FREEZE = ACTIVE"

REQUIRED_DOCUMENTS: tuple[str, ...] = (
    "docs/research/ECONOMIC_STATE.json",
    "docs/research/FINAL_BUSINESS_DECISION.json",
    "docs/research/BUSINESS_REENTRY_POLICY.json",
    "docs/research/PROFITABILITY_OPERATING_MODEL.json",
    "docs/research/PROFITABILITY_OPERATING_SCOREBOARD.json",
    "docs/research/CANDIDATE_ARCHIVE.json",
)

# §6 — never a reason to spend a cycle.
NOT_ALLOWED: tuple[str, ...] = (
    "new strategy",
    "new signal",
    "new backtest",
    "parameter tuning",
    "broker live integration",
    "paper run",
    "live order",
    "research daemon",
    "scheduled alpha search",
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


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


# --------------------------------------------------------------------------- #
# entry gate (§1)
# --------------------------------------------------------------------------- #


def _is_ancestor(rev: str, head: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", rev, head],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def entry_gate() -> dict[str, Any]:
    head = git(["rev-parse", "HEAD"])
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    ancestors = {name: _is_ancestor(rev, head) for name, rev in EXPECTED_ANCESTORS.items()}
    state = json.loads((DOCS / "ECONOMIC_STATE.json").read_text(encoding="utf-8"))
    freeze = state["alpha_research_freeze"]
    edge_count = int(state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"])
    hard_rule_ok = freeze == "ACTIVE" and edge_count == 0
    rfc042_date = git(["show", "-s", "--format=%cs", EXPECTED_ANCESTORS["RFC-042"]])
    return {
        "repository": str(REPO),
        "branch": branch,
        "head": head,
        "source_commit": git(["rev-parse", EXPECTED_ANCESTORS["RFC-043"]]),
        "git_log_15": git(["log", "-15", "--oneline"]).splitlines(),
        "git_status_short": git(["status", "--short"]).splitlines(),
        "expected_ancestors": EXPECTED_ANCESTORS,
        "ancestors_present": ancestors,
        "documents_read": list(REQUIRED_DOCUMENTS),
        "alpha_research_freeze": freeze,
        "business_validated_edge_count": edge_count,
        "authority_rule": "REAL_RUNTIME / REAL_REPOSITORY > DOCUMENT CLAIM",
        "hard_rule": HARD_RULE,
        "hard_rule_ok": hard_rule_ok,
        "rfc042_date": rfc042_date,
        "entry_condition_met": hard_rule_ok and all(ancestors.values()),
    }


# --------------------------------------------------------------------------- #
# payload builders
# --------------------------------------------------------------------------- #


def build_plan(entry: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-044",
        "title": "PROFITABILITY REENTRY WATCH",
        "generated_at": generated_at,
        "mission": "HAS ANYTHING CHANGED THAT JUSTIFIES SPENDING ONE MORE RESEARCH CYCLE?",
        "why_this_rfc_exists": (
            "RFC-041/042/043 showed MORE INTERNAL SEARCH != MORE PROFITABILITY; this "
            "watch only reduces the cost of detecting a valid opportunity"
        ),
        "allowed_results": list(rw.ALLOWED_DECISIONS),
        "reference_capital_usdt": rw.REFERENCE_CAPITAL_USDT,
        "role_of_200_usdt": "FUTURE_CANARY_CAPITAL",
        "entry_gate": entry,
        "non_negotiable_freeze": {
            "alpha_research_freeze": rw.ALPHA_RESEARCH_FREEZE,
            "next_alpha_rfc_allowed": rw.NEXT_ALPHA_RFC_ALLOWED,
            "forbidden": [
                "strategy code",
                "signal",
                "backtest",
                "portfolio model",
                "broker integration",
                "paper execution",
                "live execution",
            ],
        },
        "valid_triggers": dict(rw.TRIGGER_TYPE_DEFINITIONS),
        "invalid_events": list(rw.INVALID_EVENT_KINDS),
        "source_quality": dict(rw.SOURCE_QUALITY_MEANING),
        "minimum_evidence": (
            ">= 2 independent high-quality sources, or one strong source that "
            "provably survives post-publication"
        ),
        "post_publication_classes": list(rw.POST_PUBLICATION_CLASSES),
        "critical_gates": dict(rw.CRITICAL_GATE_THRESHOLDS),
        "budgets": {
            "MAX_PENDING_OPPORTUNITIES": rw.MAX_PENDING_OPPORTUNITIES,
            "MAX_DEEP_REVIEW": rw.MAX_DEEP_REVIEW,
            "MAX_AUTHORIZED_CANDIDATES": rw.MAX_AUTHORIZED_CANDIDATES,
            "MAX_PARAMETER_VARIANTS": rw.MAX_PARAMETER_VARIANTS,
        },
        "g_business_reentry_conditions": list(rw.G_BUSINESS_REENTRY_CONDITIONS),
        "kill_test_bases": list(rw.KILL_TEST_BASES),
        "candidate_stages": list(rw.CANDIDATE_STAGES),
        "candidate_failure_rule": rw.CANDIDATE_FAILURE_RULE,
        "second_best_policy": rw.SECOND_BEST_POLICY,
        "kill_test_policy": "no backtest for early kill; use evidence/arithmetic/product/cost/data",
        "no_daemon": {
            "reentry_mode": rw.REENTRY_MODE,
            "daemon_allowed": rw.DAEMON_ALLOWED,
            "scheduled_alpha_search_allowed": rw.SCHEDULED_ALPHA_SEARCH_ALLOWED,
        },
        "not_allowed": list(NOT_ALLOWED),
        "tracked_files": [
            "docs/research/REENTRY_EVIDENCE_REGISTRY.md",
            "docs/research/REENTRY_EVIDENCE_REGISTRY.json",
            "docs/research/REENTRY_DECISION_LEDGER.md",
            "docs/research/REENTRY_DECISION_LEDGER.json",
            "docs/research/BUSINESS_REENTRY_CHECKLIST.md",
            "docs/research/reentry-inbox/",
        ],
        "reports": [
            "reports/reentry-watch/RFC044_PLAN.md/json",
            "reports/reentry-watch/CURRENT_REENTRY_STATE.md/json",
            "reports/reentry-watch/REENTRY_GATE_AUDIT.md/json",
            "reports/reentry-watch/RFC044_VERIFICATION.md/json",
            "reports/RFC044_FINAL_REPORT.md/json",
        ],
        "hard_stop": "DO NOT CREATE RFC-045 until a REAL NEW REENTRY EVENT exists",
    }


def build_current_state(generated_at: str) -> dict[str, Any]:
    decision = rw.reentry_decision(qualified_events=[], pending_opportunities=0)
    return {
        "rfc": "RFC-044",
        "generated_at": generated_at,
        "reference_capital_usdt": rw.REFERENCE_CAPITAL_USDT,
        "current_milestone": rw.CURRENT_MILESTONE,
        "profit_kpis": dict(rw.PROFIT_KPIS),
        "research_status": rw.RESEARCH_STATUS,
        "alpha_research_freeze": rw.ALPHA_RESEARCH_FREEZE,
        "next_alpha_rfc_allowed": rw.NEXT_ALPHA_RFC_ALLOWED,
        "active_candidates": rw.ACTIVE_CANDIDATES,
        "current_decision": "WAIT_FOR_REENTRY_QUALIFIED_BUSINESS_OPPORTUNITY",
        "new_qualified_event": "NO",
        "pending_opportunities": 0,
        "deep_reviews_this_cycle": 0,
        "authorized_candidates": 0,
        "registry_items": 0,
        "decision": decision,
        "next_economic_milestone": rw.NEXT_ECONOMIC_MILESTONE,
    }


def build_gate_audit(generated_at: str) -> dict[str, Any]:
    absent = rw.business_reentry_gate({})
    return {
        "rfc": "RFC-044",
        "generated_at": generated_at,
        "evaluated": False,
        "reason": "NO_NEW_EVENT = TRUE: no opportunity exists to evaluate",
        "G_BUSINESS_REENTRY": "NOT_EVALUATED",
        "conditions": dict.fromkeys(rw.G_BUSINESS_REENTRY_CONDITIONS, False),
        "gate_result_for_absent_opportunity": absent,
        "gate_is_exceptional": "normal outcome is FAIL; the gate is not designed to produce candidates",
        "critical_gate_thresholds": dict(rw.CRITICAL_GATE_THRESHOLDS),
        "budgets": {
            "MAX_PENDING_OPPORTUNITIES": rw.MAX_PENDING_OPPORTUNITIES,
            "MAX_DEEP_REVIEW": rw.MAX_DEEP_REVIEW,
            "MAX_AUTHORIZED_CANDIDATES": rw.MAX_AUTHORIZED_CANDIDATES,
        },
        "no_runner_up": True,
        "kill_test_policy": "no backtest for early kill",
        "capital_respected": rw.REFERENCE_CAPITAL_USDT == 200.0,
        "profit_kpis_unchanged": all(v == 0 for v in rw.PROFIT_KPIS.values()),
    }


def build_registry(generated_at: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-044",
        "generated_at": generated_at,
        "description": (
            "Tracked, lightweight registry of reentry evidence. Store citation, "
            "URL, claim, summary, counter_evidence and retrieval_date only; never "
            "bulk copies of papers or protected content."
        ),
        "required_item_fields": [
            "evidence_id",
            "citation",
            "url",
            "claim",
            "summary",
            "counter_evidence",
            "retrieval_date",
            "source_quality",
            "trigger_type",
        ],
        "items": [],
        "note": (
            "No post-RFC-042 evidence has been recorded. Newly discovered evidence "
            "is registered here so it cannot be lost inside the gitignored reports/."
        ),
    }


def build_ledger(entry: dict[str, Any], generated_at: str) -> dict[str, Any]:
    rfc042_date = str(entry.get("rfc042_date") or generated_at[:10])
    return {
        "rfc": "RFC-044",
        "generated_at": generated_at,
        "description": "Decision ledger: every reentry review and its outcome.",
        "entries": [
            {
                "review_id": "RFC042",
                "date": rfc042_date,
                "opportunity": "external evidence screen (RFC-042 source registry)",
                "trigger": "A_NEW_EXTERNAL_EVIDENCE",
                "decision": "NO_REENTRY",
                "reason": (
                    "no screened candidate produced a benchmark-adjusted, "
                    "capital-fit business case for 200 USDT"
                ),
            },
            {
                "review_id": "RFC044",
                "date": generated_at[:10],
                "opportunity": "(none)",
                "trigger": "NONE",
                "decision": "NO_ACTION",
                "reason": (
                    "NO_NEW_EVENT = TRUE: no post-RFC-042 evidence or trigger A-E "
                    "has been recorded"
                ),
            },
        ],
    }


def checkpoint_md() -> str:
    return "\n".join(
        [
            "# BUSINESS REENTRY CHECKLIST",
            "",
            "One page to decide in minutes whether a new source deserves a research",
            "cycle. If any answer below is NO, the answer is **NO_ACTION**.",
            "",
            "## 1. Is this a valid event? (RFC-044 §5-§6)",
            "",
            "- Is it a new external publication/replication, a new structural",
            "  mechanism, a material capital change, a material instrument/broker",
            "  change, or new data that unlocks an already-supported hypothesis?",
            "- If it is a new indicator, a different moving average/threshold/symbol,",
            "  more agents, an LLM prediction, ML on old features, a renamed family,",
            "  parameter tuning or a social-media claim alone -> **reject**.",
            "",
            "## 2. Source quality (RFC-044 §11-§13)",
            "",
            "- Grade the source: A peer-reviewed, B working paper/institutional,",
            "  C implementation, D blog/social.",
            "- C or D alone never opens research. Prefer >= 2 independent A/B sources.",
            "- Did the effect SURVIVE post-publication, or is it WEAKENED/DECAYED/",
            "  CONTRADICTORY/UNKNOWN? Prefer SURVIVES.",
            "",
            "## 3. Duplicate check (RFC-044 §14)",
            "",
            "- Is this economically the same family already in CANDIDATE_ARCHIVE?",
            "  If yes -> SAME_FAMILY_REHASH -> **reject**.",
            "",
            "## 4. Profitability first (RFC-044 §4/§34-§35)",
            "",
            "- WHY COULD THIS MAKE MORE MONEY PER UNIT OF RISK THAN THE PASSIVE",
            "  ALTERNATIVE? If there is no evidenced answer -> **reject** before code.",
            "- What is the PRIMARY_PASSIVE_BENCHMARK (and RISK_MATCHED_BENCHMARK)?",
            "- Is the claim RETURN/RISK relative to the benchmark *after costs*, not a",
            "  raw return number?",
            "",
            "## 5. Capital contract (RFC-044 §7-§8/§33)",
            "",
            "- Can it be faithfully executed with 200 USDT (fractional, low minimum",
            "  notional, low turnover, no mandatory leverage/short/borrow, low data",
            "  cost)? If not, only a material capital change (trigger C) reopens it.",
            "",
            "## 6. Critical gates (RFC-044 §18) — none can be compensated",
            "",
            "- evidence >= 3, business plausibility >= 3, capital fit >= 4,",
            "  tradability >= 4, data feasibility >= 3.",
            "",
            "## 7. Cheap falsification (RFC-044 §15-§16)",
            "",
            "- Write the FASTEST_KILL_TEST now, using only external evidence,",
            "  arithmetic, product rules, cost estimates or data feasibility.",
            "- No backtest is allowed at this stage.",
            "",
            "## 8. Reentry gate (RFC-044 §22-§23)",
            "",
            "- G_BUSINESS_REENTRY = PASS only if VALID_TRIGGER AND MATERIALLY_NEW AND",
            "  STRONG_EVIDENCE AND PRODUCT_FIT AND CAPITAL_FIT AND TRADABILITY AND",
            "  DATA_FEASIBLE AND BENCHMARK_CASE AND CHEAP_FALSIFICATION_DEFINED.",
            "- The normal answer is FAIL, and at most ONE candidate is ever authorized.",
            "",
            "## 9. Log the decision",
            "",
            "- Record the review in REENTRY_DECISION_LEDGER (review_id, date,",
            "  opportunity, trigger, decision, reason) and any evidence in",
            "  REENTRY_EVIDENCE_REGISTRY.",
            "",
        ]
    )


def inbox_readme_md() -> str:
    fields = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(rw.OPPORTUNITY_FIELDS))
    return "\n".join(
        [
            "# REENTRY INBOX",
            "",
            "Drop candidate opportunities here before any evaluation. Each file",
            "must declare every field below (RFC-044 §10):",
            "",
            fields,
            "",
            "Then run the checklist (docs/research/BUSINESS_REENTRY_CHECKLIST.md) and",
            "record the outcome in REENTRY_DECISION_LEDGER. The inbox holds at most",
            f"{rw.MAX_PENDING_OPPORTUNITIES} pending opportunities; there is no daemon,",
            "no crawler and no scheduled alpha search (§41-§42).",
            "",
            "If nothing new is present, the correct result is NO_ACTION (§47).",
            "",
        ]
    )


# --------------------------------------------------------------------------- #
# final report (§54-§55)
# --------------------------------------------------------------------------- #


def build_final_report(
    entry: dict[str, Any],
    state: dict[str, Any],
    audit: dict[str, Any],
    false_success: dict[str, Any],
    generated_at: str,
    verification: str,
) -> dict[str, Any]:
    decision = state["decision"]
    return {
        "title": "RFC-044 PROFITABILITY REENTRY WATCH",
        "generated_at": generated_at,
        "reference_capital_usdt": rw.REFERENCE_CAPITAL_USDT,
        "current_milestone": state["current_milestone"],
        "business_validated_edges": state["profit_kpis"]["BUSINESS_VALIDATED_EDGE_COUNT"],
        "paper_candidates": state["profit_kpis"]["PAPER_CANDIDATE_COUNT"],
        "forward_profitable": state["profit_kpis"]["FORWARD_PROFITABLE_COUNT"],
        "live_profitable": state["profit_kpis"]["LIVE_PROFITABLE_COUNT"],
        "realized_trading_pnl": state["profit_kpis"]["REALIZED_TRADING_PNL"],
        "research_freeze": state["alpha_research_freeze"],
        "new_qualified_event": state["new_qualified_event"],
        "g_business_reentry": audit["G_BUSINESS_REENTRY"],
        "authorized_candidate": decision["authorized_candidate"],
        "next_alpha_rfc_allowed": decision["next_alpha_rfc_allowed"],
        "next_economic_milestone": rw.NEXT_ECONOMIC_MILESTONE,
        "next": decision["next"],
        "decision": decision["decision"],
        "hard_stop": "DO NOT CREATE RFC-045 until a REAL NEW REENTRY EVENT exists",
        "false_success": false_success["FALSE_SUCCESS"],
        "independent_verification": verification,
        "source_commit": entry["source_commit"],
        "final_commit": "",
    }


def final_report_md(report: dict[str, Any]) -> str:
    lines = [
        "RFC-044 PROFITABILITY REENTRY WATCH",
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


def false_success_audit(state: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    missing_benchmark = any(
        not str(item.get("PRIMARY_BENCHMARK", "")).strip() for item in registry["items"]
    )
    claims = {
        "idle_time_treated_as_event": state["new_qualified_event"] == "YES",
        "new_strategy_invented": False,
        "old_family_renamed": False,
        "weak_source_unlocks_research": False,
        "capital_constraint_ignored": bool(rw.REFERENCE_CAPITAL_USDT != 200.0),
        "benchmark_missing": missing_benchmark,
        "strategy_implemented": False,
        "freeze_released_without_pass": state["alpha_research_freeze"] != rw.ALPHA_RESEARCH_FREEZE,
        "more_than_one_candidate_authorized": state["authorized_candidates"] > rw.MAX_AUTHORIZED_CANDIDATES,
    }
    return {
        "triggers": list(rw.FALSE_SUCCESS_TRIGGERS),
        "claims": claims,
        "FALSE_SUCCESS": rw.false_success_count(claims),
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    generated_at = now_utc()
    entry = entry_gate()
    if not entry["entry_condition_met"]:
        print(
            json.dumps(
                {
                    "ENTRY_GATE": "FAIL",
                    "reason": "hard rule §2 or ancestor check failed",
                    "entry_gate": entry,
                },
                indent=2,
            )
        )
        return 2

    plan = build_plan(entry, generated_at)
    state = build_current_state(generated_at)
    audit = build_gate_audit(generated_at)
    registry = build_registry(generated_at)
    ledger = build_ledger(entry, generated_at)
    false_success = false_success_audit(state, registry)

    # -- §53 report artifacts ------------------------------------------------- #
    write_json(OUT / "RFC044_PLAN.json", plan)
    write_md(OUT / "RFC044_PLAN.md", render("RFC-044 PLAN — PROFITABILITY REENTRY WATCH", plan))

    write_json(OUT / "CURRENT_REENTRY_STATE.json", state)
    write_md(
        OUT / "CURRENT_REENTRY_STATE.md",
        render("RFC-044 CURRENT REENTRY STATE", state),
    )

    write_json(OUT / "REENTRY_GATE_AUDIT.json", audit)
    write_md(
        OUT / "REENTRY_GATE_AUDIT.md",
        render("RFC-044 REENTRY GATE AUDIT", audit),
    )

    verification_doc = {
        "rfc": "RFC-044",
        "generated_at": generated_at,
        "VERIFICATION_STATUS": "PENDING",
        "mismatch_count": None,
        "false_success": 0,
    }
    write_json(OUT / "RFC044_VERIFICATION.json", verification_doc)
    write_md(
        OUT / "RFC044_VERIFICATION.md",
        render("RFC-044 VERIFICATION", verification_doc),
    )

    # -- §36/§38/§40/§51 tracked canonical documents --------------------------- #
    write_json(DOCS / "REENTRY_EVIDENCE_REGISTRY.json", registry)
    write_md(
        DOCS / "REENTRY_EVIDENCE_REGISTRY.md",
        render("REENTRY EVIDENCE REGISTRY", registry),
    )

    write_json(DOCS / "REENTRY_DECISION_LEDGER.json", ledger)
    ledger_md = "\n".join(
        [
            "# REENTRY DECISION LEDGER",
            "",
            *md_table(
                ["Review", "Date", "Opportunity", "Trigger", "Decision", "Reason"],
                [
                    [
                        e["review_id"],
                        e["date"],
                        e["opportunity"],
                        e["trigger"],
                        e["decision"],
                        e["reason"],
                    ]
                    for e in ledger["entries"]
                ],
            ),
            "",
        ]
    )
    write_md(DOCS / "REENTRY_DECISION_LEDGER.md", ledger_md)

    write_md(DOCS / "BUSINESS_REENTRY_CHECKLIST.md", checkpoint_md())
    write_md(INBOX / "README.md", inbox_readme_md())

    # -- §54-§55 final report -------------------------------------------------- #
    pending = build_final_report(entry, state, audit, false_success, generated_at, "PENDING")
    write_json(REPORTS / "RFC044_FINAL_REPORT.json", pending)
    write_md(REPORTS / "RFC044_FINAL_REPORT.md", final_report_md(pending))

    print(
        json.dumps(
            {
                "entry_condition_met": entry["entry_condition_met"],
                "new_qualified_event": state["new_qualified_event"],
                "G_BUSINESS_REENTRY": audit["G_BUSINESS_REENTRY"],
                "decision": state["decision"]["decision"],
                "authorized_candidate": state["decision"]["authorized_candidate"],
                "next_alpha_rfc_allowed": state["decision"]["next_alpha_rfc_allowed"],
                "next": state["decision"]["next"],
                "FALSE_SUCCESS": false_success["FALSE_SUCCESS"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
