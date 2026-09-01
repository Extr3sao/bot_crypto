"""Kill Switch for V0.3 — emergency stop for paper trading.

V0.3 requires a kill switch that can:
- Emergency stop all trading
- Auto-kill on excessive drawdown
- Manual override
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog


KillReason = Literal[
    "MANUAL",           # Manual trigger
    "DRAWDOWN",         # Excessive drawdown
    "DAILY_LOSS",       # Daily loss limit
    "CONSECUTIVE_LOSS", # Consecutive losses
    "SYSTEM_ERROR",     # System error
    "CONFIG_CHANGE",    # Configuration change
]


@dataclass(frozen=True, slots=True)
class KillEvent:
    """Record of a kill switch activation."""

    timestamp: float
    reason: KillReason
    message: str = ""
    equity_at_kill: float = 0.0
    drawdown_at_kill: float = 0.0


class KillSwitch:
    """Emergency stop for paper trading.

    V0.3: Must be tested and reliable.
    """

    def __init__(
        self,
        max_drawdown_pct: float = 0.10,  # 10% max drawdown
        max_daily_loss_pct: float = 0.05,  # 5% max daily loss
        max_consecutive_losses: int = 5,
    ) -> None:
        self._max_drawdown = max_drawdown_pct
        self._max_daily_loss = max_daily_loss_pct
        self._max_consecutive = max_consecutive_losses

        self._active = False
        self._triggered_at: float | None = None
        self._trigger_reason: KillReason | None = None
        self._trigger_message: str = ""

        self._peak_equity = 0.0
        self._daily_start_equity = 0.0
        self._consecutive_losses = 0
        self._events: list[KillEvent] = []

        self._log = structlog.get_logger("kill_switch")

    @property
    def is_active(self) -> bool:
        """True if kill switch is triggered (trading halted)."""
        return self._active

    @property
    def triggered_at(self) -> float | None:
        return self._triggered_at

    @property
    def reason(self) -> KillReason | None:
        return self._trigger_reason

    @property
    def events(self) -> list[KillEvent]:
        return list(self._events)

    def activate(self, reason: KillReason, message: str = "", equity: float = 0.0) -> None:
        """Manually activate the kill switch."""
        if self._active:
            self._log.warning("kill_switch.already_active")
            return

        self._active = True
        self._triggered_at = time.time()
        self._trigger_reason = reason
        self._trigger_message = message

        event = KillEvent(
            timestamp=self._triggered_at,
            reason=reason,
            message=message,
            equity_at_kill=equity,
            drawdown_at_kill=self._compute_drawdown(equity),
        )
        self._events.append(event)

        self._log.warning(
            "kill_switch.activated",
            reason=reason,
            message=message,
            equity=equity,
        )

    def deactivate(self) -> None:
        """Deactivate the kill switch (manual override)."""
        if not self._active:
            return

        self._active = False
        self._triggered_at = None
        self._trigger_reason = None
        self._trigger_message = ""

        self._log.info("kill_switch.deactivated")

    def check(self, equity: float) -> bool:
        """Check if kill switch should trigger.

        Returns True if trading should halt.
        """
        if self._active:
            return True

        # Update peak equity
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Check drawdown
        drawdown = self._compute_drawdown(equity)
        if drawdown >= self._max_drawdown:
            self.activate("DRAWDOWN", f"Drawdown {drawdown:.2%} >= {self._max_drawdown:.2%}", equity)
            return True

        # Check daily loss
        if self._daily_start_equity > 0:
            daily_loss = (self._daily_start_equity - equity) / self._daily_start_equity
            if daily_loss >= self._max_daily_loss:
                self.activate("DAILY_LOSS", f"Daily loss {daily_loss:.2%} >= {self._max_daily_loss:.2%}", equity)
                return True

        return False

    def record_trade(self, pnl: float) -> None:
        """Record a trade result for consecutive loss tracking."""
        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._max_consecutive:
                self.activate(
                    "CONSECUTIVE_LOSS",
                    f"Consecutive losses: {self._consecutive_losses}",
                )
        else:
            self._consecutive_losses = 0

    def reset_daily(self, equity: float) -> None:
        """Reset daily tracking (call at start of new day)."""
        self._daily_start_equity = equity
        self._consecutive_losses = 0

    def _compute_drawdown(self, equity: float) -> float:
        """Compute current drawdown from peak."""
        if self._peak_equity <= 0:
            return 0.0
        return (self._peak_equity - equity) / self._peak_equity

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence."""
        return {
            "active": self._active,
            "triggered_at": self._triggered_at,
            "reason": self._trigger_reason,
            "message": self._trigger_message,
            "peak_equity": self._peak_equity,
            "daily_start_equity": self._daily_start_equity,
            "consecutive_losses": self._consecutive_losses,
            "events_count": len(self._events),
        }


__all__ = [
    "KillEvent",
    "KillReason",
    "KillSwitch",
]
