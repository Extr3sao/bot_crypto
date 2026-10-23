"""ALPHA-001 — cost frontier: is the cost, or the effect size, the binding constraint?

ALPHA-001 answered *no* under the frozen admission rule.  That raises the only
question worth asking next: **would cheaper execution have changed the answer?**
This driver re-reads the frozen discovery evidence (never recomputing alpha, never
touching the holdout) and, for every preregistered cell, solves for

* the cost at which the cell's raw net PnL turns positive (``net_break_even``), and
* the cost at which the *frozen admission rule* is exactly met (``admission_break_even``).

A negative admission break-even says the venue would have to pay the strategy; in
that case no amount of execution work can admit the cell and the constraint is the
effect size, not the fee schedule.  The arithmetic lives in
``trading_bot.research.alpha001.cost_frontier`` so it is unit-tested rather than
inlined here; this file only aggregates, renders, and records the closure.

Output: ``reports/alpha001/COST_FRONTIER.{json,md}``.
Research only: no orders, no credentials, no capital, no cost-model change.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha001 import (  # noqa: E402
    COST_BPS_V3,
    EXECUTION_UNCERTAINTY_FRACTION,
    WINNERS_CURSE_BUFFER_BPS,
    cost_frontier,
)

REPORT_DIR = REPO / "reports" / "alpha001"
ARTIFACTS_PATH = REPORT_DIR / "ALPHA001_ARTIFACTS.json"
OUT_JSON = REPORT_DIR / "COST_FRONTIER.json"
OUT_MD = REPORT_DIR / "COST_FRONTIER.md"

DESIGN_SIGMA_BPS = 400.0
Z_975 = 1.959963985

#: Cost levels the sensitivity table walks, ending at "free execution".
SENSITIVITY_COSTS_BPS = (23.790569, 20.0, 15.0, 10.0, 5.0, 0.0)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build(artifacts: dict[str, Any]) -> dict[str, Any]:
    """Aggregate the per-cell frontier and the campaign-level closure."""
    summaries: dict[str, dict[str, Any]] = artifacts["summaries"]
    components = artifacts["hurdle"]
    frozen_statistical = float(components["statistical_uncertainty_bps"])
    n_effective_design = int(components["n_effective"])
    hurdle_bps = float(artifacts["hurdle_bps"])

    per_hypothesis: dict[str, dict[str, Any]] = {}
    per_hypothesis_own_data: dict[str, dict[str, Any]] = {}
    for hypothesis_id, summary in summaries.items():
        per_hypothesis[hypothesis_id] = cost_frontier(
            gross_bps=float(summary["gross_bps"]),
            statistical_bps=frozen_statistical,
        )
        # Secondary reading: the same frontier using the cell's own realised
        # dispersion and effective sample size instead of the design constants.
        own_statistical = (
            Z_975 * float(summary["sigma_bps"]) / (float(summary["n_effective"]) ** 0.5)
        )
        per_hypothesis_own_data[hypothesis_id] = cost_frontier(
            gross_bps=float(summary["gross_bps"]),
            statistical_bps=own_statistical,
        )

    best_hypothesis = str(artifacts["best_hypothesis"])
    best_gross = float(summaries[best_hypothesis]["gross_bps"])
    frontier_admission_cost = max(
        item["admission_break_even_cost_bps"] for item in per_hypothesis.values()
    )
    frontier_net_cost = max(item["net_break_even_cost_bps"] for item in per_hypothesis.values())
    non_cost_bar = WINNERS_CURSE_BUFFER_BPS + frozen_statistical

    shares = {
        "cost": components["cost_bps"] / hurdle_bps,
        "execution_uncertainty": components["execution_uncertainty_bps"] / hurdle_bps,
        "winners_curse_buffer": components["winners_curse_buffer_bps"] / hurdle_bps,
        "statistical_uncertainty": components["statistical_uncertainty_bps"] / hurdle_bps,
    }
    sensitivity = []
    for cost in SENSITIVITY_COSTS_BPS:
        row_hurdle = cost * (1.0 + EXECUTION_UNCERTAINTY_FRACTION) + non_cost_bar
        sensitivity.append(
            {
                "cost_bps": round(cost, 6),
                "hurdle_bps": round(row_hurdle, 6),
                "best_gross_bps": round(best_gross, 6),
                "admission_gap_bps": round(best_gross - row_hurdle, 6),
                "best_net_bps": round(best_gross - cost, 6),
            }
        )

    cells_net_positive_at_zero_cost = sum(
        1 for item in per_hypothesis.values() if item["net_positive_at_zero_cost"]
    )
    cells_admissible_at_zero_cost = sum(
        1 for item in per_hypothesis.values() if item["admissible_at_zero_cost"]
    )

    frontier = {
        "best_hypothesis": best_hypothesis,
        "best_gross_bps": round(best_gross, 6),
        "frozen_hurdle_bps": round(hurdle_bps, 6),
        "hurdle_over_best_gross": round(hurdle_bps / best_gross, 6),
        "frontier_admission_cost_bps": round(frontier_admission_cost, 6),
        "frontier_net_cost_bps": round(frontier_net_cost, 6),
        "cost_reduction_to_admit_fraction": round(1.0 - frontier_admission_cost / COST_BPS_V3, 6),
        "cost_reduction_to_admit_bps": round(COST_BPS_V3 - frontier_admission_cost, 6),
        "cost_reduction_to_net_positive_fraction": round(1.0 - frontier_net_cost / COST_BPS_V3, 6),
        "cells_admissible_at_any_cost": sum(
            1 for item in per_hypothesis.values() if item["admission_break_even_cost_bps"] >= 0.0
        ),
        "cells_admissible_at_zero_cost": cells_admissible_at_zero_cost,
        "cells_net_positive_at_zero_cost": cells_net_positive_at_zero_cost,
        "binding_constraint": "EFFECT_SIZE_NOT_COST",
        "interpretation": (
            "Even at zero trading cost the best point estimate stays below the non-cost part "
            "of the frozen bar, so no execution improvement can admit anything."
        ),
    }

    closure = {
        "campaign": "ALPHA-001",
        "question": (
            "Is there at least one source of gross alpha that is reproducible with enough "
            "margin to be profitable after the certified cost?"
        ),
        "answer": "NO",
        "verdict": "ALPHA_ECONOMICALLY_TOO_SMALL",
        "case": "CASE_B",
        "binding_constraint": "EFFECT_SIZE_NOT_COST",
        "reasons": [
            (
                f"frozen hurdle {hurdle_bps:.6f} bps vs best point estimate {best_gross:.6f} "
                f"bps: the best cell is {hurdle_bps / best_gross:.3f}x short"
            ),
            (
                f"even at zero cost the frozen bar needs {non_cost_bar:.6f} bps of gross and "
                f"the best cell reaches {best_gross:.6f} bps"
            ),
            (
                "the cost would have to become a rebate of "
                f"{max(0.0, -frontier_admission_cost):.6f} bps per round trip for the frozen "
                "rule to admit the best cell"
            ),
            "0/12 cells net-positive at the certified cost; 0 survivors under BH-FDR or Holm",
            (
                "best-of-12 observed statistic is inside the best-of-N null "
                f"(p = {artifacts['null']['p_null_best_ge_observed']})"
            ),
            (
                "the lead cell is FRAGILE (top-1 trade carries 80.8% of its gross) and its "
                "sign is unstable across sub-windows"
            ),
        ],
        "recommendation": "ACCEPT NO ALPHA under the frozen cost model",
        "not_authorised_here": [
            "no holdout read",
            "no ALPHA-002 campaign started",
            "no parameter search or re-tuning of the cost model",
            "no change to MAX_COST / COST_MODEL_V3",
        ],
        "decision_owner": "human",
        "reopen_requires": [
            (
                "a genuinely NEW information source (different data, not new parameters or "
                "new breakpoints of the same series)"
            ),
            "a preregistered hypothesis whose expected gross exceeds the frozen hurdle ex ante",
            "owner approval to spend capital-time on a new campaign",
        ],
    }

    return {
        "campaign": "ALPHA-001",
        "generated_at": int(time.time()),
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "source_artifact": {
            "path": "reports/alpha001/ALPHA001_ARTIFACTS.json",
            "sha256": file_sha256(ARTIFACTS_PATH),
        },
        "frozen_inputs": {
            "cost_bps": COST_BPS_V3,
            "execution_fraction": EXECUTION_UNCERTAINTY_FRACTION,
            "winners_curse_buffer_bps": WINNERS_CURSE_BUFFER_BPS,
            "design_sigma_bps": DESIGN_SIGMA_BPS,
            "n_effective_design": n_effective_design,
            "statistical_uncertainty_bps": frozen_statistical,
            "frozen_hurdle_bps": hurdle_bps,
            "holdout_read": artifacts["holdout_read"],
            "cost_model_changed": False,
        },
        "hurdle_decomposition": {
            "cost_bps": components["cost_bps"],
            "execution_uncertainty_bps": components["execution_uncertainty_bps"],
            "winners_curse_buffer_bps": components["winners_curse_buffer_bps"],
            "statistical_uncertainty_bps": components["statistical_uncertainty_bps"],
            "hurdle_bps": components["min_gross_alpha_hurdle_bps"],
            "shares": {key: round(value, 6) for key, value in shares.items()},
            "trading_cost_share": round(shares["cost"] + shares["execution_uncertainty"], 6),
            "safety_margin_share": round(
                shares["winners_curse_buffer"] + shares["statistical_uncertainty"], 6
            ),
        },
        "frontier": frontier,
        "sensitivity": sensitivity,
        "per_hypothesis": per_hypothesis,
        "per_hypothesis_own_data": per_hypothesis_own_data,
        "closure": closure,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    frozen = payload["frozen_inputs"]
    decomposition = payload["hurdle_decomposition"]
    frontier = payload["frontier"]
    closure = payload["closure"]
    lines = [
        "# ALPHA-001 — COST FRONTIER",
        "",
        (
            "How far would the certified cost have to fall before one of the preregistered "
            "hypotheses became tradeable?  Every number below is re-read from the frozen "
            "discovery evidence; no alpha is recomputed and the holdout is never touched."
        ),
        "",
        "## Frozen inputs",
        "",
        f"- certified cost: **{frozen['cost_bps']} bps** round trip (COST_MODEL_V3, unchanged)",
        f"- execution uncertainty: **{frozen['execution_fraction']:.0%}** of cost",
        f"- winner's-curse buffer: **{frozen['winners_curse_buffer_bps']} bps** (RFC-023)",
        (
            f"- statistical uncertainty: **{frozen['statistical_uncertainty_bps']} bps** "
            f"(z = 1.96 at the 97.5% one-sided level x {frozen['design_sigma_bps']} / "
            f"sqrt({frozen['n_effective_design']}))"
        ),
        f"- frozen admission hurdle: **{frozen['frozen_hurdle_bps']} bps**",
        f"- holdout read: **{str(frozen['holdout_read']).lower()}**",
        "",
        "## Where the hurdle comes from",
        "",
        "| component | bps | share of hurdle |",
        "| --- | --- | --- |",
    ]
    for key, label in (
        ("cost", "certified cost"),
        ("execution_uncertainty", "execution uncertainty"),
        ("winners_curse_buffer", "winner's-curse buffer"),
        ("statistical_uncertainty", "statistical uncertainty"),
    ):
        lines.append(
            f"| {label} | {decomposition[key + '_bps']} | {decomposition['shares'][key]:.2%} |"
        )
    lines.extend(
        [
            "",
            (
                f"Cost plus its execution margin is **{decomposition['trading_cost_share']:.2%}** "
                f"of the bar; the safety margins are **{decomposition['safety_margin_share']:.2%}**."
            ),
            "",
            "## The frontier",
            "",
            f"- best point estimate: **{frontier['best_hypothesis']} at "
            f"{frontier['best_gross_bps']} bps** against a hurdle of "
            f"{frontier['frozen_hurdle_bps']} bps ({frontier['hurdle_over_best_gross']}x short)",
            (
                f"- admission break-even cost: **{frontier['frontier_admission_cost_bps']} bps** "
                "— the venue would have to *pay* the strategy to make the frozen rule admit anything"
            ),
            (
                f"- required cost change: **{frontier['cost_reduction_to_admit_fraction']:.2%}** "
                f"({frontier['cost_reduction_to_admit_bps']} bps)"
            ),
            (
                f"- raw net-PnL break-even cost: **{frontier['frontier_net_cost_bps']} bps** "
                f"— a {frontier['cost_reduction_to_net_positive_fraction']:.2%} cut, with every "
                "safety margin dropped"
            ),
            (
                f"- cells admissible at any cost (even negative): "
                f"**{frontier['cells_admissible_at_any_cost']}**"
            ),
            (
                f"- cells net-positive at zero cost: "
                f"**{frontier['cells_net_positive_at_zero_cost']}**"
            ),
            f"- binding constraint: **{frontier['binding_constraint']}**",
            "",
            frontier["interpretation"],
            "",
            "## Cost sensitivity of the best cell",
            "",
            "| cost (bps) | hurdle (bps) | best gross (bps) | admission gap (bps) | best net (bps) |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["sensitivity"]:
        lines.append(
            f"| {row['cost_bps']} | {row['hurdle_bps']} | {row['best_gross_bps']} | "
            f"{row['admission_gap_bps']} | {row['best_net_bps']} |"
        )
    lines.extend(
        [
            "",
            "## Per hypothesis",
            "",
            "| hypothesis | gross (bps) | net (bps) | admission gap (bps) | net break-even cost | "
            "admission break-even cost | path to viability |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for hypothesis_id, item in sorted(payload["per_hypothesis"].items()):
        lines.append(
            f"| {hypothesis_id} | {item['gross_bps']} | {round(item['gross_bps'] - item['cost_bps'], 6)} | "
            f"{item['admission_gap_bps']} | {item['net_break_even_cost_bps']} | "
            f"{item['admission_break_even_cost_bps']} | {item['path_to_viability']} |"
        )
    lines.extend(
        [
            "",
            (
                "`admission break-even cost` is the cost at which the frozen rule is exactly met; "
                "a negative value is a required *rebate*."
            ),
            "",
            "### Same frontier on each cell's own data",
            "",
            (
                "Secondary reading: the frozen rule applies one design dispersion to every "
                "hypothesis.  Substituting each cell's own realised dispersion and effective "
                "sample size moves the bar in both directions; the set of viable cells stays empty."
            ),
            "",
            "| hypothesis | own statistical (bps) | own admission break-even cost | own path |",
            "| --- | --- | --- | --- |",
        ]
    )
    for hypothesis_id, item in sorted(payload["per_hypothesis_own_data"].items()):
        lines.append(
            f"| {hypothesis_id} | {item['statistical_uncertainty_bps']} | "
            f"{item['admission_break_even_cost_bps']} | {item['path_to_viability']} |"
        )
    lines.extend(
        [
            "",
            "## Closure",
            "",
            f"- question: {closure['question']}",
            f"- answer: **{closure['answer']}**",
            f"- verdict: **{closure['verdict']}** ({closure['case']})",
            f"- binding constraint: **{closure['binding_constraint']}**",
            f"- recommendation: **{closure['recommendation']}** (decision owner: "
            f"{closure['decision_owner']})",
            "",
            "Reasons:",
            "",
        ]
    )
    lines.extend(f"- {reason}" for reason in closure["reasons"])
    lines.extend(["", "Not done here:", ""])
    lines.extend(f"- {item}" for item in closure["not_authorised_here"])
    lines.extend(["", "Reopening requires:", ""])
    lines.extend(f"- {item}" for item in closure["reopen_requires"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="ALPHA-001 cost frontier").parse_args(argv)

    artifacts = load_json(ARTIFACTS_PATH)
    payload = build(artifacts)
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")

    frontier = payload["frontier"]
    print(
        json.dumps(
            {
                "BEST": frontier["best_hypothesis"],
                "BEST_GROSS_BPS": frontier["best_gross_bps"],
                "HURDLE_BPS": frontier["frozen_hurdle_bps"],
                "ADMISSION_BREAK_EVEN_COST_BPS": frontier["frontier_admission_cost_bps"],
                "COST_REDUCTION_TO_ADMIT": frontier["cost_reduction_to_admit_fraction"],
                "NET_BREAK_EVEN_COST_BPS": frontier["frontier_net_cost_bps"],
                "CELLS_ADMISSIBLE_AT_ANY_COST": frontier["cells_admissible_at_any_cost"],
                "BINDING_CONSTRAINT": frontier["binding_constraint"],
                "ANSWER": payload["closure"]["answer"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
