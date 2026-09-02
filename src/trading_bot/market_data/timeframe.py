"""TimeframeContract — validates that candle timeframe matches strategy declaration.

Fase 4: A strategy configured for 5m MUST only receive 5m candles.
If it receives 1m candles, raise TimeframeMismatch and DO NOT trade.

This prevents the critical bug where indicators are calculated on 1m data
but signals are labeled as 5m, producing incorrect signals.
"""

from __future__ import annotations

from trading_bot.market_data.types import OHLCV


class TimeframeMismatch(Exception):
    """Raised when candle timeframe doesn't match the strategy's declared timeframe."""

    def __init__(
        self,
        symbol: str,
        expected: str,
        actual: str,
        message: str = "",
    ) -> None:
        self.symbol = symbol
        self.expected = expected
        self.actual = actual
        detail = message or (
            f"Timeframe mismatch for {symbol}: strategy expects {expected}, received {actual}"
        )
        super().__init__(detail)


# Timeframe durations in seconds (for resampling validation)
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def infer_timeframe_from_candles(candles: list[OHLCV]) -> str | None:
    """Infer the timeframe from candle timestamps.

    Uses the median interval between consecutive candle timestamps
    to determine the actual timeframe.

    Returns None if there are fewer than 2 candles.
    """
    if len(candles) < 2:
        return None

    intervals: list[int] = []
    for i in range(1, len(candles)):
        delta = candles[i].timestamp - candles[i - 1].timestamp
        intervals.append(delta)

    if not intervals:
        return None

    # Use median for robustness against gaps
    intervals.sort()
    median_interval = intervals[len(intervals) // 2]

    # Normaliza la unidad del intervalo a segundos: ``OHLCV.timestamp`` es ms
    # (contrato canónico types.py; hub/fakes entregan ms) pero
    # ``TIMEFRAME_SECONDS`` está en segundos y los tests legacy construyen
    # velas con ``time.time()`` (s). Delta de velas 5m en ms = 300000; en s =
    # 300. Un delta > 1e5 solo puede ser ms (300 s como ms sería 1970-01-01).
    if median_interval > 100_000:
        median_interval = median_interval // 1000

    # Find closest matching timeframe
    best_match: str | None = None
    best_diff = float("inf")
    for tf, seconds in TIMEFRAME_SECONDS.items():
        diff = abs(median_interval - seconds)
        if diff < best_diff:
            best_diff = diff
            best_match = tf

    # Allow tolerance: within 30% of expected duration
    if best_match is not None:
        expected_seconds = TIMEFRAME_SECONDS[best_match]
        if best_diff > expected_seconds * 0.3:
            return None  # Can't reliably determine

    return best_match


def validate_timeframe(
    candles: list[OHLCV],
    expected_timeframe: str,
    symbol: str = "",
    *,
    strict: bool = True,
) -> str | None:
    """Validate that candles match the expected timeframe.

    Args:
        candles: The OHLCV candles to validate.
        expected_timeframe: The strategy's declared timeframe (e.g. "5m").
        symbol: Symbol for error messages.
        strict: If True, raise TimeframeMismatch on mismatch.
                 If False, return the inferred timeframe without raising.

    Returns:
        The inferred timeframe if validation passes.

    Raises:
        TimeframeMismatch: If strict=True and timeframe doesn't match.
    """
    inferred = infer_timeframe_from_candles(candles)
    if inferred is None:
        return None  # Can't determine, don't block

    if inferred != expected_timeframe:
        if strict:
            raise TimeframeMismatch(
                symbol=symbol,
                expected=expected_timeframe,
                actual=inferred,
            )
        return inferred

    return inferred
