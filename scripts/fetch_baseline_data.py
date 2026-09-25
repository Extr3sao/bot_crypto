"""Fetch 5m OHLCV for the strategy performance baseline (offline analysis).

Read-only public Binance REST (no credentials, no order API, market data
only). Caches per (asset, window) JSON so re-runs never re-download.

Windows (UTC): 7 monthly windows ending 2026-09-24 23:59 — the paper run
(2026-09-25) stays OUT of every window (clean OOS separation vs V2 paper).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL = "5m"
LIMIT = 1000
MS = 3_000_000  # 5m in ms

WINDOWS: list[tuple[str, int, int, str]] = [
    # name, start_ms, end_ms_exclusive, expected regime tag
    ("W1_2026-03", 1772323200000, 1775001599999, "post-crash recovery"),
    ("W2_2026-04", 1775001600000, 1777593599999, "tbd"),
    ("W3_2026-05", 1777593600000, 1780271999999, "tbd"),
    ("W4_2026-06", 1780272000000, 1782863999999, "tbd"),
    ("W5_2026-07", 1782864000000, 1785542399999, "tbd"),
    ("W6_2026-08", 1785542400000, 1788220799999, "tbd"),
    ("W7_2026-09", 1788220800000, 1790351999999, "pre-paper"),
]


def fetch_klines(symbol: str, start: int, end: int) -> list[list]:
    rows: list[list] = []
    cursor = start
    while cursor < end:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={INTERVAL}&startTime={cursor}"
            f"&endTime={end}&limit={LIMIT}"
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    batch = json.loads(r.read().decode())
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][6] + 1  # close_time + 1ms
        if len(batch) < LIMIT:
            break
        time.sleep(0.25)
    return rows


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for sym in SYMBOLS:
        for name, start, end, tag in WINDOWS:
            path = os.path.join(OUT, f"{sym}_{name}.json")
            if os.path.exists(path):
                continue
            raw = fetch_klines(sym, start, end)
            candles = [
                {
                    "ts": k[0], "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                }
                for k in raw
            ]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(candles, fh)
            print(sym, name, len(candles), "bars", flush=True)
            time.sleep(0.4)
    print("done ->", OUT)


if __name__ == "__main__":
    main()
