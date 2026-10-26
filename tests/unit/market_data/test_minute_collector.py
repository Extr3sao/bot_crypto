"""UNIT/CONTRACT — a 1-minute collector that cannot dress a non-bar as a bar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.market_data.minute_collector import (
    MINUTE_MS,
    FormingBarError,
    KlinePage,
    MinuteBar,
    MinuteBarError,
    MinuteCollector,
    MinuteStore,
    SourceUnavailable,
    aggregate_complete,
    last_closed_minute_open,
)

#: Aligned to five minutes so aggregation tests are not fighting an offset.
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (5 * MINUTE_MS))
FIVE = 5 * MINUTE_MS


def kline(open_ms: int, *, o=100.0, h=101.0, low=99.0, c=100.5, v=10.0) -> list[float]:
    return [open_ms, o, h, low, c, v]


class ScriptedVenue:
    """A venue that answers any range from the minutes it is told it has.

    The page queue of the first draft could only replay a script; a real venue answers a
    request for a *range*, which is exactly what reconciliation needs. This fake keeps
    that property, including the ability to declare a minute missing and to fail a call.
    """

    name = "scripted_source"

    def __init__(self, *, server_time_ms: int | None = None) -> None:
        self.server_time_ms = (
            T0 + 2 * MINUTE_MS if server_time_ms is None else int(server_time_ms)
        )
        self.rows: dict[int, list[float]] = {}
        self.missing: set[int] = set()
        self.received_at_ms: int | None = None
        self.failures = 0
        self.fetches: list[dict[str, int | None]] = []

    def add(self, open_ms: int, **kwargs: float) -> ScriptedVenue:
        self.rows[int(open_ms)] = kline(int(open_ms), **kwargs)
        return self

    def add_range(self, first_open: int, count: int) -> ScriptedVenue:
        for index in range(count):
            self.add(first_open + index * MINUTE_MS)
        return self

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> KlinePage:
        if self.failures:
            self.failures -= 1
            raise SourceUnavailable("NETWORK", "scripted outage")
        self.fetches.append({"symbol": symbol, "start_ms": start_ms, "end_ms": end_ms})
        stamps = sorted(
            stamp
            for stamp in self.rows
            if stamp not in self.missing
            and (start_ms is None or stamp >= int(start_ms))
            and (end_ms is None or stamp <= int(end_ms))
        )
        stamps = stamps[-max(1, limit) :] if start_ms is None else stamps[: max(1, limit)]
        return KlinePage(
            symbol=symbol,
            rows=tuple(tuple(self.rows[stamp]) for stamp in stamps),
            server_time_ms=int(self.server_time_ms),
            received_at_ms=int(
                self.server_time_ms if self.received_at_ms is None else self.received_at_ms
            ),
        )

    def server_time(self) -> int:
        if self.failures:
            self.failures -= 1
            raise SourceUnavailable("NETWORK", "scripted outage")
        return int(self.server_time_ms)


def make_collector(tmp_path: Path, venue: ScriptedVenue, **kwargs) -> MinuteCollector:
    defaults = dict(
        source=venue,
        root=tmp_path / "market",
        symbols=("BTCUSDT",),
        local_clock=lambda: int(venue.server_time_ms),
        settle_ms=0,
    )
    defaults.update(kwargs)
    return MinuteCollector(**defaults).open()


# ------------------------------------------------------------------ the bar


def test_a_forming_minute_is_never_stored(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 30_000)
    venue.add(T0)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 0
        assert "FORMING_BAR_IGNORED" in [event["kind"] for event in collector.events]
        assert not (tmp_path / "market" / "BTCUSDT.jsonl").exists()
    finally:
        collector.close()


def test_a_just_closed_minute_is_deferred_until_it_settles(tmp_path: Path) -> None:
    # Measured on the venue: a minute stored 1.2 s after its close was amended later.
    venue = ScriptedVenue(server_time_ms=T0 + MINUTE_MS + 1_000)
    venue.add(T0)
    collector = make_collector(tmp_path, venue, settle_ms=2_500)
    try:
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 0
        assert "SETTLE_DEFERRED" in [event["kind"] for event in collector.events]
        venue.server_time_ms = T0 + MINUTE_MS + 3_000
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 1
    finally:
        collector.close()


def test_a_closed_minute_records_origin_and_receipt(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 65_000)
    venue.add(T0)
    venue.received_at_ms = T0 + 67_000
    # settle_ms=0: this test is about the stamps, not about the settle gate.
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        stored = collector.stores["BTCUSDT"].bars()[0]
        assert stored.open_ms == T0
        assert stored.close_ms == T0 + MINUTE_MS
        assert stored.server_time_ms == T0 + 65_000
        assert stored.received_at_ms == T0 + 67_000
        assert stored.delivery_latency_ms == 7_000
        row = json.loads(
            (tmp_path / "market" / "BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        assert row["open_ms"] == T0
        assert row["received_at_ms"] == T0 + 67_000
        assert row["server_time_ms"] == T0 + 65_000
        assert row["open_utc"].endswith("Z")
    finally:
        collector.close()


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"h": 99.0}, "OHLC_INCONSISTENT"),
        ({"o": 0.0}, "NON_POSITIVE_PRICE"),
        ({"v": -1.0}, "NEGATIVE_VOLUME"),
    ],
)
def test_a_malformed_minute_is_refused(tmp_path: Path, kwargs: dict, code: str) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 70_000)
    venue.add(T0, **kwargs)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 0
        assert code in (collector.blocked.get("BTCUSDT") or "")
    finally:
        collector.close()


# ------------------------------------------------------------- duplicates


def test_a_duplicate_identical_minute_is_ignored_not_rewritten(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 70_000)
    venue.add(T0)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        venue.server_time_ms = T0 + 80_000
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 1
        lines = (tmp_path / "market" / "BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert "DUPLICATE_IDENTICAL" in [event["kind"] for event in collector.events]
    finally:
        collector.close()


def test_a_duplicate_with_different_ohlcv_blocks_and_is_not_overwritten(
    tmp_path: Path,
) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 70_000)
    venue.add(T0)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        venue.rows[T0] = kline(T0, c=100.9)
        venue.server_time_ms = T0 + 80_000
        collector.poll()
        assert collector.stores["BTCUSDT"].bars()[0].close == 100.5
        assert "DUPLICATE_CONFLICT" in collector.blocked["BTCUSDT"]
        assert collector.health()["BTCUSDT"].tradeable is False
    finally:
        collector.close()


# ------------------------------------------------------------- ordering


def test_an_unknown_older_minute_is_out_of_order_and_blocks(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 4 * MINUTE_MS)
    venue.add(T0 + 2 * MINUTE_MS)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        venue.add(T0 + MINUTE_MS)  # a late correction arriving after the newer minute
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 1
        assert "OUT_OF_ORDER" in collector.blocked["BTCUSDT"]
    finally:
        collector.close()


# ------------------------------------------------------------------ gaps


def test_a_gap_is_detected_and_filled_before_the_later_minute_is_stored(
    tmp_path: Path,
) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 4 * MINUTE_MS + 5_000)
    venue.add(T0).add(T0 + 3 * MINUTE_MS)
    venue.add(T0 + MINUTE_MS).add(T0 + 2 * MINUTE_MS)
    venue.missing = {T0 + MINUTE_MS, T0 + 2 * MINUTE_MS}
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        # The hole could not be filled, so the later minute is *not* stored and the
        # symbol is blocked: the store never has to be rewritten.
        assert [bar.open_ms for bar in collector.stores["BTCUSDT"].bars()] == [T0]
        assert "UNRESOLVED_GAP" in collector.blocked["BTCUSDT"]
        assert collector.health()["BTCUSDT"].tradeable is False
        venue.missing = set()
        result = collector.reconcile("BTCUSDT")
        assert result["ok"] is True
        assert [bar.open_ms for bar in collector.stores["BTCUSDT"].bars()] == [
            T0,
            T0 + MINUTE_MS,
            T0 + 2 * MINUTE_MS,
            T0 + 3 * MINUTE_MS,
        ]
        assert "BTCUSDT" not in collector.blocked
    finally:
        collector.close()


def test_a_gap_with_an_answer_is_filled_inline(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 70_000)
    venue.add(T0)
    collector = make_collector(tmp_path, venue, lookback=1)
    try:
        collector.poll()
        assert collector.stores["BTCUSDT"].last_open_ms == T0
        # The next page is the far side of a hole the venue can still answer for.
        venue.add(T0 + MINUTE_MS).add(T0 + 2 * MINUTE_MS).add(T0 + 3 * MINUTE_MS)
        venue.server_time_ms = T0 + 4 * MINUTE_MS + 5_000
        collector.poll()
        assert collector.stores["BTCUSDT"].gaps() == []
        assert [bar.open_ms for bar in collector.stores["BTCUSDT"].bars()] == [
            T0,
            T0 + MINUTE_MS,
            T0 + 2 * MINUTE_MS,
            T0 + 3 * MINUTE_MS,
        ]
        assert "GAP_FILLED" in [event["kind"] for event in collector.events]
        assert "BTCUSDT" not in collector.blocked
    finally:
        collector.close()


def test_an_unreconcilable_gap_keeps_the_symbol_blocked(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 4 * MINUTE_MS + 5_000)
    venue.add(T0).add(T0 + 3 * MINUTE_MS)
    venue.missing = {T0 + MINUTE_MS, T0 + 2 * MINUTE_MS}
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        result = collector.reconcile("BTCUSDT")
        assert result["ok"] is False
        assert "RECONCILE_FAILED" in collector.blocked["BTCUSDT"]
        assert collector.stores["BTCUSDT"].last_open_ms == T0
    finally:
        collector.close()


def test_a_disconnect_reconnects_and_reconciles_before_trading(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 3 * MINUTE_MS + 5_000)
    venue.add_range(T0, 3)
    venue.failures = 1
    collector = make_collector(tmp_path, venue)
    try:
        result = collector.collect(max_attempts=2, base_backoff_s=0.0)
        assert result["ok"] is True
        assert [event["kind"] for event in collector.events].count("DISCONNECT") == 1
        assert "RECONNECT" in [event["kind"] for event in collector.events]
        assert [bar.open_ms for bar in collector.stores["BTCUSDT"].bars()] == [
            T0,
            T0 + MINUTE_MS,
            T0 + 2 * MINUTE_MS,
        ]
    finally:
        collector.close()


# -------------------------------------------------------------- freshness


def test_a_stale_feed_is_not_tradeable(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 70_000)
    venue.add(T0)
    collector = make_collector(tmp_path, venue, stale_after_ms=120_000)
    try:
        collector.poll()
        venue.server_time_ms = T0 + 12 * MINUTE_MS
        collector.poll()
        health = collector.health()["BTCUSDT"]
        assert health.state == "STALE"
        assert health.tradeable is False
    finally:
        collector.close()


def test_a_clock_skew_blocks_trading_even_with_fresh_data(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 70_000)
    venue.add(T0)
    collector = MinuteCollector(
        source=venue,
        root=tmp_path / "market",
        symbols=("BTCUSDT",),
        local_clock=lambda: int(venue.server_time_ms) + 60_000,
        settle_ms=0,
        max_skew_ms=5_000,
    ).open()
    try:
        collector.poll()
        health = collector.health()["BTCUSDT"]
        assert health.state == "CLOCK_SKEW"
        assert health.tradeable is False
    finally:
        collector.close()


def test_health_before_any_venue_clock_is_refused(tmp_path: Path) -> None:
    venue = ScriptedVenue()
    collector = make_collector(tmp_path, venue)
    try:
        with pytest.raises(RuntimeError, match="venue clock"):
            collector.health()
    finally:
        collector.close()


# ------------------------------------------------------------ persistence


def test_the_store_reloads_in_order_and_keeps_its_digest(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 4 * MINUTE_MS)
    venue.add_range(T0, 3)
    collector = make_collector(tmp_path, venue)
    collector.poll()
    digest = collector.stores["BTCUSDT"].digest()
    collector.close()

    reopened = MinuteStore(tmp_path / "market" / "BTCUSDT.jsonl").open()
    try:
        assert [bar.open_ms for bar in reopened.bars()] == [
            T0,
            T0 + MINUTE_MS,
            T0 + 2 * MINUTE_MS,
        ]
        assert reopened.digest() == digest
    finally:
        reopened.close()


def test_a_corrupt_store_is_refused_instead_of_repaired(tmp_path: Path) -> None:
    path = tmp_path / "BTCUSDT.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    first = MinuteBar.from_kline(
        "BTCUSDT", kline(T0), received_at_ms=T0 + 70_000, server_time_ms=T0 + 70_000
    )
    path.write_text(
        json.dumps(first.to_row()) + "\n" + json.dumps(first.to_row()) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MinuteBarError, match="CORRUPT_STORE"):
        MinuteStore(path).open()


def test_the_manifest_names_the_bytes_it_consumed(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 3 * MINUTE_MS)
    venue.add_range(T0, 2)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        manifest = collector.manifest()
        entry = manifest["symbols"]["BTCUSDT"]
        assert entry["minutes"] == 2
        assert entry["sha256"] == collector.stores["BTCUSDT"].digest()
        assert entry["gaps"] == []
        assert manifest["source"] == "scripted_source"
        assert manifest["events"] >= 0
    finally:
        collector.close()


def test_a_second_writer_on_the_same_store_is_refused(tmp_path: Path) -> None:
    venue = ScriptedVenue()
    first = make_collector(tmp_path, venue)
    try:
        with pytest.raises(RuntimeError, match="another collector"):
            MinuteStore(tmp_path / "market" / "BTCUSDT.jsonl").open()
    finally:
        first.close()


# ----------------------------------------------------------- aggregation


def _minute(index: int) -> MinuteBar:
    return MinuteBar.from_kline(
        "BTCUSDT",
        kline(
            T0 + index * MINUTE_MS,
            o=100 + index,
            h=101 + index,
            low=99 + index,
            c=100 + index,
        ),
        received_at_ms=T0 + 10 * MINUTE_MS,
        server_time_ms=T0 + 10 * MINUTE_MS,
    )


def test_aggregation_drops_a_partial_group_and_marks_the_open_tail() -> None:
    bars, meta = aggregate_complete([_minute(i) for i in range(7)], interval_ms=FIVE)
    assert [item.ts_ms for item in bars] == [T0]
    assert meta["incomplete_groups"] == []
    assert meta["pending_group"] == T0 + FIVE


def test_aggregation_flags_an_interior_hole_as_incomplete() -> None:
    bars, meta = aggregate_complete(
        [_minute(0), _minute(1), _minute(3), _minute(4)], interval_ms=FIVE
    )
    assert bars == []
    assert meta["incomplete_groups"] == [T0]


def test_aggregation_drops_the_group_cut_by_the_window_start() -> None:
    # The session asks for the last N minutes; the oldest 5 m group is usually cut by
    # that boundary. It is not a hole in the feed and must not block the session.
    bars, meta = aggregate_complete(
        [_minute(2), _minute(3), _minute(4)] + [_minute(5 + i) for i in range(5)],
        interval_ms=FIVE,
    )
    assert meta["incomplete_groups"] == []
    assert meta["leading_partial_group"] == T0
    assert [item.ts_ms for item in bars] == [T0 + FIVE]


def test_aggregation_refuses_a_non_minute_interval() -> None:
    with pytest.raises(ValueError, match="multiple of one minute"):
        aggregate_complete([_minute(0)], interval_ms=90_000)


def test_forming_bar_error_carries_the_exchange_clock() -> None:
    with pytest.raises(FormingBarError) as raised:
        MinuteBar.from_kline(
            "BTCUSDT", kline(T0), received_at_ms=T0 + 30_000, server_time_ms=T0 + 30_000
        )
    assert "still in formation" in str(raised.value)


def test_last_closed_minute_is_the_one_that_ended_at_the_server_clock() -> None:
    assert last_closed_minute_open(T0 + 4 * MINUTE_MS + 5_000) == T0 + 3 * MINUTE_MS
    assert last_closed_minute_open(T0 + 4 * MINUTE_MS) == T0 + 3 * MINUTE_MS
    assert last_closed_minute_open(T0 + 4 * MINUTE_MS - 1) == T0 + 2 * MINUTE_MS
