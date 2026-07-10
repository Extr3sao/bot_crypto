"""Tests for ``OHLCVFetcher``.

Estrategia: mock ``ExchangeConnector`` con ``MagicMock`` y crear
``OHLCVStore`` real con SQLite sobre ``tmp_path``. El ``clock_fn``
inyectable verifica que el fetcher consume el reloj (para logging).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.ohlcv_fetcher import OHLCVFetcher
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore


def _make_ohlcv(symbol: str, ts: int, close: float = 100.0) -> OHLCV:
    return OHLCV(
        symbol=symbol,
        timestamp=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10.0,
    )


@pytest.fixture
def store(tmp_path: Path) -> OHLCVStore:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as s:
        yield s
    # __exit__ del context manager cierra la conexion al final del yield.


@pytest.fixture
def connector_mock() -> MagicMock:
    return MagicMock(spec=ExchangeConnector)


def test_fetch_and_cache_pulls_persists_returns_from_store(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    connector_mock.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
        _make_ohlcv("BTC/USDT", 1672534800000, 200.0),
    ]
    fetcher = OHLCVFetcher(connector_mock, store)
    result = fetcher.fetch_and_cache("BTC/USDT", "1h", limit=2)
    assert len(result) == 2
    # DESC order (store.get_ohlcv devuelve DESC).
    assert result[0].timestamp == 1672534800000
    connector_mock.fetch_ohlcv.assert_called_once_with(
        "BTC/USDT",
        "1h",
        limit=2,
    )


def test_re_fetch_is_idempotent_no_duplicates(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    connector_mock.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
    ]
    fetcher = OHLCVFetcher(connector_mock, store)
    fetcher.fetch_and_cache("BTC/USDT", "1h", limit=1)
    fetcher.fetch_and_cache("BTC/USDT", "1h", limit=1)
    rows = store.get_ohlcv("BTC/USDT", limit=10)
    assert len(rows) == 1


def test_re_fetch_with_corrected_value_overwrites_last_write_wins(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    fetcher = OHLCVFetcher(connector_mock, store)
    connector_mock.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
    ]
    fetcher.fetch_and_cache("BTC/USDT", "1h", limit=1)
    # Vela "en curso" recibe correccion tardia con close=250.
    connector_mock.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1672531200000, 250.0),
    ]
    fetcher.fetch_and_cache("BTC/USDT", "1h", limit=1)
    rows = store.get_ohlcv("BTC/USDT", limit=10)
    assert len(rows) == 1
    assert rows[0].close == 250.0


def test_connector_exception_propagates_and_store_untouched(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    connector_mock.fetch_ohlcv.side_effect = RuntimeError("boom")
    fetcher = OHLCVFetcher(connector_mock, store)
    with pytest.raises(RuntimeError, match="boom"):
        fetcher.fetch_and_cache("BTC/USDT", "1h", limit=1)
    # La excepcion se eleva antes del upsert: store vacio.
    rows = store.get_ohlcv("BTC/USDT", limit=10)
    assert rows == []


def test_nan_values_are_dropped(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    connector_mock.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1672534800000,
            open=float("nan"),
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10.0,
        ),
    ]
    fetcher = OHLCVFetcher(connector_mock, store)
    result = fetcher.fetch_and_cache("BTC/USDT", "1h", limit=2)
    assert len(result) == 1
    assert result[0].timestamp == 1672531200000


def test_high_less_than_low_is_dropped(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    connector_mock.fetch_ohlcv.return_value = [
        # Vela con high < low (corrupta): descartar.
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1672531200000,
            open=100.0,
            high=50.0,
            low=200.0,
            close=100.0,
            volume=10.0,
        ),
        _make_ohlcv("BTC/USDT", 1672534800000, 100.0),
    ]
    fetcher = OHLCVFetcher(connector_mock, store)
    result = fetcher.fetch_and_cache("BTC/USDT", "1h", limit=2)
    assert len(result) == 1
    assert result[0].timestamp == 1672534800000


def test_clock_fn_invoked_at_least_once(
    store: OHLCVStore,
    connector_mock: MagicMock,
) -> None:
    connector_mock.fetch_ohlcv.return_value = [
        _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
    ]
    clock = MagicMock(return_value=1672534900000.0)
    fetcher = OHLCVFetcher(connector_mock, store, clock_fn=clock)
    fetcher.fetch_and_cache("BTC/USDT", "1h", limit=1)
    assert clock.called
