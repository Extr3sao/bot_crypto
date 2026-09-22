"""Trade domain enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class TradeDirection(StrEnum):
    """Direction of a trade position."""

    LONG = "LONG"
    SHORT = "SHORT"


@unique
class OrderSide(StrEnum):
    """Side of an order."""

    BUY = "BUY"
    SELL = "SELL"


@unique
class OrderType(StrEnum):
    """Type of order."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    IOC = "IOC"


@unique
class ExitReason(StrEnum):
    """Reason for position exit."""

    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    SIGNAL = "signal"
    KILL_SWITCH = "kill_switch"
    DAILY_LOSS = "daily_loss"
    DRAWDOWN = "drawdown"
    MANUAL = "manual"
    INTRABAR_AMBIGUOUS_SL_FIRST = "intrabar_ambiguous_sl_first"
    INTRABAR_AMBIGUOUS_TP_FIRST = "intrabar_ambiguous_tp_first"
    EXPIRED = "expired"
    RECONCILIATION = "reconciliation"
