"""Point-in-time availability — information exists when the BAR CLOSES (§6).

Every slice the autonomous runtime consumes or reconstructs derives from these
three functions, so the rule is stated exactly once:

* ``infer_bar_interval_ms`` — the bar spacing, INFERRED from the bars instead
  of declared by a caller (a declared interval could silently disagree with
  the data it is applied to);
* ``availability_ms`` — the instant a single bar became observable: its close,
  i.e. ``timestamp + interval`` (``timestamp`` is the bar's OPEN);
* ``closed_bar_slice`` — the bars a decision at ``decision_time_ms`` may use:
  exactly those whose close is at or before it.

Using a bar's OPEN timestamp as its availability instant is a look-ahead bug:
the bar's price is not final until it closes.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from trading_bot.market_data.types import OHLCV

__all__ = ["availability_ms", "closed_bar_slice", "infer_bar_interval_ms"]


def infer_bar_interval_ms(bars: Sequence[OHLCV]) -> int | None:
    """Most common positive spacing between consecutive bar timestamps.

    ``None`` when the spacing cannot be established (fewer than two bars, or
    no strictly increasing pair). Callers must then fall back to a
    conservative rule and SAY SO — never assume an interval.
    """
    stamps = sorted({b.timestamp for b in bars})
    if len(stamps) < 2:
        return None
    diffs = [b - a for a, b in pairwise(stamps) if b > a]
    if not diffs:
        return None
    counts: dict[int, int] = {}
    for diff in diffs:
        counts[diff] = counts.get(diff, 0) + 1
    return max(counts, key=lambda key: (counts[key], -key))


def availability_ms(bar: OHLCV, interval_ms: int | None) -> int:
    """When ``bar`` became observable: its close.

    Without a known interval the bar's own timestamp is the only conservative
    answer available, so it is returned unchanged.
    """
    if interval_ms is None or interval_ms <= 0:
        return bar.timestamp
    return bar.timestamp + interval_ms


def closed_bar_slice(
    bars: Sequence[OHLCV],
    decision_time_ms: int,
    *,
    interval_ms: int | None = None,
) -> list[OHLCV]:
    """Bars whose CLOSE is at or before ``decision_time_ms``.

    This is the strictest PIT slice: a bar opened one millisecond before the
    decision but still forming is NOT usable, because its close (and therefore
    its price) is in the future.
    """
    interval = interval_ms if interval_ms is not None else infer_bar_interval_ms(bars)
    return [bar for bar in bars if availability_ms(bar, interval) <= decision_time_ms]
