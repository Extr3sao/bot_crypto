"""Event Store — append-only with hash-chain integrity per RFC §5 C7.

Every event includes a hash-chain link:
  event_hash = SHA256(event_id + timestamp + ticket_id + type + actor + payload + previous_hash)
  previous_hash = event_hash of the previous event

This allows tamper detection without blockchain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from trading_bot.domain.events.hashing import compute_event_hash, verify_hash_chain
from trading_bot.domain.events.journal import DeskEvent, EventType


@dataclass
class EventStore:
    """Append-only event store with hash-chain integrity.

    Usage:
        store = EventStore()
        event = store.append(
            event_type=EventType.PROPOSAL_OPENED,
            ticket_id="TA-001",
            actor="system",
            payload={"proposal_id": "TA-001", "market": "BTC"},
        )
        assert store.verify_integrity()  # True

        # Tamper detection
        store._events[0]["payload"]["market"] = "ETH"
        assert not store.verify_integrity()  # False (tampered)
    """

    _events: list[dict[str, Any]] = field(default_factory=list)
    _previous_hash: str = ""

    def append(
        self,
        event_type: EventType,
        ticket_id: str = "",
        actor: str = "system",
        payload: Optional[dict[str, Any]] = None,
    ) -> DeskEvent:
        """Append a new event to the store.

        Automatically computes hash-chain link.
        """
        event_id = uuid4()
        timestamp = datetime.utcnow()
        payload = payload or {}

        event_hash = compute_event_hash(
            event_id=event_id,
            timestamp=timestamp,
            ticket_id=ticket_id,
            event_type=event_type.value,
            actor=actor,
            payload=payload,
            previous_hash=self._previous_hash,
        )

        event_dict = {
            "event_id": str(event_id),
            "timestamp": timestamp,
            "ticket_id": ticket_id,
            "event_type": event_type.value,
            "actor": actor,
            "payload": payload,
            "previous_hash": self._previous_hash,
            "event_hash": event_hash,
        }

        self._events.append(event_dict)
        self._previous_hash = event_hash

        return DeskEvent(
            event_id=event_id,
            timestamp=timestamp,
            ticket_id=ticket_id,
            event_type=event_type,
            actor=actor,
            payload=payload,
            previous_hash=event_dict["previous_hash"],
            event_hash=event_hash,
        )

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the integrity of the entire event chain.

        Returns (is_valid, error_message).
        """
        return verify_hash_chain(self._events)

    def get_events(
        self,
        ticket_id: Optional[str] = None,
        event_type: Optional[EventType] = None,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Get events, optionally filtered."""
        events = list(self._events)

        if ticket_id:
            events = [e for e in events if e.get("ticket_id") == ticket_id]
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type.value]
        if since:
            events = [e for e in events if e.get("timestamp", datetime.min) >= since]

        return events

    def get_trade_events(self, ticket_id: str) -> list[dict[str, Any]]:
        """Get all events for a specific trade ticket (full lifecycle)."""
        return self.get_events(ticket_id=ticket_id)

    def reconstruct_trade(self, ticket_id: str) -> dict[str, Any]:
        """Reconstruct a complete trade from events.

        Returns a dict with all trade state reconstructed from events.
        """
        events = self.get_trade_events(ticket_id)

        trade = {
            "ticket_id": ticket_id,
            "events": [],
            "proposal": None,
            "risk_assessment": None,
            "approval": None,
            "execution": None,
            "fills": [],
            "closed": False,
        }

        for event in events:
            trade["events"].append(event)
            event_type = event.get("event_type", "")

            if event_type == EventType.PROPOSAL_OPENED.value:
                trade["proposal"] = event.get("payload", {})
            elif event_type in (EventType.RISK_PASSED.value, EventType.RISK_REJECTED.value):
                trade["risk_assessment"] = event.get("payload", {})
            elif event_type == EventType.APPROVAL_GRANTED.value:
                trade["approval"] = event.get("payload", {})
            elif event_type == EventType.ORDER_SENT.value:
                trade["execution"] = event.get("payload", {})
            elif event_type == EventType.FILL_RECEIVED.value:
                trade["fills"].append(event.get("payload", {}))
            elif event_type == EventType.TRADE_CLOSED.value:
                trade["closed"] = True

        return trade

    @property
    def event_count(self) -> int:
        """Number of events in the store."""
        return len(self._events)

    @property
    def last_hash(self) -> str:
        """Hash of the last event (for chaining)."""
        return self._previous_hash

    def to_json(self) -> str:
        """Serialize the event store to JSON."""
        return json.dumps(self._events, default=str, indent=2)

    def clear(self) -> None:
        """Clear all events (use with caution)."""
        self._events.clear()
        self._previous_hash = ""
