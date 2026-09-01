"""Real strategy evaluator for V0.3.1 certification.

Generates actual tradeable signals using EMA crossover + RSI filter.
References already-closed bars for signal timestamps (closed-bar compliance).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import List
from uuid import UUID, uuid4

from trading_bot.paper.signal_types import SignalCandidate, SignalDirection, MarketSnapshot


class TrueCrossEvaluator:
    """EMA21/EMA50 crossover with RSI14 filter.
    
    Generates BUY when fast EMA crosses above slow EMA and RSI < 70.
    Generates SELL when fast EMA crosses below slow EMA and RSI > 30.
    """

    def __init__(
        self,
        alpha_id: UUID,
        fast_period: int = 21,
        slow_period: int = 50,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 3.0,
    ):
        self.alpha_id = alpha_id
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self._last_signal_bar: dict[str, int] = {}  # symbol -> last bar index

    def __call__(self, snapshot: MarketSnapshot) -> List[SignalCandidate]:
        """Evaluate snapshot for signals."""
        signals = []
        for symbol in snapshot.symbols:
            bars = snapshot.get_ohlcv(symbol)
            if not bars or len(bars) < self.slow_period + 5:
                continue

            closes = [b.close for b in bars]
            highs = [b.high for b in bars]
            lows = [b.low for b in bars]

            # Calculate indicators — padded to align with bar indices
            ema_fast_padded = self._ema_padded(closes, self.fast_period)
            ema_slow_padded = self._ema_padded(closes, self.slow_period)
            rsi_padded = self._rsi_padded(closes, self.rsi_period)
            atr_padded = self._atr_padded(highs, lows, closes, self.atr_period)

            current_idx = len(bars) - 1
            prev_idx = current_idx - 1

            if prev_idx < self.slow_period:
                continue  # Not enough history

            # Skip if we already signaled on this bar
            if self._last_signal_bar.get(symbol) == current_idx:
                continue

            current_close = closes[current_idx]
            current_rsi = rsi_padded[current_idx]
            current_atr = atr_padded[current_idx]

            if current_atr <= 0:
                continue

            fast_curr = ema_fast_padded[current_idx]
            fast_prev = ema_fast_padded[prev_idx]
            slow_curr = ema_slow_padded[current_idx]
            slow_prev = ema_slow_padded[prev_idx]

            # Skip if any EMA is None (not yet warm)
            if None in (fast_curr, fast_prev, slow_curr, slow_prev):
                continue

            # BUY: fast crosses above slow
            if fast_prev <= slow_prev and fast_curr > slow_curr:
                source_bar = bars[prev_idx]
                source_bar_ts = datetime.utcfromtimestamp(source_bar.timestamp / 1000.0)

                entry = current_close
                stop = entry - (current_atr * self.atr_sl_mult)
                target = entry + (current_atr * self.atr_tp_mult)
                stop_distance = entry - stop
                if stop_distance <= 0:
                    continue

                signals.append(SignalCandidate(
                    signal_id=uuid4(),
                    setup_id=f"ema_cross_buy_{symbol}_{current_idx}",
                    alpha_id=self.alpha_id,
                    family="true_cross",
                    version="v031",
                    symbol=symbol,
                    timeframe="5m",
                    direction=SignalDirection.BUY,
                    signal_timestamp=source_bar_ts,
                    source_bar_timestamp=source_bar_ts,
                    entry_reference=entry,
                    stop=stop,
                    target=target,
                    planned_risk=25.0,
                    planned_rr=(target - entry) / stop_distance,
                    planned_net_rr=((target - entry) / stop_distance) * 0.95,
                ))
                self._last_signal_bar[symbol] = current_idx

            # SELL: fast crosses below slow
            elif fast_prev >= slow_prev and fast_curr < slow_curr:
                source_bar = bars[prev_idx]
                source_bar_ts = datetime.utcfromtimestamp(source_bar.timestamp / 1000.0)

                entry = current_close
                stop = entry + (current_atr * self.atr_sl_mult)
                target = entry - (current_atr * self.atr_tp_mult)
                stop_distance = stop - entry
                if stop_distance <= 0:
                    continue

                signals.append(SignalCandidate(
                    signal_id=uuid4(),
                    setup_id=f"ema_cross_sell_{symbol}_{current_idx}",
                    alpha_id=self.alpha_id,
                    family="true_cross",
                    version="v031",
                    symbol=symbol,
                    timeframe="5m",
                    direction=SignalDirection.SELL,
                    signal_timestamp=source_bar_ts,
                    source_bar_timestamp=source_bar_ts,
                    entry_reference=entry,
                    stop=stop,
                    target=target,
                    planned_risk=25.0,
                    planned_rr=(entry - target) / stop_distance,
                    planned_net_rr=((entry - target) / stop_distance) * 0.95,
                ))
                self._last_signal_bar[symbol] = current_idx

        return signals

    def _ema_padded(self, data: list[float], period: int) -> list:
        """EMA padded with None to align with bar indices.
        
        Returns list of same length as data.
        First (period-1) elements are None (warmup).
        Element at index i = EMA through bar i.
        """
        if len(data) < period:
            return [None] * len(data)

        # SMA as seed
        sma = sum(data[:period]) / period
        result: list = [None] * (period - 1) + [sma]

        multiplier = 2.0 / (period + 1)
        for i in range(period, len(data)):
            result.append((data[i] - result[-1]) * multiplier + result[-1])

        return result

    def _rsi_padded(self, data: list[float], period: int = 14) -> list:
        """RSI padded with 50.0 for warmup bars."""
        if len(data) < period + 1:
            return [50.0] * len(data)

        deltas = [data[i] - data[i - 1] for i in range(1, len(data))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rsi_values = []
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

        # Pad: deltas starts at index 1 of data, RSI starts at period of deltas
        # So RSI[0] corresponds to deltas[period-1] → data[period]
        # Pad from data[0] to data[period]: that's period+1 values
        padding = len(data) - len(rsi_values)
        return [50.0] * padding + rsi_values

    def _atr_padded(self, highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list:
        """ATR padded with default for warmup bars."""
        if len(highs) < 2:
            return [highs[0] * 0.01] * len(highs) if highs else []

        true_ranges = [highs[0] - lows[0]]
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            default = sum(true_ranges) / len(true_ranges)
            return [default] * len(true_ranges)

        first_atr = sum(true_ranges[:period]) / period
        atr_values = [first_atr]
        for i in range(period, len(true_ranges)):
            atr_values.append((atr_values[-1] * (period - 1) + true_ranges[i]) / period)

        # Pad: ATR[0] = first_atr, corresponds to true_ranges[period-1]
        # true_ranges[i] corresponds to highs[i], lows[i]
        # So ATR[0] corresponds to bar index period-1
        padding = len(true_ranges) - len(atr_values)
        return [first_atr] * padding + atr_values
