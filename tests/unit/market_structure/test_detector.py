from __future__ import annotations

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.market_structure import detect_market_structure, distance_to_zone_bps


def _candle(
    ts: int, open_: float, high: float, low: float, close: float, volume: float = 100.0
) -> OHLCV:
    return OHLCV(
        symbol="BTC/USDT",
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_detects_support_and_resistance_pivots() -> None:
    candles = [
        _candle(1, 100, 103, 99, 102),
        _candle(2, 102, 105, 101, 104),
        _candle(3, 104, 106, 95, 96),
        _candle(4, 96, 99, 94, 98),
        _candle(5, 98, 110, 97, 109),
        _candle(6, 109, 108, 103, 104),
        _candle(7, 104, 106, 102, 103),
    ]

    zones = detect_market_structure(candles, symbol="BTC/USDT", timeframe="1m", swing_window=1)

    assert any(zone.kind == "support" and zone.low == 94 for zone in zones)
    assert any(zone.kind == "resistance" and zone.high == 110 for zone in zones)
    assert any(zone.kind == "range_low" for zone in zones)
    assert any(zone.kind == "range_high" for zone in zones)


def test_detects_order_block_before_impulse() -> None:
    candles = [
        _candle(1, 100, 101, 99, 100),
        _candle(2, 100, 101, 98, 99),
        _candle(3, 99, 108, 98, 107),
        _candle(4, 107, 109, 106, 108),
        _candle(5, 108, 109, 107, 108),
    ]

    zones = detect_market_structure(candles, symbol="BTC/USDT", timeframe="1m")
    order_blocks = [zone for zone in zones if zone.kind == "order_block"]

    assert order_blocks
    assert order_blocks[0].source == "opposite_candle_before_atr_impulse"
    assert order_blocks[0].low == 99
    assert order_blocks[0].high == 100


def test_detects_accumulation_in_tight_range_with_relative_volume() -> None:
    candles = [
        _candle(1, 100, 102, 99, 101, 50),
        _candle(2, 101, 102, 100, 101, 50),
        _candle(3, 101, 101.2, 100.9, 101.1, 200),
        _candle(4, 101.1, 101.3, 101.0, 101.2, 210),
        _candle(5, 101.2, 101.4, 101.1, 101.3, 220),
        _candle(6, 101.3, 101.5, 101.2, 101.4, 230),
        _candle(7, 101.4, 101.6, 101.3, 101.5, 240),
        _candle(8, 101.5, 101.7, 101.4, 101.6, 250),
        _candle(9, 101.6, 101.8, 101.5, 101.7, 260),
        _candle(10, 101.7, 101.9, 101.6, 101.8, 270),
    ]

    zones = detect_market_structure(candles, symbol="BTC/USDT", timeframe="1m")

    assert any(zone.kind == "accumulation" for zone in zones)


def test_distance_to_zone_bps_returns_zero_inside_zone() -> None:
    zone = detect_market_structure(
        [
            _candle(1, 100, 101, 99, 100),
            _candle(2, 100, 103, 99, 102),
            _candle(3, 102, 104, 101, 103),
            _candle(4, 103, 105, 102, 104),
            _candle(5, 104, 106, 103, 105),
        ],
        symbol="BTC/USDT",
        timeframe="1m",
    )[0]

    assert distance_to_zone_bps((zone.low + zone.high) / 2, zone) == 0.0


def test_distance_to_zone_bps_rejects_invalid_price() -> None:
    zone = detect_market_structure(
        [
            _candle(1, 100, 101, 99, 100),
            _candle(2, 100, 103, 99, 102),
            _candle(3, 102, 104, 101, 103),
            _candle(4, 103, 105, 102, 104),
            _candle(5, 104, 106, 103, 105),
        ],
        symbol="BTC/USDT",
        timeframe="1m",
    )[0]

    with pytest.raises(ValueError, match="price must be > 0"):
        distance_to_zone_bps(0, zone)
