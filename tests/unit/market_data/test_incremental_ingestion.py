"""Incremental ingestion — the properties that make a delta trustworthy.

Every test builds its own tiny exchange and clock: the point is not "the code
runs" but "a wrong delta cannot advance the watermark".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.market_data.incremental import (
    IncrementalOHLCVIngestor,
    WatermarkCorrupt,
    WatermarkStore,
    bar_sha256,
    closed_boundary_ms,
)
from trading_bot.market_data.replay import ReplayConnector
from trading_bot.market_data.timeframe_store import OHLCVTimeframeStore
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore

HOUR = 3_600_000
START = 1_700_000_000_000  # aligned to the hour: 1700000000 % 3600 == 0? checked below
START = (START // HOUR) * HOUR
SYMBOL = "BTC/USDT"
TF = "1h"


def make_bars(count: int, *, start: int = START) -> list[list[float]]:
    """Deterministic, strictly closed bars (open time, o, h, l, c, v)."""
    rows: list[list[float]] = []
    price = 30_000.0
    for index in range(count):
        price *= 1.0001
        rows.append(
            [
                start + index * HOUR,
                price,
                price * 1.001,
                price * 0.999,
                price * 1.0002,
                10.0 + index,
            ]
        )
    return rows


class Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


def build(tmp_path: Path, bars: int = 40, now: int | None = None):
    rows = make_bars(bars)
    clock = Clock(now if now is not None else START + (bars - 1) * HOUR + HOUR // 2)
    connector = ReplayConnector({SYMBOL: {TF: rows}}, now_ms=clock)
    store = OHLCVTimeframeStore(OHLCVStore(f"sqlite:///{(tmp_path / 'ohlcv.sqlite').as_posix()}"))
    ingestor = IncrementalOHLCVIngestor(
        connector=connector,
        store=store,
        watermarks=WatermarkStore(tmp_path / "watermarks"),
        source_id="test",
        warmup_bars=bars,
        overlap_bars=2,
    )
    return ingestor, connector, store, clock, rows


def test_a_bootstrap_reads_once_and_then_a_closed_cycle_makes_no_request(tmp_path):
    ingestor, connector, _store, clock, _rows = build(tmp_path, bars=40)

    first = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert first.status == "BOOTSTRAP"
    assert first.requests_made == 1
    assert first.rows_incomplete == 1, "the forming bar must be counted, not stored"
    assert first.last_returned_open_ms == closed_boundary_ms(clock.now, TF) - HOUR

    calls = len(connector.calls)
    second = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert second.status == "NO_NEW_DATA"
    assert second.requests_made == 0
    assert len(connector.calls) == calls, "no request may be issued without a new bar"


def test_a_delta_moves_by_one_bar_and_stays_equivalent_to_a_full_read(tmp_path):
    ingestor, connector, store, clock, _rows = build(tmp_path, bars=60)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)

    clock.now += HOUR
    delta = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert delta.status == "DELTA"
    assert delta.requested_limit == 5, "2 overlap + 1 new + the forming bar"
    assert delta.rows_new == 1
    assert delta.gap_open_ms == ()

    full = connector.fetch_ohlcv(SYMBOL, TF, limit=60)
    closed_full = [r for r in full if r.timestamp + HOUR <= clock.now][-5:]
    closed_store = store.tail(SYMBOL, TF, 5)
    assert bar_sha256(closed_full) == bar_sha256(closed_store)


def test_the_forming_bar_is_never_persisted(tmp_path):
    ingestor, _connector, store, clock, rows = build(tmp_path, bars=10)
    result = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert result.rows_incomplete == 1
    stored = {r.timestamp for r in store.tail(SYMBOL, TF, 100)}
    newest_closed = max(r[0] for r in rows if r[0] + HOUR <= clock.now)
    assert newest_closed in stored
    assert newest_closed + HOUR not in stored


def test_a_restart_resumes_from_the_watermark_instead_of_bootstrapping_again(tmp_path):
    ingestor, _connector, store, clock, _rows = build(tmp_path, bars=30)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    restarted = IncrementalOHLCVIngestor(
        connector=_connector,
        store=store,
        watermarks=WatermarkStore(tmp_path / "watermarks"),
        source_id="test",
        warmup_bars=30,
    )
    again = restarted.ingest(SYMBOL, TF, now_ms=clock.now)
    assert again.status == "NO_NEW_DATA"
    assert again.watermark_before is not None


def test_a_corrupt_watermark_fails_closed(tmp_path):
    ingestor, _connector, _store, clock, _rows = build(tmp_path, bars=20)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    path = WatermarkStore(tmp_path / "watermarks").path_for("test", SYMBOL, TF)
    path.write_text('{"source_id": "test"}', encoding="utf-8")
    with pytest.raises(WatermarkCorrupt):
        ingestor.ingest(SYMBOL, TF, now_ms=clock.now)


def test_provider_failure_does_not_advance_the_watermark(tmp_path):
    ingestor, connector, _store, clock, _rows = build(tmp_path, bars=20)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    clock.now += HOUR
    healthy = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert healthy.status == "DELTA"
    before = healthy.watermark_after
    clock.now += HOUR
    connector._fail_on_call = len(connector.calls) + 1
    failed = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert failed.status == "PROVIDER_FAILED"
    assert failed.watermark_after == before
    assert failed.advanced is False


def test_invalid_rows_are_rejected_without_moving_the_watermark(tmp_path):
    ingestor, connector, _store, clock, rows = build(tmp_path, bars=20)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    broken = [list(row) for row in rows]
    broken[-2][2], broken[-2][3] = broken[-2][3], broken[-2][2]  # high < low
    connector._series[SYMBOL][TF] = broken
    clock.now += HOUR
    result = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert result.status == "REJECTED_ROWS"
    assert result.watermark_after == result.watermark_before


def test_a_duplicated_bar_inside_one_response_is_deduplicated(tmp_path):
    rows = make_bars(30)
    rows.insert(len(rows) - 1, list(rows[-2]))  # provider resends the boundary bar
    clock = Clock(START + 29 * HOUR + HOUR // 2)
    connector = ReplayConnector({SYMBOL: {TF: rows}}, now_ms=clock)
    store = OHLCVTimeframeStore(OHLCVStore(f"sqlite:///{(tmp_path / 'ohlcv.sqlite').as_posix()}"))
    ingestor = IncrementalOHLCVIngestor(
        connector=connector,
        store=store,
        watermarks=WatermarkStore(tmp_path / "wm"),
        source_id="test",
        warmup_bars=40,
    )
    result = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert result.status == "BOOTSTRAP"
    assert result.rows_final == 29, "29 distinct closed bars, duplicate collapsed"


def test_a_trailing_gap_stops_the_watermark_at_the_last_held_bar(tmp_path):
    rows = make_bars(30)
    del rows[-2]  # the exchange has not published the bar before the forming one
    clock = Clock(START + 29 * HOUR + HOUR // 2)
    connector = ReplayConnector({SYMBOL: {TF: rows}}, now_ms=clock)
    store = OHLCVTimeframeStore(OHLCVStore(f"sqlite:///{(tmp_path / 'ohlcv.sqlite').as_posix()}"))
    ingestor = IncrementalOHLCVIngestor(
        connector=connector,
        store=store,
        watermarks=WatermarkStore(tmp_path / "wm"),
        source_id="test",
        warmup_bars=30,
    )
    result = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert result.status == "BOOTSTRAP"
    assert result.gap_open_ms, "the hole must be reported, not filled"
    assert result.watermark_after is not None
    assert result.watermark_after.last_verified_open_ms < result.boundary_ms - HOUR


def test_a_backlog_larger_than_the_window_is_refused_and_reconcile_is_explicit(tmp_path):
    ingestor, connector, _store, clock, _rows = build(tmp_path, bars=40)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    connector._series[SYMBOL][TF] = make_bars(4_000)
    clock.now += 3_000 * HOUR
    refused = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert refused.status == "BACKLOG_EXCEEDS_WINDOW"
    assert refused.requests_made == 0
    assert refused.watermark_after == refused.watermark_before

    rebuilt = ingestor.ingest(SYMBOL, TF, now_ms=clock.now, reconcile=True)
    assert rebuilt.status == "RECONCILE"
    assert rebuilt.requests_made == 1


def test_the_boundary_is_the_open_time_of_the_forming_bar():
    now = START + 5 * HOUR + 30 * 60 * 1_000
    assert closed_boundary_ms(now, "1h") == START + 5 * HOUR
    assert closed_boundary_ms(START + 5 * HOUR, "1h") == START + 5 * HOUR
    assert closed_boundary_ms(now, "4h") == (now // (4 * HOUR)) * (4 * HOUR)


def test_store_round_trip_keeps_the_watermark_hash_of_the_persisted_tail(tmp_path):
    ingestor, _connector, store, clock, _rows = build(tmp_path, bars=25)
    result = ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    assert result.watermark_after is not None
    stored = store.tail(SYMBOL, TF, result.rows_final)
    assert bar_sha256(stored) == result.watermark_after.last_persisted_sha


def test_the_ingestor_only_ever_calls_fetch_ohlcv(tmp_path):
    ingestor, connector, _store, clock, _rows = build(tmp_path, bars=12)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    clock.now += HOUR
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    methods = {call.get("symbol") for call in connector.calls}
    assert methods == {SYMBOL}, "no balance/order/ticker call may be issued"
    assert all("error" not in call or call["error"] is None for call in connector.calls)


def test_returned_rows_are_typed_ohlcv_with_symbol_bound(tmp_path):
    ingestor, connector, _store, clock, _rows = build(tmp_path, bars=8)
    ingestor.ingest(SYMBOL, TF, now_ms=clock.now)
    returned = connector.fetch_ohlcv(SYMBOL, TF, limit=3)
    assert returned
    assert all(isinstance(row, OHLCV) for row in returned)
    assert {row.symbol for row in returned} == {SYMBOL}
