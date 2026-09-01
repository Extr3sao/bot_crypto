"""Trend-following AlphaFamily — EMA ribbon alignment + slope strength.

Orthogonal to momentum (rate-of-change) and breakout (range transition):
trend follows SUSTAINED directional structure. LONG when the EMA ribbon
is fully stacked bullish AND slope is meaningful; SHORT on the mirror.

Preregistered parameter set (do not tune to fabricate performance):
- EMA ribbon: 8/21/55 (fast/mid/slow)
- Slope threshold: slow EMA slope > 0.05% per bar
- Structural stop = 2.5 x ATR(14) — trend trades need wider stops
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.indicators.builtin import AtrIndicator, EmaIndicator
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from ..types import AlphaSignal, FeaturesBag

MIN_CANDLES = 56  # slow EMA(55) + 1 for slope
SLOPE_THRESHOLD = 0.0005  # 0.05% per bar
ATR_STOP_MULT = 2.5


class TrendFamily:
    """EMA ribbon trend family.

    LONG when ema_fast > ema_mid > ema_slow AND slow EMA slope > +0.05%/bar.
    SHORT when ema_fast < ema_mid < ema_slow AND slope < -0.05%/bar.
    Structural stop = 2.5 x ATR(14).
    """

    @property
    def family_name(self) -> str:
        return "trend"

    def generate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        features: FeaturesBag | None = None,
        **kwargs: str | float | None,
    ) -> list[AlphaSignal]:
        if len(candles) < MIN_CANDLES:
            return []

        if not indicators:
            indicators = self._compute_indicators(candles)

        ema_fast = indicators.get("ema_fast")
        ema_mid = indicators.get("ema_mid")
        ema_slow = indicators.get("ema_slow")
        ema_slow_prev = indicators.get("ema_slow_prev")
        atr = indicators.get("atr")

        vals = [ema_fast, ema_mid, ema_slow, ema_slow_prev, atr]
        if not all(
            isinstance(v, (int, float))
            for v in vals
        ):
            return []

        # mypy: the guard above narrows every element to a number; re-binding
        # the five values keeps the arithmetic below strict-clean without casts.
        ema_fast = float(ema_fast)  # type: ignore[arg-type]  # narrowed above
        ema_mid = float(ema_mid)  # type: ignore[arg-type]
        ema_slow = float(ema_slow)  # type: ignore[arg-type]
        ema_slow_prev = float(ema_slow_prev)  # type: ignore[arg-type]
        atr = float(atr)  # type: ignore[arg-type]

        if atr <= 0 or ema_slow <= 0 or ema_slow_prev <= 0:
            return []

        # Slope of slow EMA per bar (normalized)
        slope = (ema_slow - ema_slow_prev) / ema_slow_prev

        current_price = candles[-1].close
        symbol = candles[-1].symbol
        timestamp = candles[-1].timestamp

        feat = FeaturesBag(
            ema_alignment=(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else None,
            ema_slope=slope,
            atr=atr,
            atr_pct=(atr / current_price * 100) if current_price > 0 else None,
            structural_stop_width=(
                (atr * ATR_STOP_MULT) / current_price * 100
            ) if current_price > 0 else None,
        )

        signals: list[AlphaSignal] = []

        # Bullish ribbon: fully stacked + meaningful upward slope
        if ema_fast > ema_mid > ema_slow and slope > SLOPE_THRESHOLD:
            stop = current_price - atr * ATR_STOP_MULT
            signals.append(AlphaSignal(
                family=self.family_name,
                symbol=symbol,
                timestamp=timestamp,
                direction="LONG",
                entry_reference=current_price,
                structural_stop=max(stop, 0.01),
                timeframe=str(kwargs.get("timeframe", "5m")),
                features=feat,
                effective_stop=stop,
            ))

        # Bearish ribbon: fully inverted + meaningful downward slope
        if ema_fast < ema_mid < ema_slow and slope < -SLOPE_THRESHOLD:
            stop = current_price + atr * ATR_STOP_MULT
            signals.append(AlphaSignal(
                family=self.family_name,
                symbol=symbol,
                timestamp=timestamp,
                direction="SHORT",
                entry_reference=current_price,
                structural_stop=stop,
                timeframe=str(kwargs.get("timeframe", "5m")),
                features=feat,
                effective_stop=stop,
            ))

        return signals

    @staticmethod
    def _compute_indicators(candles: Sequence[OHLCV]) -> dict[str, IndicatorResult]:
        ema = EmaIndicator()
        return {
            "ema_fast": ema.compute(candles, {"period": 8}),
            "ema_mid": ema.compute(candles, {"period": 21}),
            "ema_slow": ema.compute(candles, {"period": 55}),
            # Slow EMA one bar ago: drop the last candle
            "ema_slow_prev": ema.compute(candles[:-1], {"period": 55}),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }


__all__ = ["TrendFamily"]
