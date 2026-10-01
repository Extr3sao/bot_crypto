"""Context-keyed performance with rolling windows (§6/§7/§14/§26).

The store keeps the RAW observations per ``(strategy, asset, timeframe,
regime)`` cell and derives aggregates on read, exactly like the existing
experience store — so every number can be traced back to the observations that
produced it, and nothing is silently overwritten.

Determinism: observations are ordered by ``(timestamp_ms, sequence)``; equal
timestamps never reorder aggregates. No wall-clock is consulted for values.
"""

from __future__ import annotations

from collections.abc import Iterable
import bisect
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from .config import RollingWindows
from .contracts import ContextKey, ExecutionMode, PerformanceCell

__all__ = [
    "PERFORMANCE_STORE_VERSION",
    "ContextualPerformanceStore",
    "PerformanceObservation",
    "PerformanceWindow",
    "derive_cell",
]

PERFORMANCE_STORE_VERSION: Final[str] = "contextual-performance-store-v1"


class PerformanceWindow(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass(frozen=True, slots=True)
class PerformanceObservation:
    """One realised observation with full provenance (§26)."""

    context: ContextKey
    timestamp_ms: int
    gross_bps: float
    net_bps: float
    cost_bps: float
    notional_usdt: float
    correct: bool
    execution_mode: ExecutionMode = ExecutionMode.SHADOW
    sequence: int = 0
    decision_id: str = ""

    def __post_init__(self) -> None:
        if self.execution_mode is ExecutionMode.LIVE:
            raise ValueError("observations in this plane are never LIVE")
        if not self.context.regime:
            raise ValueError("an observation must carry its regime label (§14)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "timestamp_ms": self.timestamp_ms,
            "gross_bps": round(self.gross_bps, 8),
            "net_bps": round(self.net_bps, 8),
            "cost_bps": round(self.cost_bps, 8),
            "notional_usdt": round(self.notional_usdt, 8),
            "correct": self.correct,
            "execution_mode": self.execution_mode.value,
            "sequence": self.sequence,
            "decision_id": self.decision_id,
        }


def _max_drawdown_bps(net_series: list[float]) -> float:
    """Peak-to-trough of the cumulative net-bps curve, in bps (>= 0)."""
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in net_series:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return abs(worst)


def _split_windows(series: list[float], parts: int) -> list[list[float]]:
    if parts <= 1 or len(series) < parts:
        return [series] if series else []
    size = len(series) // parts
    out: list[list[float]] = []
    for i in range(parts):
        start = i * size
        end = len(series) if i == parts - 1 else start + size
        out.append(series[start:end])
    return out


def derive_cell(
    context: ContextKey,
    observations: list[PerformanceObservation],
    *,
    window: str,
    last_updated_ms: int = 0,
    stability_parts: int = 4,
) -> PerformanceCell:
    """Derive one :class:`PerformanceCell` from a (already windowed) list."""
    net = [o.net_bps for o in observations]
    gross = [o.gross_bps for o in observations]
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v < 0]
    gross_win = sum(w for w in gross if w > 0)
    gross_loss = abs(sum(w for w in gross if w < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    sub = _split_windows(net, stability_parts)
    positive_windows = sum(1 for part in sub if part and sum(part) > 0)

    return PerformanceCell(
        context=context,
        window=window,
        sample_count=len(observations),
        trade_count=len(observations),
        gross_pnl_usdt=sum(o.notional_usdt * (o.gross_bps / 10_000.0) for o in observations),
        net_pnl_usdt=sum(o.notional_usdt * (o.net_bps / 10_000.0) for o in observations),
        gross_expectancy_bps=(sum(gross) / len(gross)) if gross else 0.0,
        net_expectancy_bps=(sum(net) / len(net)) if net else 0.0,
        profit_factor=profit_factor,
        hit_rate=(len(wins) / len(net)) if net else 0.0,
        avg_win_bps=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss_bps=(sum(losses) / len(losses)) if losses else 0.0,
        max_drawdown_bps=_max_drawdown_bps(net),
        exposure_usdt=sum(o.notional_usdt for o in observations),
        turnover_usdt=sum(o.notional_usdt for o in observations),
        cost_bps=(sum(o.cost_bps for o in observations) / len(observations)) if observations else 0.0,
        slippage_bps=None,
        positive_windows=positive_windows,
        window_count=len(sub),
        last_updated_ms=last_updated_ms,
        execution_mode=_dominant_mode(observations),
    )


def _dominant_mode(observations: list[PerformanceObservation]) -> ExecutionMode:
    if not observations:
        return ExecutionMode.SHADOW
    modes = {o.execution_mode for o in observations}
    if len(modes) == 1:
        return next(iter(modes))
    # Mixed provenance: report the weakest (SHADOW) so a mixed cell is never
    # presented as if it were all PAPER.
    return ExecutionMode.SHADOW


@dataclass(slots=True)
class ContextualPerformanceStore:
    """Append-only, context-keyed observation store with rolling windows."""

    windows: RollingWindows = field(default_factory=RollingWindows)
    _observations: dict[ContextKey, list[PerformanceObservation]] = field(
        default_factory=dict, repr=False
    )
    _sequence: int = field(default=0, repr=False)
    schema_version: str = PERFORMANCE_STORE_VERSION

    # -- writes -------------------------------------------------------------

    def record(self, observation: PerformanceObservation) -> PerformanceObservation:
        """Append one observation. Sequence is assigned here so ordering is total."""
        seq = self._sequence
        self._sequence += 1
        if observation.sequence == 0:
            observation = _with_sequence(observation, seq)
        key = observation.context
        bucket = self._observations.setdefault(key, [])
        # Keep the bucket ordered without re-sorting the whole list on every
        # insert (that was O(n^2); feeding a long experiment hung). bisect keeps
        # the invariant with one O(log n) probe and a memmove.
        bisect.insort(bucket, observation, key=lambda o: (o.timestamp_ms, o.sequence))
        return observation

    def record_many(self, observations: Iterable[PerformanceObservation]) -> None:
        for obs in observations:
            self.record(obs)

    # -- reads --------------------------------------------------------------

    def contexts(self) -> list[ContextKey]:
        return sorted(self._observations, key=str)

    def observations(self, context: ContextKey) -> tuple[PerformanceObservation, ...]:
        return tuple(self._observations.get(context, ()))

    def window_size(self, window: str) -> int:
        return self.windows.resolve(window)

    def cell(self, context: ContextKey, window: str) -> PerformanceCell:
        size = self.windows.resolve(window)
        obs = self._observations.get(context, [])
        sliced = obs[-size:] if size > 0 else list(obs)
        last = max((o.timestamp_ms for o in sliced), default=0)
        return derive_cell(context, sliced, window=window, last_updated_ms=last)

    def cells(self, context: ContextKey) -> dict[str, PerformanceCell]:
        return {w: self.cell(context, w) for w in ("short", "medium", "long")}

    def contexts_for(self, strategy_id: str | None = None, asset: str | None = None) -> list[ContextKey]:
        """All cells, optionally filtered by strategy and/or asset (§6/§14)."""
        out: list[ContextKey] = []
        for key in self._observations:
            if strategy_id is not None and key.strategy_id != strategy_id:
                continue
            if asset is not None and key.asset != asset:
                continue
            out.append(key)
        return sorted(out, key=str)

    def regime_matrix(self, strategy_id: str, asset: str, timeframe: str, window: str = "medium") -> dict[str, PerformanceCell]:
        """strategy x asset x timeframe x regime table (§14)."""
        out: dict[str, PerformanceCell] = {}
        for key in self._observations:
            if (key.strategy_id, key.asset, key.timeframe) != (strategy_id, asset, timeframe):
                continue
            out[key.regime] = self.cell(key, window)
        return dict(sorted(out.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "windows": {
                "short": self.windows.short,
                "medium": self.windows.medium,
                "long": self.windows.long,
            },
            "cells": {
                str(key): [o.to_dict() for o in obs] for key, obs in self._observations.items()
            },
        }


def _with_sequence(obs: PerformanceObservation, seq: int) -> PerformanceObservation:
    return PerformanceObservation(
        context=obs.context,
        timestamp_ms=obs.timestamp_ms,
        gross_bps=obs.gross_bps,
        net_bps=obs.net_bps,
        cost_bps=obs.cost_bps,
        notional_usdt=obs.notional_usdt,
        correct=obs.correct,
        execution_mode=obs.execution_mode,
        sequence=seq,
        decision_id=obs.decision_id,
    )
