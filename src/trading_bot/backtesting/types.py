"""Tipos y protocolos del backtest engine (TSK-104 F1).

Pine contract (TSK-104 F1 + docs/backtesting-methodology.md):

- ``Order``, ``Fill``, ``Trade``, ``EquityPoint``, ``BacktestResult`` son
  frozen dataclasses con ``slots=True``: inmutables y serializables.
- ``OHLCV`` es frozen dataclass con ``timestamp: int`` (epoch ms) para
  mantener consistencia con ``trading_bot.market_data.types.OHLCV``;
  el adapter ``OHLCVStoreSource`` (F2) convierte entre formatos si es
  necesario.
- ``OHLCVSourceProtocol`` y ``StrategyProtocol`` son
  ``@runtime_checkable`` Protocols: cualquier clase que implemente
  los métodos listados pasa ``isinstance(x, Protocol)``.
- ``BacktestContext`` provee estado running (equity, posicion, precio)
  a la estrategia en cada ``on_candle``.

Anti-patterns (no deben regressar):

- NO hacer ``Order``/``Fill``/``Trade`` mutables: romperia el
  determinismo (mismo input -> misma output).
- NO importar ``OHLCVStore`` directamente: F1 esta desacoplado
  del storage layer via Protocol; F2 anadira el adapter.
- NO usar ``datetime.datetime`` en el timestamp de ``OHLCV``:
  inconsistency con market_data types.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, runtime_checkable


@dataclass(frozen=True, slots=True)
class OHLCV:
    """Vela OHLCV usada por el backtest engine.

    El timestamp es epoch ms (int) por consistencia con
    ``trading_bot.market_data.types.OHLCV``. F2 anadira
    ``OHLCVStoreSource`` que adaptara de epoch ms a este formato.
    """

    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Order:
    """Orden generada por la estrategia. Inmutable post-creacion."""

    id: str
    symbol: str
    side: Literal["buy", "sell"]
    qty: float
    type: str  # "market" | "limit" (F1 solo implementa market)
    timestamp: int
    limit_price: float | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    """Fill ejecutado por el engine. Inmutable."""

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    qty_filled: float
    fill_price: float
    commission: float
    slippage: float
    timestamp: int


@dataclass(frozen=True, slots=True)
class Trade:
    """Trade completo: entry fill + exit fill + PnL realizado."""

    entry_fill: Fill
    exit_fill: Fill
    pnl: float
    pnl_pct: float
    bars_held: int


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """Snapshot de equity en un timestamp. Usado para equity curve."""

    timestamp: int
    equity: float
    drawdown_pct: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Resultado consolidado de un backtest run."""

    strategy_name: str
    symbol: str
    timeframe: str
    start: datetime.datetime
    end: datetime.datetime
    initial_capital: float
    final_equity: float
    trades: list[Trade]
    equity_curve: list[EquityPoint]
    metrics: Metrics


@dataclass(frozen=True, slots=True)
class BacktestContext:
    """Estado running que el engine pasa a la estrategia en cada candle.

    Piensa en esto como el snapshot del portfolio al momento de
    ``on_candle``: equity disponible, posicion abierta, precio actual.
    La estrategia lo lee (no lo modifica; frozen) para decidir si
    emitir una ``Order``.
    """

    symbol: str
    current_time: int  # epoch ms
    current_price: float
    equity: float
    position_qty: float
    position_avg_price: float


class Metrics(TypedDict):
    """Contrato del payload ``BacktestResult.metrics`` (TSK-104 F2).

    Pine contract:
    - F1 baseline (4 keys): ``total_trades``, ``win_rate``,
      ``profit_factor``, ``final_equity``.
    - F2 advanced (7 keys adicionales): ``max_drawdown``, ``cagr``,
      ``calmar_ratio``, ``sharpe_ratio``, ``sortino_ratio``,
      ``avg_trade_pnl``, ``expectancy``.

    Units (CRITICAL):
    - ``expectancy``, ``avg_trade_pnl``, ``final_equity``:
      **monetary units (USDT)**. ``expectancy`` formula =
      ``(win_rate * avg_win) - (loss_rate * avg_loss)`` (Van K. Tharp),
      returns USD per trade promedio.
    - ``profit_factor``: **dimensionless ratio** (``gross_profit / gross_loss``,
      both in USD, so the ratio cancels out). Values < 1.0 mean net loss
      (0.0 = no wins at all); values >= 1.0 mean profitable; ``float('inf')``
      when all trades are winners.
    - ``win_rate`` (0..1), ``max_drawdown`` (0..1 as fraction),
      ``cagr``, ``sharpe_ratio``, ``sortino_ratio``, ``calmar_ratio``:
      **dimensionless ratios** / percentages / annualized.

    Todas las keys son obligatorias: si no hay trades, los valores
    derivados (win_rate, profit_factor, sharpe, etc.) se devuelven
    como ``0.0`` (o ``float('inf')`` para ``profit_factor`` cuando
    hay ganancias y ninguna perdida).
    """

    # F1 baseline
    total_trades: float
    win_rate: float
    profit_factor: float
    final_equity: float
    # F2 advanced
    max_drawdown: float
    cagr: float
    calmar_ratio: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_trade_pnl: float
    expectancy: float


@runtime_checkable
class OHLCVSourceProtocol(Protocol):
    """Contrato que cualquier fuente de velas OHLCV debe cumplir.

    F1 provee ``FakeOHLCVSource`` (in-memory) en tests.
    F2 anadira ``OHLCVStoreSource`` que envuelve el ``OHLCVStore``
    real (TSK-102) cuando se mergea a main.
    """

    def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
        """Itera velas en orden cronologico ascendente.

        ``start`` y ``end`` son epoch ms. La implementacion debe
        respetar el orden (sin reordenamiento aleatorio) para
        preservar determinismo.
        """
        ...


@runtime_checkable
class StrategyProtocol(Protocol):
    """Contrato que cualquier estrategia backtestable debe cumplir.

    La estrategia recibe el ``BacktestContext`` (estado running) y el
    ``OHLCV`` (candle actual). Retorna ``None`` si no hay senal, o
    una ``Order`` si quiere operar.
    """

    @property
    def name(self) -> str:
        """Nombre de la estrategia (usado en metricas / reports)."""
        ...

    def on_candle(self, ctx: BacktestContext, candle: OHLCV) -> Order | None:
        """Decide si emitir una orden dado el estado y la vela actual."""
        ...


__all__ = [
    "OHLCV",
    "BacktestContext",
    "BacktestResult",
    "EquityPoint",
    "Fill",
    "Metrics",
    "OHLCVSourceProtocol",
    "Order",
    "StrategyProtocol",
    "Trade",
]
