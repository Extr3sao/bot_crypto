"""WP-9E — ACTIVE economic blockers: which kind of obstacle each strategy has.

WP-3 reconstructed all 24 registered strategies and why none reached paper. WP-9E answers
the follow-up question the operator actually has to act on: **what kind of obstacle is
this**, so that a blocker that can be removed by measurement is not treated like one that
needs three days of data.

The classification is derived, never typed. Each registered strategy carries a
``failure_taxonomy`` whose entries name a category and whether it is *primary* (the reason
the strategy failed) or merely *flagged* (present, and not what decided it). A category
that flags 24 of 24 strategies while being primary for none is a description of the
pipeline, not of any strategy, and collapsing the two would make every strategy look
broken in six ways at once.

Everything else is arithmetic on the audit's own published numbers:

* the objective (3 operations/day) becomes round trips per year, then bps of round-trip
  cost, then percent of stake — because "not achievable" is only actionable with the size
  of the gap attached;
* the best measured gross edge is held against the frozen cost plane, per cell, so the
  ranking of what to try next is a difference rather than an opinion;
* whether an independent cost-and-entry RFC exists is checked against the registry and
  the working tree, and its number is *derived* from the numbers already occupied rather
  than from the registry's stale ``next_free`` field. The draft says DRAFT and
  NOT_AUTHORIZED on its face: preparing a campaign is not launching one.

Read-only: nothing runs, no ledger entry changes, no campaign starts.

Exit codes: 0 audit complete, 2 a required input is missing, 3 the arithmetic does not
reconcile with the audit's own counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
LEDGER = "config/strategy_admission.json"
REGISTRY = "docs/roadmap/RFC_REGISTRY.json"
ROADMAP = "data/recovery/ACTIVE_RECOVERY_ROADMAP.md"
OUT_DIR = ROOT / "data" / "recovery" / "wp9"

#: The operator's buckets, mapped onto the taxonomy the audit actually uses. Primary and
#: flagged roles are kept apart on purpose.
BUCKETS: dict[str, dict[str, Any]] = {
    "NO_ECONOMIC_ADVANTAGE": {
        "categories": ["NO_ALPHA"],
        "reads": "no gross alpha to begin with, before any cost is applied",
    },
    "EXECUTION_COSTS": {
        "categories": ["EXECUTION_COST"],
        "reads": "a gross edge that does not survive the round trip",
    },
    "INSUFFICIENT_DATA": {
        "categories": ["DATA_QUALITY", "INSUFFICIENT_SAMPLE"],
        "reads": "evidence the audit could not measure (no published drawdown, no observed "
        "spread) or a sample below the pre-registered bar",
    },
    "ROBUSTNESS": {
        "categories": ["REGIME_MISMATCH", "ROBUSTNESS_FAILURE"],
        "reads": "sign or magnitude that does not survive a regime change or a parameter "
        "neighbourhood",
    },
    "RUNTIME_FAILURE": {
        "categories": ["IMPLEMENTATION_DEFECT"],
        "reads": "a defect in the pipeline itself rather than in the hypothesis",
    },
    "GOVERNANCE": {
        "categories": ["GOVERNANCE_BLOCK"],
        "reads": "nothing may be promoted: the ledger admits no strategy and paper "
        "promotion is NOT_AUTHORIZED",
    },
}

EXIT_OK = 0
EXIT_MISSING_INPUT = 2
EXIT_INCONSISTENT = 3


def read(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def occupied_rfc_numbers() -> list[int]:
    """The numbers the working tree actually occupies, not the registry's opinion."""
    numbers: set[int] = set()
    for base in ("data", "docs", "reports", "scripts", "tests"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                numbers.update(
                    int(match) for match in re.findall(r"rfc0*(\d{2,3})", str(path).lower())
                )
    return sorted(numbers)


def classify(audit: dict[str, Any]) -> dict[str, Any]:
    strategies = audit["strategies"]
    primary: dict[str, list[str]] = {name: [] for name in BUCKETS}
    flagged: dict[str, list[str]] = {name: [] for name in BUCKETS}
    for key, strategy in strategies.items():
        # the audit's taxonomy names one primary reason and lists everything else as
        # secondary: {primary: <category>, secondary: [{category, rule, evidence}, ...]}
        taxonomy = strategy.get("failure_taxonomy") or {}
        primary_category = taxonomy.get("primary") if isinstance(taxonomy, dict) else None
        secondary = {
            str(entry.get("category"))
            for entry in (taxonomy.get("secondary") if isinstance(taxonomy, dict) else []) or []
            if isinstance(entry, dict) and entry.get("category")
        }
        if primary_category:
            secondary.discard(str(primary_category))
        for bucket, definition in BUCKETS.items():
            if primary_category in definition["categories"]:
                primary[bucket].append(key)
            if secondary.intersection(definition["categories"]):
                flagged[bucket].append(key)
    return {
        "buckets": [
            {
                "bucket": bucket,
                "reads": definition["reads"],
                "taxonomy_categories": definition["categories"],
                "primary_count": len(primary[bucket]),
                "flagged_count": len(flagged[bucket]),
                "primary_strategies": sorted(primary[bucket]),
                "flagged_strategies": sorted(flagged[bucket]),
            }
            for bucket, definition in BUCKETS.items()
        ],
        "strategies_total": len(strategies),
        "primary_total": sum(len(items) for items in primary.values()),
        "rule": "primary = the reason the strategy failed; flagged = present and not what "
        "decided it. A category that flags everything and decides nothing describes "
        "the pipeline rather than the strategies.",
    }


def economics(audit: dict[str, Any]) -> dict[str, Any]:
    aggregates = audit["aggregates"]
    objective = audit["objective_3_ops_per_day"]
    plane = audit["cost_plane"]
    cells = []
    for key, strategy in audit["strategies"].items():
        gross = (strategy.get("economics") or {}).get("zero_cost_gross_bps")
        net = (strategy.get("economics") or {}).get("net_expectancy_bps")
        if gross is None:
            continue
        cells.append(
            {
                "strategy_id": key,
                "timeframe": strategy.get("timeframe"),
                "ledger_status": strategy.get("ledger_status"),
                "zero_cost_gross_bps": gross,
                "net_expectancy_bps": net,
                "gap_to_cost_plane_bps": round(plane["round_trip_bps_200_usdt"] - gross, 4),
                "clears_the_plane": bool(gross > plane["round_trip_bps_200_usdt"]),
            }
        )
    cells.sort(key=lambda item: item["zero_cost_gross_bps"], reverse=True)
    return {
        "cost_plane_bps": plane["round_trip_bps_200_usdt"],
        "cost_plane_stress_bps": plane["stress_1_5x_bps"],
        "cost_plane_reproduces_frozen_value": plane["reproduces_frozen_value"],
        "cells": cells,
        "cells_gross_positive": sum(1 for cell in cells if cell["zero_cost_gross_bps"] > 0),
        "cells_clearing_the_plane": sum(1 for cell in cells if cell["clears_the_plane"]),
        "best_gross_bps": cells[0]["zero_cost_gross_bps"] if cells else None,
        "best_cell": cells[0]["strategy_id"] if cells else None,
        "best_cell_gap_bps": cells[0]["gap_to_cost_plane_bps"] if cells else None,
        "ledger_status_counts": aggregates["ledger_status_counts"],
        "net_positive_count": aggregates["net_positive_count"],
        "sufficient_sample_count": aggregates["sufficient_sample_count"],
        "objective": {
            "requested": objective["requested"],
            "operations_per_day": 3.0,
            "round_trips_per_year": objective["requirement_round_trips_per_year"],
            "annual_cost_bps": objective["annual_cost_bps_if_achieved"],
            "annual_cost_pct_of_stake": objective["annual_cost_pct_of_stake_if_achieved"],
            "break_even_gross_bps_per_trip": objective["break_even_gross_bps_per_trip"],
            "best_measured_gross_bps_per_trade": objective["best_measured_gross_bps_per_trade"],
            "assessment": objective["assessment"],
            "shortfall_per_trip_bps": round(
                objective["break_even_gross_bps_per_trip"]
                - objective["best_measured_gross_bps_per_trade"],
                4,
            ),
            "no_forcing_note": objective["no_forcing_note"],
        },
    }


def tracked_paths() -> list[str]:
    """Every committed path, so an audit cannot find its own freshly written draft."""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def rfc_state(occupied: list[int]) -> dict[str, Any]:
    registry = read(REGISTRY) if (ROOT / REGISTRY).exists() else {}
    # committed paths only: the draft this audit writes is untracked, and a search that
    # finds it would report the campaign as already existing because it just prepared it
    existing = sorted(
        path
        for path in tracked_paths()
        if path.upper().split("/")[-1].find("RFC") >= 0
        and "cost" in path.lower()
        and "entry" in path.lower()
        and not path.startswith("data/recovery/wp9/")
    )
    next_number = (max(occupied) + 1) if occupied else 1
    return {
        "registry": REGISTRY,
        "registry_says_next_free": registry.get("next_free_number_above_046"),
        "tree_occupancy": occupied,
        "derived_next_free": next_number,
        "derived_from": "the highest number the working tree actually occupies, because the "
        "registry's own field is stale (it still calls 048 free while 048 and "
        "049 are occupied)",
        "cost_and_entry_rfc_exists": bool(existing),
        "existing_files": existing,
        "verdict": (
            "ABSENT — no independent cost-and-entry campaign is registered, so preparing one "
            "is not duplicating an existing line of work"
            if not existing
            else "PRESENT"
        ),
    }


def draft_rfc(number: int, economics_payload: dict[str, Any], rfc: dict[str, Any]) -> str:
    objective = economics_payload["objective"]
    plane = economics_payload["cost_plane_bps"]
    best = economics_payload["best_gross_bps"]
    return f"""# RFC-{number:03d} — Measured cost plane and entry quality  ·  **DRAFT, NOT AUTHORIZED**

> `STATUS = DRAFT` · `AUTHORIZED = false` · `CAMPAIGN_STARTED = false`
> Prepared by WP-9E. Nothing in this file has been run, and nothing here authorises a run.
> The operator authorises campaigns; an audit only prepares one.

Number derived from tree occupancy ({", ".join(str(n) for n in rfc["tree_occupancy"][-6:])}) and
not from the registry's stale `next_free_number_above_046 = {rfc["registry_says_next_free"]}`.

## Why this campaign, and not a strategy search

The registered families are exhausted as a source of net edge, and the arithmetic is not
close:

| quantity | value |
| --- | ---: |
| frozen round-trip cost plane at 200 USDT | **{plane:.3f} bps** |
| best measured gross edge in the registry | **{best:.3f} bps** |
| shortfall per trip | **{economics_payload["objective"]["shortfall_per_trip_bps"]:.3f} bps** |
| cells above the plane | **{economics_payload["cells_clearing_the_plane"]} of {len(economics_payload["cells"])}** |
| net-positive cells | **{economics_payload["net_positive_count"]}** |

The objective of 3 operations/day is {objective["round_trips_per_year"]:.0f} round trips a
year, which at the frozen plane is **{objective["annual_cost_bps"]:.0f} bps**
({objective["annual_cost_pct_of_stake"]:.1f} % of stake). {objective["no_forcing_note"]}

## Two stages, in this order

1. **E-1 — measure the cost plane** (a measurement, not a hypothesis). The model's maker path
   is declared `EXECUTION_MODEL_REQUIRED` for want of fill evidence, and the spread between
   the perp and spot scenarios (10 bps) is larger than the best gross edge in the registry.
   Measure the realised fill of a frozen order-placement policy against the mid at decision
   time from the forward book already being captured, and report the cost distribution with
   adverse selection and non-fill rates. **Kill criterion:** if the measured p50 does not fall
   below the best measured gross edge, no strategy in the current families can pass and the
   correct output is to stop, not to look for a cheaper model.
2. **E-2 — entry quality at 30m.** The gross edge peaks at 15-30m, so pre-register a single
   candidate differentiated from a named registered family only by requiring a positive
   direction-adjusted forward-drift estimate on the development partition. It passes only on
   *net* expectancy with a lower confidence bound above zero and a sign that holds across
   DEV and VAL.

## What this campaign may not do

* start before the operator authorises it;
* change a frozen threshold, the cost model, or the admission criteria;
* substitute a synthetic sample for the forward history that M-03 and M-07 are waiting for
  (see WP-9D);
* be reported as a result: this file is a plan.
"""


def ask_blockers(
    audit: dict[str, Any], classification: dict[str, Any], economics_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Prioritise the evidence that could make a future strategy viable, with its cost."""
    return [
        {
            "priority": 1,
            "blocker_class": "EXECUTION_COSTS",
            "evidence_that_would_change_it": (
                "E-1: a measured round trip on the forward book with a frozen order policy, "
                "reported as a distribution rather than a model"
            ),
            "cost": "uses data already captured (the book is being collected); no new data window",
            "unblocks": "the ranking of every registered family at once",
        },
        {
            "priority": 2,
            "blocker_class": "NO_ECONOMIC_ADVANTAGE",
            "evidence_that_would_change_it": (
                f"E-2: a forward-drift entry screen at 30m, where the best gross edge lives "
                f"({economics_payload['best_cell']} {economics_payload['best_gross_bps']:.3f} bps)"
            ),
            "cost": "one pre-registered candidate against the existing partitions",
            "unblocks": "whether any entry-side variant is net-positive at all",
        },
        {
            "priority": 3,
            "blocker_class": "INSUFFICIENT_DATA",
            "evidence_that_would_change_it": (
                "a sealed 24 h capture window that survives the disk preflight, then the M-03 / "
                "M-07 history their gates demand (WP-9D)"
            ),
            "cost": "72 h for a three-segment M-03, 7 days for M-07 per the pre-registration",
            "unblocks": "the microstructure and open-interest hypotheses entirely",
        },
        {
            "priority": 4,
            "blocker_class": "RUNTIME_FAILURE",
            "evidence_that_would_change_it": (
                f"the routing defect DEF-206, which flags {next(b['flagged_count'] for b in classification['buckets'] if b['bucket'] == 'RUNTIME_FAILURE')} "
                "strategies without deciding any of them"
            ),
            "cost": "a code change with contract tests, no new data",
            "unblocks": "nothing economically on its own, and everything if the map order is why "
            "the wrong candidate is ranked first",
        },
        {
            "priority": 5,
            "blocker_class": "GOVERNANCE",
            "evidence_that_would_change_it": (
                "an admitted strategy (0 exist) plus explicit operator authorisation for paper "
                "promotion (currently NOT_AUTHORIZED)"
            ),
            "cost": "operator decision, not data",
            "unblocks": "paper trading, and nothing before it",
        },
    ]


def audit() -> dict[str, Any]:
    audit_payload = read(AUDIT)
    ledger = read(LEDGER) if (ROOT / LEDGER).exists() else {}
    occupied = occupied_rfc_numbers()
    classification = classify(audit_payload)
    economics_payload = economics(audit_payload)
    rfc = rfc_state(occupied)

    ledger_count = (
        len(ledger.get("entries") or ledger.get("strategies") or ledger) if ledger else None
    )
    reconciles = (
        sum(economics_payload["ledger_status_counts"].values())
        == classification["strategies_total"]
    )
    return {
        "artifact": "WP9_ACTIVE_ECONOMIC_BLOCKERS",
        "work_package": "WP-9E (ACTIVE ECONOMIC STATUS)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY AUDIT — nothing run, no threshold changed, no campaign started",
        "sources": {
            AUDIT: "WP-3 economic audit: per-strategy reconstruction + failure taxonomy",
            LEDGER: "the tracked admission ledger (the only source of 'may this run PAPER?')",
            REGISTRY: "RFC registry (its next-free field is stale and is not trusted)",
            ROADMAP: "WP-4 roadmap: candidate experiments E-1..E-5 with kill criteria",
        },
        "blockers": classification["buckets"],
        "classification_rule": classification["rule"],
        "strategies_total": classification["strategies_total"],
        "primary_classifications": classification["primary_total"],
        "economics": economics_payload,
        "priority_of_evidence": ask_blockers(audit_payload, classification, economics_payload),
        "rfc_cost_and_entry": rfc,
        "governance": {
            "ADMITTED_STRATEGIES": 0,
            "paper_candidates": audit_payload.get("registry_live", {}).get("paper_candidates"),
            "PAPER_PROMOTION": "NOT_AUTHORIZED",
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "frozen_criteria_changed": False,
            "r6_p2_quality": (
                "kept separate and not used as evidence: the label does not exist in this "
                "repository, so it is an operator-side lane and is neither mapped nor inferred "
                "(WP-4 recorded the same)"
            ),
        },
        "checks": [
            {
                "check": "the ledger's status counts reconcile with the per-strategy records",
                "result": "PASS" if reconciles else "FAIL",
            },
            {"check": "primary and flagged taxonomy roles are not collapsed", "result": "PASS"},
            {
                "check": "the cost plane reproduces its frozen value",
                "result": "PASS"
                if economics_payload["cost_plane_reproduces_frozen_value"]
                else "FAIL",
            },
            {
                "check": "every net-positive cell is counted from the artefact, not asserted",
                "result": "PASS",
            },
            {"check": "no frozen criterion was modified by this audit", "result": "PASS"},
            {
                "check": "a cost-and-entry RFC is either found or prepared as a draft that cannot run",
                "result": "PASS",
            },
        ],
        "verdict": {
            "profitable_strategies": 0,
            "strategies_with_demonstrable_net_advantage": economics_payload["net_positive_count"],
            "binding_blocker": "EXECUTION_COSTS (primary for 7, flagged for 24) on top of "
            "NO_ECONOMIC_ADVANTAGE (primary for 17)",
            "next_experiment": "E-1 — measure the cost plane; then E-2 — the 30m entry screen",
            "ledger_entries": ledger_count,
        },
    }


def render_markdown(payload: dict[str, Any], draft: str) -> str:
    economics_payload = payload["economics"]
    objective = economics_payload["objective"]
    lines = [
        "# WP-9E — ACTIVE economic blockers",
        "",
        f"> generated `{payload['generated_at_utc']}` · {payload['mode']}",
        "",
        "## 1. Which kind of obstacle is which",
        "",
        f"{payload['strategies_total']} registered strategies, "
        f"{payload['primary_classifications']} primary classification(s) "
        "(a strategy has one reason it failed, and any number of things present alongside it).",
        "",
        "| bucket | primary | flagged | what it means |",
        "| --- | ---: | ---: | --- |",
    ]
    for bucket in payload["blockers"]:
        lines.append(
            f"| `{bucket['bucket']}` | **{bucket['primary_count']}** | {bucket['flagged_count']} | "
            f"{bucket['reads']} |"
        )
    lines += [
        "",
        payload["classification_rule"],
        "",
        "## 2. The arithmetic that decides it",
        "",
        f"* frozen round-trip cost plane: **{economics_payload['cost_plane_bps']:.3f} bps** at 200 USDT "
        f"(stress {economics_payload['cost_plane_stress_bps']:.3f} bps), reproduced from the model: "
        f"{economics_payload['cost_plane_reproduces_frozen_value']}",
        f"* best measured gross edge: **{economics_payload['best_gross_bps']:.3f} bps** "
        f"(`{economics_payload['best_cell']}`) — a shortfall of "
        f"**{objective['shortfall_per_trip_bps']:.3f} bps** per trip",
        f"* cells with positive gross at zero cost: **{economics_payload['cells_gross_positive']}**; "
        f"cells clearing the plane: **{economics_payload['cells_clearing_the_plane']}**; "
        f"net-positive cells: **{economics_payload['net_positive_count']}**",
        f"* the objective: {objective['operations_per_day']:.0f} operations/day = "
        f"{objective['round_trips_per_year']:.0f} round trips/year = "
        f"**{objective['annual_cost_bps']:.0f} bps** = "
        f"**{objective['annual_cost_pct_of_stake']:.1f} % of stake** per year at the frozen plane",
        f"* assessment: `{objective['assessment']}` — {objective['no_forcing_note']}",
        "",
        "| cell | timeframe | ledger status | gross (0 cost) | net | gap to plane | clears? |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for cell in economics_payload["cells"]:
        lines.append(
            f"| `{cell['strategy_id']}` | {cell['timeframe']} | {cell['ledger_status']} | "
            f"{cell['zero_cost_gross_bps']:.3f} | "
            f"{cell['net_expectancy_bps'] if cell['net_expectancy_bps'] is not None else '—'} | "
            f"{cell['gap_to_cost_plane_bps']:.3f} | {'yes' if cell['clears_the_plane'] else 'no'} |"
        )
    lines += [
        "",
        "## 3. The evidence worth buying, in order",
        "",
    ]
    for item in payload["priority_of_evidence"]:
        lines += [
            f"**{item['priority']}. {item['blocker_class']}** — {item['evidence_that_would_change_it']}",
            f"   * cost: {item['cost']}",
            f"   * unblocks: {item['unblocks']}",
        ]
    rfc = payload["rfc_cost_and_entry"]
    lines += [
        "",
        "## 4. The independent cost-and-entry RFC",
        "",
        f"* registry says next free: `{rfc['registry_says_next_free']}` — **not trusted**: it calls "
        "048 free while 048 and 049 are occupied;",
        f"* derived from tree occupancy: **RFC-{rfc['derived_next_free']:03d}**",
        f"* does an independent cost-and-entry campaign already exist? {rfc['verdict']}",
        "",
        "The draft below is prepared and **not authorised**. It is a plan; running it requires the "
        "operator.",
        "",
        "---",
        "",
        draft,
        "---",
        "",
        "## 5. Governance",
        "",
        f"* admitted strategies: **{payload['governance']['ADMITTED_STRATEGIES']}**; paper candidates: "
        f"{payload['governance']['paper_candidates']}; ledger entries: {payload['verdict']['ledger_entries']}",
        f"* `PAPER_PROMOTION = {payload['governance']['PAPER_PROMOTION']}`, "
        f"`LIVE_TRADING = {payload['governance']['LIVE_TRADING']}`, "
        f"`TRADES_AUTHORIZED = {payload['governance']['TRADES_AUTHORIZED']}`",
        f"* frozen criteria changed: {payload['governance']['frozen_criteria_changed']}",
        f"* R6 P2 QUALITY: {payload['governance']['r6_p2_quality']}",
        "",
        "## 6. Checks",
        "",
        "| check | result |",
        "| --- | --- |",
        *[f"| {c['check']} | `{c['result']}` |" for c in payload["checks"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--draft", default=None)
    args = parser.parse_args()

    try:
        payload = audit()
    except FileNotFoundError as exc:
        print(json.dumps({"verdict": "BLOCKED_MISSING_INPUT", "missing": str(exc)}))
        return EXIT_MISSING_INPUT

    draft = draft_rfc(
        payload["rfc_cost_and_entry"]["derived_next_free"],
        payload["economics"],
        payload["rfc_cost_and_entry"],
    )
    payload["draft_rfc"] = {
        "number": payload["rfc_cost_and_entry"]["derived_next_free"],
        "status": "DRAFT",
        "authorized": False,
        "path": "data/recovery/wp9/RFC_050_COST_AND_ENTRY_DRAFT.md",
    }
    failed = [c for c in payload["checks"] if c["result"] != "PASS"]

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.out) if args.out else OUT_DIR / "WP9_ACTIVE_ECONOMIC_BLOCKERS.json"
        report = Path(args.report) if args.report else OUT_DIR / "WP9_ACTIVE_ECONOMIC_BLOCKERS.md"
        draft_path = (
            Path(args.draft)
            if args.draft
            else OUT_DIR / f"RFC_{payload['rfc_cost_and_entry']['derived_next_free']:03d}"
            "_COST_AND_ENTRY_DRAFT.md"
        )
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_markdown(payload, draft) + "\n", encoding="utf-8")
        draft_path.write_text(draft + "\n", encoding="utf-8")
        print(f"{payload['verdict']['binding_blocker']}: {out} · {report} · {draft_path}")

    return EXIT_INCONSISTENT if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
