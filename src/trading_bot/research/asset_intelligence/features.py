"""Shared feature calculators for Asset Intelligence (RFC-AIL-004).

Pure, deterministic, point-in-time feature computation over OHLCV bars.
Every calculator consumes ONLY bars at or before the context timestamp —
callers pass a pre-sliced window; these functions never look ahead into a
full dataset.

Design rules:
- Shared logic >> duplicated logic: BTC/ETH/SOL agents reuse these exact
  calculators; asset-specific behaviour lives in the agents, not here.
- Determinism: same input bars → same features, no wall-clock, no RNG.
- Fail-soft per feature: a calculator returns None (never raises) when its
  window is too short; the AssetAgent decides whether a None mandatory
  feature fails the context build (fail closed) or degrades explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

__all__ = [
    "FEATURE_VERSIONS",
    "liquidity_proxy",
    "momentum_rsi",
    "returns",
    "trend_state",
    "volatility_atr",
    "volume_profile",
]


# Version pinning: every context records which calculator versions produced
# its features, so a historical context can be reconstructed exactly.
FEATURE_VERSIONS = {
    "returns": "returns-v1",
    "volatility_atr": "atr-v1",
    "trend": "trend-v1",
    "momentum_rsi": "rsi-v1",
    "volume_profile": "volume-v1",
    "liquidity_proxy": "liquidity-v1",
}

# Minimum history each calculator needs (mirrors EMA21/RSI14/ATR14 warmups).
MIN_BARS = {
    "returns": 2,
    "volatility_atr": 15,
    "trend_state": 22,
    "momentum_rsi": 15,
    "volume_profile": 2,
    "liquidity_proxy": 2,
}


def returns(candles: Sequence[OHLCV], lookback: int = 20) -> float | None:
    """Simple return over the last ``lookback`` closes (point-in-time)."""
    if len(candles) < max(2, lookback + 1):
        return None
    first = candles[-(lookback + 1)].close
    last = candles[-1].close
    if first <= 0:
        return None
    return (last - first) / first


def volatility_atr(candles: Sequence[OHLCV], period: int = 14) -> float | None:
    """Average True Range over ``period`` bars, normalised by last close."""
    if len(candles) < period + 1:
        return None
    trs = []
    for prev, cur in zip(candles[-(period + 1) : -1], candles[-period:], strict=False):
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    atr = sum(trs) / len(trs)
    close = candles[-1].close
    if close <= 0:
        return None
    return atr / close


def trend_state(
    candles: Sequence[OHLCV], fast: int = 9, slow: int = 21
) -> dict[str, float | str] | None:
    """EMA(fast) vs EMA(slope-adjusted slow) trend classification.

    Returns {"direction": "up"|"down"|"flat", "spread": float} where spread
    is (ema_fast - ema_slow) / ema_slow. Needs ``slow + 1`` bars.
    """
    if len(candles) < slow + 1:
        return None
    closes = [c.close for c in candles]

    def ema(period: int) -> float:
        k = 2.0 / (period + 1)
        seed = sum(closes[:period]) / period
        value = seed
        for price in closes[period:]:
            value = price * k + value * (1 - k)
        return value

    f, s = ema(fast), ema(slow)
    if s <= 0:
        return None
    spread = (f - s) / s
    direction = "up" if spread > 0.001 else ("down" if spread < -0.001 else "flat")
    return {"direction": direction, "spread": round(spread, 6)}


def momentum_rsi(candles: Sequence[OHLCV], period: int = 14) -> float | None:
    """Classic Wilder RSI on the last ``period`` deltas."""
    if len(candles) < period + 1:
        return None
    deltas = [
        b.close - a.close
        for a, b in zip(candles[-(period + 1) : -1], candles[-period:], strict=False)
    ]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 4)


def volume_profile(candles: Sequence[OHLCV], lookback: int = 20) -> dict[str, float] | None:
    """Recent volume vs its lookback average (surge ratio) + last volume."""
    if len(candles) < max(2, lookback):
        return None
    window = candles[-lookback:]
    avg = sum(c.volume for c in window) / len(window)
    last = candles[-1].volume
    if avg <= 0:
        return None
    return {"last": last, "avg": round(avg, 8), "surge": round(last / avg, 6)}


def liquidity_proxy(candles: Sequence[OHLCV], lookback: int = 20) -> dict[str, float] | None:
    """Turnover (close*volume) and median spread proxy (high-low)/close."""
    if len(candles) < max(2, lookback):
        return None
    window = candles[-lookback:]
    turnover = sum(c.close * c.volume for c in window)
    spreads = sorted((c.high - c.low) / c.close for c in window if c.close > 0)
    if not spreads:
        return None
    mid = spreads[len(spreads) // 2]
    return {"turnover": round(turnover, 4), "spread_median": round(mid, 6)}


@dataclass(frozen=True, slots=True)
class SharedFeatures:
    """Bag of shared-feature results (None = window too short)."""

    returns: float | None = None
    volatility_atr: float | None = None
    trend: dict[str, float | str] | None = None
    momentum_rsi: float | None = None
    volume: dict[str, float] | None = None
    liquidity: dict[str, float] | None = None


def compute_shared(candles: Sequence[OHLCV]) -> SharedFeatures:
    """Run every shared calculator over a pre-sliced point-in-time window."""
    return SharedFeatures(
        returns=returns(candles),
        volatility_atr=volatility_atr(candles),
        trend=trend_state(candles),
        momentum_rsi=momentum_rsi(candles),
        volume=volume_profile(candles),
        liquidity=liquidity_proxy(candles),
    )
