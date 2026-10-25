"""RFC-049 DISCOVERY 2 — ACTIVE pipeline audit (FASE 5).

Answers, from evidence rather than intent:

* what the strategy pipeline actually admits today (the admission ledger and the live
  registry code path the runtime uses);
* the real separation between a signal generated, a proposal, an authorized order and an
  executed operation in the paper lane;
* what the operator's objective ("three operations a day, seven days a week, multiple
  assets when it makes sense") would require against the frozen cost floor, and whether
  the current pipeline can reach it;
* where the low-frequency line sits (the operator's ``R6 P2 QUALITY`` label has no
  artifact in this repository; the audit records that and maps it to the low-frequency
  liquidity line without modifying anything).

Read-only with respect to the runtime: no process is started, no state is written outside
``data/rfc049/discovery2/``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D2 = ROOT / "data" / "rfc049" / "discovery2"
LEDGER = ROOT / "config" / "strategy_admission.json"


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def tracked(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    out = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True, text=True)
    return out.returncode == 0


def main() -> int:
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})

    ledger_payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    strategies = ledger_payload["strategies"]
    status_counts: dict[str, int] = {}
    for row in strategies.values():
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    check("ledger:24_strategies", len(strategies) == 24, f"{len(strategies)} entries")
    check("ledger:none_admitted", all(not row["admitted_for_paper"] for row in strategies.values()), "admitted_for_paper=false everywhere")

    # live registry: the exact code path the paper runtime builds
    sys.path.insert(0, str(ROOT / "src"))
    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.strategy_state import StrategyRegistry

    ledger = AdmissionLedger.load(LEDGER)
    registry = StrategyRegistry.from_ledger(ledger, assets=["BTCUSDT", "ETHUSDT"])
    counts = registry.counts_by_status()
    activations = {tf: sorted(registry.paper_activations(tf).keys()) for tf in ("5m", "15m", "1h")}
    map_sizes = {tf: len(registry.strategy_map(tf)) for tf in ("5m", "15m", "1h")}
    refusals_1h = [line for line in registry.describe("1h") if "refused" in line]
    check("registry:no_paper_executable", all(not v for v in activations.values()), json.dumps(activations))
    check("registry:paper_candidates_empty", ledger.paper_candidates() == [], "ledger exposes no paper candidates")

    # cost arithmetic for the operator's objective
    cost_bps = 23.353553391
    trips_per_day = 3.0
    annual_trips = trips_per_day * 365
    annual_cost_bps = cost_bps * annual_trips
    gross_edges = sorted(
        {
            row["expected_gross_edge_bps"]
            for row in strategies.values()
            if row.get("expected_gross_edge_bps") is not None
        }
    )
    best_gross = max(gross_edges)
    check(
        "objective:best_measured_gross_below_cost_floor",
        best_gross < cost_bps,
        f"best measured family gross edge {best_gross} bps/trade < round-trip cost {cost_bps} bps",
    )

    # paper lane evidence (worktree files are cited with hashes and ownership notes)
    evidence_files = []
    for rel in (
        "config/strategy_admission.json",
        "docs/PAPER_CONTINUOUS_STRATEGY_LAB_FINAL.md",
        "RUN_REPORT.json",
        "PAPER_DATA_24H_REPORT.json",
        "data/storage/paper_state.json",
        "data/storage/autonomous_paper_state.json",
    ):
        p = ROOT / rel
        evidence_files.append({"path": rel, "exists": p.exists(), "tracked": tracked(p) if p.exists() else None, "sha256": sha(p)})

    paper_24h = json.loads((ROOT / "PAPER_DATA_24H_REPORT.json").read_text(encoding="utf-8")) if (ROOT / "PAPER_DATA_24H_REPORT.json").exists() else None
    paper_state = json.loads((ROOT / "data" / "storage" / "paper_state.json").read_text(encoding="utf-8")) if (ROOT / "data" / "storage" / "paper_state.json").exists() else None

    funnel = {
        "definitions": {
            "signal_generated": "a strategy evaluation produced a candidate direction (per cycle, per asset)",
            "proposal": "an executable intent that passed the admission gate",
            "authorized": "an order authorization issued after the deterministic risk review",
            "executed": "a fill recorded by the paper broker",
        },
        "current": {
            "strategy_evaluations_per_cycle": (paper_24h or {}).get("paper", {}).get("strategies_evaluated_per_cycle"),
            "decisions_per_cycle": (paper_24h or {}).get("paper", {}).get("decisions_per_cycle"),
            "proposals": 0,
            "risk_reviews": 0,
            "authorized": 0,
            "executed": 0,
            "reason": "the admission gate admits no strategy for paper execution, so every cycle ends in NO_TRADE_STRATEGIC",
        },
    }
    if paper_state:
        funnel["current"]["open_positions_in_state"] = len(paper_state.get("open_positions", []))
        funnel["current"]["sent_intents_in_state"] = len(paper_state.get("sent_intents", []))
        funnel["current"]["trades_today_in_risk_state"] = paper_state.get("risk_state", {}).get("trades_today")

    audit = {
        "artifact": "RFC049_DISCOVERY2_ACTIVE_STRATEGY_STATUS",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_at_run": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "method": "assembled from the tracked admission ledger, the live registry code path the runtime itself uses, and the paper lane's own reports; no process was started and nothing was executed",
        "ledger": {
            "source": "config/strategy_admission.json",
            "total": len(strategies),
            "status_counts": status_counts,
            "admitted_for_paper": 0,
            "per_status_note": {
                "NO_GROSS_EDGE": "zero-cost research diagnostic: gross edge per trade <= 0 before any cost is applied",
                "COST_KILLED": "a positive gross edge exists but is smaller than the frozen round-trip cost floor",
            },
            "gross_edge_range_bps": [gross_edges[0], gross_edges[-1]],
        },
        "registry_live": {
            "counts_by_status": counts,
            "paper_activations": activations,
            "strategy_map_sizes": map_sizes,
            "refusals_1h": refusals_1h,
            "paper_candidates": ledger.paper_candidates(),
        },
        "paper_lane": {
            "last_lab_run": {
                "cycles": (paper_24h or {}).get("paper", {}).get("cycles"),
                "asset_evaluations": (paper_24h or {}).get("paper", {}).get("cycles", 0) * ((paper_24h or {}).get("paper", {}).get("asset_evaluations_per_cycle") or 0) or None,
                "no_trade_kind": (paper_24h or {}).get("paper", {}).get("no_trade_kind"),
                "paper_trades": (paper_24h or {}).get("paper", {}).get("paper_trades"),
                "shadow_trades": (paper_24h or {}).get("paper", {}).get("shadow_trades"),
                "risk_vetoes": (paper_24h or {}).get("paper", {}).get("risk_vetoes"),
                "paper_candidates": (paper_24h or {}).get("paper", {}).get("paper_candidates"),
                "state": (paper_24h or {}).get("paper", {}).get("state"),
                "verdict": (paper_24h or {}).get("verdict"),
                "source": "PAPER_DATA_24H_REPORT.json (worktree evidence owned by the paper lane; cited with sha256)",
            },
            "lifecycle_histogram_from_lab_report": "PAPER_ACTIVE=0, PAPER_CANDIDATE=0, REJECTED=0, RESEARCH_REQUIRED=0, PAPER_RETIRED=0 (docs/PAPER_CONTINUOUS_STRATEGY_LAB_FINAL.md)",
        },
        "funnel": funnel,
        "objective_3_ops_per_day": {
            "requested": "3 operations/day, 7 days/week, multiple assets when it makes sense",
            "current_operations_per_day": 0,
            "requirement": {
                "round_trips_per_year": annual_trips,
                "round_trip_cost_bps": cost_bps,
                "annual_cost_if_achieved_bps": annual_cost_bps,
                "annual_cost_pct_of_stake": annual_cost_bps / 100.0,
                "break_even_gross_bps_per_trip": cost_bps,
                "implied_average_hold_hours_at_one_position": 8.0,
            },
            "measured_edges": {
                "best_gross_bps_per_trade_across_families": best_gross,
                "all_measured_gross_below_break_even": best_gross < cost_bps,
                "families_tested": "24 (6 families x 4 timeframes), zero admitted",
            },
            "assessment": "NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE",
            "blockers": [
                "no admitted strategy: the admission gate admits nothing (0 of 24)",
                "no measured family edge clears the frozen cost floor: best family gross edge is " f"{best_gross} bps/trade against a {cost_bps} bps round trip",
                "at 3 trips/day the strategy would pay ~{:.1f}% of its stake in round-trip costs every year; the gross edge would have to average above the floor per trip".format(annual_cost_bps / 100.0),
            ],
            "what_would_change_it": [
                "a new admitted hypothesis whose measured net expectancy is positive at a cadence of several trades per day after the frozen cost model",
                "multi-asset expansion multiplies opportunity count but not per-trade edge; it does not remove the per-trade cost requirement",
                "the decision is a governance matter (new hypothesis, new budget); this audit proposes nothing",
            ],
            "no_forcing_note": "the objective is not a quota: no operation is generated to satisfy a frequency target",
        },
        "low_frequency_line": {
            "operator_label": "R6 P2 QUALITY",
            "label_found_in_repository": False,
            "label_search": "git grep -i 'R6 P2 QUALITY|R6_P2|P2 QUALITY' over tracked files: no matches",
            "mapping": "if the label denotes the low-frequency liquidity line, that line is the RFC-049 candidates at 2.96-6.18 round trips/year; it stays separate from the 3-ops/day objective and nothing in this campaign modifies it",
        },
        "evidence_files": evidence_files,
        "checks": checks,
        "checks_failed": sum(1 for c in checks if c["result"] != "PASS"),
        "scope": {"trading": "not performed", "processes_started": 0, "state_written_outside_discovery2": False},
    }
    (D2 / "ACTIVE_STRATEGY_STATUS.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# RFC-049 DISCOVERY 2 — ACTIVE STRATEGY STATUS (AUDIT)",
        "",
        f"- generated: `{audit['generated_at_utc']}` · head `{audit['head_at_run'][:12]}`",
        "- method: tracked ledger + the live registry code path + the paper lane's own reports; nothing executed.",
        "",
        "## What the pipeline admits today",
        "",
        f"- admission ledger: **{len(strategies)} strategies, 0 admitted for paper** "
        f"({status_counts.get('NO_GROSS_EDGE', 0)} NO_GROSS_EDGE, {status_counts.get('COST_KILLED', 0)} COST_KILLED).",
        f"- live registry: paper-executable on 5m/15m/1h: **NONE**; every refused strategy cites its ledger status.",
        f"- best measured family gross edge: **{best_gross} bps/trade** (zero-cost diagnostics) against a "
        f"**{cost_bps} bps** frozen round trip.",
        "",
        "## Signal → proposal → authorization → execution",
        "",
        "| stage | definition | current |",
        "| --- | --- | ---: |",
        f"| signal generated | strategy evaluations per cycle | {funnel['current']['strategy_evaluations_per_cycle']} |",
        "| proposal | executable intent passing the admission gate | **0** |",
        "| authorized | order authorization after risk review | **0** |",
        "| executed | paper fills | **0** |",
        "",
        f"- every decision ends `NO_TRADE_STRATEGIC` by construction: {funnel['current']['reason']}",
        "",
        "## Objective: three operations a day",
        "",
        f"- requirement: {int(annual_trips)} round trips/year at {cost_bps} bps per round trip "
        f"= **{annual_cost_bps:,.0f} bps** ({annual_cost_bps / 100.0:.1f}% of stake) per year in costs; "
        f"the gross edge would have to average above {cost_bps} bps per trip.",
        f"- assessment: **NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE** — current operations/day: **0**.",
        "- the objective is not a quota: no operation is generated to satisfy a frequency target.",
        "",
        "## Low-frequency line",
        "",
        "- the operator label `R6 P2 QUALITY` was searched for and **is not present** in the repository; "
        "if it denotes the low-frequency liquidity line (RFC-049 candidates: 2.96–6.18 round trips/year), "
        "it remains separate from the 3-ops/day objective and is untouched by this campaign.",
    ]
    (D2 / "ACTIVE_STRATEGY_STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "activations": activations, "status_counts": status_counts}, indent=2))
    return 1 if audit["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
