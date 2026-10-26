"""Deterministic, PIT-safe rules for EXP-ARP-001/002/003/005 (tracked, research-only).

SOURCE-FAITHFULNESS (§6-§9) — verified against the candidate specs, reported honestly:

* **EXP-ARP-001 / STRAT-CAND-001**: the source *is* resolvable enough for a
  source-faithful arm — ``STRAT-CAND-001_ma20_40_pullback_trend.md`` states ordered
  ``SMA20>SMA40>SMA200``, first pullback to ``SMA20``, entry on the break of the
  pullback candle, stop below the pullback candle low, and **exit on the ``SMA40``
  break**. The chapter's take-profit is ``UNSPECIFIED_BY_SOURCE``, so the
  "measured-move target" from the ARP-001 SPEC is exposed as an explicit
  ``PROJECT_DERIVED_VARIANT`` arm, never as the source rule.
* **EXP-ARP-002 / STRAT-CAND-016**, **EXP-ARP-003 / STRAT-CAND-012**,
  **EXP-ARP-005 / STRAT-CAND-019**: each spec declares
  ``SOURCE_FAITHFUL_EXPERIMENT = FALSE`` and lists the missing rules (boundaries,
  divergence window, entry timing, stop, target, "first contact"). Every deterministic
  parameter below is therefore labelled ``PROJECT_DERIVED_VARIANT`` and can be
  compared economically, but **no result may be attributed to the source**.

All rules read only closed bars: a setup produced by ``entry(i)`` uses bars
``<= i`` and is executed at ``close[i]``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

from .series import atr_series, sma_series
from .simulate import Position, Setup

__all__ = [
    "EXP001_CONFIG",
    "EXP002_CONFIG",
    "EXP003_CONFIG",
    "EXP005_CONFIG",
    "Exp001Config",
    "Exp001PullbackContinuation",
    "Exp002Config",
    "Exp002VoidRetest",
    "Exp003Config",
    "Exp003RelativeStrength",
    "Exp005Config",
    "Exp005PivotFade",
]

_DAY_MS = 86_400_000


def _day_key(ts_ms: int) -> int:
    return ts_ms // _DAY_MS


# ===================================================================== EXP-ARP-001


@dataclass(frozen=True, slots=True)
class Exp001Config:
    """SOURCE_THRESHOLDS (MA20/40/200) + one frozen PROJECT_DERIVED bound."""

    fast: int = 20
    mid: int = 40
    slow: int = 200
    #: PROJECT_DERIVED_VARIANT: source does not bound how old the ordered cross may
    #: be for its pullback to still count as "the first".
    cross_lookback: int = 60
    #: "source" = SMA40-break exit (source-faithful); "measured_move" = the
    #: PROJECT_DERIVED target named by the ARP-001 SPEC (source TP is UNSPECIFIED).
    variant: str = "source"


EXP001_CONFIG = Exp001Config()


class Exp001PullbackContinuation:
    """MA20/40/200 pullback continuation. See module docstring for provenance."""

    def __init__(self, config: Exp001Config | None = None) -> None:
        self.config = config or EXP001_CONFIG
        self.warmup = self.config.slow + 1
        self._bars: Sequence[OHLCV] = ()
        self._fast: list[float | None] = []
        self._mid: list[float | None] = []
        self._slow: list[float | None] = []

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        closes = [b.close for b in bars]
        self._fast = sma_series(closes, self.config.fast)
        self._mid = sma_series(closes, self.config.mid)
        self._slow = sma_series(closes, self.config.slow)

    def _cross_index(self, t: int, up: bool) -> int | None:
        f, m = self._fast, self._mid
        for c in range(t, 0, -1):
            f0, m0, f1, m1 = f[c - 1], m[c - 1], f[c], m[c]
            if f0 is None or m0 is None or f1 is None or m1 is None:
                continue
            if up and f0 <= m0 and f1 > m1:
                return c
            if not up and f0 >= m0 and f1 < m1:
                return c
        return None

    def _first_pullback(self, start: int, t: int, long_side: bool) -> int | None:
        for p in range(start + 1, t):
            fp = self._fast[p]
            if fp is None:
                continue
            if long_side and self._bars[p].low <= fp:
                return p
            if not long_side and self._bars[p].high >= fp:
                return p
        return None

    def entry(self, i: int) -> Setup | None:
        cfg = self.config
        f_t, m_t, s_t = self._fast[i], self._mid[i], self._slow[i]
        if f_t is None or m_t is None or s_t is None:
            return None
        bar = self._bars[i]
        up = f_t > m_t > s_t
        down = f_t < m_t < s_t

        if up:
            cross = self._cross_index(i, up=True)
            if cross is not None and 0 < i - cross <= cfg.cross_lookback:
                pull = self._first_pullback(cross, i, long_side=True)
                if pull is not None and bar.close > self._bars[pull].high:
                    target: float | None = None
                    if cfg.variant == "measured_move":
                        swing = max(self._bars[k].high for k in range(cross, pull + 1))
                        target = bar.close + (swing - self._bars[pull].low)
                    return Setup(
                        side="long",
                        stop=self._bars[pull].low,
                        target=target,
                        rule=f"exp001_{cfg.variant}_long",
                    )
        if down:
            cross = self._cross_index(i, up=False)
            if cross is not None and 0 < i - cross <= cfg.cross_lookback:
                pull = self._first_pullback(cross, i, long_side=False)
                if pull is not None and bar.close < self._bars[pull].low:
                    target = None
                    if cfg.variant == "measured_move":
                        swing = min(self._bars[k].low for k in range(cross, pull + 1))
                        target = bar.close - (self._bars[pull].high - swing)
                    return Setup(
                        side="short",
                        stop=self._bars[pull].high,
                        target=target,
                        rule=f"exp001_{cfg.variant}_short",
                    )
        return None

    def exit_reason(self, i: int, pos: Position) -> str | None:
        if self.config.variant != "source":
            return None  # measured_move arm exits on target (handled by simulator)
        m = self._mid[i]
        if m is None:
            return None
        close = self._bars[i].close
        if pos.side == "long" and close < m:
            return "ma40_break"
        if pos.side == "short" and close > m:
            return "ma40_break"
        return None


# ===================================================================== EXP-ARP-002


@dataclass(frozen=True, slots=True)
class Exp002Config:
    """All PROJECT_DERIVED_VARIANT: STRAT-CAND-016 declares source-faithfulness FALSE."""

    void_bars: int = 3
    void_atr_mult: float = 2.0
    retest_window: int = 48
    atr_period: int = 14


EXP002_CONFIG = Exp002Config()


class Exp002VoidRetest:
    """Liquidity-void retest. PROJECT_DERIVED_VARIANT (source is not source-faithful)."""

    def __init__(self, config: Exp002Config | None = None) -> None:
        self.config = config or EXP002_CONFIG
        self.warmup = self.config.atr_period + self.config.void_bars + 2
        self._bars: Sequence[OHLCV] = ()
        self._atr: list[float | None] = []

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        self._atr = atr_series(
            [b.high for b in bars], [b.low for b in bars], [b.close for b in bars],
            self.config.atr_period,
        )

    def _void_at(self, j: int) -> str | None:
        """Return ``"up"``/``"down"`` if the void window ending at ``j`` qualifies."""
        cfg = self.config
        start = j - cfg.void_bars + 1
        atr_j = self._atr[j]
        if start < 1 or atr_j is None:
            return None
        closes = [self._bars[k].close for k in range(start, j + 1)]
        highs = [self._bars[k].high for k in range(start, j + 1)]
        lows = [self._bars[k].low for k in range(start, j + 1)]
        span = max(highs) - min(lows)
        if span <= cfg.void_atr_mult * atr_j:
            return None
        inc = all(closes[k] < closes[k + 1] for k in range(len(closes) - 1))
        dec = all(closes[k] > closes[k + 1] for k in range(len(closes) - 1))
        if inc:
            return "up"
        if dec:
            return "down"
        return None

    def _origin(self, j: int) -> float:
        return self._bars[j - self.config.void_bars].close

    def _first_retest(self, j: int, direction: str) -> int | None:
        cfg = self.config
        origin = self._origin(j)
        end = min(j + cfg.retest_window, len(self._bars) - 1)
        for m in range(j + 1, end + 1):
            if direction == "up" and self._bars[m].low <= origin:
                return m
            if direction == "down" and self._bars[m].high >= origin:
                return m
        return None

    def entry(self, i: int) -> Setup | None:
        cfg = self.config
        atr_i = self._atr[i]
        if i < self.warmup or atr_i is None:
            return None
        close = self._bars[i].close
        lo = max(cfg.void_bars, i - cfg.retest_window)
        j = None
        direction = None
        for k in range(i, lo - 1, -1):
            found = self._void_at(k)
            if found is not None:
                j, direction = k, found
                break
        if j is None or direction is None:
            return None
        # trade only the FIRST retest of the most recent qualifying void
        if self._first_retest(j, direction) != i:
            return None
        zone_low = min(self._bars[k].low for k in range(j - cfg.void_bars + 1, j + 1))
        zone_high = max(self._bars[k].high for k in range(j - cfg.void_bars + 1, j + 1))
        atr = atr_i
        if direction == "up":
            return Setup(side="long", stop=zone_low, target=close + atr, rule="exp002_void_up")
        return Setup(side="short", stop=zone_high, target=close - atr, rule="exp002_void_down")

    def exit_reason(self, i: int, pos: Position) -> str | None:
        del i, pos
        return None


# ===================================================================== EXP-ARP-003


@dataclass(frozen=True, slots=True)
class Exp003Config:
    """All PROJECT_DERIVED_VARIANT: STRAT-CAND-012 declares source-faithfulness FALSE."""

    divergence_window: int = 24
    atr_period: int = 14


EXP003_CONFIG = Exp003Config()


class Exp003RelativeStrength:
    """Cross-sectional relative-strength divergence, traded on the laggard leg.

    ``leader_bars`` is the instrument that must make the divergent extreme; the
    simulator is run over ``laggard_bars`` (the instrument that is traded). Both
    legs are sampled at the same closed bar (``data_time <= decision_time`` for
    BOTH), which §8 requires.
    """

    def __init__(self, leader_bars: Sequence[OHLCV], config: Exp003Config | None = None) -> None:
        self.config = config or EXP003_CONFIG
        self._leader = leader_bars
        self.warmup = self.config.divergence_window + 2
        self._bars: Sequence[OHLCV] = ()
        self._lag_atr: list[float | None] = []
        self._leader_idx: dict[int, int] = {}

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        self._lag_atr = atr_series(
            [b.high for b in bars], [b.low for b in bars], [b.close for b in bars],
            self.config.atr_period,
        )
        self._leader_idx = {b.timestamp: k for k, b in enumerate(self._leader)}

    def entry(self, i: int) -> Setup | None:
        cfg = self.config
        w = cfg.divergence_window
        if i < self.warmup or self._lag_atr[i] is None:
            return None
        bar = self._bars[i]
        ia = self._leader_idx.get(bar.timestamp)
        if ia is None or ia < w + 1:
            return None
        a = self._leader
        hi_a = a[ia].high > max(a[k].high for k in range(ia - w, ia))
        lo_a = a[ia].low < min(a[k].low for k in range(ia - w, ia))
        hi_b = bar.high > max(self._bars[k].high for k in range(i - w, i))
        lo_b = bar.low < min(self._bars[k].low for k in range(i - w, i))
        atr = self._lag_atr[i]
        if atr is None:
            return None
        # leader makes the extreme, laggard does not -> resolve laggard toward leader
        if hi_a and not hi_b:
            return Setup(
                side="long", stop=bar.low, target=bar.close + atr,
                rule="exp003_divergence_up", max_hold_bars=w,
            )
        if lo_a and not lo_b:
            return Setup(
                side="short", stop=bar.high, target=bar.close - atr,
                rule="exp003_divergence_down", max_hold_bars=w,
            )
        return None

    def exit_reason(self, i: int, pos: Position) -> str | None:
        del i, pos
        return None


# ===================================================================== EXP-ARP-005


@dataclass(frozen=True, slots=True)
class Exp005Config:
    """All PROJECT_DERIVED_VARIANT: STRAT-CAND-019 declares source-faithfulness FALSE.

    Source-explicit parts kept: floor-trader pivots ``P=(H+L+C)/3``, ``R1=2P-L``,
    ``S1=2P-H``; fade the first contact. Source-unspecified parts frozen here:
    stop ``0.5 x ATR14``, target ``P``, session = UTC calendar day, one touch per
    level per day.
    """

    atr_period: int = 14
    stop_atr_mult: float = 0.5


EXP005_CONFIG = Exp005Config()


class Exp005PivotFade:
    """First-touch fade of the prior UTC day's P/R1/S1. PROJECT_DERIVED_VARIANT."""

    def __init__(self, config: Exp005Config | None = None) -> None:
        self.config = config or EXP005_CONFIG
        self.warmup = self.config.atr_period + 1
        self._bars: Sequence[OHLCV] = ()
        self._atr: list[float | None] = []
        self._pivots: dict[int, tuple[float, float, float]] = {}
        self._session_start: dict[int, int] = {}

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        self._atr = atr_series(
            [b.high for b in bars], [b.low for b in bars], [b.close for b in bars],
            self.config.atr_period,
        )
        # prior completed UTC day -> (P, R1, S1)
        day_hilo: dict[int, list[float]] = {}
        for b in bars:
            d = _day_key(b.timestamp)
            agg = day_hilo.setdefault(d, [b.high, b.low, b.close])
            agg[0] = max(agg[0], b.high)
            agg[1] = min(agg[1], b.low)
            agg[2] = b.close
        self._pivots = {}
        for d, (hi, lo, cl) in day_hilo.items():
            p = (hi + lo + cl) / 3.0
            self._pivots[d] = (p, 2.0 * p - lo, 2.0 * p - hi)
        self._session_start = {}
        for i, b in enumerate(bars):
            self._session_start.setdefault(_day_key(b.timestamp), i)

    def entry(self, i: int) -> Setup | None:
        if i < self.warmup or self._atr[i] is None:
            return None
        d = _day_key(self._bars[i].timestamp)
        piv = self._pivots.get(d - 1)
        if piv is None:
            return None
        p, r1, s1 = piv
        start = self._session_start.get(d, i)
        bar = self._bars[i]
        atr = self._atr[i]
        if atr is None:
            return None
        # first touch of R1 in the session -> short; first touch of S1 -> long
        if bar.high >= r1 and not any(self._bars[k].high >= r1 for k in range(start, i)):
            return Setup(
                side="short", stop=bar.close + self.config.stop_atr_mult * atr, target=p,
                rule="exp005_r1_short", exit_on_session_end=True,
            )
        if bar.low <= s1 and not any(self._bars[k].low <= s1 for k in range(start, i)):
            return Setup(
                side="long", stop=bar.close - self.config.stop_atr_mult * atr, target=p,
                rule="exp005_s1_long", exit_on_session_end=True,
            )
        return None

    def exit_reason(self, i: int, pos: Position) -> str | None:
        del i, pos
        return None
