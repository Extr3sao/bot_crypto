"""Execution domain enums."""

from __future__ import annotations

from enum import Enum, unique


@unique
class ExecutionMode(str, Enum):
    """Trading execution mode (RFC §11)."""
    RESEARCH = "research"
    TESTNET = "testnet"
    MAINNET = "mainnet"
    PAPER = "paper"
    REPLAY = "replay"
    SHADOW_LIVE = "shadow_live"


@unique
class OrderStatus(str, Enum):
    """Order status after submission."""
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    RESTING = "resting"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@unique
class FillStatus(str, Enum):
    """Fill status."""
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
