"""Point-in-time core for the WP-EDGE-015/016 families.

The defect this module exists to remove was measured, not suspected: in the
WP-EDGE-015 families every exit test read the *current* bar's close and then
filled at that same bar's **open**, which had already happened before that close
existed. Every exit in the published run was filled at a price that preceded its
own information (see ``reports/economic-recovery/RFC-EDGE-016/PIT_DEFECT_MAP.md``).

The contract is stated once, here, and every family is evaluated through it:

``decision_clock``
    A rule is evaluated once per **closed** bar, at the instant that bar's data
    is complete. An indicator that has not warmed up is undefined (NaN), and a
    gate reading an undefined input is False — never a default.
``entry_signal``
    A signal read off bar *t* fills at the open of bar *t+1*. This is what the
    WP-EDGE-015 entries already did, and it is preserved exactly.
``exit_signal``
    A signal read off bar *t* fills at the open of bar *t+1* — **not** at the
    open of bar *t*, which is where WP-EDGE-015 filled it. That single shift is
    the point-in-time repair.
``terminal``
    A position still open at the last closed bar is **marked** at that bar's
    close and flagged ``is_mark``. A mark is not a fill, and the reports say so.
``intrabar``
    No intrabar path is invented: these rules act on closes only. The paper
    lane's broker owns the OHLC question and resolves it conservatively.

Both paths — the batch backtest and the streaming paper lane — drive the **same
machine objects**: ``run_family`` runs a machine to completion, and the lane
calls ``on_closed_bar`` one bar at a time. There is no second implementation of
a rule to drift from the first, which is what makes ``TEST_TARGET ==
EXPERIMENT_TARGET`` true here rather than aspirational.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Protocol

from .experiments import Bar

__all__ = [
    "PIT_CONTRACT",
    "Decision",
    "MachineBase",
    "OutOfOrderBar",
    "audit_trade",
    "machine_for",
    "run_family",
]

#: The contract as data, so a verifier reads it instead of quoting a docstring.
PIT_CONTRACT: dict[str, Any] = {
    "schema_version": "EDGE16_PIT_CONTRACT_V1",
    "decision_clock": "once per closed bar, at data_available_at (the bar's close time)",
    "entry_signal": "signal read off bar t fills at the open of bar t+1",
    "exit_signal": "signal read off bar t fills at the open of bar t+1, never at bar t's open",
    "terminal_mark": "an open position at the last closed bar is marked at that close, is_mark=true",
    "undefined_indicator": "NaN; every gate that reads it is False",
    "intrabar": "not resolved here: these rules act on closes only",
    "same_instant_reentry": "an entry filling at the same instant as the previous exit is dropped",
}


def _nan(value: float | None) -> float:
    """``None`` as NaN — what the vectorised indicators did with it."""
    return float("nan") if value is None else float(value)


class OutOfOrderBar(ValueError):
    """A bar older than one the machine has already decided on.

    Silently accepting it would let a shuffled tape produce a decision that the real
    clock could never have produced, so the machine refuses instead.
    """


class Machine(Protocol):
    """What the batch driver and the paper lane both require from a family."""

    name: str

    def period_ms(self) -> int: ...

    def on_closed_bar(self, index: int, bar: Bar, *, in_position: bool) -> Decision | None: ...

    def notify_fill(self, kind: str, index: int, price: float) -> None: ...


# --------------------------------------------------------------------------------------
# incremental indicators: same arithmetic and same seeding as the vectorised twins
# --------------------------------------------------------------------------------------


class RollingSum:
    """The running sum ``_sma`` keeps: add, then subtract the value leaving the window."""

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self._values: list[float] = []
        self._running = 0.0

    def update(self, value: float) -> float | None:
        self._values.append(value)
        self._running += value
        if len(self._values) > self.span:
            self._running -= self._values[-self.span - 1]
        if len(self._values) < self.span:
            return None
        return self._running / self.span


class RollingStdev:
    """Population stdev over the trailing ``span`` values, as ``_stdev`` computes it."""

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self._values: list[float] = []

    def update(self, value: float) -> float | None:
        self._values.append(value)
        if len(self._values) < self.span:
            return None
        window = self._values[-self.span :]
        mean = sum(window) / self.span
        return math.sqrt(sum((v - mean) ** 2 for v in window) / self.span)


class Ema:
    """``_ema``: seeded with the mean of the first ``span`` values, then recursive."""

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self._k = 2.0 / (self.span + 1.0)
        self._seed: list[float] = []
        self._previous: float | None = None

    def update(self, value: float) -> float | None:
        if self._previous is None:
            self._seed.append(value)
            if len(self._seed) < self.span:
                return None
            self._previous = sum(self._seed) / self.span
            return self._previous
        self._previous = value * self._k + self._previous * (1.0 - self._k)
        return self._previous

    @property
    def value(self) -> float:
        return _nan(self._previous)


class Atr:
    """``_atr``: EMA of the true ranges, seeded the same way."""

    def __init__(self, span: int) -> None:
        self._ema = Ema(span)
        self._previous_close: float | None = None

    def update(self, bar: Bar) -> float | None:
        if self._previous_close is None:
            true_range = bar.high - bar.low
        else:
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - self._previous_close),
                abs(bar.low - self._previous_close),
            )
        self._previous_close = bar.close
        return self._ema.update(true_range)

    @property
    def value(self) -> float:
        return self._ema.value


class RollingExtreme:
    """``_rolling_max`` / ``_rolling_min`` over the trailing ``span`` values."""

    def __init__(self, span: int, *, biggest: bool) -> None:
        self.span = int(span)
        self._biggest = biggest
        self._values: list[float] = []

    def update(self, value: float) -> float | None:
        self._values.append(value)
        if len(self._values) < self.span:
            return None
        window = self._values[-self.span :]
        return max(window) if self._biggest else min(window)


class PercentileRank:
    """``_percentile_rank``: bounds fixed by the first full window, then rolling counts.

    The vectorised twin fixes its bucket bounds from the first ``window`` known
    values of the whole series and never revisits them; this mirrors that,
    including the clamp and the 50-bucket resolution.
    """

    def __init__(self, window: int, *, buckets: int = 50) -> None:
        self.window = int(window)
        self.buckets = int(buckets)
        self._warmup: list[float] = []
        self._low: float | None = None
        self._width: float | None = None
        self._counts: list[int] = []
        self._recent: list[int] = []
        self._dead = window <= 1

    def update(self, value: float | None) -> float | None:
        if self._dead or value is None or math.isnan(float(value)):
            return None
        if self._low is None:
            self._warmup.append(float(value))
            if len(self._warmup) < self.window:
                return None
            low, high = min(self._warmup), max(self._warmup)
            if high <= low:
                self._dead = True
                return None
            self._low = low
            self._width = (high - low) / self.buckets
            self._counts = [0] * self.buckets
            for item in self._warmup:
                bucket = self._bucket(item)
                self._counts[bucket] += 1
                self._recent.append(bucket)
            self._warmup = []
            return self._rank(self._recent[-1])
        bucket = self._bucket(float(value))
        self._counts[bucket] += 1
        self._recent.append(bucket)
        if len(self._recent) > self.window:
            self._counts[self._recent.pop(0)] -= 1
        return self._rank(bucket)

    def _bucket(self, value: float) -> int:
        assert self._low is not None and self._width is not None  # set before any use
        raw = int((value - self._low) / self._width) if self._width > 0 else 0
        return min(self.buckets - 1, max(0, raw))

    def _rank(self, bucket: int) -> float:
        below = sum(self._counts[:bucket]) + 0.5 * self._counts[bucket]
        return below / self.window


class VolumeMedian:
    """``median`` over the trailing ``span`` volumes, as the vectorised code did it."""

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self._values: list[float] = []

    def update(self, value: float) -> float | None:
        self._values.append(value)
        if len(self._values) < 2:
            return None
        return median(self._values[-self.span :])


class PeriodEstimator:
    """The series' own bar spacing, so a timestamp is never assumed to be an hour."""

    def __init__(self) -> None:
        self._last: int | None = None
        self._deltas: list[int] = []

    def update(self, ts_ms: int) -> None:
        if self._last is not None and ts_ms > self._last:
            self._deltas.append(ts_ms - self._last)
        self._last = ts_ms

    def period_ms(self) -> int:
        if not self._deltas:
            return 3_600_000
        return int(median(self._deltas))


# --------------------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """A rule fired at a closed bar. The machine owns the rule; the driver owns the fill."""

    kind: str  # ENTRY | EXIT
    rule: str
    signal_index: int
    fill_index: int
    detail: dict[str, float] = field(default_factory=dict)


class MachineBase:
    """Shared plumbing: which bar is being decided on, and where it may fill."""

    name = "machine"

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        self.index = -1
        self.bar: Bar | None = None
        self.in_position = False
        self.entry_index: int | None = None
        self.entry_price = float("nan")
        self._period = PeriodEstimator()

    def period_ms(self) -> int:
        return self._period.period_ms()

    def notify_fill(self, kind: str, index: int, price: float) -> None:
        if kind == "ENTRY":
            self.entry_index = index
            self.entry_price = float(price)
            return
        self.entry_index = None
        self.entry_price = float("nan")

    def _advance(self, index: int, bar: Bar, in_position: bool) -> None:
        if self.index >= 0 and index < self.index:
            raise OutOfOrderBar(
                f"{self.name}: bar index {index} arrived after {self.index}; "
                "a rule must never decide on a bar older than one it has already seen"
            )
        self.index = index
        self.bar = bar
        self.in_position = in_position
        self._period.update(bar.ts_ms)

    def _decide(self, kind: str, rule: str, **detail: float) -> Decision:
        return Decision(
            kind=kind,
            rule=rule,
            signal_index=self.index,
            fill_index=self.index + 1,
            detail=detail,
        )

    def on_closed_bar(self, index: int, bar: Bar, *, in_position: bool) -> Decision | None:
        raise NotImplementedError

    # -- small history helper ----------------------------------------------------------

    @staticmethod
    def _at(series: deque[float], back: int) -> float:
        """Value ``back`` bars before the newest one; NaN when the series is short."""
        if len(series) <= back:
            return float("nan")
        return float(series[-1 - back])


# --- A1: volatility-regime breakout ---------------------------------------------------


class BreakoutMachine(MachineBase):
    """Close above the trailing high, gated on ATR percentile and the long trend."""

    name = "vol_regime_breakout"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._upper = RollingExtreme(int(self.params["channel_hours"]), biggest=True)
        self._lower = RollingExtreme(int(self.params["channel_hours"]), biggest=False)
        self._atr = Atr(int(self.params["atr_hours"]))
        self._rank = PercentileRank(int(self.params["percentile_window_hours"]))
        self._regime = Ema(int(self.params["regime_ema_hours"]))
        self._closes: deque[float] = deque(maxlen=4)
        self._uppers: deque[float] = deque(maxlen=4)
        self._lowers: deque[float] = deque(maxlen=4)
        self._atrs: deque[float] = deque(maxlen=4)
        self._ranks: deque[float] = deque(maxlen=4)
        self._regimes: deque[float] = deque(maxlen=4)
        self._peak = float("nan")

    def notify_fill(self, kind: str, index: int, price: float) -> None:
        super().notify_fill(kind, index, price)
        if kind == "ENTRY":
            self._peak = float("nan")  # seeded from the entry bar's close, as before

    def on_closed_bar(self, index: int, bar: Bar, *, in_position: bool) -> Decision | None:
        self._advance(index, bar, in_position)
        self._closes.append(bar.close)
        self._uppers.append(_nan(self._upper.update(bar.high)))
        self._lowers.append(_nan(self._lower.update(bar.low)))
        atr_value = self._atr.update(bar)
        self._atrs.append(_nan(atr_value))
        # the rank is read over the ATR series, so it warms up with it
        self._ranks.append(_nan(self._rank.update(None if atr_value is None else float(atr_value))))
        self._regimes.append(_nan(self._regime.update(bar.close)))

        if not in_position:
            # signal bar t: the channel ends at t-1 (``prior`` in the WP-EDGE-015 code), so a
            # close cannot break a channel that contains its own bar
            upper_prior = self._at(self._uppers, 1)
            rank = self._at(self._ranks, 0)
            regime = self._at(self._regimes, 0)
            if (
                index >= 1
                and bar.close > upper_prior
                and float(self.params["atr_percentile_min"])
                <= rank
                <= float(self.params["atr_percentile_max"])
                and bar.close > regime
            ):
                return self._decide(
                    "ENTRY", "BREAKOUT_CLOSE_ABOVE_CHANNEL", close=bar.close, rank=rank
                )
            return None

        if math.isnan(self._peak):
            self._peak = bar.close
        self._peak = max(self._peak, bar.close)
        atr_previous = self._at(self._atrs, 1)
        if bar.close < self._peak - float(self.params["trail_atr_multiple"]) * atr_previous:
            return self._decide("EXIT", "TRAILING_STOP_ON_CLOSE", close=bar.close, peak=self._peak)
        previous_close = self._at(self._closes, 1)
        lower_prior = self._at(self._lowers, 2)
        if previous_close < lower_prior:
            return self._decide("EXIT", "CHANNEL_BREAK_ON_CLOSE", close=bar.close)
        return None


# --- A2: trend pullback ---------------------------------------------------------------


class PullbackMachine(MachineBase):
    """First close back below the fast mean while the trend filter is up, then recovery."""

    name = "trend_pullback"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._trend = Ema(int(self.params["trend_ema_hours"]))
        self._fast = Ema(int(self.params["fast_ema_hours"]))
        self._slow = Ema(int(self.params["slow_ema_hours"]))
        self._atr = Atr(int(self.params["atr_hours"]))
        self._slope = int(self.params["trend_slope_hours"])
        self._closes: deque[float] = deque(maxlen=int(self.params["trend_ema_hours"]) + 2)
        self._trends: deque[float] = deque(maxlen=int(self.params["trend_slope_hours"]) + 2)
        self._fasts: deque[float] = deque(maxlen=4)
        self._slows: deque[float] = deque(maxlen=4)
        self._atrs: deque[float] = deque(maxlen=4)
        self._armed = False

    def on_closed_bar(self, index: int, bar: Bar, *, in_position: bool) -> Decision | None:
        self._advance(index, bar, in_position)
        self._closes.append(bar.close)
        self._trends.append(_nan(self._trend.update(bar.close)))
        self._fasts.append(_nan(self._fast.update(bar.close)))
        self._slows.append(_nan(self._slow.update(bar.close)))
        self._atrs.append(_nan(self._atr.update(bar)))
        trend = self._at(self._trends, 0)
        trend_back = self._at(self._trends, self._slope)
        fast = self._at(self._fasts, 0)
        slow = self._at(self._slows, 0)

        if not in_position:
            trend_ok = (
                trend > trend_back
                and bar.close > trend
                and fast > slow
                and not math.isnan(trend)
                and not math.isnan(trend_back)
                and not math.isnan(fast)
                and not math.isnan(slow)
            )
            if not trend_ok:
                self._armed = False
                return None
            if bar.close < fast:
                self._armed = True
                return None
            if self._armed and bar.close > fast:
                self._armed = False
                return self._decide("ENTRY", "PULLBACK_RECLAIM_ABOVE_FAST_MEAN", close=bar.close)
            return None

        atr_previous = self._at(self._atrs, 1)
        stop_level = self.entry_price - float(self.params["stop_atr_multiple"]) * atr_previous
        if bar.close < stop_level:
            return self._decide("EXIT", "STOP_LOSS_ON_CLOSE", close=bar.close, stop=stop_level)
        previous_close = self._at(self._closes, 1)
        slow_previous = self._at(self._slows, 1)
        if previous_close < slow_previous:
            return self._decide("EXIT", "TREND_BREAK_ON_CLOSE", close=bar.close)
        return None


# --- A4: mean reversion conditioned on volatility and liquidity ------------------------


class MeanReversionMachine(MachineBase):
    """A two-sigma stretch below the mean, but only when volatility is low and the bar liquid."""

    name = "mean_reversion_vol_liq"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._mean = RollingSum(int(self.params["mean_hours"]))
        self._dev = RollingStdev(int(self.params["mean_hours"]))
        self._atr = Atr(int(self.params["atr_hours"]))
        self._rank = PercentileRank(int(self.params["percentile_window_hours"]))
        self._volume = VolumeMedian(int(self.params["volume_median_hours"]))
        self._closes: deque[float] = deque(maxlen=4)
        self._means: deque[float] = deque(maxlen=4)
        self._devs: deque[float] = deque(maxlen=4)
        self._ranks: deque[float] = deque(maxlen=4)
        self._atrs: deque[float] = deque(maxlen=4)
        self._volume_medians: deque[float] = deque(maxlen=4)
        self._entry_atr = float("nan")

    def notify_fill(self, kind: str, index: int, price: float) -> None:
        super().notify_fill(kind, index, price)
        if kind == "ENTRY":
            # the stop reads the ATR of the entry bar, which is the bar being closed now
            self._entry_atr = float("nan")

    def on_closed_bar(self, index: int, bar: Bar, *, in_position: bool) -> Decision | None:
        self._advance(index, bar, in_position)
        self._closes.append(bar.close)
        self._means.append(_nan(self._mean.update(bar.close)))
        self._devs.append(_nan(self._dev.update(bar.close)))
        atr_value = self._atr.update(bar)
        self._atrs.append(_nan(atr_value))
        self._ranks.append(_nan(self._rank.update(atr_value)))
        self._volume_medians.append(_nan(self._volume.update(bar.volume)))

        if in_position and math.isnan(self._entry_atr) and index == self.entry_index:
            self._entry_atr = _nan(atr_value)

        if not in_position:
            z = self._z(0)
            rank = self._at(self._ranks, 0)
            volume_median = self._at(self._volume_medians, 0)
            if (
                z <= float(self.params["z_entry"])
                and rank <= float(self.params["atr_percentile_max"])
                and bar.volume > float(self.params["volume_multiple_min"]) * volume_median
            ):
                return self._decide("ENTRY", "Z_STRETCH_LOW_VOL_LIQUID", z=z, rank=rank)
            return None

        held = index - int(self.entry_index if self.entry_index is not None else index)
        if held >= int(self.params["max_hold_hours"]):
            return self._decide("EXIT", "MAX_HOLD_REACHED", held=float(held))
        z_previous = self._z(1)
        if z_previous >= float(self.params["z_exit"]):
            return self._decide("EXIT", "MEAN_REACHED_ON_CLOSE", z=z_previous)
        stop_level = self.entry_price - float(self.params["atr_stop_multiple"]) * self._entry_atr
        if bar.close < stop_level:
            return self._decide("EXIT", "STOP_LOSS_ON_CLOSE", close=bar.close, stop=stop_level)
        return None

    def _z(self, back: int) -> float:
        deviation = self._at(self._devs, back)
        if not (deviation > 0.0):
            return float("nan")
        return (self._at(self._closes, back) - self._at(self._means, back)) / deviation


MACHINES: dict[str, type[MachineBase]] = {
    BreakoutMachine.name: BreakoutMachine,
    PullbackMachine.name: PullbackMachine,
    MeanReversionMachine.name: MeanReversionMachine,
}


def machine_for(name: str, params: dict[str, Any]) -> MachineBase:
    """The one construction site for a family's decision core."""
    try:
        machine = MACHINES[name]
    except KeyError:  # pragma: no cover - the caller's family registry is closed
        raise KeyError(f"no point-in-time machine for family {name!r}") from None
    return machine(params)


# --------------------------------------------------------------------------------------
# the driver: fills, marks and the audit that proves the ordering
# --------------------------------------------------------------------------------------


@dataclass
class _Open:
    """A filled entry that is waiting for its exit."""

    fill_index: int
    price: float
    rule: str
    signal_index: int
    signal_ms: int
    data_available_ms: int
    fill_ms: int


def _close_trade(
    opening: _Open,
    exit_index: int,
    exit_price: float,
    *,
    machine: MachineBase,
    bars: Sequence[Bar],
    rule: str,
    signal_index: int,
    is_mark: bool = False,
) -> dict[str, Any]:
    period = machine.period_ms()
    exit_signal_ms = bars[signal_index].ts_ms
    # A mark is a valuation, not an order: its price is the last *close*, which exists at
    # the end of its bar, so its earliest instant is the close and not the bar's open.
    exit_instant_ms = bars[exit_index].ts_ms + (period if is_mark else 0)
    return {
        "entry_ts_ms": bars[opening.fill_index].ts_ms,
        "exit_ts_ms": bars[exit_index].ts_ms,
        "entry_signal_ts_ms": opening.signal_ms,
        "exit_signal_ts_ms": exit_signal_ms,
        "entry_data_available_ms": opening.data_available_ms,
        "exit_data_available_ms": exit_signal_ms + period if not is_mark else exit_instant_ms,
        "entry_earliest_fill_ms": opening.fill_ms,
        "exit_earliest_fill_ms": exit_instant_ms,
        "entry_price": opening.price,
        "exit_price": float(exit_price),
        "gross_bps": (float(exit_price) / opening.price - 1.0) * 10_000.0,
        "bars_held": exit_index - opening.fill_index,
        "direction": "long",
        "entry_rule": opening.rule,
        "exit_rule": rule,
        "is_mark": bool(is_mark),
        "entry_signal_index": opening.signal_index,
        "exit_signal_index": signal_index,
        "entry_fill_index": opening.fill_index,
        "exit_fill_index": exit_index,
    }


def run_family(name: str, bars: Sequence[Bar], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Drive a family's machine over a series, resolving fills under the PIT contract.

    This is the batch path; the paper lane feeds the same machine one bar at a
    time through ``on_closed_bar``. Both end up calling ``_close_trade`` with the
    same arguments, so a trade produced by one is reproducible by the other.
    """
    machine = machine_for(name, params)
    trades: list[dict[str, Any]] = []
    opening: _Open | None = None
    pending: Decision | None = None
    last_exit_fill: int | None = None
    dropped_same_instant = 0
    dropped_beyond_window = 0

    for index, bar in enumerate(bars):
        # 1) a decision taken at the previous bar's close is executable now, at this open
        if pending is not None and pending.fill_index == index:
            if pending.kind == "ENTRY":
                opening = _Open(
                    fill_index=index,
                    price=bar.open,
                    rule=pending.rule,
                    signal_index=pending.signal_index,
                    signal_ms=bars[pending.signal_index].ts_ms,
                    data_available_ms=bars[pending.signal_index].ts_ms + machine.period_ms(),
                    fill_ms=bar.ts_ms,
                )
                machine.notify_fill("ENTRY", index, bar.open)
            else:
                assert opening is not None, "an EXIT decision without a filled entry"
                trades.append(
                    _close_trade(
                        opening,
                        index,
                        bar.open,
                        machine=machine,
                        bars=bars,
                        rule=pending.rule,
                        signal_index=pending.signal_index,
                    )
                )
                machine.notify_fill("EXIT", index, bar.open)
                opening = None
                last_exit_fill = index
            pending = None

        # 2) the machine observes the closed bar
        decision = machine.on_closed_bar(index, bar, in_position=opening is not None)
        if decision is None:
            continue
        if decision.fill_index >= len(bars):
            dropped_beyond_window += 1
            continue
        if (
            decision.kind == "ENTRY"
            and last_exit_fill is not None
            and decision.fill_index <= last_exit_fill
        ):
            dropped_same_instant += 1
            continue
        pending = decision

    if opening is not None:
        last = len(bars) - 1
        trades.append(
            _close_trade(
                opening,
                last,
                bars[last].close,
                machine=machine,
                bars=bars,
                rule="TERMINAL_MARK_AT_LAST_CLOSE",
                signal_index=last,
                is_mark=True,
            )
        )

    for trade in trades:
        trade["dropped_same_instant_entries"] = dropped_same_instant
        trade["dropped_beyond_window_decisions"] = dropped_beyond_window
    return trades


def audit_trade(trade: dict[str, Any]) -> list[str]:
    """Violations of the PIT contract in one trade row; empty means it holds."""
    violations: list[str] = []
    available = int(trade["entry_data_available_ms"])
    earliest = int(trade["entry_earliest_fill_ms"])
    fill = int(trade["entry_ts_ms"])
    if not available <= earliest:
        violations.append(f"entry: earliest fill {earliest} precedes availability {available}")
    if not earliest <= fill:
        violations.append(f"entry: fill {fill} precedes the earliest possible fill {earliest}")
    if int(trade["exit_ts_ms"]) < int(trade["entry_ts_ms"]):
        violations.append("exit precedes entry")
    if trade["is_mark"]:
        if trade["exit_rule"] != "TERMINAL_MARK_AT_LAST_CLOSE":
            violations.append("a mark must say it is the terminal mark")
        if int(trade["exit_data_available_ms"]) != int(trade["exit_earliest_fill_ms"]):
            violations.append("a mark is valued at the close, so its instant is that close's")
    else:
        available = int(trade["exit_data_available_ms"])
        earliest = int(trade["exit_earliest_fill_ms"])
        fill = int(trade["exit_ts_ms"])
        if not available <= earliest:
            violations.append(f"exit: earliest fill {earliest} precedes availability {available}")
        if not earliest <= fill:
            violations.append(f"exit: fill {fill} precedes the earliest possible fill {earliest}")
        if int(trade["exit_fill_index"]) <= int(trade["exit_signal_index"]):
            violations.append(
                "exit filled at or before its own signal bar: the same-bar close-to-open exploit"
            )
    if int(trade["entry_fill_index"]) <= int(trade["entry_signal_index"]):
        violations.append("entry filled at or before its own signal bar")
    return violations
