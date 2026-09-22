"""Execution domain enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class ExecutionMode(StrEnum):
    """Trading execution mode (RFC §11)."""

    RESEARCH = "research"
    TESTNET = "testnet"
    MAINNET = "mainnet"
    PAPER = "paper"
    REPLAY = "replay"
    SHADOW_LIVE = "shadow_live"


@unique
class OrderStatus(StrEnum):
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
class FillStatus(StrEnum):
    """Fill status."""

    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
