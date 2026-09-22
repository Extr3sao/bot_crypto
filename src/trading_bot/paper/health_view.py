"""Read-only Strategy Health view layer (UI-01..UI-04).

PORTFOLIO-AND-RUNTIME-INTEGRATION-01, Track D. Composes

- ``paper.health_projection`` rows (per strategy x asset x timeframe x regime), and
- ``research.regime_eligibility`` evidence cells

into a frontend-ready, strictly read-only view model:

- every regime-matrix cell is evidence-backed (no family-name inference);
- missing evidence is reported as ``INSUFFICIENT_EVIDENCE`` with an explicit
  ``no_evidence`` marker (honest empty cells, D2);
- trading controls are structurally impossible: this module exposes no
  mutation, no trading methods, and the payload is flagged ``read_only``.

No POC01 interaction: consumes only already-computed evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trading_bot.paper.health_projection import HealthProjectionRow

__all__ = [
    "INSUFFICIENT_EVIDENCE",
    "HealthCell",
    "HealthMatrixView",
    "HealthRowView",
    "build_health_matrix",
]

INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

# Canonical regime columns for the matrix (Track D1). Pre-declared, not
# inferred from data.
REGIME_COLUMNS: tuple[str, ...] = (
    "TREND",
    "RANGE",
    "HIGH_VOL",
    "SHOCK",
)


@dataclass(frozen=True, slots=True)
class HealthRowView:
    """One read-only strategy health row (UI-01 fields)."""

    strategy: str
    asset: str
    timeframe: str
    regime: str
    health_state: str
    sample_n: int
    rolling_expectancy: float
    baseline_expectancy: float
    rolling_sharpe: float
    baseline_sharpe: float
    profit_factor: float
    drawdown: float
    last_transition: str
    transition_reason: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "health_state": self.health_state,
            "metrics": {
                "sample_n": self.sample_n,
                "rolling_expectancy": self.rolling_expectancy,
                "baseline_expectancy": self.baseline_expectancy,
                "rolling_sharpe": self.rolling_sharpe,
                "baseline_sharpe": self.baseline_sharpe,
                "profit_factor": self.profit_factor,
                "drawdown": self.drawdown,
            },
            "transition": {
                "last": self.last_transition,
                "reason": self.transition_reason,
                "next_action": self.next_action,
            },
            "read_only": True,
        }


@dataclass(frozen=True, slots=True)
class HealthCell:
    """One evidence-backed matrix cell. Empty evidence stays explicit (D2)."""

    strategy: str
    regime: str
    status: str
    evidence_n: int
    evidence_basis: str
    no_evidence: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "regime": self.regime,
            "status": self.status,
            "evidence": {
                "n": self.evidence_n,
                "basis": self.evidence_basis,
                "no_evidence": self.no_evidence,
            },
            "read_only": True,
        }


def _insufficient_cell(strategy: str, regime: str) -> HealthCell:
    return HealthCell(
        strategy=strategy,
        regime=regime,
        status=INSUFFICIENT_EVIDENCE,
        evidence_n=0,
        evidence_basis="no evidence rows for this strategy x regime cell",
        no_evidence=True,
    )


@dataclass(frozen=True, slots=True)
class HealthMatrixView:
    """Strategy x regime matrix with every cell evidence-backed."""

    cells: tuple[tuple[HealthCell, ...], ...]
    strategies: tuple[str, ...]
    regimes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "regimes": list(self.regimes),
            "rows": [
                {
                    "strategy": self.strategies[row_idx],
                    "cells": [cell.to_dict() for cell in row],
                }
                for row_idx, row in enumerate(self.cells)
            ],
            "read_only": True,
        }


def build_health_matrix(
    rows: Sequence[HealthProjectionRow],
    *,
    regimes: Sequence[str] = REGIME_COLUMNS,
    min_evidence_n: int = 1,
) -> HealthMatrixView:
    """Build the strategy x regime view from health projection rows.

    ``min_evidence_n`` is the pre-declared minimum sample for a cell to report
    anything other than ``INSUFFICIENT_EVIDENCE``. Cells without rows are
    never inferred from strategy names or families.
    """
    strategies: list[str] = []
    for row in rows:
        if row.strategy not in strategies:
            strategies.append(row.strategy)
    # Evidence per (strategy, regime): count + best-basis status (deterministic:
    # max N row decides the cell, ties broken by first appearance).
    evidence: dict[tuple[str, str], list[HealthProjectionRow]] = {}
    for row in rows:
        evidence.setdefault((row.strategy, row.regime), []).append(row)
    cell_rows: list[tuple[HealthCell, ...]] = []
    for strategy in strategies:
        cells: list[HealthCell] = []
        for regime in regimes:
            cell_rows_evidence = evidence.get((strategy, regime), [])
            if not cell_rows_evidence:
                cells.append(_insufficient_cell(strategy, regime))
                continue
            best = max(cell_rows_evidence, key=lambda r: r.sample_size)
            if best.sample_size < min_evidence_n:
                cells.append(_insufficient_cell(strategy, regime))
                continue
            cells.append(
                HealthCell(
                    strategy=strategy,
                    regime=regime,
                    status=best.health_state,
                    evidence_n=best.sample_size,
                    evidence_basis=(
                        f"health projection row n={best.sample_size} "
                        f"(asset={best.asset}, timeframe={best.timeframe})"
                    ),
                    no_evidence=False,
                )
            )
        cell_rows.append(tuple(cells))
    return HealthMatrixView(
        cells=tuple(cell_rows),
        strategies=tuple(strategies),
        regimes=tuple(regimes),
    )


@dataclass(frozen=True, slots=True)
class _HealthRowsAdapter:
    """Adapts eligibility-style dicts into projection rows for reuse."""

    @staticmethod
    def from_dicts(payload: Iterable[Mapping[str, Any]]) -> tuple[HealthProjectionRow, ...]:
        out: list[HealthProjectionRow] = []
        for item in payload:
            out.append(
                HealthProjectionRow(
                    strategy=str(item["strategy"]),
                    version=str(item.get("version", "1")),
                    asset=str(item.get("asset", "")),
                    timeframe=str(item.get("timeframe", "")),
                    regime=str(item["regime"]),
                    observation_window=str(item.get("observation_window", "")),
                    health_state=str(item["health_state"]),
                    rolling_expectancy=float(item.get("rolling_expectancy", 0.0)),
                    baseline_expectancy=float(item.get("baseline_expectancy", 0.0)),
                    rolling_sharpe=float(item.get("rolling_sharpe", 0.0)),
                    baseline_sharpe=float(item.get("baseline_sharpe", 0.0)),
                    profit_factor=float(item.get("profit_factor", 0.0)),
                    drawdown=float(item.get("drawdown", 0.0)),
                    sample_size=int(item.get("sample_size", 0)),
                    last_transition=str(item.get("last_transition", "")),
                    reason=str(item.get("reason", "")),
                    next_gate=str(item.get("next_gate", "")),
                )
            )
        return tuple(out)


def health_view_payload(
    rows: Sequence[HealthProjectionRow],
    *,
    regimes: Sequence[str] = REGIME_COLUMNS,
    min_evidence_n: int = 1,
) -> dict[str, Any]:
    """Frontend payload: row views + evidence matrix, strictly read-only."""
    matrix = build_health_matrix(rows, regimes=regimes, min_evidence_n=min_evidence_n)
    return {
        "rows": [
            HealthRowView(
                strategy=r.strategy,
                asset=r.asset,
                timeframe=r.timeframe,
                regime=r.regime,
                health_state=r.health_state,
                sample_n=r.sample_size,
                rolling_expectancy=r.rolling_expectancy,
                baseline_expectancy=r.baseline_expectancy,
                rolling_sharpe=r.rolling_sharpe,
                baseline_sharpe=r.baseline_sharpe,
                profit_factor=r.profit_factor,
                drawdown=r.drawdown,
                last_transition=r.last_transition,
                transition_reason=r.reason,
                next_action=r.next_gate,
            ).to_dict()
            for r in rows
        ],
        "regime_matrix": matrix.to_dict(),
        "read_only": True,
    }
