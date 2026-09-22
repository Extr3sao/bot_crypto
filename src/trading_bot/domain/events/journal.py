"""Event journal types — append-only with hash-chain per RFC §5 C7."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique
from typing import Any
from uuid import UUID, uuid4


@unique
class EventType(StrEnum):
    """Lifecycle event types for the trade desk."""

    PROPOSAL_OPENED = "ProposalOpened"
    EVIDENCE_ADDED = "EvidenceAdded"
    RISK_PASSED = "RiskPassed"
    RISK_REJECTED = "RiskRejected"
    APPROVAL_REQUESTED = "ApprovalRequested"
    APPROVAL_GRANTED = "ApprovalGranted"
    EXECUTION_PREPARED = "ExecutionPrepared"
    ORDER_SENT = "OrderSent"
    ORDER_ACKNOWLEDGED = "OrderAcknowledged"
    ORDER_RESTING = "OrderResting"
    FILL_RECEIVED = "FillReceived"
    POSITION_CHANGED = "PositionChanged"
    PROTECTION_VERIFIED = "ProtectionVerified"
    INCIDENT_OPENED = "IncidentOpened"
    TRADE_CLOSED = "TradeClosed"
    TRADE_REVIEWED = "TradeReviewed"


@dataclass(frozen=True, slots=True)
class DeskEvent:
    """A single event in the trade lifecycle.

    Append-only. Each event includes a hash-chain link.
    """

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ticket_id: str = ""
    event_type: EventType = EventType.PROPOSAL_OPENED
    actor: str = "system"
    payload: dict[str, Any] = field(default_factory=dict)

    # Hash-chain for tamper detection
    previous_hash: str = ""
    event_hash: str = ""


# Concrete event types for type safety
@dataclass(frozen=True, slots=True)
class ProposalOpened(DeskEvent):
    """A new trade proposal has been opened."""

    event_type: EventType = field(default=EventType.PROPOSAL_OPENED, init=False)


@dataclass(frozen=True, slots=True)
class EvidenceAdded(DeskEvent):
    """Evidence has been added to a proposal."""

    event_type: EventType = field(default=EventType.EVIDENCE_ADDED, init=False)


@dataclass(frozen=True, slots=True)
class RiskPassed(DeskEvent):
    """Risk engine passed the proposal."""

    event_type: EventType = field(default=EventType.RISK_PASSED, init=False)


@dataclass(frozen=True, slots=True)
class RiskRejected(DeskEvent):
    """Risk engine rejected the proposal."""

    event_type: EventType = field(default=EventType.RISK_REJECTED, init=False)


@dataclass(frozen=True, slots=True)
class ApprovalRequested(DeskEvent):
    """Human approval has been requested."""

    event_type: EventType = field(default=EventType.APPROVAL_REQUESTED, init=False)


@dataclass(frozen=True, slots=True)
class ApprovalGranted(DeskEvent):
    """Human approval has been granted."""

    event_type: EventType = field(default=EventType.APPROVAL_GRANTED, init=False)


@dataclass(frozen=True, slots=True)
class ExecutionPrepared(DeskEvent):
    """Execution has been prepared (gateway pre-validation)."""

    event_type: EventType = field(default=EventType.EXECUTION_PREPARED, init=False)


@dataclass(frozen=True, slots=True)
class OrderSent(DeskEvent):
    """Order has been sent to the exchange."""

    event_type: EventType = field(default=EventType.ORDER_SENT, init=False)


@dataclass(frozen=True, slots=True)
class OrderAcknowledged(DeskEvent):
    """Exchange acknowledged the order."""

    event_type: EventType = field(default=EventType.ORDER_ACKNOWLEDGED, init=False)


@dataclass(frozen=True, slots=True)
class OrderResting(DeskEvent):
    """Order is resting (limit order not yet filled)."""

    event_type: EventType = field(default=EventType.ORDER_RESTING, init=False)


@dataclass(frozen=True, slots=True)
class FillReceived(DeskEvent):
    """Fill received from exchange."""

    event_type: EventType = field(default=EventType.FILL_RECEIVED, init=False)


@dataclass(frozen=True, slots=True)
class PositionChanged(DeskEvent):
    """Position state has changed."""

    event_type: EventType = field(default=EventType.POSITION_CHANGED, init=False)


@dataclass(frozen=True, slots=True)
class ProtectionVerified(DeskEvent):
    """Stop/protection order has been verified."""

    event_type: EventType = field(default=EventType.PROTECTION_VERIFIED, init=False)


@dataclass(frozen=True, slots=True)
class IncidentOpened(DeskEvent):
    """An incident has been opened."""

    event_type: EventType = field(default=EventType.INCIDENT_OPENED, init=False)


@dataclass(frozen=True, slots=True)
class TradeClosed(DeskEvent):
    """A trade has been closed."""

    event_type: EventType = field(default=EventType.TRADE_CLOSED, init=False)


@dataclass(frozen=True, slots=True)
class TradeReviewed(DeskEvent):
    """Post-trade review completed."""

    event_type: EventType = field(default=EventType.TRADE_REVIEWED, init=False)
