"""Dynamic correlation — Track D of INTELLIGENCE-AND-EXECUTION-HARDENING-01.

Aligned PIT returns -> rolling correlation matrix -> thresholded edges ->
edge density -> causal smoothing -> hysteresis -> NORMAL/FUSED regime.

Hard invariants:

- PIT/alignment: the state at index t depends only on returns[: t + 1].
- No centered windows, no future leakage.
- No artificial zero-return forward filling (gaps stay gaps; windows with
  insufficient overlap are skipped, not fabricated).

Causality test contract: modifying ALL FUTURE observations must leave every
PAST correlation state byte-identical.

Context/risk evidence only — never alpha. Nothing here changes POC01
behavior; the module is a standalone primitive for future MarketContext /
AssetContext / Portfolio / Risk / Health consumers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class CorrelationState(StrEnum):
    NORMAL = "NORMAL"
    FUSED = "FUSED"


def aligned_pit_returns(
    ts: tuple[int, ...], prices: tuple[float, ...]
) -> tuple[tuple[int, float], ...]:
    """Aligned PIT returns from (timestamp, price) observations.

    Returns are computed only between CONSECUTIVE aligned observations of the
    same series (no forward filling): a gap in timestamps simply produces a
    return between the observations that exist. Missing points are never
    synthesized as 0.0.
    """
    if len(ts) != len(prices):
        raise ValueError("ts and prices must have the same length")
    out: list[tuple[int, float]] = []
    for i in range(1, len(prices)):
        if ts[i] < ts[i - 1]:
            raise ValueError("timestamps must be non-decreasing")
        if ts[i] == ts[i - 1]:
            continue  # duplicate timestamp: skip, do not fabricate
        if prices[i - 1] <= 0:
            continue  # invalid price: skip pair, never fill with zero
        out.append((ts[i], prices[i] / prices[i - 1] - 1.0))
    return tuple(out)


def _pearson(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    n = len(a)
    if n != len(b) or n < 2:
        raise ValueError("pearson requires equal-length series of length >= 2")
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    denom = math.sqrt(var_a * var_b)
    if denom == 0.0:
        return 0.0  # zero variance -> no correlation evidence (not 1.0, not NaN)
    return max(-1.0, min(1.0, cov / denom))


def rolling_correlation(
    series_a: tuple[tuple[int, float], ...],
    series_b: tuple[tuple[int, float], ...],
    *,
    window: int,
) -> tuple[tuple[int, float], ...]:
    """Causal rolling Pearson correlation between two aligned PIT return series.

    At each common timestamp t, the correlation uses ONLY the trailing
    ``window`` overlapping observations at or before t (trailing window —
    never centered, never future). Timestamps with insufficient overlap are
    skipped entirely.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    index_b = dict(series_b)
    common = [(t, r) for t, r in series_a if t in index_b]
    out: list[tuple[int, float]] = []
    for i in range(len(common)):
        t = common[i][0]
        lo = max(0, i - window + 1)
        pair = common[lo : i + 1]
        if len(pair) < window:
            continue  # insufficient overlap: no fabricated state
        corr = _pearson(tuple(r for _, r in pair), tuple(index_b[tt] for tt, _ in pair))
        out.append((t, corr))
    return tuple(out)


def _ema(series: tuple[tuple[int, float], ...], span: int) -> tuple[tuple[int, float], ...]:
    """Causal EMA smoothing (alpha = 2 / (span + 1)); first point seeds."""
    if span < 1 or not series:
        return series
    alpha = 2.0 / (span + 1.0)
    out: list[tuple[int, float]] = []
    acc = series[0][1]
    for t, v in series:
        acc = alpha * v + (1.0 - alpha) * acc
        out.append((t, acc))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Thresholds + hysteresis for the NORMAL/FUSED regime."""

    window: int = 30
    smoothing_span: int = 5
    fuse_enter: float = 0.85  # edge density above this -> FUSED
    fuse_exit: float = 0.60  # edge density below this -> NORMAL (hysteresis)
    edge_threshold: float = 0.70  # |corr| above this counts as an edge


class DynamicCorrelationEngine:
    """Rolling pairwise correlation regime with hysteresis.

    Single-pair mode (a vs b) exposes the same edge-density logic used for
    the multi-asset matrix: a pair contributes an edge when its causal
    smoothed |correlation| exceeds ``edge_threshold``. The FUSED/NORMAL
    decision enters FUSED above ``fuse_enter`` density and exits back to
    NORMAL below ``fuse_exit`` (hysteresis band).
    """

    def __init__(self, config: FusionConfig | None = None) -> None:
        self._config = config or FusionConfig()
        self._state: CorrelationState = CorrelationState.NORMAL

    @property
    def state(self) -> CorrelationState:
        return self._state

    def evaluate_series(
        self,
        series_a: tuple[tuple[int, float], ...],
        series_b: tuple[tuple[int, float], ...],
    ) -> tuple[tuple[tuple[int, CorrelationState], ...], tuple[tuple[int, float], ...]]:
        """Full causal pipeline; returns (states, smoothed correlations).

        The hysteresis state evolves forward in time only: at each t the
        decision uses the smoothed correlation at t and the prior state.
        """
        rolling = rolling_correlation(series_a, series_b, window=self._config.window)
        smoothed = _ema(rolling, self._config.smoothing_span)
        states: list[tuple[int, CorrelationState]] = []
        for t, corr in smoothed:
            density = 1.0 if abs(corr) >= self._config.edge_threshold else 0.0
            if (
                self._state is CorrelationState.NORMAL
                and density >= 1.0
                and corr >= self._config.fuse_enter
            ):
                self._state = CorrelationState.FUSED
            elif self._state is CorrelationState.FUSED and corr < self._config.fuse_exit:
                self._state = CorrelationState.NORMAL
            states.append((t, self._state))
        return tuple(states), smoothed
