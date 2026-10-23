"""ARP-005 PATH A — fetch ADDITIONAL earlier 5m OHLCV into an ISOLATED corpus.

Read-only public Binance REST (market data only, no credentials, no order API).
Downloads monthly windows that PRECEDE the frozen ARP-002..004 corpus window W1
so the 5-day-hold liquidity-reversal experiment can reach a usable sample.

Hard isolation rules (do not violate):

* output goes to ``reports/alpha-recovery-v1-4/data/`` — **never** into
  ``reports/strategy-baseline/data/``, whose byte-level fingerprint
  (``9d51385d…``) is pinned by the frozen ARP-003/004 manifests;
* files are named ``{SYMBOL}_WX{n}_{yyyy-mm}.json`` and are *window files* in the
  same JSON shape as the baseline corpus, so the existing loader can read them;
* no interpolation, no synthesis: a day is only usable if the provider returned a
  complete 288-bar UTC day (the ARP-004 derivation already drops incomplete days).

Windows end at the frozen W1 boundary start (2026-03-01 00:00 UTC); the paper run
(2026-09-25) and the OOS window W7 stay untouched.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "reports", "alpha-recovery-v1-4", "data")
MANIFEST = os.path.join(OUT, "_FETCH_MANIFEST.json")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL = "5m"
LIMIT = 1000

#: (name, start_ms, end_ms_exclusive). Six consecutive months immediately before
#: the frozen W1_2026-03 window. Boundaries are UTC month starts.
WINDOWS: list[tuple[str, int, int]] = [
    ("WX1_2025-09", 1756684800000, 1759276800000),
    ("WX2_2025-10", 1759276800000, 1761955200000),
    ("WX3_2025-11", 1761955200000, 1764547200000),
    ("WX4_2025-12", 1764547200000, 1767225600000),
    ("WX5_2026-01", 1767225600000, 1769817600000),
    ("WX6_2026-02", 1769817600000, 1772323200000),
]


def fetch_klines(symbol: str, start: int, end: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start
    while cursor < end:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={INTERVAL}&startTime={cursor}"
            f"&endTime={end - 1}&limit={LIMIT}"
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
    entries: list[dict[str, Any]] = []
    for sym in SYMBOLS:
        for name, start, end in WINDOWS:
            path = os.path.join(OUT, f"{sym}_{name}.json")
            if os.path.exists(path):
                rows = json.loads(Path(path).read_text(encoding="utf-8"))
            else:
                raw = fetch_klines(sym, start, end)
                rows = [
                    {
                        "ts": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                    for k in raw
                ]
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                time.sleep(0.4)
            entries.append(
                {
                    "symbol": sym,
                    "window": name,
                    "file": os.path.basename(path),
                    "rows": len(rows),
                    "start_ms": rows[0]["ts"] if rows else None,
                    "end_ms": rows[-1]["ts"] if rows else None,
                }
            )
            print(sym, name, len(rows), "bars", flush=True)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump({"windows": entries}, fh, indent=2, sort_keys=True)
    print("done ->", OUT, flush=True)


if __name__ == "__main__":
    main()
