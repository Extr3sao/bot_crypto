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

import math
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
from trading_bot.market_data.exceptions import ConnectorProtocolError
from trading_bot.market_data.types import (
    OHLCV,
    Balance,
    CCXTOHLCVProtocol,
    CCXTPayloadProtocol,
    ExchangeMarketType,
    MarketRules,
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


# IDs de exchange soportados por este connector. TSK-101 cubrió Binance
# (sandbox); se amplió a bitunix (TSK-022) y a bybit (spot, demo trading
# vía ``enable_demo_trading``). Cualquier otra ampliación (Coinbase, OKX,
# Kraken...) requiere un ticket dedicado con sandbox testing y la
# confirmación de que el adapter traduce ``clientOrderId`` y emite los
# mismos status canónicos.
SUPPORTED_EXCHANGES_FOR_TSK_101: Final[frozenset[str]] = frozenset({"binance", "bitunix", "bybit"})

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
            if config.demo_trading:
                # Bybit Demo Trading (api-demo.*): entorno virtual con fondos
                # demo. CCXT lanza NotSupported si sandbox mode ya está
                # activo, así que demo_trading y sandbox son mutuamente
                # excluyentes (fail-fast abajo para ids no-bybit).
                if config.id != "bybit":
                    raise ValueError(
                        f"demo_trading=True solo está soportado para bybit, recibido {config.id!r}."
                    )
                self._exchange_instance.enable_demo_trading(True)
                self._log.info(
                    "connector_demo_trading_enabled",
                    exchange=config.id,
                    ex_req_ms=config.timeouts.request_ms,
                )
            else:
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

    def fetch_24h_volume_usdt(self, symbol: str) -> float:
        """Volumen rolling 24h en USDT desde el ticker (``quoteVolume``).

        Datos reales del exchange (ticker público), nunca fabricados. Si el
        ticker no expone ``quoteVolume`` o el valor no es convertible, se
        devuelve ``0.0``: el ``VolumeFilter`` del scanner rechazará el par
        (fail-closed), en vez de inventar un volumen.
        """
        request_id = str(uuid.uuid4())
        log = self._log.bind(req_id=request_id, op="fetch_24h_volume_usdt", symbol=symbol)

        @self._retry_decorator
        def _execute() -> CCXTPayloadProtocol:
            return narrow_ccxt_payload(self._exchange_instance.fetch_ticker(symbol))

        log.info("fetch_24h_volume_usdt_start")
        try:
            raw = _execute()
        except Exception:
            log.error("fetch_24h_volume_usdt_failed", exc_info=True)
            raise

        quote_volume = raw.get("quoteVolume")
        if quote_volume is None:
            log.warning("fetch_24h_volume_usdt_missing_quote_volume", symbol=symbol)
            return 0.0
        try:
            volume = float(quote_volume)
        except (TypeError, ValueError):
            log.warning("fetch_24h_volume_usdt_invalid_quote_volume", symbol=symbol)
            return 0.0
        if volume < 0:
            log.warning("fetch_24h_volume_usdt_negative_quote_volume", symbol=symbol)
            return 0.0
        log.info("fetch_24h_volume_usdt_ok", volume_usdt=volume, symbol=symbol)
        return volume

    def fetch_spread_bps(self, symbol: str) -> float:
        """Spread top-of-book en bps desde el ticker (``bid``/``ask``).

        Datos reales del exchange, nunca fabricados. Sin ``bid``/``ask``
        válidos se devuelve ``inf``: el ``SpreadFilter`` rechazará el par
        (fail-closed), en vez de simular un spread de 0 bps.
        """
        request_id = str(uuid.uuid4())
        log = self._log.bind(req_id=request_id, op="fetch_spread_bps", symbol=symbol)

        @self._retry_decorator
        def _execute() -> CCXTPayloadProtocol:
            return narrow_ccxt_payload(self._exchange_instance.fetch_ticker(symbol))

        log.info("fetch_spread_bps_start")
        try:
            raw = _execute()
        except Exception:
            log.error("fetch_spread_bps_failed", exc_info=True)
            raise

        bid = raw.get("bid")
        ask = raw.get("ask")
        if bid is None or ask is None:
            log.warning("fetch_spread_bps_missing_bid_ask", symbol=symbol)
            return float("inf")
        try:
            bid_f = float(bid)
            ask_f = float(ask)
        except (TypeError, ValueError):
            log.warning("fetch_spread_bps_invalid_bid_ask", symbol=symbol)
            return float("inf")
        mid = (bid_f + ask_f) / 2.0
        if mid <= 0:
            log.warning("fetch_spread_bps_invalid_mid", symbol=symbol)
            return float("inf")
        spread = ((ask_f - bid_f) / mid) * 10_000.0
        log.info("fetch_spread_bps_ok", spread_bps=spread, symbol=symbol)
        return spread

    def fetch_market_rules(self, symbol: str) -> MarketRules:
        """Reglas de negociación del símbolo desde el catálogo ``markets``.

        Lee el catálogo local de CCXT (poblado por ``load_markets()``): quote,
        estado, mínimos (``limits.cost.min`` / ``limits.amount.min``) y
        precisión de redondeo (``precision.amount``/``precision.price``).
        Datos reales del exchange, nunca fabricados.

        Fail-closed:
        - Catálogo no cargado (``load_markets()`` pendiente) o símbolo ausente
          → ``ConnectorProtocolError`` (no se inventan reglas; el hub exige
          ``load_markets()`` explícito, fail-fast como el resto del arranque).
        - ``quote`` ausente → ``ConnectorProtocolError`` (no se puede
          determinar la divisa de cotización).
        - Límites ausentes → ``0.0`` (sin mínimo declarado: el ejecutor aplica
          sus propias reglas de risk, p. ej. ``risk.min_order_notional_usdt``).
        - Precisión ausente/no convertible → 8 decimales (default conservador;
          el redondeo hacia abajo nunca sobrepasa el tamaño aceptado).
        """
        request_id = str(uuid.uuid4())
        log = self._log.bind(
            req_id=request_id, op="fetch_market_rules", symbol=symbol, exchange=self._config.id
        )
        log.info("fetch_market_rules_start")
        markets = self._exchange_instance.markets
        if not markets:
            log.error("fetch_market_rules_markets_not_loaded", symbol=symbol)
            raise ConnectorProtocolError(
                f"{self._config.id} aún no tiene el catálogo de markets cargado: "
                "llama a load_markets() antes de fetch_market_rules (fail-closed, "
                "sin reglas fabricadas)."
            )
        try:
            market = markets[symbol]
        except KeyError:
            log.error("fetch_market_rules_symbol_not_in_catalog", symbol=symbol)
            raise ConnectorProtocolError(
                f"{self._config.id} no lista {symbol!r} en su catálogo de "
                "markets; no se fabrican reglas para un par desconocido "
                "(fail-closed)."
            ) from None

        quote = market.get("quote")
        if not quote:
            log.error("fetch_market_rules_missing_quote", symbol=symbol)
            raise ConnectorProtocolError(
                f"{self._config.id} no expone quote para {symbol!r}; sin "
                "divisa de cotización no se pueden resolver las reglas "
                "(fail-closed)."
            )

        limits = market.get("limits") or {}
        cost = limits.get("cost") or {}
        amount = limits.get("amount") or {}
        precision = market.get("precision") or {}
        rules = MarketRules(
            symbol=symbol,
            is_open=bool(market.get("active", True)),
            quote=str(quote),
            min_trade_value_usdt=self._limit_to_float(cost.get("min")),
            min_volume=self._limit_to_float(amount.get("min")),
            base_precision=self._precision_to_decimals(precision.get("amount")),
            quote_precision=self._precision_to_decimals(precision.get("price")),
        )
        log.info(
            "fetch_market_rules_ok",
            is_open=rules.is_open,
            quote=rules.quote,
            min_trade_value_usdt=rules.min_trade_value_usdt,
            min_volume=rules.min_volume,
            base_precision=rules.base_precision,
            quote_precision=rules.quote_precision,
        )
        return rules

    @staticmethod
    def _limit_to_float(value: Any) -> float:
        """Convierte un límite del catálogo CCXT a float; ausente → ``0.0``."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _precision_to_decimals(value: Any) -> int:
        """Normaliza la precisión CCXT a decimales de redondeo.

        CCXT puede expresar precisión como decimal places (int, p. ej. ``8``)
        o como tick size (float, p. ej. ``0.00000001``). Ambos se reducen a
        ``decimals`` para ``MarketRules.round_*``. Un valor ausente o no
        convertible cae a 8 decimales (default conservador).
        """
        if value is None:
            return 8
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 8
        if numeric >= 1.0:
            return int(numeric)
        if numeric > 0.0:
            return max(0, round(math.log10(1.0 / numeric)))
        return 8

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
    # Reliability-primitive support (SHADOW-AND-LEGACY-VALIDATION-01, Track D).
    # Additive surface required by ExecutionGateway ACK-recovery and fill
    # reconciliation. Inherited by Binance/Bybit/Bitunix adapters.
    # ------------------------------------------------------------------------

    def fetch_order_query(self, client_order_id: str, symbol: str) -> dict[str, Any] | None:
        """Query an order by STABLE client_order_id (ACK_UNKNOWN recovery).

        Returns the normalized order payload when the venue knows the
        order, ``None`` when the venue definitively does not know it, and
        propagates transport failure for the caller to classify as
        UNCERTAIN (never guessed here).

        Semantics per exchange family:
        - ``ccxt``-canonical: ``fetch_order(None, symbol, params={'clientOrderId': cid})``.
        - Binance/Bybit/Bitunix accept the client id in ``originalClientOrderId``
          / ``orderLinkId`` / ``clientOrderId`` params respectively; unknown
          ids surface as a ``ccxt.OrderNotFound`` (-> ``None``).
        """
        request_id = str(uuid.uuid4())
        log = self._log.bind(
            req_id=request_id, op="fetch_order_query", symbol=symbol, client_order_id=client_order_id
        )

        @self._retry_decorator
        def _execute() -> CCXTPayloadProtocol | None:
            return narrow_ccxt_payload(
                self._exchange_instance.fetch_order(
                    None, symbol, params={"clientOrderId": client_order_id}
                )
            )

        log.info("fetch_order_query_start")
        try:
            res = _execute()
        except ccxt.OrderNotFound:
            # Venue definitively does not know this client id -> ABSENT.
            log.info("fetch_order_query_absent")
            return None
        except Exception:
            log.error("fetch_order_query_failed", exc_info=True)
            raise

        if res is None or not res.get("id"):
            # Some adapters return an empty payload for unknown ids.
            log.info("fetch_order_query_absent")
            return None
        log.info("fetch_order_query_ok", exchange_id=res["id"])
        return {k: res[k] for k in res}

    def fetch_recent_fills(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        """Recent venue fills for idempotent fill reconciliation.

        Maps ccxt ``fetch_my_trades`` (symbol-scoped). Fill identity is the
        venue trade id; the gateway's FillLedger deduplicates by it.
        """
        request_id = str(uuid.uuid4())
        log = self._log.bind(req_id=request_id, op="fetch_recent_fills", symbol=symbol)

        @self._retry_decorator
        def _execute() -> list[CCXTPayloadProtocol]:
            raw = self._exchange_instance.fetch_my_trades(symbol, limit=limit)
            if not isinstance(raw, list):
                raise RuntimeError("protocol violation: fetch_my_trades must return a list")
            return [narrow_ccxt_payload(t) for t in raw]

        log.info("fetch_recent_fills_start")
        try:
            trades = _execute()
        except Exception:
            log.error("fetch_recent_fills_failed", exc_info=True)
            raise

        fills: list[dict[str, Any]] = []
        for t in trades:
            fills.append(
                {
                    "fill_id": str(t.get("id") or ""),
                    "order_id": str(t.get("order") or ""),
                    "symbol": str(t.get("symbol") or symbol),
                    "side": str(t.get("side") or ""),
                    "price": float(t.get("price") or 0.0),
                    "amount": float(t.get("amount") or 0.0),
                    "fee": float((t.get("fee") or {}).get("cost", 0.0) or 0.0),
                    "timestamp": t.get("timestamp"),
                }
            )
        log.info("fetch_recent_fills_ok", count=len(fills))
        return fills

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


class BinanceConnector(CCXTExchangeConnector):
    """Adapter Binance del hub multi-exchange (TSK-022.4, RF-MX-2).

    Implementa ``MultiExchangeConnector`` reutilizando toda la lógica CCXT
    de ``CCXTExchangeConnector`` (sandbox ANTES de ``load_markets()``, rate
    limit, timeouts, retries idempotentes con ``client_order_id``, guards
    ``narrow_ccxt_payload``/``narrow_ccxt_ohlcv`` y whitelist estricta de
    ``OrderStatus``) sin duplicarla.

    ``CCXTExchangeConnector`` se conserva como clase genérica de
    compatibilidad TSK-101 (whitelist ``SUPPORTED_EXCHANGES_FOR_TSK_101``);
    el nuevo wiring multi-exchange usa ``BinanceConnector``.

    Identidad del target: ``exchange_id == "binance"``,
    ``market_type == "spot"``. El sandbox sigue controlado por
    ``config.sandbox`` (default paper + sandbox).
    """

    exchange_id: str = "binance"
    market_type: ExchangeMarketType = "spot"

    def __init__(self, config: Exchange) -> None:
        # Fail-fast de identidad: un adapter "Binance" no debe construirse
        # sobre un config de otro exchange (mismo patrón whitelist TSK-101).
        if config.id != "binance":
            raise ValueError(
                f"BinanceConnector exige config.id='binance', recibido "
                f"{config.id!r}. Para otros exchanges del whitelist TSK-101 "
                "usa CCXTExchangeConnector."
            )
        super().__init__(config)


class BybitConnector(CCXTExchangeConnector):
    """Adapter Bybit (spot) del hub multi-exchange — demo trading.

    Reutiliza la lógica CCXT de ``CCXTExchangeConnector`` sin duplicarla
    (retries idempotentes, rate limit, guards ``narrow_ccxt_*`` y whitelist
    de ``OrderStatus``).

    Entorno: el target ``sandbox: true`` mapea a **Demo Trading** de Bybit
    (``api-demo.bybit.com``) vía ``config.demo_trading``, NO a testnet: las
    API keys creadas bajo "Demo Trading" solo funcionan contra el entorno
    demo, y CCXT prohíbe combinar ``enable_demo_trading`` con
    ``set_sandbox_mode``. Con ``sandbox: false`` (live) se usan las URLs de
    producción.

    Identidad del target: ``exchange_id == "bybit"``,
    ``market_type == "spot"``.
    """

    exchange_id: str = "bybit"
    market_type: ExchangeMarketType = "spot"

    def __init__(self, config: Exchange) -> None:
        # Fail-fast de identidad: un adapter "Bybit" no debe construirse
        # sobre un config de otro exchange (mismo patrón whitelist TSK-101).
        if config.id != "bybit":
            raise ValueError(
                f"BybitConnector exige config.id='bybit', recibido "
                f"{config.id!r}. Para otros exchanges del whitelist TSK-101 "
                "usa CCXTExchangeConnector."
            )
        super().__init__(config)


__all__ = [
    "MULTI_EXCHANGE_SCOPE",
    "RETRYABLE_EXCEPTIONS",
    "SUPPORTED_EXCHANGES_FOR_TSK_101",
    # Whitelist versionada. Exportada explícitamente para que tests la
    # importen sin F401/private-import warnings. Cambios requieren ADR
    # firmada en tasks/decisions.md.
    "_KNOWN_STATUS_MAP",
    "BinanceConnector",
    "BybitConnector",
    "CCXTExchangeConnector",
    "ExchangeConnector",
    "UnmappedOrderStatusError",
]
