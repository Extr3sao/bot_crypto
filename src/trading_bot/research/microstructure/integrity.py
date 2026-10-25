"""Temporal integrity and adversarial data checks (§18, §64-65).

All validators FAIL CLOSED: any structural violation raises
``DataIntegrityError`` rather than silently dropping or repairing the datum.
Research code must never "fix" bad data into a backtest.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BookSnapshot",
    "DataIntegrityError",
    "IntegrityReport",
    "check_book_snapshot",
    "check_ordering_and_duplicates",
    "check_price_series",
    "classify_gaps",
    "pit_slice",
]


class DataIntegrityError(ValueError):
    """Raised when input data violates a fail-closed invariant."""


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Result of a non-fatal integrity scan (gaps are reported, not raised)."""

    n: int
    duplicates: int = 0
    out_of_order: int = 0
    gaps: int = 0
    worst_gap_ms: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """Top-of-book / depth snapshot for adversarial checks.

    ``bids`` and ``asks`` are lists of ``(price, qty)``.
    """

    timestamp: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


def check_price_series(prices: Sequence[float], name: str = "prices") -> None:
    """Fail closed on non-positive or non-finite prices."""
    if len(prices) == 0:
        raise DataIntegrityError(f"{name}: empty series")
    for i, p in enumerate(prices):
        if not (p > 0.0):
            raise DataIntegrityError(f"{name}[{i}] = {p} is not > 0")


def check_ordering_and_duplicates(timestamps: Sequence[int], name: str = "ts") -> None:
    """Fail closed on non-monotonic timestamps or duplicates."""
    counts = Counter(timestamps)
    dups = [t for t, c in counts.items() if c > 1]
    if dups:
        raise DataIntegrityError(f"{name}: {len(dups)} duplicate timestamp(s), e.g. {dups[:3]}")
    for i in range(1, len(timestamps)):
        if timestamps[i] <= timestamps[i - 1]:
            raise DataIntegrityError(
                f"{name}: out-of-order at index {i} ({timestamps[i - 1]} -> {timestamps[i]})"
            )


def classify_gaps(timestamps: Sequence[int], expected_ms: int) -> IntegrityReport:
    """Report gaps in a strictly increasing timestamp series.

    A gap is any step strictly greater than ``expected_ms``. This does not
    raise: a gap is a fact to be reported, but downstream code must decide.
    """
    if expected_ms <= 0:
        raise DataIntegrityError("expected_ms must be > 0")
    gaps = 0
    worst = 0
    for i in range(1, len(timestamps)):
        step = timestamps[i] - timestamps[i - 1]
        if step > expected_ms:
            gaps += 1
            worst = max(worst, step)
    return IntegrityReport(n=len(timestamps), gaps=gaps, worst_gap_ms=worst)


def pit_slice(records: list[Any], decision_time: int) -> list[Any]:
    """Return only records knowable at ``decision_time`` (§18).

    Generic over any object exposing ``available_at``.
    """
    return [r for r in records if r.available_at <= decision_time]


def check_book_snapshot(snapshot: BookSnapshot) -> None:
    """Adversarial order-book checks (§65): fail closed on any violation.

    Rejects: crossed book, zero/negative bid or ask, negative quantity,
    empty/one-sided book, non-monotonic price levels.
    """
    if not snapshot.bids or not snapshot.asks:
        raise DataIntegrityError("book: empty side")
    bids = snapshot.bids
    asks = snapshot.asks
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    if best_bid <= 0.0 or best_ask <= 0.0:
        raise DataIntegrityError(f"book: zero/negative top of book bid={best_bid} ask={best_ask}")
    if best_bid >= best_ask:
        raise DataIntegrityError(f"book: crossed/locked bid={best_bid} >= ask={best_ask}")
    prev = None
    for price, qty in bids:
        if qty < 0.0:
            raise DataIntegrityError(f"book: negative bid qty at {price}")
        if prev is not None and price > prev:
            raise DataIntegrityError("book: bids not sorted descending")
        prev = price
    prev = None
    for price, qty in asks:
        if qty < 0.0:
            raise DataIntegrityError(f"book: negative ask qty at {price}")
        if prev is not None and price < prev:
            raise DataIntegrityError("book: asks not sorted ascending")
        prev = price
