"""Mean Reversion AlphaFamily — Bollinger Band reversion from extremes.

Orthogonal to trend/momentum/breakout: mean reversion profits from
OVEREXTENSION snapping back. LONG when price closes below the lower
Bollinger band then re-enters the band; SHORT on the mirror.

Preregistered parameter set (do not tune to fabricate performance):
- Bollinger: 20-period, 2.0 std_dev
- Re-entry confirmation: previous bar outside band, current bar back inside
- Structural stop = 1.5 x ATR(14) beyond the band extreme
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.indicators.builtin import AtrIndicator, BollingerBandsIndicator
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from ..types import AlphaSignal, FeaturesBag

MIN_CANDLES = 22  # bollinger(20) + previous bar for re-entry check
BB_PERIOD = 20
BB_STD = 2.0
ATR_STOP_MULT = 1.5


class MeanReversionFamily:
    """Bollinger mean-reversion family.

    LONG when previous bar closed below lower band AND current bar
    closes back above lower band (re-entry confirmation).
    SHORT on the mirror (above upper → back below upper).
    Structural stop = band extreme ± 1.5 x ATR(14).
    """

    @property
    def family_name(self) -> str:
        return "mean_reversion"

    def generate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        features: FeaturesBag | None = None,
        **kwargs: str | float | None,
    ) -> list[AlphaSignal]:
        if len(candles) < MIN_CANDLES + 1:
            return []

        if not indicators:
            indicators = self._compute_indicators(candles)

        bb = indicators.get("bollinger")
        atr = indicators.get("atr")

        if not isinstance(bb, dict) or not isinstance(atr, (int, float)):
            return []

        assert isinstance(atr, (int, float))

        if atr <= 0:
            return []

        current_price = candles[-1].close
        prev_price = candles[-2].close
        symbol = candles[-1].symbol
        timestamp = candles[-1].timestamp

        upper = bb.get("upper")
        lower = bb.get("lower")
        if not isinstance(upper, (int, float)) or not isinstance(lower, (int, float)):
            return []

        feat = FeaturesBag(
            atr=atr,
            atr_pct=(atr / current_price * 100) if current_price > 0 else None,
            distance_to_ema=(current_price - bb["middle"]) / bb["middle"] if bb["middle"] > 0 else None,
            structural_stop_width=(
                (atr * ATR_STOP_MULT) / current_price * 100
            ) if current_price > 0 else None,
        )

        signals: list[AlphaSignal] = []

        # LONG: prev bar below lower band, current bar back above lower band
        if prev_price < lower and current_price > lower:
            stop = lower - atr * ATR_STOP_MULT
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

        # SHORT: prev bar above upper band, current bar back below upper band
        if prev_price > upper and current_price < upper:
            stop = upper + atr * ATR_STOP_MULT
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
            "bollinger": BollingerBandsIndicator().compute(
                candles, {"period": BB_PERIOD, "std_dev": BB_STD}
            ),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }


__all__ = ["MeanReversionFamily"]
