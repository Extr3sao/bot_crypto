"""Adapter from ``OHLCVStore`` to ``OHLCVSourceProtocol``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from .types import OHLCV, OHLCVSourceProtocol

if TYPE_CHECKING:
    from trading_bot.storage.ohlcv_store import OHLCVStore


class OHLCVStoreSource(OHLCVSourceProtocol):
    """Read-only adapter for replaying candles from SQLite storage."""

    def __init__(self, store: OHLCVStore) -> None:
        self._store = store

    def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
        for candle in self._store.get_ohlcv_range(symbol, start, end):
            yield OHLCV(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )


__all__ = ["OHLCVStoreSource"]
