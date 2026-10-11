"""COST-BARRIER EXPLORER - per venue and per horizon, which ACTIVE cells are reachable.

WP-6 of the POST RFC-049 / ACTIVE RECOVERY lane. The AUDIT (WP-3) established
that no registered ``family@timeframe`` cell is net-positive. This artefact turns
that verdict into a *map*: for every execution configuration the repository's own
cost model can express, and for every horizon the evidence supports, which cells
sit above the round-trip cost line and which do not.

Definitions (fixed in this module, applied mechanically):

* **cell** - one of the 24 registered ``family@timeframe`` entries. Its structural
  edge is ``zero_cost_gross_bps`` as published by
  ``data/recovery/ACTIVE_ECONOMIC_AUDIT.json``. That is the only edge measure in
  the repository that is independent of the cost plane, so it is the correct
  left-hand side of a barrier comparison. Nothing here re-measures edge.
* **configuration** - ``(scenario_id, execution mode, size_usd, liquidity_regime)``
  over the 9 venue scenarios of COST_MODEL_V3. ``required_bps`` is the model's
  all-in round trip multiplied by the stress multiple.
* **reachable** - ``zero_cost_gross_bps > required_bps``, strict. Equality is not
  reachability; a strategy that exactly pays its costs has zero edge.
* **horizon** - three measured sub-axes, because the model has no single horizon
  parameter that means "holding time":
  1. *model horizon*: ``horizon_minutes`` in COST_MODEL_V3, which is a funding
     accrual term and nothing else;
  2. *funding horizon*: how long a perpetual may be held before funding carry
     consumes a given edge;
  3. *market horizon*: the median bars/hours the market itself needs to move the
     cost line, per timeframe and asset (``reports/strategy-baseline/COST_BARRIER.json``).
     This is the repo's pre-existing definition of a cost horizon; it is reused,
     not redefined.
* **evidence class** - a barrier is ``observed`` when its line uses no ASSUMED
  component, and ``assumed`` when it needs the maker fill/adverse-selection model.
  Reachability resting on an ASSUMED line is reported as such and never mixed into
  the observed-only count.

Read-only: writes only ``data/recovery/COST_BARRIER_EXPLORER.{json,md}`` (or the
directory given by ``--out-dir``, which exists so a governor or a drift gate can
reproduce the artefact without touching the published files); starts no process,
touches no runtime state, opens no network path and claims no promotion.
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
OUT = ROOT / "data" / "recovery"

# --------------------------------------------------------------------------- #
# sources (the provenance chain; every one is hashed into the artefact)
# --------------------------------------------------------------------------- #

AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
COST_BARRIER = "reports/strategy-baseline/COST_BARRIER.json"
LEDGER = "config/strategy_admission.json"
COST_V3 = "docs/COST_MODEL_V3.json"
COST_MODEL_MODULE = "src/trading_bot/research/microstructure/cost_model_v3.py"

SOURCE_ROLES = {
    AUDIT: "ACTIVE economic audit (WP-3): the 24 cells and their zero-cost gross edge",
    COST_BARRIER: "transaction-cost barrier: median bars/hours for a move equal to the cost",
    LEDGER: "tracked admission ledger: the only source of 'may this run PAPER?'",
    COST_V3: "COST_MODEL_V3 document: venue scenarios and knowledge classes",
    COST_MODEL_MODULE: "the executable cost model this artefact evaluates",
}

CAMPAIGN_SCENARIO = "BINANCE_SPOT_STANDARD_TAKER"
CAMPAIGN_STAKE_USDT = 200.0          # stake at which the runtime admission line is evaluated
MODEL_DEFAULT_STAKE_USD = 1_000.0    # stake at which the research expectancies are expressed
CAMPAIGN_HORIZON_MINUTES = 25.0      # the model's default and the campaign's frozen value
FROZEN_ADMISSION_RT_BPS = 23.353553391
FROZEN_STRESS_1_5X_BPS = 35.030330086
TOLERANCE_BPS = 1e-6
RESEARCH_BASE_RT_BPS = 12.0
OPS_PER_DAY = 3.0

HORIZON_GRID_MIN = (5.0, 15.0, 25.0, 60.0, 120.0, 240.0, 480.0, 1440.0)
FUNDING_RATES_BPS_PER_INTERVAL = (0.25, 1.0, 3.0)
STRESS_MULTIPLES = (1.0, 1.25, 1.5, 2.0)
SIZES_USD: tuple[float, ...] = (200.0, 1_000.0)
LIQUIDITIES: tuple[str, ...] = ("deep", "normal", "thin")

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def tracked(rel: str) -> bool:
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True, text=True
    )
    return out.returncode == 0


def read_json(rel: str) -> Any:
    path = ROOT / rel
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def r4(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def r9(value: float | None) -> float | None:
    return None if value is None else round(float(value), 9)


def model_module() -> Any:
    """Import the executable cost model the runtime itself uses."""
    sys.path.insert(0, str(ROOT / "src"))
    from trading_bot.research.microstructure import cost_model_v3

    return cost_model_v3


# --------------------------------------------------------------------------- #
# cells (WP-3 audit is the only source of the structural edge)
# --------------------------------------------------------------------------- #


def cells_from_audit(audit: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cell_id, row in sorted(audit["strategies"].items()):
        econ = row.get("economics") or {}
        gross = econ.get("zero_cost_gross_bps")
        out.append(
            {
                "cell_id": cell_id,
                "strategy_id": row.get("strategy_id"),
                "family": row.get("family"),
                "timeframe": row.get("timeframe"),
                "ledger_status": row.get("ledger_status"),
                "admitted_for_paper": row.get("admitted_for_paper"),
                "zero_cost_gross_bps": None if gross is None else float(gross),
                "gross_evidence": "ZERO_COST (independent of the cost plane)",
                "trades": (row.get("sample") or {}).get("trades"),
                "sample_sufficient": (row.get("sample") or {}).get("trades") is not None,
                "runtime_admission_rt_bps": (row.get("costs") or {}).get("runtime_admission_rt_bps"),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# venue grid and the horizon axes
# --------------------------------------------------------------------------- #


def venue_grid() -> list[dict[str, Any]]:
    cm = model_module()
    rows: list[dict[str, Any]] = []
    for scenario_id in cm.scenario_ids():
        model = cm.default_model(scenario_id)
        spec = model.spec
        funding_applicable = not str(spec.funding_source_id).startswith("n/a")
        for mode, entry, exit_ in (
            ("taker", "market", "market"),
            ("maker", "limit_post_only", "limit_post_only"),
        ):
            for size_usd in SIZES_USD:
                for liquidity in ("deep", "normal", "thin"):
                    all_in = model.evaluate(
                        size_usd=size_usd,
                        liquidity_regime=liquidity,
                        horizon_minutes=CAMPAIGN_HORIZON_MINUTES,
                        entry_order_type=entry,
                        exit_order_type=exit_,
                    )
                    classes = sorted({c.knowledge for c in all_in.components})
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "venue": spec.venue,
                            "product": spec.product,
                            "order_mode": mode,
                            "size_usd": size_usd,
                            "liquidity_regime": liquidity,
                            "round_trip_bps": float(all_in.round_trip_bps),
                            "knowledge_class": str(all_in.knowledge_class),
                            "component_classes": classes,
                            "rests_on_assumed_component": "ASSUMED" in classes,
                            "funding_applicable": funding_applicable,
                            "maker_fee_bps": spec.maker_fee_bps,
                            "taker_fee_bps": spec.taker_fee_bps,
                            "integration_status": spec.integration_status,
                            "components": [
                                {"name": c.name, "value_bps": r4(c.value_bps), "knowledge": c.knowledge}
                                for c in all_in.components
                            ],
                        }
                    )
    return rows


def model_horizon_axis() -> dict[str, Any]:
    """Is the round trip a function of holding time? Measure, do not assert."""
    cm = model_module()
    rows: list[dict[str, Any]] = []
    for scenario_id in cm.scenario_ids():
        model = cm.default_model(scenario_id)
        for mode, entry, exit_ in (("taker", "market", "market"), ("maker", "limit_post_only", "limit_post_only")):
            costs = []
            for horizon in (5.0, 15.0, 25.0, 60.0, 120.0, 240.0, 480.0, 1440.0):
                all_in = model.evaluate(
                    size_usd=CAMPAIGN_STAKE_USDT,
                    liquidity_regime="normal",
                    horizon_minutes=horizon,
                    entry_order_type=entry,
                    exit_order_type=exit_,
                )
                costs.append(float(all_in.round_trip_bps))
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "order_mode": mode,
                    "horizon_minutes": list(HORIZON_GRID_MIN),
                    "round_trip_bps": [r9(c) for c in costs],
                    "max_minus_min_bps": float(max(costs) - min(costs)),
                }
            )
    flat = all(r["max_minus_min_bps"] == 0.0 for r in rows)
    return {
        "question": "does the all-in round trip depend on holding time?",
        "rows": rows,
        "verdict": "HORIZON_INVARIANT_AT_ZERO_FUNDING" if flat else "HORIZON_DEPENDENT",
        "note": (
            "at a zero funding rate the model's cost has no horizon term: fees, spread, "
            "slippage and impact are per-execution quantities. Horizon enters only through "
            "funding carry on perpetuals, measured separately below."
        ),
    }


def funding_axis() -> dict[str, Any]:
    """Perp-only: how long may a position be held before funding eats a given edge?"""
    cm = model_module()
    perp_ids = [
        sid for sid in cm.scenario_ids()
        if not str(cm.VENUE_SPECS[sid].funding_source_id).startswith("n/a")
    ]
    rows: list[dict[str, Any]] = []
    minute_per_interval: float | None = None
    for scenario_id in perp_ids:
        model = cm.default_model(scenario_id)
        probe = model.evaluate(
            size_usd=CAMPAIGN_STAKE_USDT,
            liquidity_regime="normal",
            horizon_minutes=1440.0,
            entry_order_type="market",
            exit_order_type="market",
            funding_rate_bps_per_interval=1.0,
        )
        carry_1440 = sum(c.value_bps for c in probe.components if c.name == "funding_carry")
        intervals_per_day = carry_1440 / 1.0
        if intervals_per_day > 0.0:
            minute_per_interval = 1440.0 / intervals_per_day
        for mode, entry, exit_ in (("taker", "market", "market"), ("maker", "limit_post_only", "limit_post_only")):
            for rate in (0.25, 1.0, 3.0):
                for horizon in HORIZON_GRID_MIN:
                    all_in = model.evaluate(
                        size_usd=CAMPAIGN_STAKE_USDT,
                        liquidity_regime="normal",
                        horizon_minutes=horizon,
                        entry_order_type=entry,
                        exit_order_type=exit_,
                        funding_rate_bps_per_interval=rate,
                    )
                    carry = sum(c.value_bps for c in all_in.components if c.name == "funding_carry")
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "order_mode": mode,
                            "funding_rate_bps_per_interval": rate,
                            "horizon_minutes": horizon,
                            "funding_carry_bps": r9(carry),
                            "round_trip_bps": r9(all_in.round_trip_bps),
                            "analytic_carry_bps": (
                                None if minute_per_interval is None
                                else r9(rate * horizon / minute_per_interval)
                            ),
                        }
                    )
    return {
        "question": "how does holding time enter the barrier on a perpetual?",
        "funding_intervals_per_day_derived": (
            None if minute_per_interval is None else 1440.0 / minute_per_interval
        ),
        "minute_per_interval_derived": r9(minute_per_interval),
        "scenarios": perp_ids,
        "rows": rows,
        "note": (
            "carry is linear in both rate and horizon: rate x horizons / intervals_per_day. "
            "The analytic column is computed here from the measured interval length and must "
            "equal the model's own carry component."
        ),
    }


def market_horizon_axis() -> dict[str, Any]:
    """The repo's own cost horizon: median bars/hours for a move equal to the cost."""
    barrier = read_json(COST_BARRIER) or {}
    meta = barrier.get("meta") or {}
    lines = (meta.get("cost_model_bps_rt") or {})
    speeds: list[dict[str, Any]] = []
    for timeframe in ("5m", "15m", "30m", "1h"):
        for asset, row in sorted((barrier.get(timeframe) or {}).items()):
            speeds.append(
                {
                    "timeframe": timeframe,
                    "asset": asset,
                    "bars": row.get("bars"),
                    "abs_ret_bps_median": row.get("abs_ret_bps_median"),
                    "bars_to_BASE": row.get("bars_to_BASE"),
                    "hours_to_BASE": row.get("hours_to_BASE"),
                    "bars_to_2X_COST": row.get("bars_to_2X_COST"),
                    "hours_to_2X_COST": row.get("hours_to_2X_COST"),
                    "bars_to_STRESSED": row.get("bars_to_STRESSED"),
                    "hours_to_STRESSED": row.get("hours_to_STRESSED"),
                }
            )
    return {
        "question": "how long does the market itself need to move the cost line?",
        "source_definition": "bars_to_X = median bars for a move equal to X bps",
        "published_lines_bps": lines,
        "rows": speeds,
        "note": (
            "round trips convert to a *market* horizon through these medians. If the median "
            "move at a timeframe already exceeds the line, the market's amplitude is not the "
            "binding constraint; capture efficiency is."
        ),
    }


# --------------------------------------------------------------------------- #
# reachability
# --------------------------------------------------------------------------- #


def reachability(cells: list[dict[str, Any]], grid: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: list[dict[str, Any]] = []
    for cfg in grid:
        counts: dict[str, int] = {}
        best: list[dict[str, Any]] = []
        for multiple in STRESS_MULTIPLES:
            required = cfg["round_trip_bps"] * multiple
            reached = [
                {
                    "cell_id": c["cell_id"],
                    "distance_bps": c["zero_cost_gross_bps"] - required,
                }
                for c in cells
                if c["zero_cost_gross_bps"] is not None and c["zero_cost_gross_bps"] > required
            ]
            counts[f"{multiple}x"] = len(reached)
            if multiple == 1.0:
                best = sorted(reached, key=lambda r: r["distance_bps"], reverse=True)
        matrix.append(
            {
                "scenario_id": cfg["scenario_id"],
                "venue": cfg["venue"],
                "order_mode": cfg["order_mode"],
                "size_usd": cfg["size_usd"],
                "liquidity_regime": cfg["liquidity_regime"],
                "round_trip_bps": cfg["round_trip_bps"],
                "knowledge_class": cfg["knowledge_class"],
                "rests_on_assumed_component": cfg["rests_on_assumed_component"],
                "reachable_counts_by_stress": counts,
                "reachable_cell_ids": [r["cell_id"] for r in best],
                "best_distance_bps": best[0]["distance_bps"] if best else None,
            }
        )

    def cheapest(predicate) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
        """Cheapest line matching the predicate, preferring the canonical scenario.

        A ``*_TAKER`` and a ``*_MAKER`` spec are cost-identical when the same order
        types are used (the pair differs only in the fee the execution mode does not
        use), so the tie-break must not report a maker-named venue for taker execution.
        """
        subset = [row for row in matrix if predicate(row)]
        if not subset:
            return None

        def preference(row: dict[str, Any]) -> tuple[float, int, str]:
            suffix = "_TAKER" if row["order_mode"] == "taker" else "_MAKER"
            return (row["round_trip_bps"], 0 if row["scenario_id"].endswith(suffix) else 1,
                    row["scenario_id"])

        return min(subset, key=preference)

    observed_only = cheapest(lambda r: not r["rests_on_assumed_component"])
    assumed_free = cheapest(lambda r: True)
    taker_only = cheapest(lambda r: r["order_mode"] == "taker")
    maker_only = cheapest(lambda r: r["order_mode"] == "maker")

    cell_view: list[dict[str, Any]] = []
    for c in cells:
        gross = c["zero_cost_gross_bps"]
        if gross is None:
            cell_view.append(
                {
                    "cell_id": c["cell_id"],
                    "verdict": "UNKNOWN_GROSS_EDGE_NOT_PUBLISHED",
                    "zero_cost_gross_bps": None,
                }
            )
            continue
        rows = [r for r in matrix if r["reachable_counts_by_stress"]["1.0x"] > 0 and c["cell_id"] in r["reachable_cell_ids"]]
        near = sorted(
            (
                {
                    "scenario_id": r["scenario_id"],
                    "order_mode": r["order_mode"],
                    "size_usd": r["size_usd"],
                    "liquidity_regime": r["liquidity_regime"],
                    "round_trip_bps": r["round_trip_bps"],
                    "distance_bps": gross - r["round_trip_bps"],
                }
                for r in matrix
            ),
            key=lambda d: d["distance_bps"],
            reverse=True,
        )
        best_line = near[0] if near else None
        best_observed = next((d for d in near if not _assumed(d, matrix)), None)
        best_taker = next((d for d in near if d["order_mode"] == "taker"), None)
        verdict = "NOT_REACHABLE_AT_ANY_MODELED_VENUE"
        if rows and all(r["order_mode"] == "maker" for r in rows):
            verdict = "REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL"
        elif rows:
            verdict = "REACHABLE_TAKER"
        cell_view.append(
            {
                "cell_id": c["cell_id"],
                "family": c["family"],
                "timeframe": c["timeframe"],
                "ledger_status": c["ledger_status"],
                "zero_cost_gross_bps": gross,
                "verdict": verdict,
                "reachable_configurations": len(rows),
                "best_configuration": best_line,
                "best_observed_only_configuration": best_observed,
                "best_taker_configuration": best_taker,
                "cheapest_line_cleared": min((r["round_trip_bps"] for r in rows), default=None),
            }
        )

    return {
        "definition": "reachable := zero_cost_gross_bps > round_trip_bps * stress_multiple (strict)",
        "matrix": matrix,
        "cell_view": cell_view,
        "frontier": {
            "distinct_lines": len({row["round_trip_bps"] for row in matrix}),
            "configurations": len(matrix),
            "cheapest_line_observed_only": observed_only,
            "cheapest_line_any": assumed_free,
            "cheapest_line_taker": taker_only,
            "cheapest_line_maker": maker_only,
            "max_zero_cost_gross_bps": max(
                (c["zero_cost_gross_bps"] for c in cells if c["zero_cost_gross_bps"] is not None),
                default=None,
            ),
            "reachable_cells_observed_only": sum(
                1
                for r in cell_view
                if r["verdict"] in ("REACHABLE_TAKER",)
            ),
            "reachable_cells_any": sum(
                1
                for r in cell_view
                if r["verdict"].startswith("REACHABLE")
            ),
            "cells_unknown": sum(1 for r in cell_view if r["verdict"].startswith("UNKNOWN")),
        },
    }


def _assumed(row: dict[str, Any], matrix: list[dict[str, Any]]) -> bool:
    for cfg in matrix:
        if (
            cfg["scenario_id"] == row["scenario_id"]
            and cfg["order_mode"] == row["order_mode"]
            and cfg["size_usd"] == row["size_usd"]
            and cfg["liquidity_regime"] == row["liquidity_regime"]
        ):
            return bool(cfg["rests_on_assumed_component"])
    return False


def execution_direction() -> dict[str, Any]:
    """Post-only versus market: measure which way the price moves per venue."""
    cm = model_module()
    rows: list[dict[str, Any]] = []
    for scenario_id in cm.scenario_ids():
        model = cm.default_model(scenario_id)
        taker = model.evaluate(
            size_usd=CAMPAIGN_STAKE_USDT,
            liquidity_regime="normal",
            horizon_minutes=CAMPAIGN_HORIZON_MINUTES,
            entry_order_type="market",
            exit_order_type="market",
        )
        maker = model.evaluate(
            size_usd=CAMPAIGN_STAKE_USDT,
            liquidity_regime="normal",
            horizon_minutes=CAMPAIGN_HORIZON_MINUTES,
            entry_order_type="limit_post_only",
            exit_order_type="limit_post_only",
        )
        delta = float(maker.round_trip_bps) - float(taker.round_trip_bps)
        rows.append(
            {
                "scenario_id": scenario_id,
                "maker_fee_bps": model.spec.maker_fee_bps,
                "taker_fee_bps": model.spec.taker_fee_bps,
                "taker_round_trip_bps": r4(float(taker.round_trip_bps)),
                "maker_round_trip_bps": r4(float(maker.round_trip_bps)),
                "maker_minus_taker_bps": r4(delta),
                "direction": "maker_cheaper" if delta < 0.0 else ("maker_dearer" if delta > 0.0 else "equal"),
            }
        )
    return {
        "question": "is post-only execution cheaper than market execution?",
        "rows": rows,
        "note": (
            "measured, not assumed. Post-only is dearer wherever the maker fee is non-zero, "
            "because the model inflates an unfilled leg's fee by 1/fill_probability; it is "
            "cheaper only where the maker fee really is 0 (or the taker fee dominates)."
        ),
    }


def spot_funding_footgun() -> dict[str, Any]:
    """Probe whether the model guards funding carry by product, or trusts the caller."""
    cm = model_module()
    model = cm.default_model(CAMPAIGN_SCENARIO)
    with_rate = model.evaluate(
        size_usd=CAMPAIGN_STAKE_USDT,
        liquidity_regime="normal",
        horizon_minutes=1440.0,
        entry_order_type="market",
        exit_order_type="market",
        funding_rate_bps_per_interval=1.0,
    )
    carry = sum(c.value_bps for c in with_rate.components if c.name == "funding_carry")
    return {
        "probe": "call a spot scenario with a non-zero funding rate",
        "product": model.spec.product,
        "funding_source_id": model.spec.funding_source_id,
        "carry_added_bps": r9(carry),
        "guarded_by_model": carry == 0.0,
        "note": (
            "the model applies carry whenever a rate is supplied, whatever the product. The "
            "guard therefore lives in the caller: this explorer only ever passes a funding "
            "rate to perpetual scenarios."
        ),
    }


def frequency_axis(audit: dict[str, Any], frontier: dict[str, Any]) -> dict[str, Any]:
    """What does the 3-round-trips-a-day objective cost under each line?"""
    published = (audit.get("objective_3_ops_per_day") or {})
    trips = float(published.get("requirement_round_trips_per_year") or OPS_PER_DAY * 365.0)
    rows = []
    for label, line in (
        ("campaign_runtime_admission", FROZEN_ADMISSION_RT_BPS),
        ("research_base", RESEARCH_BASE_RT_BPS),
        ("cheapest_taker_observed", (frontier.get("cheapest_line_taker") or {}).get("round_trip_bps")),
        ("cheapest_any_assumed", (frontier.get("cheapest_line_any") or {}).get("round_trip_bps")),
    ):
        if line is None:
            continue
        annual_bps = float(line) * trips
        rows.append(
            {
                "line": label,
                "round_trip_bps": float(line),
                "round_trips_per_year": trips,
                "annual_cost_bps": annual_bps,
                "annual_cost_pct_of_stake": annual_bps / 100.0,
            }
        )
    return {
        "question": "what does the 3-operations-per-day objective cost per year?",
        "published_current_operations_per_day": published.get("current_operations_per_day"),
        "requirement_round_trips_per_year": trips,
        "rows": rows,
        "note": (
            "cost-only arithmetic: gross edge must exceed these figures before any net "
            "profit exists. No strategy in the repository is claimed to sustain them."
        ),
    }


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #


# The identity convention of the artefact this explorer re-derives. It has to track that
# artefact's own list: WP-8 added ``local_observations`` there (per-machine materialization
# facts that must not certify anything), and the check below caught the divergence as a
# failed re-derivation rather than a silent mismatch - which is what it is for.
VOLATILE_KEYS = ("generated_at_utc", "payload_sha256", "head", "branch", "sources", "local_observations")


def payload_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in VOLATILE_KEYS}
    return hashlib.sha256(
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build() -> dict[str, Any]:
    audit = read_json(AUDIT)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})

    if not isinstance(audit, dict):
        raise SystemExit(f"missing prerequisite {AUDIT}")

    # --- provenance ------------------------------------------------------- #
    stored_body = {k: v for k, v in audit.items() if k not in VOLATILE_KEYS}
    recomputed = hashlib.sha256(
        json.dumps(stored_body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    check(
        "audit:payload_sha256_reproduces",
        recomputed == audit.get("payload_sha256"),
        f"recomputed {recomputed[:16]} vs stored {str(audit.get('payload_sha256'))[:16]}",
    )
    sources = [
        {"path": rel, "role": SOURCE_ROLES[rel], "exists": (ROOT / rel).exists(),
         "tracked": tracked(rel) if (ROOT / rel).exists() else None,
         "sha256": sha256_file(ROOT / rel)}
        for rel in (AUDIT, COST_BARRIER, LEDGER, COST_V3, COST_MODEL_MODULE)
    ]
    check("sources:all_present", all(s["exists"] for s in sources),
          ", ".join(f"{s['path']}={'ok' if s['exists'] else 'MISSING'}" for s in sources))

    cells = cells_from_audit(audit)
    grid = venue_grid()
    model_horizon = model_horizon_axis()
    funding = funding_axis()
    market_horizon = market_horizon_axis()
    direction = execution_direction()
    footgun = spot_funding_footgun()
    reach = reachability(cells, grid)
    frontier = reach["frontier"]
    frequency = frequency_axis(audit, frontier)

    gross_positive = sorted(
        c["cell_id"] for c in cells
        if c["zero_cost_gross_bps"] is not None and c["zero_cost_gross_bps"] > 0.0
    )
    declared_positive = sorted((audit.get("aggregates") or {}).get("zero_cost_gross_positive") or [])

    # --- checks ----------------------------------------------------------- #
    check("cells:count_matches_audit",
          len(cells) == int(audit.get("strategy_count") or -1),
          f"{len(cells)} cells vs strategy_count {audit.get('strategy_count')}")
    check("cells:gross_positive_set_matches_audit_aggregates",
          gross_positive == declared_positive,
          f"derived {gross_positive} vs declared {declared_positive}")
    check("cells:no_gross_invented",
          all(
              c["zero_cost_gross_bps"] is None
              or abs(c["zero_cost_gross_bps"] - float(audit["strategies"][c["cell_id"]]["economics"]["zero_cost_gross_bps"])) < 1e-9
              for c in cells
          ),
          "every cell gross is the audit's own published value, compared exactly")

    cm = model_module()
    campaign = cm.default_model(CAMPAIGN_SCENARIO)
    campaign_cost = campaign.evaluate(
        size_usd=CAMPAIGN_STAKE_USDT,
        liquidity_regime="normal",
        horizon_minutes=CAMPAIGN_HORIZON_MINUTES,
        entry_order_type="market",
        exit_order_type="market",
    )
    campaign_bps = float(campaign_cost.round_trip_bps)
    check("campaign:cost_line_reproduces",
          abs(campaign_bps - FROZEN_ADMISSION_RT_BPS) <= TOLERANCE_BPS
          and abs(campaign_bps - float((audit.get("cost_plane") or {}).get("round_trip_bps_200_usdt") or -1)) <= 1e-9,
          f"derived {campaign_bps!r} vs frozen {FROZEN_ADMISSION_RT_BPS} vs audit "
          f"{(audit.get('cost_plane') or {}).get('round_trip_bps_200_usdt')!r}")
    check("campaign:stress_line_reproduces",
          abs(campaign_bps * 1.5 - FROZEN_STRESS_1_5X_BPS) <= TOLERANCE_BPS,
          f"derived {campaign_bps * 1.5!r} vs frozen {FROZEN_STRESS_1_5X_BPS}")
    check("source:research_base_agrees_across_sources",
          float((market_horizon["published_lines_bps"] or {}).get("BASE") or -1) == RESEARCH_BASE_RT_BPS
          and all(
              abs(float((audit["strategies"][c]["costs"] or {}).get("research_base_rt_bps") or -1)
                  - RESEARCH_BASE_RT_BPS) < 1e-9
              for c in audit["strategies"]
          ),
          f"COST_BARRIER BASE={market_horizon['published_lines_bps'].get('BASE')} and every "
          f"audit cell agree on {RESEARCH_BASE_RT_BPS}")

    check("horizon:zero_funding_is_flat", model_horizon["verdict"] == "HORIZON_INVARIANT_AT_ZERO_FUNDING",
          "; ".join(f"{r['scenario_id']}/{r['order_mode']} spread {r['max_minus_min_bps']}"
                    for r in model_horizon["rows"] if r["max_minus_min_bps"] != 0.0)
          or "every scenario is exactly flat across the horizon grid: max-min = 0.0 bps")
    check("horizon:funding_is_only_ever_passed_to_perpetuals",
          footgun["product"] == "Spot" and len(funding["scenarios"]) >= 1
          and all(row["funding_applicable"] is False for row in grid if row["scenario_id"] not in funding["scenarios"]),
          f"funding-applicable scenarios {funding['scenarios']}; probe: a spot scenario given a "
          f"funding rate would add {footgun['carry_added_bps']} bps of carry "
          f"(model_guarded={footgun['guarded_by_model']}), so the caller is the guard")
    drift = [
        abs(float(row["funding_carry_bps"]) - float(row["analytic_carry_bps"]))
        for row in funding["rows"] if row["analytic_carry_bps"] is not None
    ]
    check("horizon:funding_carry_matches_analytic_form",
          bool(drift) and max(drift) <= 1e-9,
          f"max |model - rate*horizon/{funding['minute_per_interval_derived']}| = "
          f"{max(drift) if drift else 'n/a'} bps over {len(drift)} rows")
    covered = {
        tf: sorted({row["asset"] for row in market_horizon["rows"] if row["timeframe"] == tf})
        for tf in {row["timeframe"] for row in market_horizon["rows"]}
    }
    check("horizon:market_time_to_cover_covers_every_cell_timeframe",
          {c["timeframe"] for c in cells} <= set(covered),
          f"cells timeframes {sorted({c['timeframe'] for c in cells})} vs published {sorted(covered)}")

    by_key: dict[tuple[str, str, str, float], float] = {}
    for cfg in grid:
        by_key[(cfg["scenario_id"], cfg["order_mode"], cfg["liquidity_regime"], cfg["size_usd"])] = cfg["round_trip_bps"]
    size_ok = all(
        by_key[(sid, mode, liq, 1_000.0)] >= by_key[(sid, mode, liq, 200.0)]
        for sid in cm.scenario_ids() for mode in ("taker", "maker") for liq in ("deep", "normal", "thin")
    )
    check("monotonic:cost_non_decreasing_in_size", size_ok,
          "round trip at 1000 USD >= at 200 USD for every scenario, mode and liquidity regime")
    liq_ok = all(
        by_key[(sid, mode, "deep", size)] <= by_key[(sid, mode, "normal", size)] <= by_key[(sid, mode, "thin", size)]
        for sid in cm.scenario_ids() for mode in ("taker", "maker") for size in SIZES_USD
    )
    check("monotonic:cost_non_decreasing_as_liquidity_worsens", liq_ok,
          "deep <= normal <= thin for every scenario, mode and size")
    spec_pairs = [
        (sid, sid[: -len("_TAKER")] + "_MAKER") for sid in cm.scenario_ids()
        if sid.endswith("_TAKER") and sid[: -len("_TAKER")] + "_MAKER" in cm.VENUE_SPECS
    ]
    pair_identical = all(
        by_key[(taker_id, mode, liq, size)] == by_key[(maker_id, mode, liq, size)]
        for taker_id, maker_id in spec_pairs
        for mode in ("taker", "maker") for liq in LIQUIDITIES for size in SIZES_USD
    )
    check("scenarios:taker_maker_spec_pairs_are_cost_identical_for_equal_order_types",
          bool(spec_pairs) and pair_identical,
          f"{len(spec_pairs)} spec pair(s) differ only in the fee the execution mode does not "
          f"use, so the grid carries {frontier['distinct_lines']} distinct lines across "
          f"{frontier['configurations']} configurations")
    directions = {row["scenario_id"]: row["direction"] for row in direction["rows"]}
    check("structure:maker_price_direction_is_measured_not_assumed",
          {directions[sid] for sid in cm.scenario_ids()} == {"maker_cheaper", "maker_dearer"},
          "both directions occur across the 9 scenarios ("
          + ", ".join(f"{sid}={directions[sid]}" for sid in cm.scenario_ids()) + ")")

    observed = frontier["cheapest_line_observed_only"]
    any_line = frontier["cheapest_line_any"]
    best_gross = frontier["max_zero_cost_gross_bps"]
    check("barrier:no_cell_reachable_on_a_line_without_assumed_components",
          observed is not None and best_gross is not None
          and all(
              (row["zero_cost_gross_bps"] or 0.0) <= observed["round_trip_bps"]
              for row in reach["cell_view"]
              if row["zero_cost_gross_bps"] is not None
          ),
          f"cheapest line without an assumed component {observed['round_trip_bps'] if observed else None} "
          f"bps ({observed['scenario_id']}/{observed['order_mode']}/{observed['liquidity_regime']} "
          f"if observed else '') vs best cell gross {best_gross} bps")
    check("barrier:reachable_set_equals_gross_above_the_cheapest_line",
          frontier["reachable_cells_any"] == len([
              c for c in cells
              if c["zero_cost_gross_bps"] is not None
              and any_line is not None
              and c["zero_cost_gross_bps"] > any_line["round_trip_bps"]
          ]),
          f"{frontier['reachable_cells_any']} reachable vs the count implied by the cheapest line "
          f"{any_line['round_trip_bps'] if any_line else None} bps")
    check("barrier:taker_execution_clears_nothing",
          frontier["cheapest_line_taker"] is not None
          and frontier["max_zero_cost_gross_bps"] is not None
          and frontier["max_zero_cost_gross_bps"] < frontier["cheapest_line_taker"]["round_trip_bps"],
          f"best gross {frontier['max_zero_cost_gross_bps']} bps < cheapest taker round trip "
          f"{frontier['cheapest_line_taker']['round_trip_bps']} bps "
          f"({frontier['cheapest_line_taker']['scenario_id']})")
    campaign_row = min(
        (r for r in reach["matrix"] if r["scenario_id"] == CAMPAIGN_SCENARIO
         and r["order_mode"] == "taker" and r["size_usd"] == CAMPAIGN_STAKE_USDT
         and r["liquidity_regime"] == "normal"),
        key=lambda r: r["round_trip_bps"],
    )
    audit_net_positive = (audit.get("aggregates") or {}).get("net_positive_count")
    check("consistency:campaign_line_reaches_no_cell",
          campaign_row["reachable_counts_by_stress"]["1.0x"] == 0
          and isinstance(audit_net_positive, int) and audit_net_positive == 0,
          f"reachable at the campaign line: {campaign_row['reachable_counts_by_stress']['1.0x']}; "
          f"audit net_positive_count {audit_net_positive!r}")
    amplitude_by_tf = {
        tf: min((r["abs_ret_bps_median"] or 0.0)
                for r in market_horizon["rows"] if r["timeframe"] == tf)
        for tf in {r["timeframe"] for r in market_horizon["rows"]}
    }
    above_campaign_line = sorted(
        f"{r['timeframe']}/{r['asset']}" for r in market_horizon["rows"]
        if (r["abs_ret_bps_median"] or 0.0) > campaign_bps
    )
    check("amplitude:median_bar_move_covers_the_base_line_only_from_30m_up",
          amplitude_by_tf.get("30m", 0.0) > RESEARCH_BASE_RT_BPS
          and amplitude_by_tf.get("1h", 0.0) > RESEARCH_BASE_RT_BPS
          and amplitude_by_tf.get("5m", 99.0) < RESEARCH_BASE_RT_BPS
          and amplitude_by_tf.get("15m", 99.0) < RESEARCH_BASE_RT_BPS,
          "worst-asset median bar move by timeframe: "
          + ", ".join(f"{tf}={amplitude_by_tf[tf]}" for tf in sorted(amplitude_by_tf))
          + f" bps vs base line {RESEARCH_BASE_RT_BPS} bps")
    check("amplitude:only_one_published_median_move_reaches_the_campaign_line",
          above_campaign_line == ["1h/SOL"],
          f"cells above the campaign line {campaign_bps} bps: {above_campaign_line or 'none'}")
    line_multiple = (
        round((observed["round_trip_bps"] if observed else 0.0) / best_gross, 3)
        if observed and best_gross else None
    )
    check("amplitude:the_executable_line_is_a_multiple_of_the_best_edge",
          line_multiple is not None and line_multiple > 1.0,
          f"cheapest observed-only line {fmt(observed['round_trip_bps'] if observed else None)} bps "
          f"= {line_multiple}x the best cell's entire edge ({fmt(best_gross)} bps), so the best "
          f"cell must improve its capture or the line must fall by "
          f"{fmt((observed['round_trip_bps'] - best_gross) if observed and best_gross else None)} bps")
    check("governance:no_promotion_or_rentability_claimed",
          str((audit.get("answers") or {}).get("Q6_next_rfc", {}).get("authorization_state")) == "NOT_AUTHORIZED",
          "the explorer reduces the barrier to a measured configuration set; it authorizes nothing "
          "and claims no strategy is RENTABLE, CERTIFIED or PRODUCTION_READY")

    return {
        "artifact": "COST_BARRIER_EXPLORER",
        "work_package": "POST RFC-049 / ACTIVE RECOVERY - WP-6 (cost-barrier exploration)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip(),
        "branch": subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True,
                                 text=True).stdout.strip(),
        "mode": "OFFLINE read-only: no keys, no orders, no capital, no live path",
        "ladder": (
            "This is WP-6 of the ACTIVE recovery lane: WP-1 closed RFC-049, WP-2 reconstructed "
            "campaign state, WP-3 audited the 24 cells, WP-4/5 reported. WP-6 turns the cost "
            "plane from a gate into a searched surface: which (venue, execution mode, size, "
            "liquidity) lines any cell can clear, and at which horizon."
        ),
        "cells": cells,
        "venue_grid": grid,
        "execution_direction": direction,
        "model_limitations": {"spot_funding_guard": footgun},
        "horizon": {
            "model_horizon": model_horizon,
            "funding_horizon": funding,
            "market_horizon": market_horizon,
        },
        "reachability": reach,
        "frequency": frequency,
        "sources": sources,
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if c["result"] != "PASS"),
        "claims": {
            "promotion_claimed": False,
            "rentable_claimed": False,
            "certified_claimed": False,
            "production_ready_claimed": False,
            "authorization_state": "NOT_AUTHORIZED",
            "trades_authorized": 0,
            "false_success": 0,
        },
        "scope": (
            "Derived, read-only map. Every cost is the repository's own COST_MODEL_V3 evaluated "
            "at the stated configuration; every edge is the WP-3 audit's published zero-cost "
            "gross. No metric is estimated here and no runtime behaviour is changed."
        ),
    }


def fmt(value: Any, digits: int = 4) -> str:
    """Presentation only: the JSON keeps full precision, the report is readable."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") if abs(value) < 1e15 else str(value)
    return str(value)


def render_markdown(payload: dict[str, Any]) -> str:
    frontier = payload["reachability"]["frontier"]
    mh = payload["horizon"]["model_horizon"]
    fh = payload["horizon"]["funding_horizon"]
    mk = payload["horizon"]["market_horizon"]
    lines: list[str] = [
        "# COST-BARRIER EXPLORER - per venue and per horizon",
        "",
        f"- generated `{payload['generated_at_utc']}` · head `{payload['head'][:12]}` · "
        f"branch `{payload['branch']}`",
        f"- mode: {payload['mode']}",
        f"- cells: {len(payload['cells'])} · venue configurations: {len(payload['venue_grid'])} "
        f"· checks: {payload['checks_total'] - payload['checks_failed']}/{payload['checks_total']} pass",
        "",
        "## 1. Headline",
        "",
        f"- best structural edge (zero-cost gross): **{fmt(frontier['max_zero_cost_gross_bps'])} bps**",
        f"- cheapest round trip **without** any assumed component: "
        f"**{fmt(frontier['cheapest_line_observed_only']['round_trip_bps'])} bps** "
        f"({frontier['cheapest_line_observed_only']['scenario_id']}, "
        f"{frontier['cheapest_line_observed_only']['order_mode']}, "
        f"{frontier['cheapest_line_observed_only']['size_usd']:.0f} USD, "
        f"{frontier['cheapest_line_observed_only']['liquidity_regime']})",
        f"- cheapest line **anywhere** in the model: "
        f"**{fmt(frontier['cheapest_line_any']['round_trip_bps'])} bps** "
        f"({frontier['cheapest_line_any']['scenario_id']}, {frontier['cheapest_line_any']['order_mode']})",
        f"- cells reachable on an observed-only line: **{frontier['reachable_cells_observed_only']}** "
        f"of {len(payload['cells'])}",
        f"- cells reachable once assumed maker-fill components are admitted: "
        f"**{frontier['reachable_cells_any']}** of {len(payload['cells'])}",
        "",
        "The whole cost surface is therefore split in two: execution that is *priced* by "
        "observed components cannot carry any cell, and the only lines that can carry a cell "
        "are the ones whose honesty depends on an unmodelled maker fill / adverse-selection "
        "assumption.",
        "",
        "## 2. Horizon: what holding time does to the barrier",
        "",
        f"**Model horizon - {mh['verdict']}.** Measured on {len(mh['rows'])} "
        f"(scenario, execution mode) pairs across "
        + " ".join(f"{h:.0f}m" for h in mh["rows"][0]["horizon_minutes"]) + ":",
        "",
    ]
    flat_rows = [row for row in mh["rows"] if row["max_minus_min_bps"] == 0.0]
    if len(flat_rows) == len(mh["rows"]):
        lines.append(f"- all {len(flat_rows)} pairs are exactly flat: max - min = 0.0 bps")
    else:
        lines += ["| scenario | mode | max - min bps |", "| --- | --- | --- |"]
        for row in mh["rows"]:
            lines.append(
                f"| {row['scenario_id']} | {row['order_mode']} | {row['max_minus_min_bps']} |"
            )
    lines += [
        "",
        "The round trip is a per-execution quantity: with a zero funding rate the model's price "
        "does not move across five minutes or a day. Horizon enters the barrier in exactly one "
        "place, and it is not a strategy parameter.",
        "",
        f"**Funding horizon - perpetuals only** (funding interval "
        f"{fh['minute_per_interval_derived']:.0f} min, derived from the model, not typed). "
        f"Carry = rate x horizon / interval, verified against the model on "
        f"{len([r for r in fh['rows'] if r['analytic_carry_bps'] is not None])} rows.",
        "",
        "| scenario | mode | rate (bps/8h) | horizon | carry bps | round trip bps |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in fh["rows"]:
        if row["horizon_minutes"] in (240.0, 1440.0):
            lines.append(
                f"| {row['scenario_id']} | {row['order_mode']} | {row['funding_rate_bps_per_interval']} "
                f"| {row['horizon_minutes']:.0f}m | {fmt(row['funding_carry_bps'])} "
                f"| {fmt(row['round_trip_bps'])} |"
            )
    best_gross = frontier["max_zero_cost_gross_bps"] or 0.0
    funding_budget = [
        {
            "rate_bps_per_interval": rate,
            "hours_before_carry_equals_best_edge": round(best_gross * (fh["minute_per_interval_derived"] or 480.0) / rate / 60.0, 2),
        }
        for rate in FUNDING_RATES_BPS_PER_INTERVAL
    ]
    lines += [
        "",
        "Holding budget: how long the best measured edge survives funding carry on a perpetual",
        "",
        "| funding rate (bps/8h) | hours until carry alone consumes "
        f"{best_gross} bps |",
        "| --- | --- |",
    ]
    for row in funding_budget:
        lines.append(
            f"| {row['rate_bps_per_interval']} | {row['hours_before_carry_equals_best_edge']} |"
        )
    lines += [
        "",
        "**Market horizon - how long the market itself needs to move the cost line.** "
        f"Source definition: *{mk['source_definition']}*.",
        "",
        "| timeframe | asset | median bar move (bps) | bars to BASE | hours to BASE "
        "| bars to 2X | hours to 2X |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in mk["rows"]:
        lines.append(
            f"| {row['timeframe']} | {row['asset']} | {row['abs_ret_bps_median']} "
            f"| {row['bars_to_BASE']} | {row['hours_to_BASE']} "
            f"| {row['bars_to_2X_COST']} | {row['hours_to_2X_COST']} |"
        )
    amplitude_by_tf = {
        tf: min((r["abs_ret_bps_median"] or 0.0)
                for r in mk["rows"] if r["timeframe"] == tf)
        for tf in {r["timeframe"] for r in mk["rows"]}
    }
    above_campaign = sorted(
        f"{r['timeframe']}/{r['asset']}" for r in mk["rows"]
        if (r["abs_ret_bps_median"] or 0.0) > (frontier["cheapest_line_observed_only"] or {}).get(
            "round_trip_bps", float("inf"))
    )
    lines += [
        "",
        "Worst-asset median bar move by timeframe: "
        + ", ".join(f"{tf}={amplitude_by_tf[tf]}" for tf in sorted(amplitude_by_tf))
        + f" bps. The base line is {RESEARCH_BASE_RT_BPS} bps, so the market's own amplitude "
        "only reaches it from 30m upward; at 5m and 15m the median bar does not pay a single "
        "round trip. Published medians that exceed the cheapest *executable* line: "
        + (", ".join(above_campaign) if above_campaign else "none")
        + ". Amplitude is therefore not the free variable - capture per execution is.",
        "",
        "## 3. Venue frontier",
        "",
        "One row per (scenario, execution mode, size). `bps` columns are the round trip by "
        "liquidity regime; `reach@1x` columns are how many of the 24 cells that exact line "
        "carries.",
        "",
        "| scenario | mode | size | deep bps | normal bps | thin bps | class "
        "| reach@1x deep | reach@1x normal | reach@1x thin |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    mat = {
        (row["scenario_id"], row["order_mode"], row["size_usd"], row["liquidity_regime"]): row
        for row in payload["reachability"]["matrix"]
    }
    seen: set[tuple[str, str, float]] = set()
    for row in payload["reachability"]["matrix"]:
        key = (row["scenario_id"], row["order_mode"], row["size_usd"])
        if key in seen:
            continue
        seen.add(key)
        trio = [mat[(row["scenario_id"], row["order_mode"], row["size_usd"], liq)]
                for liq in LIQUIDITIES]
        lines.append(
            f"| {row['scenario_id']} | {row['order_mode']} | {row['size_usd']:.0f} "
            f"| {fmt(trio[0]['round_trip_bps'])} | {fmt(trio[1]['round_trip_bps'])} "
            f"| {fmt(trio[2]['round_trip_bps'])} | {trio[0]['knowledge_class']} "
            f"| {trio[0]['reachable_counts_by_stress']['1.0x']} "
            f"| {trio[1]['reachable_counts_by_stress']['1.0x']} "
            f"| {trio[2]['reachable_counts_by_stress']['1.0x']} |"
        )
    lines += [
        "",
        "Post-only direction, measured per venue:",
        "",
        "| scenario | taker bps | maker bps | maker - taker | direction |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["execution_direction"]["rows"]:
        lines.append(
            f"| {row['scenario_id']} | {fmt(row['taker_round_trip_bps'])} "
            f"| {fmt(row['maker_round_trip_bps'])} "
            f"| {fmt(row['maker_minus_taker_bps'])} | {row['direction']} |"
        )
    lines += [
        "",
        "## 4. Cells",
        "",
        "| cell | ledger | gross bps | verdict | cheapest line cleared | best configuration |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["reachability"]["cell_view"]:
        best = row.get("best_configuration") or {}
        lines.append(
            f"| {row['cell_id']} | {row.get('ledger_status')} "
            f"| {fmt(row.get('zero_cost_gross_bps'))} "
            f"| {row['verdict']} | {fmt(row.get('cheapest_line_cleared'))} "
            f"| {best.get('scenario_id')}/{best.get('order_mode')}/"
            f"{fmt(best.get('size_usd'), 0)} USD/{best.get('liquidity_regime')} "
            f"({fmt(best.get('distance_bps'))} bps) |"
        )
    lines += [
        "",
        "## 5. What the 3-operations-per-day objective costs",
        "",
        "| line | round trip bps | trips/yr | annual cost bps | annual cost % of stake |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["frequency"]["rows"]:
        lines.append(
            f"| {row['line']} | {fmt(row['round_trip_bps'])} | {row['round_trips_per_year']:.0f} "
            f"| {fmt(row['annual_cost_bps'], 1)} | {fmt(row['annual_cost_pct_of_stake'], 2)} |"
        )
    lines += [
        "",
        "## 6. Checks and governance",
        "",
        f"**{payload['checks_total'] - payload['checks_failed']}/{payload['checks_total']} checks pass; "
        f"checks_failed = {payload['checks_failed']}.**",
        "",
    ]
    for row in payload["checks"]:
        lines.append(f"- `{row['result']}` {row['check']} - {row['detail']}")
    lines += [
        "",
        f"- claims: {json.dumps(payload['claims'], sort_keys=True)}",
        f"- payload_sha256: `{payload.get('payload_sha256', '')}`",
        "",
        "Nothing here declares a strategy RENTABLE, CERTIFIED or PRODUCTION_READY. The map "
        "shows where a barrier could be cleared and under which assumptions; the assumptions "
        "that would have to be earned (a forward maker fill model, observed spreads) are named, "
        "not granted.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="rebuild and compare payload_sha256 with the stored artefact")
    parser.add_argument("--out-dir", type=Path, default=OUT,
                        help="directory to write the artefact into (default: data/recovery). "
                             "A drift gate uses a temporary directory so reproduction never "
                             "touches the published files.")
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build()
    payload["payload_sha256"] = payload_hash(payload)
    target_json = out_dir / "COST_BARRIER_EXPLORER.json"
    stored = json.loads(target_json.read_text(encoding="utf-8")) if target_json.exists() else {}
    target_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "COST_BARRIER_EXPLORER.md").write_text(render_markdown(payload), encoding="utf-8")

    if args.check:
        same = stored.get("payload_sha256") == payload["payload_sha256"]
        print(json.dumps({"check": "determinism:payload_sha256_stable",
                          "result": "PASS" if same else "FAIL",
                          "detail": f"{payload['payload_sha256'][:16]} vs "
                                    f"{str(stored.get('payload_sha256'))[:16]}"}))
        return 0 if same else 1

    print(json.dumps({
        "cells": len(payload["cells"]),
        "configurations": len(payload["venue_grid"]),
        "reachable_observed_only": payload["reachability"]["frontier"]["reachable_cells_observed_only"],
        "reachable_any": payload["reachability"]["frontier"]["reachable_cells_any"],
        "best_gross_bps": payload["reachability"]["frontier"]["max_zero_cost_gross_bps"],
        "cheapest_observed_only_bps": payload["reachability"]["frontier"]["cheapest_line_observed_only"]["round_trip_bps"],
        "cheapest_any_bps": payload["reachability"]["frontier"]["cheapest_line_any"]["round_trip_bps"],
        "checks_failed": payload["checks_failed"],
        "payload_sha256": payload["payload_sha256"],
    }, indent=2))
    return 1 if payload["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
