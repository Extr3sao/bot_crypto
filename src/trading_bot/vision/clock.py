"""clock — the instant a bar's close actually became knowable.

``Bar.ts_ms`` is a bar's **open**. Everything in this package that reads the bar's
close — the chart, the prompt, the decision — is therefore only available at

    open + timeframe + data_delay

and a decision stamped at the open is a decision that knew the future. RFC-TAP-AI-BOTS-003
found exactly that: the lane rendered the closed bar and then recorded the instant one
timeframe earlier, so a retrospective analysis looked like a live one and a real provider's
latency was measured against a clock that had already run an hour behind.

The duration is read from a table, never guessed: a wrong interval puts the decision at the
wrong instant, which is the defect, not a rounding error. An unknown timeframe raises
instead of defaulting to something plausible, and the data delay is a declared parameter of
the run (it appears in the ledger next to the timeframe) rather than an assumption baked
into the arithmetic.
"""

from __future__ import annotations

TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


class UnknownTimeframe(ValueError):
    """The bar duration is the clock; an unreadable timeframe stops the run."""


def timeframe_ms(timeframe: str) -> int:
    """Duration of one bar of ``timeframe``, in milliseconds."""

    key = str(timeframe).strip().lower()
    if key not in TIMEFRAME_MS:
        raise UnknownTimeframe(
            f"unknown timeframe {timeframe!r}: the bar duration is what makes a close "
            "knowable, so it is declared rather than guessed"
        )
    return TIMEFRAME_MS[key]


def bar_close_ms(bar_ts_ms: int, interval_ms: int) -> int:
    """When the bar that opened at ``bar_ts_ms`` closed."""

    interval = int(interval_ms)
    if interval <= 0:
        raise ValueError("interval_ms must be positive")
    return int(bar_ts_ms) + interval


def information_ms(bar_ts_ms: int, interval_ms: int, data_delay_ms: int = 0) -> int:
    """Earliest instant at which the bar's close could have reached a decision."""

    delay = int(data_delay_ms)
    if delay < 0:
        raise ValueError("data_delay_ms cannot be negative: the feed cannot deliver early")
    return bar_close_ms(bar_ts_ms, interval_ms) + delay
