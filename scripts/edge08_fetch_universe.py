#!/usr/bin/env python
"""WP-EDGE-08A — fetch the one resource that is still unread: the symbol dimension.

Every time-based resource this project could read has been read. The ``trend`` OOS window
(2025-01-01 … 2026-02-28) was consulted by WP-EDGE-01 and WP-EDGE-02, the ``NEW_HOLDOUT``
window WP-EDGE-07 created (2026-03-01 … 2026-10-14) was read once and spent, and both clocks of
the BTC/ETH/SOL universe have been measured for every family registered so far. What has *not*
been read is a **cross-section**: liquid majors whose bar history no committed artefact of this
repository has ever measured.

This script builds it. Six Binance spot USDT pairs — AAVE, UNI, MKR, SNX, CRV and SUSHI — are
fetched at 1h from 2021-01-01 to the last closed hour, read-only public REST
(``/api/v3/klines``): market data only, no credentials, no order API, and the same endpoint the
frozen corpora were downloaded from.

Two rules this script keeps, and the reason it is written this way:

* **the claim is checkable, so the script checks it.** Before fetching anything it scans the
  corpora this repository already holds (``reports/alpha-expansion-v1/data``,
  ``data/raw/alpha003/price``, ``data/edge07/holdout-1h``) for a shard of any of these symbols
  and refuses to continue if one exists. A symbol that already has a local corpus is not a
  holdout, it is a re-read.
* **nothing is written into a frozen corpus and nothing is interpolated.** The shards go to
  ``data/edge08/universe-1h/``; a missing hour is recorded as a gap and left absent; one SHA-256
  per shard, the exact requested range, the bar counts and the first/last bar per symbol travel
  in ``_FETCH_MANIFEST.json``, so a reading can be tied to the bytes it was measured on.

Usage::

    python scripts/edge08_fetch_universe.py            # fetch what is missing, write the manifest
    python scripts/edge08_fetch_universe.py --status    # report coverage, fetch nothing
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

OUT_DIR = REPO_ROOT / "data" / "edge08" / "universe-1h"
MANIFEST = OUT_DIR / "_FETCH_MANIFEST.json"

#: The corpora this repository already holds. A symbol with a shard here is not a holdout.
EXISTING_CORPORA: tuple[Path, ...] = (
    REPO_ROOT / "reports" / "alpha-expansion-v1" / "data",
    REPO_ROOT / "data" / "raw" / "alpha003" / "price",
    REPO_ROOT / "data" / "edge07" / "holdout-1h",
)

SCHEMA_VERSION = "EDGE08_UNIVERSE_FETCH_V1"
SYMBOLS: tuple[str, ...] = ("AAVEUSDT", "UNIUSDT", "KSMUSDT", "SNXUSDT", "CRVUSDT", "SUSHIUSDT")
INTERVAL = "1h"
LIMIT = 1000
HOUR_MS = 3_600_000
SOURCE = "BINANCE_PUBLIC_REST:/api/v3/klines"

#: A symbol must cover the requested range to this fraction of its hours or it is not usable as
#: part of the cross-section. MKRUSDT was in the first draft of this universe and was dropped by
#: exactly this check before the registration was committed: MKR stops trading on 2025-09-15
#: (the SKY migration), so it cannot cover the decisive window 2025-01-01 onwards. The check runs
#: here, on coverage, before any strategy touches a bar.
COVERAGE_FLOOR_PCT = 99.0

#: 2021-01-01T00:00:00Z. Six symbols listed between 2018 and 2020 all have bars here, and the
#: window gives the decisive out-of-sample split (2025-01-01 onwards) a three-year warm-up of
#: *unread* history behind it — the whole span is new for these symbols, not only its tail.
START_MS = 1_609_459_200_000
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


def existing_shards(symbol: str) -> list[str]:
    """Every local corpus file that already holds bars for ``symbol`` (must be empty)."""
    base = symbol[: len(symbol) - 4]
    found: list[str] = []
    for root in EXISTING_CORPORA:
        if not root.is_dir():
            continue
        for path in sorted(root.glob(f"{base}USDT*")):
            found.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return found


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
        if batch is None or not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + HOUR_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < LIMIT and cursor + HOUR_MS * LIMIT > end:
            break
        time.sleep(0.25)
    return rows, failures


def normalize(rows: list[list[Any]]) -> list[list[float]]:
    """``[ts, open, high, low, close, volume]`` per closed bar, deduplicated, ts ascending."""
    bars: list[list[float]] = []
    seen: set[int] = set()
    for row in rows:
        ts = int(row[0])
        if ts in seen:
            continue
        seen.add(ts)
        bars.append(
            [
                float(ts),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
            ]
        )
    bars.sort(key=lambda bar: bar[0])
    return bars


def gaps_of(bars: list[list[float]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for previous, current in itertools.pairwise(bars):
        step = int(current[0]) - int(previous[0])
        if step != HOUR_MS:
            gaps.append(
                {
                    "after_utc": stamp(int(previous[0])),
                    "before_utc": stamp(int(current[0])),
                    "missing_hours": step // HOUR_MS - 1,
                    "step_hours": step / HOUR_MS,
                }
            )
    return gaps


def status() -> int:
    if not MANIFEST.is_file():
        print(f"no manifest at {MANIFEST}; nothing has been fetched")
        return 1
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for symbol in SYMBOLS:
        entry = (payload.get("symbols") or {}).get(symbol) or {}
        print(
            f"{symbol:<10} {entry.get('bars', 0):>6} bars  "
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

    # The holdout claim, checked before anything is downloaded.
    already_local = {symbol: existing_shards(symbol) for symbol in SYMBOLS}
    contaminated = {symbol: paths for symbol, paths in already_local.items() if paths}
    if contaminated:
        print(
            f"refusing: these symbols already have a local corpus, so they are not a holdout: "
            f"{contaminated}",
            file=sys.stderr,
        )
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "fetched_at_utc": stamp(now_ms()),
        "source": SOURCE,
        "interval": INTERVAL,
        "requested_range": {"start_utc": stamp(START_MS), "end_utc_exclusive": stamp(end)},
        "requested_range_ms": [START_MS, end],
        "normalization": (
            "list of [ts,open,high,low,close,volume]; ts = bar OPEN time (ms, UTC); ts as float, "
            "prices unrounded as the venue published them; no interpolation, no synthesis, gaps "
            "left absent"
        ),
        "unread_cross_section": {
            "claim": (
                "no corpus of this repository holds a bar of these symbols, and no committed "
                "strategy artefact has ever been measured on one"
            ),
            "corpora_scanned": [
                str(root.relative_to(REPO_ROOT)).replace("\\", "/") for root in EXISTING_CORPORA
            ],
            "existing_shards_found": already_local,
            "claim_holds": not contaminated,
        },
        "symbols": {},
        "failures": [],
    }

    for symbol in SYMBOLS:
        raw_rows, failures = fetch_klines(symbol, START_MS, end)
        bars = normalize(raw_rows)
        gaps = gaps_of(bars)
        path = OUT_DIR / f"{symbol}_2021_2026_1h.json"
        path.write_text(
            json.dumps(bars, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        payload["failures"].extend(failures)
        expected_hours = (end - START_MS) // HOUR_MS
        coverage_pct = round(len(bars) / max(1, expected_hours) * 100, 4)
        covers_end = bool(bars) and int(bars[-1][0]) >= end - 2 * HOUR_MS
        payload["symbols"][symbol] = {
            "asset": symbol[: len(symbol) - 4],
            "bars": len(bars),
            "rows_returned": len(raw_rows),
            "duplicates_removed": len(raw_rows) - len(bars),
            "first_utc": stamp(int(bars[0][0])) if bars else None,
            "last_utc": stamp(int(bars[-1][0])) if bars else None,
            "gaps": len(gaps),
            "gap_examples": gaps[:5],
            "expected_hours": expected_hours,
            "coverage_pct": coverage_pct,
            "covers_requested_end": covers_end,
            "coverage_floor_pct": COVERAGE_FLOOR_PCT,
            "coverage_floor_met": coverage_pct >= COVERAGE_FLOOR_PCT and covers_end,
            "shard": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        }
        print(
            f"{symbol:<10} {len(bars):>6} bars  "
            f"{payload['symbols'][symbol]['first_utc']} .. {payload['symbols'][symbol]['last_utc']}  "
            f"gaps={len(gaps)}  coverage={coverage_pct}%  "
            f"floor_met={payload['symbols'][symbol]['coverage_floor_met']}"
        )

    payload["totals"] = {
        "symbols": len(payload["symbols"]),
        "bars": sum(int(entry["bars"]) for entry in payload["symbols"].values()),
        "bytes": sum(int(entry["bytes"]) for entry in payload["symbols"].values()),
        "gaps": sum(int(entry["gaps"]) for entry in payload["symbols"].values()),
        "failures": len(payload["failures"]),
        "symbols_below_coverage_floor": [
            symbol
            for symbol, entry in payload["symbols"].items()
            if not entry["coverage_floor_met"]
        ],
    }
    payload["corpus_digest"] = hashlib.sha256(
        json.dumps(
            {symbol: entry["sha256"] for symbol, entry in sorted(payload["symbols"].items())},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"manifest {MANIFEST.relative_to(REPO_ROOT)}: {payload['totals']['bars']} bars, "
        f"{payload['totals']['bytes'] / 1024 / 1024:.1f} MiB, {payload['totals']['gaps']} gaps, "
        f"digest {payload['corpus_digest'][:16]}…"
    )
    if options.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    usable = not payload["totals"]["symbols_below_coverage_floor"]
    if not usable:
        print(
            f"WARNING: below the coverage floor: "
            f"{payload['totals']['symbols_below_coverage_floor']}",
            file=sys.stderr,
        )
    return 0 if payload["totals"]["failures"] == 0 and usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
