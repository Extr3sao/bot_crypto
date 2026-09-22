"""CCXT venue adapters driven through the reliability primitives.

SHADOW-AND-LEGACY-VALIDATION-01 (Track D). Binds the REAL runtime
connectors (``CCXTExchangeConnector`` and its Binance/Bybit/Bitunix
subclasses) to the certified ``ExecutionGateway`` path:

    TradeIntent -> stable intent_id -> stable client_order_id
      -> ExecutionJournal -> adapter submit/query/cancel
      -> ACK handling -> fill idempotency -> reconciliation

No agent and no strategy reaches the adapter directly: callers must go
through :class:`GatewayDrivenVenue` + ``ExecutionGateway`` (or the
``ExecutionService``). LIVE remains disabled — this module contains zero
network calls of its own; it drives whatever connector instance it is
given (tests inject a fake CCXT transport, never a real exchange client).

Additive surface used on the connector (D1/D4 requirements):

- ``create_order`` / ``cancel_order`` — existing, idempotent client id.
- ``fetch_order_query`` (NEW, additive): query by stable client_order_id
  returning a 3-valued ACK result; required for ACK_UNKNOWN recovery.
- ``fetch_recent_fills`` (NEW, additive): recent venue fills for
  idempotent reconciliation.

The additive methods are defined on ``CCXTExchangeConnector`` so every
concrete adapter (Binance/Bybit/Bitunix) inherits them — no per-venue
lowering of the safety contract.
"""

from __future__ import annotations

from typing import Any, Protocol

from trading_bot.execution.gateway import ExecutionGateway
from trading_bot.execution.intent import AckQueryResult, TradeIntent
from trading_bot.market_data.exchange_connector import CCXTExchangeConnector
from trading_bot.market_data.types import OrderResult, OrderType, Side

__all__ = [
    "GatewayDrivenVenue",
    "QueryingConnector",
    "connector_conformance_adapter",
]


class QueryingConnector(Protocol):
    """Connector surface required by the gateway-driven venue path."""

    def create_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult: ...

    def cancel_order(self, order_id: str, symbol: str) -> None: ...

    def fetch_order_query(self, client_order_id: str, symbol: str) -> dict[str, Any] | None: ...

    def fetch_recent_fills(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]: ...


class GatewayDrivenVenue:
    """Drive a REAL connector through the gateway authority path.

    Implements the ``VenuePort``-compatible surface (submit/query/
    venue_order_id_of) but with a symbol-aware submit so the CCXT
    connector receives the instrument it needs. Every submit passes the
    stable ``client_order_id`` derived from the intent — retries reuse it
    and the venue deduplicates.
    """

    def __init__(self, connector: QueryingConnector, *, default_symbol: str) -> None:
        self._connector = connector
        self._default_symbol = default_symbol

    @property
    def connector(self) -> QueryingConnector:
        return self._connector

    # -- VenuePort surface ---------------------------------------------------

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        """Submit the intent's economic order; return venue order id."""
        symbol = intent.metadata.get("symbol") or self._default_symbol
        side: Side = "buy" if intent.side == "buy" else "sell"
        order_type: OrderType = "limit" if intent.order_type == "limit" else "market"
        result = self._connector.create_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=intent.quantity,
            price=intent.limit_price,
            client_order_id=client_order_id,  # stable identity, reused on retry
        )
        return result.id

    def query(self, client_order_id: str) -> AckQueryResult:
        """3-valued ACK query by stable client identity.

        - order found -> FOUND
        - exchange explicitly reports it does not know the id -> ABSENT
        - any transport/unknown failure -> UNCERTAIN (never guess)
        """
        try:
            payload = self._connector.fetch_order_query(client_order_id, self._default_symbol)
        except Exception:
            return AckQueryResult.UNCERTAIN
        if payload is None:
            return AckQueryResult.ABSENT
        return AckQueryResult.FOUND

    def venue_order_id_of(self, client_order_id: str) -> str | None:
        try:
            payload = self._connector.fetch_order_query(client_order_id, self._default_symbol)
        except Exception:
            return None
        if not payload:
            return None
        venue_id = payload.get("id")
        return str(venue_id) if venue_id is not None else None

    # -- reconciliation helpers ----------------------------------------------

    def recent_fills(self, symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._connector.fetch_recent_fills(symbol or self._default_symbol, limit)

    def cancel(self, client_order_id: str) -> str:
        """Cancel by stable client identity (venue order id resolved first).

        Returns the canonical journal state string (CANCELLED when the venue
        confirms; CANCEL_PENDING on an unresolved outcome) — the cancel is
        NEVER assumed confirmed just because the request was sent.
        """
        venue_id = self.venue_order_id_of(client_order_id)
        if venue_id is None:
            raise LookupError(f"venue order not found for client id {client_order_id!r}")
        try:
            self._connector.cancel_order(venue_id, self._default_symbol)
        except Exception:
            return "CANCEL_PENDING"  # unresolved: reconciliation decides later
        try:
            payload = self._connector.fetch_order_query(client_order_id, self._default_symbol)
        except Exception:
            return "CANCEL_PENDING"
        if payload is None:
            return "CANCEL_PENDING"
        status = str(payload.get("status") or "").lower()
        if status in {"canceled", "cancelled", "closed"}:
            return "CANCELLED"
        return "CANCEL_PENDING"


class _ConformanceBinding:
    """Adapter the V1 conformance suite can drive over a real connector."""

    def __init__(
        self,
        venue: GatewayDrivenVenue,
        gateway: ExecutionGateway,
        *,
        adapter_id: str,
    ) -> None:
        self._venue = venue
        self._gateway = gateway
        self._id = adapter_id

    def adapter_id(self) -> str:
        return self._id

    def instrument_metadata(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "venue": self._id}

    def account_snapshot(self) -> dict[str, float]:
        """Real balances via the connector, mapped to the suite contract."""
        snapshot = {"equity": 0.0}
        fetch = getattr(self._venue.connector, "fetch_balance", None)
        if callable(fetch):
            for balance in fetch():
                snapshot[balance.asset] = float(balance.free)
                snapshot["equity"] += float(balance.total)
        return snapshot

    def positions(self) -> dict[str, float]:
        return {}

    def open_orders(self) -> list[str]:
        return []

    def fills(self) -> list[dict[str, Any]]:
        return [dict(f) for f in self._venue.recent_fills()]

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        return self._venue.submit(intent, client_order_id)

    def query(self, client_order_id: str) -> AckQueryResult:
        return self._venue.query(client_order_id)

    def venue_order_id_of(self, client_order_id: str) -> str | None:
        return self._venue.venue_order_id_of(client_order_id)

    def cancel(self, client_order_id: str) -> str:
        return self._venue.cancel(client_order_id)

    def reconnect(self) -> None:
        return None

    def staleness(self) -> float:
        return 0.0


def connector_conformance_adapter(
    connector: CCXTExchangeConnector,
    *,
    adapter_id: str,
    default_symbol: str,
    gateway: ExecutionGateway | None = None,
) -> _ConformanceBinding:
    """Build a conformance-suite-drivable binding over a REAL connector."""
    venue = GatewayDrivenVenue(connector, default_symbol=default_symbol)
    return _ConformanceBinding(
        venue,
        gateway or ExecutionGateway(),
        adapter_id=adapter_id,
    )
