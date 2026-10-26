"""Integrity + adversarial data tests (§18, §64-65). Fail closed."""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.integrity import (
    BookSnapshot,
    DataIntegrityError,
    check_book_snapshot,
    check_ordering_and_duplicates,
    check_price_series,
    classify_gaps,
    pit_slice,
)
from trading_bot.research.microstructure.types import MicroBar


def _bar(event_time: int, available_at: int, close: float = 100.0) -> MicroBar:
    return MicroBar(
        event_time=event_time,
        available_at=available_at,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10.0,
        quote_volume=1000.0,
        trades=5,
        taker_buy_base=6.0,
        taker_buy_quote=600.0,
    )


# --- ordering / duplicates / gaps -----------------------------------------


def test_ordering_ok() -> None:
    check_ordering_and_duplicates([1, 2, 3, 4])


def test_duplicate_timestamp_fails_closed() -> None:
    with pytest.raises(DataIntegrityError):
        check_ordering_and_duplicates([1, 2, 2, 3])


def test_out_of_order_fails_closed() -> None:
    with pytest.raises(DataIntegrityError):
        check_ordering_and_duplicates([1, 3, 2])


def test_gap_detection() -> None:
    report = classify_gaps([0, 300_000, 600_000, 1_500_000], 300_000)
    assert report.gaps == 1
    assert report.worst_gap_ms == 900_000


def test_gap_is_reported_not_raised() -> None:
    report = classify_gaps([0, 600_000], 300_000)
    assert report.gaps == 1  # no exception


def test_classify_gaps_rejects_bad_expected() -> None:
    with pytest.raises(DataIntegrityError):
        classify_gaps([0, 1], 0)


# --- prices ----------------------------------------------------------------


def test_zero_price_fails_closed() -> None:
    with pytest.raises(DataIntegrityError):
        check_price_series([100.0, 0.0, 101.0])


def test_negative_price_fails_closed() -> None:
    with pytest.raises(DataIntegrityError):
        check_price_series([-1.0])


def test_empty_series_fails_closed() -> None:
    with pytest.raises(DataIntegrityError):
        check_price_series([])


# --- PIT ------------------------------------------------------------------


def test_pit_slice_excludes_future() -> None:
    a = _bar(0, 100)
    b = _bar(200, 300)
    c = _bar(400, 500)
    got = pit_slice([a, b, c], decision_time=350)
    assert got == [a, b]


def test_pit_slice_includes_available_at_boundary() -> None:
    a = _bar(0, 100)
    assert pit_slice([a], decision_time=100) == [a]


# --- adversarial order book (§65) ------------------------------------------


def test_crossed_book_fails_closed() -> None:
    snap = BookSnapshot(timestamp=1, bids=[(101.0, 1.0)], asks=[(100.0, 1.0)])
    with pytest.raises(DataIntegrityError):
        check_book_snapshot(snap)


def test_zero_bid_fails_closed() -> None:
    snap = BookSnapshot(timestamp=1, bids=[(0.0, 1.0)], asks=[(100.0, 1.0)])
    with pytest.raises(DataIntegrityError):
        check_book_snapshot(snap)


def test_negative_quantity_fails_closed() -> None:
    snap = BookSnapshot(timestamp=1, bids=[(100.0, -1.0)], asks=[(101.0, 1.0)])
    with pytest.raises(DataIntegrityError):
        check_book_snapshot(snap)


def test_empty_side_fails_closed() -> None:
    snap = BookSnapshot(timestamp=1, bids=[], asks=[(101.0, 1.0)])
    with pytest.raises(DataIntegrityError):
        check_book_snapshot(snap)


def test_valid_book_passes() -> None:
    snap = BookSnapshot(
        timestamp=1, bids=[(100.0, 1.0), (99.0, 2.0)], asks=[(101.0, 1.0), (102.0, 2.0)]
    )
    check_book_snapshot(snap)


def test_bids_sorted_violation_fails_closed() -> None:
    snap = BookSnapshot(timestamp=1, bids=[(99.0, 1.0), (100.0, 1.0)], asks=[(101.0, 1.0)])
    with pytest.raises(DataIntegrityError):
        check_book_snapshot(snap)
