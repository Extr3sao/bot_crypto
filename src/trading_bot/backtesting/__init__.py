"""Backtesting engine public API (TSK-104 F1 + F2 + F3).

Pine contract:
- F1: ``BacktestEngine.run(symbol, ...) -> BacktestResult``.
- F2: pluggable ``CommissionModel`` / ``SlippageModel`` + 7 advanced metrics.
- F3 (este PR): ``run(symbol: str | list[str], ...) -> BacktestResult | list[BacktestResult]``
  + ``walk_forward_run(inputs: BacktestInputs) -> list[list[BacktestResult]]``
  + ``WalkForwardSplit`` frozen dataclass + ``BacktestInputs`` TypedDict.
"""

from .commissions import CommissionModel, FlatPctCommission, TieredCommission
from .engine import BacktestEngine
from .slippage import FlatBpsSlippage, SlippageModel, VolumeImpactSlippage
from .types import (
    OHLCV,
    BacktestInputs,
    BacktestResult,
    EquityPoint,
    Fill,
    Metrics,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
    WalkForwardSplit,
)

__all__ = [
    "OHLCV",
    "BacktestEngine",
    "BacktestInputs",
    "BacktestResult",
    "CommissionModel",
    "EquityPoint",
    "Fill",
    "FlatBpsSlippage",
    "FlatPctCommission",
    "Metrics",
    "OHLCVSourceProtocol",
    "Order",
    "SlippageModel",
    "StrategyProtocol",
    "TieredCommission",
    "Trade",
    "VolumeImpactSlippage",
    "WalkForwardSplit",
]
