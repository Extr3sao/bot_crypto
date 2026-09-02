"""Bitunix spot REST helpers used when CCXT lacks native Bitunix support.

This module keeps the integration deliberately narrow:

- Public market-data calls for the scanner.
- Private spot-balance lookup.
- Private spot order placement for explicit/manual or automatic live mode.

The implementation uses only the Python standard library so the repo can
run on the existing Windows venv without adding extra HTTP dependencies.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import time
import typing
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError

import structlog

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
    OrderType,
    Side,
    narrow_ccxt_payload,
)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _format_decimal(value: float, decimals: int | None = None) -> str:
    text = f"{value:.12f}" if decimals is None else f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") or "0"


def _round_down(value: float, decimals: int) -> float:
    factor = 10**decimals
    return typing.cast(float, int(value * factor) / factor)


def _ts_to_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def to_api_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


class BitunixAPIError(RuntimeError):
    """Raised when Bitunix responds with a non-success payload."""


@dataclass(frozen=True, slots=True)
class BitunixSpotSymbol:
    ccxt_symbol: str
    api_symbol: str
    base: str
    quote: str
    base_precision: int
    quote_precision: int
    min_trade_value_usdt: float
    min_volume: float
    is_open: bool

    def round_base_amount(self, amount: float) -> float:
        return _round_down(amount, self.base_precision)

    def round_price(self, price: float) -> float:
        return _round_down(price, self.quote_precision)


class BitunixSpotClient:
    """Minimal spot client for Bitunix."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        public_base_url: str = "https://openapi.bitunix.com",
    ) -> None:
        # Bloom-hygiene v1 (TSK-178 bitunix env-var wiring): kwarg value wins; fall back to env-var
        # if kwarg is empty (the canonical case for direct script callers).
        # No literal credentials stored in this module.
        self.api_key = api_key or os.getenv("BITUNIX_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BITUNIX_API_SECRET", "")
        self.public_base_url = public_base_url.rstrip("/")
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )
        self._symbol_cache: dict[str, BitunixSpotSymbol] | None = None
        self._server_time_offset_ms: int = 0

    def _fallback_symbol(self, symbol: str) -> BitunixSpotSymbol:
        normalized = symbol.replace("-", "/").upper()
        base, _, quote = normalized.partition("/")
        if not base or not quote:
            raise BitunixAPIError(f"Formato de simbolo invalido: {symbol!r}.")
        return BitunixSpotSymbol(
            ccxt_symbol=f"{base}/{quote}",
            api_symbol=to_api_symbol(normalized),
            base=base,
            quote=quote,
            base_precision=6,
            quote_precision=2 if quote == "USDT" else 6,
            min_trade_value_usdt=10.0 if quote == "USDT" else 0.0,
            min_volume=0.000001,
            is_open=True,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        auth: bool = False,
        _allow_time_retry: bool = True,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.public_base_url}{path}"
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
                raise BitunixAPIError("Bitunix API key/secret no configurados.")
            nonce = secrets.token_hex(16)
            timestamp = str(int(time.time() * 1000) + self._server_time_offset_ms)
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
            body = exc.read().decode("utf-8", errors="replace")
            raise BitunixAPIError(f"HTTP {exc.code}: {body}") from exc

        code = str(payload_json.get("code"))
        if code != "0":
            msg = payload_json.get("msg") or "Unknown Bitunix error"
            if auth and code == "100008" and _allow_time_retry:
                self._sync_time_offset()
                return self._request(
                    method,
                    path,
                    params=params,
                    payload=payload,
                    auth=auth,
                    _allow_time_retry=False,
                )
            raise BitunixAPIError(f"{msg} (code={code})")
        return payload_json.get("data")

    def _sync_time_offset(self) -> None:
        """Best-effort clock sync using the exchange HTTP Date header."""
        request = urllib.request.Request(
            f"{self.public_base_url}/api/spot/v1/market/last_price?symbol=BTCUSDT"
        )
        request.add_header("User-Agent", self.user_agent)
        request.add_header("Accept", "application/json, text/plain, */*")
        with urllib.request.urlopen(request, timeout=20) as response:
            server_date = response.headers.get("Date")

        if not server_date:
            self._server_time_offset_ms = 0
            return

        server_now = parsedate_to_datetime(server_date).timestamp() * 1000
        local_now = time.time() * 1000
        self._server_time_offset_ms = int(server_now - local_now)

    def fetch_symbol_catalog(self) -> dict[str, BitunixSpotSymbol]:
        if self._symbol_cache is not None:
            return self._symbol_cache

        rows = self._request("GET", "/api/spot/v1/common/coin_pair/list")
        catalog: dict[str, BitunixSpotSymbol] = {}
        for row in typing.cast(list[typing.Any], rows):
            api_symbol = str(row["symbol"]).upper()
            base = str(row["base"]).upper()
            quote = str(row["quote"]).upper()
            catalog[api_symbol] = BitunixSpotSymbol(
                ccxt_symbol=f"{base}/{quote}",
                api_symbol=api_symbol,
                base=base,
                quote=quote,
                base_precision=int(row.get("basePrecision", 6)),
                quote_precision=int(row.get("quotePrecision", 2)),
                min_trade_value_usdt=float(row.get("minPrice", 0) or 0),
                min_volume=float(row.get("minVolume", 0) or 0),
                is_open=bool(int(row.get("isOpen", 0) or 0)),
            )
        self._symbol_cache = catalog
        return catalog

    def get_symbol(self, symbol: str) -> BitunixSpotSymbol:
        api_symbol = to_api_symbol(symbol)
        try:
            catalog = self.fetch_symbol_catalog()
            if api_symbol in catalog:
                return catalog[api_symbol]
        except BitunixAPIError:
            pass
        return self._fallback_symbol(symbol)

    def fetch_last_price(self, symbol: str) -> float:
        api_symbol = to_api_symbol(symbol)
        return float(
            typing.cast(
                typing.Any,
                self._request(
                    "GET",
                    "/api/spot/v1/market/last_price",
                    params={"symbol": api_symbol},
                ),
            )
        )

    def fetch_recent_ohlcv(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        api_symbol = to_api_symbol(symbol)
        rows = self._request(
            "GET",
            "/api/spot/v1/market/kline/history",
            params={
                "symbol": api_symbol,
                "interval": "1",
                "limit": str(max(1, min(limit, 500))),
            },
        )
        candles: list[OHLCV] = []
        for row in reversed(rows):
            candles.append(
                OHLCV(
                    symbol=symbol,
                    timestamp=_ts_to_ms(str(row["ts"])),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                )
            )
        return candles

    def fetch_spread_bps(self, symbol: str) -> float:
        api_symbol = to_api_symbol(symbol)
        depth = self._request(
            "GET",
            "/api/spot/v1/market/depth",
            params={"symbol": api_symbol, "precision": "1"},
        )
        asks = depth.get("asks") or []
        bids = depth.get("bids") or []
        if not asks or not bids:
            raise BitunixAPIError(f"Depth vacio para {symbol}.")
        best_ask = float(asks[0]["price"])
        best_bid = float(bids[0]["price"])
        mid = (best_ask + best_bid) / 2.0
        if mid <= 0:
            raise BitunixAPIError(f"Mid-price invalido para {symbol}.")
        return ((best_ask - best_bid) / mid) * 10_000.0

    def fetch_24h_volume_usdt(self, symbol: str) -> float:
        api_symbol = to_api_symbol(symbol)
        rows = self._request(
            "GET",
            "/api/spot/v1/market/kline/history",
            params={"symbol": api_symbol, "interval": "60", "limit": "24"},
        )
        volume_usdt = 0.0
        for row in rows:
            close = float(row["close"])
            base_volume = float(row.get("volume", 0) or 0)
            volume_usdt += close * base_volume
        return volume_usdt

    def fetch_balances(self) -> list[Balance]:
        rows = self._request("GET", "/api/spot/v1/user/account", auth=True)
        balances: list[Balance] = []
        for row in rows:
            free = float(row.get("balance", 0) or 0)
            used = float(row.get("balanceLocked", 0) or 0)
            balances.append(
                Balance(
                    asset=str(row["coin"]).upper(),
                    free=free,
                    used=used,
                    total=free + used,
                )
            )
        return balances

    def place_spot_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: float,
    ) -> CCXTPayloadProtocol:
        rule = self.get_symbol(symbol)
        side_num = 2 if side == "buy" else 1
        type_num = 2 if order_type == "market" else 1
        normalized_price = rule.round_price(price)
        normalized_amount = rule.round_base_amount(amount)
        if normalized_amount <= 0:
            raise BitunixAPIError("La cantidad normalizada ha quedado en 0.")
        return narrow_ccxt_payload(
            self._request(
                "POST",
                "/api/spot/v1/order/place_order",
                payload={
                    "side": side_num,
                    "type": type_num,
                    "volume": _format_decimal(normalized_amount, rule.base_precision),
                    "price": _format_decimal(normalized_price, rule.quote_precision),
                    "symbol": rule.api_symbol,
                },
                auth=True,
            ),
        )


class BitunixMarketDataSource:
    """Implements the scanner protocol backed by Bitunix spot public APIs."""

    def __init__(self, client: BitunixSpotClient) -> None:
        self._client = client

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        return await asyncio.to_thread(self._client.fetch_recent_ohlcv, symbol, limit)

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        return await asyncio.to_thread(self._client.fetch_24h_volume_usdt, symbol)

    async def fetch_spread_bps(self, symbol: str) -> float:
        return await asyncio.to_thread(self._client.fetch_spread_bps, symbol)


def _check_ohlcv_row(row: object, symbol: str) -> None:
    """Valida un row devuelto por el cliente antes de entregarlo (frontera).

    Un payload REST inválido no debe convertirse en un ``OHLCV`` canónico
    silencioso: si el cliente devuelve algo que no es un ``OHLCV`` bien
    formado (tipo incorrecto, símbolo distinto del solicitado o valores no
    finitos), se falla loud con ``ConnectorProtocolError``.
    """
    if not isinstance(row, OHLCV):
        raise ConnectorProtocolError(
            f"Bitunix spot devolvió row OHLCV inválido: {type(row).__name__!r}. "
            "El adapter no fabrica valores válidos desde payloads incompletos."
        )
    if not row.symbol or row.symbol != symbol:
        raise ConnectorProtocolError(
            f"Bitunix spot devolvió row con symbol={row.symbol!r} para la "
            f"solicitud {symbol!r}; se aborta en la frontera."
        )
    for value in (row.open, row.high, row.low, row.close, row.volume):
        if not math.isfinite(float(value)):
            raise ConnectorProtocolError(
                f"Bitunix spot devolvió valor no finito en row de {symbol!r} "
                f"({value!r}); se aborta en la frontera."
            )


class BitunixSpotConnector:
    """Fachada de dominio sobre ``BitunixSpotClient`` (TSK-022.5, RF-MX-2).

    Implementa ``MultiExchangeConnector`` sin exponer el cliente REST a los
    consumidores: ``scanner``/``execution``/``strategies`` reciben únicamente
    el Protocol por inyección de dependencias (frontera RF-MX-4 / ADR-0013).

    - ``exchange_id == "bitunix"``, ``market_type == "spot"``.
    - ``sandbox_enabled`` es observable (flag declarativo del target; el
      wiring de URLs sandbox reales es responsabilidad del composition root
      y del gate de integración TSK-022.7).
    - OHLCV y balances se validan en la frontera: un payload REST incompleto
      produce ``ConnectorProtocolError``, nunca un valor por defecto.
    - ``create_order`` NO se simula: el cliente REST ``place_spot_order`` no
      correlaciona ``client_order_id`` y ``OrderResult.client_order_id`` es
      obligatorio (§2.1); sin idempotencia verificable el adapter falla loud
      antes de enviar una request ambigua.
    - ``cancel_order`` tampoco se simula: sin cancelación nativa en el
      cliente, se levanta ``UnsupportedConnectorOperationError``.
    """

    exchange_id: str = "bitunix"
    market_type: ExchangeMarketType = "spot"

    def __init__(self, client: BitunixSpotClient, *, sandbox: bool = True) -> None:
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
        """Carga el catálogo de símbolos del cliente spot (sin retry)."""
        log = self._bind("load_markets")
        try:
            self._client.fetch_symbol_catalog()
        except Exception:
            log.error("bitunix_spot_load_markets_failed", exc_info=True)
            raise
        log.info("bitunix_spot_load_markets_ok")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        """OHLCV canónico. Solo ``1m``: el cliente REST fija ``interval=1``;
        otro timeframe falla loud en vez de devolver velas del intervalo
        equivocado."""
        if timeframe != "1m":
            raise UnsupportedConnectorOperationError(
                f"Bitunix spot solo expone klines '1m' (cliente REST fija "
                f"interval=1); timeframe {timeframe!r} no soportado. "
                "Ampliar el cliente con verificación sandbox antes de habilitar."
            )
        log = self._bind("fetch_ohlcv", symbol=symbol, timeframe=timeframe, limit=limit)
        try:
            rows = self._client.fetch_recent_ohlcv(symbol, limit)
        except Exception:
            log.error("bitunix_spot_fetch_ohlcv_failed", exc_info=True)
            raise
        for row in rows:
            _check_ohlcv_row(row, symbol)
        log.info("bitunix_spot_fetch_ohlcv_ok", n=len(rows))
        return rows

    def fetch_24h_volume_usdt(self, symbol: str) -> float:
        """Volumen rolling 24h en USDT: delega en el cliente REST real."""
        log = self._bind("fetch_24h_volume_usdt", symbol=symbol)
        try:
            volume = self._client.fetch_24h_volume_usdt(symbol)
        except Exception:
            log.error("bitunix_spot_fetch_24h_volume_failed", exc_info=True)
            raise
        log.info("bitunix_spot_fetch_24h_volume_ok", volume_usdt=volume)
        return volume

    def fetch_spread_bps(self, symbol: str) -> float:
        """Spread top-of-book en bps: delega en el order book real del cliente."""
        log = self._bind("fetch_spread_bps", symbol=symbol)
        try:
            spread = self._client.fetch_spread_bps(symbol)
        except Exception:
            log.error("bitunix_spot_fetch_spread_failed", exc_info=True)
            raise
        log.info("bitunix_spot_fetch_spread_ok", spread_bps=spread)
        return spread

    def fetch_market_rules(self, symbol: str) -> MarketRules:
        """Reglas de negociación: delega en el catálogo real del cliente spot.

        ``get_symbol`` resuelve desde ``fetch_symbol_catalog`` (datos reales
        del exchange, cacheados) y mapea a ``MarketRules`` conservando los
        campos nativos (precisiones, mínimos, estado). Un símbolo ausente
        produce ``BitunixAPIError`` (fail-loud): no se fabrican reglas.
        """
        log = self._bind("fetch_market_rules", symbol=symbol)
        try:
            rule = self._client.get_symbol(symbol)
        except Exception:
            log.error("bitunix_spot_fetch_market_rules_failed", exc_info=True)
            raise
        if not isinstance(rule, BitunixSpotSymbol):
            raise ConnectorProtocolError(
                f"Bitunix spot devolvió reglas inválidas: {type(rule).__name__!r}. "
                "Se aborta en la frontera, sin valores por defecto."
            )
        rules = MarketRules(
            symbol=rule.ccxt_symbol,
            is_open=rule.is_open,
            quote=rule.quote,
            min_trade_value_usdt=rule.min_trade_value_usdt,
            min_volume=rule.min_volume,
            base_precision=rule.base_precision,
            quote_precision=rule.quote_precision,
        )
        log.info(
            "bitunix_spot_fetch_market_rules_ok",
            is_open=rules.is_open,
            quote=rules.quote,
            min_trade_value_usdt=rules.min_trade_value_usdt,
            min_volume=rules.min_volume,
        )
        return rules

    def fetch_balance(self) -> list[Balance]:
        """Balances spot normalizados a ``list[Balance]`` (frontera validada)."""
        log = self._bind("fetch_balance")
        try:
            rows = self._client.fetch_balances()
        except Exception:
            log.error("bitunix_spot_fetch_balance_failed", exc_info=True)
            raise
        for row in rows:
            if not isinstance(row, Balance):
                raise ConnectorProtocolError(
                    f"Bitunix spot devolvió balance inválido: {type(row).__name__!r}. "
                    "Se aborta en la frontera, sin valores por defecto."
                )
        log.info("bitunix_spot_fetch_balance_ok", n_assets=len(rows))
        return rows

    # ------------------------------------------------------------------
    # Write operations (sin simulación)
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
        """NO simulado: el cliente spot no correlaciona ``client_order_id``.

        ``OrderResult.client_order_id`` es obligatorio y debe conservarse en
        todos los adapters incluyendo retries (§2.1). ``place_spot_order`` no
        acepta ni refleja un client ID, así que no puede garantizarse la
        idempotencia; se falla loud antes de enviar la request.
        """
        raise UnsupportedConnectorOperationError(
            "BitunixSpotConnector.create_order no soportado: el cliente REST "
            "place_spot_order no correlaciona client_order_id y el Protocol "
            "exige conservarlo (03-specify.md §2.1). No se envía una orden "
            "sin idempotencia verificable."
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:
        """NO simulado: el cliente spot no expone cancelación nativa."""
        raise UnsupportedConnectorOperationError(
            "BitunixSpotConnector.cancel_order no soportado: BitunixSpotClient "
            "no implementa cancelación; el adapter no simula éxito."
        )


__all__ = [
    "BitunixAPIError",
    "BitunixMarketDataSource",
    "BitunixSpotClient",
    "BitunixSpotConnector",
    "BitunixSpotSymbol",
    "_format_decimal",
    "_round_down",
    "to_api_symbol",
]
