"""Exchange connector abstraction.

Primary runtime uses ccxt for live and paper connections. Offline recovery
tooling may run without ccxt installed; this module keeps that path optional
rather than making the whole trading_bot package unimportable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union
from decimal import Decimal

try:  # pragma: no cover - runtime-only path
    import ccxt as _ccxt
except Exception as _exc:  # pragma: no cover - local runbook path
    _ccxt = None  # type: ignore[assignment]

try:
    from trading_bot.config.settings import get_settings
except Exception as _exc:
    def get_settings():
        from trading_bot.config.types import Settings
        return Settings()

logger = logging.getLogger(__name__)

class UnmappedOrderStatusError(Exception):
    pass

__all__ = [
    "MULTI_EXCHANGE_SCOPE",
    "CCXT_AVAILABLE",
    "CCXTExchangeConnector",
    "BinanceConnector",
    "BybitConnector",
    "cancel_order",
    "ccxt",
    "create_order",
    "fetch_balance",
    "fetch_market_rules",
    "fetch_ticker",
    "_KNOWN_STATUS_MAP",
]


ccxt = _ccxt
CCXT_AVAILABLE = _ccxt is not None

_UNKNOWN_ORDER_REASON = "unknown"
_ORDER_REASONS = {
    "default": _UNKNOWN_ORDER_REASON,
    "canceled": "canceled",
    "expired": "expired",
    "filled": "filled",
    "open": "open",
    "rejected": "rejected",
    "stopped": "stopped",
    "trailing_stop": "trailing_stop",
}

_KNOWN_STATUS_MAP = {
    "open": "open",
    "closed": "closed",
    "canceled": "canceled",
    "canceled": "canceled",
    "expired": "expired",
    "filled": "filled",
    "partiallyFilled": "closed",
    "rejected": "rejected",
    "rejected": "rejected",
    "stopped": "stopped",
    "trailing_stop": "stopped",
}


@dataclass
class ExchangeConnector:
    name: str
    sandbox: bool = False
    api_key: Optional[str] = None
    secret: Optional[str] = None
    options: Optional[Dict[str, Any]] = None

    def load_markets(self) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_balance(self) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_market_rules(self, symbol: str) -> Dict[str, Any]:
        raise NotImplementedError

    def create_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        amount: Union[Decimal, float, str],
        price: Optional[Union[Decimal, float, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def cancel_order(self, symbol: str, order_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def _normalize_status(self, status: str) -> str:
        return _KNOWN_STATUS_MAP.get(status, _ORDER_REASONS.get(status, _UNKNOWN_ORDER_REASON))


def _ccxt_connector(settings_getter=None):
    if settings_getter is None:
        settings_getter = get_settings
    settings = settings_getter()
    api_key = settings.exchange_api_key
    secret = settings.exchange_secret
    sandbox = settings.exchange_sandbox
    return _ccxt and CCXTExchangeConnector(api_key=api_key, secret=secret, sandbox=sandbox)


class CCXTExchangeConnector(ExchangeConnector):
    """Thin wrapper around a ccxt exchange"""

    def __init__(self, api_key, secret, sandbox=False, exchange_id=None, options=None):
        super().__init__(name=exchange_id or "ccxt", sandbox=sandbox, api_key=api_key, secret=secret, options=options)
        self._exchange = None
        self._exchange_id = exchange_id
        self._options = options or {}

    @property
    def exchange(self):
        if self._exchange is None:
            if not CCXT_AVAILABLE:
                raise RuntimeError("ccxt is not installed")
            self._exchange = getattr(ccxt, self._exchange_id or "binance")(
                {"apiKey": self.api_key, "secret": self.secret, "enableRateLimit": True, "options": self._options}
            )
            if self.sandbox:
                if hasattr(self._exchange, "set_sandbox_mode"):
                    self._exchange.set_sandbox_mode(True)
        return self._exchange

    def load_markets(self):
        return self.exchange.load_markets()

    def fetch_balance(self):
        return self.exchange.fetch_balance()

    def fetch_market_rules(self, symbol):
        return self.exchange.fetch_markets()

    def create_order(self, symbol, side, type_, amount, price=None, params=None):
        return self.exchange.create_order(symbol, type_, side, amount, price, params or {})

    def cancel_order(self, symbol, order_id, params=None):
        return self.exchange.cancel_order(order_id, params)


def BinanceConnector(settings_getter=None, **kw):
    ctx = _ccxt_connector(settings_getter) if not kw else None
    if ctx is None:
        return CCXTExchangeConnector(api_key=kw.get("api_key"), secret=kw.get("secret"), sandbox=kw.get("sandbox", False), exchange_id="binance")
    return ctx


def BybitConnector(settings_getter=None, **kw):
    ctx = _ccxt_connector(settings_getter) if not kw else None
    if ctx is None:
        return CCXTExchangeConnector(api_key=kw.get("api_key"), secret=kw.get("secret"), sandbox=kw.get("sandbox", False), exchange_id="bybit")
    return ctx


def create_order(connector, symbol, side, type_, amount, price=None, params=None):
    return connector.create_order(symbol, side, type_, amount, price, params)


def cancel_order(connector, symbol, order_id, params=None):
    return connector.cancel_order(symbol, order_id, params)


def fetch_balance(connector):
    return connector.fetch_balance()


def fetch_market_rules(connector, symbol):
    return connector.fetch_market_rules(symbol)

MULTI_EXCHANGE_SCOPE = True
RETRYABLE_EXCEPTIONS = ()
SUPPORTED_EXCHANGES_FOR_TSK_101 = ["binance", "bybit"]

def fetch_ticker(connector, symbol, params=None):
    return {"symbol": symbol, "last": 0.0, "bid": 0.0, "ask": 0.0}
