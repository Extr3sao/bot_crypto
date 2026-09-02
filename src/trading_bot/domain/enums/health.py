"""Health status enums."""

from __future__ import annotations

from enum import Enum, unique


@unique
class SystemHealthStatus(str, Enum):
    """System health classification."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    PAUSED = "paused"
    FAIL_CLOSED = "fail_closed"


@unique
class FaultType(str, Enum):
    """Fault classification."""
    SYSTEM_FAULT = "system_fault"
    ALPHA_FAULT = "alpha_fault"
    MARKET_DATA_FAULT = "market_data_fault"
    RISK_FAULT = "risk_fault"
    EXECUTION_FAULT = "execution_fault"
    RECONCILIATION_FAULT = "reconciliation_fault"
    UNKNOWN_SEND_RESULT = "unknown_send_result"
    POSITION_UNPROTECTED = "position_unprotected"
    POSITION_MISMATCH = "position_mismatch"
    ORDER_MISMATCH = "order_mismatch"
    NETWORK_MISMATCH = "network_mismatch"
    EXCHANGE_OUTAGE = "exchange_outage"
    DATA_CORRUPTION = "data_corruption"
    KEY_COMPROMISE = "key_compromise"
