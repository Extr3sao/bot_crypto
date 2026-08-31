"""Volatility Squeeze AlphaFamily — Bollinger/Keltner squeeze release.

Orthogonal to all directional families: squeeze trades VOLATILITY
COMPRESSION releasing into expansion. The direction of the release
determines LONG/SHORT — no direction bias.

Preregistered parameter set (do not tune to fabricate performance):
- Bollinger: 20-period, 2.0 std_dev
- Keltner: 20-period EMA, 1.5 x ATR(10) band
- Squeeze: Bollinger inside Keltner for >= 6 consecutive bars
- Release: close outside Bollinger band ends the squeeze
- Structural stop = opposite side of the squeeze box
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.indicators.builtin import AtrIndicator, BollingerBandsIndicator, EmaIndicator
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from ..types import AlphaSignal, FeaturesBag

MIN_CANDLES = 27  # bollinger(20) + squeeze tracking(6) + 1
BB_PERIOD = 20
BB_STD = 2.0
KC_PERIOD = 20
KC_ATR_PERIOD = 10
KC_ATR_MULT = 1.5
MIN_SQUEEZE_BARS = 6


class VolatilityFamily:
    """Bollinger/Keltner squeeze family.

    Squeeze: Bollinger band inside Keltner channel for >= 6 consecutive bars.
    Release: current bar closes outside the Bollinger band → signal in
    that direction. Structural stop = opposite side of the squeeze box.
    """

    @property
    def family_name(self) -> str:
        return "volatility"

    def generate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        features: FeaturesBag | None = None,
        **kwargs: str | float | None,
    ) -> list[AlphaSignal]:
        if len(candles) < MIN_CANDLES + MIN_SQUEEZE_BARS:
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

        bb_upper = bb.get("upper")
        bb_lower = bb.get("lower")
        if not isinstance(bb_upper, (int, float)) or not isinstance(bb_lower, (int, float)):
            return []

        # Keltner channel over the recent window (computed per bar to
        # detect the squeeze condition without extra indicator machinery)
        squeeze_bars = 0
        for i in range(MIN_SQUEEZE_BARS, 0, -1):
            window = candles[:-i]
            if len(window) < KC_PERIOD + KC_ATR_PERIOD:
                break
            keltner = self._keltner(window)
            if keltner is None:
                break
            if bb_upper < keltner["upper"] and bb_lower > keltner["lower"]:
                squeeze_bars += 1
            else:
                break

        # Squeeze must have been active for >= MIN_SQUEEZE_BARS
        if squeeze_bars < MIN_SQUEEZE_BARS:
            return []

        current_price = candles[-1].close
        symbol = candles[-1].symbol
        timestamp = candles[-1].timestamp

        # Keltner channel over the recent window (computed per bar to
        # detect the squeeze condition without extra indicator machinery)
        keltner = self._keltner(candles)
        if keltner is None:
            return []

        feat = FeaturesBag(
            atr=atr,
            atr_pct=(atr / current_price * 100) if current_price > 0 else None,
            custom={
                "squeeze_bars": squeeze_bars,
                "keltner_upper": keltner["upper"],
                "keltner_lower": keltner["lower"],
            },
        )

        signals: list[AlphaSignal] = []

        # Release upward: close above Bollinger upper band
        if current_price > bb_upper:
            stop = keltner["lower"]
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

        # Release downward: close below Bollinger lower band
        if current_price < bb_lower:
            stop = keltner["upper"]
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
    def _keltner(candles: Sequence[OHLCV]) -> dict[str, float] | None:
        if len(candles) < KC_PERIOD + KC_ATR_PERIOD:
            return None
        middle = EmaIndicator().compute(candles, {"period": KC_PERIOD})
        atr = AtrIndicator().compute(candles, {"period": KC_ATR_PERIOD})
        offset = atr * KC_ATR_MULT
        return {"upper": middle + offset, "lower": middle - offset}

    @staticmethod
    def _compute_indicators(candles: Sequence[OHLCV]) -> dict[str, IndicatorResult]:
        return {
            "bollinger": BollingerBandsIndicator().compute(
                candles, {"period": BB_PERIOD, "std_dev": BB_STD}
            ),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }


__all__ = ["VolatilityFamily"]
