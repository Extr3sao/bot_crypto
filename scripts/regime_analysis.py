"""D-05 regime-conditional analysis (STRATEGY-DISCOVERY-V3).

Pre-registered in docs/STRATEGY_DISCOVERY_V3.md BEFORE results:
  regime definition (PIT, no lookahead):
    vol_now  = std of the last 100 bar log-returns ending at the signal bar
    regime   = HIGH if vol_now >= median(vol_now over trailing 720 bars) else LOW
  cells (12): {trend, mean_reversion, volatility} x {15m, 30m} x {HIGH, LOW}
  cell gate: ZERO_COST gross bps/trade > 12 on DEV (W1-W4) with n_DEV >= 30,
  and ZERO gross > 0 on VAL (W5-W6). OOS checked only for cells passing the
  gate. ZERO_COST is diagnostic (edge measurement); admission would still
  require BASE-cost survival per docs/STRATEGY_ADMISSION_CRITERIA.md.

Reads TRADES_<fam>_<tf>.csv dumps (DUMP_TRADES=1, DATASET_TF) produced by
multi_family_backtest.py. Writes reports/strategy-baseline/REGIME_ANALYSIS.json.
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")

FAMS = ["trend", "mean_reversion", "volatility"]
TFS = ["15m", "30m"]
ASSET_IDX = {"BTCUSDT": 0, "ETHUSDT": 1, "SOLUSDT": 2}


def load_regimes(tf: str) -> tuple[dict[str, dict[str, dict[int, str]]], dict[str, dict[str, dict[int, int]]]]:
    """Return {(window, sym): {bar_index: regime}}, {(window, sym): {ts: bar_index}}."""
    suffix = f"_5m_{tf}"
    regimes: dict[str, dict[str, dict[int, str]]] = {}
    ts_index: dict[str, dict[str, dict[int, int]]] = {}
    for f in sorted(glob.glob(os.path.join(DATA, f"*{suffix}.json"))):
        base = os.path.basename(f)[: -len(suffix) - 5]
        sym, window = base.split("_", 1)
        with open(f, encoding="utf-8") as fh:
            bars = json.load(fh)
        closes = [b["close"] for b in bars]
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        vols: list[float] = [0.0]
        for i in range(1, len(rets) + 1):
            if i < 100:
                vols.append(0.0)
                continue
            w = rets[i - 100: i]
            mu = sum(w) / 100.0
            vols.append((sum((x - mu) ** 2 for x in w) / 100.0) ** 0.5)
        reg: dict[int, str] = {}
        for i in range(100, len(vols)):
            hist = vols[max(0, i - 720): i]
            med = sorted(hist)[len(hist) // 2]
            reg[i] = "HIGH" if vols[i] >= med else "LOW"
        regimes.setdefault(window, {})[sym] = reg
        ts_index.setdefault(window, {})[sym] = {b["ts"]: i for i, b in enumerate(bars)}
    return regimes, ts_index


def bps(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    gross = sum(float(t["gross"]) for t in trades)
    return 10000.0 * gross / (len(trades) * 500.0)


def pf(trades: list[dict[str, Any]]) -> float | None:
    wins = sum(t["net"] for t in trades if t["net"] > 0)
    losses = -sum(t["net"] for t in trades if t["net"] <= 0)
    if losses <= 0:
        return None
    return round(float(wins) / float(losses), 4)


def main() -> None:
    results: dict[str, Any] = {"meta": {"regime_def": "vol100 vs trailing-720 median (PIT)",
                                        "cells": len(FAMS) * len(TFS) * 2,
                                        "gate": "ZERO gross>12bps DEV n>=30 & ZERO VAL gross>0"}}
    passing: list[str] = []
    for fam in FAMS:
        for tf in TFS:
            path = os.path.join(OUTDIR, f"TRADES_{fam}_{tf}.csv")
            key = f"{fam}_{tf}"
            if not os.path.exists(path):
                results[key] = {"error": "missing trade dump"}
                continue
            regimes, ts_index = load_regimes(tf)
            rows: list[dict[str, str]] = []
            with open(path, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            buckets: dict[str, dict[str, list[dict[str, Any]]]] = {
                reg: {"DEV": [], "VAL": [], "OOS": []} for reg in ("HIGH", "LOW")}
            skipped = 0
            for r in rows:
                window = str(r["window"]).split("_5m_")[0]  # CSV carries the tf suffix
                wi = window.split("_")[0]
                sym = str(r["asset"]).replace("/USDT", "USDT")
                reg_map = regimes.get(window, {}).get(sym)
                idx_map = ts_index.get(window, {}).get(sym)
                if reg_map is None or idx_map is None:
                    skipped += 1
                    continue
                i = idx_map.get(int(r["exit_ts"]))
                if i is None or i not in reg_map:
                    skipped += 1
                    continue
                split = "DEV" if wi in ("W1", "W2", "W3", "W4") else ("VAL" if wi in ("W5", "W6") else "OOS")
                buckets[reg_map[i]][split].append({
                    "gross": float(r["gross"]), "net": float(r["net"]),
                    "mfe": float(r["mfe_pct"]), "mae": float(r["mae_pct"])})
            cell: dict[str, Any] = {"skipped_rows": skipped}
            for reg in ("HIGH", "LOW"):
                dev, val, oos = (buckets[reg]["DEV"], buckets[reg]["VAL"], buckets[reg]["OOS"])
                zero_dev = [t for t in dev if True]  # dump already ZERO_COST-scenario only
                stats = {
                    "DEV": {"n": len(zero_dev), "gross_bps": round(bps(zero_dev), 2)},
                    "VAL": {"n": len(val), "gross": round(sum(t["gross"] for t in val), 2)},
                    "OOS": {"n": len(oos), "gross_bps": round(bps(oos), 2)},
                }
                gate = stats["DEV"]["n"] >= 30 and stats["DEV"]["gross_bps"] > 12.0 and stats["VAL"]["gross"] > 0
                stats["gate_pass"] = gate
                cell[reg] = stats
                if gate:
                    passing.append(f"{key}:{reg}")
            results[key] = cell
    results["passing_cells"] = passing
    with open(os.path.join(OUTDIR, "REGIME_ANALYSIS.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(json.dumps(results["passing_cells"]))
    for key in results:
        if key in ("meta", "passing_cells"):
            continue
        cell = results[key]
        if "error" in cell:
            print(key, cell["error"])
            continue
        for reg in ("HIGH", "LOW"):
            s = cell[reg]
            print(f"{key:28s} {reg:4s} DEV n={s['DEV']['n']:4d} bps={s['DEV']['gross_bps']:7.2f} "
                  f"| VAL n={s['VAL']['n']:4d} gross={s['VAL']['gross']:8.2f} "
                  f"| OOS n={s['OOS']['n']:4d} bps={s['OOS']['gross_bps']:7.2f} gate={s['gate_pass']}")


if __name__ == "__main__":
    main()
