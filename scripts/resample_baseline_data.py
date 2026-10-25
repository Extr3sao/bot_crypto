"""Fetch OHLCV at higher timeframes for the STRATEGY-DISCOVERY-V3 timeframe audit.

Read-only public Binance REST (market data only, no credentials). Same 7
monthly windows ending 2026-09-24 23:59 as the 5m baseline; paper run
(2026-09-25) stays OUT of every window (clean OOS separation).

Resampling (deterministic, from 5m source bars — no extra API calls):
  15m = 3 x 5m, 30m = 6 x 5m, 1h = 12 x 5m
Bar alignment: UTC epoch buckets (bucket = ts // tf_ms). A bucket is emitted
only when complete (last bucket of each window may be partial -> dropped).
The source 5m data must already exist (fetch_baseline_data.py).
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60}


def resample(bars: list[dict[str, Any]], tf_min: int) -> list[dict[str, Any]]:
    ms = tf_min * 60_000
    bars_per = tf_min // 5  # source is strictly 5m
    out: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    bucket: int | None = None
    for b in bars:
        bk = b["ts"] // ms
        if bucket is None:
            bucket = bk
        if bk != bucket:
            if len(cur) == bars_per:  # complete bucket only
                out.append({"ts": cur[0]["ts"], "open": cur[0]["open"], "high": max(x["high"] for x in cur),
                            "low": min(x["low"] for x in cur), "close": cur[-1]["close"],
                            "volume": sum(x["volume"] for x in cur)})
            cur, bucket = [], bk
        cur.append(b)
    return out


def main() -> None:
    files = sorted(glob.glob(os.path.join(SRC, "*_W*.json")))
    # only the 5m sources (fetch_baseline_data names have no TF infix)
    src = [f for f in files if "_5m_" not in f]
    made = 0
    for f in src:
        base = os.path.basename(f)[:-5]
        with open(f, encoding="utf-8") as fh:
            bars = json.load(fh)
        if not bars or bars[0]["ts"] % 300_000 != 0:
            print("skip non-5m source:", base)
            continue
        for tf, minutes in TF_MIN.items():
            out_path = os.path.join(SRC, f"{base}_5m_{tf}.json")
            if os.path.exists(out_path):
                continue
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(resample(bars, minutes), fh)
            made += 1
        print("resampled", base, flush=True)
    print("done, files written:", made)


if __name__ == "__main__":
    main()
