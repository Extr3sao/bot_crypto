"""EMA Crossover Strategy — first candidate for Fase 4.

Classic dual-EMA crossover with RSI confirmation:
- BUY when fast EMA crosses above slow EMA + RSI > 50
- SELL when fast EMA crosses below slow EMA + RSI < 50

Parameters configurable via StrategyConfig.entry_rules / exit_rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from .types import Signal, StrategyConfig


class EmaCrossoverStrategy:
    """Dual EMA crossover with RSI confirmation.

    Entry:
        - fast_ema > slow_ema (for LONG)
        - fast_ema < slow_ema (for SHORT)
        - RSI confirms direction

    Exit:
        - stop_loss_atr_multiplier * ATR
        - take_profit_atr_multiplier * ATR
    """

    strategy_name = "ema_crossover"

    def evaluate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        config: StrategyConfig,
    ) -> Signal | None:
        if len(candles) < 3:
            return None

        fast_ema = indicators.get("ema_fast")
        slow_ema = indicators.get("ema_slow")
        rsi = indicators.get("rsi")
        atr = indicators.get("atr")

        if not all(isinstance(v, (int, float)) for v in [fast_ema, slow_ema, rsi, atr]):
            return None

        assert isinstance(fast_ema, (int, float))
        assert isinstance(slow_ema, (int, float))
        assert isinstance(rsi, (int, float))
        assert isinstance(atr, (int, float))

        if atr <= 0:
            return None

        current_price = candles[-1].close
        symbol = candles[-1].symbol

        # Get thresholds from config
        rsi_long_threshold = config.entry_rules.get("rsi_long_threshold", 50.0)
        rsi_short_threshold = config.entry_rules.get("rsi_short_threshold", 50.0)
        sl_mult = config.exit_rules.get("stop_loss_atr_multiplier", 1.5)
        tp_mult = config.exit_rules.get("take_profit_atr_multiplier", 2.0)

        # Compute SL/TP prices for the explanation
        sl_price = current_price - (atr * sl_mult)
        tp_price = current_price + (atr * tp_mult)

        # EMA history for crossover detection (relaxed: check last N bars).
        # Contract: producers of "*_history" indicator keys always supply
        # lists of per-bar values (see EmaCrossoverFamily/scanner wiring); a
        # scalar IndicatorResult for these keys is never produced. The cast is
        # annotation-only and preserves the exact runtime fallback of
        # ``.get(key, [])``.
        ema_fast_history = cast(list[Any], indicators.get("ema_fast_history", []))
        ema_slow_history = cast(list[Any], indicators.get("ema_slow_history", []))
        crossover_window = indicators.get("crossover_window", 3)

        def _had_cross(
            window_fast: list[Any], window_slow: list[Any], direction: str
        ) -> bool:
            """Check if a crossover happened within the window of last N bars.

            LONG cross: any bar where prev_fast <= prev_slow AND current fast > slow
            SHORT cross: any bar where prev_fast >= prev_slow AND current fast < slow
            """
            n = min(len(window_fast), len(window_slow))
            for i in range(n):
                ef = window_fast[i]
                es = window_slow[i]
                if ef is None or es is None:
                    continue
                if not (isinstance(ef, (int, float)) and isinstance(es, (int, float))):
                    continue
                if direction == "long" and ef <= es:
                    return True
                if direction == "short" and ef >= es:
                    return True
            return False

        has_history = len(ema_fast_history) > 0

        # RSI zone classification
        def rsi_zone(val: float) -> str:
            if val >= 70:
                return "sobrecomprado"
            elif val >= 60:
                return "alcista fuerte"
            elif val >= 50:
                return "alcista"
            elif val >= 40:
                return "bajista"
            elif val >= 30:
                return "bajista fuerte"
            return "sobrevendido"

        # EMA alignment description
        ema_spread = fast_ema - slow_ema
        ema_spread_pct = (ema_spread / current_price * 100) if current_price > 0 else 0

        # Candle context
        last_candle = candles[-1]
        candle_body = last_candle.close - last_candle.open
        candle_range = last_candle.high - last_candle.low
        body_pct = (abs(candle_body) / candle_range * 100) if candle_range > 0 else 0
        candle_direction = "alcista" if candle_body > 0 else "bajista" if candle_body < 0 else "neutra"

        # Volume context
        recent_volumes = [c.volume for c in candles[-20:]] if len(candles) >= 20 else [c.volume for c in candles]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
        volume_ratio = (last_candle.volume / avg_volume) if avg_volume > 0 else 1.0

        # Check crossover filter: require_crossover in entry_rules
        require_crossover = config.entry_rules.get("require_crossover", False)

        # LONG signal
        long_state = fast_ema > slow_ema and rsi > rsi_long_threshold
        long_cross = (
            has_history
            and fast_ema > slow_ema
            and _had_cross(ema_fast_history, ema_slow_history, "long")
        )
        if long_state and (not require_crossover or long_cross):
            confidence = min(1.0, (rsi - rsi_long_threshold) / 50.0 + 0.5)
            sl_pct = (atr * sl_mult / current_price) * 100.0 if current_price > 0 else 0
            tp_pct = (atr * tp_mult / current_price) * 100.0 if current_price > 0 else 0

            # Build decision explanation
            explanation_parts = [
                f"CRUCE ALCISTA: EMA rápida ({fast_ema:.2f}) cruza por encima de EMA lenta ({slow_ema:.2f})",
                f"  - Separacion: {ema_spread:.2f} ({ema_spread_pct:.3f}%)",
            ]
            if has_history and ema_fast_history and ema_slow_history:
                pf = ema_fast_history[0]
                ps = ema_slow_history[0]
                if pf is not None and ps is not None and isinstance(pf, (int, float)) and isinstance(ps, (int, float)):
                    explanation_parts.append(
                        f"  - Antes (1 bar): EMA rapida ({pf:.2f}) {'>' if pf > ps else '<'} EMA lenta ({ps:.2f})"
                    )
            explanation_parts.extend([
                f"VENTANA: {crossover_window} bars para detectar cruce",
                f"CONFIRMACIÓN RSI: {rsi:.1f} > umbral {rsi_long_threshold:.0f} ({rsi_zone(rsi)})",
                f"VOLATILIDAD ATR: {atr:.2f} ({atr/current_price*100:.3f}% del precio)",
                f"STOP LOSS: ${sl_price:.2f} (-{sl_pct:.2f}% = {sl_mult}xATR)",
                f"TAKE PROFIT: ${tp_price:.2f} (+{tp_pct:.2f}% = {tp_mult}xATR)",
                f"RELACIÓN RIESGO/BENEFICIO: 1:{tp_mult/sl_mult:.1f}",
                f"CONTEXTO VELA: {candle_direction} (cuerpo {body_pct:.0f}% del rango)",
                f"VOLUMEN: ratio {volume_ratio:.2f}xvs-media (media={avg_volume:.0f})",
                f"CONFIANZA: {confidence:.1%}",
            ])

            return Signal(
                symbol=symbol,
                side="buy",
                strategy_name=self.strategy_name,
                timeframe=config.timeframes[0] if config.timeframes else "5m",
                confidence=confidence,
                price=current_price,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                metadata={
                    "fast_ema": fast_ema,
                    "slow_ema": slow_ema,
                    "rsi": rsi,
                    "atr": atr,
                    "ema_spread": ema_spread,
                    "ema_spread_pct": ema_spread_pct,
                    "rsi_zone": rsi_zone(rsi),
                    "sl_price": sl_price,
                    "tp_price": tp_price,
                    "sl_mult": sl_mult,
                    "tp_mult": tp_mult,
                    "risk_reward_ratio": tp_mult / sl_mult if sl_mult > 0 else 0,
                    "candle_direction": candle_direction,
                    "candle_body_pct": body_pct,
                    "volume_ratio": volume_ratio,
                    "avg_volume": avg_volume,
                    "explanation": "\n".join(explanation_parts),
                    "entry_reason": f"EMA crossover alcista + RSI {rsi:.1f}",
                },
            )

        # SHORT signal
        short_state = fast_ema < slow_ema and rsi < rsi_short_threshold
        short_cross = (
            has_history
            and fast_ema < slow_ema
            and _had_cross(ema_fast_history, ema_slow_history, "short")
        )
        if short_state and (not require_crossover or short_cross):
            confidence = min(1.0, (rsi_short_threshold - rsi) / 50.0 + 0.5)
            sl_pct = (atr * sl_mult / current_price) * 100.0 if current_price > 0 else 0
            tp_pct = (atr * tp_mult / current_price) * 100.0 if current_price > 0 else 0

            # SHORT: SL is above, TP is below
            sl_price_short = current_price + (atr * sl_mult)
            tp_price_short = current_price - (atr * tp_mult)

            explanation_parts = [
                f"CRUCE BAJISTA: EMA rápida ({fast_ema:.2f}) cruza por debajo de EMA lenta ({slow_ema:.2f})",
                f"  - Separacion: {ema_spread:.2f} ({ema_spread_pct:.3f}%)",
            ]
            if has_history and ema_fast_history and ema_slow_history:
                pf = ema_fast_history[0]
                ps = ema_slow_history[0]
                if pf is not None and ps is not None and isinstance(pf, (int, float)) and isinstance(ps, (int, float)):
                    explanation_parts.append(
                        f"  - Antes (1 bar): EMA rapida ({pf:.2f}) {'>' if pf > ps else '<'} EMA lenta ({ps:.2f})"
                    )
            explanation_parts.extend([
                f"VENTANA: {crossover_window} bars para detectar cruce",
                f"CONFIRMACIÓN RSI: {rsi:.1f} < umbral {rsi_short_threshold:.0f} ({rsi_zone(rsi)})",
                f"VOLATILIDAD ATR: {atr:.2f} ({atr/current_price*100:.3f}% del precio)",
                f"STOP LOSS: ${sl_price_short:.2f} (+{sl_pct:.2f}% = {sl_mult}xATR)",
                f"TAKE PROFIT: ${tp_price_short:.2f} (-{tp_pct:.2f}% = {tp_mult}xATR)",
                f"RELACIÓN RIESGO/BENEFICIO: 1:{tp_mult/sl_mult:.1f}",
                f"CONTEXTO VELA: {candle_direction} (cuerpo {body_pct:.0f}% del rango)",
                f"VOLUMEN: ratio {volume_ratio:.2f}xvs-media (media={avg_volume:.0f})",
                f"CONFIANZA: {confidence:.1%}",
            ])

            return Signal(
                symbol=symbol,
                side="sell",
                strategy_name=self.strategy_name,
                timeframe=config.timeframes[0] if config.timeframes else "5m",
                confidence=confidence,
                price=current_price,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                metadata={
                    "fast_ema": fast_ema,
                    "slow_ema": slow_ema,
                    "rsi": rsi,
                    "atr": atr,
                    "ema_spread": ema_spread,
                    "ema_spread_pct": ema_spread_pct,
                    "rsi_zone": rsi_zone(rsi),
                    "sl_price": sl_price_short,
                    "tp_price": tp_price_short,
                    "sl_mult": sl_mult,
                    "tp_mult": tp_mult,
                    "risk_reward_ratio": tp_mult / sl_mult if sl_mult > 0 else 0,
                    "candle_direction": candle_direction,
                    "candle_body_pct": body_pct,
                    "volume_ratio": volume_ratio,
                    "avg_volume": avg_volume,
                    "explanation": "\n".join(explanation_parts),
                    "entry_reason": f"EMA crossover bajista + RSI {rsi:.1f}",
                },
            )

        return None


__all__ = ["EmaCrossoverStrategy"]
