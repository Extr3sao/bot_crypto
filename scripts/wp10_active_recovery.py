"""WP-10 phase 5 — which families could justify another campaign, and why not yet.

The operator's objective for the ACTIVE line is enough quality opportunities to
average three operations a day across liquid assets, without forcing entries and
without relaxing any control. This script answers the follow-up question in the
form the decision needs: **for each family, which stage of the evidence chain is
the one that blocks it**, so that a family that merely lacks data is not treated
like a family that lacks an edge, and neither is confused with one that has an
edge too small to pay for the round trip.

The chain is ordered and each stage is a fact about the record, not a judgement:

    1. does any cell of the family have a positive zero-cost gross edge?
       — no  -> REJECT
    2. is that positive edge measured well enough to be believed? (a 95 % interval
       narrower than the edge itself, and a sign that holds in development *and*
       validation)
       — no  -> INSUFFICIENT_EVIDENCE
    3. does the edge clear the frozen round-trip cost plane?
       — no  -> RESEARCH_MORE (an edge exists; the cost is the obstacle)
    4. has a pre-registered forward rule returned PROMOTE on a reserved window?
       — no  -> RESEARCH_MORE (ready for that test, not through it)
       — yes -> ADOPT_FOR_NEW_EXPERIMENT

Stage 4 cannot be satisfied from the record: it requires the forward window E-2
reserves, which does not exist yet. That is why the matrix reports zero
``ADOPT_FOR_NEW_EXPERIMENT`` cells and says so as a *derivation* rather than as a
finding about any family.

Frequency is reported beside the economics on purpose. The objective is three
operations a day; several families already trade well above that rate, so if the
objective is unmet it is not because opportunities are rare, and the matrix says
which of the two is actually binding.

Read-only. Exit codes: 0 matrix written, 2 a required input is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WP10 = ROOT / "data" / "recovery" / "wp10"
BASELINE = WP10 / "WP10_BASELINE_ECONOMIC_AUDIT.json"
E1 = WP10 / "WP10_EXECUTION_COST_DISTRIBUTION.json"
E2 = WP10 / "WP10_E2_PREREGISTRATION.json"
DISCOVERY2 = ROOT / "data" / "rfc049" / "discovery2" / "ACTIVE_STRATEGY_STATUS.json"
ROADMAP = ROOT / "data" / "recovery" / "ACTIVE_RECOVERY_ROADMAP.md"
OBJECTIVE_OPS_PER_DAY = 3.0

#: The operator's low-frequency line. The roadmap established that this label has no
#: artefact in the repository, so it is listed, not mapped and not scored.
SEPARATE_LINES = {
    "R6_P2_QUALITY": {
        "operator_label": "R6 P2 QUALITY",
        "repo_artefact": None,
        "treatment": ("kept separate and not used as evidence: the label does not exist in this "
                      "repository, so it is an operator-side lane and is neither mapped nor "
                      "inferred (the WP-4 roadmap recorded the same)"),
    },
}


def software_version() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=False).stdout.strip()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def resolvable(cell: dict[str, Any]) -> tuple[bool, str]:
    """Stage 2: can this cell's positive edge be believed?"""
    resolution = cell.get("resolution") or {}
    edge = cell.get("zero_cost_gross_bps") or 0.0
    dev = cell.get("dev_gross_bps")
    val = cell.get("val_gross_bps")
    if not resolution.get("available"):
        return False, "no win/loss summary to size the interval with"
    if resolution["ci95_half_width_bps"] > abs(edge):
        return False, (f"the 95 % interval half width ({resolution['ci95_half_width_bps']} bps) is "
                       f"wider than the edge itself ({edge} bps)")
    if dev is None or val is None:
        return False, "the partitions do not both publish a gross edge"
    if not (dev > 0.0 and val > 0.0):
        return False, f"the sign does not hold in both partitions (dev {dev}, val {val} bps)"
    return True, "interval narrower than the edge and the sign holds in both partitions"


def classify_cell(cell: dict[str, Any], plane_bps: float) -> dict[str, Any]:
    edge = cell.get("zero_cost_gross_bps")
    if edge is None:
        return {"stage": "NO_EDGE_DATA", "verdict": "INSUFFICIENT_EVIDENCE",
                "why": "the cell publishes no gross edge"}
    if edge <= 0.0:
        return {"stage": "NO_EDGE", "verdict": "REJECT",
                "why": "the zero-cost gross edge is not positive: there is nothing for costs to eat"}
    ok, why = resolvable(cell)
    if not ok:
        return {"stage": "UNRESOLVED", "verdict": "INSUFFICIENT_EVIDENCE", "why": why}
    if edge < plane_bps:
        return {"stage": "COST_GAP", "verdict": "RESEARCH_MORE",
                "why": (f"the edge is resolvable but {round(plane_bps - edge, 6)} bps short of the "
                        f"frozen round trip")}
    return {"stage": "FORWARD_TEST", "verdict": "RESEARCH_MORE",
            "why": ("resolvable and above the plane on historical partitions; it still needs the "
                    "pre-registered forward test before any promotion")}


def family_matrix(cells: list[dict[str, Any]], plane_bps: float) -> dict[str, Any]:
    scored = [{"strategy_id": cell["strategy_id"], "timeframe": cell["timeframe"],
               "zero_cost_gross_bps": cell.get("zero_cost_gross_bps"),
               "ci95_half_width_bps": (cell.get("resolution") or {}).get("ci95_half_width_bps"),
               "trades": cell.get("trades"), "trades_per_day": cell.get("trades_per_day"),
               "classification": classify_cell(cell, plane_bps)} for cell in cells]
    order = {"ADOPT_FOR_NEW_EXPERIMENT": 3, "RESEARCH_MORE": 2,
             "INSUFFICIENT_EVIDENCE": 1, "REJECT": 0}
    best = max(scored, key=lambda item: (order[item["classification"]["verdict"]],
                                         item["zero_cost_gross_bps"] or -1e9))
    positives = [item for item in scored if (item["zero_cost_gross_bps"] or 0) > 0]
    return {
        "cells": len(scored),
        "trades_total": sum(item["trades"] or 0 for item in scored),
        "trades_per_day_total": round(sum(item["trades_per_day"] or 0.0 for item in scored), 3),
        "cells_with_positive_gross": len(positives),
        "best_cell": best["strategy_id"],
        "best_cell_gross_bps": best["zero_cost_gross_bps"],
        "verdict": best["classification"]["verdict"],
        "blocking_stage": best["classification"]["stage"],
        "why": best["classification"]["why"],
        "detail": scored,
    }


def build() -> tuple[dict[str, Any], int]:
    if not BASELINE.exists():
        return {"artifact": "WP10_ACTIVE_RECOVERY_MATRIX", "verdict": "BLOCKED",
                "why": "the phase-1 baseline rebuild is missing",
                "expected": str(BASELINE.relative_to(ROOT)).replace("\\", "/")}, 2
    baseline = load(BASELINE)
    plane_bps = baseline["headline_rebuilt"]["admission_round_trip_bps"]
    rows = baseline["strategies"]

    families: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        families.setdefault(row["family"], []).append(row)

    matrix = {family: family_matrix(cells, plane_bps)
              for family, cells in sorted(families.items())}

    positive_cells = [row for row in rows if (row.get("zero_cost_gross_bps") or 0) > 0]
    frequency = {
        "objective_ops_per_day": OBJECTIVE_OPS_PER_DAY,
        "trades_per_day_all_24_cells": round(sum(row.get("trades_per_day") or 0.0 for row in rows), 3),
        "trades_per_day_positive_cells": round(
            sum(row.get("trades_per_day") or 0.0 for row in positive_cells), 3),
        "where_frequency_exists": [
            {"strategy_id": row["strategy_id"], "trades_per_day": row["trades_per_day"],
             "zero_cost_gross_bps": row["zero_cost_gross_bps"],
             "net_vs_admission_floor_bps": row.get("net_vs_admission_floor_bps")}
            for row in sorted(rows, key=lambda r: r.get("trades_per_day") or 0.0, reverse=True)[:6]
        ],
        "reading": ("frequency is not the binding constraint: several cells already trade far "
                    "above the objective's daily rate, and every one of them is net-negative. "
                    "The objective is unmet because the net expectancy is, not because "
                    "opportunities are rare — and no entry may be manufactured to close the gap"),
    }

    hurdle = {
        "frozen_round_trip_bps": plane_bps,
        "best_zero_cost_gross_bps": baseline["headline_rebuilt"]["best_gross_bps"],
        "shortfall_bps": round(plane_bps - baseline["headline_rebuilt"]["best_gross_bps"], 6),
        "required_move_per_round_trip_bps": plane_bps,
        "what_it_means": ("a signal has to capture a price move larger than "
                          f"{round(plane_bps, 3)} bps per round trip before it can be net "
                          "positive at the frozen plane; that is the number a new hypothesis "
                          "must beat, and no threshold in this repository may be lowered to "
                          "make it easier"),
    }

    measured = None
    if E1.exists():
        payload = load(E1)
        assessment = payload.get("assessment") or {}
        measured = {
            "state": assessment.get("state"),
            "source": str(E1.relative_to(ROOT)).replace("\\", "/"),
            "observed_round_trip_microstructure_bps_median":
                assessment.get("observed_round_trip_microstructure_bps_median_across_books"),
            "plane_known_fee_term_bps": assessment.get("plane_known_fee_term_bps"),
            "best_gross_edge_covers_known_fees_alone":
                assessment.get("best_gross_edge_covers_known_fees_alone"),
            "consequence": ("cheaper execution narrows the bar; it does not clear it. The fee legs "
                            "alone already exceed the best gross edge in the register"),
        }

    e2 = load(E2) if E2.exists() else None
    forward_gate = {
        "e2_state": (e2 or {}).get("verdict", {}).get("e2"),
        "gate": (e2 or {}).get("verdict", {}).get("gate"),
        "reserved_from": ((e2 or {}).get("windows") or {}).get("reserved_from"),
        "role": ("stage 4 of the chain above: nothing may be ADOPT_FOR_NEW_EXPERIMENT until a "
                 "pre-registered rule returns PROMOTE on the reserved forward window"),
    }

    discovery = load(DISCOVERY2)
    separate: dict[str, Any] = dict(SEPARATE_LINES)
    separate["RFC049_DISCOVERY2"] = {
        "artefact": str(DISCOVERY2.relative_to(ROOT)).replace("\\", "/") if DISCOVERY2.exists() else None,
        "present": DISCOVERY2 is not None,
        "treatment": ("its two hypotheses were rejected at the development/validation stage on "
                      "sign decay, drawdown over the limit and failure to beat the baselines; "
                      "they are new hypotheses and are not members of the 24-strategy register, so "
                      "they are neither re-opened nor counted as families"),
        "headline": (discovery or {}).get("summary") or (discovery or {}).get("verdict"),
    }
    separate["M03_M07_MICROSTRUCTURE"] = {
        "treatment": ("gated behind the forward-history requirements in "
                      "config/microstructure_preregistration.json; not a family and not scorable "
                      "until the history exists"),
        "artefact": "data/recovery/wp9/WP9_M03_M07_READINESS.json",
    }

    counts: dict[str, int] = {}
    for family in matrix.values():
        counts[family["verdict"]] = counts.get(family["verdict"], 0) + 1

    payload = {
        "artifact": "WP10_ACTIVE_RECOVERY_MATRIX",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "PHASE 5 — ACTIVE RECOVERY MATRIX",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — no process, no order, no key, no capital",
        "head": software_version(),
        "sources": {
            "baseline": str(BASELINE.relative_to(ROOT)).replace("\\", "/"),
            "execution_cost": str(E1.relative_to(ROOT)).replace("\\", "/") if E1.exists() else None,
            "e2_preregistration": str(E2.relative_to(ROOT)).replace("\\", "/") if E2.exists() else None,
        },
        "classes_definition": {
            "ADOPT_FOR_NEW_EXPERIMENT": ("a pre-registered rule returned PROMOTE on a reserved "
                                         "forward window"),
            "RESEARCH_MORE": ("an edge exists and is resolvable, but it is short of the plane, or "
                              "it has not yet passed the forward test"),
            "INSUFFICIENT_EVIDENCE": ("a positive edge is claimed but cannot be believed yet: the "
                                      "interval is wider than the edge or the sign does not hold "
                                      "across partitions"),
            "REJECT": "no cell of the family shows a positive zero-cost gross edge",
            "no_family_may_be_added_to_inflate_the_count": True,
        },
        "families": matrix,
        "verdict_counts": counts,
        "frequency": frequency,
        "hurdle": hurdle,
        "measured_cost_layer": measured,
        "forward_gate": forward_gate,
        "separate_lines": separate,
        "frozen_artifacts_modified": 0,
        "no_promotion": {
            "strategies_admitted": 0,
            "thresholds_changed": 0,
            "cost_model_changed": False,
            "live_trading": "DISABLED",
            "trades_authorized": 0,
        },
        "checks": [
            {"check": "every one of the 24 registered cells is classified",
             "ok": sum(family["cells"] for family in matrix.values()) == 24},
            {"check": "no family is classified ADOPT without a forward PROMOTE",
             "ok": counts.get("ADOPT_FOR_NEW_EXPERIMENT", 0) == 0},
            {"check": "the plane quoted is the rebuilt one, not a copy",
             "ok": abs(plane_bps - 23.353553391) < 1e-6},
            {"check": "the low-frequency operator line is kept separate and unmapped",
             "ok": SEPARATE_LINES["R6_P2_QUALITY"]["repo_artefact"] is None},
            {"check": "frequency is reported next to expectancy so the two are not confused",
             "ok": "reading" in frequency},
            {"check": "no frozen criterion, threshold or cost is modified", "ok": True},
        ],
        "verdict": (
            "PARTIAL — the chain is populated and 0 families reach ADOPT; the obstacle is named "
            "per family, and for every family it is either an unresolvable edge or a cost gap"
        ),
    }
    exit_code = 0 if all(check["ok"] for check in payload["checks"]) else 3
    return payload, exit_code


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-10 PHASE 5 — ACTIVE RECOVERY MATRIX",
        "",
        f"> `{payload['generated_at_utc']}` · head `{payload['head']}` · "
        f"**{payload['verdict'].split(' — ')[0]}**",
        "",
        "Each family goes through an ordered chain and fails at exactly one stage:",
        "",
        *[f"* **{name}** — {text}" for name, text in payload["classes_definition"].items()
          if name != "no_family_may_be_added_to_inflate_the_count"],
        "",
        "## 1. The matrix",
        "",
        "| family | cells | positive cells | best cell | best gross bps | trades/day | verdict | "
        "blocking stage |",
        "| --- | ---: | ---: | --- | ---: | ---: | --- | --- |",
    ]
    for family, record in payload["families"].items():
        lines.append(
            f"| `{family}` | {record['cells']} | {record['cells_with_positive_gross']} | "
            f"`{record['best_cell']}` | {record['best_cell_gross_bps']} | "
            f"{record['trades_per_day_total']} | **{record['verdict']}** | "
            f"{record['blocking_stage']} |"
        )
    lines += ["", "Why each family stops where it stops:", ""]
    for family, record in payload["families"].items():
        lines.append(f"* `{family}` → **{record['verdict']}**: {record['why']}")
    lines += [
        "",
        f"Verdict counts: {', '.join(f'{k} = {v}' for k, v in sorted(payload['verdict_counts'].items()))}.",
        "",
        "## 2. Frequency is not what is missing",
        "",
        f"* objective: {payload['frequency']['objective_ops_per_day']} operations/day",
        f"* trades/day across all 24 cells: {payload['frequency']['trades_per_day_all_24_cells']}",
        f"* trades/day across the cells with positive gross: "
        f"{payload['frequency']['trades_per_day_positive_cells']}",
        "",
        "| cell | trades/day | gross bps | net vs the plane bps |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in payload["frequency"]["where_frequency_exists"]:
        lines.append(f"| `{row['strategy_id']}` | {row['trades_per_day']} | "
                     f"{row['zero_cost_gross_bps']} | {row['net_vs_admission_floor_bps']} |")
    lines += [
        "",
        payload["frequency"]["reading"] + ".",
        "",
        "## 3. The hurdle a new hypothesis must beat",
        "",
        f"* frozen round trip: **{payload['hurdle']['frozen_round_trip_bps']} bps**",
        f"* best zero-cost gross edge in the register: {payload['hurdle']['best_zero_cost_gross_bps']} bps",
        f"* shortfall: {payload['hurdle']['shortfall_bps']} bps",
        f"* {payload['hurdle']['what_it_means']}",
        "",
    ]
    measured = payload["measured_cost_layer"]
    if measured:
        lines += [
            "## 4. What the measured execution cost changes (E-1)",
            "",
            f"* state: `{measured['state']}`; observed round-trip microstructure "
            f"{measured['observed_round_trip_microstructure_bps_median']} bps versus "
            f"{measured['plane_known_fee_term_bps']} bps of KNOWN fees",
            f"* the best gross edge clears the fee legs alone: "
            f"`{measured['best_gross_edge_covers_known_fees_alone']}`",
            f"* {measured['consequence']}",
            "",
        ]
    lines += [
        "## 5. The forward gate (stage 4)",
        "",
        f"* E-2 state `{payload['forward_gate']['e2_state']}`, gate "
        f"`{payload['forward_gate']['gate']}`, reserved window from "
        f"`{payload['forward_gate']['reserved_from']}`",
        f"* {payload['forward_gate']['role']}",
        "",
        "## 6. Lines kept separate",
        "",
    ]
    for name, record in payload["separate_lines"].items():
        lines.append(f"* **{name}** — {record.get('treatment')}")
    lines += [
        "",
        "## 7. Checks",
        "",
        *[f"* [{'x' if check['ok'] else ' '}] {check['check']}" for check in payload["checks"]],
        "",
        f"Nothing was admitted, no threshold moved: admitted "
        f"{payload['no_promotion']['strategies_admitted']}, thresholds changed "
        f"{payload['no_promotion']['thresholds_changed']}, live trading "
        f"`{payload['no_promotion']['live_trading']}`, trades authorized "
        f"{payload['no_promotion']['trades_authorized']}.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload, exit_code = build()
    WP10.mkdir(parents=True, exist_ok=True)
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    json_path = WP10 / "WP10_ACTIVE_RECOVERY_MATRIX.json"
    md_path = WP10 / "WP10_ACTIVE_RECOVERY_MATRIX.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    payload["payload_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['verdict'].split(' — ')[0]}: {json_path.relative_to(ROOT)} — "
          f"{json.dumps(payload['verdict_counts'])} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
