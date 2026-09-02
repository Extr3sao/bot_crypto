"""Signal domain enums."""

from __future__ import annotations

from enum import Enum, unique


@unique
class SignalDirection(str, Enum):
    """Direction of a trade signal."""
    BUY = "buy"
    SELL = "sell"


@unique
class SignalState(str, Enum):
    """Lifecycle state of a signal."""
    CANDIDATE = "candidate"
    REGISTERED = "registered"
    APPROVED = "approved"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
