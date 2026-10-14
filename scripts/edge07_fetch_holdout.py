#!/usr/bin/env python
"""WP-EDGE-07 Track B — fetch the one window nobody has read: 2026-03-01 … now.

The local corpora end on `2026-02-28 23:00Z`, which is the last bar of the `trend` OOS window
WP-EDGE-01 (and WP-EDGE-02's robustness analysis) already read. A family that cleared the gate
on that window is therefore *not yet rejected*, not validated. This script builds the missing
thing: a period that begins on the first hour after that window and runs to the last closed hour
before the run.

Read-only public Binance REST (`/api/v3/klines`): market data only, no credentials, no order
API, no vendor beyond the same endpoint the frozen `reports/alpha-expansion-v1/data` corpus was
downloaded from. Rules this script keeps:

* **nothing is written into a frozen corpus** — the new shards go to ``data/edge07/holdout-1h/``
  and the frozen directories are read only to prove the new window does not overlap them;
* **no interpolation and no synthesis**: a missing hour is recorded as a gap, never filled;
* **the bytes are pinned**: one SHA-256 per shard, the exact requested range, the response count
  and the first/last bar per symbol all travel in ``_FETCH_MANIFEST.json``, so the validation can
  be tied to the bytes it was measured on.

Usage::

    python scripts/edge07_fetch_holdout.py            # fetch what is missing, write the manifest
    python scripts/edge07_fetch_holdout.py --status    # report coverage, fetch nothing
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_DIR = REPO_ROOT / "data" / "edge07" / "holdout-1h"
MANIFEST = OUT_DIR / "_FETCH_MANIFEST.json"
FROZEN_1H = REPO_ROOT / "reports" / "alpha-expansion-v1" / "data"

SCHEMA_VERSION = "EDGE07_HOLDOUT_FETCH_V1"
SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
INTERVAL = "1h"
LIMIT = 1000
HOUR_MS = 3_600_000
SOURCE = "BINANCE_PUBLIC_REST:/api/v3/klines"

#: The first hour after the last bar of the frozen corpora (2026-02-28 23:00Z).
START_MS = 1_772_323_200_000
#: How far the fetch is allowed to walk if the endpoint keeps answering.
SAFETY_END_MS = 1_800_000_000_000


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def last_closed_hour_ms() -> int:
    return (now_ms() // HOUR_MS) * HOUR_MS - HOUR_MS


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_klines(symbol: str, start: int, end: int) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """Every closed 1h bar in ``[start, end)``. A gap is left absent, never filled."""
    rows: list[list[Any]] = []
    failures: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={INTERVAL}&startTime={cursor}"
            f"&endTime={end - 1}&limit={LIMIT}"
        )
        batch: list[list[Any]] | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    batch = json.loads(response.read().decode())
                break
            except Exception as exc:  # a network fact, recorded rather than hidden
                failures.append(
                    {
                        "symbol": symbol,
                        "at_ms": cursor,
                        "attempt": attempt + 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                time.sleep(1.5 * (attempt + 1))
        if batch is None:
            break
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + HOUR_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        # A short page means the rest of the window does not exist yet: stop instead of
        # asking for a range the endpoint has already answered for.
        if len(batch) < LIMIT and cursor + HOUR_MS * LIMIT > end:
            break
        time.sleep(0.25)
    return rows, failures


def normalize(rows: list[list[Any]]) -> list[dict[str, float]]:
    bars: list[dict[str, float]] = []
    seen: set[int] = set()
    for row in rows:
        ts = int(row[0])
        if ts in seen:
            continue
        seen.add(ts)
        bars.append(
            {
                "ts": ts,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    bars.sort(key=lambda bar: bar["ts"])
    return bars


def gaps_of(bars: list[dict[str, float]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for previous, current in itertools.pairwise(bars):
        step = int(current["ts"]) - int(previous["ts"])
        if step != HOUR_MS:
            gaps.append(
                {
                    "after_utc": stamp(int(previous["ts"])),
                    "before_utc": stamp(int(current["ts"])),
                    "missing_hours": step // HOUR_MS - 1,
                    "step_hours": step / HOUR_MS,
                }
            )
    return gaps


def frozen_last_bar_ms() -> dict[str, int]:
    """The last bar of each frozen 1h shard, so the new window can be proved disjoint."""
    last: dict[str, int] = {}
    for symbol in SYMBOLS:
        base = symbol[:3]
        newest = 0
        for path in sorted(FROZEN_1H.glob(f"{base}USDT_*.json")):
            if path.name.startswith("_"):
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
            if rows:
                newest = max(newest, int(rows[-1]["ts"]))
        last[base] = newest
    return last


def status() -> int:
    if not MANIFEST.is_file():
        print(f"no manifest at {MANIFEST}; nothing has been fetched")
        return 1
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for symbol in SYMBOLS:
        entry = (payload.get("symbols") or {}).get(symbol) or {}
        print(
            f"{symbol:<8} {entry.get('bars', 0):>6} bars  "
            f"{entry.get('first_utc')} .. {entry.get('last_utc')}  "
            f"gaps={entry.get('gaps')}  sha256={(entry.get('sha256') or '')[:16]}…"
        )
    print(f"requested range: {payload.get('requested_range')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--status", action="store_true", help="report coverage and exit")
    parser.add_argument("--end-ms", type=int, default=None, help="override the exclusive end")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    if options.status:
        return status()

    end = int(options.end_ms) if options.end_ms else last_closed_hour_ms()
    if end <= START_MS:
        print(f"the requested end {stamp(end)} is not after the start {stamp(START_MS)}")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frozen_last = frozen_last_bar_ms()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "fetched_at_utc": stamp(now_ms()),
        "source": SOURCE,
        "interval": INTERVAL,
        "requested_range": {"start_utc": stamp(START_MS), "end_utc_exclusive": stamp(end)},
        "requested_range_ms": [START_MS, end],
        "normalization": (
            "list of {ts,open,high,low,close,volume}; ts = bar OPEN time (ms, UTC); floats; "
            "no interpolation, no synthesis, gaps left absent"
        ),
        "disjoint_from_frozen_corpora": {
            "frozen_last_bar_utc": {
                symbol: stamp(ts) for symbol, ts in sorted(frozen_last.items())
            },
            "new_window_starts_utc": stamp(START_MS),
            "disjoint": all(ts < START_MS for ts in frozen_last.values()),
        },
        "symbols": {},
        "failures": [],
    }
    if not payload["disjoint_from_frozen_corpora"]["disjoint"]:
        print("refusing: the requested window overlaps a frozen corpus", file=sys.stderr)
        return 2

    for symbol in SYMBOLS:
        raw_rows, failures = fetch_klines(symbol, START_MS, end)
        bars = normalize(raw_rows)
        gaps = gaps_of(bars)
        path = OUT_DIR / f"{symbol}_holdout2026.json"
        path.write_text(
            json.dumps(bars, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        payload["failures"].extend(failures)
        payload["symbols"][symbol] = {
            "bars": len(bars),
            "rows_returned": len(raw_rows),
            "duplicates_removed": len(raw_rows) - len(bars),
            "first_utc": stamp(int(bars[0]["ts"])) if bars else None,
            "last_utc": stamp(int(bars[-1]["ts"])) if bars else None,
            "gaps": len(gaps),
            "gap_examples": gaps[:5],
            "expected_hours": (end - START_MS) // HOUR_MS,
            "coverage_pct": round(len(bars) / max(1, (end - START_MS) // HOUR_MS) * 100, 4),
            "shard": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        }
        print(
            f"{symbol:<8} {len(bars):>6} bars  "
            f"{payload['symbols'][symbol]['first_utc']} .. {payload['symbols'][symbol]['last_utc']}  "
            f"gaps={len(gaps)}  coverage={payload['symbols'][symbol]['coverage_pct']}%"
        )

    payload["totals"] = {
        "bars": sum(int(entry["bars"]) for entry in payload["symbols"].values()),
        "bytes": sum(int(entry["bytes"]) for entry in payload["symbols"].values()),
        "gaps": sum(int(entry["gaps"]) for entry in payload["symbols"].values()),
        "failures": len(payload["failures"]),
    }
    payload["corpus_digest"] = hashlib.sha256(
        json.dumps(
            {symbol: entry["sha256"] for symbol, entry in sorted(payload["symbols"].items())},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"manifest {MANIFEST.relative_to(REPO_ROOT)}: "
        f"{payload['totals']['bars']} bars, {payload['totals']['bytes'] / 1024:.1f} KiB, "
        f"{payload['totals']['gaps']} gaps, digest {payload['corpus_digest'][:16]}…"
    )
    if options.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["totals"]["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
