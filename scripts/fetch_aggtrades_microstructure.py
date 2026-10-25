"""AGGTRADES histogram fetcher — real ticks -> compact PIT per-minute rows.

§PHASE 5. Downloads the OFFICIAL Binance daily aggTrades zips (SRC-04),
stream-aggregates every tick into one row per UTC minute, and then DELETES the
raw zip. Nothing is fabricated: every derived row is a deterministic function
of real prints, and the manifest keeps the SHA-256 of the source zip plus the
exact URL so the aggregate is reconstructable.

Why aggregate instead of keeping ticks: a day of BTCUSDT aggTrades is ~15 MB
zipped / ~100 MB raw and we only have a few GB of disk. The aggregate keeps
everything the pre-registered features need (signed flow, trade counts, size
distribution, inter-arrival, VWAP), and the source hash proves which bytes it
came from.

Aggregation rules (must match docs/AGGTRADES_HYPOTHESES_V1.md §2):
  * bucket = floor(exchange timestamp / 60_000) * 60_000  (UTC minute open)
  * a tick belongs to the bucket of its OWN exchange timestamp
  * isBuyerMaker == True  -> aggressor is the SELLER
  * isBuyerMaker == False -> aggressor is the BUYER
  * "large" = notional (price * qty) >= 50_000 USD (fixed threshold)

Usage:
  uv run python scripts/fetch_aggtrades_microstructure.py [--assets BTC,ETH,SOL]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "reports", "microstructure-v1", "aggtrades"))
UA = {"User-Agent": "trading-agentic-portable-research/1.0"}

BASE = "https://data.binance.vision/data/spot/daily/aggTrades/{sym}/{sym}-aggTrades-{day}.zip"

LARGE_TRADE_NOTIONAL_USD = 50_000.0
MINUTE_MS = 60_000

# Binance bulk spot aggTrades switched its timestamp column to MICROSECONDS.
# A millisecond epoch in 2026 is ~1.8e12; a microsecond epoch is ~1.8e15, so a
# 1e14 threshold separates them unambiguously. Getting this wrong fragments the
# minute buckets into one bucket per print (observed 2026-09-27: 62k rows/day).
_MICROSECOND_THRESHOLD = 10**14


def _to_ms(raw_ts: int) -> tuple[int, str]:
    """Normalise an exchange timestamp to milliseconds; report the unit seen."""
    if raw_ts >= _MICROSECOND_THRESHOLD:
        return raw_ts // 1000, "microseconds"
    return raw_ts, "milliseconds"

# PRE-REGISTERED day sample — see docs/AGGTRADES_HYPOTHESES_V1.md §1.1.
SAMPLE_DAYS: dict[str, list[str]] = {
    "DEV": [
        "2026-03-12", "2026-03-24",
        "2026-04-12", "2026-04-24",
        "2026-05-12", "2026-05-24",
        "2026-06-12", "2026-06-24",
    ],
    "VAL": ["2026-07-12", "2026-07-24", "2026-08-12", "2026-08-24"],
    "OOS": ["2026-09-12", "2026-09-24"],
}


def _http_bytes(url: str, timeout: float = 120.0) -> bytes | None:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data: bytes = r.read()
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _empty_bucket() -> dict[str, Any]:
    return {
        "n_trades": 0,
        "buy_vol": 0.0,
        "sell_vol": 0.0,
        "buy_quote": 0.0,
        "sell_quote": 0.0,
        "buy_count": 0,
        "sell_count": 0,
        "sum_qty_sq": 0.0,
        "large_buy_vol": 0.0,
        "large_sell_vol": 0.0,
        "first_price": None,
        "last_price": None,
        "high": None,
        "low": None,
        "max_trade_qty": 0.0,
        "last_ts": None,
        "min_interarrival_ms": None,
    }


def aggregate_day(zip_bytes: bytes) -> tuple[dict[int, dict[str, Any]], str]:
    """Stream one daily zip into per-minute buckets. Deterministic.

    Returns the buckets plus the detected timestamp unit (fail-loud: an
    unexpected unit is reported in the manifest rather than silently bucketed).
    """
    buckets: dict[int, dict[str, Any]] = {}
    units_seen: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for row in csv.reader(text):
                if not row or row[0].startswith("aggTradeId"):
                    continue
                ts_raw = int(row[5])
                ts, unit = _to_ms(ts_raw)
                units_seen.add(unit)
                price = float(row[1])
                qty = float(row[2])
                # isBuyerMaker may be "true"/"True"
                is_buyer_maker = str(row[6]).strip().lower() == "true"
                minute = (ts // MINUTE_MS) * MINUTE_MS
                b = buckets.get(minute)
                if b is None:
                    b = _empty_bucket()
                    buckets[minute] = b
                notional = price * qty
                b["n_trades"] += 1
                if is_buyer_maker:
                    b["sell_vol"] += qty
                    b["sell_quote"] += notional
                    b["sell_count"] += 1
                    if notional >= LARGE_TRADE_NOTIONAL_USD:
                        b["large_sell_vol"] += qty
                else:
                    b["buy_vol"] += qty
                    b["buy_quote"] += notional
                    b["buy_count"] += 1
                    if notional >= LARGE_TRADE_NOTIONAL_USD:
                        b["large_buy_vol"] += qty
                b["sum_qty_sq"] += qty * qty
                if b["first_price"] is None:
                    b["first_price"] = price
                b["last_price"] = price
                b["high"] = price if b["high"] is None else max(b["high"], price)
                b["low"] = price if b["low"] is None else min(b["low"], price)
                b["max_trade_qty"] = max(b["max_trade_qty"], qty)
                if b["last_ts"] is not None:
                    gap = ts - b["last_ts"]
                    prev = b["min_interarrival_ms"]
                    b["min_interarrival_ms"] = gap if prev is None else min(prev, gap)
                b["last_ts"] = ts
    if len(units_seen) > 1:
        raise ValueError(f"mixed timestamp units in one file: {sorted(units_seen)}")
    return buckets, (units_seen.pop() if units_seen else "unknown")


def _serialise(minute: int, b: dict[str, Any]) -> dict[str, Any]:
    total_vol = b["buy_vol"] + b["sell_vol"]
    out = {
        "minute_ms": minute,
        "n_trades": b["n_trades"],
        "buy_vol": round(b["buy_vol"], 10),
        "sell_vol": round(b["sell_vol"], 10),
        "buy_quote": round(b["buy_quote"], 6),
        "sell_quote": round(b["sell_quote"], 6),
        "buy_count": b["buy_count"],
        "sell_count": b["sell_count"],
        "sum_qty_sq": round(b["sum_qty_sq"], 12),
        "large_buy_vol": round(b["large_buy_vol"], 10),
        "large_sell_vol": round(b["large_sell_vol"], 10),
        "first_price": b["first_price"],
        "last_price": b["last_price"],
        "high": b["high"],
        "low": b["low"],
        "max_trade_qty": b["max_trade_qty"],
        "min_interarrival_ms": b["min_interarrival_ms"],
        "total_vol": round(total_vol, 10),
        # available_at = close of the minute + 1 ms: the row is only usable on
        # the NEXT decision (§18).
        "available_at": minute + MINUTE_MS + 1,
    }
    return out


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rebuild_manifest() -> dict[str, Any]:
    """Rebuild the manifest from every AGG_*.json on disk.

    The manifest is derived, never authoritative: each aggregate file carries
    its own provenance (source URL, source zip SHA-256, timestamp unit), so the
    manifest can always be reconstructed from the data alone. This makes the
    fetch resumable per asset/split without losing earlier provenance.
    """
    files: list[dict[str, Any]] = []
    for name in sorted(os.listdir(DATA)):
        if not name.startswith("AGG_") or not name.endswith(".json"):
            continue
        path = os.path.join(DATA, name)
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        agg = obj.get("aggregation", {})
        files.append(
            {
                "symbol": obj["symbol"],
                "day": obj["day"],
                "split": obj["split"],
                "url": obj["source_url"],
                "source_zip_sha256": obj.get("source_zip_sha256"),
                "source_zip_bytes": obj.get("source_zip_bytes"),
                "source_timestamp_unit": agg.get("source_timestamp_unit"),
                "rows": len(obj["rows"]),
                "derived_sha256": _sha256_bytes(json.dumps(obj, sort_keys=True).encode()),
                "cached": True,
            }
        )
    files.sort(key=lambda f: (f["day"], f["symbol"]))
    manifest: dict[str, Any] = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "rebuilt_from_files": True,
        "source_id": "SRC-04",
        "url_template": BASE,
        "schema": "aggTradeId,price,qty,firstTradeId,lastTradeId,timestamp,isBuyerMaker,isBestMatch",
        "large_trade_notional_usd": LARGE_TRADE_NOTIONAL_USD,
        "minute_ms": MINUTE_MS,
        "sample_days": SAMPLE_DAYS,
        "sample_declared_limitation": (
            "14 discontinuous days across 2026-03..2026-09; conclusions are "
            "about this sample, not the full period"
        ),
        "files": files,
        "missing_days": [],
        "source_timestamp_units": sorted(
            {str(f.get("source_timestamp_unit")) for f in files if f.get("source_timestamp_unit")}
        ),
        "total_files": len(files),
        "total_minute_rows": sum(int(f["rows"]) for f in files),
        "total_source_zip_bytes": sum(int(f.get("source_zip_bytes") or 0) for f in files),
    }
    with open(os.path.join(DATA, "MANIFEST_AGGTRADES.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="BTC,ETH,SOL")
    ap.add_argument("--split", default="all", help="all|DEV|VAL|OOS")
    ap.add_argument(
        "--rebuild-manifest",
        action="store_true",
        help="rebuild MANIFEST_AGGTRADES.json from the AGG_*.json files already on disk",
    )
    args = ap.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    os.makedirs(DATA, exist_ok=True)

    if args.rebuild_manifest:
        m = rebuild_manifest()
        print(
            f"manifest rebuilt: {m['total_files']} files, {m['total_minute_rows']} rows, "
            f"units={m['source_timestamp_units']}"
        )
        sys.exit(0)

    plan: list[tuple[str, str, str]] = []
    for split, days in SAMPLE_DAYS.items():
        if args.split != "all" and split != args.split:
            continue
        for day in days:
            for a in assets:
                plan.append((split, day, a))

    manifest: dict[str, Any] = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "source_id": "SRC-04",
        "url_template": BASE,
        "schema": "aggTradeId,price,qty,firstTradeId,lastTradeId,timestamp,isBuyerMaker,isBestMatch",
        "large_trade_notional_usd": LARGE_TRADE_NOTIONAL_USD,
        "minute_ms": MINUTE_MS,
        "sample_days": SAMPLE_DAYS,
        "sample_declared_limitation": (
            "14 discontinuous days across 2026-03..2026-09; conclusions are "
            "about this sample, not the full period"
        ),
        "files": [],
        "missing_days": [],
    }

    done = 0
    for split, day, asset in plan:
        sym = f"{asset}USDT"
        url = BASE.format(sym=sym, day=day)
        out_path = os.path.join(DATA, f"AGG_{sym}_{day}.json")
        done += 1
        if os.path.exists(out_path):
            print(f"[{done}/{len(plan)}] {sym} {day} cached", flush=True)
            with open(out_path, encoding="utf-8") as fh:
                existing = json.load(fh)
            manifest["files"].append(
                {
                    "symbol": sym,
                    "day": day,
                    "split": split,
                    "url": url,
                    "rows": len(existing["rows"]),
                    "source_timestamp_unit": existing.get("aggregation", {}).get(
                        "source_timestamp_unit"
                    ),
                    "derived_sha256": _sha256_bytes(
                        json.dumps(existing, sort_keys=True).encode()
                    ),
                    "cached": True,
                }
            )
            continue
        print(f"[{done}/{len(plan)}] {sym} {day} downloading", flush=True)
        payload = _http_bytes(url)
        if payload is None:
            print(f"  MISSING (404): {day} {sym}", flush=True)
            manifest["missing_days"].append({"symbol": sym, "day": day, "reason": "HTTP 404"})
            continue
        src_hash = _sha256_bytes(payload)
        src_bytes = len(payload)
        buckets, ts_unit = aggregate_day(payload)
        if ts_unit != "milliseconds":
            print(f"  NOTE: source timestamp unit = {ts_unit}", flush=True)
        rows = [_serialise(m, buckets[m]) for m in sorted(buckets)]
        obj = {
            "symbol": sym,
            "day": day,
            "split": split,
            "source_id": "SRC-04",
            "source_url": url,
            "source_zip_sha256": src_hash,
            "source_zip_bytes": src_bytes,
            "aggregation": {
                "unit": "utc_minute",
                "source_timestamp_unit": ts_unit,
                "available_at": "minute_open + 60_001 ms",
                "large_trade_notional_usd": LARGE_TRADE_NOTIONAL_USD,
                "aggressor_from": "isBuyerMaker (True -> SELL aggressor)",
            },
            "rows": rows,
        }
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh)
        manifest["files"].append(
            {
                "symbol": sym,
                "day": day,
                "split": split,
                "url": url,
                "source_zip_sha256": src_hash,
                "source_zip_bytes": src_bytes,
                "rows": len(rows),
                "source_timestamp_unit": ts_unit,
                "derived_sha256": _sha256_bytes(json.dumps(obj, sort_keys=True).encode()),
            }
        )
        print(f"  -> {len(rows)} minute rows (zip {src_bytes} bytes, sha {src_hash[:12]})", flush=True)
        time.sleep(0.2)

    manifest["source_timestamp_units"] = sorted(
        {str(f.get("source_timestamp_unit", "milliseconds")) for f in manifest["files"]}
    )
    manifest["files"].sort(key=lambda f: (f["day"], f["symbol"]))
    manifest["total_files"] = len(manifest["files"])
    manifest["total_minute_rows"] = sum(int(f["rows"]) for f in manifest["files"])
    manifest["total_source_zip_bytes"] = sum(int(f.get("source_zip_bytes", 0)) for f in manifest["files"])
    with open(os.path.join(DATA, "MANIFEST_AGGTRADES.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(
        f"done: {manifest['total_files']} files, {manifest['total_minute_rows']} minute rows, "
        f"{len(manifest['missing_days'])} missing"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
