from __future__ import annotations

from trading_bot.indicators import IndicatorCache
from trading_bot.market_data.types import OHLCV


def _candles(last_timestamp: int) -> list[OHLCV]:
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=last_timestamp,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10.0,
        )
    ]


def test_cache_reuses_result_with_same_key() -> None:
    cache = IndicatorCache()
    calls = {"n": 0}

    def compute() -> float:
        calls["n"] += 1
        return 42.0

    first = cache.get_or_compute("ema_fast", {"period": 9}, _candles(1), compute)
    second = cache.get_or_compute("ema_fast", {"period": 9}, _candles(1), compute)
    assert first == 42.0
    assert second == 42.0
    assert calls["n"] == 1


def test_cache_invalidates_on_new_candle_by_default() -> None:
    cache = IndicatorCache()
    calls = {"n": 0}

    def compute() -> float:
        calls["n"] += 1
        return float(calls["n"])

    first = cache.get_or_compute("ema_fast", {"period": 9}, _candles(1), compute)
    second = cache.get_or_compute("ema_fast", {"period": 9}, _candles(2), compute)
    assert first == 1.0
    assert second == 2.0
    assert calls["n"] == 2


def test_cache_can_ignore_new_candle_when_disabled() -> None:
    cache = IndicatorCache(invalidate_on_new_candle=False)
    calls = {"n": 0}

    def compute() -> float:
        calls["n"] += 1
        return 7.0

    first = cache.get_or_compute("ema_fast", {"period": 9}, _candles(1), compute)
    second = cache.get_or_compute("ema_fast", {"period": 9}, _candles(2), compute)
    assert first == 7.0
    assert second == 7.0
    assert calls["n"] == 1
