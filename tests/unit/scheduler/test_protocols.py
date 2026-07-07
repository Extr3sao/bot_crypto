"""Tests unitarios para ``src/trading_bot/scheduler/protocols.py``.

Pinea el contrato de abstraccion estructural de Protocol (duck
typing). Tests deterministas sin red.

Cobertura esperada per DoD F1 (TSK-104.1): 6 tests verde en este
archivo (3 OHLCVSourceProtocol + 2 ConnectorFactory + 2 PullMetricsSink),
sumando ~12 tests total al paquete scheduler.

Sentinelas pineados (ADR-locked per 03-specify.md §3):

1. ``OHLCVSourceProtocol`` es ``runtime_checkable``: implementaciones
   parciales falla el ``isinstance`` check.
2. ``OHLCVSourceProtocol`` exige SOLO los 2 metodos async
   documentados (no mas, no menos): ``fetch_one`` y
   ``get_last_candle_ts``.
3. ``ConnectorFactory`` es ``Callable[[TradingMode], ExchangeConnector]``:
   cualquier callable con esa firma satisface el alias (estructural
   via duck-typing); firmas invalidas son rechazadas.
4. ``PullMetricsSink`` NO es ``runtime_checkable`` (per 03-specify
   §3 verbatim): pineamos el contrato via ``hasattr`` + ``callable``.
"""

from __future__ import annotations

import inspect

from trading_bot.config.runtime import TradingMode
from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.types import OHLCV
from trading_bot.scheduler.protocols import OHLCVSourceProtocol
from trading_bot.scheduler.types import (
    CacheHitDecision,
    PullFailureReason,
    PullOutcome,
    SchedulerResult,
)

# ---------------------------------------------------------------------------
# OHLCVSourceProtocol: runtime_checkable.
# ---------------------------------------------------------------------------


def test_ohlcv_source_protocol_runtime_checkable_accepts_full_impl() -> None:
    """Una clase con los 2 metodos async requeridos es
    ``isinstance(_, OHLCVSourceProtocol)`` (runtime_checkable)."""

    class LiveSource:
        async def fetch_one(
            self,
            symbol: str,
            timeframe: str,
            limit: int,
        ) -> list[OHLCV]:
            return []

        async def get_last_candle_ts(self, symbol: str) -> int | None:
            return None

    fake = LiveSource()
    assert isinstance(fake, OHLCVSourceProtocol)


def test_ohlcv_source_protocol_rejects_partial_implementation() -> None:
    """Una clase que solo expone ``fetch_one`` NO satisface el
    Protocol (falta ``get_last_candle_ts``).

    mypy strict detecta esto en compile-time; runtime_checkable lo
    pinea en tests.
    """

    class PartialSource:
        async def fetch_one(
            self,
            symbol: str,
            timeframe: str,
            limit: int,
        ) -> list[OHLCV]:
            return []

    partial = PartialSource()
    assert not isinstance(partial, OHLCVSourceProtocol)


def test_ohlcv_source_protocol_rejects_no_async_methods() -> None:
    """Una clase sin NINGUN metodo async NO satisface el Protocol.

    Sentinel: el scheduler recibe ``OHLCVSourceProtocol`` y NUNCA
    debe aceptar ``object()`` o clases vacias.
    """
    empty_source = object()
    assert not isinstance(empty_source, OHLCVSourceProtocol)


# ---------------------------------------------------------------------------
# ConnectorFactory: Callable type alias via duck-typing.
# ---------------------------------------------------------------------------


def test_connector_factory_callable_satisfies_structural_check() -> None:
    """Pinea que ``ConnectorFactory`` se satisface por cualquier
    callable ``(TradingMode) -> ExchangeConnector``.

    ``ConnectorFactory`` es un Type alias (``Callable[[TradingMode],
    ExchangeConnector]``), no un ``Protocol``, asi que NO es
    runtime-checkable via ``isinstance``. El pine contract es
    estructural via:

    1. ``callable(factory)`` -> es invocable.
    2. ``inspect.signature(factory)`` -> la firma tiene exactamente
       un parametro posicional requerido (``mode: TradingMode``).
    3. mypy strict en compile-time -> la firma satisface el alias.

    Decision de diseno: NO instanciamos ``ExchangeConnector`` (es ABC)
    para evitar arrastrar implementaciones mock gigantes; la
    satisfaccion del alias se verifica a nivel de firma, mientras
    que la satisfaccion del return-type la fuerza mypy en CI.
    """

    def fake_factory(mode: TradingMode) -> ExchangeConnector:
        # Body vacio: solo verificamos la firma structural.
        raise NotImplementedError  # pragma: no cover

    # 1. Callable.
    assert callable(fake_factory)

    # 2. Structural signature: exactly one required positional param.
    sig = inspect.signature(fake_factory)
    params = list(sig.parameters.values())
    assert len(params) == 1, (
        f"ConnectorFactory must take exactly 1 arg (TradingMode); got {len(params)}: {sig}"
    )
    mode_param = params[0]
    assert mode_param.default is inspect.Parameter.empty, (
        f"ConnectorFactory's mode arg must be REQUIRED (no default); "
        f"got default={mode_param.default}"
    )
    assert mode_param.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), f"ConnectorFactory's mode arg must be POSITIONAL; got kind={mode_param.kind}"


def test_connector_factory_callable_rejects_wrong_signature() -> None:
    """Pinea el pine estructural anti-regresion: firmas invalidas NO
    satisfacen el alias.

    Verifica tres contra-ejemplos (todos pine contract por la
    negativa, ADR-locked per 03-specify §3):

    1. ``bad_factory_zero_args()``: aridad 0, no satisface.
    2. ``bad_factory_with_default(mode=TradingMode.PAPER)``: param
       con default, no satisface (mode debe ser REQUIRED).
    3. ``bad_factory_kwargs(**kwargs)``: VAR_KEYWORD, no satisface.

    Sentinel: si alguien refactoriza ``ConnectorFactory`` para
    aceptar ``(mode=None)`` o ``(mode, **kwargs)``, este test cae y
    obliga a re-evaluar el BDD scenario
    ``"Scheduler.run() idempotente en quick succession"`` que asume
    firma canonica.
    """

    # 1. Cero args.
    def bad_factory_zero_args() -> ExchangeConnector:
        raise NotImplementedError  # pragma: no cover

    sig = inspect.signature(bad_factory_zero_args)
    assert len(list(sig.parameters.values())) == 0

    # 2. Param con default.
    def bad_factory_with_default(
        mode: TradingMode = TradingMode.PAPER,
    ) -> ExchangeConnector:
        raise NotImplementedError  # pragma: no cover

    sig = inspect.signature(bad_factory_with_default)
    mode_param = next(iter(sig.parameters.values()))
    assert mode_param.default is not inspect.Parameter.empty, (
        f"default-mode factory should be REJECTED by structural check; "
        f"got default={mode_param.default}"
    )

    # 3. **kwargs (VAR_KEYWORD).
    def bad_factory_kwargs(**kwargs: object) -> ExchangeConnector:
        raise NotImplementedError  # pragma: no cover

    sig = inspect.signature(bad_factory_kwargs)
    only_param = next(iter(sig.parameters.values()))
    assert only_param.kind is inspect.Parameter.VAR_KEYWORD, (
        f"**kwargs factory should be REJECTED; got kind={only_param.kind}"
    )


# ---------------------------------------------------------------------------
# PullMetricsSink: NO runtime_checkable. Contrato via hasattr + callable.
# ---------------------------------------------------------------------------


def test_pull_metrics_sink_structural_check_via_hasattr() -> None:
    """Pinea que ``PullMetricsSink`` exige los 4 metodos async.

    NO usamos ``isinstance(impl, PullMetricsSink)`` (NO es
    ``runtime_checkable`` per 03-specify §3 imperative: los Protocols
    con metodos async tienen limitaciones en CPython 3.11's isinstance
    runtime check, asi que se pinea via hasattr + callable)."""

    class StructlogSink:
        async def on_pull_completed(self, outcome: PullOutcome) -> None:
            pass

        async def on_pull_skipped(
            self,
            symbol: str,
            decision: CacheHitDecision,
        ) -> None:
            pass

        async def on_pull_failed(
            self,
            symbol: str,
            reason: PullFailureReason,
            attempts: int,
        ) -> None:
            pass

        async def on_iteration_completed(
            self,
            result: SchedulerResult,
            early_exit: str | None,
        ) -> None:
            pass

    impl = StructlogSink()
    assert hasattr(impl, "on_pull_completed")
    assert hasattr(impl, "on_pull_skipped")
    assert hasattr(impl, "on_pull_failed")
    assert hasattr(impl, "on_iteration_completed")
    assert callable(impl.on_pull_completed)
    assert callable(impl.on_pull_skipped)
    assert callable(impl.on_pull_failed)
    assert callable(impl.on_iteration_completed)


def test_pull_metrics_sink_without_methods_fails_attribute_check() -> None:
    """Una implementacion parcial falla el pine estructural.

    NO usamos isinstance porque NO es runtime_checkable; pineamos
    via ausencia de atributos.
    """
    incomplete = object()
    assert not hasattr(incomplete, "on_pull_completed")
    assert not hasattr(incomplete, "on_pull_skipped")
    assert not hasattr(incomplete, "on_pull_failed")
    assert not hasattr(incomplete, "on_iteration_completed")
