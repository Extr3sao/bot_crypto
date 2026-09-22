"""Risk domain enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class RiskDecision(StrEnum):
    """Risk engine decision."""

    PASS = "PASS"
    REJECT = "REJECT"
    UNAVAILABLE = "UNAVAILABLE"


@unique
class RiskBlockReason(StrEnum):
    """Reasons to block a trade on risk."""

    RISK_BUDGET_EXCEEDED = "risk_budget_exceeded"
    DAILY_LOSS_LOCK = "daily_loss_lock"
    DRAWDOWN_LOCK = "drawdown_lock"
    LIQUIDITY_INSUFFICIENT = "liquidity_insufficient"
    EXPOSURE_LIMIT = "exposure_limit"
    LEVERAGE_INSUFFICIENT = "leverage_insufficient"
    EQUITY_SAFETY_THRESHOLD = "equity_safety_threshold"
    MAX_POSITIONS = "max_positions"
    STOP_MISSING = "stop_missing"
    MIN_ORDER_SIZE = "min_order_size"
    CORRELATION_CLUSTER = "correlation_cluster"
    MARGIN_HEADROOM = "margin_headroom"
    LIQUIDATION_DISTANCE = "liquidation_distance"
    TICKET_EXPIRED = "ticket_expired"
    TICKET_CONSUMED = "ticket_consumed"
    TICKET_HASH_MISMATCH = "ticket_hash_mismatch"
    NETWORK_MISMATCH = "network_mismatch"
    ACCOUNT_MISMATCH = "account_mismatch"
    POLICY_VIOLATION = "policy_violation"


@unique
class RiskPolicyViolation(StrEnum):
    """Types of risk policy violations."""

    STALE_SNAPSHOT = "stale_snapshot"
    NAN_VALUE = "nan_value"
    INFINITY_VALUE = "infinity_value"
    NEGATIVE_EQUITY = "negative_equity"
    ZERO_STOP_DISTANCE = "zero_stop_distance"
    HUGE_LEVERAGE = "huge_leverage"
    CONFlicting_STATE = "conflicting_state"
