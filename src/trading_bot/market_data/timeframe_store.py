"""Timeframe-aware view over ``OHLCVStore``.

``ohlcv_store.OHLCVStore`` keys rows by ``(symbol, timestamp)``; it has no
timeframe column.  That is fine for one series and wrong for three: a 4h bar
and a 1h bar can share an open time, so the second write overwrites the first
and a "multi-timeframe snapshot" silently becomes a single-timeframe one with
holes.  This was measured during RFC-TAP-MARKET-005 (a 4h slice came back with
a 1d bar's value at its tail).

The fix does not touch the store's schema — changing its primary key would
affect every existing backtest and database.  Instead this adapter namespaces
the *symbol* with the timeframe (``BTC/USDT@1h``) and rewrites the field back on
read, so callers keep seeing ``OHLCV(symbol="BTC/USDT")``.

One adapter, one database, existing ``OHLCVStore`` underneath: no second
storage engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore

__all__ = ["STORAGE_SEPARATOR", "OHLCVTimeframeStore", "TimeframeStore"]

STORAGE_SEPARATOR = "@"


class TimeframeStore(Protocol):
    """Minimal storage contract the ingestion and snapshot planes need."""

    def upsert(self, rows: Iterable[OHLCV], *, symbol: str, timeframe: str) -> int:
        """Persist rows that belong to ``(symbol, timeframe)``; return the count."""
        ...

    def tail(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        """Return up to ``limit`` newest rows, oldest first."""
        ...

    def close(self) -> None: ...


class OHLCVTimeframeStore:
    """``TimeframeStore`` on top of the canonical ``OHLCVStore``."""

    def __init__(self, store: OHLCVStore) -> None:
        self._store = store

    @staticmethod
    def storage_symbol(symbol: str, timeframe: str) -> str:
        return f"{symbol}{STORAGE_SEPARATOR}{timeframe}"

    def upsert(self, rows: Iterable[OHLCV], *, symbol: str, timeframe: str) -> int:
        key = self.storage_symbol(symbol, timeframe)
        bound = [
            OHLCV(
                symbol=key,
                timestamp=int(row.timestamp),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in rows
        ]
        return self._store.upsert_ohlcv(bound)

    def tail(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        key = self.storage_symbol(symbol, timeframe)
        rows = self._store.get_ohlcv(key, limit=limit)
        return [
            OHLCV(
                symbol=symbol,
                timestamp=int(row.timestamp),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in reversed(rows)  # store returns DESC; the contracts want ASC
        ]

    def close(self) -> None:
        self._store.close()
