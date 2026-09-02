"""Domain events — append-only lifecycle events with hash-chain."""

from trading_bot.domain.events.journal import (
    DeskEvent,
    EventType,
    ProposalOpened,
    EvidenceAdded,
    RiskPassed,
    RiskRejected,
    ApprovalRequested,
    ApprovalGranted,
    ExecutionPrepared,
    OrderSent,
    OrderAcknowledged,
    OrderResting,
    FillReceived,
    PositionChanged,
    ProtectionVerified,
    IncidentOpened,
    TradeClosed,
    TradeReviewed,
)

__all__ = [
    "DeskEvent", "EventType",
    "ProposalOpened", "EvidenceAdded",
    "RiskPassed", "RiskRejected",
    "ApprovalRequested", "ApprovalGranted",
    "ExecutionPrepared", "OrderSent", "OrderAcknowledged", "OrderResting",
    "FillReceived", "PositionChanged", "ProtectionVerified",
    "IncidentOpened", "TradeClosed", "TradeReviewed",
]
