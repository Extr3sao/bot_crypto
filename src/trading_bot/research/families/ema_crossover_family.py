"""EMA Crossover AlphaFamily — wraps existing EmaCrossoverStrategy (FASE 3, P5).

Demonstrates how to adapt the existing strategy to the AlphaFamily interface.
This is the FIRST family; more will follow.

The family generates AlphaSignals with:
- Structural stop from ATR
- Diagnostic features (RSI, EMA alignment, etc.)
- Direction based on EMA crossover + RSI confirmation
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.indicators.builtin import AtrIndicator, EmaIndicator, RsiIndicator
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from ..types import AlphaSignal, FeaturesBag


class EmaCrossoverFamily:
    """EMA crossover alpha family.

    Generates LONG when fast EMA > slow EMA + RSI > 50.
    Generates SHORT when fast EMA < slow EMA + RSI < 50.
    Structural stop = ATR-based.
    """

    @property
    def family_name(self) -> str:
        return "ema_crossover"

    def generate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        features: FeaturesBag | None = None,
        **kwargs: str | float | None,
    ) -> list[AlphaSignal]:
        # Guardia anti-panic (FASE 9): il PortfolioBacktestEngine invia
        # lookback a partire da 3 barre; gli indicatori richiesti
        # (EMA21, RSI14+1, ATR14) necessitano almeno 22 barre. Senza
        # abbastanza storico la family NON genera segnali (non è un
        # cambio di regole: le condizioni di ingresso restano identiche).
        if len(candles) < 22:
            return []

        # Compute indicators if not provided
        if not indicators:
            indicators = self._compute_indicators(candles)

        fast_ema = indicators.get("ema_fast")
        slow_ema = indicators.get("ema_slow")
        rsi = indicators.get("rsi")
        atr = indicators.get("atr")

        if not all(isinstance(v, (int, float)) for v in [fast_ema, slow_ema, rsi, atr]):
            return []

        assert isinstance(fast_ema, (int, float))
        assert isinstance(slow_ema, (int, float))
        assert isinstance(rsi, (int, float))
        assert isinstance(atr, (int, float))

        if atr <= 0:
            return []

        current_price = candles[-1].close
        symbol = candles[-1].symbol
        timestamp = candles[-1].timestamp

        # Build features bag (P7: diagnostic, not rules)
        feat = FeaturesBag(
            rsi=rsi,
            atr=atr,
            atr_pct=(atr / current_price * 100) if current_price > 0 else None,
            ema_alignment=(fast_ema - slow_ema) / slow_ema if slow_ema > 0 else None,
            structural_stop_width=(atr * 1.5 / current_price * 100) if current_price > 0 else None,
        )

        signals: list[AlphaSignal] = []

        # LONG
        if fast_ema > slow_ema and rsi > 50:
            structural_stop = current_price - atr * 1.5
            signals.append(
                AlphaSignal(
                    family=self.family_name,
                    symbol=symbol,
                    timestamp=timestamp,
                    direction="LONG",
                    entry_reference=current_price,
                    structural_stop=max(structural_stop, 0.01),
                    timeframe=str(kwargs.get("timeframe", "5m")),
                    features=feat,
                    effective_stop=structural_stop,
                )
            )

        # SHORT
        if fast_ema < slow_ema and rsi < 50:
            structural_stop = current_price + atr * 1.5
            signals.append(
                AlphaSignal(
                    family=self.family_name,
                    symbol=symbol,
                    timestamp=timestamp,
                    direction="SHORT",
                    entry_reference=current_price,
                    structural_stop=structural_stop,
                    timeframe=str(kwargs.get("timeframe", "5m")),
                    features=feat,
                    effective_stop=structural_stop,
                )
            )

        return signals

    @staticmethod
    def _compute_indicators(candles: Sequence[OHLCV]) -> dict[str, IndicatorResult]:
        """Compute indicator values from candles."""
        return {
            "ema_fast": EmaIndicator().compute(candles, {"period": 9}),
            "ema_slow": EmaIndicator().compute(candles, {"period": 21}),
            "rsi": RsiIndicator().compute(candles, {"period": 14}),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }


__all__ = ["EmaCrossoverFamily"]
