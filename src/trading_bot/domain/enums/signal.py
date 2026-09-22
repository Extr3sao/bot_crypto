"""Signal domain enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class SignalDirection(StrEnum):
    """Direction of a trade signal."""

    BUY = "buy"
    SELL = "sell"


@unique
class SignalState(StrEnum):
    """Lifecycle state of a signal."""

    CANDIDATE = "candidate"
    REGISTERED = "registered"
    APPROVED = "approved"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
