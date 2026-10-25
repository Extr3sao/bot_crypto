#!/usr/bin/env python
"""WP-EDGE-09D — cost, liquidity, capacity and frequency, measured.

    python scripts/edge09_gates.py

Reads the panel built by ``scripts/edge09_panel.py`` and the authoritative cost
model, and publishes ``gates/COST_LIQUIDITY_CAPACITY.{json,md}``. It decides
which hypotheses may proceed to WP-EDGE-09E; it never decides that a strategy
may trade.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09 import gates  # noqa: E402
from trading_bot.research.edge09.registration import (  # noqa: E402
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    SCHEMA_VERSION,
    WP,
)

PANEL_DIR = WP / "panel"
OUTDIR = WP / "gates"


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09D — cost, liquidity, capacity and frequency",
        "",
        f"*Measured on `{payload['streams']}` streams of the forward capture, "
        f"{payload['grid_seconds']} s grid. Cost model: V4 over the V3 venue specs. "
        "`promotion: NONE`.*",
        "",
        "## 1. What the tape itself costs — measured spread",
        "",
        "| Run | Market | Symbol | Observations | Median (bps) | Mean (bps) | p90 (bps) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["spread_by_stream"]:
        lines.append(
            f"| `{row['run']}` | {row['market']} | {row['symbol']} | "
            f"{row['observations']} | {row['median_bps']} | {row['mean_bps']} | "
            f"{row['p90_bps']} |"
        )
    lines += [
        "",
        "## 2. The barrier, per asset and market, on every registered venue",
        "",
        "| Market | Symbol | Scenario | Spread meas. | Round trip (bps) | Required 1.5x (bps) | Fee share |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["barriers"]:
        if "error" in row:
            lines.append(
                f"| {row['market']} | {row['symbol']} | `{row['scenario']}` | — | — | — | "
                f"{row['error']} |"
            )
            continue
        fee = row["components_bps"]["fee"]
        share = fee / row["round_trip_bps"] * 100.0 if row["round_trip_bps"] else 0.0
        lines.append(
            f"| {row['market']} | {row['symbol']} | `{row['scenario']}` | "
            f"{row['spread_observations']} | {row['round_trip_bps']} | "
            f"{row['required_bps']} | {share:.1f}% |"
        )
    lines += [
        "",
        "## 3. Capacity: what the captured book actually offers",
        "",
        f"Order size quoted at **{payload['quote_size_usd']:.0f} USD**; the runtime's own floor for "
        f"an order is {payload['min_order_notional_usdt']:.0f} USDT.",
        "",
        "| Market | Symbol | Snapshots | Levels | Top of book (USD) | 5 bps band (USD) | 25 bps band (USD) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    capacity_by_stream: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in payload["capacity"]:
        capacity_by_stream.setdefault((row["market"], row["symbol"]), []).append(row)

    def median(key: str, stream_rows: list[dict[str, Any]]) -> float:
        values = [row[key] for row in stream_rows if row.get(key) is not None]
        return statistics.median(values) if values else 0.0

    for (market, symbol), rows in sorted(capacity_by_stream.items()):
        lines.append(
            f"| {market} | {symbol} | {len(rows)} | {max(row['levels_kept'] for row in rows)} | "
            f"{median('top_of_book_usd', rows):.2f} | "
            f"{median('bid_notional_within_5.0bps_usd', rows):.2f} | "
            f"{median('bid_notional_within_25.0bps_usd', rows):.2f} |"
        )
    lines += [
        "",
        "## 4. Frequency: the tape's own upper bound",
        "",
        "How often the mid itself moves by at least the admission barrier in the horizon. No "
        "predictor can exceed this: a trade whose move does not clear the barrier cannot pay "
        "for itself. The span column is the capture the per-day rate was extrapolated from, in "
        "hours: this is a rate, not a day count.",
        "",
        "| Horizon (s) | Span (h, min-max) | Streams summed | Barrier-clearing per day | ACTIVE target | Meets it |",
        "| ---: | --- | ---: | ---: | ---: | :-: |",
    ]
    for row in payload["frequency_pooled"]:
        span = "—"
        if row.get("hours_min") is not None:
            span = f"{row['hours_min']}-{row['hours_max']}"
        lines.append(
            f"| {row['horizon_seconds']} | {span} | "
            f"{row.get('streams_summed')} | {row.get('clearing_per_day')} | "
            f"{ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY} | {row.get('meets_target')} |"
        )
    lines += [
        "",
        "## 5. The bar the barrier sets, per stream and horizon",
        "",
        "| Market | Symbol | Horizon (s) | Clearing per day | Barrier (bps) |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload["frequency"]:
        lines.append(
            f"| {row['market']} | {row['symbol']} | {row['horizon_seconds']} | "
            f"{row['clearing_per_day']} | {row['barrier_bps']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    payload = gates.build(PANEL_DIR)
    payload["schema_version"] = SCHEMA_VERSION
    payload["work_package"] = "WP-EDGE-09D"
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "COST_LIQUIDITY_CAPACITY.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (OUTDIR / "COST_LIQUIDITY_CAPACITY.md").write_text(render(payload), encoding="utf-8")
    print(f"streams {payload['streams']}  barriers {len(payload['barriers'])}")
    for key, value in sorted(payload["admission_barrier_bps"].items()):
        print(f"  admission barrier {key:<16} {value} bps")
    for row in payload["frequency_pooled"]:
        print(
            f"  horizon {row['horizon_seconds']:>3}s  clearing/day="
            f"{row.get('clearing_per_day')}  target={ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY}  "
            f"meets={row.get('meets_target')}"
        )
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)}/COST_LIQUIDITY_CAPACITY.{{json,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
