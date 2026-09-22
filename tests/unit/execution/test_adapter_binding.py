"""Track D tests — real connectors driven through the reliability primitives.

The fake ccxt transport is patched at the ``ccxt.<id>`` namespace level
(same strategy as ``tests/unit/market_data/test_ccxt_connector.py``), so the
REAL ``CCXTExchangeConnector`` code path executes — no live network. The
gateway binding then drives it through the certified primitives
(EX-01..EX-08).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import ccxt
import pytest

from trading_bot.config.exchange import Exchange, ExchangeRetries, ExchangeTimeouts
from trading_bot.execution.adapter_binding import (
    GatewayDrivenVenue,
    connector_conformance_adapter,
)
from trading_bot.execution.conformance import ExchangeAdapterConformanceSuite
from trading_bot.execution.gateway import ExecutionGateway
from trading_bot.execution.intent import TradeIntent
from trading_bot.execution.journal import ExecutionState
from trading_bot.execution.service import ExecutionService
from trading_bot.market_data.exchange_connector import CCXTExchangeConnector


class FakeCcxtTransport:
    """Simulated venue behind the ccxt.Exchange interface (no network)."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}  # clientOrderId -> order
        self.trades: list[dict[str, Any]] = []
        self.fail_submit_after_accept = False
        self.fail_before_accept = False  # raise WITHOUT registering (never landed)
        self.fail_query = False

    # -- order surface -------------------------------------------------------
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
        if self.fail_before_accept:
            raise ccxt.RequestTimeout("connection died before venue accepted")
        if self.fail_submit_after_accept:
            self.orders.setdefault(cid, self._order(cid, symbol, side, amount, price))
            raise ccxt.RequestTimeout("accepted then connection died")
        self.orders[cid] = self._order(cid, symbol, side, amount, price)
        return self.orders[cid]

    @staticmethod
    def _order(
        cid: str, symbol: str, side: str, amount: float, price: float | None
    ) -> dict[str, Any]:
        return {
            "id": f"VEN-{cid[-8:]}",
            "clientOrderId": cid,
            "symbol": symbol,
            "status": "open",
            "side": side,
            "type": "limit" if price is not None else "market",
            "price": price,
            "amount": amount,
            "filled": 0.0,
        }

    def fetch_order(
        self,
        order_id: str | None,
        symbol: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.fail_query:
            raise ccxt.NetworkError("query transport failed")
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
        return {"USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}}


@pytest.fixture
def connector(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CCXTExchangeConnector, FakeCcxtTransport]:
    transport = FakeCcxtTransport()
    instance = MagicMock(spec=ccxt.Exchange)
    instance.create_order.side_effect = transport.create_order
    instance.fetch_order.side_effect = transport.fetch_order
    instance.fetch_my_trades.side_effect = transport.fetch_my_trades
    instance.cancel_order.side_effect = transport.cancel_order
    instance.fetch_balance.side_effect = transport.fetch_balance
    instance.rateLimit = 250
    instance.timeout = 15000
    monkeypatch.setattr(ccxt, "binance", lambda *args: instance)
    cfg = Exchange(
        id="binance",
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
    return CCXTExchangeConnector(cfg), transport


def _intent() -> TradeIntent:
    return TradeIntent(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.01,
        order_type="limit",
        limit_price=60_000.0,
        venue="binance",
        account_id="test",
    )


class TestRealPathIdentity:
    def test_retry_reuses_same_client_order_id(self, connector) -> None:
        conn, transport = connector
        venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        gateway = ExecutionGateway()
        intent = _intent()
        cloid = gateway.client_order_id(intent)
        first = venue.submit(intent, cloid)
        second = venue.submit(intent, cloid)
        assert first == second
        # venue-side: exactly ONE economic order exists
        assert len(transport.orders) == 1
        assert next(iter(transport.orders)) == cloid

    def test_wall_clock_never_affects_identity(self, connector) -> None:
        conn, _ = connector
        GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        gateway = ExecutionGateway()
        base = _intent()
        a = TradeIntent(
            **{
                **{f: getattr(base, f) for f in base.__dataclass_fields__ if f != "metadata"},
                "metadata": {"ts": "2026-01-01T00:00:00Z"},
            }
        )
        b = TradeIntent(
            **{
                **{f: getattr(base, f) for f in base.__dataclass_fields__ if f != "metadata"},
                "metadata": {"ts": "2027-12-31T23:59:59Z"},
            }
        )
        assert gateway.client_order_id(a) == gateway.client_order_id(b)


class TestRealPathAckRecovery:
    def test_accepted_then_timeout_adopts_existing_order(self, connector) -> None:
        conn, transport = connector
        venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        gateway = ExecutionGateway()
        intent = _intent()
        transport.fail_submit_after_accept = True
        with pytest.raises(ccxt.RequestTimeout):
            gateway.submit(intent, venue)
        # ACK_UNKNOWN -> query by stable identity -> ADOPT
        receipt = gateway.resolve_ack_unknown(intent, venue)
        assert receipt.journal_state is ExecutionState.ACCEPTED
        assert receipt.venue_order_id is not None
        # exactly one economic order
        assert len(transport.orders) == 1

    def test_definitely_absent_allows_controlled_retry(self, connector) -> None:
        conn, transport = connector
        venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        gateway = ExecutionGateway()
        intent = _intent()
        # Connection dies BEFORE the venue registers anything.
        transport.fail_before_accept = True
        with pytest.raises(ccxt.RequestTimeout):
            gateway.submit(intent, venue)
        assert len(transport.orders) == 0  # venue definitively never accepted
        transport.fail_before_accept = False  # transport healed
        receipt = gateway.resolve_ack_unknown(intent, venue)
        # ABSENT -> controlled retry submitted exactly once venue-side.
        assert receipt.journal_state in (ExecutionState.SUBMITTING, ExecutionState.ACCEPTED)
        assert len(transport.orders) == 1

    def test_uncertain_query_blocks(self, connector) -> None:
        conn, transport = connector
        venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        gateway = ExecutionGateway()
        intent = _intent()
        transport.fail_submit_after_accept = True
        with pytest.raises(ccxt.RequestTimeout):
            gateway.submit(intent, venue)
        transport.fail_query = True  # query transport broken -> UNCERTAIN
        receipt = gateway.resolve_ack_unknown(intent, venue)
        assert receipt.journal_state is ExecutionState.RECONCILING
        assert receipt.venue_order_id is None


class TestRealPathFillsAndRestart:
    def test_duplicate_fill_applied_once(
        self, connector: tuple[CCXTExchangeConnector, FakeCcxtTransport]
    ) -> None:
        conn, _transport = connector
        venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        gateway = ExecutionGateway()
        intent = _intent()
        receipt = gateway.submit(intent, venue)
        assert receipt.journal_state is ExecutionState.ACCEPTED
        app1 = gateway.apply_fill(
            intent, venue_fill_id="F-1", quantity=0.01, price=60_000.0, fee=0.6
        )
        app2 = gateway.apply_fill(
            intent, venue_fill_id="F-1", quantity=0.01, price=60_000.0, fee=0.6
        )
        assert app1.applied is True
        assert app2.applied is False  # duplicate: exactly-once
        assert app1.position_delta == pytest.approx(0.01)
        assert app2.position_delta == 0.0  # duplicate changes nothing

    def test_restart_reconciles_from_journal(
        self, connector: tuple[CCXTExchangeConnector, FakeCcxtTransport], tmp_path
    ) -> None:
        conn, transport = connector
        venue = GatewayDrivenVenue(conn, default_symbol="BTC/USDT")
        journal_path = tmp_path / "journal.jsonl"
        service = ExecutionService.from_path(journal_path)
        intent = _intent()
        service.execute(intent, venue)
        # Restart: a fresh service replays the durable journal and observes
        # the same FSM state (no second economic order is ever submitted).
        reborn = ExecutionService.from_path(journal_path)
        assert reborn.journal.current_state(service.intent_id(intent)) is (ExecutionState.ACCEPTED)
        assert len(transport.orders) == 1


class TestConformanceSuiteOverRealConnector:
    def test_binance_conformance_passes(self, connector) -> None:
        conn, _ = connector
        adapter = connector_conformance_adapter(
            conn, adapter_id="binance", default_symbol="BTC/USDT"
        )
        suite = ExchangeAdapterConformanceSuite()
        passed, checks = suite.run(adapter)
        names = {c.name: c for c in checks}
        assert passed, {n: (c.passed, c.detail) for n, c in names.items() if not c.passed}
        assert all(c.passed for c in checks)
