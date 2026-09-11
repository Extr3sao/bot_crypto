"""Deterministic data-quality engine for admitted data families.

ALPHA-DATA-ADMISSION-01 Track F. Pure functions over canonical records; no
network access; no alpha/performance semantics whatsoever.

Core PIT invariant: ``data_time <= decision_time`` — every record whose data
time is after the supplied decision cutoff is flagged as FUTURE_RECORD and
excluded from normalized state produced with that cutoff (future-mutation
safety is unit-tested in Track N).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import TypeVar

from trading_bot.research.data_contracts import (
    OpenInterestRecord,
    TradeFlowRecord,
)

NORMALIZER_VERSION = "1.0.0"

T = TypeVar("T")


# ---------------------------------------------------------------------------
# PIT / future-mutation core
# ---------------------------------------------------------------------------


def enforce_pit_cutoff(
    records: Sequence[T],
    time_of: object,
    decision_time_ms: int,
) -> tuple[list[T], list[T]]:
    """Split records into (allowed, future) by ``data_time <= decision_time``.

    ``time_of`` is a callable returning the record's data time in ms.
    Future records are REPORTED, never silently dropped, so callers can
    assert PIT safety explicitly.
    """
    allowed: list[T] = []
    future: list[T] = []
    for rec in records:
        t = time_of(rec)  # type: ignore[operator]
        (allowed if t <= decision_time_ms else future).append(rec)
    return allowed, future


# ---------------------------------------------------------------------------
# Generic quality checks
# ---------------------------------------------------------------------------


def check_time_ordering(times_ms: Sequence[int]) -> list[str]:
    """Non-strict monotonicity violations (indices of out-of-order records)."""
    return [i for i in range(1, len(times_ms)) if times_ms[i] < times_ms[i - 1]]


def check_duplicates(values: Sequence[object]) -> list[object]:
    """Return the duplicated values as-is (first occurrence kept)."""
    seen: set[object] = set()
    dupes: list[object] = []
    for v in values:
        if v in seen:
            dupes.append(v)
        else:
            seen.add(v)
    return dupes


def check_missing_intervals(
    times_ms: Sequence[int],
    interval_ms: int,
    *,
    tolerance_pct: float = 0.0,
) -> list[int]:
    """Indices where the gap to the previous timestamp exceeds the interval.

    Only meaningful for families with fixed-cadence semantics (metrics OI).
    ``tolerance_pct`` allows fractional-cadence slack (0 = exact).
    """
    gaps: list[int] = []
    allowed = float(interval_ms) * (1.0 + tolerance_pct)
    for i in range(1, len(times_ms)):
        if times_ms[i] - times_ms[i - 1] > allowed:
            gaps.append(i)
    return gaps


def check_stale_tail(times_ms: Sequence[int], now_ms: int, max_age_ms: int) -> bool:
    """True if the newest record is older than ``max_age_ms`` vs ``now_ms``."""
    return not times_ms or (now_ms - max(times_ms)) > max_age_ms


# ---------------------------------------------------------------------------
# Family-specific normalization + quality
# ---------------------------------------------------------------------------


def normalize_trade_flow(
    records: Sequence[TradeFlowRecord],
    decision_time_ms: int,
) -> dict[str, object]:
    """Deterministic normalized state for trade flow.

    Sorts by (trade_time_ms, agg_trade_id); enforces agg_trade_id uniqueness;
    reports ordering violations; excludes future records via PIT cutoff.
    """
    errors: dict[str, object] = {}
    allowed, future = enforce_pit_cutoff(
        records, lambda r: r.trade_time_ms, decision_time_ms
    )
    if future:
        errors["FUTURE_RECORDS"] = [r.agg_trade_id for r in future]

    ordered = sorted(allowed, key=lambda r: (r.trade_time_ms, r.agg_trade_id))
    order_violations = [
        i
        for i in range(1, len(ordered))
        if ordered[i].trade_time_ms < ordered[i - 1].trade_time_ms
    ]
    if order_violations:
        errors["ORDER_VIOLATIONS"] = order_violations

    id_dupes = check_duplicates([r.agg_trade_id for r in ordered])
    if id_dupes:
        errors["DUPLICATE_AGG_TRADE_IDS"] = id_dupes

    invalid: list[str] = []
    for r in ordered:
        if r.price <= 0:
            invalid.append(f"price:{r.agg_trade_id}")
        if r.quantity <= 0:
            invalid.append(f"quantity:{r.agg_trade_id}")
        if r.first_trade_id > r.last_trade_id:
            invalid.append(f"trade_id_bounds:{r.agg_trade_id}")
    if invalid:
        errors["INVALID_RECORDS"] = invalid

    taker_buy_qty = sum(r.quantity for r in ordered if r.taker_side.value == "TAKER_BUY")
    taker_sell_qty = sum(r.quantity for r in ordered if r.taker_side.value == "TAKER_SELL")
    return {
        "rows_total": len(records),
        "rows_within_pit": len(ordered),
        "time_min_ms": ordered[0].trade_time_ms if ordered else None,
        "time_max_ms": ordered[-1].trade_time_ms if ordered else None,
        "taker_buy_qty": taker_buy_qty,
        "taker_sell_qty": taker_sell_qty,
        "errors": errors,
    }


def normalize_open_interest(
    records: Sequence[OpenInterestRecord],
    decision_time_ms: int,
    expected_interval_ms: int = 300_000,
) -> dict[str, object]:
    """Deterministic normalized state for open interest.

    Native provider cadence is 5m (288 complete rows per UTC day; official
    metrics archive, DEF-DATA-OI-001 reconciliation: previously mis-declared
    as 15m). Sorts by timestamp; PIT cutoff; zero/negative checks;
    missing-interval (gap) report against the expected cadence; NO
    interpolation or backfill. Provider files are not guaranteed row-sorted;
    canonical state is produced after a deterministic sort.
    """
    errors: dict[str, object] = {}
    allowed, future = enforce_pit_cutoff(
        records, lambda r: r.timestamp_ms, decision_time_ms
    )
    if future:
        errors["FUTURE_RECORDS"] = [r.timestamp_ms for r in future]

    ordered = sorted(allowed, key=lambda r: r.timestamp_ms)
    order_violations = [
        i for i in range(1, len(ordered)) if ordered[i].timestamp_ms < ordered[i - 1].timestamp_ms
    ]
    if order_violations:
        errors["ORDER_VIOLATIONS"] = order_violations

    gaps = check_missing_intervals([r.timestamp_ms for r in ordered], expected_interval_ms)
    if gaps:
        errors["MISSING_INTERVALS"] = [ordered[i].timestamp_ms for i in gaps]

    invalid: list[str] = []
    for r in ordered:
        if r.open_interest_contracts < 0:
            invalid.append(f"oi_contracts:{r.timestamp_ms}")
        if r.open_interest_value < 0:
            invalid.append(f"oi_value:{r.timestamp_ms}")
    if invalid:
        errors["INVALID_RECORDS"] = invalid

    return {
        "rows_total": len(records),
        "rows_within_pit": len(ordered),
        "time_min_ms": ordered[0].timestamp_ms if ordered else None,
        "time_max_ms": ordered[-1].timestamp_ms if ordered else None,
        "expected_interval_ms": expected_interval_ms,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Deterministic fingerprinting (Track H)
# ---------------------------------------------------------------------------


def _canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def dataset_fingerprint(payload: dict[str, object]) -> str:
    """Stable canonical fingerprint: same inputs -> same hash, any dict order."""
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def fingerprint_trade_flow(
    records: Sequence[TradeFlowRecord],
    *,
    asset: str,
    time_range_ms: tuple[int, int],
    schema_version: str,
    normalizer_version: str,
    source_file_hashes: list[str],
) -> str:
    return dataset_fingerprint(
        {
            "family": "trade_flow",
            "asset": asset,
            "row_count": len(records),
            "time_range_ms": list(time_range_ms),
            "schema_version": schema_version,
            "normalizer_version": normalizer_version,
            "source_file_hashes": sorted(source_file_hashes),
            "rows": [
                [
                    r.agg_trade_id,
                    r.price,
                    r.quantity,
                    r.first_trade_id,
                    r.last_trade_id,
                    r.trade_time_ms,
                    r.buyer_is_maker,
                ]
                for r in sorted(records, key=lambda r: (r.trade_time_ms, r.agg_trade_id))
            ],
        }
    )


def fingerprint_open_interest(
    records: Sequence[OpenInterestRecord],
    *,
    asset: str,
    time_range_ms: tuple[int, int],
    schema_version: str,
    normalizer_version: str,
    source_file_hashes: list[str],
) -> str:
    return dataset_fingerprint(
        {
            "family": "open_interest",
            "asset": asset,
            "row_count": len(records),
            "time_range_ms": list(time_range_ms),
            "schema_version": schema_version,
            "normalizer_version": normalizer_version,
            "source_file_hashes": sorted(source_file_hashes),
            "rows": [
                [r.timestamp_ms, r.open_interest_contracts, r.open_interest_value, r.period]
                for r in sorted(records, key=lambda r: r.timestamp_ms)
            ],
        }
    )
