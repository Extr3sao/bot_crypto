from __future__ import annotations

from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from trading_bot.indicators import (
    BollingerBandsIndicator,
    EmaIndicator,
    MomentumIndicator,
    OrderBookImbalanceIndicator,
    RsiIndicator,
    VolatilityIndicator,
    VolumeRelativeIndicator,
)
from trading_bot.market_data.types import OHLCV


def _candles_from_closes(closes: list[float]) -> list[OHLCV]:
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1_700_000_000_000 + index * 60_000,
            open=close,
            high=close + 1.0,
            low=max(close - 1.0, 0.0001),
            close=close,
            volume=100.0 + index,
        )
        for index, close in enumerate(closes)
    ]


positive_closes = st.lists(
    st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    min_size=6,
    max_size=40,
)


@given(
    start=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    step=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
)
def test_ema_is_bounded_by_latest_window_values(start: float, step: float) -> None:
    closes = [start + step * index for index in range(8)]
    candles = _candles_from_closes(closes)
    period = 5
    result = EmaIndicator().compute(candles, {"period": period})
    window = closes[-period:]
    assert min(window) <= result <= max(window)


@given(positive_closes)
def test_rsi_stays_in_closed_interval(closes: list[float]) -> None:
    result = RsiIndicator().compute(_candles_from_closes(closes), {"period": 5})
    assert 0.0 <= result <= 100.0


@given(positive_closes)
def test_bollinger_bands_are_ordered(closes: list[float]) -> None:
    result = BollingerBandsIndicator().compute(
        _candles_from_closes(closes),
        {"period": 5, "std_dev": 2.0},
    )
    assert result["lower"] <= result["middle"] <= result["upper"]


@given(positive_closes)
def test_volatility_is_non_negative_and_deterministic(closes: list[float]) -> None:
    candles = _candles_from_closes(closes)
    params = {"lookback": 5, "method": "stddev"}
    first = VolatilityIndicator().compute(candles, params)
    second = VolatilityIndicator().compute(candles, params)
    assert first >= 0.0
    assert first == second


@given(
    base=st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    current_volume=st.floats(
        min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_volume_relative_is_non_negative(base: float, current_volume: float) -> None:
    candles = _candles_from_closes([10.0, 10.5, 11.0, 11.5])
    candles[0] = replace(candles[0], volume=base)
    candles[1] = replace(candles[1], volume=base)
    candles[2] = replace(candles[2], volume=base)
    candles[3] = replace(candles[3], volume=current_volume)
    result = VolumeRelativeIndicator().compute(candles, {"lookback": 3})
    assert result >= 0.0


@given(
    start=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    end=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_momentum_sign_matches_price_direction(start: float, end: float) -> None:
    candles = _candles_from_closes([start, start, start, end])
    result = MomentumIndicator().compute(candles, {"lookback": 3})
    if end > start:
        assert result > 0.0
    elif end < start:
        assert result < 0.0
    else:
        assert result == 0.0


@given(
    bid_1=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    bid_2=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    ask_1=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    ask_2=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
)
def test_order_book_imbalance_stays_in_unit_interval(
    bid_1: float,
    bid_2: float,
    ask_1: float,
    ask_2: float,
) -> None:
    result = OrderBookImbalanceIndicator().compute(
        [],
        {
            "feature_enabled": True,
            "bids": [[100.0, bid_1], [99.5, bid_2]],
            "asks": [[100.5, ask_1], [101.0, ask_2]],
        },
    )
    assert -1.0 <= result <= 1.0
