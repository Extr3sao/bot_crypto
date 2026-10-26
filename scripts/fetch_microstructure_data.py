"""Read-only microstructure data fetcher (EXECUTION-COST & MICROSTRUCTURE-EDGE-V1 §14-17).

Fetches PUBLIC, read-only market data. NEVER connects to an execution API,
never uses credentials, never places orders.

Sources:
  * Binance Spot REST /api/v3/klines          (OHLCV + taker buy flow + trades)
  * Binance USD-M /fapi/v1/fundingRate        (realised funding history)
  * Binance USD-M /fapi/v1/premiumIndexKlines (premium index history)
  * Binance USD-M /futures/data/openInterestHist (30-day retention)
  * Binance USD-M /futures/data/basis         (30-day retention)

Everything is stored raw under reports/microstructure-v1/data/ (gitignored).
Each stored kline keeps ALL 12 columns so downstream code can rebuild flow
features; each stored record keeps its exchange timestamp verbatim so the
PIT clock is reconstructable.

Data planes:
  historical plane (this script)  -> reproducible, PIT-safe when consumed
                                     via available_at >= event_time
  forward plane  (collector)      -> see MICROSTRUCTURE-FORWARD-DATA-V1

Usage:
  uv run python scripts/fetch_microstructure_data.py [--assets BTC,ETH,SOL]
                                                     [--start 2026-03-01]
                                                     [--end 2026-09-25]
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "reports", "microstructure-v1", "data")
UA = {"User-Agent": "trading-agentic-portable-research/1.0"}

SPOT = "https://api.binance.com"
FAPI = "https://fapi.binance.com"

RATE_SLEEP = 0.25


def _get(url: str, retries: int = 4) -> Any:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (418, 429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    assert last is not None
    raise last


def ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


# --- klines ---------------------------------------------------------------


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    """Page through /api/v3/klines (max 1000/req). Returns raw rows."""
    out: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"{SPOT}/api/v3/klines?symbol={symbol}&interval={interval}"
            f"&startTime={cursor}&endTime={end_ms}&limit=1000"
        )
        rows = _get(url)
        if not rows:
            break
        out.extend(rows)
        cursor = int(rows[-1][0]) + 1
        time.sleep(RATE_SLEEP)
        if len(rows) < 1000:
            break
    return out


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"{FAPI}/fapi/v1/fundingRate?symbol={symbol}"
            f"&startTime={cursor}&endTime={end_ms}&limit=1000"
        )
        rows = _get(url)
        if not rows:
            break
        out.extend(rows)
        cursor = int(rows[-1]["fundingTime"]) + 1
        time.sleep(RATE_SLEEP)
        if len(rows) < 1000:
            break
    return out


def fetch_premium_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    out: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"{FAPI}/fapi/v1/premiumIndexKlines?symbol={symbol}&interval={interval}"
            f"&startTime={cursor}&endTime={end_ms}&limit=1500"
        )
        rows = _get(url)
        if not rows:
            break
        out.extend(rows)
        cursor = int(rows[-1][0]) + 1
        time.sleep(RATE_SLEEP)
        if len(rows) < 1500:
            break
    return out


def fetch_recent_history(path: str, symbol: str, period: str, pages: int = 25) -> list[Any]:
    """Page a 30-day-retention endpoint (OI / basis) BACKWARDS by endTime.

    These endpoints ignore a bare ``startTime`` and return the most recent
    window, so the only reliable way to walk the retained history is to move
    ``endTime`` towards the past until the API rejects (retention boundary).
    """
    is_basis = path.endswith("basis")
    cursor_end = int(time.time() * 1000)
    chunks: list[list[Any]] = []
    for _ in range(pages):
        if is_basis:
            url = (
                f"{FAPI}{path}?pair={symbol}&contractType=PERPETUAL"
                f"&period={period}&limit=500&endTime={cursor_end}"
            )
        else:
            url = f"{FAPI}{path}?symbol={symbol}&period={period}&limit=500&endTime={cursor_end}"
        try:
            rows = _get(url)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break  # retention boundary reached
            raise
        if not rows:
            break
        chunks.append(rows)
        cursor_end = int(rows[0]["timestamp"]) - 1
        time.sleep(RATE_SLEEP)
        if len(rows) < 500:
            break
    # chunks are newest-first; reverse to oldest-first
    out: list[Any] = []
    for c in reversed(chunks):
        out.extend(c)
    return out


def save(name: str, obj: Any) -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    print(f"  -> {name} ({os.path.getsize(path)} bytes)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="BTC,ETH,SOL")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-09-25")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--only", default="all", help="all|klines|premium|funding|oi|basis")
    args = ap.parse_args()
    only = args.only

    start_ms = ms(args.start)
    end_ms = ms(args.end)
    symbols = [f"{a.strip()}USDT" for a in args.assets.split(",") if a.strip()]

    manifest: dict[str, Any] = {
        "start": args.start,
        "end": args.end,
        "interval": args.interval,
        "symbols": symbols,
        "generated_utc": datetime.now(UTC).isoformat(),
        "files": {},
    }

    for sym in symbols:
        if only in ("all", "klines"):
            print(f"[{sym}] klines {args.interval}", flush=True)
            kl = fetch_klines(sym, args.interval, start_ms, end_ms)
            save(f"KLINES_{sym}_{args.interval}.json", kl)
            manifest["files"][f"KLINES_{sym}_{args.interval}.json"] = len(kl)

        if only in ("all", "premium"):
            print(f"[{sym}] premiumIndexKlines {args.interval}", flush=True)
            pk = fetch_premium_klines(sym, args.interval, start_ms, end_ms)
            save(f"PREMIUM_{sym}_{args.interval}.json", pk)
            manifest["files"][f"PREMIUM_{sym}_{args.interval}.json"] = len(pk)

        if only in ("all", "funding"):
            print(f"[{sym}] fundingRate", flush=True)
            fr = fetch_funding(sym, start_ms, end_ms)
            save(f"FUNDING_{sym}.json", fr)
            manifest["files"][f"FUNDING_{sym}.json"] = len(fr)

        if only in ("all", "oi"):
            print(f"[{sym}] openInterestHist (30d retention)", flush=True)
            oi = fetch_recent_history("/futures/data/openInterestHist", sym, args.interval, 25)
            save(f"OPENINTEREST_{sym}.json", oi)
            manifest["files"][f"OPENINTEREST_{sym}.json"] = len(oi)

        if only in ("all", "basis"):
            print(f"[{sym}] basis (30d retention)", flush=True)
            ba = fetch_recent_history("/futures/data/basis", sym, args.interval, 25)
            save(f"BASIS_{sym}.json", ba)
            manifest["files"][f"BASIS_{sym}.json"] = len(ba)

    save(f"MANIFEST_{only}.json", manifest)
    print("done", flush=True)


if __name__ == "__main__":
    main()
