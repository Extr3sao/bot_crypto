"""Connector CCXT con sandbox + idempotencia + whitelist de exchanges.

Diseño (TSK-101, sprint-002 Pri 3 — ver verdict del thinker y
`context/retrieval-log.md` entradas 2026-07-03/04):

- ``ExchangeConnector`` es ``ABC`` para permitir un futuro
  ``BacktestExchangeConnector`` (Fase 6) sin cambiar el dominio.
- ``CCXTExchangeConnector`` envuelve ``ccxt.Exchange`` con reintentos
  Tenacity y trazas structlog.
- **Sandbox** se activa ANTES de ``load_markets()`` para que CCXT no
  cachee URLs de producción.
- **Idempotencia** en ``create_order``: el caller pasa un
  ``client_order_id``; si no, el connector genera un UUIDv4 y lo lo
  reusa en cada intento de retry, de modo que el exchange puede
  deduplicar la orden si la red cayó a mitad del POST.
- **Request_id** se regenera por llamada (no por intento) y se
  vincula a structlog para correlacionar trazas.
- **Reintentos** son exponenciales con jitter (thundering herd) y
  SOLO sobre excepciones transitorias (red, rate limit, DDoS guard).
- ``load_markets()`` NO se reintenta: si falla, fail-fast el
  arranque (regla del repo).

Pacing de CCXT (master switch vs override) — pinear explicito:
- ``{"enableRateLimit": True}`` es el **MASTER SWITCH** que activa el
  rate-limiter interno de ccxt. Sin este flag, CCXT NO pacea y recae
  en el rate-limit del exchange (HTTP 429). El override YAML
  ``options.enableRateLimit=false`` lo desactiva — aceptable solo en
  tests unitarios (mock).
- ``self._exchange_instance.rateLimit = config.rate_limit_ms`` (ms
  entre requests) sobreescribe el delay por defecto de CCXT cuando
  está definido en YAML.
- **NO se duplican**: CCXT pacea ANTES del POST (rate-limit ms wait);
  tenacity reintenta POST-falla (backoff exponencial con jitter).

Alcance multi-exchange (P2 — entry 2026-07-04 02:00):
- ``SUPPORTED_EXCHANGES_FOR_TSK_101`` es un frozenset explícito con
  los IDs cubiertos por los tests sandbox actuales. TSK-101 sólo
  prueba contra Binance. Cualquier otro ``config.id`` falla en
  ``__init__`` con ``ValueError`` ANTES de llamar a
  ``getattr(ccxt, ...)``, para que tests de rechazo funcionen sin
  necesidad de parchear ``ccxt``.
- La capa de mapping por adapter (``clientOid`` para Coinbase,
  ``clOrdID`` para OKX, ``orderLinkId`` para Bybit, etc.) queda como
  alcance del ticket multi-exchange (TSK-105). CCXT v4+ ya traduce
  ``clientOrderId`` para los adapters principales (Binance, Kraken,
  Coinbase Pro, OKX, Bybit), pero NO probamos esa traducción
  exhaustivamente en TSK-101.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, Final

import ccxt
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from trading_bot.config.exchange import Exchange
from trading_bot.market_data.types import (
    CCXTOHLCVProtocol,
    CCXTPayloadProtocol,
    OHLCV,
    Balance,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
    narrow_ccxt_ohlcv,
    narrow_ccxt_payload,
)

# Excepciones que justifican reintento. NO incluyen errores semánticos
# (InvalidOrder, InsufficientFunds, AuthenticationError) que nunca se
# resuelven con un retry.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
)


class UnmappedOrderStatusError(RuntimeError):
    """CCXT devolvió un status fuera del whitelist.

    ``RuntimeError`` y no ``AssertionError``: este último se desactiva
    con ``python -O``, lo que silenciaría el fail en producción.
    Forzar ADR firmada en ``tasks/decisions.md`` y añadir el status al
    whitelist ``_KNOWN_STATUS_MAP`` antes de continuar.
    """


# IDs de exchange sandbox-testeados con este connector. TSK-101 sólo
# cubre Binance. Cualquier ampliación (Coinbase, Bybit, OKX, Kraken...)
# requiere un ticket dedicado con sandbox testing y la confirmación de
# que el adapter traduce ``clientOrderId`` y emite los mismos status
# canónicos.
SUPPORTED_EXCHANGES_FOR_TSK_101: Final[frozenset[str]] = frozenset({"binance", "bitunix"})

# Scope descriptivo del ticket multi-exchange (TSK-105). Se usa en
# mensajes de error para que el caller sepa dónde abrir la incidencia.
# El valor está pineado SIN caracteres regex especiales (paréntesis,
# puntos, corchetes) para que ``pytest.raises(match=MULTI_EXCHANGE_SCOPE)``
# se comporte como búsqueda literal y no como ``re.search``. El ID
# literal del ticket se cita solo en docstrings/comentarios, no en el
# valor runtime-tested.
MULTI_EXCHANGE_SCOPE: Final[str] = "multi-exchange sandbox verification"


# Whitelist de status que CCXT puede devolver, mapeados al Literal
# ``OrderStatus`` de ``types.py``. Case-insensitive. Si CCXT introduce
# un status nuevo, AÑADIRLO aquí + ADR firmada. NO hay fallback
# silencioso: cualquier status no contemplado o ausente rompe loud vía
# ``UnmappedOrderStatusError``.
#
# P1 — entry 2026-07-04 02:00 — incluye ``partially_filled`` (CCXT
# canonical de orden parcialmente ejecutada pero aún en libro). Sin
# este mapeo, una orden EXITOSA con partial fill se elevaba como
# excepción post-POST y el caller podía reintentar y duplicar la
# posición. NO añadimos aliases defensivos tipo ``partial_fill``: CCXT
# v4 canonicaliza via ``unify_order_status`` y si un adapter emite
# algo no-canónico debe romper loud per ADR lock convention para
# forzar la corrección del adapter.
_KNOWN_STATUS_MAP: Final[dict[str, OrderStatus]] = {
    "open": "open",
    "new": "open",  # alias Binance para "open"
    "partially_filled": "partially_filled",  # CCXT canonical (P1 fix)
    "closed": "closed",
    "filled": "closed",  # ccxt canonical synonym
    "canceled": "canceled",
    "cancelled": "canceled",  # US/UK spelling
    "rejected": "rejected",
    "expired": "expired",
}


class ExchangeConnector(ABC):
    """Interfaz pública del conector; abstracción sobre CCXT o stubs."""

    @abstractmethod
    def load_markets(self) -> None:
        """Descarga metadatos. Fail-fast; sin reintento."""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        """Devuelve ``limit`` velas OHLCV más recientes."""

    @abstractmethod
    def fetch_balance(self) -> list[Balance]:
        """Devuelve balances por asset con campos ``free``/``used``/``total``."""

    @abstractmethod
    def create_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        """Crea una orden. ``client_order_id`` se reutiliza en cada retry."""

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancela una orden existente."""

    @property
    @abstractmethod
    def sandbox_enabled(self) -> bool:
        """True si el conector opera en sandbox."""


class CCXTExchangeConnector(ExchangeConnector):
    """Adapter CCXT v4+. Único connector concreto en TSK-101."""

    def __init__(self, config: Exchange) -> None:
        # Whitelist check ANTES de cualquier getattr/ccxt lookup para
        # que un exchange no soportado falle con mensaje claro sin
        # necesidad de monkeypatchar ``ccxt`` en los tests.
        if config.id not in SUPPORTED_EXCHANGES_FOR_TSK_101:
            raise ValueError(
                f"Exchange '{config.id}' no está cubierto por TSK-101. "
                f"Soportados actualmente: "
                f"{sorted(SUPPORTED_EXCHANGES_FOR_TSK_101)}. "
                f"Ampliación a otros exchanges corresponde al scope "
                f"'{MULTI_EXCHANGE_SCOPE}'."
            )

        self._config = config
        # Bind lazy por instancia + nombre de módulo explícito: cada log
        # JSON queda atribuible a `trading_bot.market_data.exchange_connector`
        # en observabilidad. `_log_name` se almacena como atributo para
        # que tests puedan verificar la atribuibilidad sin inspeccionar
        # `__class__` del wrapper de structlog (que devolvería el módulo
        # interno de structlog, no el nuestro).
        self._log_name = self.__class__.__module__
        self._log = structlog.get_logger(self._log_name)

        exchange_class = getattr(ccxt, config.id)
        options: dict[str, Any] = {
            "enableRateLimit": True,
            "apiKey": config.api_key,
            "secret": config.api_secret,
        }
        if config.password:
            options["password"] = config.password
        # `enableRateLimit: True` evita llamar a `wait` manual: ccxt pacea
        # las requests para no chocar con el rate limit del exchange.
        # Config del usuario sobreescribe si lo define en `options`.
        options.update(config.options)
        self._exchange_instance: ccxt.Exchange = exchange_class(options)

        if config.rate_limit_ms is not None:
            # Override del rate-limit por defecto de CCXT (ms entre requests).
            self._exchange_instance.rateLimit = config.rate_limit_ms
        self._exchange_instance.timeout = config.timeouts.request_ms

        if config.sandbox:
            # Importante: ANTES de `load_markets()` — si se hace después,
            # ccxt puede tener URLs de producción pre-cargadas en caché.
            self._exchange_instance.set_sandbox_mode(True)
            self._log.info(
                "connector_sandbox_enabled",
                exchange=config.id,
                ex_req_ms=config.timeouts.request_ms,
            )

        # Decorador per-instance: usa los parámetros del YAML del
        # exchange concreto (no globales) — distinto exchange puede
        # tener límites distintos.
        self._retry_decorator = retry(
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            wait=wait_exponential_jitter(
                initial=config.retries.initial_backoff_ms / 1000.0,
                max=config.retries.max_backoff_ms / 1000.0,
            ),
            stop=stop_after_attempt(config.retries.max_attempts),
            reraise=True,
        )

    @property
    def sandbox_enabled(self) -> bool:
        return self._config.sandbox

    # ------------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------------
    def load_markets(self) -> None:
        """Sin reintento — si falla, fail-fast."""
        log = self._log.bind(exchange=self._config.id)
        try:
            self._exchange_instance.load_markets()
            log.info("markets_loaded", sandbox=self._config.sandbox)
        except Exception:
            log.error("load_markets_failed", exc_info=True)
            raise

    # ------------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        request_id = str(uuid.uuid4())
        log = self._log.bind(
            req_id=request_id,
            op="fetch_ohlcv",
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        @self._retry_decorator
        def _execute() -> CCXTOHLCVProtocol:
            return narrow_ccxt_ohlcv(
                self._exchange_instance.fetch_ohlcv(symbol, timeframe, limit=limit)
            )

        log.info("fetch_ohlcv_start")
        try:
            raw = _execute()
        except Exception:
            log.error("fetch_ohlcv_failed", exc_info=True)
            raise

        # P1 round-2 (TSK-102): ``symbol`` se inyecta en cada vela. ccxt
        # filtra por ``symbol`` upstream (``fetch_ohlcv(symbol, ...)``
        # ya filtra server-side), asi que todos los rows pertenecen al
        # mismo par; pinearlo en el dataclass permite que el store
        # persista la PK compuesta ``(symbol, timestamp)`` de forma
        # limpia sin perdida de metadata.
        ohlcv_list = [
            OHLCV(
                symbol=symbol,
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in raw
        ]
        log.info("fetch_ohlcv_ok", n=len(ohlcv_list))
        return ohlcv_list

    def fetch_balance(self) -> list[Balance]:
        request_id = str(uuid.uuid4())
        log = self._log.bind(req_id=request_id, op="fetch_balance")

        @self._retry_decorator
        def _execute() -> CCXTPayloadProtocol:
            return narrow_ccxt_payload(self._exchange_instance.fetch_balance())

        try:
            raw = _execute()
        except Exception:
            log.error("fetch_balance_failed", exc_info=True)
            raise

        balances = [
            Balance(
                asset=asset,
                free=float(data["free"]),
                used=float(data["used"]),
                total=float(data["total"]),
            )
            for asset, data in raw.items()
            if isinstance(data, dict) and "total" in data
        ]
        log.info("fetch_balance_ok", n_assets=len(balances))
        return balances

    # ------------------------------------------------------------------------
    # Write operations (idempotent)
    # ------------------------------------------------------------------------
    def create_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        # El connector genera el client_order_id SOLO si el caller no
        # aporta uno. En ambos casos, el CIERRE (`_execute` más abajo)
        # captura ese mismo id, así tenacity reusa el mismo valor en cada
        # intento → exchange deduplica.
        #
        # CCXT v4 unifica ``clientOrderId`` para los adapters principales
        # (Binance, Kraken, OKX, Bybit, Coinbase Pro); TSK-101 sólo
        # cubre Binance. Multi-exchange mapping (clientOid, clOrdID,
        # orderLinkId) queda en ``MULTI_EXCHANGE_SCOPE``.
        cid = client_order_id or str(uuid.uuid4())
        params: dict[str, Any] = {"clientOrderId": cid}

        request_id = str(uuid.uuid4())
        log = self._log.bind(
            req_id=request_id,
            op="create_order",
            symbol=symbol,
            side=side,
            type=order_type,
            client_order_id=cid,
        )

        @self._retry_decorator
        def _execute() -> CCXTPayloadProtocol:
            return narrow_ccxt_payload(
                self._exchange_instance.create_order(
                    symbol,
                    type=order_type,
                    side=side,
                    amount=amount,
                    price=price,
                    params=params,
                )
            )

        log.info("create_order_start")
        try:
            res = _execute()
        except Exception:
            log.error("create_order_failed", exc_info=True)
            raise

        log.info(
            "create_order_ok",
            exchange_id=res["id"],
            status=res.get("status"),
        )
        return OrderResult(
            id=str(res["id"]),
            client_order_id=cid,
            symbol=str(res["symbol"]),
            status=self._normalize_status(res.get("status")),
            side=side,
            type=order_type,
            price=float(res.get("price", price or 0.0)),
            amount=float(res["amount"]),
            filled=float(res.get("filled", 0.0)),
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:
        request_id = str(uuid.uuid4())
        log = self._log.bind(req_id=request_id, op="cancel_order", order_id=order_id, symbol=symbol)

        @self._retry_decorator
        def _execute() -> None:
            self._exchange_instance.cancel_order(order_id, symbol)

        log.info("cancel_order_start")
        try:
            _execute()
        except Exception:
            log.error("cancel_order_failed", exc_info=True)
            raise
        log.info("cancel_order_ok")

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------
    @staticmethod
    def _normalize_status(raw: str | None) -> OrderStatus:
        """Mapea status de CCXT al ``OrderStatus`` Literal.

        Whitelist estricto: si CCXT añade un status nuevo, debe
        mapearse en ``_KNOWN_STATUS_MAP`` (acción: ADR firmada + PR).
        NO hay fallback silencioso: ``None``, string vacío, o status
        desconocido rompen loud vía ``UnmappedOrderStatusError`` para
        forzar la actualización del whitelist en lugar de aceptar
        silenciosamente un status inválido que podría romper reglas
        de negocio downstream.
        """
        if not raw or not raw.strip():
            raise UnmappedOrderStatusError(f"missing or empty status from ccxt (raw={raw!r})")
        key = raw.strip().lower()
        if key in _KNOWN_STATUS_MAP:
            return _KNOWN_STATUS_MAP[key]
        raise UnmappedOrderStatusError(
            f"Unmapped ccxt order_status: {raw!r}. "
            "Add to _KNOWN_STATUS_MAP and file an ADR in tasks/decisions.md."
        )


__all__ = [
    "MULTI_EXCHANGE_SCOPE",
    "RETRYABLE_EXCEPTIONS",
    "SUPPORTED_EXCHANGES_FOR_TSK_101",
    # Whitelist versionada. Exportada explícitamente para que tests la
    # importen sin F401/private-import warnings. Cambios requieren ADR
    # firmada en tasks/decisions.md.
    "_KNOWN_STATUS_MAP",
    "CCXTExchangeConnector",
    "ExchangeConnector",
    "UnmappedOrderStatusError",
]
