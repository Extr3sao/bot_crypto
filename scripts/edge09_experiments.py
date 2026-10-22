#!/usr/bin/env python
"""WP-EDGE-09E — run the registered experiments where the gates allow.

    python scripts/edge09_experiments.py

Writes ``experiments/EXPERIMENTS.{json,md}`` and
``experiments/EXPERIMENT_REGISTRY.{json,md}``. The registry carries every
hypothesis with its classification, including the ones that failed and the
negative control, because a package that only publishes its wins is not a
research package.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09 import experiments, gates  # noqa: E402
from trading_bot.research.edge09.panel import (  # noqa: E402
    read_depth,
    read_oi,
    read_panel_map,
)
from trading_bot.research.edge09.registration import (  # noqa: E402
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    HYPOTHESES,
    SCENARIOS_COMPARED,
    SCHEMA_VERSION,
    WP,
)

PANEL_DIR = WP / "panel"
GATES_JSON = WP / "gates" / "COST_LIQUIDITY_CAPACITY.json"
OUTDIR = WP / "experiments"


def venue_comparison(
    barriers: list[dict[str, Any]], best_gross_bps: float | None
) -> dict[str, Any]:
    """E-02: would a different fee schedule turn the same gross into a net gain?"""
    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS_COMPARED:
        selected = [row for row in barriers if row.get("scenario") == scenario]
        if not selected:
            continue
        round_trips = sorted(row["round_trip_bps"] for row in selected)
        cheapest = round_trips[0]
        rows.append(
            {
                "scenario": scenario,
                "venue": selected[0]["venue"],
                "assets_compared": len(selected),
                "cheapest_round_trip_bps": cheapest,
                "fee_component_bps": min(row["components_bps"]["fee"] for row in selected),
                "net_at_best_gross_bps": None
                if best_gross_bps is None
                else round(best_gross_bps - cheapest, 6),
                "clears_cost": None if best_gross_bps is None else bool(best_gross_bps >= cheapest),
                "clears_1_5x": None
                if best_gross_bps is None
                else bool(best_gross_bps >= 1.5 * cheapest),
            }
        )
    best = min(rows, key=lambda row: row["cheapest_round_trip_bps"]) if rows else None
    return {
        "hypothesis": "E-02",
        "best_measured_gross_bps": best_gross_bps,
        "scenarios": rows,
        "cheapest_scenario": best["scenario"] if best else None,
        "falsified": None
        if best is None or best_gross_bps is None
        else not bool(best_gross_bps >= best["cheapest_round_trip_bps"]),
        "note": (
            "a venue change is a governance decision; this only measures whether the "
            "fee schedule is what blocks the edge"
        ),
    }


def capacity_verdict(capacity: list[dict[str, Any]], quote_size_usd: float) -> dict[str, Any]:
    """E-03: can the measured book absorb the quoted size inside a 5 bps band?"""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in capacity:
        grouped.setdefault((row["market"], row["symbol"]), []).append(
            row["bid_notional_within_5.0bps_usd"]
        )
    rows = []
    for (market, symbol), values in sorted(grouped.items()):
        median_notional = statistics.median(values)
        rows.append(
            {
                "market": market,
                "symbol": symbol,
                "snapshots": len(values),
                "median_notional_within_5bps_usd": round(median_notional, 4),
                "absorbs_quote_size": median_notional >= quote_size_usd,
                "quote_size_usd": quote_size_usd,
            }
        )
    return {
        "hypothesis": "E-03",
        "rows": rows,
        "capacity_ok_for_all": all(row["absorbs_quote_size"] for row in rows) if rows else None,
        "note": (
            "spot depth snapshots are rare in this capture, so a spot capacity claim rests "
            "on a small number of observations and is reported as such"
        ),
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09E — experiments",
        "",
        f"*Run at `{payload['run_utc']}`. Streams: {payload['streams']}. "
        "`promotion: NONE`, `order_sent: False`.*",
        "",
        "## 1. E-01 — quote imbalance against the measured barrier",
        "",
        "`gross` is the **long-only** mean forward move of the high-imbalance quartile, the only "
        "direction this runtime's spot product can take.",
        "",
        "| Market | Symbol | Horizon (s) | n | IC | Long-only gross (bps) | Spread (bps) | Hit rate | Barrier (bps) | Verdict |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for cell in payload["experiments"]["E-01_imbalance"]:
        stats = cell["stats"] or {}
        lines.append(
            f"| {cell['market']} | {cell['symbol']} | {cell['horizon_seconds']} | {cell['n']} | "
            f"{cell['ic']} | {stats.get('long_only_mean_bps')} | {stats.get('spread_bps')} | "
            f"{stats.get('high_set_hit_rate')} | {cell['verdict']['cost_bps']} | "
            f"**{cell['verdict']['classification']}** |"
        )
    lines += [
        "",
        "## 2. E-07 — negative control (the same pipeline, feature destroyed)",
        "",
        "| Market | Symbol | Horizon (s) | IC | Long-only gross (bps) | Verdict |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for cell in payload["experiments"]["E-07_negative_control"]:
        stats = cell["stats"] or {}
        lines.append(
            f"| {cell['market']} | {cell['symbol']} | {cell['horizon_seconds']} | {cell['ic']} | "
            f"{stats.get('long_only_mean_bps')} | **{cell['verdict']['classification']}** |"
        )
    lines += [
        "",
        "## 3. E-05 — opportunities per day against the ACTIVE objective",
        "",
        "`long-only` counts moves a spot book could take; `any direction` also counts downward "
        "moves, which this runtime cannot execute and which are reported only for the record. "
        "Each row is the sum over streams of a per-day rate that was extrapolated from hours of "
        "capture, so it is an upper bound and not a day count.",
        "",
        "| Horizon (s) | Streams | Span (h, min-max) | Long-only opp/day | Any-direction opp/day | ACTIVE target | Meets it |",
        "| ---: | ---: | --- | ---: | ---: | ---: | :-: |",
    ]
    for row in payload["frequency_pooled"]:
        lines.append(
            f"| {row['horizon_seconds']} | {row.get('streams_summed')} | "
            f"{row.get('hours_min')}-{row.get('hours_max')} | "
            f"{row.get('opportunities_per_day')} | "
            f"{row.get('opportunities_per_day_any_direction')} | "
            f"{row.get('active_target_per_day')} | {row.get('meets_target')} |"
        )
    lines += [
        "",
        "| Market | Symbol | Horizon (s) | Selector | Selected/day | Clearing/day (long-only) |",
        "| --- | --- | ---: | --- | ---: | ---: |",
    ]
    for cell in payload["experiments"]["E-05_frequency"]:
        selector = str(cell.get("selector")).replace("|", "\\|")
        lines.append(
            f"| {cell['market']} | {cell['symbol']} | {cell['horizon_seconds']} | "
            f"{selector} | {cell.get('selected_per_day')} | "
            f"{cell.get('opportunities_per_day')} |"
        )
    lines += [
        "",
        "## 4. E-06 — what a taker actually pays",
        "",
        "| Market | Symbol | Observations | Median shortfall (bps) | Mean (bps) | p90 (bps) |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for cell in payload["experiments"]["E-06_execution"]:
        lines.append(
            f"| {cell['market']} | {cell['symbol']} | {cell['observations']} | "
            f"{cell.get('median_shortfall_bps')} | {cell.get('mean_shortfall_bps')} | "
            f"{cell.get('p90_shortfall_bps')} |"
        )
    lines += [
        "",
        "## 5. E-04 — price against open interest (5-minute clock)",
        "",
        "| Symbol | States | PRICE_DOWN_OI_UP n / mean (bps) | PRICE_UP_OI_UP n / mean |",
        "| --- | ---: | --- | --- |",
    ]
    for cell in payload["experiments"]["E-04_oi_quadrant"]:
        down_up = cell["cells"].get("PRICE_DOWN_OI_UP", {})
        up_up = cell["cells"].get("PRICE_UP_OI_UP", {})
        lines.append(
            f"| {cell['symbol']} | {cell.get('states')} | {down_up.get('n')} / "
            f"{down_up.get('mean_bps')} | {up_up.get('n')} / {up_up.get('mean_bps')} |"
        )
    lines += [
        "",
        "## 6. E-02 — is the fee schedule what blocks the edge?",
        "",
        "| Scenario | Venue | Assets | Cheapest round trip (bps) | Net at best gross | Clears cost |",
        "| --- | --- | ---: | ---: | ---: | :-: |",
    ]
    for row in payload["venue_comparison"]["scenarios"]:
        lines.append(
            f"| `{row['scenario']}` | {row['venue']} | {row['assets_compared']} | "
            f"{row['cheapest_round_trip_bps']} | {row['net_at_best_gross_bps']} | "
            f"{row['clears_cost']} |"
        )
    lines += [
        "",
        "## 7. E-03 — capacity at the quoted size",
        "",
        "| Market | Symbol | Snapshots | Median notional within 5 bps (USD) | Absorbs 1,000 USD |",
        "| --- | --- | ---: | ---: | :-: |",
    ]
    for row in payload["capacity"]["rows"]:
        lines.append(
            f"| {row['market']} | {row['symbol']} | {row['snapshots']} | "
            f"{row['median_notional_within_5bps_usd']} | {row['absorbs_quote_size']} |"
        )
    lines += [
        "",
        "## 8. Verdicts",
        "",
        "| Hypothesis | Track | Classification | Failed filter | Why |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["registry"]:
        lines.append(
            f"| `{row['id']}` | {row['track']} | **{row['classification']}** | "
            f"{row['failed_filter']} | {row['reason']} |"
        )
    lines += [
        "",
        f"`FALSE_SUCCESS` guard: the negative control ended "
        f"**{payload['negative_control_classification']}**; "
        f"`false_success = {payload['false_success']}`.",
        "",
        f"`promotion: {payload['promotion']}`, `order_sent: {payload['order_sent']}`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    from datetime import UTC, datetime

    series_map = read_panel_map(PANEL_DIR / "PANEL_SECONDS.csv")
    oi_samples = read_oi(PANEL_DIR / "OI_SAMPLES.csv")
    depth_rows = read_depth(PANEL_DIR / "DEPTH_SNAPSHOTS.csv")
    gate_payload = json.loads(GATES_JSON.read_text(encoding="utf-8"))

    barriers: dict[tuple[str, str], float] = {
        tuple(key.split("|")): value for key, value in gate_payload["admission_barrier_bps"].items()
    }
    results = experiments.run_all(series_map, barriers=barriers, oi_samples=oi_samples)

    cells = [cell for cell in results["E-01_imbalance"] if cell["stats"]]
    best_gross = max(cell["stats"]["long_only_mean_bps"] for cell in cells) if cells else None
    venue = venue_comparison(gate_payload["barriers"], best_gross)
    capacity = capacity_verdict(gate_payload["capacity"], gates.QUOTE_SIZE_USD)

    negative = [cell["verdict"]["classification"] for cell in results["E-07_negative_control"]]
    false_success = sum(1 for value in negative if value == "ADMIT_RESEARCH")

    # E-05 is judged per horizon on the pooled long-only rate: the ACTIVE
    # objective is stated for the aggregate universe, and summing the horizons
    # together would count the same tape several times.
    pooled = experiments.pool_frequency(results["E-05_frequency"])
    pooled_by_horizon = {row["horizon_seconds"]: row for row in pooled}
    frequency_verdict = experiments.frequency_classification(pooled)
    for cell in results["E-05_frequency"]:
        row = pooled_by_horizon.get(cell["horizon_seconds"]) or {}
        per_horizon = row.get("opportunities_per_day")
        cell["pooled_opportunities_per_day"] = per_horizon
        cell["verdict"] = (
            {
                "classification": "FREQUENCY_KILLED",
                "failed_filter": "F5",
                "reason": (
                    f"the aggregate universe offers {per_horizon} long-only "
                    f"barrier-clearing opportunities/day at this horizon, below the ACTIVE "
                    f"target of {ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY}"
                ),
                "n": cell.get("selected") or 0,
                "promotion": "NONE",
            }
            if per_horizon is not None and per_horizon < ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY
            else {
                "classification": "OBSERVED" if per_horizon is not None else "INSUFFICIENT_SAMPLE",
                "failed_filter": "—",
                "reason": (
                    f"the aggregate universe offers {per_horizon} long-only "
                    f"barrier-clearing opportunities/day at this horizon, so frequency is not "
                    f"what blocks a book at this clock"
                    if per_horizon is not None
                    else "no measurable span at this horizon"
                ),
                "n": cell.get("selected") or 0,
                "promotion": "NONE",
            }
        )

    registry: list[dict[str, Any]] = []
    for hypothesis in HYPOTHESES:
        classification = "OBSERVED"
        failed = "—"
        reason = ""
        if hypothesis.id == "E-01":
            ranked = sorted(
                results["E-01_imbalance"], key=lambda cell: _rank(cell["verdict"]["classification"])
            )
            best = max(
                (cell for cell in results["E-01_imbalance"] if cell["stats"]),
                key=lambda cell: cell["stats"]["long_only_mean_bps"],
                default=ranked[0],
            )
            classification = best["verdict"]["classification"]
            failed = best["verdict"]["failed_filter"]
            counts: dict[str, int] = {}
            for cell in results["E-01_imbalance"]:
                value = cell["verdict"]["classification"]
                counts[value] = counts.get(value, 0) + 1
            reason = (
                f"best measured cell {best['market']}/{best['symbol']} "
                f"h={best['horizon_seconds']}s gross "
                f"{best['stats']['long_only_mean_bps'] if best['stats'] else None} bps vs "
                f"{best['verdict']['cost_bps']} bps barrier — {best['verdict']['reason']} "
                f"(cells: {counts})"
            )
        elif hypothesis.id == "E-02":
            classification = "COST_KILLED" if venue["falsified"] else "OBSERVED"
            failed = "F2"
            cheapest = min(
                (row for row in venue["scenarios"]),
                key=lambda row: row["cheapest_round_trip_bps"],
                default=None,
            )
            reason = (
                f"the cheapest registered schedule ({cheapest['scenario']} at "
                f"{cheapest['cheapest_round_trip_bps']} bps) still exceeds the best measured "
                f"gross ({best_gross} bps): the fee schedule is not the only constraint"
                if cheapest
                else "no scenario priced"
            )
        elif hypothesis.id == "E-03":
            classification = "OBSERVED" if capacity["capacity_ok_for_all"] else "CAPACITY_KILLED"
            failed = "F4"
            reason = capacity["note"]
        elif hypothesis.id == "E-04":
            entry = max(
                results["E-04_oi_quadrant"],
                key=lambda cell: cell["cells"].get("PRICE_DOWN_OI_UP", {}).get("mean_bps") or -999,
                default=None,
            )
            if entry is None or not entry["cells"]:
                classification, reason = "NO_VIABLE_DATA", "no forward open-interest samples"
            else:
                best_cell = entry["cells"].get("PRICE_DOWN_OI_UP", {})
                classification = (
                    "INSUFFICIENT_SAMPLE" if (best_cell.get("n") or 0) < 500 else "OBSERVED"
                )
                reason = (
                    f"PRICE_DOWN_OI_UP n={best_cell.get('n')} mean={best_cell.get('mean_bps')} bps "
                    f"against a barrier of {gate_payload['admission_barrier_bps'].get('perp|ETHUSDT')} bps"
                )
        elif hypothesis.id == "E-05":
            classification = frequency_verdict["classification"]
            failed = frequency_verdict["failed_filter"]
            reason = frequency_verdict["reason"]
        elif hypothesis.id == "E-06":
            measured = [
                cell["median_shortfall_bps"]
                for cell in results["E-06_execution"]
                if cell.get("median_shortfall_bps")
            ]
            classification = "OBSERVED"
            reason = (
                f"median measured taker shortfall {round(statistics.median(measured), 4)} bps "
                "against the modelled spread+impact components"
                if measured
                else "no prints to measure against"
            )
        elif hypothesis.id == "E-07":
            classification = (
                "NO_GROSS_EDGE"
                if all(
                    value
                    in ("NO_GROSS_EDGE", "NO_INFORMATION", "COST_KILLED", "INSUFFICIENT_SAMPLE")
                    for value in negative
                )
                else "ADMIT_RESEARCH"
            )
            reason = f"negative control verdicts: {sorted(set(negative))}"
        registry.append(
            {
                **hypothesis.as_dict(),
                "classification": classification,
                "failed_filter": failed,
                "reason": reason,
                "promotion": "NONE",
            }
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09E",
        "run_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "streams": len(series_map),
        "grid_seconds": gate_payload["grid_seconds"],
        "barriers": gate_payload["admission_barrier_bps"],
        "experiments": results,
        "frequency_pooled": pooled,
        "venue_comparison": venue,
        "capacity": capacity,
        "registry": registry,
        "negative_control_classification": sorted(set(negative)),
        "false_success": false_success,
        "promotion": "NONE",
        "order_sent": False,
        "depth_snapshots_read": len(depth_rows),
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "EXPERIMENTS.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUTDIR / "EXPERIMENTS.md").write_text(render(payload), encoding="utf-8")
    (OUTDIR / "EXPERIMENT_REGISTRY.json").write_text(
        json.dumps({"registry": registry}, indent=2) + "\n", encoding="utf-8"
    )
    (OUTDIR / "EXPERIMENT_REGISTRY.md").write_text(
        "\n".join(
            ["# WP-EDGE-09E — experiment registry", ""]
            + [
                f"- **{row['id']}** ({row['track']}) — {row['title']}: "
                f"**{row['classification']}** — {row['reason']}"
                for row in registry
            ]
            + ["", "Rejected hypotheses and the negative control are registered here too.", ""]
        ),
        encoding="utf-8",
    )

    print(f"streams {len(series_map)}  best long-only gross {best_gross} bps")
    for row in pooled:
        print(
            f"  horizon {row['horizon_seconds']:>4}s  long-only "
            f"{row.get('opportunities_per_day')}/day  "
            f"any-direction {row.get('opportunities_per_day_any_direction')}/day  "
            f"meets={row.get('meets_target')}"
        )
    print(f"E-05 {frequency_verdict['classification']}")
    print(f"negative control {sorted(set(negative))}  false_success={false_success}")
    for row in registry:
        print(f"  {row['id']:<4} {row['classification']:<20} {row['reason'][:90]}")
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)}/EXPERIMENTS.{{json,md}}")
    return 0


def _rank(classification: str) -> int:
    """Order classifications from the most promising to the least."""
    order = [
        "ADMIT_RESEARCH",
        "FREQUENCY_KILLED",
        "CAPACITY_KILLED",
        "COST_KILLED",
        "OBSERVED",
        "NO_GROSS_EDGE",
        "NO_INFORMATION",
        "INSUFFICIENT_SAMPLE",
        "LIMITED_HISTORY",
        "NO_VIABLE_DATA",
        "NON_EXECUTABLE_UNDER_RUNTIME",
    ]
    return order.index(classification) if classification in order else len(order)


if __name__ == "__main__":
    raise SystemExit(main())
