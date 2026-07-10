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

from trading_bot.market_data.types import OHLCV, Balance


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
    ) -> dict[str, Any]:
        rule = self.get_symbol(symbol)
        side_num = 2 if side == "buy" else 1
        type_num = 2 if order_type == "market" else 1
        normalized_price = rule.round_price(price)
        normalized_amount = rule.round_base_amount(amount)
        if normalized_amount <= 0:
            raise BitunixAPIError("La cantidad normalizada ha quedado en 0.")
        return self._request(
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


__all__ = [
    "BitunixAPIError",
    "BitunixMarketDataSource",
    "BitunixSpotClient",
    "BitunixSpotSymbol",
    "_format_decimal",
    "_round_down",
    "to_api_symbol",
]
