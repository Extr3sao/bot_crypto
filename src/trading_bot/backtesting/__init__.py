"""Backtest engine (TSK-104).

Fase objetivo: 6.

Componentes:
- ``Engine``: itera velas y emite ordenes simuladas. Pine contract:
  mismo input -> misma output (determinismo). Comisiones y slippage
  flat-pct en F1; F2 introducira modelos mas finos.
- ``Commissions``: fee model configurable (F2: tiered, maker/taker).
- ``Slippage``: modelo configurable (F2: volume-weighted, random).
- ``Metrics``: win rate, profit factor, expectancy, drawdown,
  Sharpe aprox., Sortino aprox., n trades, mejor/peor trade,
  racha max perdidas, ratio B/R, etc. (F2 anadira los que faltan;
  F1 solo calcula 4 baseline).
- ``WalkForward``: separacion train/test con avance (F3, ADR-0007).

F1 status: implementa ``Engine`` skeleton + tipos + protocolos.
La data source es un ``OHLCVSourceProtocol``; F1 provee un fake
in-memory para tests, F2 anadira un adapter sobre ``OHLCVStore``
(TSK-102) cuando se mergea a main.
"""

from .engine import BacktestEngine
from .types import (
    OHLCV,
    BacktestContext,
    BacktestResult,
    EquityPoint,
    Fill,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
)

__all__ = [
    "OHLCV",
    "BacktestContext",
    "BacktestEngine",
    "BacktestResult",
    "EquityPoint",
    "Fill",
    "OHLCVSourceProtocol",
    "Order",
    "StrategyProtocol",
    "Trade",
]
