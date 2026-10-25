"""Adapter from the real ``PaperBroker`` to the lifecycle engine.

The broker is the project's single execution boundary (docs/PAPER_OPERATIONAL_CONTRACT_
CONVERGENCE.md). This recorder is attached to it and observes the boundaries that already
exist: a position opened, a position closed, a signal refused. It adds no policy, changes
no number the broker computes, and does nothing at all when it is not attached.

One honest limitation, recorded in every envelope's payload rather than glossed over: the
broker does not publish a decision instant, only the instant it booked the fill. The
recorder therefore stamps ``decision_time_utc`` with that instant and declares
``decision_time_source = PAPER_BROKER_BOOKING_INSTANT``. It is an upper bound the caller
can check against its own ledger; it is not a fabricated decision clock.

Likewise, the risk gate it records is the broker's own notional guard (a signal without a
risk-approved ``notional_usdt`` is refused), not a copy of the RiskManager transcript. The
payload says so: ``risk_evaluation_source = PAPERBROKER_NOTIONAL_GUARD``.
"""

from __future__ import annotations

from typing import Any

from .contracts import OrderIntent, digest_of, utc_ms
from .engine import LifecycleEngine
from .venue import VenueMessage

DECISION_TIME_SOURCE = "PAPER_BROKER_BOOKING_INSTANT"
RISK_SOURCE = "PAPERBROKER_NOTIONAL_GUARD"


def _ms(seconds: float) -> int:
    return round(float(seconds) * 1000.0)


class PaperBrokerRecorder:
    """Observes one ``PaperBroker`` and writes its fills as lifecycle events."""

    def __init__(
        self,
        engine: LifecycleEngine,
        *,
        book_id: str,
        ledger_name: str = "PAPER_BROKER_BOOK",
    ) -> None:
        self.engine = engine
        self.book_id = book_id
        self.ledger_name = ledger_name
        self.recorded_entries = 0
        self.recorded_exits = 0
        self.recorded_refusals = 0
        self._intents: dict[str, dict[str, Any]] = {}

    # -- identity -------------------------------------------------------------

    def _client_order_id(self, *, symbol: str, metadata: dict[str, Any], fallback: str) -> str:
        explicit = str(metadata.get("cloid") or "").strip()
        if explicit:
            return explicit
        decision_seq = metadata.get("decision_seq")
        if decision_seq is not None:
            # The lane's own opinion identity: a retry of the same opinion carries the same
            # sequence, so the intent is stable without inventing a new identifier. The
            # symbol is part of the key because one sequence is minted per symbol.
            asset = symbol.split("/")[0]
            return f"LANE-{self.book_id}-{asset}-{int(decision_seq):06d}"
        return f"ORD-{self.book_id}-{symbol.replace('/', '')}-{fallback}"

    def _intent(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        strategy_id: str,
        when_s: float,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
        metadata: dict[str, Any],
    ) -> OrderIntent:
        instant = utc_ms(_ms(when_s))
        return OrderIntent(
            client_order_id=client_order_id,
            asset=symbol.split("/")[0],
            side=side,
            order_type="market",
            quantity=float(quantity),
            strategy_id=strategy_id or "unknown",
            decision_time_utc=instant,
            data_cutoff_utc=instant,
            notional_usdt=float(quantity) * float(price),
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_evaluation_id=RISK_SOURCE,
            policy_verification_id="PAPER_BROKER_EXECUTION_BOUNDARY",
            decision_id=(
                None if metadata.get("decision_seq") is None
                else str(metadata.get("decision_seq"))
            ),
        )

    @staticmethod
    def _meta() -> dict[str, Any]:
        """What a broker-observed event can honestly claim about its own clocks."""

        return {
            "decision_time_source": DECISION_TIME_SOURCE,
            "risk_evaluation_source": RISK_SOURCE,
        }

    # -- boundaries -----------------------------------------------------------

    def on_entry(self, position: Any, signal: Any, *, when_s: float | None = None) -> None:
        """A position was opened by the real broker: record intent, ack and fill."""

        metadata = dict(getattr(signal, "metadata", None) or {})
        client_order_id = self._client_order_id(
            symbol=str(position.symbol), metadata=metadata, fallback=str(position.entry_order_id)
        )
        booked_ms = _ms(position.opened_at if when_s is None else when_s)
        intent = self._intent(
            client_order_id=client_order_id,
            symbol=str(position.symbol),
            side=str(position.side),
            quantity=float(position.quantity),
            price=float(position.entry_price),
            strategy_id=str(getattr(signal, "strategy_name", "") or position.strategy_name),
            when_s=booked_ms / 1000.0,
            stop_loss_pct=float(position.stop_loss_pct),
            take_profit_pct=float(position.take_profit_pct),
            metadata=metadata,
        )
        intent_row = intent.to_row()
        self.engine.create(intent, now_ms=booked_ms, risk_approved=True, meta=self._meta())
        self.engine.submit(client_order_id, now_ms=booked_ms)
        self.engine.ingest(
            VenueMessage(
                kind="ACK",
                event_time_ms=booked_ms,
                venue_order_id=str(position.entry_order_id),
                event_id=f"{client_order_id}:ACK",
            ),
            client_order_id=client_order_id,
        )
        self.engine.ingest(
            VenueMessage(
                kind="FILL",
                event_time_ms=booked_ms,
                venue_order_id=str(position.entry_order_id),
                event_id=f"{client_order_id}:FILL:1",
                fill={
                    "fill_key": f"{position.entry_order_id}:1",
                    "filled_quantity": float(position.quantity),
                    "fill_price": float(position.entry_price),
                    "fee_amount": float(position.entry_commission),
                    "fee_currency": "USDT",
                    "complete": True,
                },
            ),
            client_order_id=client_order_id,
        )
        #: The intent row is kept on the order so an auditor can see the declared decision
        #: instant next to the booking instant that produced it.
        self._intents[intent.client_order_id] = intent_row
        self.recorded_entries += 1

    def on_exit(self, trade: Any, *, when_s: float | None = None) -> None:
        """A position was closed by the real broker: record the exit leg the same way."""

        booked_s = float(trade.closed_at if when_s is None else when_s)
        booked_ms = _ms(booked_s)
        side = "sell" if str(trade.side) == "buy" else "buy"
        client_order_id = f"EXIT-{self.book_id}-{trade.exit_order_id}"
        intent = self._intent(
            client_order_id=client_order_id,
            symbol=str(trade.symbol),
            side=side,
            quantity=float(trade.quantity),
            price=float(trade.exit_price),
            strategy_id=str(getattr(trade, "strategy_name", "")),
            when_s=booked_ms / 1000.0,
            stop_loss_pct=None,
            take_profit_pct=None,
            metadata={},
        )
        self.engine.create(intent, now_ms=booked_ms, risk_approved=True, meta=self._meta())
        self.engine.submit(client_order_id, now_ms=booked_ms)
        self.engine.ingest(
            VenueMessage(
                kind="ACK",
                event_time_ms=booked_ms,
                venue_order_id=str(trade.exit_order_id),
                event_id=f"{client_order_id}:ACK",
            ),
            client_order_id=client_order_id,
        )
        self.engine.ingest(
            VenueMessage(
                kind="FILL",
                event_time_ms=booked_ms,
                venue_order_id=str(trade.exit_order_id),
                event_id=f"{client_order_id}:FILL:1",
                fill={
                    "fill_key": f"{trade.exit_order_id}:1",
                    "filled_quantity": float(trade.quantity),
                    "fill_price": float(trade.exit_price),
                    "fee_amount": float(trade.exit_commission),
                    "fee_currency": "USDT",
                    "complete": True,
                },
            ),
            client_order_id=client_order_id,
        )
        self._intents[client_order_id] = intent.to_row()
        self.recorded_exits += 1

    def on_refusal(
        self, *, symbol: str, side: str, reason: str, when_s: float, metadata: dict[str, Any]
    ) -> None:
        """The broker refused to build an order. Recorded as a never-submitted intent."""

        client_order_id = self._client_order_id(
            symbol=symbol,
            metadata=metadata,
            fallback=digest_of({"symbol": symbol, "reason": reason, "when": when_s})[7:19],
        )
        if client_order_id in self._intents:
            return
        intent = OrderIntent(
            client_order_id=client_order_id,
            asset=symbol.split("/")[0],
            side=side if side in ("buy", "sell") else "buy",
            order_type="market",
            quantity=1.0,
            strategy_id="unknown",
            decision_time_utc=utc_ms(_ms(when_s)),
            data_cutoff_utc=utc_ms(_ms(when_s)),
            risk_evaluation_id="",
            policy_verification_id="",
        )
        self.engine.create(
            intent, now_ms=_ms(when_s), risk_approved=False, rejection_reason=reason
        )
        self.recorded_refusals += 1

    def introspection(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "ledger_name": self.ledger_name,
            "recorded_entries": self.recorded_entries,
            "recorded_exits": self.recorded_exits,
            "recorded_refusals": self.recorded_refusals,
            "intents": len(self._intents),
            "decision_time_source": DECISION_TIME_SOURCE,
            "risk_evaluation_source": RISK_SOURCE,
        }


__all__ = ["DECISION_TIME_SOURCE", "RISK_SOURCE", "PaperBrokerRecorder"]
