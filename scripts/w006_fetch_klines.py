#!/usr/bin/env python3
"""Fetch real historical klines from Binance's public USDⓈ-M endpoint (WP-006).

No credentials: `/fapi/v1/klines` is public. Every request is recorded with its
exact URL, HTTP status, byte length and SHA-256 of the response body, so the
dataset can be traced back to bytes that a reviewer can re-request.

Only closed bars are kept: a kline whose ``close_time`` is in the future is
still forming and would be a look-ahead in the most literal sense.

Output (all under ``--out``):

* ``datasets/<SYMBOL>_<interval>.json`` - bars as ``{ts, open, high, low, close, volume}``
  with ``ts`` = open time in UTC milliseconds;
* ``MANIFEST.json`` - per-chunk provenance, dataset digest, coverage, gap and
  duplicate accounting.

The fetcher is deterministic given the same server state: bars come from the
exchange, not from a local generator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://fapi.binance.com"
KLINES = BASE + "/fapi/v1/klines"
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
MAX_LIMIT = 1500


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def request(url: str, params: dict[str, Any], retries: int = 4) -> tuple[int, bytes]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    full = f"{url}?{query}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(full, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as e:  # 418/429/5xx are transient by policy
            body = e.read()
            if e.code in (418, 429) or e.code >= 500:
                last = e
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f"HTTP {e.code} for {full}: {body[:200]!r}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise SystemExit(f"request failed after {retries} attempts: {full}: {last}")


def fetch_symbol(symbol: str, interval: str, bars_wanted: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    step = INTERVAL_MS[interval]
    now_ms = int(time.time() * 1000)
    # Align the requested window to the interval so a re-run at a different
    # second within the same bar yields the same window.
    end_ms = (now_ms // step) * step
    start_target = end_ms - bars_wanted * step
    cursor = start_target
    chunks: list[dict[str, Any]] = []
    collected: dict[int, dict[str, Any]] = {}
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": interval, "limit": MAX_LIMIT,
                  "startTime": cursor, "endTime": end_ms}
        status, body = request(KLINES, params)
        rows = json.loads(body)
        chunks.append({
            "url": KLINES,
            "params": params,
            "http_status": status,
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "response_bytes": len(body),
            "rows": len(rows),
            "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        if not rows:
            break
        for row in rows:
            open_time, close_time = int(row[0]), int(row[6])
            if close_time >= end_ms:
                continue  # still forming: never a closed bar
            collected[open_time] = {
                "ts": open_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        next_cursor = int(rows[-1][0]) + step
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.12)
    return [collected[k] for k in sorted(collected)], chunks


def gaps(bars: list[dict[str, Any]], step: int) -> list[dict[str, Any]]:
    out = []
    for a, b in zip(bars, bars[1:]):
        delta = b["ts"] - a["ts"]
        if delta != step:
            out.append({"after_ts": a["ts"], "after_utc": iso(a["ts"]),
                        "next_ts": b["ts"], "next_utc": iso(b["ts"]),
                        "delta_ms": delta, "missing_bars": delta // step - 1})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    p.add_argument("--interval", default="5m", choices=sorted(INTERVAL_MS))
    p.add_argument("--days", type=float, default=120.0)
    args = p.parse_args(argv)

    step = INTERVAL_MS[args.interval]
    bars_wanted = int(args.days * 86_400_000 / step)
    (args.out / "datasets").mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "schema": "W006_MARKET_DATA_MANIFEST_V1",
        "source": {
            "venue": "Binance USDⓈ-M futures",
            "endpoint": KLINES,
            "auth": "none (public market data)",
            "interval": args.interval,
            "interval_ms": step,
        },
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_bars_per_symbol": bars_wanted,
        "datasets": {},
    }
    for symbol in args.symbols:
        bars, chunks = fetch_symbol(symbol, args.interval, bars_wanted)
        if not bars:
            raise SystemExit(f"no closed bars returned for {symbol}; refusing to write a dataset")
        payload = json.dumps(bars, separators=(",", ":")).encode("utf-8") + b"\n"
        rel = f"datasets/{symbol}_{args.interval}.json"
        (args.out / rel).write_bytes(payload)
        deltas = sorted({b["ts"] - a["ts"] for a, b in zip(bars, bars[1:])})
        manifest["datasets"][symbol] = {
            "path": rel,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "bars": len(bars),
            "start_ts": bars[0]["ts"],
            "start_utc": iso(bars[0]["ts"]),
            "end_ts": bars[-1]["ts"],
            "end_utc": iso(bars[-1]["ts"]),
            "span_hours": round((bars[-1]["ts"] - bars[0]["ts"]) / 3_600_000, 3),
            "step_ms_values_seen": deltas,
            "duplicate_open_times_removed": sum(c["rows"] for c in chunks) - len(bars),
            "gaps": gaps(bars, step),
            "requests": chunks,
        }
        print(f"{symbol}: bars={len(bars)} {iso(bars[0]['ts'])} -> {iso(bars[-1]['ts'])} "
              f"step={deltas} gaps={len(manifest['datasets'][symbol]['gaps'])} "
              f"requests={len(chunks)}")

    (args.out / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"manifest -> {args.out / 'MANIFEST.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
