"""Backtest reports module (TSK-104 F3).

Pure-function helpers that build per-fold + cross-fold reports from completed
``BacktestResult`` objects. NO I/O, NO ``datetime.now()``, NO set iteration.
Deterministic: all input ordering handled via explicit sorting.

Pine contract (per ADR-0012 F3a DoD):
- ``FoldReport`` + ``WalkForwardReport`` son frozen dataclasses con
  ``slots=True`` (consistente con F2 pine contract).
- ``build_fold_report`` agrega per-symbol metrics dict + cross-fold metadata.
- ``build_walk_forward_report`` agrega per-fold reports + global aggregate
  (cross-fold: mean of per-fold metrics).
- ``render_table`` produce ASCII deterministico via ``rich`` (si esta
  instalado) o fallback ``str.join`` plain. Sin acentos decorativos.

Anti-patterns (no deben regressar):
- NO I/O (no ``open()``, no ``print``); ``render_table`` return str.
- NO ``datetime.now()`` (engine ya pinea determinismo via candle timestamps).
- NO set iteration; sort estable explicito.
- NO mutar inputs (frozen dataclasses pine contract).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .types import BacktestResult, Metrics, WalkForwardSplit

# Metric keys grouped semantically (for table rendering).
_PER_FOLD_METRIC_KEYS: tuple[str, ...] = (
    "total_trades",
    "win_rate",
    "profit_factor",
    "final_equity",
    "max_drawdown",
    "cagr",
    "calmar_ratio",
    "sharpe_ratio",
    "sortino_ratio",
    "avg_trade_pnl",
    "expectancy",
)


@dataclass(frozen=True, slots=True)
class FoldReport:
    """Per-fold report aggregating per-symbol metrics + cross-fold metadata.

    Pine contract:
        - ``fold_id``: 0-based index; el caller determina el orden (F3b caller-side).
        - ``split``: ``WalkForwardSplit`` reference preserva train/test windows.
        - ``per_symbol_metrics``: dict estable ordenando por symbol al construirlo.
    """

    fold_id: int
    split: WalkForwardSplit
    per_symbol_metrics: dict[str, Metrics]


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Cross-fold report aggregating per-fold reports + global aggregate.

    Pine contract:
        - ``folds``: lista ordenada por ``fold_id`` ascendente.
        - ``global_aggregate_metrics``: ``Metrics`` promedio cross-fold.
          (mean simple por metric key; sin re-compute via ``_compute_metrics``
          per ADR-0012 F3a-phase-2 deferral).
    """

    folds: list[FoldReport]
    global_aggregate_metrics: Metrics


def build_fold_report(
    results: Sequence[BacktestResult],
    fold_id: int,
    split: WalkForwardSplit,
) -> FoldReport:
    """Build a per-fold report from per-symbol ``BacktestResult`` objects.

    Args:
        results: per-symbol ``BacktestResult`` from a single fold OOS window.
            Pine contract: lista NO-vacia; sort por symbol.
        fold_id: 0-based index (caller-controlled).
        split: ``WalkForwardSplit`` reference (train + test windows).

    Returns:
        ``FoldReport`` con ``per_symbol_metrics`` dict[alphabetical_symbol, Metrics].

    Raises:
        ValueError: si ``results`` esta vacia.
    """
    if not results:
        raise ValueError("build_fold_report: results must be non-empty")

    sorted_results = sorted(results, key=lambda r: r.symbol)
    per_symbol_metrics: dict[str, Metrics] = {r.symbol: r.metrics for r in sorted_results}
    return FoldReport(
        fold_id=fold_id,
        split=split,
        per_symbol_metrics=per_symbol_metrics,
    )


def build_walk_forward_report(
    fold_results: Sequence[Sequence[BacktestResult]],
    splits: Sequence[WalkForwardSplit],
) -> WalkForwardReport:
    """Build a cross-fold report from per-fold per-symbol results.

    Args:
        fold_results: outer = folds (in order); inner = per-symbol results.
            Debe tener misma longitud que ``splits``.
        splits: ``WalkForwardSplit`` por fold, en orden.

    Returns:
        ``WalkForwardReport`` con per-fold reports ordenados + global aggregate.

    Raises:
        ValueError: si ``len(fold_results) != len(splits)`` o si cualquier fold
            tiene results vacios.
    """
    if len(fold_results) != len(splits):
        raise ValueError(
            f"build_walk_forward_report: fold_results length ({len(fold_results)}) "
            f"!= splits length ({len(splits)})"
        )

    fold_reports: list[FoldReport] = []
    for fold_idx, (results, split) in enumerate(zip(fold_results, splits, strict=True)):
        fold_reports.append(build_fold_report(results, fold_idx, split))

    # Global aggregate: mean simple por metric key, cross-fold.
    # Cross-symbol averaging dentro de cada fold ya esta en build_fold_report.
    global_aggregate = _aggregate_metrics_cross_fold(fold_reports)

    return WalkForwardReport(
        folds=fold_reports,
        global_aggregate_metrics=global_aggregate,
    )


def _metric_value(metrics: Metrics, key: str) -> float:
    """Safely extract a metric value from a Metrics TypedDict.

    Returns 0.0 for missing keys (defensive default; should not occur
    in practice since the aggregator only iterates over ``_PER_FOLD_METRIC_KEYS``).
    """
    val = metrics.get(key, 0.0)
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _aggregate_metrics_cross_fold(folds: Sequence[FoldReport]) -> Metrics:
    """Mean simple por metric key cross-fold + cross-symbol (deterministic order).

    Doble-promedio:
        - Dentro de cada fold: mean per-symbol metrics (ponderado por total_trades
          si esta disponible; uniformemente si no).
        - Cross-fold: mean de los per-fold aggregates.

    Para F3a-phase-1 preferimos uniform-mean (simple, deterministico). F3a-phase-2
    re-implementara con weighted-mean + recompute via ``_compute_metrics`` + sort
    temporal de trades.
    """
    if not folds:
        raise ValueError("_aggregate_metrics_cross_fold: folds must be non-empty")

    # Step 1: aggregate per-fold (mean per-symbol).
    per_fold_aggregates: list[Metrics] = []
    for fold in folds:
        per_fold_aggregates.append(_average_metrics_within_fold(fold))

    # Step 2: aggregate cross-fold (mean).
    aggregate: dict[str, float] = {}
    for key in _PER_FOLD_METRIC_KEYS:
        values = [_metric_value(pf, key) for pf in per_fold_aggregates]
        if values:
            aggregate[key] = sum(values) / len(values)
        else:
            aggregate[key] = 0.0
    return aggregate  # type: ignore[return-value]


def _average_metrics_within_fold(fold: FoldReport) -> Metrics:
    """Mean simple per-symbol metrics dentro de un fold (F3a-phase-1 naive)."""
    if not fold.per_symbol_metrics:
        return {key: 0.0 for key in _PER_FOLD_METRIC_KEYS}  # type: ignore[return-value]

    aggregate: dict[str, float] = {}
    for key in _PER_FOLD_METRIC_KEYS:
        values = [_metric_value(m, key) for m in fold.per_symbol_metrics.values()]
        if values:
            aggregate[key] = sum(values) / len(values)
        else:
            aggregate[key] = 0.0
    return aggregate  # type: ignore[return-value]


def render_table(report: WalkForwardReport) -> str:
    """Render ``WalkForwardReport`` como ASCII table deterministico.

    Pine contract:
        - Pure function: retorna str (NO prints; caller decide I/O).
        - Sin emojis ni acentos decorativos (cross-locale grep-safe).
        - Si ``rich`` esta disponible, usa ``rich.table.Table`` con utf-8; sino
          fallback plain.
    """
    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        table = Table(
            title=f"Walk-Forward Report ({len(report.folds)} folds)",
            box=box.MINIMAL,
            show_header=True,
            header_style="bold",
        )
        table.add_column("Fold")
        table.add_column("Symbol")
        # Add one column per Metric key for FoldReport rows
        for key in _PER_FOLD_METRIC_KEYS:
            table.add_column(key)
        # Add global aggregate row
        for fold in report.folds:
            for symbol, metrics in sorted(fold.per_symbol_metrics.items()):
                row = [str(fold.fold_id), symbol]
                for key in _PER_FOLD_METRIC_KEYS:
                    v = metrics.get(key, 0.0)
                    row.append(_fmt_metric(key, v))
                table.add_row(*row)
        # Separator row + global aggregate
        empty_row = ["", "GLOBAL"]
        for key in _PER_FOLD_METRIC_KEYS:
            empty_row.append(_fmt_metric(key, report.global_aggregate_metrics.get(key, 0.0)))
        table.add_row(*empty_row)
        console = Console(record=True, width=200)
        console.print(table)
        return console.export_text()
    except ImportError:
        # Fallback: plain ASCII table aligned by key.
        return _render_plain(report)


def _render_plain(report: WalkForwardReport) -> str:
    """Plain ASCII table fallback (deterministic, no rich dep)."""
    headers = ["fold", "symbol", *_PER_FOLD_METRIC_KEYS]
    rows: list[list[str]] = []
    for fold in report.folds:
        for symbol, metrics in sorted(fold.per_symbol_metrics.items()):
            row = [str(fold.fold_id), symbol]
            for key in _PER_FOLD_METRIC_KEYS:
                row.append(_fmt_metric(key, metrics.get(key, 0.0)))
            rows.append(row)
    global_row = ["ALL", "global".upper()]
    for key in _PER_FOLD_METRIC_KEYS:
        global_row.append(_fmt_metric(key, report.global_aggregate_metrics.get(key, 0.0)))
    rows.append(global_row)

    # Column widths = max(len(header), max(len(row[col]), ...) for each col).
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
    lines: list[str] = []
    # Header line
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    # Separator
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    # Data lines
    for row in rows:
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
    return "\n".join(lines)


def _fmt_metric(key: str, value: object) -> str:
    """Format a metric value for table rendering; accepts object to handle
    TypedDict.get() result union (value type | default)."""
    """Format a metric value for table rendering. No decimal precision battles:
    use 4 decimals for ratios, 2 decimals for monetary, 'inf' literal for
    profit_factor == inf."""
    if not isinstance(value, (int, float)):
        return str(value)
    v = float(value)
    if v != v:  # NaN check
        return "nan"
    if v == float("inf"):
        return "inf"
    if v == float("-inf"):
        return "-inf"
    # Monetary metrics get 2 decimals; ratios get 4.
    if key in ("final_equity", "avg_trade_pnl", "expectancy"):
        return f"{v:.2f}"
    return f"{v:.4f}"


__all__ = [
    "FoldReport",
    "WalkForwardReport",
    "build_fold_report",
    "build_walk_forward_report",
    "render_table",
]
