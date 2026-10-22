#!/usr/bin/env python
"""WP-EDGE-08D — the economic matrix on the known universe.

Nine arms (six proposed, three frozen CURRENT books), three windows, three cost scenarios, one
corpus, one risk policy and one simulator. Alongside the money each cell carries the readings a
verdict is computed from — block-bootstrap intervals, the three time blocks, per-asset and
per-market-context breakdowns, leave-out-largest, serial dependence and the frequency — and each
arm carries its own cost sensitivity: what ``2X_FEES`` and ``ADVERSE`` did to it.

The ground is the known universe, which every earlier work package has read. That is deliberate:
this document is the *estate* reading and the CURRENT-vs-PROPOSED baseline, not evidence. The
evidence is the cross-section, and it is read once, in ``scripts/edge08_validate.py``.

Usage::

    python scripts/edge08_economics.py            # runs every arm, writes the matrix
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge08.artifacts import stamp, write_json, write_trades_csv  # noqa: E402
from trading_bot.research.edge08.books import (  # noqa: E402
    CURRENT_ARMS,
    DECLARED_PARAMS,
    PROPOSED_ARMS,
    build_current,
    build_proposed,
    params_hash,
)
from trading_bot.research.edge08.economics import (  # noqa: E402
    compare_arms,
    cost_sensitivity,
    gate_status,
    run_arm_cells,
)
from trading_bot.research.edge08.registration import (  # noqa: E402
    MULTIPLICITY,
    SCHEMA_VERSION,
    WINDOWS,
    WP,
)
from trading_bot.research.edge08.runner import COST_SCENARIOS  # noqa: E402
from trading_bot.research.edge08.universe import known_corpus  # noqa: E402

OUTDIR = WP / "economics"


def scope_of(arm: str) -> dict[str, Any]:
    if arm in PROPOSED_ARMS:
        return PROPOSED_ARMS[arm]
    return CURRENT_ARMS[arm]


def build() -> dict[str, Any]:
    scopes = {arm: scope_of(arm) for arm in list(PROPOSED_ARMS) + list(CURRENT_ARMS)}
    timeframes = sorted({scope["timeframe"] for scope in scopes.values()})
    corpora = {timeframe: known_corpus(timeframe) for timeframe in timeframes}
    books = {
        **build_proposed(corpora[timeframes[0]].bars_by_asset),
        **build_current(corpora[timeframes[0]].bars_by_asset),
    }

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-08D",
        "as_of_utc": stamp(),
        "ground": "the known universe (BTC/ETH/SOL) — read many times; this is the estate reading",
        "costs": {"model": "COST_MODEL_V3", "scenarios": list(COST_SCENARIOS)},
        "windows": {name: dict(window) for name, window in WINDOWS.items()},
        "multiplicity": dict(MULTIPLICITY),
        "arms": {},
        "promotion": "NONE",
        "order_sent": False,
    }

    trade_rows: list[dict[str, Any]] = []
    matrices: dict[str, dict[str, Any]] = {}
    for arm, scope in sorted(scopes.items()):
        timeframe = scope["timeframe"]
        cells = run_arm_cells(
            arm_id=arm,
            track=str(scope.get("track") or "CURRENT"),
            book=books[arm],
            corpus=corpora[timeframe],
            timeframe=timeframe,
            horizon_minutes=float(scope["horizon_minutes"]),
            windows=WINDOWS,
        )
        matrices[arm] = {"cells": cells}
        sensitivity = cost_sensitivity(cells)
        payload["arms"][arm] = {
            "track": scope.get("track") or "CURRENT",
            "timeframe": timeframe,
            "horizon_minutes": scope["horizon_minutes"],
            "source": scope.get("source") or "this work package",
            "answers": scope.get("answers") or scope.get("already"),
            "params": dict(DECLARED_PARAMS.get(arm) or {}),
            "params_hash": params_hash(dict(DECLARED_PARAMS[arm]))
            if arm in DECLARED_PARAMS
            else None,
            "cost_sensitivity": sensitivity,
            "gate_status": gate_status(cells=cells, window_label="known universe"),
            "cells": cells,
        }
        for window, scenarios in cells.items():
            for trade in scenarios["BASE"].get("trade_rows", []):
                trade_rows.append(
                    {
                        **trade,
                        "arm": arm,
                        "track": scope.get("track") or "CURRENT",
                        "window": window,
                        "scenario": "BASE",
                    }
                )
        print(
            f"  {arm:<36} DEV net {cells['DEV']['BASE']['net_usdt']}  "
            f"OOS net {cells['OOS']['BASE']['net_usdt']}"
        )

    payload["comparison"] = compare_arms(
        matrices=matrices,
        proposed=tuple(sorted(PROPOSED_ARMS)),
        current=tuple(sorted(CURRENT_ARMS)),
    )
    # Trade rows travel to the CSV, not into the JSON: the matrix is a summary document, and a
    # copy of every trade row inside it would double the bytes of the package for nothing.
    stripped = 0
    for entry in payload["arms"].values():
        for scenarios in entry["cells"].values():
            for cell in scenarios.values():
                stripped += len(cell.pop("trade_rows", []) or [])
    payload["trade_rows_written_to_csv"] = stripped
    write_json(OUTDIR / "ECONOMIC_MATRIX.json", payload)
    write_trades_csv(OUTDIR / "ECONOMIC_TRADES.csv", trade_rows)
    (OUTDIR / "ECONOMIC_MATRIX.md").write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08D — the economic matrix",
        "",
        f"*Read at `{payload['as_of_utc']}` (`{payload['schema_version']}`). Ground: "
        f"{payload['ground']}.*",
        "",
        "Cost model `COST_MODEL_V3`, scenarios " + ", ".join(payload["costs"]["scenarios"]),
        " — derived from the plane's own components, never from fresh assumptions.",
        "",
        "## 1. The whole matrix, one line per arm and window",
        "",
        "| Arm | Track | Window | Trades | Gross | Net | Expectancy | Net @2x fees | Net @adverse |"
        " PF | DD % | Sharpe | Cost bps/trade | Trades/day |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        for window in ("DEV", "VAL", "OOS"):
            cells = entry["cells"].get(window) or {}
            base = cells.get("BASE") or {}
            stress = cells.get("2X_FEES") or {}
            adverse = cells.get("ADVERSE") or {}
            lines.append(
                f"| `{arm}` | {entry['track']} | {window} | {base.get('trades')} | "
                f"{base.get('gross_usdt')} | **{base.get('net_usdt')}** | "
                f"{base.get('expectancy_usdt')} | {stress.get('net_usdt')} | "
                f"{adverse.get('net_usdt')} | {base.get('profit_factor')} | "
                f"{base.get('max_drawdown_pct')} | {base.get('sharpe_annualised')} | "
                f"{base.get('total_cost_bps_per_trade')} | "
                f"{(base.get('frequency') or {}).get('trades_per_day_universe')} |"
            )
    lines += [
        "",
        "`ECONOMIC_TRADES.csv` carries every BASE trade of every cell, with its asset, its regime,",
        "its cost components and its exit reason.",
        "",
        "## 2. Cost sensitivity, per arm",
        "",
        "| Arm | Base net | 2x fees | Adverse | Survives 2x | Survives adverse | Cost bps/trade",
        " (base → 2x) | Margin left/trade |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        margin = entry["cost_sensitivity"]["margin"]
        lines.append(
            f"| `{arm}` | {margin['base_net_usdt']} | {margin['two_x_fees_net_usdt']} | "
            f"{margin['adverse_net_usdt']} | {margin['survives_two_x_fees']} | "
            f"{margin['survives_adverse']} | {margin['base_cost_bps_per_trade']} → "
            f"{margin['two_x_fees_cost_bps_per_trade']} | "
            f"{margin['net_per_trade_left_at_base_usdt']} |"
        )
    lines += [
        "",
        "## 3. Robustness readings, per arm (BASE, on the decisive window)",
        "",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        base = (entry["cells"].get("OOS") or {}).get("BASE") or {}
        if not base:
            continue
        readings = base.get("serial_dependence") or {}
        blocks = base.get("time_blocks") or []
        lines += [
            f"### `{arm}` — {entry['answers']}",
            "",
            f"- Clock `{entry['timeframe']}`, horizon {entry['horizon_minutes']:.0f} min"
            + (f", params hash `{entry['params_hash'][:16]}…`" if entry.get("params_hash") else "")
            + ".",
            f"- Expectancy interval (90 %, block bootstrap): {base.get('expectancy_ci_90_usdt')}; "
            f"net interval: {base.get('net_ci_90_usdt')}.",
            f"- Time blocks: {base.get('positive_time_blocks')} of 3 positive — "
            + "; ".join(
                f"block {block['block']} {block['trades']} trades, net {block['net_usdt']}"
                for block in blocks
            )
            + ".",
            f"- Largest winner removed: {base.get('with_the_largest_winner_removed')}.",
            f"- Serial dependence: lag-1 {readings.get('lag1_autocorrelation')} against a "
            f"±{readings.get('band_2_over_sqrt_n')} band; runs z={readings.get('runs_z')}.",
            f"- Exits: {base.get('exit_reason_mix')}; frequency "
            f"{(base.get('frequency') or {}).get('trades_per_day_universe')} trades/day across the "
            f"universe, mean hold "
            f"{(base.get('frequency') or {}).get('mean_hold_hours')} h.",
            f"- Frozen gate with OOS := this window: {entry['gate_status']['verdict']} — "
            + "; ".join(entry["gate_status"]["reasons"] or []),
            "",
            "| Asset | Trades | Net | Expectancy |",
            "| --- | --- | --- | --- |",
        ]
        for asset, row in sorted((base.get("by_asset_detail") or {}).items()):
            lines.append(
                f"| {asset} | {row['trades']} | {row['net_usdt']} | {row['expectancy_usdt']} |"
            )
        lines += ["", "| Market context | Trades | Net | Expectancy |", "| --- | --- | --- | --- |"]
        for label, row in sorted((base.get("by_market_context_detail") or {}).items()):
            lines.append(
                f"| {label} | {row['trades']} | {row['net_usdt']} | {row['expectancy_usdt']} |"
            )
        lines.append("")
    lines += ["## 4. CURRENT vs PROPOSED", ""]
    for window, block in payload["comparison"].items():
        if window == "note":
            continue
        lines += [
            f"### {window}",
            "",
            "| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day | Cost bps |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in block["rows"]:
            lines.append(
                f"| {row['group']} | `{row['arm']}` | {row['trades']} | {row['net_usdt']} | "
                f"{row['expectancy_usdt']} | {row['profit_factor']} | {row['max_drawdown_pct']} | "
                f"{row['trades_per_day_universe']} | {row['cost_bps_per_trade']} |"
            )
        lines.append("")
    lines += [payload["comparison"]["note"] + ".", "", "## 5. What this matrix is not", ""]
    lines += [
        "- It is not evidence: the ground is a universe every earlier work package has read. The "
        "evidence of this work package is the cross-section, read once, in `validation/`.",
        "- It promotes nothing: `promotion: NONE`, `order_sent: false`.",
        "- The frozen gate shown per arm is the yardstick earlier work packages were judged by, "
        "reported for comparability with `OOS` := this corpus's OOS window.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    build()
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)} (ECONOMIC_MATRIX.json/md, ECONOMIC_TRADES.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
