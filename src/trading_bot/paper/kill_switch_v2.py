"""5-state Kill Switch per RFC §16.

States:
  NORMAL → NO_NEW_RISK → PROTECTION_ONLY → READ_ONLY → HALTED

Can be activated by:
  user, daily loss, policy violation, exchange inconsistency,
  unknown send, data corruption, key compromise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from trading_bot.domain.enums.kill_switch import (
    KillSwitchAction,
    KillSwitchState,
    is_action_allowed,
)


@dataclass
class KillSwitch:
    """5-state kill switch per RFC §16.

    Usage:
        ks = KillSwitch()
        assert ks.state == KillSwitchState.NORMAL
        ks.activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
        assert ks.state == KillSwitchState.HALTED
        assert not ks.is_action_allowed("send_order")
    """

    _state: KillSwitchState = field(default=KillSwitchState.NORMAL)
    _history: list[tuple[KillSwitchState, KillSwitchState, KillSwitchAction, datetime]] = field(
        default_factory=list
    )
    _activated_at: datetime | None = None
    _activation_reason: str | None = None

    @property
    def state(self) -> KillSwitchState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state != KillSwitchState.NORMAL

    def activate(
        self,
        action: KillSwitchAction,
        target: KillSwitchState | None = None,
        reason: str = "",
    ) -> None:
        """Activate kill switch.

        If target is specified, go directly to that state.
        Otherwise, escalate one level.
        """
        previous = self._state

        if target:
            self._state = target
        else:
            # Escalate one level
            escalation = {
                KillSwitchState.NORMAL: KillSwitchState.NO_NEW_RISK,
                KillSwitchState.NO_NEW_RISK: KillSwitchState.PROTECTION_ONLY,
                KillSwitchState.PROTECTION_ONLY: KillSwitchState.READ_ONLY,
                KillSwitchState.READ_ONLY: KillSwitchState.HALTED,
                KillSwitchState.HALTED: KillSwitchState.HALTED,  # already max
            }
            self._state = escalation.get(self._state, KillSwitchState.HALTED)

        self._activated_at = datetime.utcnow()
        self._activation_reason = reason or action.value
        self._history.append((previous, self._state, action, datetime.utcnow()))

    def deactivate(self, reason: str = "manual") -> bool:
        """Deactivate kill switch back to NORMAL.

        Only allowed from NO_NEW_RISK or PROTECTION_ONLY.
        HALTED requires explicit reset.
        """
        if self._state in (KillSwitchState.READ_ONLY, KillSwitchState.HALTED):
            return False

        previous = self._state
        self._state = KillSwitchState.NORMAL
        self._activated_at = None
        self._activation_reason = None
        self._history.append(
            (previous, KillSwitchState.NORMAL, KillSwitchAction.USER, datetime.utcnow())
        )
        return True

    def reset(self) -> None:
        """Force reset to NORMAL (for emergency recovery)."""
        previous = self._state
        self._state = KillSwitchState.NORMAL
        self._activated_at = None
        self._activation_reason = None
        self._history.append(
            (previous, KillSwitchState.NORMAL, KillSwitchAction.MANUAL, datetime.utcnow())
        )

    def is_action_allowed(self, action: str) -> bool:
        """Check if an action is allowed under current state."""
        return is_action_allowed(self._state, action)

    def get_history(
        self,
    ) -> list[tuple[KillSwitchState, KillSwitchState, KillSwitchAction, datetime]]:
        """Get activation history."""
        return list(self._history)
