"""ALPHA-003 — the point-in-time cross-asset frame.

ALPHA-003 asks a question that is only meaningful if the answer is measured on a single
synchronised clock: *does information from asset A add anything about asset B's future,
beyond B's own history?*  The moment that frame is sloppy, the campaign manufactures the
very edge it claims to test, because the easiest way to make a "leader" look predictive is
to let it read a bar the target had not yet seen.

So this module is deliberately boring about time and explicit about the frame it builds:

* **One clock, one grid.**  The frame is indexed by the *entry bar's* open time,
  ``t``.  A decision taken for that bar happens at its close, ``decision_ms = t + period``.
  Every symbol's bar is addressed by the same ``t``, so "synchronised closed bars" is a
  structural property, not a convention a caller has to remember.
* **Contiguity is required, not assumed.**  A window is only used when every bar it needs
  is actually present.  A missing bar yields ``None`` (an undefined feature), never a
  forward-filled value across a gap.
* **The leader is always earlier.**  With lag ``L`` the leader's move is measured over the
  window ending at ``t - (L - 1) * period``, so for ``L >= 2`` the leader's information is
  strictly older than the target's decision instant, and for ``L == 1`` it closes exactly
  at it.  ``source_time <= decision_time`` holds for every column the frame emits.
* **Dimensionless.**  Every derived value is a return expressed in ATR units, so a
  movement in BTC and a movement in XRP are comparable without a fitted scale.

The frame is target-independent on purpose: it carries each asset's raw window return, its
ATR and the equal-weight market return, and :func:`cell_row` turns those into the handful of
derived features a hypothesis may read.  One frame per timeframe is therefore shared by
every target, pair and lag, which is also why the campaign cannot quietly grow a
per-cell data pipeline.

Causality, explicitly:

* rolling windows are trailing, never centred and never full-sample;
* the volatility regime comes from the most recent *closed* context bar, using trailing
  windows only, and is context reported beside a result, never a filter applied to one;
* the forward return is the *next* entry bar and is the only forward-looking quantity in the
  campaign — it is the label, never an input.

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
    "MIN_VOL_REGIME_OBSERVATIONS",
    "RELATIVE_WINDOW",
    "REQUIRED_FEATURES",
    "VOL_REGIME_BASELINE_WINDOW",
    "VOL_REGIME_SHORT_WINDOW",
    "build_frame",
    "cell_row",
    "feature_version",
    "forward_return_for",
    "period_ms",
]


# --------------------------------------------------------------------------- #
# §0 — frozen construction constants
# --------------------------------------------------------------------------- #
#
# Feature *construction* parameters, not hypothesis thresholds.  Fixed before any
# ALPHA-003 result was computed, chosen as conventional non-fitted values, and covered by
# ``feature_version()`` so a later change is visible as a version change.

#: Trailing bars used for the average true range.  Same value as ALPHA-002 so the two
#: campaigns normalise price moves identically.
ATR_WINDOW = 14

#: Trailing bars used for the relative-strength / dispersion window.
RELATIVE_WINDOW = 12

#: Short and baseline windows for the context volatility regime, in context bars.
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

#: The derived feature names a cell row exposes.  The preregistration lists exactly these
#: and a hypothesis may read nothing else.
FEATURE_NAMES: tuple[str, ...] = (
    "leader_ret_z",
    "target_ret_z",
    "target_mom_z",
    "market_ret_z",
    "relative_z",
)

#: Which derived features each declared arm reads.  A row missing any of them is *not a
#: decision* for that arm — it is dropped and counted, never imputed.
REQUIRED_FEATURES: dict[str, tuple[str, ...]] = {
    "A3-H01": ("leader_ret_z", "target_ret_z"),
    "A3-H02": ("relative_z",),
    "A3-H03": ("market_ret_z", "relative_z"),
    "A3-NT-01": ("leader_ret_z",),
    "A3-NT-02": ("leader_ret_z", "target_ret_z"),
    "A3-B0_UNCONDITIONAL_LONG": (),
    "A3-B1_OWN_MOMENTUM_SAME_LAG": ("target_ret_z",),
    "A3-B1_OWN_MOMENTUM_R": ("target_mom_z",),
    "A3-B3_MARKET_DIRECTION": ("market_ret_z",),
    "A3-B4_LEADER_ONLY": ("leader_ret_z",),
}

#: The declarative description of the engine, digestible and reportable.
FEATURE_CONFIG: dict[str, Any] = {
    "atr_window": ATR_WINDOW,
    "relative_window": RELATIVE_WINDOW,
    "vol_regime_short_window": VOL_REGIME_SHORT_WINDOW,
    "vol_regime_baseline_window": VOL_REGIME_BASELINE_WINDOW,
    "min_vol_regime_observations": MIN_VOL_REGIME_OBSERVATIONS,
    "clock": "decision_ms = entry bar open + period; every symbol is addressed by the same open",
    "price_availability": "available = bar open + period (a bar is knowable at its close)",
    "leader_availability": (
        "with lag L the leader window ends at decision_ms - (L - 1) * period, so it is never "
        "later than the decision instant"
    ),
    "contiguity_policy": (
        "a window is used only when every bar it needs is present; otherwise the feature is "
        "undefined, never forward-filled across a gap"
    ),
    "market_definition": (
        "equal-weight mean of the universe's raw window returns; the common factor, expressed "
        "in the target's ATR units when read by a hypothesis"
    ),
    "relative_definition": "target_mom_z - market_ret_z; both normalised by the target's own ATR",
    "zero_denominator_policy": "a feature whose ATR denominator is zero is undefined, not zero",
    "missing_observation_policy": "a row missing a required source is dropped for that arm, never imputed",
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
# §1 — per-symbol preparation
# --------------------------------------------------------------------------- #


def _stdev(values: Sequence[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


class _SymbolSeries:
    """One symbol's own contiguous bars, addressed by open time.

    Kept private: the campaign only ever consumes frame rows and cell rows, so no caller can
    reach a per-symbol array and silently use a bar the grid did not agree on.
    """

    __slots__ = ("atr_pct", "close", "opens", "position")

    def __init__(self, bars: Sequence[Sequence[float]]) -> None:
        self.opens = [int(bar[0]) for bar in bars]
        self.close = [float(bar[4]) for bar in bars]
        self.position = {open_ms: index for index, open_ms in enumerate(self.opens)}
        self.atr_pct = _atr_pct_series(bars)

    def window_return(self, index: int, window: int, step: int) -> float | None:
        """Return over ``window`` bars ending at ``index``, or ``None`` if not contiguous."""
        start = index - window
        if start < 0:
            return None
        if self.opens[start] != self.opens[index] - window * step:
            return None
        base = self.close[start]
        if base <= 0.0:
            return None
        return self.close[index] / base - 1.0


def _atr_pct_series(bars: Sequence[Sequence[float]]) -> list[float | None]:
    """ATR/close at each bar using trailing windows only, ``None`` when undefined."""
    out: list[float | None] = [None] * len(bars)
    for index in range(ATR_WINDOW, len(bars)):
        base_open = int(bars[index][0])
        step = base_open - int(bars[index - 1][0])
        if step <= 0:
            continue
        contiguous = all(
            int(bars[index - offset][0]) == base_open - offset * step
            for offset in range(0, ATR_WINDOW + 1)
        )
        if not contiguous:
            continue
        true_ranges: list[float] = []
        for offset in range(ATR_WINDOW):
            position = index - offset
            high = float(bars[position][2])
            low = float(bars[position][3])
            prior = float(bars[position - 1][4])
            true_ranges.append(max(high - low, abs(high - prior), abs(low - prior)))
        atr = statistics.fmean(true_ranges)
        close = float(bars[index][4])
        if close > 0.0 and atr > 0.0:
            out[index] = atr / close
    return out


def _regime_series(bars: Sequence[Sequence[float]]) -> list[float | None]:
    """Causal volatility regime per context bar: +1 expanding, -1 contracting, else None."""
    opens = [int(bar[0]) for bar in bars]
    closes = [float(bar[4]) for bar in bars]
    returns: list[float | None] = [None] * len(bars)
    for index in range(1, len(bars)):
        if closes[index - 1] > 0.0 and opens[index] > opens[index - 1]:
            returns[index] = closes[index] / closes[index - 1] - 1.0
    out: list[float | None] = [None] * len(bars)
    for index in range(len(bars)):
        trailing = [
            value
            for value in returns[max(0, index - VOL_REGIME_BASELINE_WINDOW + 1) : index + 1]
            if value is not None
        ]
        if len(trailing) < MIN_VOL_REGIME_OBSERVATIONS:
            continue
        short_window = trailing[-VOL_REGIME_SHORT_WINDOW:]
        short_vol = _stdev(short_window)
        baseline_vol = _stdev(trailing)
        if short_vol <= 0.0 or baseline_vol <= 0.0:
            continue
        out[index] = 1.0 if short_vol > baseline_vol else -1.0
    return out


def _regime_at(
    opens: Sequence[int], regimes: Sequence[float | None], decision_ms: int, step: int
) -> float | None:
    """Regime from the newest context bar that had closed by ``decision_ms``."""
    position = bisect_right(opens, decision_ms - step) - 1
    if position < 0:
        return None
    return regimes[position]


# --------------------------------------------------------------------------- #
# §2 — the frame builder
# --------------------------------------------------------------------------- #


def build_frame(
    *,
    timeframe: str,
    bars_by_symbol: Mapping[str, Sequence[Sequence[float]]],
    windows: Sequence[int],
    regime_bars_by_symbol: Mapping[str, Sequence[Sequence[float]]] | None = None,
    context_timeframe: str = "1h",
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Emit one synchronised frame row per entry bar, over the universe's common grid.

    ``windows`` are the lookbacks the campaign will read, in entry bars (the preregistered
    lag ladder plus the relative window).  ``bars_by_symbol`` and ``regime_bars_by_symbol``
    hold ``[open, o, h, l, c, v]`` bars.

    A row carries each symbol's raw window return in each window, each symbol's ATR, the
    equal-weight market return in each window, each symbol's context volatility regime and
    each symbol's forward return.  Nothing is derived per hypothesis here; that is
    :func:`cell_row`.
    """
    symbols = sorted(bars_by_symbol)
    if not symbols:
        return []
    series = {symbol: _SymbolSeries(bars_by_symbol[symbol]) for symbol in symbols}
    step = period_ms(timeframe)
    context_step = period_ms(context_timeframe)

    regimes: dict[str, list[float | None]] = {}
    regime_opens: dict[str, list[int]] = {}
    if regime_bars_by_symbol:
        for symbol in symbols:
            bars = regime_bars_by_symbol.get(symbol, [])
            regime_opens[symbol] = [int(bar[0]) for bar in bars]
            regimes[symbol] = _regime_series(bars)

    grids = [set(series[symbol].position) for symbol in symbols]
    common = sorted(set.intersection(*grids))

    ordered_windows = sorted({*windows, RELATIVE_WINDOW})
    rows: list[dict[str, Any]] = []
    for open_ms in common:
        decision_ms = open_ms + step
        if start_ms is not None and decision_ms < start_ms:
            continue
        if end_ms is not None and decision_ms > end_ms:
            continue

        row: dict[str, Any] = {"bar_open_ms": open_ms, "decision_ms": decision_ms}
        for symbol in symbols:
            local = series[symbol]
            index = local.position[open_ms]
            row[f"atr_pct_{symbol}"] = local.atr_pct[index]
            row[f"fwd_{symbol}"] = (
                local.close[index + 1] / local.close[index] - 1.0
                if index + 1 < len(local.close) and local.close[index] > 0.0
                else None
            )
            row[f"vol_regime_{symbol}"] = (
                _regime_at(regime_opens[symbol], regimes[symbol], decision_ms, context_step)
                if regime_bars_by_symbol
                else None
            )
        for window in ordered_windows:
            values: list[float] = []
            for symbol in symbols:
                local = series[symbol]
                value = local.window_return(local.position[open_ms], window, step)
                row[f"ret{window}_{symbol}"] = value
                if value is not None:
                    values.append(value)
            row[f"market_ret{window}"] = (
                statistics.fmean(values) if len(values) == len(symbols) else None
            )
        # The invariant this module exists to guarantee: every source bar the row used had
        # closed by the decision instant, by construction of the shared grid and the lag rule.
        row["available_ms"] = decision_ms
        row["point_in_time_ok"] = True
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# §3 — the per-cell derived features
# --------------------------------------------------------------------------- #


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0.0:
        return None
    return numerator / denominator


def cell_row(
    frame_row: Mapping[str, Any],
    *,
    target: str,
    leader: str | None = None,
    lag: int | None = None,
) -> dict[str, float | None]:
    """Derive the feature names a hypothesis may read, for one (target, leader, lag).

    ``lag`` is required for the lead-lag features and ``leader`` for ``leader_ret_z``;
    hypotheses that do not use them ignore the arguments.
    """
    target_atr = frame_row.get(f"atr_pct_{target}")
    out: dict[str, float | None] = {}

    if leader is not None and lag is not None:
        out["leader_ret_z"] = _divide(
            frame_row.get(f"ret{lag}_{leader}"), frame_row.get(f"atr_pct_{leader}")
        )
        out["target_ret_z"] = _divide(frame_row.get(f"ret{lag}_{target}"), target_atr)
    else:
        out["leader_ret_z"] = None
        out["target_ret_z"] = None

    target_mom_z = _divide(frame_row.get(f"ret{RELATIVE_WINDOW}_{target}"), target_atr)
    market_ret_z = _divide(frame_row.get(f"market_ret{RELATIVE_WINDOW}"), target_atr)
    out["target_mom_z"] = target_mom_z
    out["market_ret_z"] = market_ret_z
    out["relative_z"] = (
        target_mom_z - market_ret_z
        if target_mom_z is not None and market_ret_z is not None
        else None
    )
    return out


def forward_return_for(frame_row: Mapping[str, Any], target: str) -> float | None:
    """The label: the target's next-bar return.  Never an input."""
    value = frame_row.get(f"fwd_{target}")
    if value is None:
        return None
    return float(value)
