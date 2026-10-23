"""ARP-005 daily strategies + cross-sectional portfolio simulator (research-only).

Implements, for the pre-registered ARP-005 portfolio only:

* :class:`Exp006LiquidityVoidReversal` — the frozen ``EXP-ARP-006`` rules
  (``STRAT-CAND-016-VARIANT-B``): fade a fast one-sided move after a retest of its
  origin band.
* :class:`Exp011VolExpansionBreakout` — a **new** project hypothesis
  (``H-VOLEXP-BREAK-001``): Donchian-high breakout that requires a daily
  volatility-expansion gate.
* :func:`simulate_xsec` — the ``EXP-ARP-009`` (``H-XSEC-RELSTR-001``) long-only
  cross-sectional momentum portfolio: rotate to the highest trailing-return asset
  at the next daily open.

All three are deterministic, PIT-safe (``data_time <= decision_time``) and free of
RNG/wall-clock. The two per-asset strategies reuse :func:`simulate_daily`; the
cross-sectional one has its own portfolio simulator because it holds exactly one
asset at a time across a synchronized multi-asset calendar.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

from .daily import DailySetup
from .series import atr_series
from .simulate import SimulationResult, Trade
from .xsec import CrossSectionalRanker

__all__ = [
    "Exp006Config",
    "Exp006LiquidityVoidReversal",
    "Exp011Config",
    "Exp011VolExpansionBreakout",
    "XsecConfig",
    "XsecRotation",
    "simulate_xsec",
]

BPS = 10_000.0
MS_PER_DAY = 86_400_000


# ------------------------------------------------------------- EXP-ARP-006 (reversal)


@dataclass(frozen=True, slots=True)
class Exp006Config:
    """Frozen EXP-ARP-006 parameters (round values, never tuned)."""

    atr_period: int = 14
    void_min_days: int = 3
    void_min_atr: float = 2.0
    retest_lookback_days: int = 10
    stop_atr: float = 1.5
    target_atr: float = 3.0
    max_hold_days: int = 5


class Exp006LiquidityVoidReversal:
    """Fade a >=3-day one-sided 'void' after price re-enters its origin band.

    Void: ``>= void_min_days`` consecutive strictly monotone daily closes whose
    total displacement is ``>= void_min_atr x ATR(14)`` at the void's last day.
    Origin band: ``[min(open_first, close_last), max(open_first, close_last)]``.
    Entry: first bar within ``retest_lookback_days`` of the void end whose high
    (down-void) or low (up-void) re-enters the band, filled at the NEXT open,
    opposite the void. Stop ``stop_atr x ATR``; target ``target_atr x ATR``.
    """

    def __init__(self, config: Exp006Config | None = None) -> None:
        self.config = config or Exp006Config()
        self.warmup = self.config.atr_period + 2
        self._bars: Sequence[OHLCV] = ()
        self._closes: list[float] = []
        self._atr: list[float | None] = []
        self._voids: dict[int, tuple[int, float, float]] = {}
        self._consumed: set[int] = set()

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        self._closes = [b.close for b in bars]
        self._atr = atr_series(
            [b.high for b in bars], [b.low for b in bars], self._closes, self.config.atr_period
        )
        self._voids = {}
        self._consumed = set()
        n = len(bars)
        for e in range(n):
            atr = self._atr[e]
            if atr is None or atr <= 0:
                continue
            for direction in (1, -1):
                start = e
                while start - 1 >= 0 and (
                    (direction == 1 and self._closes[start] > self._closes[start - 1])
                    or (direction == -1 and self._closes[start] < self._closes[start - 1])
                ):
                    start -= 1
                length = e - start + 1
                if length < self.config.void_min_days:
                    continue
                disp = abs(self._closes[e] - self._closes[start])
                if disp < self.config.void_min_atr * atr:
                    continue
                lo = min(bars[start].open, self._closes[e])
                hi = max(bars[start].open, self._closes[e])
                self._voids[e] = (direction, lo, hi)

    def entry(self, i: int) -> DailySetup | None:
        if i < self.warmup:
            return None
        atr = self._atr[i]
        if atr is None:
            return None
        bar = self._bars[i]
        low_e = max(0, i - self.config.retest_lookback_days)
        for e in range(i - 1, low_e - 1, -1):
            if e in self._consumed or e not in self._voids:
                continue
            direction, lo, hi = self._voids[e]
            side: str | None = None
            if direction == -1 and bar.high >= lo:  # down-void -> fade long
                side = "long"
            elif direction == 1 and bar.low <= hi:  # up-void -> fade short
                side = "short"
            if side is not None:
                self._consumed.add(e)
                return DailySetup(
                    side=side,
                    rule="exp006_void_reversal",
                    max_hold_days=self.config.max_hold_days,
                    atr=atr,
                    stop_atr_mult=self.config.stop_atr,
                    target_atr_mult=self.config.target_atr,
                )
        return None


# ------------------------------------------------------- EXP-ARP-011 (breakout)


@dataclass(frozen=True, slots=True)
class Exp011Config:
    """Frozen EXP-ARP-011 parameters (round values, never tuned)."""

    atr_period: int = 14
    breakout_lookback_days: int = 20
    vol_gate_days: int = 20
    stop_atr: float = 1.5
    target_atr: float = 3.0
    max_hold_days: int = 10


class Exp011VolExpansionBreakout:
    """Long a Donchian-high breakout only when volatility is expanding.

    Signal on the daily close: ``close[i] > max(high[i-L .. i-1])`` (prior
    ``breakout_lookback_days`` bars, current excluded) **and**
    ``ATR(14)[i] > median(ATR(14)[i-V .. i-1])``. Long at the next open; stop
    ``stop_atr x ATR``; target ``target_atr x ATR``; max hold ``max_hold_days``.
    Long-only (spot corpus; a short leg is out of scope).
    """

    def __init__(self, config: Exp011Config | None = None) -> None:
        self.config = config or Exp011Config()
        self.warmup = max(self.config.breakout_lookback_days, self.config.vol_gate_days) + 2
        self._bars: Sequence[OHLCV] = ()
        self._atr: list[float | None] = []
        self._prior_high: list[float | None] = []
        self._atr_median: list[float | None] = []

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        n = len(bars)
        self._atr = atr_series(
            [b.high for b in bars],
            [b.low for b in bars],
            [b.close for b in bars],
            self.config.atr_period,
        )
        lb = self.config.breakout_lookback_days
        prior_high: list[float | None] = [None] * n
        for i in range(n):
            if i >= lb:
                prior_high[i] = max(bars[j].high for j in range(i - lb, i))
        self._prior_high = prior_high
        vg = self.config.vol_gate_days
        atr_med: list[float | None] = [None] * n
        for i in range(n):
            window = [self._atr[j] for j in range(max(0, i - vg), i)]
            vals = [v for v in window if v is not None]
            if len(vals) == vg:
                atr_med[i] = statistics.median(vals)
        self._atr_median = atr_med

    def entry(self, i: int) -> DailySetup | None:
        if i < self.warmup:
            return None
        atr = self._atr[i]
        ph = self._prior_high[i]
        med = self._atr_median[i]
        if atr is None or atr <= 0 or ph is None or med is None:
            return None
        if self._bars[i].close > ph and atr > med:
            return DailySetup(
                side="long",
                rule="exp011_volexp_breakout",
                max_hold_days=self.config.max_hold_days,
                atr=atr,
                stop_atr_mult=self.config.stop_atr,
                target_atr_mult=self.config.target_atr,
            )
        return None


# ------------------------------------------- EXP-ARP-009 (cross-sectional momentum)


@dataclass(frozen=True, slots=True)
class XsecConfig:
    """Frozen EXP-ARP-009 parameters (round values, never tuned)."""

    lookback_days: int = 30
    max_hold_days: int = 30
    long_only: bool = True


@dataclass(frozen=True, slots=True)
class XsecRotation:
    """One completed holding episode of the cross-sectional portfolio."""

    symbol: str
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    reason: str


def _daily_index(bars: Sequence[OHLCV]) -> dict[int, OHLCV]:
    return {b.timestamp: b for b in bars}


def simulate_xsec(
    bars_by_symbol: Mapping[str, Sequence[OHLCV]],
    *,
    config: XsecConfig,
    cost_bps_rt: float,
    notional: float = 500.0,
) -> SimulationResult:
    """Long-only cross-sectional momentum: hold the top trailing-return asset.

    Rebalance decision at the close of each synchronized daily bar, executed at the
    NEXT day's open (``data_time <= decision_time <= fill_time``). The calendar is
    the intersection of all symbols' day-only series, so no asset is ever ranked on
    a stale bar. Rotation closes the current holding and opens the new leader at the
    same next open; a ``max_hold_days`` cap force-exits and excludes re-entry until
    the leader changes. One round-trip cost is charged per completed episode.
    """
    ranker = CrossSectionalRanker(min_members=2)
    index: dict[str, dict[int, OHLCV]] = {s: _daily_index(b) for s, b in bars_by_symbol.items()}
    if not index:
        return SimulationResult(trades=[], eval_bars=0)
    day_sets = [set(d) for d in index.values()]
    calendar = sorted(set.intersection(*day_sets))
    fee_usd = notional * cost_bps_rt / BPS
    trades: list[Trade] = []

    held_sym: str | None = None
    entry_price = 0.0
    entry_ts = 0
    entry_i = -1
    cap_excluded: str | None = None

    def close(sym: str, exit_price: float, exit_ts: int, reason: str) -> None:
        gross = notional * (exit_price / entry_price - 1.0)
        trades.append(
            Trade(
                side="long",
                entry_ts=entry_ts,
                exit_ts=exit_ts,
                duration_min=round((exit_ts - entry_ts) / 60_000.0, 1),
                entry=round(entry_price, 6),
                exit=round(exit_price, 6),
                reason=reason,
                mfe_pct=0.0,
                mae_pct=0.0,
                notional=round(notional, 2),
                gross=round(gross, 4),
                fees=round(fee_usd, 4),
                net=round(gross - fee_usd, 4),
                rule=f"exp009_xsec_{sym}",
            )
        )

    for i in range(len(calendar) - 1):
        day = calendar[i]
        nxt_day = calendar[i + 1]
        snapshot = {s: [b for b in bars_by_symbol[s] if b.timestamp <= day] for s in index}
        ru = ranker.rank(snapshot, day, config.lookback_days)
        leader = ru.leader()
        if cap_excluded is not None and leader != cap_excluded:
            cap_excluded = None
        nxt_open = {s: index[s][nxt_day].open for s in index}

        if held_sym is None:
            if leader is not None and leader != cap_excluded:
                held_sym, entry_price, entry_ts, entry_i = leader, nxt_open[leader], nxt_day, i + 1
            continue

        rank = ru.rank_of(held_sym)
        days_held = i - entry_i
        rank_lost = leader != held_sym or rank is None
        cap_hit = days_held >= config.max_hold_days
        if rank_lost or cap_hit:
            close(held_sym, nxt_open[held_sym], nxt_day, "rotate" if rank_lost else "window_expiry")
            exited = held_sym
            held_sym = None
            if cap_hit and not rank_lost:
                cap_excluded = exited
            if leader is not None and leader != cap_excluded:
                held_sym, entry_price, entry_ts, entry_i = leader, nxt_open[leader], nxt_day, i + 1

    # close any residual holding at the final bar's close (mark-to-market exit)
    if held_sym is not None:
        last_day = calendar[-1]
        close(held_sym, index[held_sym][last_day].close, last_day, "window_expiry")

    return SimulationResult(trades=trades, eval_bars=len(calendar))
