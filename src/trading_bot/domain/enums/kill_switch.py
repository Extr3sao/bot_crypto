"""Kill switch enums — 5-state model per RFC §16."""

from __future__ import annotations

from enum import Enum, unique


@unique
class KillSwitchState(str, Enum):
    """5-state kill switch (RFC §16).

    NORMAL → NO_NEW_RISK → PROTECTION_ONLY → READ_ONLY → HALTED
    """
    NORMAL = "normal"
    NO_NEW_RISK = "no_new_risk"
    PROTECTION_ONLY = "protection_only"
    READ_ONLY = "read_only"
    HALTED = "halted"


@unique
class KillSwitchAction(str, Enum):
    """What triggered the kill switch."""
    USER = "user"
    DAILY_LOSS = "daily_loss"
    POLICY_VIOLATION = "policy_violation"
    EXCHANGE_INCONSISTENCY = "exchange_inconsistency"
    UNKNOWN_SEND = "unknown_send"
    DATA_CORRUPTION = "data_corruption"
    KEY_COMPROMISE = "key_compromise"
    MANUAL = "manual"


# Allowed actions per kill switch state
KILL_SWITCH_ALLOWED_ACTIONS: dict[KillSwitchState, set[str]] = {
    KillSwitchState.NORMAL: {
        "open_new_position", "modify_position", "close_position",
        "send_order", "cancel_order", "read_data",
    },
    KillSwitchState.NO_NEW_RISK: {
        "close_position", "cancel_order", "read_data",
    },
    KillSwitchState.PROTECTION_ONLY: {
        "close_position", "read_data",
    },
    KillSwitchState.READ_ONLY: {
        "read_data",
    },
    KillSwitchState.HALTED: set(),
}


def is_action_allowed(state: KillSwitchState, action: str) -> bool:
    """Check if an action is allowed under the given kill switch state."""
    return action in KILL_SWITCH_ALLOWED_ACTIONS.get(state, set())
