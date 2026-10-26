"""ALPHA-002 — the derivatives series that only exist forwards in time.

Why this module exists at all: unlike price, the derivatives participant data that
ALPHA-002 wants to test is **not** available as history.  Measured on 2026-10-07,
Binance retains every ``/futures/data/*`` series (open interest, taker buy/sell
volume, global and top-trader long/short ratios) for **exactly 30 days at every
granularity** — 18 pages of 500 at 5m, then an empty page — and there is no
vendor or archive that backfills it.  Funding rate is the exception: it is
retained in full since 2019.

So a question about derivatives positioning is only answerable from the moment
capture starts.  Every day without a capture run is a day of information
destroyed, and no later re-run can recover it.

This module holds the pure, offline half of that capture: the frozen series
registry, merging without duplication, coverage, gap detection and the manifest
shape.  The network half lives in ``scripts/alpha002_capture.py`` so that the
logic which decides *what the dataset is* stays testable without a socket.

Design rules it encodes:

* **Source fidelity.**  Records are stored exactly as the venue returns them,
  strings included; nothing is parsed into floats on the way to disk.  That includes
  venue quirks: ``fundingTime`` carries a sub-millisecond jitter (3360 of 7752
  BTCUSDT rows are off the exact 8h boundary), so a consumer must align funding to
  the grid rather than assume exact timestamps.
* **Append-only and idempotent.**  Merging the same window twice changes nothing
  but the fetch log.
* **Gaps are recorded, not hidden.**  A missing bucket is a fact about the
  dataset, and a downstream hypothesis must be able to refuse to run without it.
* **No credentials, no orders.**  Public market data only.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Any

__all__ = [
    "PAGE_LIMIT",
    "PERIODS",
    "RETAINED_DAYS",
    "SERIES",
    "UNIVERSE",
    "coverage",
    "find_gaps",
    "merge_records",
    "period_ms",
    "series_by_id",
    "series_digest",
]

#: The preregistered traded universe.  Four assets, deliberately small: ALPHA-002
#: is a first campaign over a new information source, not a wide sweep.
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

#: Granularities to capture.  5m and 15m feed entries, 1h feeds the regime filter,
#: 1d keeps the campaign comparable with the daily work in ALPHA-001.
PERIODS = ("5m", "15m", "1h", "1d")

#: Measured retention of the ``/futures/data/*`` family, in days.  Not a guess and
#: not a documentation claim: paginating backwards from now returns 30.0 days and
#: then an empty page.  ``funding_rate`` is not subject to it.
RETAINED_DAYS = 30.0

#: Venue page size for these endpoints.
PAGE_LIMIT = 500

_PERIOD_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}

#: The frozen series registry.  ``periodic`` series take the ``period`` parameter
#: and are retention-limited; ``funding_rate`` is a full-history endpoint paged by
#: time range instead.
SERIES: tuple[dict[str, Any], ...] = (
    {
        "series_id": "open_interest_hist",
        "path": "/futures/data/openInterestHist",
        "periodic": True,
        "timestamp_key": "timestamp",
        "value_keys": ("sumOpenInterest", "sumOpenInterestValue"),
        "retention_limited": True,
        "mechanism": "outstanding derivative exposure, i.e. whether a move is new positioning",
    },
    {
        "series_id": "taker_long_short_ratio",
        "path": "/futures/data/takerlongshortRatio",
        "periodic": True,
        "timestamp_key": "timestamp",
        "value_keys": ("buySellRatio", "buyVol", "sellVol"),
        "retention_limited": True,
        "mechanism": "aggressor-side flow, i.e. who is crossing the spread",
    },
    {
        "series_id": "global_long_short_account_ratio",
        "path": "/futures/data/globalLongShortAccountRatio",
        "periodic": True,
        "timestamp_key": "timestamp",
        "value_keys": ("longShortRatio", "longAccount", "shortAccount"),
        "retention_limited": True,
        "mechanism": "retail crowding, the population most likely to be wrong at extremes",
    },
    {
        "series_id": "top_long_short_account_ratio",
        "path": "/futures/data/topLongShortAccountRatio",
        "periodic": True,
        "timestamp_key": "timestamp",
        "value_keys": ("longShortRatio", "longAccount", "shortAccount"),
        "retention_limited": True,
        "mechanism": "large-account positioning by account count",
    },
    {
        "series_id": "top_long_short_position_ratio",
        "path": "/futures/data/topLongShortPositionRatio",
        "periodic": True,
        "timestamp_key": "timestamp",
        "value_keys": ("longShortRatio", "longAccount", "shortAccount"),
        "retention_limited": True,
        "mechanism": "large-account positioning weighted by size, not headcount",
    },
    {
        "series_id": "funding_rate",
        "path": "/fapi/v1/fundingRate",
        "periodic": False,
        "timestamp_key": "fundingTime",
        "value_keys": ("fundingRate", "markPrice"),
        "retention_limited": False,
        "mechanism": "the price of holding one side of the book, i.e. the carry",
    },
)


def series_by_id(series_id: str) -> dict[str, Any]:
    """Look up a frozen series spec, or raise."""
    for item in SERIES:
        if item["series_id"] == series_id:
            return item
    raise KeyError(f"unknown series_id: {series_id}")


def period_ms(period: str) -> int:
    """Milliseconds between two buckets of a granularity."""
    if period not in _PERIOD_MS:
        raise ValueError(f"unsupported period: {period}")
    return _PERIOD_MS[period]


def merge_records(
    existing: Sequence[dict[str, Any]],
    incoming: Iterable[dict[str, Any]],
    *,
    timestamp_key: str = "timestamp",
) -> list[dict[str, Any]]:
    """Union two record sets by timestamp, newest value winning on a collision.

    Re-running a capture over a window already stored must be a no-op, and a
    venue correction to a recent bucket must overwrite the earlier reading.
    """
    merged: dict[int, dict[str, Any]] = {}
    for record in existing:
        merged[int(record[timestamp_key])] = record
    for record in incoming:
        merged[int(record[timestamp_key])] = record
    return [merged[stamp] for stamp in sorted(merged)]


def coverage(
    records: Sequence[dict[str, Any]], *, timestamp_key: str = "timestamp"
) -> dict[str, Any]:
    """Count, first and last bucket of a stored series."""
    if not records:
        return {"count": 0, "first_ts": None, "last_ts": None, "span_days": 0.0}
    first = int(records[0][timestamp_key])
    last = int(records[-1][timestamp_key])
    return {
        "count": len(records),
        "first_ts": first,
        "last_ts": last,
        "span_days": round((last - first) / 86_400_000.0, 6),
    }


def find_gaps(
    records: Sequence[dict[str, Any]], *, step_ms: int, timestamp_key: str = "timestamp"
) -> list[dict[str, int]]:
    """Missing buckets inside the stored span.

    Deliberately reports gaps rather than papering over them: a hypothesis that
    needs a continuous 5m series must be able to refuse to run on a patchy one.
    """
    if step_ms <= 0:
        raise ValueError("step_ms must be > 0")
    gaps: list[dict[str, int]] = []
    for previous, current in pairwise(records):
        left = int(previous[timestamp_key])
        right = int(current[timestamp_key])
        missing = (right - left) // step_ms - 1
        if missing > 0:
            gaps.append(
                {"after_ts": left, "before_ts": right, "missing_buckets": int(missing)}
            )
    return gaps


def series_digest(records: Sequence[dict[str, Any]]) -> str:
    """Stable content digest of a stored series, for the manifest."""
    payload = json.dumps(list(records), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
