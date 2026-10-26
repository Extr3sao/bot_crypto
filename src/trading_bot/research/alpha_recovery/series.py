"""Deterministic indicator helpers for the ARP-002 experiments (pure, no I/O).

``sma_series`` exists because the repository ships no simple-moving-average
indicator (verified: ``trading_bot.indicators.builtin`` offers EMA, RSI, MACD,
ATR, Bollinger, VWAP, volume-relative, spread, volatility, momentum and
order-book-imbalance only). It is a documented ``PROJECT_DERIVED`` helper, kept
local to this research package so the runtime indicator registry is untouched —
the same reason ``experimental/series.py`` gives.

Values are ``None`` until the window is complete, so a caller can never read a
partially-formed statistic.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["atr_series", "ema_series", "sma_series"]


def sma_series(values: Sequence[float], period: int) -> list[float | None]:
    """Rolling simple moving average; ``None`` until ``period`` values exist."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema_series(values: Sequence[float], period: int) -> list[float | None]:
    """Exponential moving average; ``None`` until ``period`` values exist.

    Seed = SMA of the first ``period`` values (standard, reproducible); then
    ``alpha = 2 / (period + 1)``.
    """
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * alpha + prev * (1.0 - alpha)
        out[i] = prev
    return out


def atr_series(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    """Wilder's Average True Range; ``None`` until a full ``period`` of TR exists.

    ``TR[0]`` is undefined (no previous close), so a valid ATR first appears at
    index ``period``. Seed = simple mean of ``TR[1..period]``; then Wilder
    smoothing ``atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period``.
    """
    if period <= 0:
        raise ValueError("period must be > 0")
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    seed = sum(tr[1 : period + 1]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out
