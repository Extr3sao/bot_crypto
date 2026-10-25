"""Provider failure policy tests (REAL-DATA-01, hardening phase §14).

Every case asserts the OBSERVABLE policy of ``FetcherBarReader``:

    timeout / network error   -> exception propagates (runner records
                                 history_error; NO orders; never a
                                 silent NO_TRADE-as-ok)
    empty dataset             -> [] -> context error downstream (fail closed)
    partial response          -> accepted as-is; context enforces min history
    duplicate candles         -> first kept, duplicates rejected
    out-of-order candles      -> reordered ascending
    stale last candle         -> kept only if closed at decision time
                                 (stale + closed data is legitimately the
                                 newest truth; a STALE *snapshot* is the
                                 scanner's freshness gate, not the reader's)
    future candle             -> rejected by the closed-candle filter
    missing candle            -> not invented (no padding)
    invalid timestamp         -> bar rejected
    forming candle            -> NEVER leaked (open-candle rule)

Also: a misbehaving reader cannot defeat PIT (trim happens downstream in
``snapshot_context.trim_to_pit``) — defence in depth is asserted directly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from trading_bot.market_data.candle_filter import UnknownTimeframeError
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.snapshot_context import trim_to_pit
from trading_bot.paper.snapshot_history import FetcherBarReader

TS0 = 1_700_000_000_000


def _bar(ts: int, close: float = 100.0, symbol: str = "BTC/USDT") -> OHLCV:
    return OHLCV(
        symbol=symbol,
        timestamp=ts,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1.0,
    )


class _SeqSource:
    """Fetch stub returning a canned sequence (or raising)."""

    def __init__(self, bars: list[OHLCV] | None = None, exc: Exception | None = None) -> None:
        self._bars = bars or []
        self._exc = exc
        self.calls = 0

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return list(self._bars)


def _read(source: Any, *, as_of: int, timeframe: str = "5m") -> list[OHLCV]:
    reader = FetcherBarReader(source, timeframe=timeframe)
    return asyncio.run(reader.get_ohlcv("BTC/USDT", as_of_timestamp_ms=as_of, lookback_bars=120))


# -- timeout / network failure: exception PROPAGATES (never swallowed) ------


def test_timeout_propagates_not_converted_to_no_trade() -> None:
    src = _SeqSource(exc=TimeoutError("provider timeout"))
    with pytest.raises(TimeoutError):
        _read(src, as_of=TS0 + 10 * 60_000)


def test_network_error_propagates() -> None:
    src = _SeqSource(exc=ConnectionError("socket closed"))
    with pytest.raises(ConnectionError):
        _read(src, as_of=TS0 + 10 * 60_000)


# -- empty / partial --------------------------------------------------------


def test_empty_dataset_yields_empty_not_error() -> None:
    out = _read(_SeqSource([]), as_of=TS0 + 10 * 60_000)
    assert out == []  # context stage turns this into a recorded context error


def test_partial_response_not_padded() -> None:
    bars = [_bar(TS0 + i * 300_000) for i in range(3)]  # 5m grid, far below min history
    out = _read(_SeqSource(bars), as_of=TS0 + 3 * 300_000)
    assert len(out) == 3  # all closed, passed through, NOT padded; context will reject


# -- duplicates / ordering / invalid timestamps ------------------------------


def test_duplicate_candles_keep_first() -> None:
    bars = [_bar(TS0), _bar(TS0, close=999.0), _bar(TS0 + 300_000)]
    out = _read(_SeqSource(bars), as_of=TS0 + 300_000 + 300_000)
    stamps = [b.timestamp for b in out]
    assert stamps.count(TS0) == 1
    assert next(b for b in out if b.timestamp == TS0).close == 100.0  # FIRST kept


def test_out_of_order_candles_reordered() -> None:
    bars = [_bar(TS0 + 600_000), _bar(TS0), _bar(TS0 + 300_000)]
    out = _read(_SeqSource(bars), as_of=TS0 + 900_000)
    stamps = [b.timestamp for b in out]
    assert stamps == sorted(stamps) == [TS0, TS0 + 300_000, TS0 + 600_000]


def test_invalid_timestamp_bar_rejected() -> None:
    bars = [_bar(0), _bar(-5), _bar(TS0), _bar(TS0 + 300_000)]
    out = _read(_SeqSource(bars), as_of=TS0 + 600_000)
    assert [b.timestamp for b in out] == [TS0, TS0 + 300_000]


def test_missing_candle_is_not_invented() -> None:
    bars = [_bar(TS0), _bar(TS0 + 600_000)]  # 5m gap: TS0+300k missing
    out = _read(_SeqSource(bars), as_of=TS0 + 900_000)
    assert [b.timestamp for b in out] == [TS0, TS0 + 600_000]  # no padding


# -- open / future candles: the core PIT-for-real-data guarantee --------------


def test_forming_candle_never_leaks() -> None:
    # Decision at the open of the 5th bar: bars 1-3 closed, bar 4 forming,
    # bar 5 stamped after decision (future).
    bars = [_bar(TS0 + i * 300_000) for i in range(5)]
    decision_ts = TS0 + 4 * 300_000  # bar 4 just opened -> not closed yet
    out = _read(_SeqSource(bars), as_of=decision_ts)
    stamps = [b.timestamp for b in out]
    assert TS0 + 3 * 300_000 in stamps  # last CLOSED bar present
    assert TS0 + 4 * 300_000 not in stamps  # forming candle rejected
    assert TS0 + 5 * 300_000 not in stamps  # future candle rejected
    assert max(b.timestamp for b in out) + 300_000 <= decision_ts // 1  # closed rule


def test_future_candle_rejected_even_if_provider_sends_it() -> None:
    bars = [_bar(TS0), _bar(TS0 + 300_000), _bar(TS0 + 9_000_000)]
    out = _read(_SeqSource(bars), as_of=TS0 + 600_000)
    assert [b.timestamp for b in out] == [TS0, TS0 + 300_000]


def test_stale_but_closed_data_is_kept() -> None:
    # An exchange outage returns only old-but-closed bars: the reader keeps
    # them (they are the newest truth); freshness policy belongs to the
    # router's stale gate, not to the candle filter. Assert observable rule:
    bars = [_bar(TS0), _bar(TS0 + 300_000)]
    out = _read(_SeqSource(bars), as_of=TS0 + 9_000_000)
    assert [b.timestamp for b in out] == [TS0, TS0 + 300_000]


def test_unknown_timeframe_fails_closed() -> None:
    with pytest.raises(UnknownTimeframeError):
        _read(_SeqSource([_bar(TS0)]), as_of=TS0 + 600_000, timeframe="7m")


# -- defence in depth: trim_to_pit holds even against a misbehaving reader ---


def test_trim_to_pit_enforced_downstream_against_bad_reader() -> None:
    bars = [_bar(TS0), _bar(TS0 + 300_000), _bar(TS0 + 9_000_000)]
    pit = trim_to_pit(bars, TS0 + 300_000)
    assert [b.timestamp for b in pit] == [TS0, TS0 + 300_000]
