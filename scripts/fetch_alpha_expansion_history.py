"""ARP-005 ALPHA EXPANSION §3-§5 — fetch long native 1h OHLCV history.

Read-only public Binance REST (market data only, no credentials, no order API).

Downloads enough history (2019-01-01 UTC .. 2026-02-28 UTC) to support 4h/8h/1d
and multi-day research across multiple regimes (bull / bear / sideways / high-
and low-volatility). 1h is fetched natively because it is cheap and exact; higher
timeframes (4h/8h/1d) are CONSTRUCTED deterministically by
``trading_bot.research.alpha_expansion.htf`` with PIT guarantees (see §5).

Hard isolation rules (do not violate):

* output goes to ``reports/alpha-expansion-v1/data/`` — **never** into
  ``reports/strategy-baseline/data/`` (fingerprint ``9d51385d…``) nor
  ``reports/alpha-recovery-v1-4/data/`` (digest ``d3669d28…``), both pinned by
  frozen upstream manifests;
* files are ``{SYMBOL}_{YYYY}.json`` year shards in the same JSON shape as the
  other corpora, so the existing loader conventions still apply;
* no interpolation, no synthesis: missing bars are recorded as gaps, never filled.

The frozen W1..W7 windows (2026-03 onward) and the paper run (2026-09-25) are
outside the fetched range and stay untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "reports", "alpha-expansion-v1", "data")
MANIFEST = os.path.join(OUT, "_FETCH_MANIFEST.json")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL = "1h"
LIMIT = 1000
HOUR_MS = 3_600_000

#: 2019-01-01 00:00:00 UTC .. 2026-02-28 23:00:00 UTC (exclusive end).
START_MS = 1546300800000
END_MS = 1772323200000
SOURCE = "BINANCE_PUBLIC_REST:/api/v3/klines"

YEAR_MS = 31_536_000_000  # nominal year, only used to bucket files by real year


def year_of(ts_ms: int) -> int:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).year


def fetch_klines(symbol: str, start: int, end: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start
    while cursor < end:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={INTERVAL}&startTime={cursor}"
            f"&endTime={end - 1}&limit={LIMIT}"
        )
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    batch = json.loads(r.read().decode())
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][6] + 1  # close_time + 1ms
        if len(batch) < LIMIT:
            break
        time.sleep(0.15)
    return rows


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Gap / duplicate audit for one fetched symbol (all year shards combined)."""
    ts = [b["ts"] for b in bars]
    n = len(ts)
    duplicates = n - len(set(ts))
    if n:
        expected = (ts[-1] - ts[0]) // HOUR_MS + 1
        gaps = expected - len(set(ts))
    else:
        expected, gaps = 0, 0
    return {
        "first_ts": ts[0] if ts else None,
        "last_ts": ts[-1] if ts else None,
        "bars": n,
        "expected_bars": expected,
        "gaps": max(0, gaps),
        "duplicates": duplicates,
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    manifest: dict[str, Any] = {
        "source": SOURCE,
        "interval": INTERVAL,
        "requested_range_ms": [START_MS, END_MS],
        "downloaded_utc": datetime.now(UTC).isoformat(),
        "normalization": (
            "list of {ts,open,high,low,close,volume}; ts = bar OPEN time (ms, UTC); "
            "floats; no interpolation, no synthesis, gaps left absent"
        ),
        "symbols": {},
    }
    for sym in SYMBOLS:
        all_bars: list[dict[str, Any]] = []
        # Deterministic year shards: fetch the whole range once, bucket by UTC year.
        raw = fetch_klines(sym, START_MS, END_MS)
        bars = [
            {
                "ts": k[0], "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
            }
            for k in raw
        ]
        by_year: dict[int, list[dict[str, Any]]] = {}
        for b in bars:
            by_year.setdefault(year_of(b["ts"]), []).append(b)
        files: dict[str, Any] = {}
        for year, ybars in sorted(by_year.items()):
            path = Path(OUT) / f"{sym}_{year}.json"
            path.write_text(json.dumps(ybars), encoding="utf-8")
            files[str(year)] = {
                "file": path.name, "bars": len(ybars),
                "sha256": _sha256_file(path),
                "first_ts": ybars[0]["ts"], "last_ts": ybars[-1]["ts"],
            }
        all_bars.extend(bars)
        audit = _audit(all_bars)
        manifest["symbols"][sym] = {
            "source": SOURCE, "symbol": sym, "timeframe": INTERVAL,
            "download_time_utc": manifest["downloaded_utc"],
            "first_ts": audit["first_ts"], "last_ts": audit["last_ts"],
            "bars": audit["bars"], "expected_bars": audit["expected_bars"],
            "gaps": audit["gaps"], "duplicates": audit["duplicates"],
            "files": files,
            "year_bars": {y: len(b) for y, b in sorted(by_year.items())},
        }
        print(
            f"{sym}: {audit['bars']} bars  first={audit['first_ts']} "
            f"last={audit['last_ts']} gaps={audit['gaps']} dup={audit['duplicates']}",
            flush=True,
        )
    # Corpus-level digest: ordered sha256 over every shard in sorted name order.
    combined = hashlib.sha256()
    shards = sorted(p for p in Path(OUT).glob("*.json") if not p.name.startswith("_"))
    for p in shards:
        combined.update(_sha256_file(p).encode())
    manifest["corpus_digest"] = combined.hexdigest()
    manifest["shards"] = [p.name for p in shards]
    Path(MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print("corpus_digest =", manifest["corpus_digest"])
    print("done ->", OUT)


if __name__ == "__main__":
    main()
