"""Transaction-cost barrier quantification (STRATEGY-DISCOVERY-V3 section 5).

Answers: what is the minimum edge a signal must have to survive the current
cost model, expressed in comparable units (bps, %, ATR multiples) per
asset and per timeframe? Uses the cached datasets (no network).

Cost model (pre-registered, docs/STRATEGY_ADMISSION_CRITERIA.md era):
  fees 5 bps/side, slippage 1 bp/side -> 12 bps round-trip (BASE)
  2X_COST = 24 bps; STRESSED_SLIPPAGE = 5x slip = 32 bps

Metrics per (asset, timeframe):
  realized vol per bar (close-to-close, annualized for reference)
  ATR14 as % of price (mean)
  bars needed for a move equal to the round-trip cost (median)
  wall-clock time implied by that bar count (hours)
Interpretation: a signal whose mean favorable excursion is smaller than the
round-trip cost cannot be net-positive regardless of exit engineering.

Pure read-only analysis script: prints a table and writes
reports/strategy-baseline/COST_BARRIER.json.
"""

from __future__ import annotations

import glob
import json
import os
from statistics import mean, median
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")

SCENARIOS = {"BASE": 12.0, "2X_COST": 24.0, "STRESSED": 32.0}  # round-trip bps
TFS: dict[str, float] = {"5m": 5.0, "15m": 15.0, "30m": 30.0, "1h": 60.0}


def atr_pct(bars: list[dict[str, Any]], period: int = 14) -> list[float]:
    out: list[float] = []
    for i in range(period, len(bars)):
        tr = max(bars[i]["high"] - bars[i]["low"],
                 abs(bars[i]["high"] - bars[i - 1]["close"]),
                 abs(bars[i]["low"] - bars[i - 1]["close"]))
        out.append(tr / bars[i]["close"] * 100.0)
    return out


def analyze(bars: list[dict[str, Any]], tf_min: float) -> dict[str, Any]:
    closes = [b["close"] for b in bars]
    rets = [abs(closes[i] / closes[i - 1] - 1) * 10000.0 for i in range(1, len(closes))]
    a = atr_pct(bars)
    out: dict[str, Any] = {
        "bars": len(bars),
        "abs_ret_bps_median": round(median(rets), 2),
        "atr_pct_mean": round(mean(a), 4) if a else None,
    }
    for name, bps in SCENARIOS.items():
        # bars needed (median case) for an absolute move == round-trip cost
        need = [bps / r for r in rets if r > 0]
        out[f"bars_to_{name}"] = round(median(need), 1) if need else None
        out[f"hours_to_{name}"] = round(median(need) * tf_min / 60.0, 2) if need else None
    return out


def main() -> None:
    results: dict[str, Any] = {"meta": {"cost_model_bps_rt": SCENARIOS,
                                        "note": "bars_to_X = median bars for a move equal to X bps"}}
    for tf, tf_min in TFS.items():
        suffix = "" if tf == "5m" else f"_5m_{tf}"
        files = sorted(glob.glob(os.path.join(DATA, f"*{suffix}.json")))
        per_asset: dict[str, list[list[dict[str, Any]]]] = {}
        for f in files:
            base = os.path.basename(f)[: -len(suffix) - 5] if suffix else os.path.basename(f)[:-5]
            sym = base.split("_", 1)[0].replace("USDT", "")
            with open(f, encoding="utf-8") as fh:
                bars = json.load(fh)
            per_asset.setdefault(sym, []).append(bars)
        results[tf] = {}
        for sym, chunks in sorted(per_asset.items()):
            flat: list[dict[str, Any]] = []
            for c in chunks:
                flat.extend(c)
            results[tf][sym] = analyze(flat, tf_min)
        b = results[tf]
        print(f"{tf}: BTC atr%={b['BTC']['atr_pct_mean']} bars_to_BASE={b['BTC']['bars_to_BASE']} "
              f"(~{b['BTC']['hours_to_BASE']}h) | ETH atr%={b['ETH']['atr_pct_mean']} "
              f"bars_to_BASE={b['ETH']['bars_to_BASE']} | SOL atr%={b['SOL']['atr_pct_mean']} "
              f"bars_to_BASE={b['SOL']['bars_to_BASE']}", flush=True)
    with open(os.path.join(OUTDIR, "COST_BARRIER.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print("-> COST_BARRIER.json")


if __name__ == "__main__":
    main()
