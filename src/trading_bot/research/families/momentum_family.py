"""Momentum AlphaFamily — MACD histogram + price momentum confirmation.

Orthogonal to EMA crossover: momentum measures the RATE of change, not
the level alignment. LONG when MACD histogram > 0 AND price momentum
positive; SHORT on the mirror condition.

Preregistered parameter set (do not tune to fabricate performance):
- MACD 12/26/9 (industry standard, not fitted)
- Momentum lookback 10 bars, threshold 0.5%
- Structural stop = 2.0 x ATR(14)
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.indicators.builtin import (
    AtrIndicator,
    MacdIndicator,
    MomentumIndicator,
)
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from ..types import AlphaSignal, FeaturesBag

MIN_CANDLES = 36  # macd slow(26)+signal(9)-1 = 34, momentum needs 11
MOMENTUM_THRESHOLD = 0.005  # 0.5% over lookback
ATR_STOP_MULT = 2.0


class MomentumFamily:
    """MACD-histogram momentum family.

    LONG when MACD histogram > 0 AND price momentum > +0.5% over 10 bars.
    SHORT when MACD histogram < 0 AND price momentum < -0.5%.
    Structural stop = 2.0 x ATR(14).
    """

    @property
    def family_name(self) -> str:
        return "momentum"

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

        macd = indicators.get("macd")
        momentum = indicators.get("momentum")
        atr = indicators.get("atr")

        if not isinstance(macd, dict) or not all(
            isinstance(v, (int, float)) for v in [momentum, atr]
        ):
            return []

        assert isinstance(momentum, (int, float))
        assert isinstance(atr, (int, float))

        histogram = macd.get("histogram")
        if not isinstance(histogram, (int, float)) or atr <= 0:
            return []

        current_price = candles[-1].close
        symbol = candles[-1].symbol
        timestamp = candles[-1].timestamp

        feat = FeaturesBag(
            macd=macd.get("macd"),
            macd_signal=macd.get("signal"),
            macd_histogram=histogram,
            momentum=momentum,
            atr=atr,
            atr_pct=(atr / current_price * 100) if current_price > 0 else None,
            structural_stop_width=(
                (atr * ATR_STOP_MULT) / current_price * 100
            ) if current_price > 0 else None,
        )

        signals: list[AlphaSignal] = []

        if histogram > 0 and momentum > MOMENTUM_THRESHOLD:
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

        if histogram < 0 and momentum < -MOMENTUM_THRESHOLD:
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
        return {
            "macd": MacdIndicator().compute(candles, {"fast": 12, "slow": 26, "signal": 9}),
            "momentum": MomentumIndicator().compute(candles, {"lookback": 10}),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }


__all__ = ["MomentumFamily"]
