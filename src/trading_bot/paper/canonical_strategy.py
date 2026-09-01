"""Canonical Strategy Evaluator — single source of truth for signal logic.

Used by both BacktestEngine and PaperReplayMode.
Eliminates drift between backtest evaluator and paper evaluator.

Canonical rules (from bot.py / EmaCrossoverStrategy):
- EMA fast (9) / slow (21) crossover
- RSI 14 confirmation: BUY when RSI > rsi_long_threshold, SELL when RSI < rsi_short_threshold
- ATR 14 for SL/TP
- require_crossover=True: only signal on actual cross, not sustained alignment
- SL = stop_loss_atr_multiplier * ATR
- TP = take_profit_atr_multiplier * ATR
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from trading_bot.paper.signal_types import MarketSnapshot, SignalCandidate, SignalDirection


@dataclass(frozen=True)
class CanonicalStrategyConfig:
    """Immutable configuration for the canonical strategy."""

    strategy_id: str = "TRUE_CROSS"
    version: str = "v0.3.2"
    fast_ema_period: int = 9
    slow_ema_period: int = 21
    rsi_period: int = 14
    atr_period: int = 14
    rsi_long_threshold: float = 50.0
    rsi_short_threshold: float = 50.0
    stop_loss_atr_multiplier: float = 1.5
    take_profit_atr_multiplier: float = 2.0
    require_crossover: bool = True
    crossover_window: int = 3
    timeframe: str = "5m"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "fast_ema_period": self.fast_ema_period,
            "slow_ema_period": self.slow_ema_period,
            "rsi_period": self.rsi_period,
            "atr_period": self.atr_period,
            "rsi_long_threshold": self.rsi_long_threshold,
            "rsi_short_threshold": self.rsi_short_threshold,
            "stop_loss_atr_multiplier": self.stop_loss_atr_multiplier,
            "take_profit_atr_multiplier": self.take_profit_atr_multiplier,
            "require_crossover": self.require_crossover,
            "crossover_window": self.crossover_window,
            "timeframe": self.timeframe,
        }

    def bundle_hash(self) -> str:
        """SHA-256 of canonical config. Both backtest and paper must match."""
        blob = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class _IndicatorCache:
    """Cached indicators for a bar sequence."""

    closes: list[float]
    highs: list[float]
    lows: list[float]
    ema_fast: list  # padded with None for warmup
    ema_slow: list
    rsi: list
    atr: list


class CanonicalStrategyEvaluator:
    """Single source of truth for EMA crossover + RSI signal logic.

    Produces SignalCandidate objects compatible with both backtest and paper.
    Both engines consume this evaluator to guarantee parity.
    """

    def __init__(
        self,
        alpha_id: UUID | None = None,
        config: CanonicalStrategyConfig | None = None,
    ):
        self.alpha_id = alpha_id or uuid4()
        self.config = config or CanonicalStrategyConfig()
        self._last_signal_bar: dict[str, int] = {}  # symbol -> last bar index
        self._indicator_cache: _IndicatorCache | None = None

    def __call__(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        """Evaluate all symbols in snapshot for signals.

        Returns list of SignalCandidate (may be empty).
        """
        return self.evaluate(snapshot)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        """Evaluate all symbols in snapshot for signals.

        Returns list of SignalCandidate (may be empty).
        """
        signals = []
        for symbol in snapshot.symbols:
            bars = snapshot.get_ohlcv(symbol)
            if not bars or len(bars) < self.config.slow_ema_period + self.config.crossover_window + 2:
                continue

            sig = self._evaluate_symbol(symbol, bars)
            if sig is not None:
                signals.append(sig)
        return signals

    def _evaluate_symbol(self, symbol: str, bars: list) -> SignalCandidate | None:
        """Evaluate one symbol for a signal."""
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        cfg = self.config
        ema_fast = self._ema_padded(closes, cfg.fast_ema_period)
        ema_slow = self._ema_padded(closes, cfg.slow_ema_period)
        rsi_values = self._rsi_padded(closes, cfg.rsi_period)
        atr_values = self._atr_padded(highs, lows, closes, cfg.atr_period)

        current_idx = len(bars) - 1
        if current_idx < cfg.slow_ema_period + 1:
            return None

        # Skip if already signaled on this bar
        if self._last_signal_bar.get(symbol) == current_idx:
            return None

        fast_curr = ema_fast[current_idx]
        slow_curr = ema_slow[current_idx]
        rsi_curr = rsi_values[current_idx]
        atr_curr = atr_values[current_idx]

        if None in (fast_curr, slow_curr) or atr_curr <= 0:
            return None

        if not isinstance(rsi_curr, (int, float)):
            return None

        # Crossover detection over window
        has_cross_long = False
        has_cross_short = False
        for offset in range(1, cfg.crossover_window + 1):
            prev_idx = current_idx - offset
            if prev_idx < 0:
                break
            fp = ema_fast[prev_idx]
            sp = ema_slow[prev_idx]
            if None in (fp, sp):
                continue
            if fp <= sp and fast_curr > slow_curr:
                has_cross_long = True
            if fp >= sp and fast_curr < slow_curr:
                has_cross_short = True

        source_bar = bars[current_idx - 1]
        source_bar_ts = datetime.utcfromtimestamp(source_bar.timestamp / 1000.0)
        current_close = closes[current_idx]

        # BUY: fast crosses above slow + RSI > threshold
        if fast_curr > slow_curr and rsi_curr > cfg.rsi_long_threshold:
            if not cfg.require_crossover or has_cross_long:
                stop = current_close - (atr_curr * cfg.stop_loss_atr_multiplier)
                target = current_close + (atr_curr * cfg.take_profit_atr_multiplier)
                stop_distance = current_close - stop
                if stop_distance <= 0:
                    return None

                self._last_signal_bar[symbol] = current_idx
                return SignalCandidate(
                    signal_id=uuid4(),
                    setup_id=f"TRUE_CROSS_{symbol}_{current_idx}",
                    alpha_id=self.alpha_id,
                    family="true_cross",
                    version=cfg.version,
                    symbol=symbol,
                    timeframe=cfg.timeframe,
                    direction=SignalDirection.BUY,
                    signal_timestamp=source_bar_ts,
                    source_bar_timestamp=source_bar_ts,
                    entry_reference=current_close,
                    stop=stop,
                    target=target,
                    planned_risk=25.0,
                    planned_rr=(target - current_close) / stop_distance,
                    planned_net_rr=((target - current_close) / stop_distance) * 0.975,
                )

        # SELL: fast crosses below slow + RSI < threshold
        if fast_curr < slow_curr and rsi_curr < cfg.rsi_short_threshold:
            if not cfg.require_crossover or has_cross_short:
                stop = current_close + (atr_curr * cfg.stop_loss_atr_multiplier)
                target = current_close - (atr_curr * cfg.take_profit_atr_multiplier)
                stop_distance = stop - current_close
                if stop_distance <= 0:
                    return None

                self._last_signal_bar[symbol] = current_idx
                return SignalCandidate(
                    signal_id=uuid4(),
                    setup_id=f"TRUE_CROSS_{symbol}_{current_idx}",
                    alpha_id=self.alpha_id,
                    family="true_cross",
                    version=cfg.version,
                    symbol=symbol,
                    timeframe=cfg.timeframe,
                    direction=SignalDirection.SELL,
                    signal_timestamp=source_bar_ts,
                    source_bar_timestamp=source_bar_ts,
                    entry_reference=current_close,
                    stop=stop,
                    target=target,
                    planned_risk=25.0,
                    planned_rr=(current_close - target) / stop_distance,
                    planned_net_rr=((current_close - target) / stop_distance) * 0.975,
                )

        return None

    # ── Indicator math (padded to align with bar indices) ──

    def _ema_padded(self, data: list[float], period: int) -> list:
        """EMA padded with None for warmup. Returns same length as data."""
        if len(data) < period:
            return [None] * len(data)
        sma = sum(data[:period]) / period
        result: list = [None] * (period - 1) + [sma]
        mult = 2.0 / (period + 1)
        for i in range(period, len(data)):
            result.append((data[i] - result[-1]) * mult + result[-1])
        return result

    def _rsi_padded(self, data: list[float], period: int = 14) -> list:
        """RSI padded with 50.0 for warmup bars."""
        if len(data) < period + 1:
            return [50.0] * len(data)
        deltas = [data[i] - data[i - 1] for i in range(1, len(data))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
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
        padding = len(data) - len(rsi_values)
        return [50.0] * padding + rsi_values

    def _atr_padded(self, highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list:
        """ATR padded for warmup bars."""
        if len(highs) < 2:
            return [highs[0] * 0.01] * len(highs) if highs else []
        trs = [highs[0] - lows[0]]
        for i in range(1, len(highs)):
            trs.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ))
        if len(trs) < period:
            avg = sum(trs) / len(trs)
            return [avg] * len(trs)
        first = sum(trs[:period]) / period
        atr_vals = [first]
        for i in range(period, len(trs)):
            atr_vals.append((atr_vals[-1] * (period - 1) + trs[i]) / period)
        padding = len(trs) - len(atr_vals)
        return [first] * padding + atr_vals


__all__ = [
    "CanonicalStrategyConfig",
    "CanonicalStrategyEvaluator",
]
