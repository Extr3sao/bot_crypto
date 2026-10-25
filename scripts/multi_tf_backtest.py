"""Multi-TF family backtest (STRATEGY-DISCOVERY-V3 timeframe audit, research only).

Reuses the SAME simulate_family as multi_family_backtest (import, no copy).
Datasets are the deterministic 5m resamples (15m/30m/1h) produced by
resample_baseline_data.py over the same 7 monthly windows — identical
periods to the 5m baseline, so cross-TF comparisons are like-for-like.

Splits/costs/scenarios follow the pre-registered conventions:
  DEV W1-W4, VAL W5-W6, OOS W7; BASE/2X_COST/STRESSED_SLIPPAGE/ZERO_COST.
ZERO_COST is diagnostic only, never admission (docs/STRATEGY_ADMISSION_CRITERIA.md).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any

sys.path.insert(
    0, os.path.dirname(os.path.abspath(__file__))
)  # sibling import (mypy_path includes scripts/)

import multi_family_backtest as M

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")

ALL_TFS: dict[str, float] = {"5m": 5.0, "15m": 15.0, "30m": 30.0, "1h": 60.0}
ALL_SCEN: dict[str, tuple[float, float]] = {
    "BASE": (1.0, 1.0),
    "2X_COST": (2.0, 1.0),
    "STRESSED_SLIPPAGE": (1.0, 5.0),
    "ZERO_COST": (0.0, 0.0),
}


def run_tf(tf: str, scenarios: dict[str, tuple[float, float]] | None = None) -> dict[str, Any]:
    M.TF_MIN = ALL_TFS[tf]
    scenarios = scenarios or ALL_SCEN
    suffix = "" if tf == "5m" else f"_5m_{tf}"
    files = sorted(glob.glob(os.path.join(DATA, f"*{suffix}.json")))
    total_eval_bars = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            total_eval_bars += max(0, len(json.load(fh)) - M.START_EVAL)
    results: dict[str, Any] = {}
    for fam_id in M.FAMILIES:
        results[fam_id] = {}
        for sc, (cm, sm) in scenarios.items():
            all_trades: list[dict[str, Any]] = []
            for f in files:
                base = (
                    os.path.basename(f)[: -len(suffix) - 5] if suffix else os.path.basename(f)[:-5]
                )
                sym, window = base.split("_", 1)
                with open(f, encoding="utf-8") as fh:
                    bars = json.load(fh)
                res = M.simulate_family(fam_id, sym.replace("USDT", "/USDT"), bars, cm, sm)
                for t in res["trades"]:
                    t["window"] = window
                all_trades.extend(res["trades"])
            dev = [t for t in all_trades if t["window"].startswith(("W1", "W2", "W3", "W4"))]
            val = [t for t in all_trades if t["window"].startswith(("W5", "W6"))]
            oos = [t for t in all_trades if t["window"].startswith("W7")]
            results[fam_id][sc] = {
                "totals": M.aggregate(all_trades, total_eval_bars),
                "DEV_W1_W4": M.aggregate(dev),
                "VAL_W5_W6": M.aggregate(val),
                "OOS_W7": M.aggregate(oos),
            }
    return results


def main() -> None:
    tfs = os.environ.get("TFS", "15m,30m,1h").split(",")
    scen_names = os.environ.get("SCEN", "BASE,ZERO_COST").split(",")
    scenarios = {k: ALL_SCEN[k] for k in scen_names}
    out: dict[str, Any] = {
        "meta": {
            "windows": "W1-W7 (2026-03..2026-09-24)",
            "assets": ["BTC", "ETH", "SOL"],
            "note": "research only; same periods as 5m baseline; ZERO_COST diagnostic",
            "tfs": tfs,
            "scenarios": scen_names,
        }
    }
    for tf in tfs:
        print(f"=== TF {tf} ===", flush=True)
        res = run_tf(tf, scenarios)
        out[tf] = res
        for fam_id, fam in res.items():
            b = fam["BASE"]["totals"]
            o = fam["BASE"]["OOS_W7"]
            z = fam["ZERO_COST"]["totals"]
            print(
                f"{fam_id:15s} trades={b['trades']:5d} net={b['net']:9.2f} PF={b['profit_factor']} "
                f"| OOS PF={o['profit_factor']} net={o['net']:8.2f} n={o['trades']:4d} "
                f"| ZERO gross={z['gross']:8.2f}",
                flush=True,
            )
    with open(os.path.join(OUTDIR, "TIMEFRAME_AUDIT.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print("-> TIMEFRAME_AUDIT.json")


if __name__ == "__main__":
    main()
