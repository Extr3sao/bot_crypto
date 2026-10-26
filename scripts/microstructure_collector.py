"""MICROSTRUCTURE-FORWARD-COLLECTION-V1 — read-only forward collector.

DISCOVERY PLANE ONLY. This process:
  * uses PUBLIC read-only endpoints (no API key, no secret, no account),
  * NEVER touches the trading decision path,
  * NEVER places an order or speaks to an execution API,
  * persists raw observations append-only with three clocks
    (exchange event time, receive time, process time).

It exists because order book / bookTicker have NO historical source
(SRC-07, DS-03/04 = LIVE_ONLY) and OI/basis retain only 30 days (SRC-06).
Rather than fabricate a historical book (§16), we collect forward evidence for
a future, honest fill / adverse-selection model.

Streams collected (best effort; a stream that is unavailable is simply absent):
  bookTicker   best bid/ask + quantities          (no exchange event time)
  depth        top-N book + lastUpdateId          (sequence id)
  aggTrade     tick prints + aggTradeId, isBuyerMaker, exchange event time
  premiumIndex mark/index/last funding rate       (exchange event time)

Integrity: each record is written verbatim; the manifest reports duplicates,
out-of-order records, per-(symbol, kind) gaps and stale periods. Collection
never repairs data — it reports it.

Usage:
  uv run python scripts/microstructure_collector.py \
      --symbols BTCUSDT,ETHUSDT,SOLUSDT --interval 1.0 --duration 60 \
      --out reports/microstructure-v1/forward
  uv run python scripts/microstructure_collector.py --smoke     # short pipeline test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

COLLECTOR_VERSION = "FORWARD-COLLECTOR-V1"
SCHEMA_VERSION = "forward-record-v1"

SPOT = "https://api.binance.com"
FAPI = "https://fapi.binance.com"
UA = {"User-Agent": "trading-agentic-portable-collector/1.0"}

# A stream is "stale" when no record of that kind arrived for the symbol in
# more than this many seconds.
STALE_AFTER_S = 15.0
# A gap in a strictly-increasing integer sequence id larger than this is
# reported (exchange sequences advance irregularly, so this is a signal, not
# a failure).
SEQUENCE_GAP_THRESHOLD = 1


def _get(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _rec(kind: str, symbol: str, **fields: Any) -> dict[str, Any]:
    """Assemble one schema-versioned record with the three clocks."""
    now = _now_ms()
    rec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "kind": kind,
        "symbol": symbol,
        "exchange_event_time": None,
        "receive_time": now,
        "process_time": now,
        "receive_time_iso": _iso(now),
    }
    rec.update(fields)
    return rec


def collect_book_ticker(symbol: str) -> dict[str, Any]:
    recv = _now_ms()
    bt = _get(f"{SPOT}/api/v3/ticker/bookTicker?symbol={symbol}")
    recv_done = _now_ms()
    bid = float(bt["bidPrice"])
    ask = float(bt["askPrice"])
    mid = (bid + ask) / 2.0
    return _rec(
        "bookTicker",
        symbol,
        receive_time=recv_done,
        receive_time_iso=_iso(recv_done),
        request_sent_time=recv,
        bid=bid,
        ask=ask,
        bid_qty=float(bt["bidQty"]),
        ask_qty=float(bt["askQty"]),
        mid=mid,
        spread_bps=(ask - bid) / mid * 10_000.0 if mid > 0 else None,
        crossed=bool(bid >= ask),
    )


def collect_depth(symbol: str, depth: int) -> dict[str, Any]:
    recv = _now_ms()
    dp = _get(f"{SPOT}/api/v3/depth?symbol={symbol}&limit={depth}")
    recv_done = _now_ms()
    return _rec(
        "depth",
        symbol,
        receive_time=recv_done,
        receive_time_iso=_iso(recv_done),
        request_sent_time=recv,
        last_update_id=int(dp["lastUpdateId"]),
        bids=dp["bids"][:depth],
        asks=dp["asks"][:depth],
    )


def collect_agg_trades(symbol: str, limit: int = 100) -> list[dict[str, Any]]:
    """Recent ticks: real exchange event time + aggTradeId + aggressor side.

    ``isBuyerMaker == true`` means the aggressor was the SELLER (a market sell
    hit a resting bid). Signing the flow from this flag is what makes the
    forward dataset testable for M-01 at tick granularity instead of kline
    aggregation.
    """
    raw = _get(f"{SPOT}/api/v3/aggTrades?symbol={symbol}&limit={limit}")
    recv_done = _now_ms()
    out: list[dict[str, Any]] = []
    for t in raw:
        is_buyer_maker = bool(t["m"])
        out.append(
            _rec(
                "aggTrade",
                symbol,
                receive_time=recv_done,
                receive_time_iso=_iso(recv_done),
                exchange_event_time=int(t["T"]),
                agg_trade_id=int(t["a"]),
                first_trade_id=int(t["f"]),
                last_trade_id=int(t["l"]),
                price=float(t["p"]),
                qty=float(t["q"]),
                is_buyer_maker=is_buyer_maker,
                aggressor="SELL" if is_buyer_maker else "BUY",
            )
        )
    return out


def collect_derivative_context(symbol: str) -> dict[str, Any] | None:
    """Premium index + last funding rate. Context only; never fatal."""
    try:
        pi = _get(f"{FAPI}/fapi/v1/premiumIndex?symbol={symbol}")
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError):
        return None
    recv_done = _now_ms()
    return _rec(
        "premiumIndex",
        symbol,
        receive_time=recv_done,
        receive_time_iso=_iso(recv_done),
        exchange_event_time=int(pi["time"]),
        mark_price=float(pi["markPrice"]),
        index_price=float(pi["indexPrice"]),
        last_funding_rate=float(pi["lastFundingRate"]),
        next_funding_time=int(pi["nextFundingTime"]),
    )


# ---------------------------------------------------------------------------
# Manifest / integrity
# ---------------------------------------------------------------------------


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(path: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise coverage, gaps, duplicates, ordering and staleness."""
    by_kind: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    for r in records:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        by_symbol[r["symbol"]] = by_symbol.get(r["symbol"], 0) + 1

    recv = [int(r["receive_time"]) for r in records]
    duplicates = 0
    out_of_order = 0
    seen: set[tuple[str, str, int, Any]] = set()
    for r in records:
        key = (
            r["kind"],
            r["symbol"],
            int(r["receive_time"]),
            r.get("agg_trade_id") or r.get("last_update_id"),
        )
        if key in seen:
            duplicates += 1
        seen.add(key)
    for i in range(1, len(recv)):
        if recv[i] < recv[i - 1]:
            out_of_order += 1

    gaps: list[dict[str, Any]] = []
    for kind in sorted(by_kind):
        for sym in sorted({r["symbol"] for r in records if r["kind"] == kind}):
            ts = [
                int(r["receive_time"]) for r in records if r["kind"] == kind and r["symbol"] == sym
            ]
            if len(ts) < 2:
                continue
            worst = max(ts[i] - ts[i - 1] for i in range(1, len(ts)))
            if worst > STALE_AFTER_S * 1000:
                gaps.append(
                    {
                        "kind": kind,
                        "symbol": sym,
                        "n": len(ts),
                        "worst_gap_ms": worst,
                        "stale_periods": sum(
                            1 for i in range(1, len(ts)) if ts[i] - ts[i - 1] > STALE_AFTER_S * 1000
                        ),
                    }
                )

    seq_gaps: list[dict[str, Any]] = []
    for sym in sorted({r["symbol"] for r in records}):
        ticks = [r for r in records if r["kind"] == "aggTrade" and r["symbol"] == sym]
        ticks = [t for t in ticks if t.get("agg_trade_id") is not None]
        ids = sorted({int(t["agg_trade_id"]) for t in ticks})
        holes = 0
        worst = 0
        for i in range(1, len(ids)):
            d = ids[i] - ids[i - 1]
            if d > SEQUENCE_GAP_THRESHOLD + 1:
                holes += 1
                worst = max(worst, d)
        seq_gaps.append(
            {
                "symbol": sym,
                "kind": "aggTrade",
                "n_ids": len(ids),
                "holes": holes,
                "worst_step": worst,
            }
        )

    depth_ids: list[dict[str, Any]] = []
    for sym in sorted({r["symbol"] for r in records}):
        snaps = [r for r in records if r["kind"] == "depth" and r["symbol"] == sym]
        ids = [int(s["last_update_id"]) for s in snaps]
        regressions = sum(1 for i in range(1, len(ids)) if ids[i] < ids[i - 1])
        depth_ids.append(
            {"symbol": sym, "kind": "depth", "n": len(ids), "sequence_regressions": regressions}
        )

    event_times_present = sum(1 for r in records if r.get("exchange_event_time") is not None)
    return {
        "manifest_version": "forward-manifest-v1",
        "collector_version": COLLECTOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "file": os.path.basename(path),
        "sha256": _sha256(path),
        "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
        "records": len(records),
        "by_kind": by_kind,
        "by_symbol": by_symbol,
        "coverage": {
            "start_receive_time": min(recv) if recv else None,
            "end_receive_time": max(recv) if recv else None,
            "start_iso": _iso(min(recv)) if recv else None,
            "end_iso": _iso(max(recv)) if recv else None,
            "duration_s": ((max(recv) - min(recv)) / 1000.0) if recv else 0.0,
        },
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "gaps": gaps,
        "sequence_gaps": seq_gaps,
        "depth_sequence_regressions": depth_ids,
        "records_with_exchange_event_time": event_times_present,
        "known_limitation": (
            "REST depth/bookTicker snapshots are independent polls, not a "
            "sequenced stream; there is no diff-depth reconciliation here."
        ),
    }


def run(
    symbols: list[str], interval: float, duration: float, depth: int, out_dir: str
) -> tuple[str, int]:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"forward_{int(time.time())}.jsonl")
    started = time.time()
    ticks = 0
    records_written = 0
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        while duration <= 0 or (time.time() - started) < duration:
            t0 = time.time()
            for sym in symbols:
                batch: list[dict[str, Any]] = []
                for collector in (collect_book_ticker, lambda s: collect_depth(s, depth)):
                    try:
                        batch.append(collector(sym))
                    except (
                        urllib.error.URLError,
                        urllib.error.HTTPError,
                        ValueError,
                        KeyError,
                    ) as exc:
                        batch.append(_rec("error", sym, error=repr(exc)))
                try:
                    batch.extend(collect_agg_trades(sym))
                except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as exc:
                    batch.append(_rec("error", sym, error=repr(exc)))
                if ticks % 5 == 0:
                    ctx = collect_derivative_context(sym)
                    if ctx is not None:
                        batch.append(ctx)
                for rec in batch:
                    rec["collector_run"] = os.path.basename(path)
                    fh.write(json.dumps(rec) + "\n")
                    records_written += 1
            fh.flush()
            ticks += 1
            time.sleep(max(0.0, interval - (time.time() - t0)))
    return path, records_written


def _load_records(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between polls")
    ap.add_argument("--duration", type=float, default=60.0, help="seconds to run (0 = forever)")
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--out", default="reports/microstructure-v1/forward")
    ap.add_argument("--smoke", action="store_true", help="short pipeline verification run")
    ap.add_argument("--manifest", default="reports/microstructure-v1/COLLECTION_SMOKE_REPORT.json")
    args = ap.parse_args()

    if args.smoke:
        args.duration = 45.0
        args.interval = 1.0

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    path, n = run(symbols, args.interval, args.duration, args.depth, args.out)
    records = _load_records(path)
    manifest = build_manifest(path, records)
    manifest["mode"] = "smoke" if args.smoke else "continuous"
    manifest["expected_records_written"] = n

    os.makedirs(os.path.dirname(os.path.abspath(args.manifest)), exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print(f"collected {manifest['records']} records -> {path} (read-only, DISCOVERY PLANE)")
    print(f"manifest -> {args.manifest}")
    print(f"kinds: {manifest['by_kind']}")
    print(f"duplicates={manifest['duplicates']} out_of_order={manifest['out_of_order']}")


if __name__ == "__main__":
    main()
