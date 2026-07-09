"""Backtest engine (TSK-104).

Fase objetivo: 6.

Componentes:
- ``Engine``: itera velas y emite ordenes simuladas. Pine contract:
  mismo input -> misma output (determinismo).
- ``Commissions``: fee model configurable (F2: ``CommissionModel``
  protocol + ``FlatPctCommission`` + ``TieredCommission``).
- ``Slippage``: modelo configurable (F2: ``SlippageModel`` protocol
  + ``FlatBpsSlippage`` + ``VolumeImpactSlippage``).
- ``Metrics``: 4 baseline (F1) + 7 advanced (F2): win_rate,
  profit_factor, expectancy, drawdown, Sharpe, Sortino, CAGR,
  Calmar, n trades, avg trade pnl, etc.
- ``WalkForward``: separacion train/test con avance (F3, ADR-0007).

F2 status: F1 + commission/slippage refinados (Protocol-based,
pluggable) + 7 metricas advanced. Engine acepta tanto ``float``
(backward compat) como modelos explicitos.
"""

from .commissions import CommissionModel, FlatPctCommission, TieredCommission
from .engine import BacktestEngine
from .reports import FoldReport, build_fold_report
from .slippage import FlatBpsSlippage, SlippageModel, VolumeImpactSlippage
from .types import (
    OHLCV,
    BacktestContext,
    BacktestResult,
    EquityPoint,
    Fill,
    Metrics,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
)
from .walk_forward_reports import (
    MetricAggregate,
    WalkForwardAggregateReport,
    build_walk_forward_aggregate,
    build_walk_forward_aggregate_payload,
    render_walk_forward_aggregate_markdown,
)

__all__ = [
    "OHLCV",
    "BacktestContext",
    "BacktestEngine",
    "BacktestResult",
    "CommissionModel",
    "EquityPoint",
    "Fill",
    "FlatBpsSlippage",
    "FlatPctCommission",
    "MetricAggregate",
    "Metrics",
    "OHLCVSourceProtocol",
    "Order",
    "SlippageModel",
    "StrategyProtocol",
    "TieredCommission",
    "Trade",
    "VolumeImpactSlippage",
    "WalkForwardAggregateReport",
    "build_fold_report",
    "build_walk_forward_aggregate",
    "build_walk_forward_aggregate_payload",
    "render_walk_forward_aggregate_markdown",
]
