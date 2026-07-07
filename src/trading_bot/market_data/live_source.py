"""Real ``MarketDataSourceProtocol`` backed by CCXT + OHLCV cache.

Bridges the phase-1 market-data components to the scanner protocol:

- ``CCXTExchangeConnector`` provides exchange reads with retries.
- ``OHLCVFetcher`` pulls candles and persists them to SQLite.
- ``CCXTMarketDataSource`` exposes the three async methods the scanner
  needs (`fetch_recent`, `fetch_24h_volume_usdt`, `fetch_spread_bps`).

The implementation is intentionally small and synchronous under the
hood: the scanner API is async, but phase-1 exchange calls already
exist as blocking methods. Wrapping them behind an async protocol keeps
the scanner contract stable while we defer a true async connector to a
later phase.
"""

from __future__ import annotations

import math
from typing import Any

from trading_bot.market_data.exchange_connector import CCXTExchangeConnector
from trading_bot.market_data.ohlcv_fetcher import OHLCVFetcher
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore


class CCXTMarketDataSource:
    """Adapter from ``CCXTExchangeConnector`` to scanner market-data protocol."""

    def __init__(
        self,
        *,
        connector: CCXTExchangeConnector,
        fetcher: OHLCVFetcher,
        store: OHLCVStore,
        timeframe: str,
        ohlcv_limit: int = 100,
    ) -> None:
        self._connector = connector
        self._fetcher = fetcher
        self._store = store
        self._timeframe = timeframe
        self._ohlcv_limit = ohlcv_limit

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        capped_limit = max(limit, self._ohlcv_limit)
        return self._fetcher.fetch_and_cache(symbol, self._timeframe, limit=capped_limit)

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        ticker = self._connector.fetch_ticker(symbol)
        quote_volume = _coerce_float(ticker.get("quoteVolume"))
        if quote_volume is not None:
            return quote_volume

        base_volume = _coerce_float(ticker.get("baseVolume"))
        last_price = _coerce_float(ticker.get("last"))
        if base_volume is not None and last_price is not None:
            return base_volume * last_price

        return 0.0

    async def fetch_spread_bps(self, symbol: str) -> float:
        order_book = self._connector.fetch_order_book(symbol, limit=5)
        bids = order_book.get("bids")
        asks = order_book.get("asks")
        best_bid = _top_price(bids)
        best_ask = _top_price(asks)
        if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
            return math.inf
        mid = (best_bid + best_ask) / 2.0
        if mid <= 0:
            return math.inf
        return ((best_ask - best_bid) / mid) * 10_000.0

    def close(self) -> None:
        self._store.close()


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top_price(levels: object) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    top = levels[0]
    if not isinstance(top, list) or not top:
        return None
    return _coerce_float(top[0])


__all__ = ["CCXTMarketDataSource"]
