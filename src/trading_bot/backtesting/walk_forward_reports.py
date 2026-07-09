"""Walk-forward aggregate reports (TSK-104 F3b residuo).

Cierra el residuo pineado en retrieval-log como pendiente de F3b
("cualquier capa futura de cross-fold aggregated reports / fitting
real antes de considerar TSK-104 plenamente cerrado a nivel producto").

Responsabilidad: tomar la lista de ``FoldReport`` que produce
``walk_forward_run`` y agregar las metricas cross-fold en un
``WalkForwardAggregateReport`` con:

- Total trades + total realized PnL (sumas).
- ``consistency_score``: fraccion de folds con ``final_equity >
  initial_capital`` (pnl==0 NO cuenta como profitable, ver pine contract).
- ``MetricAggregate`` por metrica (mean / std / min / max) con filtrado
  de inf/nan antes de calcular.

Sin fitting real (queda fuera del scope F3b POC per retrieval-log).
La API de ``walk_forward_run`` permanece minimal; el agregado se
computa lazy via ``build_walk_forward_aggregate(reports)`` (opcion C
del design: separado de la ejecucion, sin expandir la API).
"""

from __future__ import annotations

import dataclasses
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from .reports import FoldReport


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    """Aggregate of one metric across multiple folds: mean, std, min, max.

    Pine contract:
    - All values are finite (math.isfinite). Inf/nan in source data is
      filtered out by ``_aggregate_metric`` before computing stats.
    - ``std`` is ``0.0`` when fewer than 2 finite samples are available
      (no StatisticsError; pineado por mirror de ``_compute_sharpe``).
    - ``mean`` / ``std`` / ``min`` / ``max`` are all ``0.0`` when no
      finite samples exist (defensive default).
    """

    mean: float
    std: float
    min: float
    max: float


@dataclass(frozen=True, slots=True)
class WalkForwardAggregateReport:
    """Cross-fold summary of a walk-forward run.

    Pine contract:
    - ``total_folds == len(reports)`` passed to the builder.
    - ``consistency_score = profitable_count / total_folds`` where
      ``profitable_count = sum(1 for r in reports if r.final_equity >
      r.initial_capital)``. ``pnl == 0`` is NOT profitable (it doesn't
      cover risk/time).
    - ``total_realized_pnl = sum(r.final_equity - r.initial_capital)``.
    - ``total_trades = sum(r.total_trades)``.
    - All ``MetricAggregate`` fields use the safe aggregation that
      filters inf/nan.
    """

    total_folds: int
    total_trades: int
    total_realized_pnl: float
    consistency_score: float
    win_rate: MetricAggregate
    profit_factor: MetricAggregate
    expectancy: MetricAggregate
    max_drawdown: MetricAggregate
    cagr: MetricAggregate
    sharpe_ratio: MetricAggregate


def build_walk_forward_aggregate(reports: list[FoldReport]) -> WalkForwardAggregateReport:
    """Build an aggregate report from a list of per-fold reports.

    Pine contract:
    - Empty ``reports`` raises ``ValueError("reports list cannot be empty")``
      (fail-fast; no silent zero aggregate that would mask a misuse).
    - Folds with inf/nan in any metric are filtered out for that metric
      (the other folds still contribute).
    - All-equal folds produce ``std=0.0`` and ``mean=min=max=that_value``.
    - Single fold produces ``std=0.0`` and ``mean=min=max=that_value``.

    Raises:
        ValueError: if ``reports`` is empty.
    """
    if not reports:
        raise ValueError("reports list cannot be empty.")

    total_trades = sum(report.total_trades for report in reports)
    total_realized_pnl = sum(report.final_equity - report.initial_capital for report in reports)
    profitable_count = sum(1 for report in reports if report.final_equity > report.initial_capital)
    consistency_score = profitable_count / len(reports)

    return WalkForwardAggregateReport(
        total_folds=len(reports),
        total_trades=total_trades,
        total_realized_pnl=total_realized_pnl,
        consistency_score=consistency_score,
        win_rate=_aggregate_metric(r.win_rate for r in reports),
        profit_factor=_aggregate_metric(r.profit_factor for r in reports),
        expectancy=_aggregate_metric(r.expectancy for r in reports),
        max_drawdown=_aggregate_metric(r.max_drawdown for r in reports),
        cagr=_aggregate_metric(r.cagr for r in reports),
        sharpe_ratio=_aggregate_metric(r.sharpe_ratio for r in reports),
    )


def _aggregate_metric(values: Iterable[float]) -> MetricAggregate:
    """Compute mean, std, min, max over a list of floats, filtering inf/nan.

    Pine contract:
    - Non-finite values (``inf``, ``-inf``, ``nan``) are filtered out
      before computing stats; they do NOT contribute to mean/std/min/max.
    - If all values are non-finite, returns ``MetricAggregate(0, 0, 0, 0)``.
    - If fewer than 2 finite values, ``std`` is ``0.0`` (no
      ``statistics.StatisticsError``).
    """
    finite = [float(v) for v in values if math.isfinite(v)]
    if not finite:
        return MetricAggregate(mean=0.0, std=0.0, min=0.0, max=0.0)
    return MetricAggregate(
        mean=float(statistics.mean(finite)),
        std=float(statistics.stdev(finite)) if len(finite) >= 2 else 0.0,
        min=float(min(finite)),
        max=float(max(finite)),
    )


def render_walk_forward_aggregate_markdown(report: WalkForwardAggregateReport) -> str:
    """Render the aggregate report as a markdown document.

    Pine contract: output is deterministic (fixed field order) so the
    output is suitable for snapshot/golden tests.
    """
    lines = [
        "# Walk-Forward Aggregate Report",
        "",
        f"- Total folds: {report.total_folds}",
        f"- Total trades: {report.total_trades}",
        f"- Total realized PnL: {report.total_realized_pnl:.4f}",
        f"- Consistency score: {report.consistency_score:.2%}",
        "",
        "## Metric Aggregates (mean / std / min / max)",
        "",
        (
            f"- win_rate: {report.win_rate.mean:.4f} / {report.win_rate.std:.4f} / "
            f"{report.win_rate.min:.4f} / {report.win_rate.max:.4f}"
        ),
        (
            f"- profit_factor: {report.profit_factor.mean:.4f} / "
            f"{report.profit_factor.std:.4f} / {report.profit_factor.min:.4f} / "
            f"{report.profit_factor.max:.4f}"
        ),
        (
            f"- expectancy: {report.expectancy.mean:.4f} / "
            f"{report.expectancy.std:.4f} / {report.expectancy.min:.4f} / "
            f"{report.expectancy.max:.4f}"
        ),
        (
            f"- max_drawdown: {report.max_drawdown.mean:.4f} / "
            f"{report.max_drawdown.std:.4f} / {report.max_drawdown.min:.4f} / "
            f"{report.max_drawdown.max:.4f}"
        ),
        (
            f"- cagr: {report.cagr.mean:.4f} / {report.cagr.std:.4f} / "
            f"{report.cagr.min:.4f} / {report.cagr.max:.4f}"
        ),
        (
            f"- sharpe_ratio: {report.sharpe_ratio.mean:.4f} / "
            f"{report.sharpe_ratio.std:.4f} / {report.sharpe_ratio.min:.4f} / "
            f"{report.sharpe_ratio.max:.4f}"
        ),
        "",
    ]
    return "\n".join(lines)


def build_walk_forward_aggregate_payload(
    report: WalkForwardAggregateReport,
) -> dict[str, object]:
    """Build a JSON-serializable payload for the aggregate report.

    Pine contract: every key is present and the structure is deterministic;
    the payload can be hashed for golden tests and snapshot comparisons.
    Shape-drift protection: iterates over ``dataclasses.fields`` so new
    fields added to ``WalkForwardAggregateReport`` (or to any nested
    ``MetricAggregate``) are automatically included without a manual
    hand-rolled dict literal.
    """
    return _dataclass_to_dict(report)


def _dataclass_to_dict(obj: object) -> dict[str, object]:
    """Serialize a dataclass to a dict, recursing into nested dataclasses.

    Pine contract:
    - Iterates over ``dataclasses.fields(obj)`` so the output keys
      follow the dataclass definition (no shape-drift).
    - Recurses into nested dataclass instances (e.g. ``MetricAggregate``).
    - Returns primitive values (int, float, str, bool, None) as-is.
    - Class objects (e.g. types) are returned as-is and not recursed.

    Limitation: does NOT recurse into ``list[Dataclass]`` fields. If a
    future schema adds a list field, extend this helper to handle
    ``isinstance(value, list) and all(dataclasses.is_dataclass(v) and
    not isinstance(v, type) for v in value)`` and emit per-element
    ``_dataclass_to_dict`` items. The current schema only nests
    ``MetricAggregate`` (single dataclass, not a list), so this
    limitation is not blocking today.
    """
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"_dataclass_to_dict requires a dataclass instance, got {type(obj)}")
    result: dict[str, object] = {}
    for field in dataclasses.fields(obj):
        value = getattr(obj, field.name)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            result[field.name] = _dataclass_to_dict(value)
        else:
            result[field.name] = value
    return result


__all__ = [
    "MetricAggregate",
    "WalkForwardAggregateReport",
    "build_walk_forward_aggregate",
    "build_walk_forward_aggregate_payload",
    "render_walk_forward_aggregate_markdown",
]
