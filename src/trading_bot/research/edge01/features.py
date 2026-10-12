"""EDGE-01 causal features — every value is a function of CLOSED past bars only.

The rule the whole lane rests on: a feature read at index ``i`` (the newest
closed bar, whose close time is the decision time) may use bars ``<= i`` and
nothing else. Three consequences are encoded explicitly rather than left to
convention:

* **resistance excludes the evaluated bar** — ``max(high[i-n:i])``, so a bar can
  never be compared against a level it helped create;
* **a swing/pivot is only known once its right-hand window has closed** — a
  pivot at ``j`` with ``k`` bars on each side becomes observable at ``j + k``;
  ``confirmed_swings`` therefore returns only pivots whose confirmation is
  complete by ``i``, which is exactly the anti-look-ahead rule the external
  reference (SRC-SMC-001) fails to satisfy at the pivot instant;
* **a fair value gap exists from the close of its third bar** — ``high[i-2] <
  low[i]`` is knowable at the close of ``i``; it is NOT knowable at ``i-1``
  (the middle bar), so no decision may cite it earlier.

Every helper returns ``None`` when the history is not yet sufficient: "not
enough data" is never silently treated as a signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data import OHLCVBar

__all__ = [
    "FVG",
    "SWING_K",
    "FeatureSeries",
    "atr",
    "build_feature_series",
    "confirmed_swings",
    "ema",
    "fvg_bullish_at",
    "last_closed_index",
    "prior_extreme",
    "swing_points",
    "trend_label",
]


#: Bars on each side of a pivot. Confirmation needs ``K`` closed bars to the right.
SWING_K = 3


@dataclass(frozen=True, slots=True)
class FVG:
    """A confirmed bullish three-bar imbalance, plus where it came from."""

    bottom: float
    top: float
    formed_index: int

    def midpoint(self) -> float:
        return (self.bottom + self.top) / 2.0

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


def prior_extreme(bars: list[OHLCVBar], i: int, lookback: int, *, want_high: bool) -> float | None:
    """Extreme of the ``lookback`` bars BEFORE ``i`` — the evaluated bar is excluded.

    Returns ``None`` when there are not enough prior bars, so a breakout can
    never be measured against a level built from fewer bars than declared.
    """
    if i - lookback < 0:
        return None
    window = bars[i - lookback : i]
    if len(window) < lookback:
        return None
    return max(b.high for b in window) if want_high else min(b.low for b in window)


def atr(bars: list[OHLCVBar], i: int, period: int = 14) -> float | None:
    """Mean true range over the last ``period`` closed bars ending at ``i``.

    The mean is a plain average of true ranges (not Wilder smoothing) because
    that is the convention the runtime's existing families use; the exact
    definition is named in the report so a reader can compare.
    """
    if i < period:
        return None
    total = 0.0
    for j in range(i - period + 1, i + 1):
        prev_close = bars[j - 1].close
        true_range = max(
            bars[j].high - bars[j].low,
            abs(bars[j].high - prev_close),
            abs(bars[j].low - prev_close),
        )
        total += true_range
    return total / period


def ema(values: list[float], period: int) -> list[float | None]:
    """EMA seeded by the simple mean of the first ``period`` values.

    ``None`` until the seed exists, so a caller cannot read an EMA that was
    computed from fewer bars than its period.
    """
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1.0)
    prev = seed
    for idx in range(period, len(values)):
        prev = values[idx] * k + prev * (1 - k)
        out[idx] = prev
    return out


def confirmed_swings(
    bars: list[OHLCVBar], i: int, *, k: int = SWING_K, want_high: bool = True
) -> list[int]:
    """Indices of pivots that a decision at ``i`` could already know about.

    A pivot at ``j`` needs ``k`` bars on each side; only ``j + k <= i`` qualifies,
    so the current bar and its ``k-1`` predecessors can never be reported as
    confirmed structure.
    """
    out: list[int] = []
    for j in range(k, i - k + 1):
        window = bars[j - k : j + k + 1]
        if len(window) != 2 * k + 1:
            continue
        value = bars[j].high if want_high else bars[j].low
        extreme = (
            max(b.high for b in window) if want_high else min(b.low for b in window)
        )
        if value == extreme:
            out.append(j)
    return out


def fvg_bullish_at(bars: list[OHLCVBar], i: int) -> FVG | None:
    """The bullish imbalance confirmed by the close of bar ``i``, if any.

    ``high[i-2] < low[i]``: the gap is a fact about three CLOSED bars, and it
    becomes knowable at the close of the third one — at ``i``, never at ``i-1``.
    """
    if i < 2:
        return None
    bottom = bars[i - 2].high
    top = bars[i].low
    if bottom >= top:
        return None
    return FVG(bottom=bottom, top=top, formed_index=i)


def swing_points(bars: list[OHLCVBar], k: int = SWING_K, *, want_high: bool = True) -> list[tuple[int, float]]:
    """Every pivot in the series with the bar that confirms it.

    The pivot at ``j`` is confirmable from ``j + k``; a caller reading at ``i``
    must still filter ``j <= i - k``. Precomputing the whole series is therefore
    safe as long as that filter is applied — which ``FeatureSeries`` does.
    """
    out: list[tuple[int, float]] = []
    for j in range(k, len(bars) - k):
        window = bars[j - k : j + k + 1]
        if len(window) != 2 * k + 1:
            continue
        value = bars[j].high if want_high else bars[j].low
        extreme = max(b.high for b in window) if want_high else min(b.low for b in window)
        if value == extreme:
            out.append((j, value))
    return out


@dataclass(frozen=True, slots=True)
class FeatureSeries:
    """Precomputed features, one entry per bar, all built from closed bars only.

    This is a cache of the pure helpers, nothing more: every element is produced
    by calling ``atr`` / ``prior_extreme`` / ``fvg_bullish_at`` / ``swing_points``
    over the SAME bar list, so a value read here is what the pure function would
    have returned at that index. ``tests/unit/research/test_edge01_pit.py``
    re-derives the arrays bar by bar on truncated series to prove it.
    """

    atr: tuple[float | None, ...]
    resistance: tuple[float | None, ...]
    support: tuple[float | None, ...]
    volume_avg: tuple[float | None, ...]
    fvg: tuple[FVG | None, ...]
    swing_highs: tuple[tuple[int, float], ...]
    swing_k: int = SWING_K

    def confirmed_swings_before(self, i: int, limit: int | None = None) -> list[tuple[int, float]]:
        """Confirmed pivots at ``i``, oldest first (newest last).

        Only pivots whose confirmation window closed by ``i`` are returned: a
        pivot at ``j`` needs ``j + swing_k <= i``. ``limit`` keeps the newest
        ``limit`` entries; the default scans the whole series so the search for a
        target never depends on a cost cap.
        """
        horizon = i - self.swing_k
        out = [p for p in self.swing_highs if p[0] <= horizon]
        return out if limit is None else out[-limit:]


def build_feature_series(
    bars: list[OHLCVBar],
    *,
    lookback: int,
    atr_period: int,
    volume_lookback: int,
    with_swings: bool = False,
    swing_k: int = SWING_K,
) -> FeatureSeries:
    """Build the per-bar feature cache by calling the pure helpers once per bar."""
    n = len(bars)
    atrs: list[float | None] = []
    resistances: list[float | None] = []
    supports: list[float | None] = []
    volumes: list[float | None] = []
    fvgs: list[FVG | None] = []
    for i in range(n):
        atrs.append(atr(bars, i, atr_period))
        resistances.append(prior_extreme(bars, i, lookback, want_high=True))
        supports.append(prior_extreme(bars, i, lookback, want_high=False))
        if i - volume_lookback >= 0:
            window = bars[i - volume_lookback : i]
            volumes.append(sum(b.volume for b in window) / len(window))
        else:
            volumes.append(None)
        fvgs.append(fvg_bullish_at(bars, i))
    swings = swing_points(bars, swing_k) if with_swings else []
    return FeatureSeries(
        atr=tuple(atrs),
        resistance=tuple(resistances),
        support=tuple(supports),
        volume_avg=tuple(volumes),
        fvg=tuple(fvgs),
        swing_highs=tuple(swings),
        swing_k=swing_k,
    )


def last_closed_index(context_bars: list[OHLCVBar], decision_ts: int, *, span_ms: int = 0) -> int:
    """Index of the newest context bar that has fully CLOSED at ``decision_ts``.

    ``decision_ts`` is the close time of the signal bar and ``span_ms`` is the
    duration of the context bar itself: a bar whose ``ts`` is its OPEN time closes
    at ``ts + span_ms``, so it only becomes readable from that instant on. Reading
    it at ``ts`` would look up to one context bar into the future (DEF-EDGE01-06),
    which is why ``span_ms`` is a required-in-practice argument at the call site
    rather than a convention. -1 means nothing has closed yet.
    """
    lo, hi = 0, len(context_bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if context_bars[mid].ts + span_ms <= decision_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def trend_label(ema_fast: float | None, ema_slow: float | None) -> str:
    """Coarse regime label used for reporting, never for entry by itself.

    ``EMA50 > EMA200`` is UP, the reverse is DOWN, and anything else (including
    a warm-up ``None``) is treated as UNKNOWN so it cannot be reported as a
    regime that was never measured.
    """
    if ema_fast is None or ema_slow is None:
        return "UNKNOWN"
    if ema_fast > ema_slow:
        return "UP"
    if ema_fast < ema_slow:
        return "DOWN"
    return "RANGE"
