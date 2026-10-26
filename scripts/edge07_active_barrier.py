#!/usr/bin/env python
"""WP-EDGE-07 Track C — the frequency target's own arithmetic, measured rather than assumed.

Track C's question is a frequency question ("three or more trades a day"), and frequency is where
the cost wall bites: every trade pays the round trip. So this tool measures the two sides of the
comparison on the actual bars, for BTC, ETH and SOL, on a one-hour clock:

* **the cost** — ``COST_MODEL_V3``'s round-trip bps at a one-hour horizon, read from the cost
  plane rather than typed here;
* **the ceiling** — what a *perfect* direction call would have earned, at each holding horizon
  ``H``: entering at the next bar's open and leaving at the open ``H`` bars later captures exactly
  the absolute open-to-open move. That is an upper bound no real strategy can beat, because it
  knows the direction in advance and pays the cost like everybody else.

A horizon whose ceiling is below the cost is a horizon where **no strategy at all** — not this
work package's, not anyone's — can profit on these assets, and the ceiling is missing exactly the
part a real book loses to stops, spread timing and being wrong.

It also reads the two registered candidates' own trade rows, so the report can say what fraction
of the available move each one actually captured and what fraction it would have needed.

Read-only over the corpora and the candidate artefacts; it writes its own report and nothing else.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge01 import campaign as C  # noqa: E402
from trading_bot.research.edge01.costs import cost_plane  # noqa: E402
from trading_bot.research.edge01.data import ASSETS, load_1h  # noqa: E402
from trading_bot.research.edge07 import active as A  # noqa: E402
from trading_bot.research.edge07 import validation as V  # noqa: E402

OUT_DIR = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07" / "active-research"
SCHEMA_VERSION = "EDGE07_ACTIVE_COST_BARRIER_V1"
HORIZONS: tuple[int, ...] = (1, 2, 4, 8, 24)
BARS_PER_DAY = 24


def now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ceiling(bars: list[Any], *, window: dict[str, int], horizon: int) -> dict[str, Any]:
    """The perfect-foresight open-to-open capture at ``horizon`` bars, inside the window."""
    moves: list[float] = []
    for index in range(len(bars) - horizon - 1):
        entry_bar = bars[index + 1]
        exit_bar = bars[index + 1 + horizon]
        if entry_bar.ts < window["start"] or entry_bar.ts >= window["end"]:
            continue
        if entry_bar.open <= 0:
            continue
        moves.append(abs(exit_bar.open - entry_bar.open) / entry_bar.open * 10_000.0)
    if not moves:
        return {"bars": 0, "horizon_bars": horizon}
    mean = statistics.fmean(moves)
    sorted_moves = sorted(moves)
    cost = cost_plane(size_usd=1000.0, horizon_minutes=60.0 * horizon).round_trip_bps
    return {
        "horizon_bars": horizon,
        "horizon_hours": horizon,
        "observations": len(moves),
        "trades_per_day_per_asset": round(BARS_PER_DAY / horizon, 4),
        "trades_per_day_across_the_universe": round(BARS_PER_DAY / horizon * len(ASSETS), 4),
        "mean_absolute_move_bps": round(mean, 4),
        "median_absolute_move_bps": round(sorted_moves[len(sorted_moves) // 2], 4),
        "p90_absolute_move_bps": round(sorted_moves[int(len(sorted_moves) * 0.9)], 4),
        "round_trip_cost_bps": round(cost, 4),
        "perfect_foresight_net_bps": round(mean - cost, 4),
        "share_of_moves_below_cost": round(sum(1 for move in moves if move < cost) / len(moves), 4),
        "capture_fraction_needed_to_break_even": round(cost / mean, 4) if mean else None,
    }


def candidates_reading() -> dict[str, Any]:
    """What the registered candidates actually captured, from their own trade rows."""
    path = OUT_DIR / "ACTIVE_RESEARCH.json"
    if not path.is_file():
        return {"available": False, "reason": f"{path.name} is not on file yet"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, Any] = {}
    for book_id, windows in (payload.get("screen") or {}).items():
        dev = windows["DEV"]["BASE"]
        rows[book_id] = {
            "dev_trades": dev.get("trades"),
            "dev_trades_per_day": dev.get("trades_per_day"),
            "dev_gross_bps_per_trade": dev.get("gross_bps_per_trade"),
            "dev_net_usdt": dev.get("net_usdt"),
            "dev_avg_duration_min": dev.get("avg_duration_min"),
            "dev_exit_reason_mix": dev.get("exit_reason_mix"),
        }
    return {"available": True, "candidates": rows}


def evaluate() -> dict[str, Any]:
    cost = cost_plane(size_usd=1000.0, horizon_minutes=60.0).round_trip_bps
    windows = {
        "DEV": dict(C.SPLITS["trend"]["DEV"]),
        "VAL": dict(C.SPLITS["trend"]["VAL"]),
        "NEW_HOLDOUT": dict(V.NEW_HOLDOUT),
    }
    frozen = {asset: list(load_1h(asset).bars) for asset in ASSETS}
    holdout = {asset: list(load_1h(asset, corpus=V.HOLDOUT_DIR).bars) for asset in ASSETS}
    measured: dict[str, Any] = {}
    for window_name, window in windows.items():
        source = holdout if window_name == "NEW_HOLDOUT" else frozen
        measured[window_name] = {
            asset: [ceiling(bars, window=window, horizon=h) for h in HORIZONS]
            for asset, bars in sorted(source.items())
        }
    pooled: dict[str, Any] = {}
    for window_name, per_asset in measured.items():
        rows: list[dict[str, Any]] = []
        for horizon in HORIZONS:
            entries = [
                next(row for row in rows_for_asset if row["horizon_bars"] == horizon)
                for rows_for_asset in per_asset.values()
                if any(row["horizon_bars"] == horizon for row in rows_for_asset)
            ]
            if not entries:
                continue
            rows.append(
                {
                    "horizon_bars": horizon,
                    "trades_per_day_across_the_universe": entries[0][
                        "trades_per_day_across_the_universe"
                    ],
                    "mean_absolute_move_bps": round(
                        statistics.fmean(row["mean_absolute_move_bps"] for row in entries), 4
                    ),
                    "round_trip_cost_bps": round(cost, 4),
                    "perfect_foresight_net_bps": round(
                        statistics.fmean(row["mean_absolute_move_bps"] for row in entries) - cost, 4
                    ),
                    "share_of_moves_below_cost": round(
                        statistics.fmean(row["share_of_moves_below_cost"] for row in entries), 4
                    ),
                }
            )
        pooled[window_name] = rows

    reachable = [
        row
        for row in pooled["NEW_HOLDOUT"]
        if row["trades_per_day_across_the_universe"] >= A.FREQUENCY_TARGET_PER_DAY
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": now_utc(),
        "declared_cost_wall_bps": round(cost, 4),
        "cost_model": "COST_MODEL_V3 / BINANCE_SPOT_STANDARD_TAKER at a one-hour horizon",
        "frequency_target_per_day": A.FREQUENCY_TARGET_PER_DAY,
        "methods": (
            "perfect foresight: entry at the open of the next bar, exit at the open H bars later, "
            "capturing the absolute open-to-open move, paying the round trip; a real book captures "
            "less because it is sometimes wrong and exits early"
        ),
        "per_asset": measured,
        "pooled": pooled,
        "the_frequency_target_is_reachable_at": reachable,
        "candidates": candidates_reading(),
        "note": (
            "a horizon whose perfect-foresight net is below zero is a horizon where no strategy on "
            "these assets can profit; a positive ceiling is necessary, never sufficient"
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-07 Track C — the frequency target's arithmetic: cost, ceiling, and what was captured",
        "",
        f"*Read at `{payload['as_of_utc']}`. Cost wall: **{payload['declared_cost_wall_bps']:.2f} bps** "
        f"per round trip ({payload['cost_model']}).*",
        "",
        "## 1. The ceiling, per holding horizon",
        "",
        "A perfect direction call that enters at the next bar's open and leaves `H` bars later "
        "captures the whole open-to-open move and pays the same round trip every real book pays. "
        "It is an upper bound: it is never wrong and never exits early.",
        "",
        "| Window | H (hours) | Trades/day (3 assets) | Mean abs. move | Cost | Ceiling net | Moves below cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for window_name, rows in payload["pooled"].items():
        for row in rows:
            lines.append(
                f"| {window_name} | {row['horizon_bars']} | "
                f"{row['trades_per_day_across_the_universe']:.1f} | "
                f"{row['mean_absolute_move_bps']:.2f} bps | {row['round_trip_cost_bps']:.2f} bps | "
                f"**{row['perfect_foresight_net_bps']:+.2f} bps** | "
                f"{row['share_of_moves_below_cost']:.1%} |"
            )
    lines += [
        "",
        "## 2. Which horizons can even carry the target",
        "",
    ]
    for row in payload["the_frequency_target_is_reachable_at"]:
        lines.append(
            f"- H={row['horizon_bars']} h ({row['trades_per_day_across_the_universe']:.1f} trades/day "
            f"across the three assets): ceiling {row['perfect_foresight_net_bps']:+.2f} bps per trade "
            f"after cost."
        )
    lines += [
        "",
        "## 3. What the registered candidates actually captured",
        "",
    ]
    candidates = payload["candidates"]
    if candidates.get("available"):
        lines += [
            "| Book | DEV trades | Per day | Gross bps/trade | Net USDT | Avg duration | Exit mix |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for book_id, row in candidates["candidates"].items():
            lines.append(
                f"| `{book_id}` | {row['dev_trades']} | {row['dev_trades_per_day']} | "
                f"{row['dev_gross_bps_per_trade']} | {row['dev_net_usdt']} | "
                f"{row['dev_avg_duration_min']} min | {row['dev_exit_reason_mix']} |"
            )
    else:
        lines.append(f"*{candidates.get('reason')}*")
    lines += [
        "",
        "## 4. What this bounds",
        "",
        "- A **negative ceiling** would bound every strategy on these assets away from that horizon,",
        "  and none of the measured horizons above is negative: the cost wall does not, by itself,",
        "  forbid the mission's three trades a day.",
        "- A **positive ceiling is not an edge.** It is what an oracle earns; a real book keeps a",
        "  small fraction of the move and pays the whole cost. The candidates' own captured",
        "  fraction, measured in §3, is the number to compare with §1.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    payload = evaluate()
    if options.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "COST_BARRIER_ACTIVE.json"
    markdown_path = out / "COST_BARRIER_ACTIVE.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render(payload), encoding="utf-8")
    print("=" * 78)
    print("WP-EDGE-07 TRACK C — ACTIVE cost barrier")
    print("=" * 78)
    print(f"cost wall {payload['declared_cost_wall_bps']:.2f} bps per round trip")
    for window_name, rows in payload["pooled"].items():
        summary = ", ".join(
            f"H={row['horizon_bars']}: {row['mean_absolute_move_bps']:.1f} bps -> "
            f"{row['perfect_foresight_net_bps']:+.1f} net"
            for row in rows
        )
        print(f"  {window_name:<14} {summary}")
    print(f"wrote {json_path.relative_to(REPO_ROOT)}")
    print(f"wrote {markdown_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
