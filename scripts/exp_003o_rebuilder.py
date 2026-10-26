"""exp_003o_rebuilder — Builder B: the independent signal rebuilder of EXP-003O.

This module answers, for every evaluable instant of the frozen 003O calendar, what the rule
*says*, using its own code:

* its own minute reader and its own positional aggregation;
* its own EMA, RSI, ATR, MACD, Bollinger, momentum and volume-relative arithmetic, written
  from the specification in ``SIGNAL_SPECIFICATIONS.md``, not by calling the producer;
* its own lane-B state machines (breakout, pullback, mean reversion) and driver.

It imports the standard library, ``numpy`` and ``scripts/exp_003o_contract.py`` (cell ids,
states, writers, a bar dataclass, a digest helper). It imports, opens or greps nothing from
``trading_bot`` and never reads a published signal file. ``scripts/exp_003o_verify.py``
enforces that with an AST scan, a literal scan and a run under an audit hook.

Usage
-----
``python scripts/exp_003o_rebuilder.py --protocol design/PROTOCOL.json --out signals/independent_evaluations.jsonl.gz``
``python scripts/exp_003o_rebuilder.py --check-inputs``
``python scripts/exp_003o_rebuilder.py --truncate 900 --out .../independent_truncated.jsonl.gz``
``python scripts/exp_003o_rebuilder.py --fixtures fixtures --fixture-out fixtures/independent --protocol ...``
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    DATASET,
    MINUTE_MS,
    OUT,
    Bar,
    bar_bytes,
    read_json,
    sha256_file,
    utc_ms,
    window_digest,
)

WINDOW = 80
PRODUCER = "independent"

#: What a row's ``state`` may be. Kept next to the code that emits it so a typo cannot
#: create a state the comparator has never heard of.
SIGNAL = "SIGNAL"
NO_SIGNAL = "NO_SIGNAL"
NOT_READY = "NOT_READY"
NOT_EVALUABLE = "NOT_EVALUABLE"


# --------------------------------------------------------------------------------------
# data: own reader, own aggregation
# --------------------------------------------------------------------------------------


def read_minutes(path: Path) -> tuple[IntArray, FloatArray]:
    stamps: list[int] = []
    rows: list[list[float]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            stamps.append(int(row[0]))
            rows.append([float(value) for value in row[1:6]])
    return np.asarray(stamps, dtype=np.int64), np.asarray(rows, dtype=float)


def aggregate(stamps: IntArray, values: FloatArray, minutes_per_bar: int) -> dict[str, FloatArray]:
    """Positional aggregation of complete groups; a trailing partial group is dropped."""

    groups = len(stamps) // minutes_per_bar
    if groups == 0:
        raise ValueError("series shorter than one bar")
    usable = groups * minutes_per_bar
    cube = values[:usable].reshape(groups, minutes_per_bar, values.shape[1])
    return {
        "ts": stamps[:usable:minutes_per_bar].astype(np.int64),
        "open": cube[:, 0, 0].copy(),
        "high": cube[:, :, 1].max(axis=1),
        "low": cube[:, :, 2].min(axis=1),
        "close": cube[:, :, 3][:, -1].copy(),
        "volume": cube[:, :, 4].sum(axis=1),
    }


def cut_before(series: dict[str, FloatArray], instant_ms: int) -> dict[str, FloatArray]:
    mask = series["ts"] < instant_ms
    return {key: value[mask] for key, value in series.items()}


def to_bars(series: dict[str, FloatArray]) -> list[Bar]:
    return [
        Bar(
            ts_ms=int(series["ts"][index]),
            open=float(series["open"][index]),
            high=float(series["high"][index]),
            low=float(series["low"][index]),
            close=float(series["close"][index]),
            volume=float(series["volume"][index]),
        )
        for index in range(len(series["ts"]))
    ]


# --------------------------------------------------------------------------------------
# indicators, written from the specification
# --------------------------------------------------------------------------------------


def ema_last(windows: FloatArray, period: int) -> FloatArray:
    """EMA of each row, seeded with that row's first ``period`` values."""

    if windows.shape[1] < period:
        raise ValueError(f"ema({period}) over {windows.shape[1]} values")
    out: FloatArray = np.asarray(windows[:, :period].mean(axis=1), dtype=np.float64)
    weight = 2.0 / (period + 1.0)
    for column in range(period, windows.shape[1]):
        out = windows[:, column] * weight + out * (1.0 - weight)
    return out


def ema_series(windows: FloatArray, period: int) -> FloatArray:
    """The whole recursive EMA series of each row, aligned to its last used value."""

    length = windows.shape[1] - period + 1
    out = np.empty((windows.shape[0], length), dtype=float)
    out[:, 0] = windows[:, :period].mean(axis=1)
    weight = 2.0 / (period + 1.0)
    for column in range(period, windows.shape[1]):
        out[:, column - period + 1] = windows[:, column] * weight + out[:, column - period] * (
            1.0 - weight
        )
    return out


def rsi_last(windows: FloatArray, period: int = 14) -> FloatArray:
    deltas = np.diff(windows, axis=1)
    gains = np.clip(deltas, 0.0, None)
    losses = np.clip(-deltas, 0.0, None)
    average_gain = gains[:, :period].mean(axis=1)
    average_loss = losses[:, :period].mean(axis=1)
    for column in range(period, deltas.shape[1]):
        average_gain = (average_gain * (period - 1) + gains[:, column]) / period
        average_loss = (average_loss * (period - 1) + losses[:, column]) / period
    ratio = np.divide(
        average_gain, average_loss, out=np.zeros_like(average_gain), where=average_loss > 0
    )
    value = 100.0 - (100.0 / (1.0 + ratio))
    return np.where(average_loss == 0.0, 100.0, value)


def atr_last(high: FloatArray, low: FloatArray, close: FloatArray, period: int = 14) -> FloatArray:
    previous = np.concatenate((close[:, :1], close[:, :-1]), axis=1)
    span = np.maximum.reduce(
        [
            high - low,
            np.abs(high - previous),
            np.abs(low - previous),
        ]
    )
    ranges = span[:, 1:]
    out: FloatArray = np.asarray(ranges[:, :period].mean(axis=1), dtype=np.float64)
    for column in range(period, ranges.shape[1]):
        out = (out * (period - 1) + ranges[:, column]) / period
    return out


def bollinger_last(
    windows: FloatArray, period: int = 20, deviations: float = 2.0
) -> tuple[FloatArray, FloatArray, FloatArray]:
    tail = windows[:, -period:]
    middle = tail.mean(axis=1)
    width = np.sqrt(((tail - middle[:, None]) ** 2).mean(axis=1)) * deviations
    return middle + width, middle - width, middle


def macd_histogram(
    windows: FloatArray, fast: int = 12, slow: int = 26, signal_period: int = 9
) -> FloatArray:
    fast_series = ema_series(windows, fast)
    slow_series = ema_series(windows, slow)
    line = fast_series[:, slow - fast :] - slow_series
    signal_line = ema_series(line, signal_period)
    return line[:, -1] - signal_line[:, -1]


def momentum_last(windows: FloatArray, lookback: int = 10) -> FloatArray:
    return windows[:, -1] / windows[:, -lookback - 1] - 1.0


# --------------------------------------------------------------------------------------
# lane A: the six rules over the frozen 80-bar window
# --------------------------------------------------------------------------------------


def lane_a_states(
    family: str,
    close: FloatArray,
    high: FloatArray,
    low: FloatArray,
    volume: FloatArray,
) -> dict[str, Any]:
    """Per-row long/short masks for one family, computed from the window matrices."""

    rows = close.shape[0]
    atr = atr_last(high, low, close)
    usable = atr > 0.0
    long_mask = np.zeros(rows, dtype=bool)
    short_mask = np.zeros(rows, dtype=bool)

    if family == "ema_crossover":
        fast = ema_last(close, 9)
        slow = ema_last(close, 21)
        rsi = rsi_last(close)
        long_mask = usable & (fast > slow) & (rsi > 50.0)
        short_mask = usable & (fast < slow) & (rsi < 50.0)
    elif family == "momentum":
        histogram = macd_histogram(close)
        momentum = momentum_last(close)
        long_mask = usable & (histogram > 0.0) & (momentum > 0.005)
        short_mask = usable & (histogram < 0.0) & (momentum < -0.005)
    elif family == "breakout":
        channel_high = high[:, -21:-1].max(axis=1)
        channel_low = low[:, -21:-1].min(axis=1)
        relative = volume[:, -1] / volume[:, -21:-1].mean(axis=1)
        long_mask = usable & (close[:, -1] > channel_high) & (relative >= 1.5)
        short_mask = usable & (close[:, -1] < channel_low) & (relative >= 1.5)
    elif family == "mean_reversion":
        upper, lower, _ = bollinger_last(close)
        previous = close[:, -2]
        current = close[:, -1]
        long_mask = usable & (previous < lower) & (current > lower)
        short_mask = usable & (previous > upper) & (current < upper)
    elif family == "trend":
        fast = ema_last(close, 8)
        mid = ema_last(close, 21)
        slow = ema_last(close, 55)
        # the slope compares an EMA on the window with an EMA re-seeded on its 79-bar prefix
        slow_previous = ema_last(close[:, :-1], 55)
        slope = np.divide(
            slow - slow_previous,
            slow_previous,
            out=np.zeros_like(slow),
            where=slow_previous > 0.0,
        )
        gate = usable & (slow > 0.0) & (slow_previous > 0.0)
        long_mask = gate & (fast > mid) & (mid > slow) & (slope > 0.0005)
        short_mask = gate & (fast < mid) & (mid < slow) & (slope < -0.0005)
    elif family == "volatility":
        upper, lower, _ = bollinger_last(close)
        squeezed = np.ones(rows, dtype=bool)
        for offset in range(6, 0, -1):
            prefix_close = close[:, :-offset]
            prefix_high = high[:, :-offset]
            prefix_low = low[:, :-offset]
            middle = ema_last(prefix_close, 20)
            prefix_atr = atr_last(prefix_high, prefix_low, prefix_close, 10)
            inside = (upper < middle + 1.5 * prefix_atr) & (lower > middle - 1.5 * prefix_atr)
            squeezed = squeezed & inside
        current = close[:, -1]
        long_mask = usable & squeezed & (current > upper)
        short_mask = usable & squeezed & (current < lower)
    else:
        raise KeyError(f"no independent rule for family {family!r}")

    if bool((long_mask & short_mask).any()):
        raise AssertionError(f"{family}: a bar cannot be long and short at once")
    return {"long": long_mask, "short": short_mask}


def lane_a_rows(
    protocol: dict[str, Any],
    cell: dict[str, Any],
    symbol: str,
    series: dict[str, FloatArray],
) -> list[dict[str, Any]]:
    timeframe = str(cell["timeframe"])
    interval = int(protocol["timeframes_ms"][timeframe])
    count = len(series["ts"])
    parameter_hash = str(cell["parameter_hash"])
    rows: list[dict[str, Any]] = []
    bars = to_bars(series)

    masks: dict[str, Any] | None = None
    if count >= WINDOW:
        close = np.lib.stride_tricks.sliding_window_view(series["close"], WINDOW)
        high = np.lib.stride_tricks.sliding_window_view(series["high"], WINDOW)
        low = np.lib.stride_tricks.sliding_window_view(series["low"], WINDOW)
        volume = np.lib.stride_tricks.sliding_window_view(series["volume"], WINDOW)
        masks = lane_a_states(str(cell["family"]), close, high, low, volume)

    # The prefix digest grows bar by bar, so every row names exactly the bytes it could see:
    # a prefix for a NOT_READY instant, the 80-bar window for an evaluated one.
    running = hashlib.sha256()
    for index, bar in enumerate(bars):
        running.update(bar_bytes(bar))
        if index < WINDOW - 1 or masks is None:
            rows.append(
                _row(
                    cell,
                    symbol,
                    interval,
                    bar.ts_ms + interval,
                    NOT_READY,
                    None,
                    "WARMUP",
                    parameter_hash,
                    running.hexdigest(),
                    bars[0].ts_ms,
                    bar.ts_ms,
                    index + 1,
                )
            )
            continue
        row_index = index - (WINDOW - 1)
        if bool(masks["long"][row_index]):
            state, direction, reason = SIGNAL, "LONG", None
        elif bool(masks["short"][row_index]):
            state, direction, reason = SIGNAL, "SHORT", None
        else:
            state, direction, reason = NO_SIGNAL, None, "RULE_FALSE"
        rows.append(
            _row(
                cell,
                symbol,
                interval,
                bar.ts_ms + interval,
                state,
                direction,
                reason,
                parameter_hash,
                window_digest(bars[index - WINDOW + 1 : index + 1]),
                bars[index - WINDOW + 1].ts_ms,
                bar.ts_ms,
                WINDOW,
            )
        )
    return rows


# --------------------------------------------------------------------------------------
# lane B: own machines, own driver
# --------------------------------------------------------------------------------------


class _Ema:
    """EMA seeded with the mean of its first ``span`` values."""

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self.weight = 2.0 / (self.span + 1.0)
        self._seed: list[float] = []
        self._value: float | None = None

    def push(self, value: float) -> float | None:
        if self._value is None:
            self._seed.append(value)
            if len(self._seed) < self.span:
                return None
            self._value = sum(self._seed) / self.span
            return self._value
        self._value = value * self.weight + self._value * (1.0 - self.weight)
        return self._value


class _Atr:
    """EMA of true ranges; the first bar has no previous close."""

    def __init__(self, span: int) -> None:
        self._ema = _Ema(span)
        self._previous_close: float | None = None

    def push(self, bar: Bar) -> float | None:
        if self._previous_close is None:
            true_range = bar.high - bar.low
        else:
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - self._previous_close),
                abs(bar.low - self._previous_close),
            )
        self._previous_close = bar.close
        return self._ema.push(true_range)


class _Trailing:
    """Trailing sum / population stdev / extreme / median over a fixed bar count."""

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self._values: list[float] = []

    def push(self, value: float) -> float | None:
        self._values.append(value)
        return self._stat(self._values[-self.span :]) if len(self._values) >= self.span else None

    def _stat(self, window: list[float]) -> float | None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _median(self, window: list[float]) -> float:
        ordered = sorted(window)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0


class _Mean(_Trailing):
    def _stat(self, window: list[float]) -> float | None:
        return sum(window) / len(window)


class _Deviation(_Trailing):
    def _stat(self, window: list[float]) -> float | None:
        mean = sum(window) / len(window)
        return math.sqrt(sum((value - mean) ** 2 for value in window) / len(window))


class _Peak(_Trailing):
    def _stat(self, window: list[float]) -> float | None:
        return max(window)


class _Trough(_Trailing):
    def _stat(self, window: list[float]) -> float | None:
        return min(window)


class _VolumeMedian(_Trailing):
    """Median of the trailing volumes once at least two bars exist."""

    def push(self, value: float) -> float | None:
        self._values.append(value)
        if len(self._values) < 2:
            return None
        return self._median(self._values[-self.span :])


class _Percentile:
    """Rank of the newest value inside a trailing window, in 50 buckets.

    The bucket bounds are fixed by the first full window and never revisited; later values
    are clamped into the outermost bucket, exactly as the frozen producer's rank behaves.
    """

    def __init__(self, span: int, buckets: int = 50) -> None:
        self.span = int(span)
        self.buckets = int(buckets)
        self._warm: list[float] = []
        self._low: float | None = None
        self._width: float | None = None
        self._counts = [0] * self.buckets
        self._recent: deque[int] = deque(maxlen=self.span)
        self._dead = self.span <= 1

    def push(self, value: float | None) -> float | None:
        if self._dead or value is None or math.isnan(value):
            return None
        if self._low is None:
            self._warm.append(float(value))
            if len(self._warm) < self.span:
                return None
            low, high = min(self._warm), max(self._warm)
            if high <= low:
                self._dead = True
                return None
            self._low, self._width = low, (high - low) / self.buckets
            for item in self._warm:
                bucket = self._bucket(item)
                self._counts[bucket] += 1
                self._recent.append(bucket)
            self._warm = []
            return self._rank(self._recent[-1])
        bucket = self._bucket(float(value))
        if len(self._recent) == self.span:
            self._counts[self._recent[0]] -= 1
        self._recent.append(bucket)
        self._counts[bucket] += 1
        return self._rank(bucket)

    def _bucket(self, value: float) -> int:
        assert self._low is not None and self._width is not None
        raw = int((value - self._low) / self._width) if self._width > 0 else 0
        return min(self.buckets - 1, max(0, raw))

    def _rank(self, bucket: int) -> float:
        return (sum(self._counts[:bucket]) + 0.5 * self._counts[bucket]) / self.span


def _at(series: deque[float], back: int) -> float:
    return math.nan if len(series) <= back else series[-1 - back]


class _Machine:
    """Common bookkeeping: the bar being decided, the open position, the bar spacing."""

    name = "machine"

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        self.index = -1
        self.in_position = False
        self.entry_index: int | None = None
        self.entry_price = math.nan
        self._last_ts: int | None = None
        self._deltas: list[int] = []

    def period_ms(self) -> int:
        if not self._deltas:
            return 3_600_000
        return int(sorted(self._deltas)[len(self._deltas) // 2])

    def observe(self, index: int, bar: Bar, in_position: bool) -> None:
        if self.index >= 0 and index < self.index:
            raise ValueError(f"{self.name}: bar {index} arrived after {self.index}")
        self.index = index
        self.in_position = in_position
        if self._last_ts is not None and bar.ts_ms > self._last_ts:
            self._deltas.append(bar.ts_ms - self._last_ts)
        self._last_ts = bar.ts_ms

    def fill(self, kind: str, index: int, price: float) -> None:
        if kind == "ENTRY":
            self.entry_index, self.entry_price = index, float(price)
        else:
            self.entry_index, self.entry_price = None, math.nan

    def decide(self, index: int, bar: Bar, in_position: bool) -> tuple[str, str] | None:
        """Every machine answers the same question; the base one refuses to guess."""

        raise NotImplementedError(f"{self.name} has no rule")


class _Breakout(_Machine):
    """Close above the trailing channel, gated on the ATR percentile and the regime EMA."""

    name = "vol_regime_breakout"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._upper = _Peak(int(params["channel_hours"]))
        self._lower = _Trough(int(params["channel_hours"]))
        self._atr = _Atr(int(params["atr_hours"]))
        self._rank = _Percentile(int(params["percentile_window_hours"]))
        self._regime = _Ema(int(params["regime_ema_hours"]))
        self._closes: deque[float] = deque(maxlen=4)
        self._uppers: deque[float] = deque(maxlen=4)
        self._lowers: deque[float] = deque(maxlen=4)
        self._atrs: deque[float] = deque(maxlen=4)
        self._ranks: deque[float] = deque(maxlen=4)
        self._regimes: deque[float] = deque(maxlen=4)
        self._peak = math.nan

    def fill(self, kind: str, index: int, price: float) -> None:
        super().fill(kind, index, price)
        if kind == "ENTRY":
            self._peak = math.nan

    def decide(self, index: int, bar: Bar, in_position: bool) -> tuple[str, str] | None:
        self.observe(index, bar, in_position)
        self._closes.append(bar.close)
        upper = self._upper.push(bar.high)
        lower = self._lower.push(bar.low)
        atr = self._atr.push(bar)
        self._uppers.append(math.nan if upper is None else upper)
        self._lowers.append(math.nan if lower is None else lower)
        self._atrs.append(math.nan if atr is None else atr)
        rank = self._rank.push(atr)
        self._ranks.append(math.nan if rank is None else rank)
        regime = self._regime.push(bar.close)
        self._regimes.append(math.nan if regime is None else regime)

        if not in_position:
            previous_upper = _at(self._uppers, 1)
            rank = _at(self._ranks, 0)
            current_regime = _at(self._regimes, 0)
            if (
                index >= 1
                and bar.close > previous_upper
                and float(self.params["atr_percentile_min"])
                <= rank
                <= float(self.params["atr_percentile_max"])
                and bar.close > current_regime
            ):
                return ("ENTRY", "BREAKOUT_CLOSE_ABOVE_CHANNEL")
            return None

        if math.isnan(self._peak):
            self._peak = bar.close
        self._peak = max(self._peak, bar.close)
        if bar.close < self._peak - float(self.params["trail_atr_multiple"]) * _at(self._atrs, 1):
            return ("EXIT", "TRAILING_STOP_ON_CLOSE")
        if _at(self._closes, 1) < _at(self._lowers, 2):
            return ("EXIT", "CHANNEL_BREAK_ON_CLOSE")
        return None


class _Pullback(_Machine):
    """First close under the fast mean inside an up trend, then the reclaim."""

    name = "trend_pullback"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._trend = _Ema(int(params["trend_ema_hours"]))
        self._fast = _Ema(int(params["fast_ema_hours"]))
        self._slow = _Ema(int(params["slow_ema_hours"]))
        self._atr = _Atr(int(params["atr_hours"]))
        self._slope = int(params["trend_slope_hours"])
        self._closes: deque[float] = deque(maxlen=int(params["trend_ema_hours"]) + 2)
        self._trends: deque[float] = deque(maxlen=int(params["trend_slope_hours"]) + 2)
        self._fasts: deque[float] = deque(maxlen=4)
        self._slows: deque[float] = deque(maxlen=4)
        self._atrs: deque[float] = deque(maxlen=4)
        self._armed = False

    def decide(self, index: int, bar: Bar, in_position: bool) -> tuple[str, str] | None:
        self.observe(index, bar, in_position)
        self._closes.append(bar.close)
        trend = self._trend.push(bar.close)
        fast = self._fast.push(bar.close)
        slow = self._slow.push(bar.close)
        atr = self._atr.push(bar)
        self._trends.append(math.nan if trend is None else trend)
        self._fasts.append(math.nan if fast is None else fast)
        self._slows.append(math.nan if slow is None else slow)
        self._atrs.append(math.nan if atr is None else atr)

        current_trend = _at(self._trends, 0)
        past_trend = _at(self._trends, self._slope)
        current_fast = _at(self._fasts, 0)
        current_slow = _at(self._slows, 0)

        if not in_position:
            trend_ok = (
                current_trend > past_trend
                and bar.close > current_trend
                and current_fast > current_slow
                and not math.isnan(current_trend)
                and not math.isnan(past_trend)
                and not math.isnan(current_fast)
                and not math.isnan(current_slow)
            )
            if not trend_ok:
                self._armed = False
                return None
            if bar.close < current_fast:
                self._armed = True
                return None
            if self._armed and bar.close > current_fast:
                self._armed = False
                return ("ENTRY", "PULLBACK_RECLAIM_ABOVE_FAST_MEAN")
            return None

        stop = self.entry_price - float(self.params["stop_atr_multiple"]) * _at(self._atrs, 1)
        if bar.close < stop:
            return ("EXIT", "STOP_LOSS_ON_CLOSE")
        if _at(self._closes, 1) < _at(self._slows, 1):
            return ("EXIT", "TREND_BREAK_ON_CLOSE")
        return None


class _MeanReversion(_Machine):
    """A two-sigma flush below the mean, only when volatility is low and the bar liquid."""

    name = "mean_reversion_vol_liq"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._mean = _Mean(int(params["mean_hours"]))
        self._deviation = _Deviation(int(params["mean_hours"]))
        self._atr = _Atr(int(params["atr_hours"]))
        self._rank = _Percentile(int(params["percentile_window_hours"]))
        self._volume = _VolumeMedian(int(params["volume_median_hours"]))
        self._closes: deque[float] = deque(maxlen=4)
        self._means: deque[float] = deque(maxlen=4)
        self._deviations: deque[float] = deque(maxlen=4)
        self._ranks: deque[float] = deque(maxlen=4)
        self._atrs: deque[float] = deque(maxlen=4)
        self._volume_medians: deque[float] = deque(maxlen=4)
        self._entry_atr = math.nan

    def fill(self, kind: str, index: int, price: float) -> None:
        super().fill(kind, index, price)
        if kind == "ENTRY":
            self._entry_atr = math.nan

    def _z(self, back: int) -> float:
        deviation = _at(self._deviations, back)
        if not (deviation > 0.0):
            return math.nan
        return (_at(self._closes, back) - _at(self._means, back)) / deviation

    def decide(self, index: int, bar: Bar, in_position: bool) -> tuple[str, str] | None:
        self.observe(index, bar, in_position)
        self._closes.append(bar.close)
        mean = self._mean.push(bar.close)
        deviation = self._deviation.push(bar.close)
        atr = self._atr.push(bar)
        self._means.append(math.nan if mean is None else mean)
        self._deviations.append(math.nan if deviation is None else deviation)
        self._atrs.append(math.nan if atr is None else atr)
        rank = self._rank.push(atr)
        self._ranks.append(math.nan if rank is None else rank)
        median = self._volume.push(bar.volume)
        self._volume_medians.append(math.nan if median is None else median)

        if in_position and math.isnan(self._entry_atr) and index == self.entry_index:
            self._entry_atr = math.nan if atr is None else atr

        if not in_position:
            z = self._z(0)
            if (
                z <= float(self.params["z_entry"])
                and _at(self._ranks, 0) <= float(self.params["atr_percentile_max"])
                and bar.volume
                > float(self.params["volume_multiple_min"]) * _at(self._volume_medians, 0)
            ):
                return ("ENTRY", "Z_STRETCH_LOW_VOL_LIQUID")
            return None

        held = index - int(self.entry_index if self.entry_index is not None else index)
        if held >= int(self.params["max_hold_hours"]):
            return ("EXIT", "MAX_HOLD_REACHED")
        if self._z(1) >= float(self.params["z_exit"]):
            return ("EXIT", "MEAN_REACHED_ON_CLOSE")
        stop = self.entry_price - float(self.params["atr_stop_multiple"]) * self._entry_atr
        if bar.close < stop:
            return ("EXIT", "STOP_LOSS_ON_CLOSE")
        return None


MACHINES: dict[str, type[_Machine]] = {
    _Breakout.name: _Breakout,
    _Pullback.name: _Pullback,
    _MeanReversion.name: _MeanReversion,
}


def lane_b_rows(
    protocol: dict[str, Any],
    cell: dict[str, Any],
    symbol: str,
    bars: list[Bar],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One row per bar plus the trades the driver would have produced."""

    family = str(cell["family"])
    timeframe = str(cell["timeframe"])
    interval = int(protocol["timeframes_ms"][timeframe])
    warmup = int(protocol["evaluation_contract"]["lane_b_warmup_bars"][family])
    machine = MACHINES[family](dict(cell["parameters"]))
    parameter_hash = str(cell["parameter_hash"])

    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    pending: tuple[str, int, str, int] | None = None  # kind, fill index, rule, signal index
    opening: tuple[int, float, int, str] | None = None  # fill index, price, signal index, rule
    last_exit_fill: int | None = None
    dropped_same_instant = 0
    dropped_beyond_window = 0

    for index, bar in enumerate(bars):
        if pending is not None and pending[1] == index:
            kind, _, rule, signal_index = pending
            if kind == "ENTRY":
                opening = (index, bar.open, signal_index, rule)
                machine.fill("ENTRY", index, bar.open)
            else:
                assert opening is not None
                trades.append(
                    _trade(
                        opening,
                        index,
                        bar.open,
                        bars,
                        machine.period_ms(),
                        rule,
                        signal_index,
                        is_mark=False,
                    )
                )
                machine.fill("EXIT", index, bar.open)
                opening = None
                last_exit_fill = index
            pending = None

        decision = machine.decide(index, bar, in_position=opening is not None)
        digest.update(bar_bytes(bar))
        if index < warmup:
            state, direction, reason = NOT_READY, None, "WARMUP"
        elif decision is None:
            state = NO_SIGNAL
            direction = None
            reason = "IN_POSITION" if opening is not None else "RULE_FALSE"
        elif decision[0] == "ENTRY":
            state, direction, reason = SIGNAL, "LONG", "ENTRY_RULE"
        else:
            state, direction, reason = SIGNAL, "FLAT", "EXIT_RULE"

        rows.append(
            _row(
                cell,
                symbol,
                interval,
                bar.ts_ms + interval,
                state,
                direction,
                reason,
                parameter_hash,
                digest.hexdigest(),
                bars[0].ts_ms,
                bar.ts_ms,
                index + 1,
            )
        )

        if decision is None:
            continue
        fill_index = index + 1
        if fill_index >= len(bars):
            dropped_beyond_window += 1
            continue
        if decision[0] == "ENTRY" and last_exit_fill is not None and fill_index <= last_exit_fill:
            dropped_same_instant += 1
            continue
        pending = (decision[0], fill_index, decision[1], index)

    if opening is not None:
        last = len(bars) - 1
        trades.append(
            _trade(
                opening,
                last,
                bars[last].close,
                bars,
                machine.period_ms(),
                "TERMINAL_MARK_AT_LAST_CLOSE",
                last,
                is_mark=True,
            )
        )
    for trade in trades:
        trade["dropped_same_instant_entries"] = dropped_same_instant
        trade["dropped_beyond_window_decisions"] = dropped_beyond_window
    return rows, trades


def _trade(
    opening: tuple[int, float, int, str],
    exit_index: int,
    exit_price: float,
    bars: list[Bar],
    period: int,
    rule: str,
    signal_index: int,
    *,
    is_mark: bool,
) -> dict[str, Any]:
    fill_index, entry_price, entry_signal_index, entry_rule = opening
    exit_instant = bars[exit_index].ts_ms + (period if is_mark else 0)
    return {
        "entry_ts_ms": bars[fill_index].ts_ms,
        "exit_ts_ms": bars[exit_index].ts_ms,
        "entry_signal_ts_ms": bars[entry_signal_index].ts_ms,
        "exit_signal_ts_ms": bars[signal_index].ts_ms,
        "entry_data_available_ms": bars[entry_signal_index].ts_ms + period,
        "exit_data_available_ms": (bars[signal_index].ts_ms + period)
        if not is_mark
        else exit_instant,
        "entry_earliest_fill_ms": bars[fill_index].ts_ms,
        "exit_earliest_fill_ms": exit_instant,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "gross_bps": (float(exit_price) / entry_price - 1.0) * 10_000.0,
        "bars_held": exit_index - fill_index,
        "direction": "long",
        "entry_rule": entry_rule,
        "exit_rule": rule,
        "is_mark": bool(is_mark),
        "entry_signal_index": entry_signal_index,
        "exit_signal_index": signal_index,
        "entry_fill_index": fill_index,
        "exit_fill_index": exit_index,
    }


# --------------------------------------------------------------------------------------
# rows and the run
# --------------------------------------------------------------------------------------


def _row(
    cell: dict[str, Any],
    symbol: str,
    interval: int,
    decision_ms: int,
    state: str,
    direction: str | None,
    reason: str | None,
    parameter_hash: str,
    digest: str,
    window_first_ms: int,
    window_last_ms: int,
    window_bars: int,
) -> dict[str, Any]:
    if state in {NOT_READY, NOT_EVALUABLE} and reason is None:
        raise AssertionError(f"{state} requires a reason code")
    if state == SIGNAL and direction is None:
        raise AssertionError("SIGNAL requires a direction")
    if state != SIGNAL and direction is not None:
        raise AssertionError(f"{state} cannot carry a direction")
    return {
        "cell_id": str(cell["cell_id"]),
        "symbol": symbol,
        "timeframe": str(cell["timeframe"]),
        "decision_ms": int(decision_ms),
        "bar_open_ms": int(window_last_ms),
        "bar_close_ms": int(window_last_ms) + interval,
        "data_available_ms": int(window_last_ms) + interval,
        "state": state,
        "direction": direction,
        "reason": reason,
        "parameter_hash": parameter_hash,
        "input_snapshot_hash": digest,
        "window_first_ms": int(window_first_ms),
        "window_last_ms": int(window_last_ms),
        "window_bars": int(window_bars),
        "producer": PRODUCER,
    }


def check_inputs(protocol: dict[str, Any]) -> int:
    """Hash the three minute files against the digests the protocol inherited."""

    expected = protocol["source"]["dataset"]["symbols"]
    failed: list[str] = []
    for symbol, entry in sorted(expected.items()):
        path = DATASET / str(entry["file"])
        if not path.exists():
            failed.append(f"{symbol}: missing")
            continue
        digest = sha256_file(path)
        if digest != entry["sha256_expected"] or path.stat().st_size != entry["bytes_expected"]:
            failed.append(f"{symbol}: {digest[:12]} != {str(entry['sha256_expected'])[:12]}")
    if failed:
        for item in failed:
            print(f"[003o-rebuild] BLOCKED — {item}", file=sys.stderr)
        return 3
    print(f"[003o-rebuild] inputs OK — {len(expected)}/3 digests match the protocol")
    return 0


def build_series(
    protocol: dict[str, Any],
    symbol: str,
    timeframe: str,
    truncate: int | None,
    minutes: tuple[IntArray, FloatArray] | None = None,
) -> dict[str, FloatArray]:
    """One symbol at one timeframe, cut before the holdout; minutes are read once."""

    holdout_ms = utc_ms(protocol["holdout"]["start_utc"])
    if minutes is None:
        entry = protocol["source"]["dataset"]["symbols"][symbol]
        minutes = read_minutes(DATASET / str(entry["file"]))
    stamps, values = minutes
    series = aggregate(stamps, values, int(protocol["timeframes_ms"][timeframe]) // MINUTE_MS)
    series = cut_before(series, holdout_ms)
    if truncate is not None:
        series = {key: value[:truncate] for key, value in series.items()}
    return series


def run(
    protocol: dict[str, Any], truncate: int | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cells = list(protocol["cells"])
    symbols = [str(symbol) for symbol in protocol["symbols"]]
    timeframes = sorted({str(cell["timeframe"]) for cell in cells})
    cache: dict[tuple[str, str], dict[str, FloatArray]] = {}
    for symbol in symbols:
        entry = protocol["source"]["dataset"]["symbols"][symbol]
        minutes = read_minutes(DATASET / str(entry["file"]))
        for timeframe in timeframes:
            cache[(symbol, timeframe)] = build_series(
                protocol, symbol, timeframe, truncate, minutes
            )
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for cell in cells:
        for symbol in symbols:
            series = cache[(symbol, str(cell["timeframe"]))]
            if cell["lane"] == "A":
                rows.extend(lane_a_rows(protocol, cell, symbol, series))
            else:
                cell_rows, cell_trades = lane_b_rows(protocol, cell, symbol, to_bars(series))
                rows.extend(cell_rows)
                for trade in cell_trades:
                    trades.append({"cell_id": cell["cell_id"], "symbol": symbol, **trade})
    return rows, trades


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as handle,
        gzip.GzipFile(fileobj=handle, mode="wb", compresslevel=9, mtime=0) as stream,
    ):
        for row in rows:
            stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
                + b"\n"
            )


def run_fixtures(protocol: dict[str, Any], fixtures: Path, out: Path) -> int:
    """Evaluate the frozen synthetic series with the same code the real calendar uses."""

    out.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in fixtures.glob("*.json") if path.name != "FIXTURE_MANIFEST.json")
    if not files:
        print(f"[003o-rebuild] FAIL — no fixture in {fixtures}", file=sys.stderr)
        return 4
    for path in files:
        payload = read_json(path)
        cell = next(
            (item for item in protocol["cells"] if item["cell_id"] == payload["cell_id"]), None
        )
        if cell is None:
            print(
                f"[003o-rebuild] FAIL — fixture {path.name} names an unknown cell", file=sys.stderr
            )
            return 5
        bars = [
            Bar(
                ts_ms=int(bar["ts_ms"]),
                open=float(bar["open"]),
                high=float(bar["high"]),
                low=float(bar["low"]),
                close=float(bar["close"]),
                volume=float(bar["volume"]),
            )
            for bar in payload["bars"]
        ]
        series = {
            "ts": np.asarray([bar.ts_ms for bar in bars], dtype=np.int64),
            "open": np.asarray([bar.open for bar in bars], dtype=float),
            "high": np.asarray([bar.high for bar in bars], dtype=float),
            "low": np.asarray([bar.low for bar in bars], dtype=float),
            "close": np.asarray([bar.close for bar in bars], dtype=float),
            "volume": np.asarray([bar.volume for bar in bars], dtype=float),
        }
        if cell["lane"] == "A":
            rows = lane_a_rows(protocol, cell, payload["fixture_id"], series)
        else:
            rows, _ = lane_b_rows(protocol, cell, payload["fixture_id"], bars)
        write_rows(out / f"{payload['fixture_id']}.jsonl.gz", rows)
        signals = sum(1 for row in rows if row["state"] == SIGNAL)
        print(f"[003o-rebuild] fixture {payload['fixture_id']}: rows={len(rows)} signals={signals}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O independent signal rebuilder")
    parser.add_argument("--protocol", default=str(OUT / "design" / "PROTOCOL.json"))
    parser.add_argument("--out", default=str(OUT / "signals" / "independent_evaluations.jsonl.gz"))
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument("--truncate", type=int, default=None)
    parser.add_argument("--fixtures", type=Path, default=None)
    parser.add_argument("--fixture-out", type=Path, default=None)
    args = parser.parse_args(argv)

    protocol = read_json(Path(args.protocol))
    if args.check_inputs:
        return check_inputs(protocol)
    if args.fixtures is not None:
        if args.fixture_out is None:
            print("[003o-rebuild] FAIL — --fixtures needs --fixture-out", file=sys.stderr)
            return 2
        return run_fixtures(protocol, args.fixtures, args.fixture_out)

    rows, trades = run(protocol, args.truncate)
    write_rows(Path(args.out), rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    print(
        f"[003o-rebuild] rows={len(rows)} states={sorted(counts.items())} "
        f"trades={len(trades)} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
