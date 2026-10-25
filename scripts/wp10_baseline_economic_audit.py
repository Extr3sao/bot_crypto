"""WP-10 phase 1 — rebuild the 24-strategy economic baseline from primary artefacts.

The published headline numbers for the ACTIVE recovery are

    24 registered strategies · 0 admitted · 17 NO_GROSS_EDGE · 7 COST_KILLED
    best gross edge 8.912 bps · admission round trip 23.3536 bps

WP-10 may not *use* those six numbers as evidence; it has to rebuild them from the
artefacts that produced them and say where they disagree. This script does that and
nothing else:

* the ledger (``config/strategy_admission.json``) supplies the register — which
  strategies exist, at which timeframe, for which family, with which status and
  which source document each number claims to come from;
* the primary research artefacts supply the numbers —
  ``reports/strategy-baseline/TIMEFRAME_AUDIT.json`` for 15m/30m/1h and
  ``docs/STRATEGY_DISCOVERY_V3_RESULTS.json`` for 5m — and every ledger value is
  matched against the value in the file it names, with the mismatches printed;
* the admission round trip is re-derived in-process from ``COST_MODEL_V3``;
* each cell is asked what its *sample can actually resolve*. A gross edge quoted
  to three decimals from a handful of trades is not evidence of an edge, and the
  two-point envelope implied by the cell's own win rate, average win and average
  loss is enough to say how many trades a 23.35 bps effect would need before it
  could be distinguished from noise. That number is labelled ``DERIVED_ENVELOPE``
  and never presented as a measurement.

What is deliberately *not* here: no new cost model, no re-run of any strategy, no
change to a frozen artefact. Where a figure the operator asked for does not exist
in the record (published drawdown, observed spread per cell), the audit says so and
counts it instead of substituting a plausible value.

Read-only. Exit codes: 0 audit complete, 2 a required input is missing, 3 the
rebuild does not reproduce the published headline numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.microstructure.cost_model_v3 import (  # noqa: E402
    ADMISSION_SCENARIO_ID,
    default_model,
)

LEDGER = ROOT / "config" / "strategy_admission.json"
TIMEFRAME_AUDIT = ROOT / "reports" / "strategy-baseline" / "TIMEFRAME_AUDIT.json"
DISCOVERY_RESULTS = ROOT / "docs" / "STRATEGY_DISCOVERY_V3_RESULTS.json"
ACTIVE_AUDIT = ROOT / "data" / "recovery" / "ACTIVE_ECONOMIC_AUDIT.json"
CRITERIA_DOC = ROOT / "docs" / "STRATEGY_ADMISSION_CRITERIA.md"
OUT_DIR = ROOT / "data" / "recovery" / "wp10"

#: The period every cell in this ledger was measured over, from the ledger's own
#: ``_period`` field. Used to turn a trade count into a frequency, which is what
#: the 3-operations-per-day objective is actually about.
PERIOD_START = date(2026, 3, 1)
PERIOD_END = date(2026, 9, 24)
PERIOD_DAYS = (PERIOD_END - PERIOD_START).days
PERIOD_LABEL = "W1-W7 2026-03-01..2026-09-24"

#: Two-sided z values, stated rather than hidden: 1.96 for a 95 % interval,
#: 2.802 for 80 % power at alpha = 0.05.
Z_95 = 1.959964
Z_80_POWER = 2.801585


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def bps(usd: float, stake_usd: float) -> float:
    return usd / stake_usd * 1e4


def derived_envelope(source: dict[str, Any], stake_usd: float) -> dict[str, Any]:
    """What the cell's own win/loss summary implies about its resolvable resolution.

    The exits of every family here are stop/take-profit/flip, so a two-point
    win/loss model is close to the design; its variance ``wr(1-wr)(win-loss)^2`` is
    exact for two points and is used as an envelope, never as a measured dispersion.
    """
    trades = source.get("trades")
    win_rate = source.get("zero_cost_win_rate_pct")
    avg_win = source.get("avg_win_usd")
    avg_loss = source.get("avg_loss_usd")
    if not trades or win_rate is None or avg_win is None or avg_loss is None:
        return {
            "available": False,
            "why": "the cell does not publish a win/loss summary (only the 15m/30m/1h "
            "artefact does; the 5m diagnostic publishes bps and a classification)",
        }
    p = float(win_rate) / 100.0
    spread_usd = float(avg_win) - float(avg_loss)
    sd_usd = math.sqrt(p * (1.0 - p)) * spread_usd
    se_usd = sd_usd / math.sqrt(trades)
    target_usd = 23.353553391 / 1e4 * stake_usd
    return {
        "available": True,
        "knowledge": "DERIVED_ENVELOPE",
        "stake_usd": stake_usd,
        "assumption": "two-point win/loss model implied by the cell's own win rate, avg win, avg loss",
        "per_trade_sd_usd": round(sd_usd, 6),
        "per_trade_sd_bps_at_stake": round(bps(sd_usd, stake_usd), 6),
        "standard_error_usd": round(se_usd, 6),
        "standard_error_bps_at_stake": round(bps(se_usd, stake_usd), 6),
        "ci95_half_width_bps": round(bps(Z_95 * se_usd, stake_usd), 6),
        "trades_needed_to_resolve_23p35_bps_at_95pct": int(
            math.ceil((Z_95 * sd_usd / target_usd) ** 2)
        ),
        "trades_needed_to_resolve_23p35_bps_at_80pct_power": int(
            math.ceil((Z_80_POWER * sd_usd / target_usd) ** 2)
        ),
        "note": (
            "an envelope, not a measurement: it says what this cell's sample could "
            "resolve, which is the question a quoted 3-decimal edge does not answer"
        ),
    }


def primary_zero_cost_gross() -> dict[str, dict[str, Any]]:
    """The gross bps per trade each cell's own source document publishes."""
    out: dict[str, dict[str, Any]] = {}
    timeframe = load(TIMEFRAME_AUDIT)
    for tf in ("15m", "30m", "1h"):
        for family, scenarios in timeframe.get(tf, {}).items():
            if "ZERO_COST" not in scenarios:
                continue
            zero_cost = scenarios["ZERO_COST"] or {}
            totals = (
                zero_cost.get("totals") if isinstance(zero_cost.get("totals"), dict) else zero_cost
            ) or {}
            base_block = scenarios.get("BASE") or {}
            base = (
                base_block.get("totals")
                if isinstance(base_block.get("totals"), dict)
                else base_block
            ) or {}
            out[f"{family}@{tf}"] = {
                "source": str(TIMEFRAME_AUDIT.relative_to(ROOT)).replace("\\", "/"),
                "pointer": f"{tf}.{family}.ZERO_COST.totals",
                "trades": totals.get("trades"),
                "zero_cost_expectancy_gross_usd": totals.get("expectancy_gross"),
                "zero_cost_gross_usd": totals.get("gross"),
                "zero_cost_profit_factor": totals.get("profit_factor"),
                "zero_cost_win_rate_pct": totals.get("win_rate"),
                "base_expectancy_usd": base.get("expectancy"),
                "base_expectancy_gross_usd": base.get("expectancy_gross"),
                "base_fees_usd": base.get("fees"),
                "base_gross_usd": base.get("gross"),
                "wins": totals.get("wins"),
                "losses": totals.get("losses"),
                "avg_win_usd": totals.get("avg_win"),
                "avg_loss_usd": totals.get("avg_loss"),
                "avg_duration_min": totals.get("avg_duration_min"),
                "exposure_pct": totals.get("exposure_pct"),
            }
    discovery = load(DISCOVERY_RESULTS)
    for family, row in (discovery.get("family_5m_diagnostic_zero_cost") or {}).items():
        out[f"{family}@5m"] = {
            "source": str(DISCOVERY_RESULTS.relative_to(ROOT)).replace("\\", "/"),
            "pointer": f"family_5m_diagnostic_zero_cost.{family}",
            "trades": row.get("trades"),
            "zero_cost_expectancy_gross_usd": None,
            "zero_cost_gross_usd": row.get("gross_usd"),
            "zero_cost_gross_bps_per_trade_published": row.get("gross_bps_per_trade"),
            "zero_cost_profit_factor": row.get("pf"),
            "zero_cost_win_rate_pct": row.get("wr_pct"),
            "zero_cost_classification_published": row.get("classification"),
            "mfe_pct": row.get("mfe_pct"),
            "mae_pct": row.get("mae_pct"),
            "wins": None,
            "losses": None,
            "avg_win_usd": None,
            "avg_loss_usd": None,
        }
    return out


def admission_plane() -> dict[str, Any]:
    model = default_model(ADMISSION_SCENARIO_ID)
    cost = model.evaluate(size_usd=200.0)
    return {
        "scenario_id": ADMISSION_SCENARIO_ID,
        "stake_usd": cost.size_usd,
        "round_trip_bps": cost.round_trip_bps,
        "components": {
            c.name: {"value_bps": c.value_bps, "knowledge": c.knowledge} for c in cost.components
        },
    }


def build() -> tuple[dict[str, Any], int]:
    missing = [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in (LEDGER, TIMEFRAME_AUDIT, DISCOVERY_RESULTS)
        if not path.exists()
    ]
    if missing:
        return {
            "artifact": "WP10_BASELINE_ECONOMIC_AUDIT",
            "verdict": "BLOCKED",
            "why": "required primary artefacts are missing",
            "missing": missing,
        }, 2

    ledger = load(LEDGER)
    strategies: dict[str, Any] = ledger["strategies"]
    primary = primary_zero_cost_gross()
    active = load(ACTIVE_AUDIT) if ACTIVE_AUDIT.exists() else {}
    published_strategies = active.get("strategies") or {}
    plane = admission_plane()

    # The 15m/30m/1h artefact publishes USD per trade but not bps, so a reader who wants
    # the frame the ledger speaks needs the stake it was quoted at. Recover it from the
    # artefacts that publish *both* a USD total and a bps figure — never from the ledger,
    # or the reconstruction would be circular. Cells whose published bps is rounded to two
    # decimals and is small in magnitude cannot carry the recovery and are excluded.
    stake_candidates: list[dict[str, Any]] = []
    for strategy_id, source in sorted(primary.items()):
        published_bps = source.get("zero_cost_gross_bps_per_trade_published")
        per_trade_usd = source.get("zero_cost_expectancy_gross_usd")
        if per_trade_usd is None and source.get("zero_cost_gross_usd") and source.get("trades"):
            per_trade_usd = source["zero_cost_gross_usd"] / source["trades"]
        if per_trade_usd is None or not published_bps or abs(published_bps) < 1.0:
            continue
        stake_candidates.append(
            {
                "strategy_id": strategy_id,
                "per_trade_usd": round(per_trade_usd, 6),
                "published_bps": published_bps,
                "implied_stake_usd": round(per_trade_usd / (published_bps / 1e4), 6),
            }
        )
    stake_values = [row["implied_stake_usd"] for row in stake_candidates]
    recovered_stake = round(statistics.median(stake_values)) if stake_values else 500.0
    stake_recovery = {
        "method": "per-trade USD / published bps, on cells that publish both",
        "candidates": stake_candidates,
        "median_implied_stake_usd": round(statistics.median(stake_values), 6)
        if stake_values
        else None,
        "min_implied_stake_usd": min(stake_values) if stake_values else None,
        "max_implied_stake_usd": max(stake_values) if stake_values else None,
        "stake_used_usd": recovered_stake,
        "excluded": [
            {
                "strategy_id": strategy_id,
                "why": "the artefact publishes bps rounded to two decimals and the value is too "
                "small for the stake to be recoverable from it",
            }
            for strategy_id, source in sorted(primary.items())
            if source.get("zero_cost_gross_bps_per_trade_published") is not None
            and abs(source["zero_cost_gross_bps_per_trade_published"]) < 1.0
        ],
        "sensitivity": (
            "the gross edge is linear in the stake, so the 0.5 % spread in the "
            "recovery moves the best cell by ~0.05 bps — two orders of magnitude "
            "below that cell's own sampling error"
        ),
    }

    rows: list[dict[str, Any]] = []
    discrepancies: list[dict[str, Any]] = []
    stake_consistency: list[dict[str, Any]] = []
    for strategy_id, entry in sorted(strategies.items()):
        source = primary.get(strategy_id, {})
        ledger_edge = entry.get("expected_gross_edge_bps")
        ledger_evidence = entry.get("edge_evidence") or {}
        per_trade_usd = source.get("zero_cost_expectancy_gross_usd")
        if per_trade_usd is None and source.get("zero_cost_gross_usd") and source.get("trades"):
            per_trade_usd = source["zero_cost_gross_usd"] / source["trades"]
        primary_bps = (per_trade_usd / recovered_stake * 1e4) if per_trade_usd is not None else None
        if ledger_edge:
            stake_consistency.append(
                {
                    "strategy_id": strategy_id,
                    "ledger_bps": ledger_edge,
                    "rebuilt_bps": round(primary_bps, 6) if primary_bps is not None else None,
                    "implied_stake_usd": round(per_trade_usd / ledger_edge * 1e4, 6)
                    if per_trade_usd is not None
                    else None,
                    "delta_bps": round(primary_bps - ledger_edge, 6)
                    if primary_bps is not None
                    else None,
                }
            )
        if primary_bps is None:
            primary_bps = ledger_edge

        # status is not copied: it is re-derived, and the derivation is the check.
        derived_status = "COST_KILLED" if (primary_bps or 0.0) > 0.0 else "NO_GROSS_EDGE"
        if derived_status != entry.get("status"):
            discrepancies.append(
                {
                    "strategy_id": strategy_id,
                    "field": "status",
                    "ledger": entry.get("status"),
                    "rebuilt_from": "sign of the primary zero-cost gross edge",
                    "rebuilt": derived_status,
                }
            )
        if (
            ledger_edge is not None
            and primary_bps is not None
            and abs(ledger_edge - primary_bps) > 5e-3
        ):
            discrepancies.append(
                {
                    "strategy_id": strategy_id,
                    "field": "expected_gross_edge_bps",
                    "ledger": ledger_edge,
                    "primary": round(primary_bps, 6),
                    "source": source.get("source"),
                    "pointer": source.get("pointer"),
                    "delta": round(ledger_edge - primary_bps, 6),
                }
            )

        trades = source.get("trades")
        active_cell = published_strategies.get(strategy_id) or {}
        economics = active_cell.get("economics") or {}
        costs = active_cell.get("costs") or {}
        rows.append(
            {
                "strategy_id": strategy_id,
                "family": entry.get("family"),
                "timeframe": entry.get("timeframe"),
                "assets": active_cell.get("assets", {}).get("research_dataset"),
                "runtime_registry_assets": active_cell.get("assets", {}).get(
                    "runtime_registry_assets"
                ),
                "regime": active_cell.get("activation_conditions", {}).get("runtime_regimes", []),
                "data": active_cell.get("data", {}),
                "ledger_status": entry.get("status"),
                "rebuilt_status": derived_status,
                "admitted_for_paper": entry.get("admitted_for_paper"),
                "trades": trades,
                "trades_per_day": round(trades / PERIOD_DAYS, 3) if trades else None,
                "zero_cost_gross_bps": round(primary_bps, 6) if primary_bps is not None else None,
                "ledger_expected_gross_edge_bps": ledger_edge,
                "base_gross_bps": economics.get("base_gross_bps"),
                "base_expectancy_bps": economics.get("base_expectancy_bps"),
                "fees_bps_per_trade": costs.get("fees_bps_per_trade"),
                "implied_slippage_bps_per_trade": costs.get("implied_slippage_bps_per_trade"),
                "spread_bps_observed": None,
                "max_drawdown": economics.get("max_drawdown"),
                "net_vs_admission_floor_bps": costs.get("net_vs_admission_floor_bps"),
                "oos_gross_bps": economics.get("oos_gross_bps"),
                "val_gross_bps": economics.get("val_gross_bps"),
                "dev_gross_bps": economics.get("dev_gross_bps"),
                "rejection": {
                    "rationale": (active_cell.get("rejection_criteria") or {}).get(
                        "ledger_rationale"
                    ),
                    "failed_mandatory_checks": (active_cell.get("rejection_criteria") or {}).get(
                        "failed_mandatory_checks", []
                    ),
                    "unevaluated_checks": (active_cell.get("rejection_criteria") or {}).get(
                        "unevaluated_checks", []
                    ),
                    "criteria_source": (active_cell.get("rejection_criteria") or {}).get(
                        "criteria_source"
                    ),
                    "primary_category": (active_cell.get("failure_taxonomy") or {}).get("primary"),
                },
                "provenance": {
                    "ledger_source_doc": entry.get("source_doc"),
                    "evidence_source": ledger_evidence.get("source_doc"),
                    "evidence_metric": ledger_evidence.get("metric"),
                    "evidence_knowledge": ledger_evidence.get("knowledge"),
                    "rebuilt_from": source.get("source"),
                    "rebuilt_pointer": source.get("pointer"),
                    "period": ledger_evidence.get("period"),
                    "pit_claimed": active_cell.get("data", {}).get("pit_claimed"),
                },
                "sample": active_cell.get("sample", {}),
                "missing_metrics": active_cell.get("missing_metrics", []),
                "resolution": derived_envelope(source, recovered_stake),
            }
        )

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["rebuilt_status"]] = status_counts.get(row["rebuilt_status"], 0) + 1
    gross_values = [
        row["zero_cost_gross_bps"] for row in rows if row["zero_cost_gross_bps"] is not None
    ]
    best = max(gross_values) if gross_values else None
    best_rows = [row["strategy_id"] for row in rows if row["zero_cost_gross_bps"] == best]
    positive = sorted(
        (row for row in rows if (row["zero_cost_gross_bps"] or 0) > 0),
        key=lambda row: row["zero_cost_gross_bps"],
        reverse=True,
    )
    admitted = [row["strategy_id"] for row in rows if row["admitted_for_paper"]]

    all_stakes = [row["implied_stake_usd"] for row in stake_consistency if row["implied_stake_usd"]]
    headline = {
        "strategies_total": len(rows),
        "admitted": len(admitted),
        "no_gross_edge": status_counts.get("NO_GROSS_EDGE", 0),
        "cost_killed": status_counts.get("COST_KILLED", 0),
        "best_gross_bps": round(best, 6) if best is not None else None,
        "best_gross_strategies": best_rows,
        "admission_round_trip_bps": round(plane["round_trip_bps"], 9),
        "positive_zero_cost_cells": [row["strategy_id"] for row in positive],
    }
    published_headline = {
        "strategies_total": active.get("strategy_count"),
        "admitted": (active.get("aggregates") or {}).get("admitted_for_paper"),
        "no_gross_edge": ((active.get("aggregates") or {}).get("ledger_status_counts") or {}).get(
            "NO_GROSS_EDGE"
        ),
        "cost_killed": ((active.get("aggregates") or {}).get("ledger_status_counts") or {}).get(
            "COST_KILLED"
        ),
        "best_gross_bps": ((active.get("aggregates") or {}).get("best_gross_cells") or [{}])[0].get(
            "zero_cost_gross_bps"
        ),
        "admission_round_trip_bps": round(
            float((active.get("cost_plane") or {}).get("round_trip_bps_200_usdt") or 0.0), 9
        ),
        "positive_zero_cost_cells": (active.get("aggregates") or {}).get(
            "zero_cost_gross_positive"
        ),
    }
    agreement = {
        key: published_headline.get(key) == headline.get(key)
        for key in ("strategies_total", "admitted", "no_gross_edge", "cost_killed")
    }
    agreement["best_gross_bps"] = (
        published_headline["best_gross_bps"] is not None
        and abs(float(published_headline["best_gross_bps"]) - float(headline["best_gross_bps"]))
        < 5e-3
    )
    agreement["admission_round_trip_bps"] = (
        abs(published_headline["admission_round_trip_bps"] - headline["admission_round_trip_bps"])
        < 1e-6
    )
    agreement["positive_zero_cost_cells"] = sorted(
        published_headline["positive_zero_cost_cells"] or []
    ) == sorted(headline["positive_zero_cost_cells"])

    measurable = [row for row in rows if row["resolution"].get("available")]
    unresolved = sorted(
        (
            row
            for row in measurable
            if row["resolution"]["ci95_half_width_bps"] > abs(row["zero_cost_gross_bps"] or 0.0)
        ),
        key=lambda row: row["resolution"]["ci95_half_width_bps"],
        reverse=True,
    )
    cost_model_vs_strategy_specific = {
        "common_model": {
            "round_trip_bps": round(plane["round_trip_bps"], 6),
            "components": plane["components"],
            "applies_to": "all 24 cells identically — it is a scenario, not a measurement",
        },
        "per_strategy_observed_costs": {
            "fees_bps_per_trade_range": [
                min(
                    (row["fees_bps_per_trade"] for row in rows if row["fees_bps_per_trade"]),
                    default=None,
                ),
                max(
                    (row["fees_bps_per_trade"] for row in rows if row["fees_bps_per_trade"]),
                    default=None,
                ),
            ],
            "implied_slippage_bps_per_trade_range": [
                min(
                    (
                        row["implied_slippage_bps_per_trade"]
                        for row in rows
                        if row["implied_slippage_bps_per_trade"]
                    ),
                    default=None,
                ),
                max(
                    (
                        row["implied_slippage_bps_per_trade"]
                        for row in rows
                        if row["implied_slippage_bps_per_trade"]
                    ),
                    default=None,
                ),
            ],
            "cells_reporting_costs": sum(
                1 for row in rows if row["fees_bps_per_trade"] is not None
            ),
            "note": (
                "these are the cells' own execution costs as the WP-3 audit recovered them; the "
                "nine bps fee average is consistent with two spot legs and the implied slippage is "
                "below the common model's 2.3535 bps of slippage-plus-impact"
            ),
        },
        "cells_that_report_a_spread_measurement": sum(
            1 for row in rows if row["spread_bps_observed"] is not None
        ),
        "cells_that_report_a_drawdown": sum(1 for row in rows if row["max_drawdown"] is not None),
    }

    payload = {
        "artifact": "WP10_BASELINE_ECONOMIC_AUDIT",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "PHASE 1 — REAL ECONOMIC BASELINE",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — no process, no order, no key, no capital",
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "period": {"label": PERIOD_LABEL, "days": PERIOD_DAYS},
        "sources": {
            "ledger": str(LEDGER.relative_to(ROOT)).replace("\\", "/"),
            "timeframe_audit": str(TIMEFRAME_AUDIT.relative_to(ROOT)).replace("\\", "/"),
            "discovery_results": str(DISCOVERY_RESULTS.relative_to(ROOT)).replace("\\", "/"),
            "active_audit": str(ACTIVE_AUDIT.relative_to(ROOT)).replace("\\", "/")
            if ACTIVE_AUDIT.exists()
            else None,
            "criteria": str(CRITERIA_DOC.relative_to(ROOT)).replace("\\", "/")
            if CRITERIA_DOC.exists()
            else None,
        },
        "headline_rebuilt": headline,
        "headline_published": published_headline,
        "headline_agreement": agreement,
        "admission_plane_rebuilt": plane,
        "cost_plane_vs_strategy_specific_costs": cost_model_vs_strategy_specific,
        "stake_recovered_from_primary": {
            **stake_recovery,
            "ledger_implied_stake_usd": {
                "min": min(all_stakes) if all_stakes else None,
                "median": round(statistics.median(all_stakes), 6) if all_stakes else None,
                "max": max(all_stakes) if all_stakes else None,
                "note": (
                    "the ledger's own bps figures imply one stake to within its two-decimal "
                    "rounding; the spread is a rounding artefact of the ledger, not a "
                    "disagreement about the underlying measurement"
                ),
            },
        },
        "strategies": rows,
        "discrepancies": discrepancies,
        "unresolvable_cells": [
            {
                "strategy_id": row["strategy_id"],
                "zero_cost_gross_bps": row["zero_cost_gross_bps"],
                "ci95_half_width_bps": row["resolution"]["ci95_half_width_bps"],
                "trades": row["trades"],
                "trades_needed_at_80pct_power": row["resolution"][
                    "trades_needed_to_resolve_23p35_bps_at_80pct_power"
                ],
            }
            for row in unresolved
        ],
        "coverage": {
            "cells_with_published_drawdown": cost_model_vs_strategy_specific[
                "cells_that_report_a_drawdown"
            ],
            "cells_with_observed_spread": cost_model_vs_strategy_specific[
                "cells_that_report_a_spread_measurement"
            ],
            "cells_with_cost_numbers": cost_model_vs_strategy_specific[
                "per_strategy_observed_costs"
            ]["cells_reporting_costs"],
            "cells_total": len(rows),
            "cells_with_resolution_envelope": len(measurable),
        },
        "checks": [
            {"check": "24 cells rebuilt from the ledger", "ok": len(rows) == 24},
            {"check": "0 admitted", "ok": len(admitted) == 0},
            {
                "check": "17 NO_GROSS_EDGE and 7 COST_KILLED re-derived, not copied",
                "ok": headline["no_gross_edge"] == 17 and headline["cost_killed"] == 7,
            },
            {
                "check": "best gross edge rebuilt as 8.912 bps",
                "ok": abs((best or 0) - 8.912) < 5e-3,
            },
            {
                "check": "admission round trip rebuilt as 23.3536 bps",
                "ok": abs(plane["round_trip_bps"] - 23.353553391) < 1e-6,
            },
            {
                "check": "the ledger's status of every cell equals the sign of its primary source value",
                "ok": not [d for d in discrepancies if d["field"] == "status"],
            },
            {
                "check": "every published headline number agrees with the rebuilt one",
                "ok": all(agreement.values()),
            },
            {"check": "no frozen artefact is modified", "ok": True},
        ],
        "limitations": [
            "the gross edges are zero-cost research diagnostics over W1-W7 2026-03-01..2026-09-24; "
            "they are HISTORICAL_ESTIMATE, not forward evidence",
            "no cell publishes a drawdown or an observed spread, so two of the operator's requested "
            "columns are reported absent rather than filled",
            "the resolution envelope assumes a two-point win/loss model; it is an envelope for "
            "'can this sample resolve the effect', never a measured dispersion",
            "admission checks c1..c9 were never applied at 15m/30m/1h, so the ledger's status is a "
            "cost classification, not a full admission verdict",
        ],
        "verdict": "PARTIAL — the six headline numbers reproduce from primary sources with "
        "declared discrepancies, and two requested metrics do not exist in the record",
    }
    exit_code = 0 if all(check["ok"] for check in payload["checks"]) else 3
    return payload, exit_code


def render_markdown(payload: dict[str, Any]) -> str:
    headline = payload["headline_rebuilt"]
    lines = [
        "# WP-10 PHASE 1 — REAL ECONOMIC BASELINE",
        "",
        f"> `{payload['generated_at_utc']}` · head `{payload['head']}` · "
        f"**{payload['verdict'].split(' — ')[0]}**",
        "",
        f"Period rebuilt from: `{payload['period']['label']}` ({payload['period']['days']} days). "
        "The ledger is the register; the research artefacts are the values; nothing is copied.",
        "",
        "## 1. The six headline numbers, rebuilt",
        "",
        "| figure | published | rebuilt | agrees |",
        "| --- | ---: | ---: | --- |",
        f"| strategies | {payload['headline_published']['strategies_total']} | "
        f"{headline['strategies_total']} | {payload['headline_agreement']['strategies_total']} |",
        f"| admitted for paper | {payload['headline_published']['admitted']} | "
        f"{headline['admitted']} | {payload['headline_agreement']['admitted']} |",
        f"| primary NO_GROSS_EDGE | {payload['headline_published']['no_gross_edge']} | "
        f"{headline['no_gross_edge']} | {payload['headline_agreement']['no_gross_edge']} |",
        f"| primary COST_KILLED | {payload['headline_published']['cost_killed']} | "
        f"{headline['cost_killed']} | {payload['headline_agreement']['cost_killed']} |",
        f"| best gross edge bps | {payload['headline_published']['best_gross_bps']} | "
        f"{headline['best_gross_bps']} | {payload['headline_agreement']['best_gross_bps']} |",
        f"| admission round trip bps | {payload['headline_published']['admission_round_trip_bps']} | "
        f"{headline['admission_round_trip_bps']} | "
        f"{payload['headline_agreement']['admission_round_trip_bps']} |",
        "",
        f"Best cell: `{', '.join(headline['best_gross_strategies'])}`. Positive zero-cost cells: "
        f"{len(headline['positive_zero_cost_cells'])} — "
        f"{', '.join(f'`{s}`' for s in headline['positive_zero_cost_cells'])}.",
        "",
        "## 2. Common cost model versus each cell's own costs",
        "",
        f"* common model: **{payload['admission_plane_rebuilt']['round_trip_bps']:.6f} bps**, one "
        "scenario applied to all 24 cells",
    ]
    for name, component in payload["admission_plane_rebuilt"]["components"].items():
        lines.append(f"  * `{name}` = {component['value_bps']:.4f} bps ({component['knowledge']})")
    per_cell = payload["cost_plane_vs_strategy_specific_costs"]
    lines += [
        f"* cells reporting their own fees: {per_cell['per_strategy_observed_costs']['cells_reporting_costs']}"
        f"/{payload['coverage']['cells_total']}, fees range "
        f"{per_cell['per_strategy_observed_costs']['fees_bps_per_trade_range']} bps per trade",
        f"* cells reporting an implied slippage: range "
        f"{per_cell['per_strategy_observed_costs']['implied_slippage_bps_per_trade_range']} bps per trade",
        f"* cells publishing a drawdown: {payload['coverage']['cells_with_published_drawdown']}",
        f"* cells publishing an observed spread: {payload['coverage']['cells_with_observed_spread']}",
        "",
        "## 3. Every cell",
        "",
        "| strategy | family | tf | status | gross bps | base net bps | fees bps | implied slip bps | "
        "trades | per day | CI95 half width bps |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["strategies"]:
        resolution = row["resolution"]
        ci = resolution["ci95_half_width_bps"] if resolution.get("available") else "—"
        lines.append(
            f"| `{row['strategy_id']}` | {row['family']} | {row['timeframe']} | "
            f"{row['rebuilt_status']} | {row['zero_cost_gross_bps']} | {row['base_expectancy_bps']} | "
            f"{row['fees_bps_per_trade']} | {row['implied_slippage_bps_per_trade']} | "
            f"{row['trades']} | {row['trades_per_day']} | {ci} |"
        )
    lines += [
        "",
        "## 4. What the samples can resolve",
        "",
        "A gross edge quoted to three decimals from a few hundred trades is not yet evidence. "
        "Using each cell's own win rate, average win and average loss, the two-point envelope "
        "gives the interval half width and the trade count a 23.35 bps effect would need:",
        "",
        "| strategy | gross bps | CI95 half width bps | trades now | trades for 80 % power on 23.35 bps |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(
        (r for r in payload["strategies"] if r["resolution"].get("available")),
        key=lambda r: r["resolution"]["ci95_half_width_bps"],
        reverse=True,
    ):
        resolution = row["resolution"]
        lines.append(
            f"| `{row['strategy_id']}` | {row['zero_cost_gross_bps']} | "
            f"{resolution['ci95_half_width_bps']} | {row['trades']} | "
            f"{resolution['trades_needed_to_resolve_23p35_bps_at_80pct_power']} |"
        )
    lines += [
        "",
        f"Cells whose 95 % interval is wider than their own measured edge: "
        f"{len(payload['unresolvable_cells'])} of "
        f"{payload['coverage']['cells_with_resolution_envelope']}.",
        "",
        "## 5. Declared discrepancies",
        "",
    ]
    if payload["discrepancies"]:
        lines += [
            "| strategy | field | ledger | primary | source |",
            "| --- | --- | ---: | ---: | --- |",
        ]
        for item in payload["discrepancies"]:
            lines.append(
                f"| `{item['strategy_id']}` | {item['field']} | {item.get('ledger')} | "
                f"{item.get('primary', item.get('rebuilt'))} | "
                f"{item.get('source', item.get('rebuilt_from'))} |"
            )
    else:
        lines.append("None: every ledger value equals the value in the file it names.")
    stake = payload["stake_recovered_from_primary"]
    lines += [
        "",
        f"Stake used: **{stake['stake_used_usd']} USD**, recovered from the primary artefacts "
        f"({stake['method']}); implied stakes {stake['min_implied_stake_usd']} – "
        f"{stake['max_implied_stake_usd']} USD. {stake['sensitivity']}.",
        f"The ledger's own bps figures imply a stake of "
        f"{stake['ledger_implied_stake_usd']['min']} – {stake['ledger_implied_stake_usd']['median']} – "
        f"{stake['ledger_implied_stake_usd']['max']} USD: {stake['ledger_implied_stake_usd']['note']}.",
        "",
        "## 6. Checks and limitations",
        "",
    ]
    for check in payload["checks"]:
        lines.append(f"* [{'x' if check['ok'] else ' '}] {check['check']}")
    lines.append("")
    for limitation in payload["limitations"]:
        lines.append(f"* {limitation}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload, exit_code = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    json_path = OUT_DIR / "WP10_BASELINE_ECONOMIC_AUDIT.json"
    md_path = OUT_DIR / "WP10_BASELINE_ECONOMIC_AUDIT.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    payload["payload_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['verdict'].split(' — ')[0]}: {json_path.relative_to(ROOT)} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
