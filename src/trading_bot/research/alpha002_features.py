"""ALPHA-002 — the point-in-time feature engine for the derivatives campaign.

ALPHA-002 asks a question that only makes sense if the answer is measured
honestly: *does information about market participants add an effect that price
alone did not?*  The information is not price data.  Open interest, aggressor
volume, published positioning and funding are published by the venue on their own
clocks, with their own publication lags, and a feature engine that quietly reads
a bucket before it closed will manufacture an edge out of nothing.

So this module is deliberately boring about time.  Every derived value carries the
timestamps that produced it:

* ``event_ms``      — the timestamp the venue stamps on the newest source bucket.
* ``available_ms``  — when that newest source bucket became usable.  A periodic
  ``/futures/data/*`` bucket is a *statistic over an interval*, so it is only
  knowable once the interval closes: ``available = event + period``.  A settled
  funding rate is knowable at its ``fundingTime``.  A price bar is knowable at its
  close.
* ``decision_ms``   — the instant the rule is allowed to act, i.e. the close of the
  entry bar.

The invariant this module exists to guarantee is ``available_ms <= decision_ms``
for *every* row it emits, so a decision can never see a bucket that had not
finished when it was taken.  Rows that cannot be evaluated because a required
source is missing are flagged rather than silently filled.

Causality, explicitly:

* rolling windows are trailing (``values[i-window:i]``), never centred and never
  full-sample;
* percentiles are computed inside the trailing window ending at the newest usable
  bucket, so a percentile can never be informed by a value that came later;
* the forward return read by the experiment is the *next* bar and is the only
  forward-looking quantity in the campaign — it is the label, never an input.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ATR_WINDOW",
    "FEATURE_CONFIG",
    "FEATURE_NAMES",
    "MIN_POSITIONING_OBSERVATIONS",
    "MIN_VOL_REGIME_OBSERVATIONS",
    "MOMENTUM_WINDOW",
    "POSITIONING_PCTILE_WINDOW",
    "REQUIRED_FEATURES",
    "VOL_REGIME_BASELINE_WINDOW",
    "VOL_REGIME_SHORT_WINDOW",
    "build_feature_rows",
    "feature_version",
    "period_ms",
    "trailing_percentile",
]

# --------------------------------------------------------------------------- #
# §0 — frozen construction constants
# --------------------------------------------------------------------------- #
#
# These are *feature construction* parameters, not hypothesis thresholds.  They
# were fixed before any ALPHA-002 result was computed, chosen as conventional,
# non-fitted values, and they are part of ``feature_version()`` so a later change
# is visible as a version change rather than as a silent re-derivation.

#: Trailing bars used for the average true range.
ATR_WINDOW = 14

#: Trailing bars used for the short-horizon momentum term.
MOMENTUM_WINDOW = 3

#: Trailing bars used for the positioning percentile.
POSITIONING_PCTILE_WINDOW = 288

#: Minimum observations before a percentile is reported at all.  A percentile of
#: five values is noise, not a crowding measure.
MIN_POSITIONING_OBSERVATIONS = 72

#: Short and baseline windows for the 1h volatility regime, in 1h bars.
VOL_REGIME_SHORT_WINDOW = 24
VOL_REGIME_BASELINE_WINDOW = 168
MIN_VOL_REGIME_OBSERVATIONS = 72

_PERIOD_MS: dict[str, int] = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}

#: The exact feature names a row exposes.  The preregistration lists these ten and
#: a hypothesis may read nothing else.
FEATURE_NAMES: tuple[str, ...] = (
    "ret_z",
    "atr_pct",
    "oi_chg",
    "oi_accel",
    "taker_imbalance",
    "funding",
    "ls_global_pctile",
    "ls_top_position_pctile",
    "momentum_delta",
    "vol_regime",
)

#: Which features each preregistered signal actually reads.  A row missing any of
#: them is *not a decision* for that signal — it is dropped and counted, never
#: imputed.  Keeping this beside the feature engine (rather than inside the frozen
#: registry) means the registry stays the single declarative source and this stays
#: an executable restatement of it, checked by tests.
REQUIRED_FEATURES: dict[str, tuple[str, ...]] = {
    "A2-H01": ("ret_z", "oi_chg", "taker_imbalance", "funding"),
    "A2-H02": ("funding", "ls_global_pctile", "ls_top_position_pctile", "momentum_delta"),
    "A2-H03": ("ret_z", "oi_chg", "taker_imbalance"),
    "A2-NT-01": ("ret_z", "oi_chg"),
    "A2-NT-02": ("ret_z", "oi_chg"),
}

#: The declarative description of the engine, digestible and reportable.
FEATURE_CONFIG: dict[str, Any] = {
    "atr_window": ATR_WINDOW,
    "momentum_window": MOMENTUM_WINDOW,
    "positioning_pctile_window": POSITIONING_PCTILE_WINDOW,
    "min_positioning_observations": MIN_POSITIONING_OBSERVATIONS,
    "vol_regime_short_window": VOL_REGIME_SHORT_WINDOW,
    "vol_regime_baseline_window": VOL_REGIME_BASELINE_WINDOW,
    "min_vol_regime_observations": MIN_VOL_REGIME_OBSERVATIONS,
    "derivatives_availability": "available = bucket_start + period (a bucket is a statistic over its interval)",
    "funding_availability": "available = fundingTime (the rate is settled at that instant)",
    "price_availability": "available = bar open + period (a bar is knowable at its close)",
    "percentile_definition": "midrank share of the trailing window at or below the newest usable value",
    "zero_denominator_policy": "a flow or range feature whose denominator is zero is undefined, not zero",
    "missing_observation_policy": "a row missing a required source is dropped for that signal, never imputed",
}


def feature_version() -> str:
    """Digest of the frozen construction constants, for the run manifest."""
    payload = json.dumps(FEATURE_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def period_ms(period: str) -> int:
    if period not in _PERIOD_MS:
        raise ValueError(f"unsupported period: {period}")
    return _PERIOD_MS[period]


# --------------------------------------------------------------------------- #
# §1 — causality primitives
# --------------------------------------------------------------------------- #


def _index_at_or_before(keys: Sequence[int], limit_ms: int) -> int | None:
    """Index of the newest key ``<= limit_ms``, or ``None``."""
    position = bisect_right(keys, limit_ms)
    return position - 1 if position > 0 else None


def _newest_closed_bucket(
    starts: Sequence[int], decision_ms: int, period: str
) -> int | None:
    """Index of the newest bucket that had *finished* by ``decision_ms``.

    The venue stamps a periodic derivative bucket with the *start* of its
    interval; the value is a statistic over that whole interval, so it is only
    knowable once the interval closes.
    """
    return _index_at_or_before(starts, decision_ms - period_ms(period))


def trailing_percentile(values: Sequence[float]) -> float:
    """Midrank percentile of the newest value inside a trailing window.

    Ties are split, so a flat series returns 0.5 rather than 1.0.  Returns ``nan``
    for an empty window; callers guard on the minimum observation count.
    """
    if not values:
        return float("nan")
    current = values[-1]
    below = sum(1 for value in values if value < current)
    equal = sum(1 for value in values if value == current)
    return (below + 0.5 * equal) / len(values)


def _stdev(values: Sequence[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


# --------------------------------------------------------------------------- #
# §2 — the row builder
# --------------------------------------------------------------------------- #


def _price_features(bars: Sequence[Sequence[float]], index: int) -> dict[str, float | None]:
    """Price features from bars ``[0, index]`` inclusive.  Nothing later is read."""
    out: dict[str, float | None] = {
        "ret_z": None,
        "atr_pct": None,
        "momentum_delta": None,
    }
    if index < 1:
        return out
    close = float(bars[index][4])
    previous_close = float(bars[index - 1][4])
    if previous_close <= 0.0:
        return out

    if index >= ATR_WINDOW:
        true_ranges: list[float] = []
        for position in range(index - ATR_WINDOW + 1, index + 1):
            high = float(bars[position][2])
            low = float(bars[position][3])
            prior = float(bars[position - 1][4])
            true_ranges.append(max(high - low, abs(high - prior), abs(low - prior)))
        atr = statistics.fmean(true_ranges)
        if close > 0.0 and atr > 0.0:
            atr_pct = atr / close
            out["atr_pct"] = atr_pct
            out["ret_z"] = (close / previous_close - 1.0) / atr_pct

    if index >= MOMENTUM_WINDOW + 1:
        base = float(bars[index - MOMENTUM_WINDOW][4])
        prior_base = float(bars[index - MOMENTUM_WINDOW - 1][4])
        if base > 0.0 and prior_base > 0.0:
            momentum = close / base - 1.0
            momentum_prior = previous_close / prior_base - 1.0
            out["momentum_delta"] = momentum - momentum_prior
    return out


def _derivatives_features(
    *,
    decision_ms: int,
    period: str,
    oi: Sequence[float],
    oi_starts: Sequence[int],
    taker: Sequence[tuple[float, float]],
    taker_starts: Sequence[int],
    ls_global: Sequence[float],
    ls_global_starts: Sequence[int],
    ls_top_position: Sequence[float],
    ls_top_position_starts: Sequence[int],
    funding: Sequence[tuple[int, float]],
) -> dict[str, float | None]:
    """Derivative features from buckets that had closed by ``decision_ms``."""
    out: dict[str, float | None] = {
        "oi_chg": None,
        "oi_accel": None,
        "taker_imbalance": None,
        "funding": None,
        "ls_global_pctile": None,
        "ls_top_position_pctile": None,
    }
    available_ms = decision_ms
    event_ms = decision_ms
    step = period_ms(period)

    oi_index = _newest_closed_bucket(oi_starts, decision_ms, period)
    if oi_index is not None:
        available_ms = max(available_ms, oi_starts[oi_index] + step)
        event_ms = max(event_ms, oi_starts[oi_index])
        current = oi[oi_index]
        if oi_index >= 1 and oi[oi_index - 1] > 0.0:
            oi_change = current / oi[oi_index - 1] - 1.0
            out["oi_chg"] = oi_change
            if oi_index >= 2 and oi[oi_index - 2] > 0.0:
                prior = oi[oi_index - 1] / oi[oi_index - 2] - 1.0
                out["oi_accel"] = oi_change - prior

    taker_index = _newest_closed_bucket(taker_starts, decision_ms, period)
    if taker_index is not None:
        available_ms = max(available_ms, taker_starts[taker_index] + step)
        event_ms = max(event_ms, taker_starts[taker_index])
        buy, sell = taker[taker_index]
        total = buy + sell
        # Zero denominator policy: an interval with no executed volume has no
        # aggressor skew.  Undefined, not zero.
        if total > 0.0:
            out["taker_imbalance"] = (buy - sell) / total

    for name, values, starts in (
        ("ls_global_pctile", ls_global, ls_global_starts),
        ("ls_top_position_pctile", ls_top_position, ls_top_position_starts),
    ):
        index = _newest_closed_bucket(starts, decision_ms, period)
        if index is None:
            continue
        available_ms = max(available_ms, starts[index] + step)
        event_ms = max(event_ms, starts[index])
        if index + 1 < MIN_POSITIONING_OBSERVATIONS:
            continue
        window = values[max(0, index - POSITIONING_PCTILE_WINDOW + 1) : index + 1]
        out[name] = trailing_percentile(window)

    funding_index = _index_at_or_before([stamp for stamp, _ in funding], decision_ms)
    if funding_index is not None:
        stamp, rate = funding[funding_index]
        available_ms = max(available_ms, stamp)
        event_ms = max(event_ms, stamp)
        out["funding"] = rate

    out["_available_ms"] = float(available_ms)
    out["_event_ms"] = float(event_ms)
    return out


def _vol_regime(
    regime_bars: Sequence[Sequence[float]], decision_ms: int, period: str = "1h"
) -> tuple[float | None, int]:
    """1h volatility regime: +1 expanding, -1 contracting, ``None`` if undefined.

    Computed from the most recent *closed* 1h bar, using trailing windows only.
    The regime is context reported beside a result, never a filter applied to one.
    """
    starts = [int(bar[0]) for bar in regime_bars]
    index = _newest_closed_bucket(starts, decision_ms, period)
    if index is None or index < MIN_VOL_REGIME_OBSERVATIONS:
        return None, -1
    closes = [float(bar[4]) for bar in regime_bars]
    returns: list[float] = []
    for position in range(1, index + 1):
        prior = closes[position - 1]
        if prior > 0.0:
            returns.append(closes[position] / prior - 1.0)
    if len(returns) < MIN_VOL_REGIME_OBSERVATIONS:
        return None, -1
    short = returns[-VOL_REGIME_SHORT_WINDOW:]
    baseline = returns[-VOL_REGIME_BASELINE_WINDOW:]
    short_vol = _stdev(short)
    baseline_vol = _stdev(baseline)
    if short_vol <= 0.0 or baseline_vol <= 0.0:
        return None, index
    return (1.0 if short_vol > baseline_vol else -1.0), index


def build_feature_rows(
    *,
    symbol: str,
    timeframe: str,
    price_bars: Sequence[Sequence[float]],
    oi: Mapping[int, float],
    taker: Mapping[int, tuple[float, float]],
    funding: Sequence[tuple[int, float]],
    ls_global: Mapping[int, float],
    ls_top_position: Mapping[int, float],
    regime_bars: Sequence[Sequence[float]],
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Emit one point-in-time feature row per closed entry bar.

    ``oi``, ``taker``, ``ls_global`` and ``ls_top_position`` are keyed by bucket
    start at ``timeframe`` granularity; ``funding`` is a sorted ``(time, rate)``
    sequence.  ``price_bars`` and ``regime_bars`` are ``[open, o, h, l, c, v]``.

    A row is emitted when every source timestamp it used is at or before the bar's
    close.  Rows whose required sources are missing carry ``None`` in those feature
    slots and are dropped by the signal that needs them, not imputed.
    """
    oi_starts = sorted(oi)
    oi_values = [float(oi[stamp]) for stamp in oi_starts]
    taker_starts = sorted(taker)
    taker_values = [(float(taker[stamp][0]), float(taker[stamp][1])) for stamp in taker_starts]
    global_starts = sorted(ls_global)
    global_values = [float(ls_global[stamp]) for stamp in global_starts]
    top_starts = sorted(ls_top_position)
    top_values = [float(ls_top_position[stamp]) for stamp in top_starts]
    funding_sorted = sorted(funding)

    step = period_ms(timeframe)
    rows: list[dict[str, Any]] = []
    for index, bar in enumerate(price_bars):
        bar_open_ms = int(bar[0])
        decision_ms = bar_open_ms + step
        if start_ms is not None and decision_ms < start_ms:
            continue
        if end_ms is not None and decision_ms > end_ms:
            continue

        row: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "bar_index": index,
            "bar_open_ms": bar_open_ms,
            "decision_ms": decision_ms,
            "close": float(bar[4]),
        }
        row.update(_price_features(price_bars, index))
        row.update(
            _derivatives_features(
                decision_ms=decision_ms,
                period=timeframe,
                oi=oi_values,
                oi_starts=oi_starts,
                taker=taker_values,
                taker_starts=taker_starts,
                ls_global=global_values,
                ls_global_starts=global_starts,
                ls_top_position=top_values,
                ls_top_position_starts=top_starts,
                funding=funding_sorted,
            )
        )
        available_ms = int(row.pop("_available_ms"))
        event_ms = int(row.pop("_event_ms"))
        regime, _ = _vol_regime(regime_bars, decision_ms)
        row["vol_regime"] = regime
        row["event_ms"] = event_ms
        row["available_ms"] = available_ms
        # The one invariant this module exists to guarantee.
        row["point_in_time_ok"] = available_ms <= decision_ms
        rows.append(row)
    return rows
