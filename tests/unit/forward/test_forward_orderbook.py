"""Adversarial tests for order book reconstruction and sequence integrity (§13, §30).

The book is the component that can do the most damage if it is wrong: an
imbalance feature computed on a silently corrupt book looks exactly like a real
one. So these tests insist that every failure mode ends in a named state
(``INVALID`` / ``GAP`` / ``MALFORMED``) and never in a quietly advanced book.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_bot.research.forward.orderbook import (
    BookHealth,
    BookStateError,
    BookSyncer,
    DepthUpdate,
    DiffDisposition,
    OrderBook,
    SequencePolicy,
    SnapshotOutcome,
    parse_depth_levels,
)

# ------------------------------------------------------------------ level parsing


def test_zero_quantity_is_a_delete_not_a_missing_value() -> None:
    levels = parse_depth_levels([["100.00", "0.00000000"], ["99.50", "2"]], "bids")
    assert levels == ((Decimal("100.00"), Decimal(0)), (Decimal("99.50"), Decimal(2)))


def test_negative_size_is_rejected() -> None:
    with pytest.raises(BookStateError):
        parse_depth_levels([["100.00", "-1"]], "bids")


def test_zero_or_negative_price_is_rejected() -> None:
    with pytest.raises(BookStateError):
        parse_depth_levels([["0", "1"]], "bids")
    with pytest.raises(BookStateError):
        parse_depth_levels([["-1.5", "1"]], "asks")


def test_duplicate_price_inside_one_message_is_malformed() -> None:
    with pytest.raises(BookStateError):
        parse_depth_levels([["100.00", "1"], ["100.00", "2"]], "bids")


def test_non_numeric_and_non_finite_quantities_are_rejected() -> None:
    with pytest.raises(BookStateError):
        parse_depth_levels([["abc", "1"]], "bids")
    with pytest.raises(BookStateError):
        parse_depth_levels([["100.00", "NaN"]], "bids")


def test_malformed_level_shapes_are_rejected() -> None:
    with pytest.raises(BookStateError):
        parse_depth_levels([[100.0]], "bids")
    with pytest.raises(BookStateError):
        parse_depth_levels({"price": 1}, "bids")


# ------------------------------------------------------------------- depth payload


def test_depth_payload_must_declare_its_update_range() -> None:
    with pytest.raises(BookStateError):
        DepthUpdate.from_ws_payload({"e": "depthUpdate", "U": 1}, 10)
    with pytest.raises(BookStateError):
        DepthUpdate.from_ws_payload({"e": "aggTrade", "U": 1, "u": 2}, 10)


def test_futures_payload_keeps_the_previous_id() -> None:
    update = DepthUpdate.from_ws_payload(
        {
            "e": "depthUpdate",
            "E": 5,
            "U": 10,
            "u": 20,
            "pu": 9,
            "b": [["1", "1"]],
            "a": [["2", "1"]],
        },
        11,
    )
    assert (update.first_id, update.last_id, update.prev_id) == (10, 20, 9)
    assert update.exchange_event_time == 5


def test_inverted_depth_range_is_rejected() -> None:
    with pytest.raises(BookStateError):
        DepthUpdate(
            first_id=20,
            last_id=10,
            prev_id=None,
            bids=(),
            asks=(),
            exchange_event_time=None,
            received_time=1,
        )


# -------------------------------------------------------------------- raw book

SNAPSHOT_BIDS = ((Decimal("100.00"), Decimal("5")), (Decimal("99.00"), Decimal("3")))
SNAPSHOT_ASKS = ((Decimal("101.00"), Decimal("4")), (Decimal("102.00"), Decimal("6")))


def _book() -> OrderBook:
    book = OrderBook("BTCUSDT", "spot", depth_n=2)
    book.load_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS)
    return book


def test_snapshot_derives_the_documented_book_features() -> None:
    book = _book()
    assert book.best_bid() == Decimal("100.00")
    assert book.best_ask() == Decimal("101.00")
    assert book.mid() == Decimal("100.50")
    assert book.depth(2, "bid") == Decimal("100.00") * 5 + Decimal("99.00") * 3
    assert book.microprice() == (Decimal("100.00") * 4 + Decimal("101.00") * 5) / 9
    assert book.depth_imbalance(2) is not None
    assert book.spread_bps() == Decimal("1.00") / Decimal("100.50") * Decimal(10_000)


def test_empty_or_crossed_snapshots_are_refused() -> None:
    book = OrderBook("BTCUSDT", "spot")
    with pytest.raises(BookStateError):
        book.load_snapshot(1, (), ())
    with pytest.raises(BookStateError):
        book.load_snapshot(1, ((Decimal("0"), Decimal("0")),), ((Decimal("101"), Decimal("1")),))
    with pytest.raises(BookStateError):
        book.load_snapshot(1, ((Decimal("101"), Decimal("1")),), ((Decimal("100"), Decimal("1")),))


def test_zero_quantity_removes_a_level_exactly() -> None:
    book = _book()
    book.apply_levels(((Decimal("100.00"), Decimal("0")),), ())
    assert book.best_bid() == Decimal("99.00")
    assert book.bid_levels() == 1


def test_checkpoint_reports_every_field_a_later_consumer_needs() -> None:
    checkpoint = _book().checkpoint(BookHealth.HEALTHY)
    assert checkpoint.best_bid == "100.00"
    assert checkpoint.best_ask == "101.00"
    assert checkpoint.best_bid_qty == "5"
    assert checkpoint.best_ask_qty == "4"
    assert checkpoint.mid == "100.50"
    assert checkpoint.spread_bps is not None
    assert checkpoint.depth_imbalance is not None
    assert checkpoint.microprice is not None
    assert checkpoint.bid_levels == 2
    assert checkpoint.health is BookHealth.HEALTHY


def test_depth_imbalance_is_notional_weighted_not_size_weighted() -> None:
    book = OrderBook("BTCUSDT", "spot")
    # 2 units at 10 == 1 unit at 20 in notional, so the imbalance is exactly zero
    # even though the raw sizes differ by 2x.
    book.load_snapshot(1, ((Decimal("10"), Decimal("2")),), ((Decimal("20"), Decimal("1")),))
    assert book.depth_imbalance(1) == Decimal(0)


# ----------------------------------------------------------------------- syncer


def _spot_syncer() -> BookSyncer:
    return BookSyncer("BTCUSDT", "spot", SequencePolicy.SPOT_UPDATE_ID, depth_n=2)


def _futures_syncer() -> BookSyncer:
    return BookSyncer("BTCUSDT", "perp", SequencePolicy.FUTURES_PREV_ID, depth_n=2)


def _update(
    first: int, last: int, prev: int | None = None, ts: int = 1_000, qty: str = "1"
) -> DepthUpdate:
    return DepthUpdate(
        first_id=first,
        last_id=last,
        prev_id=prev,
        bids=((Decimal("100.00"), Decimal(qty)),),
        asks=((Decimal("101.00"), Decimal(qty)),),
        exchange_event_time=ts,
        received_time=ts,
    )


def test_snapshot_then_bridge_then_live_on_the_spot_policy() -> None:
    syncer = _spot_syncer()
    assert syncer.health(1_000) is BookHealth.RECOVERING
    outcome = syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    assert outcome is SnapshotOutcome.AWAITING_DIFF
    assert syncer.on_diff(_update(1_001, 1_005, ts=1_001)) is DiffDisposition.APPLIED
    assert syncer.is_live
    assert syncer.health(1_001) is BookHealth.HEALTHY
    assert syncer.book.last_update_id == 1_005


def test_snapshot_bridges_a_buffer_that_straddles_it() -> None:
    syncer = _spot_syncer()
    assert syncer.on_diff(_update(999, 1_003, ts=999)) is DiffDisposition.BUFFERED
    assert syncer.on_diff(_update(1_004, 1_010, ts=1_004)) is DiffDisposition.BUFFERED
    outcome = syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_004)
    assert outcome is SnapshotOutcome.LIVE
    assert syncer.book.last_update_id == 1_010
    assert syncer.counters.applied == 2


def test_a_buffer_that_starts_past_the_snapshot_is_a_gap_not_a_book() -> None:
    syncer = _spot_syncer()
    syncer.on_diff(_update(1_100, 1_105, ts=1_100))
    outcome = syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_100)
    assert outcome is SnapshotOutcome.GAP
    assert syncer.health(1_100) is BookHealth.INVALID
    assert syncer.counters.gaps == 1
    assert syncer.counters.invalidations == 1
    assert not syncer.feature_usable(1_100)


def test_missing_depth_sequence_invalidates_the_book() -> None:
    syncer = _spot_syncer()
    syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    syncer.on_diff(_update(1_001, 1_005, ts=1_001))
    assert syncer.on_diff(_update(1_050, 1_060, ts=1_050)) is DiffDisposition.GAP
    assert syncer.health(1_050) is BookHealth.INVALID
    assert not syncer.is_live
    assert syncer.counters.gaps == 1


def test_duplicate_depth_update_is_counted_and_ignored() -> None:
    syncer = _spot_syncer()
    syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    syncer.on_diff(_update(1_001, 1_005, ts=1_001))
    assert syncer.on_diff(_update(1_001, 1_005, ts=1_001)) is DiffDisposition.DUPLICATE
    assert syncer.counters.duplicates == 1
    assert syncer.book.last_update_id == 1_005
    assert syncer.is_live


def test_an_update_straddling_the_head_is_out_of_order() -> None:
    syncer = _spot_syncer()
    syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    syncer.on_diff(_update(1_001, 1_010, ts=1_001))
    assert syncer.on_diff(_update(1_008, 1_012, ts=1_008)) is DiffDisposition.OUT_OF_ORDER
    assert syncer.counters.out_of_order == 1
    assert syncer.book.last_update_id == 1_010


def test_a_stale_healthy_book_degrades_to_stale_not_to_healthy() -> None:
    syncer = _spot_syncer()
    syncer.stale_after_ms = 100
    syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    syncer.on_diff(_update(1_001, 1_005, ts=1_000))
    assert syncer.health(1_050) is BookHealth.HEALTHY
    assert syncer.health(1_500) is BookHealth.STALE
    assert not syncer.feature_usable(1_500)


def test_a_crossed_book_from_a_diff_invalidates_the_book() -> None:
    syncer = _spot_syncer()
    syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    crossing = DepthUpdate(
        first_id=1_001,
        last_id=1_001,
        prev_id=None,
        bids=((Decimal("101.50"), Decimal("1")),),
        asks=(),
        exchange_event_time=1_001,
        received_time=1_001,
    )
    assert syncer.on_diff(crossing) is DiffDisposition.APPLIED
    assert syncer.counters.crossed_book_events == 1
    assert syncer.health(1_001) is BookHealth.INVALID


def test_futures_policy_uses_the_previous_id_chain() -> None:
    syncer = _futures_syncer()
    assert syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000) is (
        SnapshotOutcome.AWAITING_DIFF
    )
    # Snapshot excludes id 1000, so an update starting at 1001 continues it.
    assert syncer.on_diff(_update(1_001, 1_005, prev=1_000, ts=1_001)) is DiffDisposition.APPLIED
    assert syncer.on_diff(_update(1_006, 1_010, prev=1_005, ts=1_006)) is DiffDisposition.APPLIED
    # Arithmetic adjacency holds but the venue-published chain does not: gap.
    assert syncer.on_diff(_update(1_011, 1_015, prev=1_009, ts=1_011)) is DiffDisposition.GAP
    assert syncer.health(1_011) is BookHealth.INVALID


def test_futures_snapshot_may_bridge_an_update_that_contains_its_id() -> None:
    syncer = _futures_syncer()
    syncer.on_diff(_update(995, 1_005, prev=994, ts=995))
    assert syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_005) is (SnapshotOutcome.LIVE)
    assert syncer.book.last_update_id == 1_005


def test_a_futures_buffer_that_starts_past_the_snapshot_is_a_gap() -> None:
    syncer = _futures_syncer()
    syncer.on_diff(_update(1_100, 1_105, prev=1_099, ts=1_100))
    assert syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_100) is SnapshotOutcome.GAP
    assert syncer.health(1_100) is BookHealth.INVALID


def test_a_late_snapshot_is_counted_as_a_snapshot_mismatch() -> None:
    syncer = _spot_syncer()
    syncer.on_diff(_update(900, 950, ts=900))
    outcome = syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    assert outcome is SnapshotOutcome.AWAITING_DIFF
    assert syncer.counters.snapshot_mismatches == 1
    assert syncer.awaiting_first


def test_recovery_requires_a_fresh_snapshot_not_a_patch() -> None:
    syncer = _spot_syncer()
    syncer.on_snapshot(1_000, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_000)
    syncer.on_diff(_update(1_001, 1_005, ts=1_001))
    syncer.on_diff(_update(1_100, 1_110, ts=1_100))
    assert syncer.health(1_100) is BookHealth.INVALID
    # Diffs keep arriving while invalid; they are buffered, never applied.
    syncer.on_diff(_update(1_111, 1_120, ts=1_111))
    assert syncer.book.last_update_id == 1_005
    assert syncer.on_snapshot(1_120, SNAPSHOT_BIDS, SNAPSHOT_ASKS, 1_120) in (
        SnapshotOutcome.LIVE,
        SnapshotOutcome.AWAITING_DIFF,
    )
    assert syncer.counters.resnapshots == 2


def test_snapshot_levels_are_re_parsed_from_wire_strings() -> None:
    raw = {"bids": [["100.01000000", "1.50000000"]], "asks": [["100.02000000", "0.00000000"]]}
    bids = parse_depth_levels(raw["bids"], "bids")
    asks = parse_depth_levels(raw["asks"], "asks")
    book = OrderBook("BTCUSDT", "spot")
    # An all-zero ask side cannot form a book.
    with pytest.raises(BookStateError):
        book.load_snapshot(1, bids, asks)
