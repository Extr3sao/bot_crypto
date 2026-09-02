"""Candle Filter — P0: Enforce completed candles only.

A 5m candle is ONLY usable when:
    bar_open_time + timeframe_duration <= current_time

This prevents the critical bug where indicators are calculated on
open candles that haven't closed yet, producing incorrect signals.

Usage:
    completed = filter_completed_candles(candles, "5m", current_time)
    last = get_last_completed_candle(candles, "5m", current_time)
"""

from __future__ import annotations

import time

import structlog

from trading_bot.market_data.timeframe import TIMEFRAME_SECONDS
from trading_bot.market_data.types import OHLCV

logger = structlog.get_logger("candle_filter")

# Umbral de detección de unidad de timestamp. ``OHLCV.timestamp`` (contrato
# canónico de ``types.py``) es **ms since epoch** (~1.78e12 hoy) y así lo
# entregan el hub multi-exchange y los fakes canónicos (``make_flat_ohlcv``).
# Los tests legacy y callers antiguos construyen velas con ``time.time()``
# (~1.78e9, **segundos**). Un timestamp > 1e11 solo puede ser ms (en s
# correspondería al año 5138); el umbral separa ambas unidades sin ambigüedad
# y permite comparar siempre en la unidad del timestamp de la vela.
_MS_EPOCH_THRESHOLD: int = 100_000_000_000  # 1e11


def _to_seconds(timestamp: int) -> float:
    """Normaliza un timestamp OHLCV a segundos según su unidad."""
    if timestamp > _MS_EPOCH_THRESHOLD:
        return timestamp / 1000.0
    return float(timestamp)


class CandleNotComplete(Exception):
    """Raised when a candle is still forming."""

    pass


class UnknownTimeframeError(Exception):
    """Raised when the timeframe is not in TIMEFRAME_SECONDS.

    V3 policy: FAIL CLOSED. We can never prove an unknown timeframe's
    candles are closed, so we refuse to use them instead of guessing.
    """


def timeframe_seconds_or_raise(timeframe: str) -> int:
    """Resolve timeframe duration in seconds or FAIL CLOSED."""
    tf_seconds = TIMEFRAME_SECONDS.get(timeframe.lower())
    if tf_seconds is None:
        raise UnknownTimeframeError(
            f"Unknown timeframe {timeframe!r}: cannot prove candles are "
            f"closed. FAIL CLOSED — refusing to use them. "
            f"Known: {sorted(TIMEFRAME_SECONDS)}"
        )
    return tf_seconds


def is_candle_complete(candle: OHLCV, timeframe: str, current_time: float | None = None) -> bool:
    """Check if a candle is completely closed.

    A candle is complete when:
        candle.timestamp + timeframe_seconds <= current_time

    Args:
        candle: The OHLCV candle to check.
        timeframe: Timeframe string (e.g. "5m", "1h").
        current_time: Current epoch time. Defaults to time.time().

    Returns:
        True if the candle is complete.
    """
    if current_time is None:
        current_time = time.time()

    # V3: FAIL CLOSED on ambiguous/unknown timeframes.
    tf_seconds = timeframe_seconds_or_raise(timeframe)

    # candle.timestamp is the bar open time, normalizado a la unidad de
    # ``current_time`` (s). REGRESIÓN P1 (bybit): el hub entrega timestamps en
    # **ms** pero ``time.time()`` está en **segundos**; comparar sin normalizar
    # (`ms + 300 <= s`) hacía que TODAS las velas se descartaran → el bot
    # nunca generaba señales → 0 trades.
    return _to_seconds(candle.timestamp) + tf_seconds <= current_time


def get_completed_candles(
    candles: list[OHLCV],
    timeframe: str,
    current_time: float | None = None,
) -> list[OHLCV]:
    """Alias canonico V3 de ``filter_completed_candles`` (P0).

    Mismo contrato: solo velas con bar_open_time + tf <= current_time.
    """
    return filter_completed_candles(candles, timeframe, current_time)


def filter_completed_candles(
    candles: list[OHLCV],
    timeframe: str,
    current_time: float | None = None,
) -> list[OHLCV]:
    """Filter out candles that are still forming.

    Returns only candles where:
        bar_open_time + timeframe_duration <= current_time

    This is the PRIMARY entry point for ensuring no open candles
    are used for signal generation.

    Args:
        candles: List of OHLCV candles.
        timeframe: Timeframe string (e.g. "5m", "1h").
        current_time: Current epoch time. Defaults to time.time().

    Returns:
        List of completed candles (may be empty or shorter).
    """
    if current_time is None:
        current_time = time.time()

    completed = [c for c in candles if is_candle_complete(c, timeframe, current_time)]

    if len(completed) < len(candles):
        logger.info(
            "candle_filter.filtered",
            timeframe=timeframe,
            total=len(candles),
            completed=len(completed),
            removed=len(candles) - len(completed),
        )

    return completed


def get_last_completed_candle(
    candles: list[OHLCV],
    timeframe: str,
    current_time: float | None = None,
) -> OHLCV | None:
    """Get the most recent completed candle.

    Args:
        candles: List of OHLCV candles (should be sorted by timestamp).
        timeframe: Timeframe string (e.g. "5m", "1h").
        current_time: Current epoch time. Defaults to time.time().

    Returns:
        The last completed candle, or None if none are complete.
    """
    completed = filter_completed_candles(candles, timeframe, current_time)
    if not completed:
        return None
    return completed[-1]


def validate_candles_not_empty(
    candles: list[OHLCV],
    timeframe: str,
    min_count: int = 3,
    current_time: float | None = None,
) -> list[OHLCV]:
    """Filter completed candles and ensure minimum count.

    This is the recommended entry point for the trading loop:
    1. Filter out open candles
    2. Ensure enough completed candles remain for indicators

    Raises ValueError if not enough completed candles.
    """
    completed = filter_completed_candles(candles, timeframe, current_time)

    if len(completed) < min_count:
        raise ValueError(
            f"Not enough completed candles for {timeframe}: got {len(completed)}, need {min_count}"
        )

    return completed


__all__ = [
    "CandleNotComplete",
    "UnknownTimeframeError",
    "filter_completed_candles",
    "get_completed_candles",
    "get_last_completed_candle",
    "is_candle_complete",
    "timeframe_seconds_or_raise",
    "validate_candles_not_empty",
]
