"""Breakout AlphaFamily — Donchian channel breakout with volume confirmation.

Orthogonal to trend/momentum: breakout catches the TRANSITION from
range to expansion. LONG when price closes above the N-bar high with
elevated volume; SHORT below the N-bar low.

Preregistered parameter set (do not tune to fabricate performance):
- Donchian channel: 20 bars (classic turtle, not fitted)
- Volume confirmation: current volume > 1.5x 20-bar average
- Structural stop = channel midpoint (inside the broken range)
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.indicators.builtin import AtrIndicator, VolumeRelativeIndicator
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from ..types import AlphaSignal, FeaturesBag

MIN_CANDLES = 21  # donchian(20) + current bar
DONCHIAN_PERIOD = 20
VOLUME_CONFIRM = 1.5
ATR_STOP_MULT = 1.5  # tighter stop: breakout failure means wrong side


class BreakoutFamily:
    """Donchian breakout family.

    LONG when close breaks above the 20-bar high AND volume > 1.5x average.
    SHORT when close breaks below the 20-bar low AND volume > 1.5x average.
    Structural stop = ATR-based (breakouts fail fast; keep stops tight).
    """

    @property
    def family_name(self) -> str:
        return "breakout"

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

        vol_rel = indicators.get("volume_relative")
        atr = indicators.get("atr")

        if not all(isinstance(v, (int, float)) for v in [vol_rel, atr]):
            return []

        assert isinstance(vol_rel, (int, float))
        assert isinstance(atr, (int, float))

        if atr <= 0:
            return []

        # Donchian channel from the PREVIOUS 20 bars (excluding current)
        window = candles[-(DONCHIAN_PERIOD + 1) : -1]
        channel_high = max(c.high for c in window)
        channel_low = min(c.low for c in window)

        current_price = candles[-1].close
        symbol = candles[-1].symbol
        timestamp = candles[-1].timestamp

        feat = FeaturesBag(
            volume_ratio=vol_rel,
            atr=atr,
            atr_pct=(atr / current_price * 100) if current_price > 0 else None,
            structural_stop_width=((atr * ATR_STOP_MULT) / current_price * 100)
            if current_price > 0
            else None,
            custom={
                "channel_high": channel_high,
                "channel_low": channel_low,
            },
        )

        signals: list[AlphaSignal] = []

        # Upside breakout: close above previous high, volume confirmed
        if current_price > channel_high and vol_rel >= VOLUME_CONFIRM:
            stop = current_price - atr * ATR_STOP_MULT
            signals.append(
                AlphaSignal(
                    family=self.family_name,
                    symbol=symbol,
                    timestamp=timestamp,
                    direction="LONG",
                    entry_reference=current_price,
                    structural_stop=max(stop, 0.01),
                    timeframe=str(kwargs.get("timeframe", "5m")),
                    features=feat,
                    effective_stop=stop,
                )
            )

        # Downside breakout: close below previous low, volume confirmed
        if current_price < channel_low and vol_rel >= VOLUME_CONFIRM:
            stop = current_price + atr * ATR_STOP_MULT
            signals.append(
                AlphaSignal(
                    family=self.family_name,
                    symbol=symbol,
                    timestamp=timestamp,
                    direction="SHORT",
                    entry_reference=current_price,
                    structural_stop=stop,
                    timeframe=str(kwargs.get("timeframe", "5m")),
                    features=feat,
                    effective_stop=stop,
                )
            )

        return signals

    @staticmethod
    def _compute_indicators(candles: Sequence[OHLCV]) -> dict[str, IndicatorResult]:
        return {
            "volume_relative": VolumeRelativeIndicator().compute(
                candles, {"lookback": DONCHIAN_PERIOD}
            ),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }


__all__ = ["BreakoutFamily"]
