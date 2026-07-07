"""Tests for ``CCXTMarketDataSource``.

The scanner protocol is async, but the phase-1 exchange components are
sync. These tests pine the adapter behavior that bridges both worlds.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from unittest.mock import MagicMock

from trading_bot.market_data.exchange_connector import CCXTExchangeConnector
from trading_bot.market_data.live_source import CCXTMarketDataSource
from trading_bot.market_data.ohlcv_fetcher import OHLCVFetcher
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore


def _make_ohlcv(symbol: str, ts: int, close: float = 100.0) -> OHLCV:
    return OHLCV(
        symbol=symbol,
        timestamp=ts,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=10.0,
    )


def test_fetch_recent_uses_fetcher_and_returns_cached_rows(tmp_path: Path) -> None:
    connector = MagicMock(spec=CCXTExchangeConnector)
    connector.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1, 100.0),
        _make_ohlcv("BTC/USDT", 2, 101.0),
    ]
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        fetcher = OHLCVFetcher(connector, store)
        source = CCXTMarketDataSource(
            connector=connector,
            fetcher=fetcher,
            store=store,
            timeframe="5m",
        )

        rows = asyncio.run(source.fetch_recent("BTC/USDT", limit=2))

    assert len(rows) == 2
    assert rows[0].timestamp == 2
    connector.fetch_ohlcv.assert_called_once_with("BTC/USDT", "5m", limit=100)


def test_fetch_24h_volume_usdt_prefers_quote_volume(tmp_path: Path) -> None:
    connector = MagicMock(spec=CCXTExchangeConnector)
    connector.fetch_ticker.return_value = {"quoteVolume": 12_345.0}
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        fetcher = OHLCVFetcher(connector, store)
        source = CCXTMarketDataSource(
            connector=connector,
            fetcher=fetcher,
            store=store,
            timeframe="5m",
        )

        volume = asyncio.run(source.fetch_24h_volume_usdt("BTC/USDT"))

    assert volume == 12_345.0


def test_fetch_24h_volume_usdt_falls_back_to_base_volume_times_last(tmp_path: Path) -> None:
    connector = MagicMock(spec=CCXTExchangeConnector)
    connector.fetch_ticker.return_value = {"quoteVolume": None, "baseVolume": 10.0, "last": 250.0}
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        fetcher = OHLCVFetcher(connector, store)
        source = CCXTMarketDataSource(
            connector=connector,
            fetcher=fetcher,
            store=store,
            timeframe="5m",
        )

        volume = asyncio.run(source.fetch_24h_volume_usdt("BTC/USDT"))

    assert volume == 2_500.0


def test_fetch_spread_bps_uses_best_bid_and_ask(tmp_path: Path) -> None:
    connector = MagicMock(spec=CCXTExchangeConnector)
    connector.fetch_order_book.return_value = {
        "bids": [[99.0, 1.0]],
        "asks": [[101.0, 1.0]],
    }
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        fetcher = OHLCVFetcher(connector, store)
        source = CCXTMarketDataSource(
            connector=connector,
            fetcher=fetcher,
            store=store,
            timeframe="5m",
        )

        spread_bps = asyncio.run(source.fetch_spread_bps("BTC/USDT"))

    assert spread_bps == 200.0


def test_fetch_spread_bps_returns_inf_for_malformed_book(tmp_path: Path) -> None:
    connector = MagicMock(spec=CCXTExchangeConnector)
    connector.fetch_order_book.return_value = {"bids": [], "asks": []}
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        fetcher = OHLCVFetcher(connector, store)
        source = CCXTMarketDataSource(
            connector=connector,
            fetcher=fetcher,
            store=store,
            timeframe="5m",
        )

        spread_bps = asyncio.run(source.fetch_spread_bps("BTC/USDT"))

    assert math.isinf(spread_bps)
