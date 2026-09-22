"""Track E — Bybit through the same real-call-path conformance suite.

Mirrors ``test_adapter_binding.py`` but drives ``BybitConnector`` (the
concrete Bybit CCXT subclass) with a simulated transport. No network, no
real orders, LIVE stays 0.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import ccxt
import pytest

from trading_bot.config.exchange import Exchange, ExchangeRetries, ExchangeTimeouts
from trading_bot.execution.adapter_binding import connector_conformance_adapter
from trading_bot.execution.conformance import ExchangeAdapterConformanceSuite
from trading_bot.market_data.exchange_connector import BybitConnector


class FakeBybitTransport:
    """Same simulated-venue semantics as the Binance fake (no network)."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        cid = params.get("clientOrderId") or ""
        self.orders[cid] = {
            "id": f"BYB-{cid[-8:]}",
            "clientOrderId": cid,
            "symbol": symbol,
            "status": "open",
            "side": side,
            "type": "limit" if price is not None else "market",
            "price": price,
            "amount": amount,
            "filled": 0.0,
        }
        return self.orders[cid]

    def fetch_order(
        self,
        order_id: str | None,
        symbol: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        cid = params.get("clientOrderId") or ""
        order = self.orders.get(cid)
        if order is None:
            raise ccxt.OrderNotFound(f"unknown clientOrderId {cid!r}")
        return dict(order)

    def fetch_my_trades(
        self, symbol: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return list(self.trades)

    def cancel_order(self, order_id: str, symbol: str | None = None) -> None:
        for order in self.orders.values():
            if order["id"] == order_id:
                order["status"] = "canceled"
                return
        raise ccxt.OrderNotFound(f"unknown venue order {order_id!r}")

    def fetch_balance(self) -> dict[str, Any]:
        return {"USDT": {"free": 2000.0, "used": 0.0, "total": 2000.0}}


@pytest.fixture
def bybit_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[BybitConnector, FakeBybitTransport]:
    transport = FakeBybitTransport()
    instance = MagicMock(spec=ccxt.Exchange)
    instance.create_order.side_effect = transport.create_order
    instance.fetch_order.side_effect = transport.fetch_order
    instance.fetch_my_trades.side_effect = transport.fetch_my_trades
    instance.cancel_order.side_effect = transport.cancel_order
    instance.fetch_balance.side_effect = transport.fetch_balance
    instance.rateLimit = 250
    instance.timeout = 15000
    monkeypatch.setattr(ccxt, "bybit", lambda *args: instance)
    cfg = Exchange(
        id="bybit",
        sandbox=True,
        account_type="spot",
        rate_limit_ms=250,
        options={"defaultType": "spot"},
        timeouts=ExchangeTimeouts(request_ms=15000, recv_window_ms=5000),
        retries=ExchangeRetries(max_attempts=1, initial_backoff_ms=100, max_backoff_ms=100),
        default_type="spot",
        time_in_force_default="GTC",
        post_only_default=True,
    )
    return BybitConnector(cfg), transport


def test_bybit_conformance_through_real_call_path(bybit_connector) -> None:
    conn, _ = bybit_connector
    adapter = connector_conformance_adapter(conn, adapter_id="bybit", default_symbol="BTC/USDT")
    suite = ExchangeAdapterConformanceSuite()
    passed, checks = suite.run(adapter)
    failures = {c.name: c.detail for c in checks if not c.passed}
    assert passed, failures
    assert all(c.passed for c in checks)


def test_bybit_identity_stable_under_retry(bybit_connector) -> None:
    from trading_bot.execution.adapter_binding import GatewayDrivenVenue
    from trading_bot.execution.gateway import ExecutionGateway
    from trading_bot.execution.intent import TradeIntent

    conn, transport = bybit_connector
    venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
    gateway = ExecutionGateway()
    intent = TradeIntent(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.01,
        order_type="limit",
        limit_price=60_000.0,
        venue="bybit",
        account_id="test",
    )
    cloid = gateway.client_order_id(intent)
    first = venue.submit(intent, cloid)
    second = venue.submit(intent, cloid)
    assert first == second
    assert len(transport.orders) == 1  # ECONOMIC_ORDERS_PER_INTENT <= 1
