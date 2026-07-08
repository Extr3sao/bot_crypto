from __future__ import annotations

from dataclasses import replace

import pytest

from trading_bot.indicators import (
    AtrIndicator,
    BollingerBandsIndicator,
    EmaIndicator,
    IndicatorError,
    MacdIndicator,
    MomentumIndicator,
    OrderBookImbalanceIndicator,
    RsiIndicator,
    SpreadIndicator,
    VolatilityIndicator,
    VolumeRelativeIndicator,
    VwapIndicator,
    build_default_indicator_registry,
)
from trading_bot.market_data.types import OHLCV


def _candles(closes: list[float]) -> list[OHLCV]:
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1_700_000_000_000 + index * 60_000,
            open=close,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1_000.0,
        )
        for index, close in enumerate(closes)
    ]


def test_ema_returns_latest_smoothed_value() -> None:
    result = EmaIndicator().compute(_candles([1.0, 2.0, 3.0, 4.0, 5.0]), {"period": 3})
    assert result == pytest.approx(4.0, rel=1e-6)


def test_rsi_returns_100_on_strict_uptrend() -> None:
    result = RsiIndicator().compute(
        _candles([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        {"period": 5},
    )
    assert result == pytest.approx(100.0, rel=1e-6)


def test_macd_returns_positive_signal_on_uptrend() -> None:
    result = MacdIndicator().compute(
        _candles([float(value) for value in range(1, 40)]),
        {"fast": 12, "slow": 26, "signal": 9},
    )
    assert set(result) == {"macd", "signal", "histogram"}
    assert result["macd"] > 0.0


def test_atr_matches_constant_true_range() -> None:
    result = AtrIndicator().compute(_candles([10.0, 11.0, 12.0, 13.0]), {"period": 3})
    assert result == pytest.approx(2.0, rel=1e-6)


def test_bollinger_collapses_on_flat_series() -> None:
    result = BollingerBandsIndicator().compute(
        _candles([10.0] * 20), {"period": 20, "std_dev": 2.0}
    )
    assert result["middle"] == pytest.approx(10.0, rel=1e-6)
    assert result["upper"] == pytest.approx(10.0, rel=1e-6)
    assert result["lower"] == pytest.approx(10.0, rel=1e-6)


def test_default_registry_exposes_phase_2_indicator_types() -> None:
    registry = build_default_indicator_registry()
    assert registry.types() == [
        "ema",
        "rsi",
        "macd",
        "atr",
        "bollinger",
        "vwap",
        "volume_relative",
        "spread",
        "volatility",
        "momentum",
        "order_book_imbalance",
    ]
    assert registry.is_frozen is True


def test_macd_validates_fast_less_than_slow() -> None:
    with pytest.raises(IndicatorError, match="fast < slow"):
        MacdIndicator().compute(
            _candles([float(value) for value in range(1, 40)]),
            {"fast": 26, "slow": 12, "signal": 9},
        )


def test_vwap_matches_flat_typical_price() -> None:
    result = VwapIndicator().compute(_candles([10.0, 10.0, 10.0]), {"anchor": "session"})
    assert result == pytest.approx(10.0, rel=1e-6)


def test_volume_relative_detects_volume_expansion() -> None:
    candles = _candles([10.0, 10.0, 10.0, 10.0])
    candles[0] = replace(candles[0], volume=100.0)
    candles[1] = replace(candles[1], volume=100.0)
    candles[2] = replace(candles[2], volume=100.0)
    candles[3] = replace(candles[3], volume=300.0)
    result = VolumeRelativeIndicator().compute(candles, {"lookback": 3})
    assert result == pytest.approx(3.0, rel=1e-6)


def test_spread_uses_best_bid_and_ask() -> None:
    result = SpreadIndicator().compute([], {"best_bid": 99.0, "best_ask": 101.0})
    assert result == pytest.approx(200.0, rel=1e-6)


def test_volatility_is_zero_on_flat_series() -> None:
    result = VolatilityIndicator().compute(
        _candles([10.0, 10.0, 10.0, 10.0]),
        {"lookback": 3, "method": "stddev"},
    )
    assert result == pytest.approx(0.0, abs=1e-12)


def test_momentum_matches_percent_change() -> None:
    result = MomentumIndicator().compute(
        _candles([10.0, 11.0, 12.0, 15.0]),
        {"lookback": 3},
    )
    assert result == pytest.approx(0.5, rel=1e-6)


def test_order_book_imbalance_is_positive_when_bids_dominate() -> None:
    result = OrderBookImbalanceIndicator().compute(
        [],
        {
            "feature_enabled": True,
            "bids": [[100.0, 8.0], [99.5, 4.0]],
            "asks": [[100.5, 2.0], [101.0, 2.0]],
        },
    )
    assert result == pytest.approx(0.5, rel=1e-6)
