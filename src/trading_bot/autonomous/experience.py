"""Experience learning V1 — outcome-driven performance memory (§7/§8).

``DECISION → OUTCOME → ANALYSIS → LESSON → StrategyPerformance →
future router selection``

What this store CAN do: reorder strategies in the next router selection
through a bounded, documented priority adjustment derived from realised
outcomes.

What it CANNOT do (structurally, not by convention):

* change risk limits, sizing, leverage, capital or accounting;
* change admission thresholds or the admission ledger;
* promote a strategy to PAPER — that is the admission ledger's job alone;
* patch a strategy in place: a proposed improvement must become a
  RESEARCH_HYPOTHESIS / STRATEGY_CANDIDATE, never a live edit.

The store persists raw samples per (strategy, asset, regime, timeframe) cell
and derives aggregates on read, so every number can be traced back to the
outcomes that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import DecisionMode, OutcomeRecord, StrategyPerformance

__all__ = [
    "EXPERIENCE_VERSION",
    "MAX_PRIORITY_ADJUSTMENT",
    "MIN_SAMPLES_FOR_ADJUSTMENT",
    "RECENT_WINDOW",
    "StrategyPerformanceStore",
]

EXPERIENCE_VERSION = "experience-learning-v1"

#: Only this much router-priority movement is ever derived from outcomes.
MAX_PRIORITY_ADJUSTMENT = 0.25
#: Below this realised sample size no adjustment is applied at all.
MIN_SAMPLES_FOR_ADJUSTMENT = 20
#: Window used for the "recent" expectancy.
RECENT_WINDOW = 20


@dataclass(frozen=True, slots=True)
class PerformanceSample:
    decision_id: str
    timestamp_ms: int
    mode: str
    gross_bps: float
    net_bps: float
    correct: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "timestamp_ms": self.timestamp_ms,
            "mode": self.mode,
            "gross_bps": self.gross_bps,
            "net_bps": self.net_bps,
            "correct": self.correct,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PerformanceSample:
        return cls(
            decision_id=str(payload["decision_id"]),
            timestamp_ms=int(payload["timestamp_ms"]),
            mode=str(payload["mode"]),
            gross_bps=float(payload["gross_bps"]),
            net_bps=float(payload["net_bps"]),
            correct=bool(payload["correct"]),
        )

    @classmethod
    def from_outcome(cls, outcome: OutcomeRecord) -> PerformanceSample:
        return cls(
            decision_id=outcome.decision_id,
            timestamp_ms=outcome.outcome_time_ms,
            mode=outcome.mode.value,
            gross_bps=outcome.gross_return_bps,
            net_bps=outcome.net_hypothetical_bps,
            correct=outcome.direction_correct,
        )


class StrategyPerformanceStore:
    """Durable, auditable performance memory fed ONLY by resolved outcomes."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._cells: dict[str, dict[str, Any]] = {}
        self._seen_decisions: set[str] = set()
        self.load()

    # -- persistence --------------------------------------------------------

    def load(self) -> None:
        if not self._path.exists():
            self._cells = {}
            self._seen_decisions = set()
            return
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        self._cells = dict(payload.get("cells", {}))
        self._seen_decisions = set(payload.get("seen_decisions", []))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": EXPERIENCE_VERSION,
            "seen_decisions": sorted(self._seen_decisions),
            "cells": self._cells,
        }
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # -- updates ------------------------------------------------------------

    def update_from_outcome(
        self,
        outcome: OutcomeRecord,
        *,
        timeframe: str = "5m",
    ) -> StrategyPerformance:
        """Record one realised outcome and return the refreshed cell."""
        if outcome.status.value != "RESOLVED":
            raise ValueError("only RESOLVED outcomes may update performance")
        if outcome.decision_id in self._seen_decisions:
            # Idempotent: re-processing the same outcome must not double count.
            return self.aggregate(
                strategy_id=outcome.strategy_id,
                asset=outcome.asset,
                regime=outcome.regime or "UNKNOWN",
                timeframe=timeframe,
            )
        key = _cell_key(outcome.strategy_id, outcome.asset, outcome.regime or "UNKNOWN", timeframe)
        cell = self._cells.setdefault(
            key,
            {
                "strategy_id": outcome.strategy_id,
                "asset": outcome.asset,
                "regime": outcome.regime or "UNKNOWN",
                "timeframe": timeframe,
                "samples": [],
            },
        )
        cell["samples"].append(PerformanceSample.from_outcome(outcome).to_dict())
        self._seen_decisions.add(outcome.decision_id)
        self.save()
        return self.aggregate(
            strategy_id=outcome.strategy_id,
            asset=outcome.asset,
            regime=outcome.regime or "UNKNOWN",
            timeframe=timeframe,
        )

    # -- reads --------------------------------------------------------------

    def samples(
        self,
        *,
        strategy_id: str,
        asset: str,
        regime: str,
        timeframe: str,
    ) -> list[PerformanceSample]:
        cell = self._cells.get(_cell_key(strategy_id, asset, regime, timeframe))
        if cell is None:
            return []
        return [PerformanceSample.from_dict(s) for s in cell.get("samples", [])]

    def get(
        self,
        *,
        strategy_id: str,
        asset: str,
        regime: str,
        timeframe: str,
    ) -> StrategyPerformance | None:
        """Aggregate cell, or ``None`` when nothing has been realised yet."""
        rows = self.samples(
            strategy_id=strategy_id, asset=asset, regime=regime, timeframe=timeframe
        )
        if not rows:
            return None
        return self._aggregate_rows(
            rows, strategy_id=strategy_id, asset=asset, regime=regime, timeframe=timeframe
        )

    def aggregate(
        self,
        *,
        strategy_id: str,
        asset: str,
        regime: str,
        timeframe: str,
    ) -> StrategyPerformance:
        """Aggregate cell, raising when there is no sample (never invent one)."""
        result = self.get(
            strategy_id=strategy_id, asset=asset, regime=regime, timeframe=timeframe
        )
        if result is None:
            raise KeyError(f"no realised samples for {_cell_key(strategy_id, asset, regime, timeframe)}")
        return result

    def _aggregate_rows(
        self,
        rows: list[PerformanceSample],
        *,
        strategy_id: str,
        asset: str,
        regime: str,
        timeframe: str,
    ) -> StrategyPerformance:
        rows = sorted(rows, key=lambda s: s.timestamp_ms)
        sample_size = len(rows)
        gross = sum(s.gross_bps for s in rows) / sample_size
        net = sum(s.net_bps for s in rows) / sample_size
        wins = [s.net_bps for s in rows if s.net_bps > 0]
        losses = [s.net_bps for s in rows if s.net_bps < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        hit_rate = sum(1 for s in rows if s.correct) / sample_size

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for s in rows:
            cumulative += s.net_bps
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        recent_rows = rows[-RECENT_WINDOW:]
        recent = sum(s.net_bps for s in recent_rows) / len(recent_rows)
        paper_rows = [s for s in rows if s.mode == DecisionMode.TRADE_PAPER.value]
        shadow_rows = [s for s in rows if s.mode == DecisionMode.SHADOW_TRADE.value]

        return StrategyPerformance(
            strategy_id=strategy_id,
            asset=asset,
            regime=regime,
            timeframe=timeframe,
            sample_size=sample_size,
            shadow_sample_size=len(shadow_rows),
            paper_sample_size=len(paper_rows),
            gross_expectancy_bps=gross,
            net_expectancy_bps=net,
            hit_rate=hit_rate,
            profit_factor=profit_factor,
            max_drawdown_bps=max_dd,
            recent_net_expectancy_bps=recent,
            historical_net_expectancy_bps=net,
            confidence=min(1.0, sample_size / 200.0),
            last_updated_ms=int(rows[-1].timestamp_ms),
        )

    def selection_priority(
        self,
        *,
        strategy_id: str,
        asset: str,
        regime: str,
        timeframe: str,
    ) -> float:
        """Bounded router-priority adjustment derived from realised outcomes.

        Bounded to ±``MAX_PRIORITY_ADJUSTMENT`` and zero below
        ``MIN_SAMPLES_FOR_ADJUSTMENT``: experience may nudge which strategy
        is evaluated first, never how much risk the system takes.
        """
        cell = self.get(
            strategy_id=strategy_id, asset=asset, regime=regime, timeframe=timeframe
        )
        if cell is None or cell.sample_size < MIN_SAMPLES_FOR_ADJUSTMENT:
            return 0.0
        # 10 bps of realised net expectancy maps to the full adjustment.
        raw = cell.net_expectancy_bps / 10.0
        return round(max(-MAX_PRIORITY_ADJUSTMENT, min(MAX_PRIORITY_ADJUSTMENT, raw)), 6)

    def all_cells(self) -> list[StrategyPerformance]:
        out: list[StrategyPerformance] = []
        for cell in self._cells.values():
            rows = [PerformanceSample.from_dict(s) for s in cell.get("samples", [])]
            if not rows:
                continue
            out.append(
                self._aggregate_rows(
                    rows,
                    strategy_id=str(cell["strategy_id"]),
                    asset=str(cell["asset"]),
                    regime=str(cell["regime"]),
                    timeframe=str(cell["timeframe"]),
                )
            )
        return sorted(out, key=lambda p: (p.strategy_id, p.asset, p.regime, p.timeframe))

    def seen_decision_ids(self) -> set[str]:
        return set(self._seen_decisions)


def _cell_key(strategy_id: str, asset: str, regime: str, timeframe: str) -> str:
    return f"{strategy_id}|{asset}|{regime}|{timeframe}"
