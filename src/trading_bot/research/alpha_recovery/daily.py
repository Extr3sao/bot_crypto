"""ARP-004 daily-horizon experiments (research-only, deterministic, PIT-safe).

Implements the two pre-registered ARP-004 experiments only:

* ``EXP-ARP-007`` — ``STRAT-CAND-019-VARIANT-B`` daily pivot fade
  (:class:`Exp007DailyPivotFade`);
* ``EXP-ARP-010`` — ``H-VOLSPIKE-MR-001`` volatility-spike mean reversion
  (:class:`Exp010VolSpikeMR`).

Neither is a source-faithful test. EXP-ARP-007 is a ``PROJECT_DERIVED_VARIANT``
(the STRAT-CAND-019 source reconstruction is ``BLOCKED_NEEDS_SPEC``) and
EXP-ARP-010 is a new project hypothesis. **No result may be attributed to a
source hypothesis.**

Two contract differences from the ARP-002 5-minute campaign, both forced by the
daily horizon and frozen BEFORE any result (documented in the ARP-004
``SPEC_AUDIT.md``):

1. **Next-open entry.** Daily bars are derived from the frozen 5-minute corpus by
   complete UTC epoch buckets. A signal produced on a *closed* daily bar is
   filled at the *next* daily bar's open — the frozen rule wording is
   "entry: next daily bar's open". :func:`simulate_daily` therefore fills at
   ``open[i+1]`` (still ``data_time <= decision_time <= fill_time``), unlike the
   5-minute :func:`~trading_bot.research.alpha_recovery.simulate.simulate` which
   fills at ``close[i]``.
2. **Per-split concatenation.** The ARP-002 driver ran each weekly window
   independently. A daily strategy cannot consume a 60-day warmup inside a
   30-day window, so the ARP-004 driver concatenates the windows of one split
   (DEV W1-W4, VALIDATION W5-W6) into a single contiguous daily series per
   symbol. OOS (W7) is never read unless every prior gate passes.

Ambiguous frozen wording is resolved conservatively and documented here so no
discretionary rule remains:

* EXP-ARP-007, a day whose daily bar touches **both** ``R1`` and ``S1`` is
  skipped (the intraday ordering is unknowable from daily OHLC).
* EXP-ARP-010, "day's return <= -1.0 x ATR(14)" is read dimensionally: the
  day's price change ``close[D] - close[D-1]`` (same units as ATR) ``<=``
  ``-1.0 * ATR(14)``.
* ``max_hold_days`` = the maximum number of daily bars the position may span
  counting the entry bar; the position is force-closed at the close of the
  ``max_hold_days``-th bar.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from trading_bot.market_data.types import OHLCV

from .series import atr_series
from .simulate import SimulationResult, Trade

__all__ = [
    "BARS_PER_DAY_5M",
    "MS_PER_DAY",
    "DailySetup",
    "Exp007Config",
    "Exp007DailyPivotFade",
    "Exp010Config",
    "Exp010VolSpikeMR",
    "daily_bars_from_5m",
    "day_key",
    "realized_daily_vol",
    "simulate_daily",
]

BPS = 10_000.0
MS_PER_DAY = 86_400_000
MS_PER_5M = 300_000
BARS_PER_DAY_5M = 288


def day_key(ts_ms: int) -> int:
    """UTC calendar-day index of a millisecond timestamp."""
    return ts_ms // MS_PER_DAY


def _sign(side: str) -> float:
    return 1.0 if side == "long" else -1.0


def _complete_days(bars_5m: Sequence[OHLCV]) -> dict[int, list[OHLCV]]:
    """Group 5-minute bars into *complete* UTC days only.

    A day qualifies only if it carries exactly 288 bars, the first at the exact
    day boundary and the last 287 x 5m later — so a partially-formed (current)
    day can never be turned into a daily bar. This is the PIT guarantee for the
    daily derivation.
    """
    by_day: dict[int, list[OHLCV]] = {}
    for b in bars_5m:
        by_day.setdefault(day_key(b.timestamp), []).append(b)
    complete: dict[int, list[OHLCV]] = {}
    span = (BARS_PER_DAY_5M - 1) * MS_PER_5M
    for d, day in by_day.items():
        if len(day) != BARS_PER_DAY_5M:
            continue
        ordered = sorted(day, key=lambda x: x.timestamp)
        if ordered[0].timestamp != d * MS_PER_DAY:
            continue
        if ordered[-1].timestamp - ordered[0].timestamp != span:
            continue
        complete[d] = ordered
    return complete


def daily_bars_from_5m(bars_5m: Sequence[OHLCV]) -> list[OHLCV]:
    """Derive 1-day bars from 5-minute bars via complete UTC epoch buckets.

    Open = first 5m open of the day, high/low = day extremes, close = last 5m
    close, timestamp = the exact UTC day boundary. Incomplete days are dropped,
    never synthesised.
    """
    complete = _complete_days(bars_5m)
    out: list[OHLCV] = []
    for d in sorted(complete):
        day = complete[d]
        out.append(
            OHLCV(
                symbol=day[0].symbol,
                timestamp=d * MS_PER_DAY,
                open=day[0].open,
                high=max(b.high for b in day),
                low=min(b.low for b in day),
                close=day[-1].close,
                volume=sum(b.volume for b in day),
            )
        )
    return out


def realized_daily_vol(bars_5m: Sequence[OHLCV]) -> dict[int, float]:
    """Daily realized volatility ``sqrt(sum(r_5m^2))`` over the day's own 5m returns.

    Only complete UTC days are considered; the returns are the 287 consecutive
    intra-day 5-minute simple returns (the day's own closed bars, available at
    that day's close — never a future bar).
    """
    out: dict[int, float] = {}
    for d, day in _complete_days(bars_5m).items():
        acc = 0.0
        for k in range(1, len(day)):
            prev = day[k - 1].close
            if prev > 0:
                r = day[k].close / prev - 1.0
                acc += r * r
        out[d] = math.sqrt(acc)
    return out


# --------------------------------------------------------------------- setups


@dataclass(frozen=True, slots=True)
class DailySetup:
    """A daily entry candidate produced on a closed bar.

    Levels may be absolute (known from closed bars at signal time) or expressed
    as ATR distances resolved against the fill price by :func:`simulate_daily`.
    """

    side: str
    rule: str
    max_hold_days: int
    stop: float | None = None
    target: float | None = None
    atr: float | None = None
    stop_atr_mult: float | None = None
    target_atr_mult: float | None = None


@dataclass(slots=True)
class _DailyPosition:
    side: str
    entry: float
    stop: float
    target: float | None
    entry_index: int
    entry_ts: int
    rule: str
    max_hold_days: int
    mfe: float = 0.0
    mae: float = 0.0


class DailyStrategy(Protocol):
    """Single-asset deterministic daily strategy protocol."""

    warmup: int

    def prepare(self, bars: Sequence[OHLCV]) -> None: ...

    def entry(self, i: int) -> DailySetup | None: ...


# ---------------------------------------------------------------- simulator


def simulate_daily(
    strategy: DailyStrategy,
    bars: Sequence[OHLCV],
    *,
    cost_bps_rt: float,
    notional: float = 500.0,
    entry_delay_days: int = 0,
) -> SimulationResult:
    """Run one daily strategy over one asset's closed daily bars.

    Contract (frozen before any result): a setup found on closed bar ``i`` is
    filled at ``open[i + 1 + entry_delay_days]``; stop-first on intra-bar
    ambiguity; one position at a time; fixed notional; a single round-trip cost
    figure. ``entry_delay_days`` > 0 models execution latency and can only make
    a strategy worse.
    """
    strategy.prepare(bars)
    n = len(bars)
    trades: list[Trade] = []
    pos: _DailyPosition | None = None
    pending: DailySetup | None = None
    pending_due = -1
    fee_usd = notional * cost_bps_rt / BPS

    def close_position(price: float, ts: int, reason: str, p: _DailyPosition) -> None:
        gross = notional * (price / p.entry - 1.0) * _sign(p.side)
        net = gross - fee_usd
        trades.append(
            Trade(
                side=p.side,
                entry_ts=p.entry_ts,
                exit_ts=ts,
                duration_min=round((ts - p.entry_ts) / 60_000.0, 1),
                entry=round(p.entry, 6),
                exit=round(price, 6),
                reason=reason,
                mfe_pct=round(p.mfe / p.entry * 100.0, 4),
                mae_pct=round(p.mae / p.entry * 100.0, 4),
                notional=round(notional, 2),
                gross=round(gross, 4),
                fees=round(fee_usd, 4),
                net=round(net, 4),
                rule=p.rule,
            )
        )

    for i in range(n):
        bar = bars[i]

        # 1. fill a pending entry at this bar's open
        if pos is None and pending is not None and i >= pending_due:
            setup = pending
            pending = None
            entry = bar.open
            if setup.stop is not None:
                stop = setup.stop
            else:
                assert setup.stop_atr_mult is not None and setup.atr is not None
                stop = entry - _sign(setup.side) * setup.stop_atr_mult * setup.atr
            if setup.target is not None:
                target: float | None = setup.target
            elif setup.target_atr_mult is not None and setup.atr is not None:
                target = entry + _sign(setup.side) * setup.target_atr_mult * setup.atr
            else:
                target = None
            pos = _DailyPosition(
                side=setup.side,
                entry=entry,
                stop=stop,
                target=target,
                entry_index=i,
                entry_ts=bar.timestamp,
                rule=setup.rule,
                max_hold_days=setup.max_hold_days,
            )

        # 2. manage the open position over this bar
        if pos is not None:
            high, low, close = bar.high, bar.low, bar.close
            if pos.side == "long":
                pos.mfe = max(pos.mfe, high - pos.entry)
                pos.mae = max(pos.mae, pos.entry - low)
                stop_hit = low <= pos.stop
                target_hit = pos.target is not None and high >= pos.target
            else:
                pos.mfe = max(pos.mfe, pos.entry - low)
                pos.mae = max(pos.mae, high - pos.entry)
                stop_hit = high >= pos.stop
                target_hit = pos.target is not None and low <= pos.target
            if stop_hit:
                close_position(pos.stop, bar.timestamp, "stop", pos)
                pos = None
            elif target_hit and pos.target is not None:
                close_position(pos.target, bar.timestamp, "target", pos)
                pos = None
            elif (i - pos.entry_index) >= pos.max_hold_days - 1:
                close_position(close, bar.timestamp, "window_expiry", pos)
                pos = None

        # 3. a signal produced on this closed bar fills at a later open
        if pos is None and pending is None and i < n - 1:
            signal = strategy.entry(i)
            if signal is not None:
                due = i + 1 + entry_delay_days
                if due <= n - 1:
                    pending = signal
                    pending_due = due

    return SimulationResult(trades=trades, eval_bars=n)


# ---------------------------------------------------------------- EXP-ARP-007


@dataclass(frozen=True, slots=True)
class Exp007Config:
    """EXP-ARP-007 frozen parameters (PROJECT_DERIVED_VARIANT, not source)."""

    atr_period: int = 14
    stop_atr: float = 1.0
    max_hold_days: int = 3


class Exp007DailyPivotFade:
    """Daily fade of the first contact with the prior day's floor-trader pivot bands.

    ``PP = (H+L+C)/3``, ``R1 = 2*PP - L``, ``S1 = 2*PP - H`` from the prior
    completed UTC day. A daily bar touching ``R1`` fades short, a bar touching
    ``S1`` fades long (a bar touching both is skipped). Stop is ``1.0 x ATR(14)``
    beyond the level, target is ``PP``. PROJECT_DERIVED_VARIANT.
    """

    def __init__(self, config: Exp007Config | None = None) -> None:
        self.config = config or Exp007Config()
        self.warmup = self.config.atr_period + 2
        self._bars: Sequence[OHLCV] = ()
        self._atr: list[float | None] = []
        self._pivot: list[tuple[float, float, float] | None] = []

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        self._atr = atr_series(
            [b.high for b in bars],
            [b.low for b in bars],
            [b.close for b in bars],
            self.config.atr_period,
        )
        pivots: list[tuple[float, float, float] | None] = [None] * len(bars)
        for i in range(1, len(bars)):
            prev = bars[i - 1]
            p = (prev.high + prev.low + prev.close) / 3.0
            pivots[i] = (p, 2.0 * p - prev.low, 2.0 * p - prev.high)
        self._pivot = pivots

    def entry(self, i: int) -> DailySetup | None:
        if i < self.warmup:
            return None
        atr = self._atr[i]
        piv = self._pivot[i]
        if atr is None or piv is None:
            return None
        bar = self._bars[i]
        p, r1, s1 = piv
        touch_short = bar.high >= r1
        touch_long = bar.low <= s1
        if touch_short and touch_long:
            return None  # frozen tie-break: intraday ordering unknowable
        if touch_short:
            return DailySetup(
                side="short",
                rule="exp007_r1_short",
                max_hold_days=self.config.max_hold_days,
                stop=r1 + self.config.stop_atr * atr,
                target=p,
            )
        if touch_long:
            return DailySetup(
                side="long",
                rule="exp007_s1_long",
                max_hold_days=self.config.max_hold_days,
                stop=s1 - self.config.stop_atr * atr,
                target=p,
            )
        return None


# ---------------------------------------------------------------- EXP-ARP-010


@dataclass(frozen=True, slots=True)
class Exp010Config:
    """EXP-ARP-010 frozen parameters (new project hypothesis H-VOLSPIKE-MR-001)."""

    atr_period: int = 14
    vol_lookback_days: int = 60
    vol_z_entry: float = 2.0
    ret_atr: float = 1.0
    stop_atr: float = 2.0
    target_atr: float = 1.0
    max_hold_days: int = 2


def _vol_z_scores(
    vols: Sequence[float | None],
    days: Sequence[int],
    lookback: int,
) -> list[float | None]:
    """Z-score of each day's realized vol against the previous ``lookback`` days.

    ``None`` until a contiguous, fully-populated trailing window exists. The
    current day is excluded from its own window (no look-ahead), and the window
    must be day-contiguous so a skipped day cannot silently shorten it.
    """
    n = len(vols)
    out: list[float | None] = [None] * n
    for i in range(n):
        if i < lookback:
            continue
        cur = vols[i]
        if cur is None:
            continue
        if days[i] - days[i - lookback] != lookback:
            continue
        window = vols[i - lookback : i]
        if any(v is None for v in window):
            continue
        vals = [v for v in window if v is not None]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var)
        if sd <= 0:
            continue
        out[i] = (cur - mean) / sd
    return out


class Exp010VolSpikeMR:
    """Long a volatility-spike down day, next open (new project hypothesis).

    Regime: daily realized-vol z-score vs the trailing ``vol_lookback_days=60``.
    Signal: ``vol_z >= 2.0`` **and** the day's price change
    ``close[D] - close[D-1] <= -1.0 * ATR(14)``. Long at the next open; stop
    ``2.0 x ATR(14)``; target ``1.0 x ATR(14)``; max hold ``2`` days; long-only.
    """

    def __init__(
        self,
        realized_vol_by_day: Mapping[int, float] | None = None,
        config: Exp010Config | None = None,
    ) -> None:
        self.config = config or Exp010Config()
        self._vol_by_day = dict(realized_vol_by_day or {})
        self.warmup = max(self.config.atr_period + 1, self.config.vol_lookback_days + 1)
        self._bars: Sequence[OHLCV] = ()
        self._atr: list[float | None] = []
        self._z: list[float | None] = []

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars
        self._atr = atr_series(
            [b.high for b in bars],
            [b.low for b in bars],
            [b.close for b in bars],
            self.config.atr_period,
        )
        days = [day_key(b.timestamp) for b in bars]
        vols: list[float | None] = [self._vol_by_day.get(d) for d in days]
        self._z = _vol_z_scores(vols, days, self.config.vol_lookback_days)

    def entry(self, i: int) -> DailySetup | None:
        if i < self.warmup:
            return None
        atr = self._atr[i]
        z = self._z[i]
        if atr is None or z is None:
            return None
        change = self._bars[i].close - self._bars[i - 1].close
        if z >= self.config.vol_z_entry and change <= -self.config.ret_atr * atr:
            return DailySetup(
                side="long",
                rule="exp010_volspike_long",
                max_hold_days=self.config.max_hold_days,
                atr=atr,
                stop_atr_mult=self.config.stop_atr,
                target_atr_mult=self.config.target_atr,
            )
        return None
