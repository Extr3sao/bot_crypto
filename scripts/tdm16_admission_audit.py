"""WP-016A — audit the 24 strategies: why each one is refused, with arithmetic.

Reads only committed artifacts and recomputes the verdict; it never asks the
runtime, the ledger or the builder for its opinion:

* ``config/strategy_admission.json``          ledger (what the runtime reads)
* ``data/recovery/COST_BARRIER_EXPLORER.json`` cost plane + per-cell gross
* ``docs/STRATEGY_ADMISSION_MATRIX.json``       pre-registered checks c1..c8
* ``docs/STRATEGY_DISCOVERY_V3_RESULTS.json``  the gross-edge measurements

For every ``family@timeframe`` the audit answers three questions separately,
because collapsing them is how "0 admitted" turns into a vague story:

1. **Does the ledger agree with its own rule?** The rule is
   ``PAPER_CANDIDATE := family ∈ matrix.paper_candidates AND gross_bps > 0``
   (``scripts/build_strategy_admission.py``). Recomputed here from the matrix
   and the ledger's own gross, then compared row by row.
2. **Why is this cell refused?** A single coded cause, never a sentence that
   hides the criterion: ``NO_GROSS_EDGE``, ``COST_KILLED_NOT_PREREGISTERED``
   (positive gross, family never placed in ``paper_candidates``),
   ``COST_KILLED_CRITERIA`` (in ``paper_candidates`` but net/OOS/2X fail).
3. **Could any available cost line save it?** The upper bound is
   ``gross - cheapest line``: with zero slippage and a perfect fill, net cannot
   exceed that. Two lines are used, both from the explorer: the cheapest
   *measured* line and the cheapest *assumed* line on the venue family the
   runtime actually trades. If the bound is negative the cell is dead on
   arithmetic, not on opinion — no new indicator, sample or backtest changes it.

The audit also verifies provenance: the ledger records the sha256 of both
research artifacts, and those hashes are recomputed from disk here. A ledger
whose own sources no longer match its recorded hashes is not evidence.

Usage:
    uv run python scripts/tdm16_admission_audit.py \
        --out evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.json \
        --markdown evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

LEDGER = Path("config/strategy_admission.json")
EXPLORER = Path("data/recovery/COST_BARRIER_EXPLORER.json")
MATRIX = Path("docs/STRATEGY_ADMISSION_MATRIX.json")
V3_RESULTS = Path("docs/STRATEGY_DISCOVERY_V3_RESULTS.json")

AUDIT_SCHEMA_VERSION = "wp-tdm-16-admission-audit-v1"

# Gross edges are published with different rounding in each artifact (the
# ledger rounds to 2 decimals, the explorer keeps 3). A mismatch beyond this
# tolerance is a real disagreement, not rounding.
GROSS_TOLERANCE_BPS = 0.0051
# Two artifacts can also disagree by more than rounding while both remaining
# right: the 5m diagnostic publishes an already-rounded 2-decimal bps figure
# while the explorer re-derives gross/trade from its own ledger. Such a
# difference is recorded as an artifact divergence and is only immaterial while
# it changes neither the sign of the edge nor which side of a cost line the
# cell sits on.
GROSS_DIVERGENCE_IMMATERIAL_BPS = 0.05


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cost_plane(explorer: dict[str, Any]) -> dict[str, Any]:
    """The three lines that decide reachability, with their knowledge class."""
    frontier = (explorer.get("reachability") or {}).get("frontier") or {}
    measured = (
        frontier.get("cheapest_line_observed_only")
        or frontier.get("cheapest_line_taker")
        or {}
    )
    assumed_any = frontier.get("cheapest_line_any") or {}
    grid = explorer.get("venue_grid") or []
    # The cheapest *assumed* maker line on the venue family the PAPER runtime
    # trades (Binance USDⓈ-M perpetuals). Its maker fee is modelled, its fill
    # probability is not — that is the whole difference from ``measured``.
    futures_maker = [
        row
        for row in grid
        if str(row.get("scenario_id", "")).endswith("USDM_PERP_MAKER")
        and str(row.get("order_mode")) == "maker"
        and float(row.get("size_usd") or 0.0) == 200.0
        and str(row.get("liquidity_regime")) == "deep"
    ]
    futures_maker_row = futures_maker[0] if futures_maker else {}
    cells = explorer.get("cells") or []
    runtime_lines = sorted(
        {
            round(float(cell.get("runtime_admission_rt_bps") or 0.0), 6)
            for cell in cells
        }
    )
    return {
        "cheapest_measured": {
            "scenario_id": measured.get("scenario_id"),
            "venue": measured.get("venue"),
            "order_mode": measured.get("order_mode"),
            "round_trip_bps": float(measured.get("round_trip_bps") or 0.0),
            "knowledge_class": measured.get("knowledge_class"),
            "rests_on_assumed_component": bool(measured.get("rests_on_assumed_component")),
        },
        "cheapest_any": {
            "scenario_id": assumed_any.get("scenario_id"),
            "venue": assumed_any.get("venue"),
            "order_mode": assumed_any.get("order_mode"),
            "round_trip_bps": float(assumed_any.get("round_trip_bps") or 0.0),
            "knowledge_class": assumed_any.get("knowledge_class"),
            "rests_on_assumed_component": bool(assumed_any.get("rests_on_assumed_component")),
        },
        "assumed_futures_maker": {
            "scenario_id": futures_maker_row.get("scenario_id"),
            "round_trip_bps": float(futures_maker_row.get("round_trip_bps") or 0.0),
            "knowledge_class": futures_maker_row.get("knowledge_class"),
            "rests_on_assumed_component": bool(
                futures_maker_row.get("rests_on_assumed_component")
            ),
            "liquidity_regime": futures_maker_row.get("liquidity_regime"),
            "size_usd": futures_maker_row.get("size_usd"),
        },
        "runtime_admission_rt_bps_values": runtime_lines,
    }


def _family_criteria(matrix: dict[str, Any]) -> dict[str, Any]:
    """c1..c8 per family, exactly as pre-registered (c6/c8 are ``null``)."""
    out: dict[str, Any] = {}
    for family, entry in sorted((matrix.get("admissions") or {}).items()):
        checks = dict(entry.get("checks") or {})
        out[family] = {
            "status": entry.get("status"),
            "checks": checks,
            "failed": sorted(k for k, v in checks.items() if v is False),
            "unknown": sorted(k for k, v in checks.items() if v is None),
            "mandatory_failures": list(entry.get("mandatory_failures") or []),
            "net_base": (entry.get("totals_base") or {}).get("net"),
            "pf_base": (entry.get("totals_base") or {}).get("profit_factor"),
            "pf_2x": (entry.get("totals_2x") or {}).get("profit_factor"),
            "oos_net": (entry.get("oos") or {}).get("net"),
            "oos_pf": (entry.get("oos") or {}).get("profit_factor"),
            "trades_base": (entry.get("totals_base") or {}).get("trades"),
        }
    return out


def _recompute_status(
    *, family: str, gross_bps: float, paper_candidates: set[str], criteria: dict[str, Any]
) -> str:
    """The builder's rule, plus the criteria split the builder leaves implicit."""
    if family in paper_candidates and gross_bps > 0:
        return "PAPER_CANDIDATE"
    if gross_bps > 0:
        fam = criteria.get(family) or {}
        if family in paper_candidates:
            return "COST_KILLED_CRITERIA"
        if fam.get("failed"):
            return "COST_KILLED_CRITERIA" if "c2_net_positive" in fam["failed"] else (
                "COST_KILLED_NOT_PREREGISTERED"
            )
        return "COST_KILLED_NOT_PREREGISTERED"
    return "NO_GROSS_EDGE"


def build_audit(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    ledger = _load(repo_root / LEDGER)
    explorer = _load(repo_root / EXPLORER)
    matrix = _load(repo_root / MATRIX)
    v3 = _load(repo_root / V3_RESULTS)

    strategies: dict[str, Any] = {
        k: v for k, v in (ledger.get("strategies") or {}).items() if not k.startswith("_")
    }
    paper_candidates = set(matrix.get("paper_candidates") or [])
    criteria = _family_criteria(matrix)
    cost = _cost_plane(explorer)
    cells = {str(c.get("cell_id")): c for c in (explorer.get("cells") or [])}
    timeframe_evidence = (
        ((v3.get("hypotheses") or {}).get("D-01_timeframe_horizon") or {}).get("evidence") or {}
    )
    tf_gross = timeframe_evidence.get("zero_cost_gross_bps_per_trade") or {}
    diagnostics = v3.get("family_5m_diagnostic_zero_cost") or {}

    measured = cost["cheapest_measured"]["round_trip_bps"]
    assumed_futures = cost["assumed_futures_maker"]["round_trip_bps"]
    assumed_any = cost["cheapest_any"]["round_trip_bps"]

    rows: list[dict[str, Any]] = []
    for strategy_id in sorted(strategies):
        entry = strategies[strategy_id]
        family = str(entry.get("family") or strategy_id.split("@")[0])
        timeframe = str(entry.get("timeframe") or strategy_id.split("@")[-1])
        gross = float(entry.get("expected_gross_edge_bps") or 0.0)
        evidence = entry.get("edge_evidence") or {}
        trades = int(evidence.get("sample_trades") or 0)

        cell = cells.get(strategy_id) or {}
        cell_gross = cell.get("zero_cost_gross_bps")
        gross_delta = (
            None
            if cell_gross is None
            else round(gross - float(cell_gross), 6)
        )
        gross_matches_explorer = (
            None if gross_delta is None else abs(gross_delta) <= GROSS_TOLERANCE_BPS
        )
        if gross_delta is None:
            delta_class = "UNMEASURED"
        elif abs(gross_delta) <= GROSS_TOLERANCE_BPS:
            delta_class = "AGREES"
        elif (
            abs(gross_delta) <= GROSS_DIVERGENCE_IMMATERIAL_BPS
            and math.copysign(1.0, gross) == math.copysign(1.0, float(cell_gross))
            and (gross > measured) == (float(cell_gross) > measured)
        ):
            delta_class = "ARTIFACT_DIVERGENCE_IMMATERIAL"
        else:
            delta_class = "ARTIFACT_DIVERGENCE_MATERIAL"

        # Re-derive the published gross from the measurement artifact itself.
        if timeframe == "5m":
            published = (diagnostics.get(family) or {}).get("gross_bps_per_trade")
            published_source = "family_5m_diagnostic_zero_cost.gross_bps_per_trade"
        else:
            published = ((tf_gross.get(family) or {}).get(timeframe))
            published_source = (
                "D-01_timeframe_horizon.evidence.zero_cost_gross_bps_per_trade."
                f"{family}.{timeframe}"
            )
        published_delta = (
            None if published is None else round(gross - float(published), 6)
        )
        gross_matches_measurement = (
            None
            if published_delta is None
            else abs(published_delta) <= GROSS_TOLERANCE_BPS
        )

        # Best available estimate of the edge: the explorer keeps 3 decimals on
        # a value the ledger rounds to 2, and the arithmetic bound must use the
        # number that favours the cell, not the one that makes it look worse.
        gross_best = gross if cell_gross is None else float(cell_gross)

        recomputed = _recompute_status(
            family=family,
            gross_bps=gross,
            paper_candidates=paper_candidates,
            criteria=criteria,
        )
        ledger_status = str(entry.get("status") or "")
        admitted = bool(entry.get("admitted_for_paper"))

        causes: list[str] = []
        if gross <= 0:
            causes.append("NO_GROSS_EDGE")
        else:
            causes.append("GROSS_BELOW_CHEAPEST_MEASURED_LINE")
            if family not in paper_candidates:
                causes.append("FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES")
            fam = criteria.get(family) or {}
            if timeframe == "5m" and fam.get("failed"):
                # The pre-registered checks were audited on the 5m diagnostic:
                # this is the cell they were measured on.
                causes.append("PREREGISTERED_CRITERIA_FAILED")
            if timeframe != "5m":
                # No 15m/30m/1h cell has its own net, OOS, drawdown or 2x-cost
                # measurement: the family-level failure is context, not a
                # verdict about this horizon, so it is named separately.
                causes.append("NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME")
                if fam.get("failed"):
                    causes.append("FAMILY_CRITERIA_FAILED_AT_5M")
            if trades == 0:
                causes.append("SAMPLE_UNPROVEN_IN_LEDGER")

        rows.append(
            {
                "strategy_id": strategy_id,
                "family": family,
                "timeframe": timeframe,
                "ledger_status": ledger_status,
                "ledger_admitted": admitted,
                "status_recomputed": recomputed,
                "status_rule_agrees": (
                    recomputed == ledger_status
                    or (recomputed.startswith("COST_KILLED") and ledger_status == "COST_KILLED")
                ),
                "gross_bps": gross,
                "gross_bps_explorer": cell_gross,
                "gross_delta_vs_explorer_bps": gross_delta,
                "gross_matches_explorer": gross_matches_explorer,
                "gross_delta_class_vs_explorer": delta_class,
                "gross_bps_best_estimate": gross_best,
                "gross_bps_measurement": published,
                "gross_measurement_source": published_source,
                "gross_delta_vs_measurement_bps": published_delta,
                "gross_matches_measurement": gross_matches_measurement,
                "sample_trades": trades,
                "sample_sufficient_in_ledger": trades > 0,
                "explorer_trades": cell.get("trades"),
                "rejection_causes": causes,
                "net_upper_bound_measured_bps": round(gross_best - measured, 6),
                "net_upper_bound_assumed_futures_maker_bps": round(
                    gross_best - assumed_futures, 6
                ),
                "net_upper_bound_assumed_any_bps": round(gross_best - assumed_any, 6),
                "clears_cheapest_measured": gross_best > measured,
                "clears_assumed_futures_maker": gross_best > assumed_futures,
                "clears_cheapest_any_assumed": gross_best > assumed_any,
                "criteria_failed": (criteria.get(family) or {}).get("failed", []),
                "criteria_unknown": (criteria.get(family) or {}).get("unknown", []),
                "num_runtime_orders_this_cell_could_place": 0,
            }
        )

    admitted_ids = [r["strategy_id"] for r in rows if r["ledger_admitted"]]
    max_gross_row = max(rows, key=lambda r: r["gross_bps_best_estimate"]) if rows else None
    clearing_measured = [r["strategy_id"] for r in rows if r["clears_cheapest_measured"]]
    clearing_futures_maker = [r["strategy_id"] for r in rows if r["clears_assumed_futures_maker"]]
    clearing_any = [r["strategy_id"] for r in rows if r["clears_cheapest_any_assumed"]]

    # Provenance: the ledger's own record of its sources, recomputed from disk.
    provenance: list[dict[str, Any]] = []
    for source in ledger.get("_sources") or []:
        path = str(source.get("path") or "")
        recorded = str(source.get("sha256") or "")
        disk = _sha256(repo_root / path) if path and (repo_root / path).exists() else ""
        provenance.append(
            {
                "path": path,
                "recorded_sha256": recorded,
                "recomputed_sha256": disk,
                "matches": bool(recorded) and recorded == disk,
            }
        )

    audit: dict[str, Any] = {
        "artifact": "WP-TDM-016-A · PAPER admission audit (24 strategies)",
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_by": "scripts/tdm16_admission_audit.py",
        "sources": {
            "ledger": {"path": LEDGER.as_posix(), "sha256": _sha256(repo_root / LEDGER)},
            "cost_barrier_explorer": {
                "path": EXPLORER.as_posix(),
                "sha256": _sha256(repo_root / EXPLORER),
            },
            "admission_matrix": {
                "path": MATRIX.as_posix(),
                "sha256": _sha256(repo_root / MATRIX),
            },
            "discovery_results": {
                "path": V3_RESULTS.as_posix(),
                "sha256": _sha256(repo_root / V3_RESULTS),
            },
        },
        "ledger_provenance": provenance,
        "admission_rule": (
            "PAPER_CANDIDATE := family in matrix.paper_candidates AND gross_bps > 0 "
            "(scripts/build_strategy_admission.py)"
        ),
        "matrix_paper_candidates": sorted(paper_candidates),
        "family_criteria": criteria,
        "cost_plane": cost,
        "population": {
            "strategies": len(rows),
            "admitted": len(admitted_ids),
            "gross_positive": sum(1 for r in rows if r["gross_bps"] > 0),
            "gross_negative": sum(1 for r in rows if r["gross_bps"] <= 0),
            "ledger_sample_unproven": sum(1 for r in rows if r["sample_trades"] == 0),
            "status_rule_disagreements": sum(
                1 for r in rows if not r["status_rule_agrees"]
            ),
            "gross_mismatch_vs_explorer": sum(
                1 for r in rows if r["gross_matches_explorer"] is False
            ),
            "gross_artifact_divergences_immaterial": sum(
                1
                for r in rows
                if r["gross_delta_class_vs_explorer"] == "ARTIFACT_DIVERGENCE_IMMATERIAL"
            ),
            "gross_artifact_divergences_material": sum(
                1
                for r in rows
                if r["gross_delta_class_vs_explorer"] == "ARTIFACT_DIVERGENCE_MATERIAL"
            ),
            "gross_mismatch_vs_measurement": sum(
                1 for r in rows if r["gross_matches_measurement"] is False
            ),
            "clearing_cheapest_measured": len(clearing_measured),
            "clearing_assumed_futures_maker": len(clearing_futures_maker),
            "clearing_cheapest_any_assumed": len(clearing_any),
        },
        "frontier": {
            "max_gross_bps": (
                max_gross_row["gross_bps_best_estimate"] if max_gross_row else None
            ),
            "max_gross_bps_ledger_rounded": (
                max_gross_row["gross_bps"] if max_gross_row else None
            ),
            "max_gross_cell": max_gross_row["strategy_id"] if max_gross_row else None,
            "cheapest_measured_rt_bps": measured,
            "assumed_futures_maker_rt_bps": assumed_futures,
            "cheapest_any_assumed_rt_bps": assumed_any,
            "distance_to_measured_bps": (
                round(max_gross_row["gross_bps_best_estimate"] - measured, 6)
                if max_gross_row
                else None
            ),
            "distance_to_assumed_futures_maker_bps": (
                round(max_gross_row["gross_bps_best_estimate"] - assumed_futures, 6)
                if max_gross_row
                else None
            ),
            "cells_clearing_measured": clearing_measured,
            "cells_clearing_assumed_futures_maker": clearing_futures_maker,
            "cells_clearing_any_assumed": clearing_any,
        },
        "strategies": rows,
        "gross_divergences": [
            {
                "strategy_id": r["strategy_id"],
                "ledger_bps": r["gross_bps"],
                "explorer_bps": r["gross_bps_explorer"],
                "delta_bps": r["gross_delta_vs_explorer_bps"],
                "class": r["gross_delta_class_vs_explorer"],
                "changes_sign": math.copysign(1.0, r["gross_bps"])
                != math.copysign(1.0, float(r["gross_bps_explorer"])),
                "changes_cost_side": (r["gross_bps"] > measured)
                != (float(r["gross_bps_explorer"]) > measured),
            }
            for r in rows
            if r["gross_delta_class_vs_explorer"]
            in ("ARTIFACT_DIVERGENCE_IMMATERIAL", "ARTIFACT_DIVERGENCE_MATERIAL")
        ],
        "verdict": {
            "admitted_for_paper": len(admitted_ids),
            "admitted_ids": admitted_ids,
            "economic_status": (
                "ECONOMIC_CANDIDATE" if admitted_ids else "ECONOMIC_BLOCKED"
            ),
            "decisive_reason": (
                "max measured gross edge "
                f"{max_gross_row['gross_bps_best_estimate'] if max_gross_row else 0.0:.3f} "
                "bps/trade is "
                f"below the cheapest measured round trip {measured:.3f} bps, and below the "
                f"cheapest assumed futures-maker line {assumed_futures:.3f} bps: every cell is "
                "negative even with zero slippage and a perfect fill"
                if max_gross_row
                else "no strategies in the ledger"
            ),
            "what_changes_the_verdict": (
                "a measured round-trip line below the gross of at least one cell, i.e. a "
                "maker fill rate measured from the tape (EXP-COST-LINE-001)"
            ),
        },
        "checks": [],
    }

    audit["checks"] = _self_checks(audit)
    audit["checks_total"] = len(audit["checks"])
    audit["checks_failed"] = sum(1 for c in audit["checks"] if not c["passed"])
    return audit


def _self_checks(audit: dict[str, Any]) -> list[dict[str, Any]]:
    pop = audit["population"]
    frontier = audit["frontier"]
    checks: list[dict[str, Any]] = []

    def add(claim_id: str, description: str, passed: bool, observed: Any) -> None:
        checks.append(
            {
                "id": claim_id,
                "description": description,
                "passed": bool(passed),
                "observed": observed,
            }
        )

    add("A01", "the ledger enumerates 24 strategies", pop["strategies"] == 24, pop["strategies"])
    add("A02", "none of the 24 is admitted for paper", pop["admitted"] == 0, pop["admitted"])
    add(
        "A03",
        "the matrix lists no paper candidates (the gate the rule needs)",
        audit["matrix_paper_candidates"] == [],
        audit["matrix_paper_candidates"],
    )
    add(
        "A04",
        "every ledger status is reproduced by the published rule",
        pop["status_rule_disagreements"] == 0,
        pop["status_rule_disagreements"],
    )
    add(
        "A05",
        "the ledger's recorded source hashes still match the files on disk",
        all(row["matches"] for row in audit["ledger_provenance"]),
        [row["matches"] for row in audit["ledger_provenance"]],
    )
    add(
        "A06",
        (
            "every ledger gross edge matches the explorer cell, or diverges only by an "
            "amount that changes neither the sign of the edge nor which side of the cost "
            "line the cell sits on"
        ),
        pop["gross_artifact_divergences_material"] == 0
        and all(
            not row["changes_sign"] and not row["changes_cost_side"]
            for row in audit["gross_divergences"]
        ),
        {
            "immaterial": pop["gross_artifact_divergences_immaterial"],
            "material": pop["gross_artifact_divergences_material"],
            "deltas_bps": [row["delta_bps"] for row in audit["gross_divergences"]],
        },
    )
    add(
        "A07",
        "every ledger gross edge matches its measurement artifact",
        pop["gross_mismatch_vs_measurement"] == 0,
        pop["gross_mismatch_vs_measurement"],
    )
    add(
        "A08",
        "7 cells have positive gross and 17 do not (sanity of the split)",
        pop["gross_positive"] == 7 and pop["gross_negative"] == 17,
        {"positive": pop["gross_positive"], "negative": pop["gross_negative"]},
    )
    add(
        "A09",
        "no cell clears the cheapest measured cost line",
        pop["clearing_cheapest_measured"] == 0,
        frontier["cells_clearing_measured"],
    )
    add(
        "A10",
        "no cell clears the cheapest assumed futures-maker line",
        pop["clearing_assumed_futures_maker"] == 0,
        frontier["cells_clearing_assumed_futures_maker"],
    )
    add(
        "A11",
        "the only line that would clear cells is an assumed, fill-unmodelled one",
        bool(audit["cost_plane"]["cheapest_any"]["rests_on_assumed_component"]),
        audit["cost_plane"]["cheapest_any"],
    )
    add(
        "A12",
        "18 of 24 ledger entries declare an unproven sample (provenance gap, not a data gap)",
        pop["ledger_sample_unproven"] == 18,
        pop["ledger_sample_unproven"],
    )
    add(
        "A13",
        "c6 (drawdown) and c8 (window dominance) are unmeasured in every 5m family",
        all(
            entry["unknown"] == ["c6_dd", "c8_no_window_dominance"]
            for entry in audit["family_criteria"].values()
        ),
        {f: e["unknown"] for f, e in audit["family_criteria"].items()},
    )
    add(
        "A14",
        "the verdict is ECONOMIC_BLOCKED because no strategy is admitted",
        audit["verdict"]["economic_status"] == "ECONOMIC_BLOCKED",
        audit["verdict"]["economic_status"],
    )
    for check in checks:
        check["observed"] = _json_safe(check["observed"])
    return checks


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def render_markdown(audit: dict[str, Any]) -> str:
    frontier = audit["frontier"]
    cost = audit["cost_plane"]
    pop = audit["population"]
    lines: list[str] = []
    lines.append("# WP-016A — auditoría de admisión de las 24 estrategias")
    lines.append("")
    lines.append(
        "> Generado por `scripts/tdm16_admission_audit.py` desde los artefactos commiteados. "
        "Cada número se recalcula aquí; nada se copia de un informe previo."
    )
    lines.append("")
    lines.append("## Respuesta")
    lines.append("")
    lines.append(
        f"**{pop['admitted']}/24 admitidas.** {pop['gross_positive']} celdas tienen gross "
        f"> 0 y {pop['gross_negative']} no. El techo de gross es "
        f"**{frontier['max_gross_bps']:.3f} bps/trade** (`{frontier['max_gross_cell']}`), "
        f"frente a una línea medida de **{frontier['cheapest_measured_rt_bps']:.3f} bps RT** "
        f"y una línea maker de futuros **asumida** de "
        f"**{frontier['assumed_futures_maker_rt_bps']:.3f} bps RT**."
    )
    lines.append("")
    lines.append(
        f"Distancias del mejor caso: **{frontier['distance_to_measured_bps']:+.3f} bps** "
        f"contra la línea medida y **{frontier['distance_to_assumed_futures_maker_bps']:+.3f} bps** "
        "contra la maker asumida. Ambas negativas ⇒ ningún slippage ni tasa de acierto "
        "salva una celda: la resta no cierra antes de ejecutar nada."
    )
    lines.append("")
    lines.append("## Líneas de coste")
    lines.append("")
    lines.append("| Línea | bps RT | Clase | Depende de componente asumido |")
    lines.append("| --- | ---: | --- | --- |")
    for key in ("cheapest_measured", "assumed_futures_maker", "cheapest_any"):
        row = cost[key]
        lines.append(
            f"| `{row['scenario_id']}` ({key}) | {row['round_trip_bps']:.3f} | "
            f"{row['knowledge_class']} | {'sí' if row['rests_on_assumed_component'] else 'no'} |"
        )
    lines.append("")
    lines.append("## Las 24 celdas")
    lines.append("")
    lines.append(
        "| Estrategia | Trades (explorer) | Gross bps | Estado | Causa del rechazo | "
        "Neto máximo vs línea medida | vs maker asumida |"
    )
    lines.append("| --- | ---: | ---: | --- | --- | ---: | ---: |")
    for row in sorted(audit["strategies"], key=lambda r: -r["gross_bps"]):
        lines.append(
            f"| `{row['strategy_id']}` | {row['explorer_trades'] or 0} | "
            f"{row['gross_bps']:+.3f} | {row['ledger_status']} | "
            f"{', '.join(row['rejection_causes'])} | "
            f"{row['net_upper_bound_measured_bps']:+.3f} | "
            f"{row['net_upper_bound_assumed_futures_maker_bps']:+.3f} |"
        )
    lines.append("")
    lines.append("## Criterios pre-registrados por familia (c1..c8)")
    lines.append("")
    lines.append("| Familia | c1 | c2 | c3 | c4 | c5 | c6 | c7 | c8 | Net BASE | PF BASE | PF 2X | OOS net |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
    for family, entry in audit["family_criteria"].items():
        checks = entry["checks"]
        cells = " | ".join(
            "—" if checks.get(k) is None else ("sí" if checks.get(k) else "no")
            for k in (
                "c1_sample",
                "c2_net_positive",
                "c3_pf_gt1",
                "c4_oos_positive",
                "c5_dev_consistent",
                "c6_dd",
                "c7_survives_2x",
                "c8_no_window_dominance",
            )
        )
        lines.append(
            f"| `{family}` | {cells} | {entry['net_base']} | {entry['pf_base']} | "
            f"{entry['pf_2x']} | {entry['oos_net']} |"
        )
    lines.append("")
    lines.append("## Checks de la propia auditoría")
    lines.append("")
    lines.append(
        f"{audit['checks_total'] - audit['checks_failed']}/{audit['checks_total']} "
        "verdes. Los fallos aparecen como fallos, no se filtran."
    )
    for check in audit["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- **{mark}** `{check['id']}` — {check['description']}")
    lines.append("")
    lines.append("## Veredicto")
    lines.append("")
    lines.append(f"- `economic_status`: **{audit['verdict']['economic_status']}**")
    lines.append(f"- admitidas: {audit['verdict']['admitted_ids'] or 'ninguna'}")
    lines.append(f"- razón decisiva: {audit['verdict']['decisive_reason']}.")
    lines.append(f"- qué cambiaría el veredicto: {audit['verdict']['what_changes_the_verdict']}.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.json",
        help="JSON audit path",
    )
    parser.add_argument(
        "--markdown",
        default="evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.md",
        help="Markdown audit path",
    )
    args = parser.parse_args(argv)

    audit = build_audit()
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    md = REPO_ROOT / args.markdown
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_markdown(audit) + "\n", encoding="utf-8", newline="\n")

    print(f"wrote {args.out} ({audit['population']['strategies']} strategies)")
    print(
        f"admitted={audit['population']['admitted']} "
        f"checks={audit['checks_total'] - audit['checks_failed']}/{audit['checks_total']} "
        f"verdict={audit['verdict']['economic_status']}"
    )
    return 0 if audit["checks_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
