"""Protocolos abstractos del OHLCV Scheduler.

Define el contrato que cualquier ``OHLCVSource`` implementador
(de ``OHLCVFetcher`` + ``OHLCVStore`` en produccion, o un fake
en tests) debe cumplir, asi como el contrato de ``PullMetricsSink``
para emitir logs estructurados.

Regla desacople (``docs/architecture.md`` §11 + §14, pineada por el
test ``tests/unit/scheduler/test_cross_layer.py`` en TSK-104.3b.5):

- ``OHLCVSourceProtocol`` se implementa en ``market_data/`` con la
  composicion ``OHLCVFetcher`` + ``OHLCVStore`` (TSK-102). El
  ``OHLCVScheduler`` (TSK-104.3 skeleton) NO importa
  ``fetcher.fetch_recent`` ni ``store.get_ohlcv`` directamente; solo
  conoce este Protocol + el ``OHLCVSourceProtocol``.
- ``ConnectorFactory`` se invoca una vez al boot o en
  ``connector_reinjector`` para construir el ``ExchangeConnector``
  correcto segun ``TradingMode`` (``paper``/``live`` con sandbox flag;
  ``backtest``/``research`` con None).
- ``PullMetricsSink`` lo implementa ``StructlogSink`` (F3b) para
  emitir los 7 eventos sin acoplar el scheduler a structlog.

Async: la implementacion CCXT en
``market_data/exchange_connector.py`` es async via Tenacity decorator;
``OHLCVFetcher`` envuelve ese async. El ``OHLCVScheduler`` invocara
estos metodos con ``await``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from trading_bot.config.runtime import TradingMode
from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.types import OHLCV
from trading_bot.scheduler.types import (
    CacheHitDecision,
    PullFailureReason,
    PullOutcome,
    SchedulerResult,
)


# ---------------------------------------------------------------------------
# OHLCVSourceProtocol — production wrapper sobre OHLCVFetcher + OHLCVStore.
#
# split: ``fetch_one`` (para pulls) y ``get_last_candle_ts``
# (para cache check) son async en el mismo objeto subyacente.
# ---------------------------------------------------------------------------
@runtime_checkable
class OHLCVSourceProtocol(Protocol):
    """Abstraccion sobre OHLCVFetcher + OHLCVStore (decision D-TSK104).

    ``runtime_checkable=True`` permite ``isinstance(fake,
    OHLCVSourceProtocol)`` en tests unitarios sin importar ABC. mypy
    strict + Protocol detecta implementaciones parciales en
    compile-time.

    Implementacion canonica de produccion:
    ``LiveOHLCVSource`` (envuelve ``OHLCVFetcher`` + ``OHLCVStore``)
    o ``DeterministicOHLCVSource`` (synthetic, para
    ``backtest``/``research``). Test scaffolding:
    ``tests.unit.scheduler.fake.FakeOHLCVSource``.

    Pine contract: el scheduler NO importa
    ``market_data.exchange_connector`` ni ``storage.ohlcv_store``
    directamente; solo este Protocol.
    """

    async def fetch_one(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[OHLCV]:
        """Pull + validate + cache; devuelve velas leidas del store.

        Raises:
            Exception: cualquier excepcion transitoria (timeout, 429,
                network) propaga al scheduler que decide retry. NO
                retorna lista vacia en error: el scheduler necesita
                distinguir success de failure.
        """
        ...

    async def get_last_candle_ts(self, symbol: str) -> int | None:
        """Devuelve el timestamp de la ultima vela en OHLCVStore, o None.

        Usado por CacheHitPredicate (RF-4) para evaluar la ventana
        de freshness. None si OHLCVStore no tiene velas para el par.
        """
        ...


# ---------------------------------------------------------------------------
# ConnectorFactory — Callable type alias.
#
# Pine contract: el scheduler NO instancia ``CCXTExchangeConnector``
# directamente; siempre delega a ``ConnectorFactory`` para que el
# caller (production wiring) pueda sustituir por ``FakeConnector``
# en tests. Pine contract tambien sobre ``OHLCVScheduler.__init__``:
# ``connector_factory=None`` es valido solo para modos
# ``research``/``backtest`` (synthetic source); cualquier intento de
# flip a ``paper``/``live``/``shadow_live`` con factory None levanta
# ``ConfigurationError`` (R1 opcion b verdict, F3b).
# ---------------------------------------------------------------------------
ConnectorFactory = Callable[[TradingMode], ExchangeConnector]


# ---------------------------------------------------------------------------
# PullMetricsSink — struktog + counters sink.
#
# NO es ``@runtime_checkable`` strict (los Protocols con metodos async
# tienen limitaciones en CPython 3.11's isinstance runtime check per
# spec del 03-specify §3). El test TSK-104.1.2 prueba el contrato via
# ``hasattr`` + ``callable``, mismo patron que ``Filter`` en scanner.
# mypy strict cubre la validacion compile-time.
# ---------------------------------------------------------------------------
class PullMetricsSink(Protocol):
    """Sink para emitir metricas (structlog + counters).

    Default: ``StructlogSink`` (envuelve structlog + CounterSnapshot
    interno). Tests usan ``InMemorySink`` que captura eventos para
    aserciones deterministas.

    Pine contract:
    - Cada metodo async se invoca UNA vez por evento correspondiente;
      NO se batchean (los counters se actualizan post-cada-event para
      que un crash del scheduler entre eventos preserve el historial
      parcial en structlog).
    - Los parametros son ``frozen+slots`` dataclasses del propio
      paquete (``PullOutcome``, ``CacheHitDecision``,
      ``SchedulerResult``); el sink NO los reconstruye, los acepta
      como API inmutable.
    """

    async def on_pull_completed(self, outcome: PullOutcome) -> None:
        """RF-6: pull exitoso. Pino en ``scheduler.pull.completed``."""
        ...

    async def on_pull_skipped(
        self,
        symbol: str,
        decision: CacheHitDecision,
    ) -> None:
        """RF-4 cache hit + RF-2 active_hours skip. Pino en
        ``scheduler.pull.skipped`` con ``reason`` discriminante."""
        ...

    async def on_pull_failed(
        self,
        symbol: str,
        reason: PullFailureReason,
        attempts: int,
    ) -> None:
        """CL-9 + RF-5 transient. Pino en ``scheduler.pull.failed``.
        ``attempts`` 0..max_retries (1 inicial + 3 retries = max 4)."""
        ...

    async def on_iteration_completed(
        self,
        result: SchedulerResult,
        early_exit: str | None,
    ) -> None:
        """Single emission point (03-specify §9.1): SIEMPRE al final
        del run_once con ``early_exit`` tag discriminante."""
        ...


__all__ = ["ConnectorFactory", "OHLCVSourceProtocol", "PullMetricsSink"]
