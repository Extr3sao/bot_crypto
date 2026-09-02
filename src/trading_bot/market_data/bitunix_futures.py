"""Bitunix futures REST helpers.

Basado en la documentacion oficial de Bitunix Futures:
- Place order: POST /api/v1/futures/trade/place_order
- Get pending positions: GET /api/v1/futures/position/get_pending_positions
- Flash close position: POST /api/v1/futures/trade/flash_close_position
- Place TP/SL order: POST /api/v1/futures/tpsl/place_order
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Final
from urllib.error import HTTPError

import structlog

from trading_bot.market_data.bitunix import BitunixAPIError, to_api_symbol
from trading_bot.market_data.exceptions import (
    ConnectorProtocolError,
    UnsupportedConnectorOperationError,
)
from trading_bot.market_data.types import (
    OHLCV,
    Balance,
    CCXTPayloadProtocol,
    ExchangeMarketType,
    MarketRules,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
    narrow_ccxt_payload,
)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _format_decimal(value: float, decimals: int | None = None) -> str:
    text = f"{value:.12f}" if decimals is None else f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") or "0"


@dataclass(frozen=True, slots=True)
class BitunixFuturesPosition:
    position_id: str
    symbol: str
    qty: float
    side: str
    margin_mode: str
    position_mode: str
    leverage: int
    margin: float
    unrealized_pnl: float
    realized_pnl: float
    avg_open_price: float
    liquidation_price: float


@dataclass(frozen=True, slots=True)
class BitunixFuturesAccount:
    margin_coin: str
    available: float
    frozen: float
    margin: float
    transferable: float
    position_mode: str
    cross_unrealized_pnl: float
    isolation_unrealized_pnl: float
    bonus: float


@dataclass(frozen=True, slots=True)
class BitunixFuturesSymbol:
    symbol: str
    base: str
    quote: str
    min_trade_volume: float
    max_market_order_volume: float
    base_precision: int
    quote_precision: int
    max_leverage: int
    min_leverage: int
    default_leverage: int
    symbol_status: str
    is_api_supported: bool


class BitunixFuturesClient:
    """Minimal futures client for Bitunix."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        futures_base_url: str = "https://fapi.bitunix.com",
    ) -> None:
        # Bloom-hygiene v1 (consistency w/ bitunix.py): kwarg value wins; fall back to env-var
        # if kwarg is empty (canonical case for direct script callers). No literal
        # credentials stored in this module.
        self.api_key = api_key or os.getenv("BITUNIX_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BITUNIX_API_SECRET", "")
        self.futures_base_url = futures_base_url.rstrip("/")
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )
        self._symbol_cache: dict[str, BitunixFuturesSymbol] | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.futures_base_url}{path}"
        if query:
            url = f"{url}?{query}"

        body = ""
        raw_body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            raw_body = body.encode("utf-8")

        request = urllib.request.Request(url, data=raw_body, method=method.upper())
        request.add_header("User-Agent", self.user_agent)
        request.add_header("Accept", "application/json, text/plain, */*")
        request.add_header("Content-Type", "application/json")

        if auth:
            if not self.api_key or not self.api_secret:
                raise BitunixAPIError("Bitunix Futures API key/secret no configurados.")
            nonce = secrets.token_hex(16)
            timestamp = str(int(time.time() * 1000))
            sorted_query = "".join(f"{key}{(params or {})[key]}" for key in sorted(params or {}))
            digest = _sha256_hex(nonce + timestamp + self.api_key + sorted_query + body)
            sign = _sha256_hex(digest + self.api_secret)
            request.add_header("api-key", self.api_key)
            request.add_header("nonce", nonce)
            request.add_header("timestamp", timestamp)
            request.add_header("sign", sign)
            request.add_header("language", "en-US")

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload_json = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise BitunixAPIError(f"HTTP {exc.code}: {error_body}") from exc

        code = str(payload_json.get("code"))
        if code != "0":
            msg = payload_json.get("msg") or "Unknown Bitunix Futures error"
            raise BitunixAPIError(f"{msg} (code={code})")
        return payload_json.get("data")

    def get_pending_positions(self, symbol: str | None = None) -> list[BitunixFuturesPosition]:
        params = {"symbol": to_api_symbol(symbol)} if symbol else None
        rows = self._request(
            "GET",
            "/api/v1/futures/position/get_pending_positions",
            params=params,
            auth=True,
        )
        positions: list[BitunixFuturesPosition] = []
        for row in rows:
            positions.append(
                BitunixFuturesPosition(
                    position_id=str(row["positionId"]),
                    symbol=str(row["symbol"]),
                    qty=float(row.get("qty", 0) or 0),
                    side=str(row.get("side", "")),
                    margin_mode=str(row.get("marginMode", "")),
                    position_mode=str(row.get("positionMode", "")),
                    leverage=int(row.get("leverage", 0) or 0),
                    margin=float(row.get("margin", 0) or 0),
                    unrealized_pnl=float(row.get("unrealizedPNL", 0) or 0),
                    realized_pnl=float(row.get("realizedPNL", 0) or 0),
                    avg_open_price=float(row.get("avgOpenPrice", 0) or 0),
                    liquidation_price=float(row.get("liqPrice", 0) or 0),
                )
            )
        return positions

    def get_account(self, margin_coin: str = "USDT") -> BitunixFuturesAccount:
        rows = self._request(
            "GET",
            "/api/v1/futures/account",
            params={"marginCoin": margin_coin.upper()},
            auth=True,
        )
        if isinstance(rows, dict):
            row = rows
        elif rows:
            row = rows[0]
        else:
            raise BitunixAPIError(f"No se devolvio cuenta futures para marginCoin={margin_coin}.")
        return BitunixFuturesAccount(
            margin_coin=str(row.get("marginCoin", margin_coin)).upper(),
            available=float(row.get("available", 0) or 0),
            frozen=float(row.get("frozen", 0) or 0),
            margin=float(row.get("margin", 0) or 0),
            transferable=float(row.get("transfer", 0) or 0),
            position_mode=str(row.get("positionMode", "")),
            cross_unrealized_pnl=float(row.get("crossUnrealizedPNL", 0) or 0),
            isolation_unrealized_pnl=float(row.get("isolationUnrealizedPNL", 0) or 0),
            bonus=float(row.get("bonus", 0) or 0),
        )

    def get_trading_pairs(
        self, symbols: list[str] | None = None
    ) -> dict[str, BitunixFuturesSymbol]:
        if symbols is None and self._symbol_cache is not None:
            return self._symbol_cache

        params = None
        if symbols:
            params = {"symbols": ",".join(to_api_symbol(symbol) for symbol in symbols)}
        rows = self._request(
            "GET",
            "/api/v1/futures/market/trading_pairs",
            params=params,
            auth=False,
        )
        catalog: dict[str, BitunixFuturesSymbol] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            catalog[symbol] = BitunixFuturesSymbol(
                symbol=symbol,
                base=str(row.get("base", "")).upper(),
                quote=str(row.get("quote", "")).upper(),
                min_trade_volume=float(row.get("minTradeVolume", 0) or 0),
                max_market_order_volume=float(row.get("maxMarketOrderVolume", 0) or 0),
                base_precision=int(row.get("basePrecision", 0) or 0),
                quote_precision=int(row.get("quotePrecision", 0) or 0),
                max_leverage=int(row.get("maxLeverage", 0) or 0),
                min_leverage=int(row.get("minLeverage", 0) or 0),
                default_leverage=int(row.get("defaultLeverage", 0) or 0),
                symbol_status=str(row.get("symbolStatus", "")),
                is_api_supported=bool(row.get("isApiSupported", False)),
            )
        if symbols is None:
            self._symbol_cache = catalog
        return catalog

    def get_symbol(self, symbol: str) -> BitunixFuturesSymbol:
        api_symbol = to_api_symbol(symbol)
        catalog = self.get_trading_pairs([symbol])
        if api_symbol not in catalog:
            raise BitunixAPIError(f"No se encontro metadata futures para {symbol}.")
        return catalog[api_symbol]

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        trade_side: str = "OPEN",
        price: float | None = None,
        position_id: str | None = None,
        reduce_only: bool = False,
        client_id: str | None = None,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> CCXTPayloadProtocol:
        payload: dict[str, Any] = {  # TSK-200: cast target
            "symbol": to_api_symbol(symbol),
            "side": side.upper(),
            "qty": _format_decimal(qty),
            "orderType": order_type.upper(),
            "tradeSide": trade_side.upper(),
            "reduceOnly": bool(reduce_only),
        }
        if price is not None:
            payload["price"] = _format_decimal(price)
        if position_id:
            payload["positionId"] = position_id
        if client_id:
            payload["clientId"] = client_id
        if order_type.upper() == "LIMIT":
            payload["effect"] = "GTC"
        if tp_price is not None:
            payload["tpPrice"] = _format_decimal(tp_price)
            payload["tpStopType"] = "MARK_PRICE"
            payload["tpOrderType"] = "MARKET"
        if sl_price is not None:
            payload["slPrice"] = _format_decimal(sl_price)
            payload["slStopType"] = "MARK_PRICE"
            payload["slOrderType"] = "MARKET"

        return narrow_ccxt_payload(
            self._request(
                "POST",
                "/api/v1/futures/trade/place_order",
                payload=payload,
                auth=True,
            )
        )

    def flash_close_position(self, position_id: str) -> CCXTPayloadProtocol:
        return narrow_ccxt_payload(
            self._request(
                "POST",
                "/api/v1/futures/trade/flash_close_position",
                payload={"positionId": str(position_id)},
                auth=True,
            )
        )

    def place_position_tpsl(
        self,
        *,
        symbol: str,
        position_id: str,
        qty: float,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> CCXTPayloadProtocol:
        if tp_price is None and sl_price is None:
            raise BitunixAPIError("Hace falta tp_price o sl_price para colocar TP/SL.")

        payload: dict[str, Any] = {
            "symbol": to_api_symbol(symbol),
            "positionId": str(position_id),
        }
        if tp_price is not None:
            payload["tpPrice"] = _format_decimal(tp_price)
            payload["tpStopType"] = "MARK_PRICE"
            payload["tpOrderType"] = "MARKET"
            payload["tpQty"] = _format_decimal(qty)
        if sl_price is not None:
            payload["slPrice"] = _format_decimal(sl_price)
            payload["slStopType"] = "MARK_PRICE"
            payload["slOrderType"] = "MARKET"
            payload["slQty"] = _format_decimal(qty)

        return narrow_ccxt_payload(
            self._request(
                "POST",
                "/api/v1/futures/tpsl/place_order",
                payload=payload,
                auth=True,
            )
        )


_FUTURES_STATUS_MAP: Final[dict[str, OrderStatus]] = {
    "new": "open",
    "open": "open",
    "partially_filled": "partially_filled",
    "filled": "closed",
    "closed": "closed",
    "canceled": "canceled",
    "cancelled": "canceled",
    "rejected": "rejected",
    "expired": "expired",
}


class BitunixFuturesConnector:
    """Fachada de dominio sobre ``BitunixFuturesClient`` (TSK-022.6, RF-MX-2).

    Implementa ``MultiExchangeConnector`` para ``exchange_id == "bitunix"`` y
    ``market_type == "futures"``, manteniendo aislados los campos nativos
    (``positionId``, ``clientId``, ``tradeSide``, ``reduceOnly``, TP/SL) en
    el cliente REST (spec §3.3): los consumidores solo reciben el Protocol.

    - ``fetch_balance`` normaliza el contrato de cuenta futures a
      ``list[Balance]`` (free=available, used=frozen, total=free+used).
    - ``create_order`` conserva ``client_order_id``/``clientId`` y devuelve
      un ``OrderResult`` con estado canónico; un payload sin ``orderId`` o
      con correlación rota falla loud en la frontera.
    - ``cancel_order`` NO es no-op: el cliente no expone cancelación, así que
      se levanta ``UnsupportedConnectorOperationError`` antes de enviar una
      request ambigua.
    - ``fetch_ohlcv`` NO se simula: el cliente futures no implementa klines
      OHLCV; falla loud hasta que exista un endpoint verificado en sandbox.
    - ``sandbox_enabled`` es observable (flag declarativo del target).
    """

    exchange_id: str = "bitunix"
    market_type: ExchangeMarketType = "futures"

    def __init__(self, client: BitunixFuturesClient, *, sandbox: bool = True) -> None:
        self._client = client
        self._sandbox = sandbox
        self._log_name = self.__class__.__module__
        self._log = structlog.get_logger(self._log_name)

    @property
    def sandbox_enabled(self) -> bool:
        return self._sandbox

    def _bind(self, op: str, **extra: Any) -> Any:
        return self._log.bind(
            exchange_id=self.exchange_id,
            market_type=self.market_type,
            sandbox=self.sandbox_enabled,
            op=op,
            **extra,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load_markets(self) -> None:
        """Carga el catálogo de pares futures (sin retry, fail-fast)."""
        log = self._bind("load_markets")
        try:
            self._client.get_trading_pairs()
        except Exception:
            log.error("bitunix_futures_load_markets_failed", exc_info=True)
            raise
        log.info("bitunix_futures_load_markets_ok")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        """No soportado (loud): el cliente futures no implementa klines.

        No se fabrica OHLCV spot ni se inventa un endpoint; un consumo de
        OHLCV futures debe esperar a un endpoint verificado en sandbox.
        """
        raise UnsupportedConnectorOperationError(
            "BitunixFuturesConnector.fetch_ohlcv no soportado: "
            "BitunixFuturesClient no implementa klines OHLCV futures. "
            "Se falla loud en vez de devolver velas de otro mercado o "
            "simular un endpoint no verificado."
        )

    def fetch_24h_volume_usdt(self, symbol: str) -> float:
        """No soportado (loud): sin endpoint de volumen 24h verificado."""
        raise UnsupportedConnectorOperationError(
            "BitunixFuturesConnector.fetch_24h_volume_usdt no soportado: "
            "BitunixFuturesClient no implementa volumen 24h futures. "
            "Se falla loud en vez de fabricar un valor."
        )

    def fetch_spread_bps(self, symbol: str) -> float:
        """No soportado (loud): sin order book spot para spread en futures."""
        raise UnsupportedConnectorOperationError(
            "BitunixFuturesConnector.fetch_spread_bps no soportado: "
            "BitunixFuturesClient no implementa spread top-of-book. "
            "Se falla loud en vez de fabricar un valor."
        )

    def fetch_market_rules(self, symbol: str) -> MarketRules:
        """No soportado (loud): el catálogo futures no expone los campos de
        ``MarketRules`` (``min_trade_value_usdt``).

        No se mapea desde ``get_trading_pairs`` parcialmente (faltaría
        ``min_trade_value_usdt`` y el estado spot/futures difiere); se falla
        loud en vez de fabricar reglas incompletas para ejecución.
        """
        raise UnsupportedConnectorOperationError(
            "BitunixFuturesConnector.fetch_market_rules no soportado: "
            "el catálogo futures no expone los campos completos de "
            "MarketRules (min_trade_value_usdt). Se falla loud en vez de "
            "fabricar reglas incompletas para ejecución."
        )

    def fetch_balance(self) -> list[Balance]:
        """Cuenta futures normalizada a ``list[Balance]`` (frontera validada)."""
        log = self._bind("fetch_balance")
        try:
            account = self._client.get_account()
        except Exception:
            log.error("bitunix_futures_fetch_balance_failed", exc_info=True)
            raise
        if not isinstance(account, BitunixFuturesAccount) or not account.margin_coin:
            raise ConnectorProtocolError(
                f"Bitunix futures devolvió cuenta inválida: "
                f"{type(account).__name__!r}. Se aborta en la frontera."
            )
        free = account.available
        used = account.frozen
        log.info("bitunix_futures_fetch_balance_ok", asset=account.margin_coin)
        return [
            Balance(
                asset=account.margin_coin,
                free=free,
                used=used,
                total=free + used,
            )
        ]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------
    def create_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        """Coloca orden futures conservando ``client_order_id``/``clientId``.

        El cliente envía ``clientId`` en el payload (idempotencia); la
        respuesta debe permitir determinar la orden (``orderId``) o se falla
        loud. Un ``clientId`` reflejado que no coincida con el enviado rompe
        la correlación y también falla loud.
        """
        cid = client_order_id or str(uuid.uuid4())
        log = self._bind(
            "create_order",
            symbol=symbol,
            side=side,
            type=order_type,
            client_order_id=cid,
        )
        try:
            payload = self._client.place_order(
                symbol=symbol,
                side=side,
                qty=amount,
                order_type=order_type.upper(),
                price=price,
                client_id=cid,
            )
        except Exception:
            log.error("bitunix_futures_create_order_failed", exc_info=True)
            raise

        order_id = payload.get("orderId")
        if not order_id:
            raise ConnectorProtocolError(
                "Bitunix futures place_order no devolvió orderId; el payload "
                "no permite determinar la orden creada."
            )

        echoed_client_id = payload.get("clientId")
        if echoed_client_id is not None and str(echoed_client_id) != cid:
            raise ConnectorProtocolError(
                "Bitunix futures devolvió clientId que no coincide con el "
                "enviado: correlación rota (respuesta no determinable)."
            )

        status = self._normalize_futures_status(payload.get("status"))
        log.info(
            "bitunix_futures_create_order_ok",
            order_id=str(order_id),
            status=status,
        )
        return OrderResult(
            id=str(order_id),
            client_order_id=str(echoed_client_id or cid),
            symbol=symbol,
            status=status,
            side=side,
            type=order_type,
            price=float(payload.get("price", price or 0.0)),
            amount=amount,
            filled=float(payload.get("filled", 0.0)),
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:
        """No soportado (loud): el cliente no expone cancelación de órdenes.

        No se simula éxito ni se reutiliza ``flash_close_position`` (cierra
        posiciones, no cancela órdenes pendientes).
        """
        raise UnsupportedConnectorOperationError(
            "BitunixFuturesConnector.cancel_order no soportado: "
            "BitunixFuturesClient no expone cancelación de órdenes "
            "pendientes; el adapter no simula éxito ni envía una request "
            "ambigua."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_futures_status(raw: object) -> OrderStatus:
        """Mapa de status futures al Literal canónico.

        Un ack de colocación sin ``status`` se considera ``open`` (la orden
        fue aceptada; los payloads de error ya elevan ``BitunixAPIError`` en
        el cliente). Un status presente pero desconocido falla loud para
        forzar la ampliación del whitelist (mismo patrón ADR lock que
        ``_KNOWN_STATUS_MAP`` de TSK-101).
        """
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return "open"
        key = str(raw).strip().lower()
        if key in _FUTURES_STATUS_MAP:
            return _FUTURES_STATUS_MAP[key]
        raise ConnectorProtocolError(
            f"Bitunix futures devolvió status no mapeado: {raw!r}. "
            "Ampliar _FUTURES_STATUS_MAP con verificación sandbox antes de continuar."
        )


__all__ = [
    "BitunixFuturesAccount",
    "BitunixFuturesClient",
    "BitunixFuturesConnector",
    "BitunixFuturesPosition",
    "BitunixFuturesSymbol",
]
