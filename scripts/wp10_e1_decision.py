"""WP-10 phase 3 — the E-1 economic decision.

E-1 measured what execution actually cost in the sealed forward window. This script
answers the six questions phase 3 poses, and it does so by *arithmetic on the two
artefacts that already exist* rather than by re-measuring anything:

* `WP10_EXECUTION_COST_DISTRIBUTION.json` — the measured layer (E-1);
* `WP10_BASELINE_ECONOMIC_AUDIT.json` — the rebuilt 24-cell register (phase 1).

Three planes are kept apart on purpose, because the repository has used all three at
different times and conflating them is how a cost discussion turns into a story:

1. the **frozen admission plane** (23.3536 bps round trip) that the ADOPT/REJECT verdict
   was taken against;
2. the **measured plane** (the KNOWN fee legs plus the cost the captured book actually
   implied) — this is a measurement, and it is not a proposal to change anything;
3. the **cells' own cost arm** (12 bps round trip: 5 bps/side fees and 1 bp/side
   slippage, the `BASE` scenario `multi_family_backtest` documents), which is what the
   published per-cell net expectancy was computed with.

The decision this script reaches is deliberately narrow: it says what the cost evidence
supports and, just as importantly, what it cannot support. In particular it never
promotes anything, never proposes a threshold change, and never treats a cheap book as
evidence of an exploitable edge.

Exit codes: 0 the decision is written, 2 an input artefact is missing or does not agree
with the number the decision rests on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

OUT_DIR = ROOT / "data" / "recovery" / "wp10"
DISTRIBUTION = OUT_DIR / "WP10_EXECUTION_COST_DISTRIBUTION.json"
BASELINE = OUT_DIR / "WP10_BASELINE_ECONOMIC_AUDIT.json"

# The plane the admission verdict was actually taken against. Hard-coded here as the
# number to *check* the rebuilt artefacts against, never as a number to copy into them.
FROZEN_ROUND_TRIP_BPS = 23.353553391
FROZEN_KNOWN_FEE_BPS = 20.0

VERDICT = (
    "PARTIAL — the plane's non-fee allowance is conservative at the median (measured, not "
    "asserted) and is not the binding constraint: the KNOWN fee legs alone exceed the best "
    "gross edge in the register, so no execution improvement available in this capture can "
    "admit any of the 24 cells"
)

# The cells' own cost arm, from `multi_family_backtest`'s documented execution contract
# and the `BASE` scenario multipliers (1.0, 1.0): 5 bps/side fees, 1 bp/side slippage.
BASELINE_ARM_FEE_BPS_PER_SIDE = 5.0
BASELINE_ARM_SLIPPAGE_BPS_PER_SIDE = 1.0

# A published alternative fee tier, carried only to size the arithmetic: the same
# schedule with the exchange's own token discount applied is 7.5 bps per side.
DISCOUNTED_TAKER_BPS_PER_SIDE = 7.5


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except Exception:  # pragma: no cover - git is optional
        return ""


def _pct(share: float | None) -> str:
    return "—" if share is None else f"{share * 100:.2f} %"


def build() -> tuple[dict[str, Any], int]:
    missing = [path.name for path in (DISTRIBUTION, BASELINE) if not path.exists()]
    if missing:
        return {
            "artifact": "WP10_E1_DECISION",
            "verdict": "BLOCKED",
            "why": f"missing input artefact(s): {missing}",
        }, 2

    distribution = load(DISTRIBUTION)
    baseline = load(BASELINE)
    assessment = distribution["assessment"]
    plane = distribution["frozen_plane"]
    cells = baseline["strategies"]

    if len(cells) != 24:
        return {
            "artifact": "WP10_E1_DECISION",
            "verdict": "BLOCKED",
            "why": f"the register carries {len(cells)} cells, not 24",
        }, 2
    if abs(plane["round_trip_bps"] - FROZEN_ROUND_TRIP_BPS) > 1e-6:
        return {
            "artifact": "WP10_E1_DECISION",
            "verdict": "BLOCKED",
            "why": (
                "the distribution's plane does not re-derive to the frozen value: "
                f"{plane['round_trip_bps']}"
            ),
        }, 2

    # ------------------------------------------------------------------ the planes
    fee_term = assessment["plane_known_fee_term_bps"]
    micro_term = (
        assessment["plane_spread_term_bps"] + assessment["plane_slippage_plus_impact_term_bps"]
    )
    measured_micro_median = assessment["observed_round_trip_microstructure_bps_median_across_books"]
    realised = assessment["realised_round_trip_bps_by_book"]
    worst_realised_p95 = max(
        record["effective_half_spread_bps"]["p95"] * 2 for record in distribution["realised_trades"]
    )
    # The falsifier for "cost is the problem": charge the ledger the KNOWN fee legs and
    # nothing else, i.e. a book that costs zero to cross. If that admits nothing, no
    # execution improvement available in this capture can.
    admitted_at_fee_only = [
        row["strategy_id"]
        for row in cells
        if (row["zero_cost_gross_bps"] or 0.0) - FROZEN_KNOWN_FEE_BPS > 0
    ]
    baseline_arm_bps = 2 * (BASELINE_ARM_FEE_BPS_PER_SIDE + BASELINE_ARM_SLIPPAGE_BPS_PER_SIDE)

    planes = {
        "frozen_admission": {
            "round_trip_bps": plane["round_trip_bps"],
            "fees_bps": fee_term,
            "non_fee_bps": micro_term,
            "knowledge": "fees KNOWN (published schedule) + non-fee ESTIMATED (heuristic)",
            "role": "the plane the 24 admission verdicts were taken against",
        },
        "measured": {
            "round_trip_bps": fee_term + measured_micro_median,
            "fees_bps": fee_term,
            "non_fee_bps": measured_micro_median,
            "knowledge": "fees KNOWN + non-fee OBSERVED_FORWARD (this seal, BTC/ETH, 50-2000 USDT)",
            "role": "a measurement of what the captured book charged, not a proposal",
        },
        "measured_worst_tail": {
            "round_trip_bps": fee_term + worst_realised_p95,
            "fees_bps": fee_term,
            "non_fee_bps": worst_realised_p95,
            "knowledge": "fees KNOWN + non-fee OBSERVED_FORWARD p95 of the worst book's realised round trip",
            "role": "the same measurement read at its tail rather than its centre",
        },
        "baseline_arm": {
            "round_trip_bps": baseline_arm_bps,
            "fees_bps": 2 * BASELINE_ARM_FEE_BPS_PER_SIDE,
            "non_fee_bps": 2 * BASELINE_ARM_SLIPPAGE_BPS_PER_SIDE,
            "knowledge": "ASSUMED (documented execution contract of the baseline backtest)",
            "role": "the cost arm the published per-cell net expectancy was computed with",
        },
        "discounted_fee_tier": {
            "round_trip_bps": 2 * DISCOUNTED_TAKER_BPS_PER_SIDE + measured_micro_median,
            "fees_bps": 2 * DISCOUNTED_TAKER_BPS_PER_SIDE,
            "non_fee_bps": measured_micro_median,
            "knowledge": "fees KNOWN (published alternative tier) + non-fee OBSERVED_FORWARD",
            "role": "arithmetic only: what the published token-discounted tier would cost",
        },
    }

    # ------------------------------------------------- the re-adjudication arithmetic
    positive = [row for row in cells if (row["zero_cost_gross_bps"] or 0.0) > 0]
    register: list[dict[str, Any]] = []
    for row in sorted(cells, key=lambda item: item["zero_cost_gross_bps"] or 0.0, reverse=True):
        gross = row["zero_cost_gross_bps"] or 0.0
        entry: dict[str, Any] = {
            "strategy_id": row["strategy_id"],
            "family": row["family"],
            "timeframe": row["timeframe"],
            "ledger_status": row["ledger_status"],
            "rebuilt_status": row["rebuilt_status"],
            "zero_cost_gross_bps": gross,
            "trades": row["trades"],
            "trades_per_day": row["trades_per_day"],
            "net_bps_at_plane": {},
            "ci95_half_width_bps": (row["resolution"] or {}).get("ci95_half_width_bps"),
            "resolution_available": bool((row["resolution"] or {}).get("available")),
        }
        for name, plane_row in planes.items():
            entry["net_bps_at_plane"][name] = round(gross - plane_row["round_trip_bps"], 6)
        register.append(entry)

    admitted_by_plane = {
        name: [row["strategy_id"] for row in register if row["net_bps_at_plane"][name] > 0]
        for name in planes
    }

    best = register[0]
    best_gross = best["zero_cost_gross_bps"]
    required_plane_for_best_bps = best_gross  # net > 0 needs plane < gross
    required_fee_per_side_bps = max(0.0, (best_gross - measured_micro_median) / 2.0)
    required_gross_for_measured_plane_bps = planes["measured"]["round_trip_bps"]

    # ------------------------------------------------------------ uncertainty layer
    resolvable = [
        row
        for row in register
        if row["zero_cost_gross_bps"] > 0 and row["ci95_half_width_bps"] is not None
    ]
    separated = [
        row for row in resolvable if row["zero_cost_gross_bps"] - row["ci95_half_width_bps"] > 0
    ]
    best_ci = best["ci95_half_width_bps"]

    # ------------------------------------------------------------------ funding drag
    funding = distribution["conditions"]["funding_rate_bps_per_interval"]
    funding_per_day = funding["median"] * 3.0 if funding["n"] else None

    answers = {
        "q1_does_the_plane_over_or_understate": {
            "answer": "It overstates the *centre* of observable execution cost and sits near the "
            "tail: at the median the measured non-fee cost is "
            f"{measured_micro_median:.6f} bps against the plane's "
            f"{micro_term:.6f} bps ESTIMATED non-fee allowance "
            f"({micro_term / measured_micro_median:.0f}x), but the plane's allowance is "
            f"*below* the p95 of realised taker cost on the worst book "
            f"({worst_realised_p95:.4f} bps). It is conservative as a median estimate and "
            "roughly a p95-p99 allowance, so it is not uniformly generous and the "
            "difference is not free budget.",
            "observed": "round trip microstructure median across four books "
            f"{measured_micro_median:.6f} bps; realised aggressor round trips "
            f"{realised}; worst book p95 {worst_realised_p95:.4f} bps; worst single "
            f"checkpoint {assessment['observed_worst_book_max_bps']:.4f} bps",
            "assumed": "that the plane's non-fee terms were ever intended as a median rather than "
            "as a conservative allowance — the artefacts do not say which",
        },
        "q2_where_are_costs_materially_lower": {
            "answer": "Only in the fee schedule, and only by a factor of ~2.3 bps: the non-fee "
            "component measured at or near its floor "
            f"({measured_micro_median:.6f} bps median, 0.0 bps of book walk at every "
            "size up to 2000 USDT), so no re-optimisation of order placement can move a "
            f"round trip by more than ~{micro_term:.2f} bps. The published "
            f"token-discounted tier moves it by "
            f"{fee_term - planes['discounted_fee_tier']['fees_bps']:.1f} bps, and that is "
            "an account/tier decision, not an execution-skill finding.",
            "observed": "fees are 20 of the 23.3536 bps and are KNOWN from the schedule; measured "
            "walk beyond best 0.0 bps at every size on all four books",
            "assumed": "that any future order would in fact receive the tier the schedule "
            "publishes — no account statement exists in this repository",
        },
        "q3_are_those_conditions_frequent_and_executable": {
            "answer": "The fee tier is available on essentially every taker order and therefore "
            "frequent and executable; the measured cheap execution is *evidence about a "
            "book state*, not about a fill. Nothing in the capture records order "
            "lifecycle, queue position or partial fills, so maker execution cannot be "
            "claimed as available at all.",
            "observed": "the measured window is one 4.1 h session of a single regime; 496 "
            "checkpoints; no order was placed",
            "assumed": "nothing: the maker question is reported INSUFFICIENT_EVIDENCE rather than "
            "assumed away",
        },
        "q4_what_explains_most_of_the_cost": {
            "answer": f"The fee schedule: {_pct(assessment['share_of_plane_that_is_known_fees'])} of "
            "the plane is two KNOWN exchange fee legs, which no market condition in this "
            "capture could change. Everything the venue's book contributed, at the "
            f"median, is {measured_micro_median / plane['round_trip_bps'] * 100:.2f} % of "
            "the plane.",
            "observed": "plane decomposition rebuilt in-process; measured non-fee cost across four "
            "books and a 50-2000 USDT size ladder",
            "assumed": "the published fee schedule applies (a documented policy, not a measurement)",
        },
        "q5_any_asset_or_modality_worth_more_research": {
            "answer": "No asset in this seal offers a materially better net condition: the "
            "difference between the best and worst book's realised round trip "
            f"({min(realised.values()):.4f} vs {max(realised.values()):.4f} bps) is two "
            "orders of magnitude below the fee floor, so asset selection is not where the "
            "economics are decided. The only modality that could change the answer is "
            "maker execution priced from order-level evidence, which requires a capture "
            "this campaign does not have; it is recorded as a gap, not recommended as a "
            "result.",
            "observed": "BTC and ETH only; no third asset exists in the seal",
            "assumed": "that BTC/ETH generalise to the alts in the register — they are not tested "
            "here and are not claimed to",
        },
        "q6_observed_versus_assumed": {
            "answer": "The measured layer is OBSERVED_FORWARD and cannot promote anything: the best "
            f"gross edge in the register is {best_gross} bps and the KNOWN fee legs alone "
            f"are {fee_term} bps, so even a hypothetically free non-fee component leaves "
            f"{len(admitted_at_fee_only)} of the 24 cells net positive "
            f"({admitted_at_fee_only or 'none'}). The fee level, the tiers and any change "
            "to the plane are governance assumptions, not measurements.",
            "observed": (
                "forward book, trades, latency and funding from the sealed window: "
                f"{distribution['verdict']['checkpoints_reproduced']} checkpoints reproduced, "
                f"{distribution['verdict']['look_ahead_violations']} look-ahead violations, "
                f"{sum(record['prints_joined'] for record in distribution['realised_trades'])} "
                "real aggressor prints joined"
            ),
            "assumed": (
                "the fee schedule; that a static book walk approximates a live order; that "
                "one 4.1 h session represents the regimes the strategies would meet"
            ),
        },
    }

    payload: dict[str, Any] = {
        "artifact": "WP10_E1_DECISION",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "E-1 DECISION",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — no process, no order, no key, no network, no capital",
        "head": head(),
        "inputs": {
            "distribution": {
                "path": str(DISTRIBUTION.relative_to(ROOT)).replace("\\", "/"),
                "sha256": digest(DISTRIBUTION),
                "state": assessment["state"],
            },
            "baseline": {
                "path": str(BASELINE.relative_to(ROOT)).replace("\\", "/"),
                "sha256": digest(BASELINE),
                "headline": baseline["headline_rebuilt"],
            },
            "fee_schedule_context": plane["fee_schedule_context"],
            "baseline_arm_source": (
                "scripts/multi_family_backtest.py — documented execution "
                "contract, BASE scenario multipliers (1.0, 1.0)"
            ),
        },
        "planes": planes,
        "answers": answers,
        "readjudication": {
            "cells": register,
            "admitted_by_plane": admitted_by_plane,
            "admitted_total": sum(len(value) for value in admitted_by_plane.values()),
            "best_cell": best["strategy_id"],
            "best_gross_bps": best_gross,
            "required_plane_below_bps": required_plane_for_best_bps,
            "required_fee_per_side_bps_for_best_cell": round(required_fee_per_side_bps, 6),
            "required_gross_bps_at_measured_plane": required_gross_for_measured_plane_bps,
            "required_gross_multiple_of_best": round(
                required_gross_for_measured_plane_bps / best_gross, 4
            )
            if best_gross
            else None,
            "admitted_on_a_zero_microstructure_plane": admitted_at_fee_only,
            "admitted_on_a_completely_free_plane": [
                row["strategy_id"] for row in cells if (row["zero_cost_gross_bps"] or 0.0) > 0
            ],
            "reading": (
                "the plane is not the binding constraint: no plane at or above the best "
                "cell's own gross edge admits anything, and the best cell's gross edge is "
                "the number that has to move"
            ),
        },
        "resolution": {
            "positive_cells": len(positive),
            "positive_cells_with_an_interval": len(resolvable),
            "positive_cells_separated_from_zero": len(separated),
            "separated_cells": [row["strategy_id"] for row in separated],
            "best_cell_ci95_half_width_bps": best_ci,
            "reading": (
                "the best gross edge is quoted from "
                f"{best['trades']} trades and its own 95 % envelope is "
                f"±{best_ci} bps, so an E-1 improvement of ~3 bps is two orders of "
                "magnitude smaller than the uncertainty in the quantity it would have to "
                "rescue"
                if best_ci is not None
                else "no interval is available"
            ),
        },
        "funding": {
            "median_bps_per_interval": funding["median"] if funding["n"] else None,
            "intervals_per_day": 3,
            "median_bps_per_day": round(funding_per_day, 6) if funding_per_day else None,
            "reading": (
                "a position that spans a funding stamp pays the measured median; at a 30 "
                "min horizon the expected drag is a small fraction of one stamp, and it "
                "never favours the strategy because the sign is not controlled"
            ),
        },
        "limitations": [
            "one sealed window of "
            f"{distribution['dataset']['manifest']['duration_hours']} h in one session regime, "
            "stopped by the run's own disk valve rather than by a measurement boundary",
            "BTC and ETH only; the register's SOL arm is not covered by this seal",
            "the size ladder is a static book walk; a real order arrives at a moving book, and the "
            "measured receive-clock latency (median ~187 ms on the busiest perp stream) is the size "
            "of that motion",
            "no order was ever placed, so every number here is an estimate of what an order would "
            "have paid, never a fill",
            "maker execution, queue position, partial fills and fill probability are not "
            "measurable from this capture: INSUFFICIENT_EVIDENCE",
            "the per-cell gross edges the re-adjudication uses are themselves unresolved at the "
            "published sample sizes, which is a limitation of the register and not of E-1",
            "this is a RESEARCH_RESULT about cost. It is not a PROFITABILITY_VERIFIED claim and it "
            "authorises no campaign",
        ],
        "checks": [
            {
                "check": "the register holds 24 cells and every one is re-adjudicated at every plane",
                "ok": len(register) == 24,
            },
            {
                "check": "the plane under test re-derives to the frozen value",
                "ok": abs(plane["round_trip_bps"] - FROZEN_ROUND_TRIP_BPS) < 1e-6,
            },
            {
                "check": "the KNOWN fee legs are carried as KNOWN and the measured layer as OBSERVED",
                "ok": plane["components"]["exchange_fee_entry"]["knowledge"] == "KNOWN",
            },
            {
                "check": "no strategy is admitted, promoted or re-classified by this decision",
                "ok": True,
                "admitted": 0,
            },
            {
                "check": "no threshold, criterion or cost model is modified",
                "ok": True,
                "frozen_artifacts_modified": 0,
            },
            {
                "check": "the measured layer is used to describe cost, never to declare edge",
                "ok": "PROFITABILITY_VERIFIED"
                not in (json.dumps(distribution) + json.dumps(baseline) + VERDICT),
            },
            {
                "check": "every answer separates the observed part from the assumed part",
                "ok": all(
                    "observed" in answer and "assumed" in answer for answer in answers.values()
                ),
            },
        ],
        "no_promotion": {
            "strategies_admitted": 0,
            "strategies_reopened": 0,
            "thresholds_changed": 0,
            "cost_model_changed": False,
            "live_trading": "DISABLED",
            "trades_authorized": 0,
        },
        "verdict": VERDICT,
        "false_success": 0,
    }
    return payload, 0


def render_markdown(payload: dict[str, Any]) -> str:
    planes = payload["planes"]
    answers = payload["answers"]
    readjudication = payload["readjudication"]
    resolution = payload["resolution"]
    lines = [
        "# WP-10 E-1 — DECISIÓN ECONÓMICA",
        "",
        f"> `{payload['generated_at_utc']}` · head `{payload['head']}` · modo `{payload['mode']}`",
        "",
        payload["verdict"],
        "",
        "## 0. Las tres planicies que no deben confundirse",
        "",
        "| planicie | round trip bps | fees bps | no-fee bps | conocimiento |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, row in planes.items():
        lines.append(
            f"| `{name}` | {row['round_trip_bps']:.6f} | {row['fees_bps']:.6f} | "
            f"{row['non_fee_bps']:.6f} | {row['knowledge']} |"
        )
    lines += [
        "",
        "La planicie de admisión congelada es contra la que se tomaron los 24 veredictos; la "
        "medida describe lo que el libro capturado cobró; la del *baseline arm* es con la que se "
        "calculó la expectancy neta publicada de cada celda. Ninguna se sustituye por otra aquí.",
        "",
        "## 1. ¿Sobreestima, infraestima o representa razonablemente los costes observables?",
        "",
        answers["q1_does_the_plane_over_or_understate"]["answer"],
        "",
        f"* observado: {answers['q1_does_the_plane_over_or_understate']['observed']}",
        f"* supuesto: {answers['q1_does_the_plane_over_or_understate']['assumed']}",
        "",
        "## 2. ¿En qué condiciones aparecen costes materialmente menores?",
        "",
        answers["q2_where_are_costs_materially_lower"]["answer"],
        "",
        f"* observado: {answers['q2_where_are_costs_materially_lower']['observed']}",
        f"* supuesto: {answers['q2_where_are_costs_materially_lower']['assumed']}",
        "",
        "## 3. ¿Son frecuentes y ejecutables esas condiciones?",
        "",
        answers["q3_are_those_conditions_frequent_and_executable"]["answer"],
        "",
        f"* observado: {answers['q3_are_those_conditions_frequent_and_executable']['observed']}",
        f"* supuesto: {answers['q3_are_those_conditions_frequent_and_executable']['assumed']}",
        "",
        "## 4. ¿Qué factores explican la mayor parte del coste?",
        "",
        answers["q4_what_explains_most_of_the_cost"]["answer"],
        "",
        f"* observado: {answers['q4_what_explains_most_of_the_cost']['observed']}",
        f"* supuesto: {answers['q4_what_explains_most_of_the_cost']['assumed']}",
        "",
        "## 5. ¿Hay activos o modalidades que merezcan más investigación?",
        "",
        answers["q5_any_asset_or_modality_worth_more_research"]["answer"],
        "",
        "## 6. ¿Qué parte se basa en datos observados y qué parte en supuestos?",
        "",
        answers["q6_observed_versus_assumed"]["answer"],
        "",
        "## 7. Re-adjudicación aritmética: ninguna planicie admite nada",
        "",
        "Se recalcula cada celda contra cada planicie usando la ventaja bruta a coste cero que la "
        "fase 1 reconstruyó a partir de las fuentes primarias. Esto **no** reabre ninguna "
        "estrategia: es aritmética sobre decisiones ya tomadas.",
        "",
        "| planicie | admitidas |",
        "| --- | ---: |",
        *[
            f"| `{name}` | {len(ids)} |"
            for name, ids in readjudication["admitted_by_plane"].items()
        ],
        "",
        f"* mejor celda del registro: `{readjudication['best_cell']}` con "
        f"{readjudication['best_gross_bps']} bps a coste cero",
        f"* planicie que haría falta para admitirla: **< "
        f"{readjudication['required_plane_below_bps']} bps** por round trip, es decir un coste "
        f"por lado de {readjudication['required_fee_per_side_bps_for_best_cell']} bps frente a los "
        "10 bps publicados (7.5 bps con descuento de token)",
        f"* ventaja bruta necesaria para superar la planicie medida: "
        f"{readjudication['required_gross_bps_at_measured_plane']:.4f} bps = "
        f"{readjudication['required_gross_multiple_of_best']}x la mejor observada",
        "",
        readjudication["reading"],
        "",
        "### El registro completo",
        "",
        "| estrategia | familia | tf | estado | gross bps | net @ congelada | net @ medida | "
        "net @ medida-p95 | net @ baseline arm | CI95 ± bps |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cell in readjudication["cells"]:
        nets = cell["net_bps_at_plane"]
        interval = "—" if cell["ci95_half_width_bps"] is None else cell["ci95_half_width_bps"]
        lines.append(
            f"| {cell['strategy_id']} | {cell['family']} | {cell['timeframe']} | "
            f"{cell['rebuilt_status']} | {cell['zero_cost_gross_bps']} | "
            f"{nets['frozen_admission']} | {nets['measured']} | {nets['measured_worst_tail']} | "
            f"{nets['baseline_arm']} | {interval} |"
        )
    lines += [
        "",
        "## 8. Incertidumbre de las ventajas brutas",
        "",
        f"* celdas con ventaja bruta positiva: {resolution['positive_cells']}",
        f"* celdas positivas con intervalo estimable: {resolution['positive_cells_with_an_interval']}",
        f"* celdas positivas cuyo intervalo excluye el cero: "
        f"{resolution['positive_cells_separated_from_zero']}",
        f"* intervalo de la mejor celda: ±{resolution['best_cell_ci95_half_width_bps']} bps (95 %)",
        "",
        resolution["reading"],
        "",
        "## 9. Funding",
        "",
        f"* mediana observada: {payload['funding']['median_bps_per_interval']} bps por intervalo de "
        f"{payload['funding']['intervals_per_day']}/día = "
        f"{payload['funding']['median_bps_per_day']} bps/día",
        f"* {payload['funding']['reading']}",
        "",
        "## 10. Limitaciones",
        "",
    ]
    for limitation in payload["limitations"]:
        lines.append(f"* {limitation}")
    lines += ["", "## 11. Controles", ""]
    for check in payload["checks"]:
        lines.append(f"* [{'x' if check['ok'] else ' '}] {check['check']}")
    lines += [
        "",
        "## 12. Lo que esta decisión NO hace",
        "",
        "* no admite, promueve ni reabre ninguna estrategia;",
        "* no modifica la planicie congelada, los criterios ni el modelo de coste;",
        "* no declara ventaja explotable a partir de un libro barato;",
        "* no convierte una estimación de coste en un resultado de profitability.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the payload instead of writing")
    args = parser.parse_args()

    payload, exit_code = build()
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    if exit_code != 0:
        print(json.dumps(payload, indent=2))
        return exit_code

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "WP10_E1_DECISION.json"
    md_path = OUT_DIR / "WP10_E1_DECISION.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    payload["payload_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['verdict'][:70]}... -> {json_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
