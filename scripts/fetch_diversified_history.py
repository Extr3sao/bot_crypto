"""ARP-006 DIVERSIFIED ALPHA SEARCH §2-§8 — fetch the broader PIT universe corpus.

Read-only public Binance REST (market data only, no credentials, no order API).

This builds an isolated DAILY research corpus at
``reports/alpha-diversified-v1/data/`` — **never** into the ARP-005 corpus
(``reports/alpha-expansion-v1/data/``, digest ``2ce6e6b5…``), nor the frozen 5m
baselines. Native ``1d`` klines are fetched because every ARP-006 experiment is a
daily-horizon (time-series or cross-sectional) study, and because the kline payload
carries the **quote-asset volume** the PIT liquidity filter needs (§7).

Frozen universe-construction rule (declared BEFORE any result; see
``reports/alpha-diversified-v1/DYNAMIC_UNIVERSE.md``):

1. *candidate pool* = every Binance **spot** pair whose quote asset is ``USDT``,
   status ``TRADING`` at fetch time, and whose base asset is not a fiat/stablecoin;
2. *listing_time(symbol)* = the timestamp of the symbol's **first available**
   Binance ``1d`` kline — an upper bound on true listing, and PIT-safe because it
   reads only what the exchange makes available;
3. *inclusion rule* = ``listing_time <= CUTOFF_MS`` (2021-06-30 UTC), fixed a priori
   to give every included asset a long multi-regime history. The cutoff is a
   breadth decision, never a tuned parameter.

**Survivorship limitation (honest, pre-declared).** ``exchangeInfo`` lists only
symbols that trade *today*; assets delisted on/before the fetch date are absent.
This corpus therefore cannot reconstruct delisted markets and the research records
``SURVIVORSHIP_DATA_LIMITATION`` (§4). Conclusions are qualified accordingly.

No interpolation, no synthesis: gaps are recorded, never filled. The frozen W1..W7
windows (2026-03 onward) are outside the range and stay untouched.
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
OUT = os.path.join(HERE, "..", "reports", "alpha-diversified-v1", "data")
MANIFEST = os.path.join(OUT, "_FETCH_MANIFEST.json")
LISTING_SCAN = os.path.join(OUT, "_LISTING_SCAN.json")

INTERVAL = "1d"
LIMIT = 1000
DAY_MS = 86_400_000

#: 2017-01-01 .. 2026-03-01 UTC (exclusive end). Native history starts 2017.
START_MS = 1_483_228_800_000
END_MS = 1_772_323_200_000
CUTOFF_MS = 1_624_992_000_000  # 2021-06-30T00:00:00Z
SOURCE = "BINANCE_PUBLIC_REST:/api/v3/klines"

STABLE_BASES = {
    "USDC",
    "TUSD",
    "BUSD",
    "FDUSD",
    "DAI",
    "USDP",
    "PAX",
    "SUSD",
    "UST",
    "USTC",
    "AEUR",
    "EURI",
    "EUR",
    "GBP",
    "BIDR",
    "IDRT",
    "BKRW",
    "BVND",
    "TRY",
    "BRL",
    "ARS",
    "ZAR",
    "RUB",
    "UAH",
    "NGN",
    "PLN",
    "RON",
    "CZK",
    "JPY",
    "MXN",
    "COP",
}


def _get(url: str, attempts: int = 5) -> Any:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    assert last is not None
    raise last


def fetch_klines(symbol: str, interval: str, start: int, end: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start
    while cursor < end:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}&startTime={cursor}"
            f"&endTime={end - 1}&limit={LIMIT}"
        )
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 1  # next open time
        if len(batch) < LIMIT:
            break
        time.sleep(0.12)
    return rows


def first_kline_ts(symbol: str) -> int | None:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&startTime=0&limit=1"
    batch = _get(url)
    return int(batch[0][0]) if batch else None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def candidate_pool() -> list[str]:
    info = _get("https://api.binance.com/api/v3/exchangeInfo")
    out: list[str] = []
    for s in info["symbols"]:
        sym = s["symbol"]
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if s.get("baseAsset") in STABLE_BASES:
            continue
        out.append(sym)
    return sorted(out)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    pool = candidate_pool()
    print(f"candidate pool: {len(pool)} USDT spot pairs", flush=True)

    scan: dict[str, int | None] = {}
    for i, sym in enumerate(pool):
        try:
            scan[sym] = first_kline_ts(sym)
        except Exception as exc:
            scan[sym] = None
            print(f"  scan-fail {sym}: {exc!r}", flush=True)
        if i % 50 == 0:
            print(f"  scanned {i}/{len(pool)}", flush=True)
    Path(LISTING_SCAN).write_text(json.dumps(scan, indent=2, sort_keys=True), encoding="utf-8")

    included = sorted(s for s, ts in scan.items() if ts is not None and ts <= CUTOFF_MS)
    print(f"included (listing <= 2021-06-30): {len(included)}", flush=True)

    manifest: dict[str, Any] = {
        "source": SOURCE,
        "interval": INTERVAL,
        "requested_range_ms": [START_MS, END_MS],
        "listing_cutoff_ms": CUTOFF_MS,
        "downloaded_utc": datetime.now(UTC).isoformat(),
        "normalization": (
            "list of {ts,open,high,low,close,volume,quote_volume,trades}; ts = bar OPEN "
            "time (ms, UTC), complete days only (ts+86400000 <= range end); floats; "
            "no interpolation, no synthesis, gaps left absent"
        ),
        "survivorship_limitation": (
            "exchangeInfo lists only symbols trading today; delisted markets are absent"
        ),
        "symbols": {},
    }
    for n, sym in enumerate(included):
        raw = fetch_klines(sym, INTERVAL, START_MS, END_MS)
        bars = []
        for k in raw:
            ts = int(k[0])
            if ts < START_MS or ts + DAY_MS > END_MS:
                continue  # drop partial/incomplete days (PIT: complete bars only)
            bars.append(
                {
                    "ts": ts,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "quote_volume": float(k[7]),
                    "trades": int(k[8]),
                }
            )
        path = Path(OUT) / f"{sym}.json"
        path.write_text(json.dumps(bars), encoding="utf-8")
        ts_all = [b["ts"] for b in bars]
        expected = (ts_all[-1] - ts_all[0]) // DAY_MS + 1 if ts_all else 0
        manifest["symbols"][sym] = {
            "listing_time": scan[sym],
            "first_ts": ts_all[0] if ts_all else None,
            "last_ts": ts_all[-1] if ts_all else None,
            "bars": len(bars),
            "expected_bars": expected,
            "gaps": max(0, expected - len(set(ts_all))),
            "duplicates": len(ts_all) - len(set(ts_all)),
            "file": path.name,
            "sha256": _sha256_file(path),
        }
        if n % 20 == 0:
            print(f"  fetched {n}/{len(included)} ({sym}: {len(bars)} bars)", flush=True)

    combined = hashlib.sha256()
    shards = sorted(p for p in Path(OUT).glob("*.json") if not p.name.startswith("_"))
    for p in shards:
        combined.update(_sha256_file(p).encode())
    manifest["corpus_digest"] = combined.hexdigest()
    manifest["shards"] = [p.name for p in shards]
    manifest["included_symbols"] = included
    Path(MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print("corpus_digest =", manifest["corpus_digest"], flush=True)
    print("done ->", OUT, flush=True)


if __name__ == "__main__":
    main()
