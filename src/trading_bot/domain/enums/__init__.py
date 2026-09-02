"""Domain enums — immutable enumerations for the trading desk."""

from trading_bot.domain.enums.desk import DeskState, DeskTransition
from trading_bot.domain.enums.execution import ExecutionMode, FillStatus, OrderStatus
from trading_bot.domain.enums.health import FaultType, SystemHealthStatus
from trading_bot.domain.enums.kill_switch import KillSwitchAction, KillSwitchState
from trading_bot.domain.enums.risk import RiskBlockReason, RiskDecision, RiskPolicyViolation
from trading_bot.domain.enums.signal import SignalDirection, SignalState
from trading_bot.domain.enums.trade import ExitReason, OrderSide, OrderType, TradeDirection

__all__ = [
    "DeskState",
    "DeskTransition",
    "ExecutionMode",
    "ExitReason",
    "FaultType",
    "FillStatus",
    "KillSwitchAction",
    "KillSwitchState",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "RiskBlockReason",
    "RiskDecision",
    "RiskPolicyViolation",
    "SignalDirection",
    "SignalState",
    "SystemHealthStatus",
    "TradeDirection",
]
