"""ARP-005 ALPHA EXPANSION §5 — PIT-safe higher-timeframe (HTF) construction.

Research-only. Constructs 4h/8h/1d bars deterministically from native 1h bars by
UTC epoch bucketing. No runtime module imports this package; it cannot size,
risk-check, execute or promote anything.

PIT contract (frozen before any result):

* **UTC epoch alignment.** ``bucket = ts // tf_ms``; a bucket's bars all share
  the same UTC-aligned bucket start. There is no timezone ambiguity and no
  local-time boundary.
* **No partial bars.** A bucket is emitted only when it contains exactly
  ``tf_hours`` lower bars, the first at the exact bucket start and the last
  ``tf_hours - 1`` hours later. A partially-formed (current or gapped) bucket is
  dropped, never synthesised or forward-filled.
* **No future constituent.** Because only complete buckets are emitted, a bar's
  last constituent closes at ``close_ms = open_ms + tf_ms - 1``; the bar is never
  readable before that instant.
* **``data_time <= decision_time``.** :func:`completed_bars` returns only bars
  with ``close_ms <= decision_time``; :func:`assert_pit` raises if a caller ever
  hands back a bar that breaks that invariant.

8h is a divisor of a day (3 bars/day) and 4h likewise (6 bars/day), so daily
aggregation can be built from either; the tests exercise all three.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

__all__ = [
    "HOUR_MS",
    "HTFBar",
    "assert_pit",
    "build_htf_bars",
    "completed_bars",
    "tf_ms_for",
]

HOUR_MS = 3_600_000


def tf_ms_for(tf_hours: int) -> int:
    if tf_hours <= 0 or not isinstance(tf_hours, int):
        raise ValueError("tf_hours must be a positive integer")
    return tf_hours * HOUR_MS


@dataclass(frozen=True, slots=True)
class HTFBar:
    """A constructed higher-timeframe bar with an explicit availability instant.

    ``open_ms`` is the UTC bucket start and ``close_ms`` is the last millisecond
    of the bucket (``open_ms + tf_ms - 1``). A caller must only use the bar once
    ``decision_time >= close_ms``.
    """

    symbol: str
    tf_hours: int
    open_ms: int
    close_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_ohlcv(self) -> OHLCV:
        return OHLCV(
            symbol=self.symbol,
            timestamp=self.open_ms,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


def build_htf_bars(lower: Sequence[OHLCV], tf_hours: int) -> list[HTFBar]:
    """Construct complete HTF bars from 1h (or finer) bars by UTC epoch buckets.

    Only complete buckets are emitted (see the module PIT contract). The input is
    treated as already ordered; ordering is re-checked defensively by grouping on
    the bucket key.
    """
    tf_ms = tf_ms_for(tf_hours)
    by_bucket: dict[int, list[OHLCV]] = {}
    for b in lower:
        by_bucket.setdefault(b.timestamp // tf_ms, []).append(b)

    out: list[HTFBar] = []
    for bucket in sorted(by_bucket):
        group = sorted(by_bucket[bucket], key=lambda x: x.timestamp)
        if len(group) != tf_hours:
            continue  # partial or over-full bucket -> dropped (PIT)
        start = bucket * tf_ms
        if group[0].timestamp != start:
            continue  # bucket does not start exactly on the UTC boundary
        if group[-1].timestamp - group[0].timestamp != (tf_hours - 1) * HOUR_MS:
            continue  # interior gap -> not a contiguous complete bucket
        out.append(
            HTFBar(
                symbol=group[0].symbol,
                tf_hours=tf_hours,
                open_ms=start,
                close_ms=start + tf_ms - 1,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )
    return out


def completed_bars(bars: Iterable[HTFBar], decision_time: int) -> list[HTFBar]:
    """Return only bars fully closed at ``decision_time`` (``close_ms <= t``)."""
    return [b for b in bars if b.close_ms <= decision_time]


def assert_pit(bars: Iterable[HTFBar], decision_time: int) -> None:
    """Raise if any bar would be used before it is complete (fail closed)."""
    for b in bars:
        if b.close_ms > decision_time:
            raise ValueError(
                f"PIT violation: {b.symbol} {b.tf_hours}h bar closing at "
                f"{b.close_ms} used at decision_time {decision_time}"
            )
