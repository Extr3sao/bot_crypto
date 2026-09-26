"""MICROSTRUCTURE-FORWARD-DATA-V1 — read-only microstructure collector (§17, §62).

DISCOVERY PLANE ONLY. This process:
  * uses PUBLIC read-only endpoints (no API key, no secret, no account),
  * NEVER touches the trading decision path,
  * NEVER places an order or speaks to an execution API,
  * persists raw snapshots with three clocks
    (exchange event time, receive time, process time).

It exists because order book / bookTicker have NO historical source
(SRC-07, DS-03/04 = LIVE_ONLY) and OI/basis retain only 30 days (SRC-06).
Rather than fabricate a historical book (§16), we collect forward evidence
for a future, honest fill/adverse-selection model.

Output: JSONL, one record per line, under reports/microstructure-v1/forward/.

Usage:
  uv run python scripts/microstructure_collector.py --symbols BTCUSDT,ETHUSDT,SOLUSDT \
      --interval 1.0 --duration 60 --out reports/microstructure-v1/forward
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

SPOT = "https://api.binance.com"
FAPI = "https://fapi.binance.com"
UA = {"User-Agent": "trading-agentic-portable-collector/1.0"}


def _get(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def collect_book(symbol: str, depth: int) -> list[dict[str, Any]]:
    """One top-of-book + depth snapshot. Read-only."""
    recv = _now_ms()
    bt = _get(f"{SPOT}/api/v3/ticker/bookTicker?symbol={symbol}")
    recv_bt = _now_ms()
    dp = _get(f"{SPOT}/api/v3/depth?symbol={symbol}&limit={depth}")
    recv_dp = _now_ms()
    proc = _now_ms()
    bid = float(bt["bidPrice"])
    ask = float(bt["askPrice"])
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10_000.0 if mid > 0 else None
    return [
        {
            "kind": "bookTicker",
            "symbol": symbol,
            "exchange_event_time": None,  # bookTicker has no exchange ts
            "receive_time": recv_bt,
            "process_time": proc,
            "receive_time_iso": _iso(recv_bt),
            "bid": bid,
            "ask": ask,
            "bid_qty": float(bt["bidQty"]),
            "ask_qty": float(bt["askQty"]),
            "mid": mid,
            "spread_bps": spread_bps,
        },
        {
            "kind": "depth",
            "symbol": symbol,
            "exchange_event_time": None,
            "receive_time": recv_dp,
            "process_time": proc,
            "receive_time_iso": _iso(recv_dp),
            "last_update_id": dp.get("lastUpdateId"),
            "bids": dp["bids"][:depth],
            "asks": dp["asks"][:depth],
            "_recv_first": recv,
        },
    ]


def collect_derivative_context(symbol: str) -> list[dict[str, Any]]:
    """Premium index + latest funding + OI value (30d endpoint). Read-only."""
    out: list[dict[str, Any]] = []
    recv = _now_ms()
    try:
        pi = _get(f"{FAPI}/fapi/v1/premiumIndex?symbol={symbol}")
        recv2 = _now_ms()
        out.append(
            {
                "kind": "premiumIndex",
                "symbol": symbol,
                "exchange_event_time": int(pi["time"]),
                "receive_time": recv2,
                "process_time": _now_ms(),
                "receive_time_iso": _iso(recv2),
                "mark_price": float(pi["markPrice"]),
                "index_price": float(pi["indexPrice"]),
                "last_funding_rate": float(pi["lastFundingRate"]),
                "next_funding_time": int(pi["nextFundingTime"]),
            }
        )
    except Exception:  # noqa: BLE001 - context only, never fatal
        pass
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between book snapshots")
    ap.add_argument("--duration", type=float, default=60.0, help="seconds to run (0 = forever)")
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--out", default="reports/microstructure-v1/forward")
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"forward_{int(time.time())}.jsonl")
    started = time.time()
    ticks = 0
    print(f"collecting -> {path} (read-only, DISCOVERY PLANE)", flush=True)
    with open(path, "a", encoding="utf-8") as fh:
        while args.duration <= 0 or (time.time() - started) < args.duration:
            t0 = time.time()
            for sym in symbols:
                try:
                    records = collect_book(sym, args.depth)
                    if ticks % 10 == 0:
                        records.extend(collect_derivative_context(sym))
                    for rec in records:
                        rec.pop("_recv_first", None)
                        rec["collector_run"] = path
                        fh.write(json.dumps(rec) + "\n")
                except Exception as exc:  # noqa: BLE001 - one bad poll never kills the run
                    fh.write(json.dumps({"kind": "error", "symbol": sym,
                                         "error": repr(exc), "receive_time": _now_ms()}) + "\n")
            fh.flush()
            ticks += 1
            elapsed = time.time() - t0
            time.sleep(max(0.0, args.interval - elapsed))
    print(f"done: {ticks} ticks -> {path}", flush=True)


if __name__ == "__main__":
    main()
