"""Built-in indicator implementations for TSK-201/202/203."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from statistics import fmean
from typing import Any

from trading_bot.market_data.types import OHLCV

from .exceptions import IndicatorError


def _require_period(params: dict[str, Any], key: str = "period") -> int:
    value = params.get(key)
    if not isinstance(value, int) or value <= 0:
        raise IndicatorError(f"Parametro {key!r} debe ser int > 0.")
    return value


def _require_float(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if not isinstance(value, (int, float)):
        raise IndicatorError(f"Parametro {key!r} debe ser numerico.")
    return float(value)


def _require_candles(candles: Sequence[OHLCV], minimum: int, indicator_type: str) -> None:
    if len(candles) < minimum:
        raise IndicatorError(
            f"{indicator_type} requiere al menos {minimum} velas; got {len(candles)}."
        )


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        raise IndicatorError(f"ema requiere al menos {period} valores; got {len(values)}.")
    seed = fmean(values[:period])
    multiplier = 2.0 / (period + 1.0)
    series = [seed]
    ema = seed
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        series.append(ema)
    return series


def _returns_series(closes: Sequence[float]) -> list[float]:
    if len(closes) < 2:
        return []
    returns: list[float] = []
    for previous, current in itertools.pairwise(closes):
        if previous <= 0.0:
            raise IndicatorError("No se pueden calcular returns con closes <= 0.")
        returns.append((current - previous) / previous)
    return returns


class EmaIndicator:
    indicator_type = "ema"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        period = _require_period(params)
        _require_candles(candles, period, self.indicator_type)
        closes = [candle.close for candle in candles]
        return _ema_series(closes, period)[-1]


class RsiIndicator:
    indicator_type = "rsi"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        period = _require_period(params)
        _require_candles(candles, period + 1, self.indicator_type)
        closes = [candle.close for candle in candles]
        deltas = [curr - prev for prev, curr in itertools.pairwise(closes)]
        gains = [max(delta, 0.0) for delta in deltas]
        losses = [max(-delta, 0.0) for delta in deltas]

        avg_gain = fmean(gains[:period])
        avg_loss = fmean(losses[:period])
        for gain, loss in zip(gains[period:], losses[period:], strict=False):
            avg_gain = ((avg_gain * (period - 1)) + gain) / period
            avg_loss = ((avg_loss * (period - 1)) + loss) / period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


class MacdIndicator:
    indicator_type = "macd"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> dict[str, float]:
        fast = _require_period(params, "fast")
        slow = _require_period(params, "slow")
        signal = _require_period(params, "signal")
        if fast >= slow:
            raise IndicatorError("macd requiere fast < slow.")
        _require_candles(candles, slow + signal - 1, self.indicator_type)
        closes = [candle.close for candle in candles]
        fast_series = _ema_series(closes, fast)
        slow_series = _ema_series(closes, slow)
        aligned_fast = fast_series[(slow - fast) :]
        macd_series = [
            fast_value - slow_value
            for fast_value, slow_value in zip(aligned_fast, slow_series, strict=False)
        ]
        signal_series = _ema_series(macd_series, signal)
        macd_value = macd_series[-1]
        signal_value = signal_series[-1]
        return {
            "macd": macd_value,
            "signal": signal_value,
            "histogram": macd_value - signal_value,
        }


class AtrIndicator:
    indicator_type = "atr"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        period = _require_period(params)
        _require_candles(candles, period + 1, self.indicator_type)
        true_ranges: list[float] = []
        previous_close = candles[0].close
        for candle in candles[1:]:
            true_ranges.append(
                max(
                    candle.high - candle.low,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            )
            previous_close = candle.close

        atr = fmean(true_ranges[:period])
        for tr in true_ranges[period:]:
            atr = ((atr * (period - 1)) + tr) / period
        return atr


class BollingerBandsIndicator:
    indicator_type = "bollinger"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> dict[str, float]:
        period = _require_period(params)
        std_dev = params.get("std_dev")
        if not isinstance(std_dev, (int, float)) or float(std_dev) <= 0.0:
            raise IndicatorError("Parametro 'std_dev' debe ser numero > 0.")
        _require_candles(candles, period, self.indicator_type)
        closes = [candle.close for candle in candles[-period:]]
        middle = fmean(closes)
        variance = sum((close - middle) ** 2 for close in closes) / period
        deviation = math.sqrt(variance)
        width = deviation * float(std_dev)
        return {
            "middle": middle,
            "upper": middle + width,
            "lower": middle - width,
        }


class VwapIndicator:
    indicator_type = "vwap"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        anchor = params.get("anchor", "session")
        if anchor not in {"session", "rolling"}:
            raise IndicatorError("Parametro 'anchor' debe ser 'session' o 'rolling'.")
        selected = list(candles)
        if anchor == "rolling":
            rolling_period = _require_period(params, "rolling_period")
            _require_candles(candles, rolling_period, self.indicator_type)
            selected = list(candles[-rolling_period:])
        elif not selected:
            raise IndicatorError("vwap requiere al menos 1 vela; got 0.")

        weighted_price_volume = 0.0
        total_volume = 0.0
        for candle in selected:
            typical_price = (candle.high + candle.low + candle.close) / 3.0
            weighted_price_volume += typical_price * candle.volume
            total_volume += candle.volume
        if total_volume <= 0.0:
            raise IndicatorError("vwap requiere volumen agregado > 0.")
        return weighted_price_volume / total_volume


class VolumeRelativeIndicator:
    indicator_type = "volume_relative"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        lookback = _require_period(params, "lookback")
        _require_candles(candles, lookback + 1, self.indicator_type)
        current_volume = candles[-1].volume
        baseline = fmean(candle.volume for candle in candles[-(lookback + 1) : -1])
        if baseline <= 0.0:
            raise IndicatorError("volume_relative requiere baseline de volumen > 0.")
        return current_volume / baseline


class SpreadIndicator:
    indicator_type = "spread"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        del candles
        if "spread_bps" in params:
            return _require_float(params, "spread_bps")
        best_bid = _require_float(params, "best_bid")
        best_ask = _require_float(params, "best_ask")
        if best_bid <= 0.0 or best_ask <= 0.0 or best_ask < best_bid:
            raise IndicatorError("spread requiere best_bid/best_ask validos.")
        midpoint = (best_bid + best_ask) / 2.0
        return ((best_ask - best_bid) / midpoint) * 10_000.0


class VolatilityIndicator:
    indicator_type = "volatility"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        lookback = _require_period(params, "lookback")
        method = params.get("method", "stddev")
        if method != "stddev":
            raise IndicatorError("volatility solo soporta method='stddev'.")
        _require_candles(candles, lookback + 1, self.indicator_type)
        closes = [candle.close for candle in candles[-(lookback + 1) :]]
        returns = _returns_series(closes)
        if not returns:
            return 0.0
        mean_return = fmean(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
        return math.sqrt(variance)


class MomentumIndicator:
    indicator_type = "momentum"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        lookback = _require_period(params, "lookback")
        _require_candles(candles, lookback + 1, self.indicator_type)
        start_close = candles[-(lookback + 1)].close
        end_close = candles[-1].close
        if start_close <= 0.0:
            raise IndicatorError("momentum requiere close inicial > 0.")
        return (end_close / start_close) - 1.0


class OrderBookImbalanceIndicator:
    indicator_type = "order_book_imbalance"

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        del candles
        if params.get("feature_enabled") is not True:
            raise IndicatorError(
                "order_book_imbalance requiere feature_enabled=True para activarse."
            )
        bids = params.get("bids")
        asks = params.get("asks")
        if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
            raise IndicatorError("order_book_imbalance requiere bids/asks no vacios.")

        def _sum_sizes(levels: list[Any]) -> float:
            total = 0.0
            for level in levels:
                if not isinstance(level, (list, tuple)) or len(level) < 2:
                    raise IndicatorError("Cada nivel del order book debe ser [price, size].")
                size = level[1]
                if not isinstance(size, (int, float)) or float(size) < 0.0:
                    raise IndicatorError("Cada size del order book debe ser >= 0.")
                total += float(size)
            return total

        bid_volume = _sum_sizes(bids)
        ask_volume = _sum_sizes(asks)
        total = bid_volume + ask_volume
        if total <= 0.0:
            raise IndicatorError("order_book_imbalance requiere volumen total > 0.")
        return (bid_volume - ask_volume) / total


__all__ = [
    "AtrIndicator",
    "BollingerBandsIndicator",
    "EmaIndicator",
    "MacdIndicator",
    "MomentumIndicator",
    "OrderBookImbalanceIndicator",
    "RsiIndicator",
    "SpreadIndicator",
    "VolatilityIndicator",
    "VolumeRelativeIndicator",
    "VwapIndicator",
]
