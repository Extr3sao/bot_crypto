"""Composition root del hub multi-exchange (TSK-022.7).

Construye ``MultiExchangeConnectorRegistry`` desde ``Settings`` reales y
resuelve el connector de la sesión a partir de ``runtime.exchange_id`` sin
fallback silencioso. Es el único lugar que conoce los adapters concretos
(``BinanceConnector``, ``BitunixSpotConnector``, ``BitunixFuturesConnector``);
``scanner``/``strategies``/``execution`` reciben únicamente el Protocol por
inyección de dependencias (frontera RF-MX-4 / ADR-0013).

Contrato (`03-specify.md` §2.2, §5, §6):

- ``build_multi_exchange_registry(settings)``: targets desde
  ``settings.universe.exchanges`` (identity ``(id, type)``; clave por ``id``
  porque solo un tipo puede estar habilitado por id) y factories solo para
  targets habilitados. Un target habilitado sin adapter soportado falla
  fail-fast con ``MultiExchangeConfigurationError`` listando los adapters
  soportados (CL-5/CL-12).
- ``resolve_runtime_connector(settings, *, session_id)``: resuelve
  ``runtime.exchange_id``; ``exchange_id`` vacío o desconocido falla loud
  (CL-2/CL-4). Emite los eventos canónicos ``multi_exchange.*`` del §6 y
  envuelve el connector en un proxy de observabilidad que conserva
  ``session_id``/``request_id`` por llamada. No captura ni convierte errores:
  ``UnsupportedConnectorOperationError`` y los errores de los adapters se
  relanzan (tratamiento explícito de capacidades no soportadas).
- Sin secretos: las credenciales viven en ``settings.exchange`` (legacy
  single-tenant) o en env vars de Bitunix; ningún evento loguea keys.
- Construcción 100% lazy: el registry no toca red ni llama a
  ``load_markets()`` en el constructor (RF-MX-7); la factory corre solo en el
  primer ``resolve``.

Este módulo NO se reexporta desde ``trading_bot.market_data.__init__``: la
frontera pública del paquete sigue siendo de tipos (``MultiExchangeConnector``
+ canónicos), no de wiring concreto.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

import structlog

from trading_bot.market_data.exceptions import MultiExchangeConfigurationError
from trading_bot.market_data.multi_exchange import MultiExchangeConnectorRegistry
from trading_bot.market_data.types import (
    OHLCV,
    Balance,
    ExchangeMarketType,
    MarketRules,
    MultiExchangeConnector,
    OrderResult,
    OrderType,
    Side,
)

if TYPE_CHECKING:
    from trading_bot.config.settings import Settings
    from trading_bot.config.universe import ExchangeTarget
    from trading_bot.market_data.scanner_bridge import HubMarketDataSource

_T = TypeVar("_T")

_log = structlog.get_logger(__name__)

# Adapter builders: (id, market_type) -> factory(settings, target).
# El builder NO recibe ni emite secretos: Binance usa `settings.exchange`
# (credenciales singulares legacy §5.3); Bitunix usa clientes que leen sus
# env vars existentes (BITUNIX_API_KEY / BITUNIX_API_SECRET).
AdapterBuilder = Callable[["Settings", "ExchangeTarget"], MultiExchangeConnector]


def _binance_builder(settings: Settings, target: ExchangeTarget) -> MultiExchangeConnector:
    from trading_bot.market_data.exchange_connector import BinanceConnector

    # Credenciales/rate-limit del config singular; id y sandbox del target.
    exchange = settings.exchange.model_copy(update={"id": "binance", "sandbox": target.sandbox})
    return BinanceConnector(exchange)


def _bitunix_spot_builder(settings: Settings, target: ExchangeTarget) -> MultiExchangeConnector:
    from trading_bot.market_data.bitunix import BitunixSpotClient, BitunixSpotConnector

    return BitunixSpotConnector(BitunixSpotClient(), sandbox=target.sandbox)


def _bybit_spot_builder(settings: Settings, target: ExchangeTarget) -> MultiExchangeConnector:
    from trading_bot.market_data.exchange_connector import BybitConnector

    # Bybit demo (sandbox: true del target) => ``demo_trading``: las API keys
    # de Demo Trading de Bybit solo valen contra api-demo.*, y CCXT prohíbe
    # combinarlo con set_sandbox_mode (testnet). Credenciales/rate-limit del
    # config singular; id y sandbox/demo del target.
    exchange = settings.exchange.model_copy(
        update={
            "id": "bybit",
            "sandbox": target.sandbox,
            "demo_trading": target.sandbox,
        }
    )
    return BybitConnector(exchange)


def _bitunix_futures_builder(settings: Settings, target: ExchangeTarget) -> MultiExchangeConnector:
    from trading_bot.market_data.bitunix_futures import (
        BitunixFuturesClient,
        BitunixFuturesConnector,
    )

    return BitunixFuturesConnector(BitunixFuturesClient(), sandbox=target.sandbox)


_ADAPTER_BUILDERS: dict[tuple[str, ExchangeMarketType], AdapterBuilder] = {
    ("binance", "spot"): _binance_builder,
    ("bitunix", "spot"): _bitunix_spot_builder,
    ("bitunix", "futures"): _bitunix_futures_builder,
    ("bybit", "spot"): _bybit_spot_builder,
}


def _supported_adapters() -> list[str]:
    """Adaptadores soportados, ordenados, para mensajes de error (CL-5/CL-12)."""
    return sorted(f"{exchange_id}/{market_type}" for exchange_id, market_type in _ADAPTER_BUILDERS)


def build_multi_exchange_registry(
    settings: Settings,
    *,
    adapter_builders: Mapping[tuple[str, ExchangeMarketType], AdapterBuilder] | None = None,
) -> MultiExchangeConnectorRegistry:
    """Construye el registry desde ``Settings`` (targets + factories lazy).

    Un target habilitado sin adapter soportado falla aquí (fail-fast antes de
    iniciar sesión) listando los adapters conocidos; nunca se ignora un id
    habilitado. Targets deshabilitados permanecen en el mapping para que
    ``resolve`` de un id deshabilitado produzca ``MultiExchangeResolutionError``
    en lugar de un falso "desconocido".

    ``adapter_builders`` permite inyectar builders alternativos (tests/fakes)
    sin tocar los adapters concretos; por defecto usa los del hub.
    """
    builders = _ADAPTER_BUILDERS if adapter_builders is None else adapter_builders
    targets: dict[str, ExchangeTarget] = {}
    for target in settings.universe.exchanges:
        current = targets.get(target.id)
        # (id, type) repite el id (bitunix spot + futures): gana el habilitado;
        # si ninguno lo está, el primero declarado sirve para el error.
        if current is None or (target.enabled and not current.enabled):
            targets[target.id] = target

    enabled_targets = [t for t in settings.universe.exchanges if t.enabled]
    if not enabled_targets:
        # BDD escenario 11 / RF-MX-3: configuración sin targets habilitados es
        # un warning observable, nunca una llamada externa (el registry queda
        # vacío y sin factories → cero conexiones).
        _log.warning("multi_exchange.config.no_enabled_exchanges")

    unsupported = [
        target
        for target in settings.universe.exchanges
        if target.enabled and (target.id, target.type) not in builders
    ]
    if unsupported:
        detail = ", ".join(
            f"{t.id}/{t.type}" for t in sorted(unsupported, key=lambda t: (t.id, t.type))
        )
        raise MultiExchangeConfigurationError(
            "Targets habilitados sin adapter soportado: "
            f"{detail}. Adaptadores soportados: {_supported_adapters()}."
        )

    factory_by_id: dict[str, Callable[[], MultiExchangeConnector]] = {}
    for target in settings.universe.exchanges:
        if not target.enabled:
            continue
        builder = builders[(target.id, target.type)]
        # Closure con binding por parámetro: cada factory captura SU target.
        factory_by_id[target.id] = _make_factory(builder, settings, target)

    return MultiExchangeConnectorRegistry(targets=targets, factory_by_id=factory_by_id)


def _make_factory(
    builder: AdapterBuilder,
    settings: Settings,
    target: ExchangeTarget,
) -> Callable[[], MultiExchangeConnector]:
    """Cierra (builder, settings, target) en una factory sin argumentos (registry)."""

    def _factory() -> MultiExchangeConnector:
        return builder(settings, target)

    return _factory


class _ObservedConnector:
    """Proxy de observabilidad canónica ``multi_exchange.*`` (spec §6).

    Envuelve un ``MultiExchangeConnector`` sin modificarlo: la observabilidad
    de sesión vive en el composition root. Cada operación emite
    ``multi_exchange.call.{started,completed,failed}`` con ``session_id`` y un
    ``request_id`` estable para esa llamada. No captura ni convierte errores:
    ``UnsupportedConnectorOperationError`` y demás se relanzan tal cual.
    """

    def __init__(self, inner: MultiExchangeConnector, *, session_id: str) -> None:
        self._inner = inner
        self._session_id = session_id
        # Miembros de datos del Protocol (settable): se copian del inner para
        # que el proxy satisfaga ``MultiExchangeConnector`` estructuralmente
        # (mypy exige variables asignables, no read-only properties).
        self.exchange_id: str = inner.exchange_id
        self.market_type: ExchangeMarketType = inner.market_type

    @property
    def sandbox_enabled(self) -> bool:
        return self._inner.sandbox_enabled

    def _base(self, operation: str, **extra: Any) -> Any:
        return _log.bind(
            exchange_id=self.exchange_id,
            market_type=self.market_type,
            sandbox=self.sandbox_enabled,
            operation=operation,
            session_id=self._session_id,
            **extra,
        )

    def _call(self, operation: str, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        request_id = str(uuid.uuid4())
        log = self._base(operation, request_id=request_id)
        log.info("multi_exchange.call.started")
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            # Solo clase de error y request_id: nunca bodies ni secretos (§6).
            log.error("multi_exchange.call.failed", error_type=type(exc).__name__)
            raise
        log.info("multi_exchange.call.completed")
        return result

    def load_markets(self) -> None:
        self._call("load_markets", self._inner.load_markets)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        return self._call("fetch_ohlcv", self._inner.fetch_ohlcv, symbol, timeframe, limit)

    def fetch_24h_volume_usdt(self, symbol: str) -> float:
        return self._call("fetch_24h_volume_usdt", self._inner.fetch_24h_volume_usdt, symbol)

    def fetch_spread_bps(self, symbol: str) -> float:
        return self._call("fetch_spread_bps", self._inner.fetch_spread_bps, symbol)

    def fetch_market_rules(self, symbol: str) -> MarketRules:
        return self._call("fetch_market_rules", self._inner.fetch_market_rules, symbol)

    def fetch_balance(self) -> list[Balance]:
        return self._call("fetch_balance", self._inner.fetch_balance)

    def create_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        return self._call(
            "create_order",
            self._inner.create_order,
            symbol,
            side,
            order_type,
            amount,
            price=price,
            client_order_id=client_order_id,
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:
        self._call("cancel_order", self._inner.cancel_order, order_id, symbol)


def resolve_runtime_connector(
    settings: Settings,
    *,
    session_id: str,
    adapter_builders: Mapping[tuple[str, ExchangeMarketType], AdapterBuilder] | None = None,
) -> MultiExchangeConnector:
    """Resuelve el connector de la sesión (composition root, RF-MX-6).

    - ``session_id`` es obligatorio: la observabilidad del §6 lo exige.
    - ``runtime.exchange_id`` vacío → ``MultiExchangeConfigurationError`` con
      guía de fix (CL-4); desconocido/deshabilitado → error del registry con
      los IDs habilitados ordenados (CL-2). Nunca fallback a Binance.
    - Emite ``multi_exchange.connector.resolve.{started,resolved}`` y
      ``multi_exchange.connector.sandbox_enabled``, y devuelve el connector
      envuelto en ``_ObservedConnector`` (eventos ``multi_exchange.call.*``).
    """
    if not session_id or not session_id.strip():
        raise ValueError(
            "session_id es obligatorio en el composition root (spec §6 observabilidad)."
        )

    exchange_id = settings.runtime.exchange_id
    if not exchange_id or not exchange_id.strip():
        raise MultiExchangeConfigurationError(
            "runtime.exchange_id vacío: configura RUNTIME_EXCHANGE_ID o "
            "runtime.exchange_id en config/runtime.yaml antes de arrancar (CL-4)."
        )

    log = _log.bind(exchange_id=exchange_id, session_id=session_id)
    log.info("multi_exchange.connector.resolve.started")

    registry = build_multi_exchange_registry(settings, adapter_builders=adapter_builders)
    connector = registry.resolve(exchange_id)

    resolved_log = _log.bind(
        exchange_id=connector.exchange_id,
        market_type=connector.market_type,
        sandbox=connector.sandbox_enabled,
        session_id=session_id,
    )
    resolved_log.info("multi_exchange.connector.resolved")
    resolved_log.info("multi_exchange.connector.sandbox_enabled")

    return _ObservedConnector(connector, session_id=session_id)


def resolve_scanner_source(
    settings: Settings,
    *,
    session_id: str,
    timeframe: str | None = None,
) -> HubMarketDataSource:
    """Composition root del scanner: connector del hub envuelto en el puente async.

    Resuelve ``runtime.exchange_id`` contra ``universe.exchanges`` (el mismo
    connector que usa el resto de la sesión) y lo adapta a
    ``MarketDataSourceProtocol`` para ``UniverseScanner``. El timeframe se
    toma de ``settings.universe.timeframes[0]`` salvo override explícito.

    Sin fallback silencioso: si el exchange no resuelve, falla loud (CL-4).
    """
    from trading_bot.market_data.scanner_bridge import HubMarketDataSource

    connector = resolve_runtime_connector(settings, session_id=session_id)
    if timeframe is None:
        timeframes = settings.universe.timeframes
        if not timeframes:
            raise MultiExchangeConfigurationError(
                "universe.timeframes vacío: el scanner necesita un timeframe "
                "para el puente al hub (resolve_scanner_source)."
            )
        timeframe = timeframes[0]
    return HubMarketDataSource(connector, timeframe=timeframe)


__all__ = [
    "AdapterBuilder",
    "MultiExchangeConnectorRegistry",
    "build_multi_exchange_registry",
    "resolve_runtime_connector",
    "resolve_scanner_source",
]
