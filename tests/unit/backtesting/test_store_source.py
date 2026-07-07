"""Tests for the OHLCVStore -> backtesting adapter."""

from __future__ import annotations

from pathlib import Path

from trading_bot.backtesting.store_source import OHLCVStoreSource
from trading_bot.backtesting.types import OHLCVSourceProtocol
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore


def _make_market_ohlcv(symbol: str, ts: int, close: float) -> OHLCV:
    return OHLCV(
        symbol=symbol,
        timestamp=ts,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=10.0,
    )


def test_store_source_implements_protocol(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        source = OHLCVStoreSource(store)
        assert isinstance(source, OHLCVSourceProtocol)


def test_store_source_iter_candles_reads_ascending_range(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        store.upsert_ohlcv([
            _make_market_ohlcv("BTC/USDT", 1672531200000, 100.0),
            _make_market_ohlcv("BTC/USDT", 1672531260000, 101.0),
            _make_market_ohlcv("BTC/USDT", 1672531320000, 102.0),
        ])
        source = OHLCVStoreSource(store)
        rows = list(source.iter_candles("BTC/USDT", 1672531200000, 1672531320000))
        assert [row.timestamp for row in rows] == [
            1672531200000,
            1672531260000,
            1672531320000,
        ]
        assert [row.close for row in rows] == [100.0, 101.0, 102.0]


def test_store_source_iter_candles_filters_symbol_and_bounds(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        store.upsert_ohlcv([
            _make_market_ohlcv("BTC/USDT", 1672531200000, 100.0),
            _make_market_ohlcv("ETH/USDT", 1672531200000, 200.0),
            _make_market_ohlcv("BTC/USDT", 1672531400000, 110.0),
        ])
        source = OHLCVStoreSource(store)
        rows = list(source.iter_candles("BTC/USDT", 1672531100000, 1672531300000))
        assert len(rows) == 1
        assert rows[0].symbol == "BTC/USDT"
        assert rows[0].timestamp == 1672531200000
