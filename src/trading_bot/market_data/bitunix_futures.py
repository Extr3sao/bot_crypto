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
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError

from trading_bot.market_data.bitunix import BitunixAPIError, to_api_symbol


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
    ) -> dict[str, Any]:
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

        return self._request(
            "POST",
            "/api/v1/futures/trade/place_order",
            payload=payload,
            auth=True,
        )

    def flash_close_position(self, position_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/futures/trade/flash_close_position",
            payload={"positionId": str(position_id)},
            auth=True,
        )

    def place_position_tpsl(
        self,
        *,
        symbol: str,
        position_id: str,
        qty: float,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> dict[str, Any]:
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

        return self._request(
            "POST",
            "/api/v1/futures/tpsl/place_order",
            payload=payload,
            auth=True,
        )


__all__ = [
    "BitunixFuturesAccount",
    "BitunixFuturesClient",
    "BitunixFuturesPosition",
    "BitunixFuturesSymbol",
]
