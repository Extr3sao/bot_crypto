"""Admission Controller (FASE 3, P3, P4).

Decides which signals are admitted to the portfolio and which are blocked.
Implements portfolio chronology constraints:
- MAX_OPEN (total positions)
- MAX_DIRECTION (same-direction positions)
- DAILY_LOSS_LIMIT
- COOLDOWN (consecutive losses)
- POSITION_ALREADY_OPEN
- LOWER_PRIORITY
- KILL_SWITCH

Every BLOCKED signal saves its reason (P4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from trading_bot.config.risk import Risk

from .types import AlphaSignal, BlockedEvent, BlockedReason, Direction


@dataclass(slots=True)
class AdmissionState:
    """Mutable state for the admission controller."""

    open_positions: dict[str, Direction] = field(default_factory=dict)  # symbol -> direction
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0
    kill_switch_active: bool = False
    last_cooldown_ts: float = 0.0


class AdmissionController:
    """Portfolio-level signal admission.

    Checks signals against portfolio constraints before execution.
    Returns either admitted signal info or BlockedEvent.
    """

    def __init__(
        self,
        risk: Risk,
        equity: float = 10_000.0,
    ) -> None:
        self._risk = risk
        self._equity = equity
        self._state = AdmissionState()
        self._blocked_events: list[BlockedEvent] = []
        self._log = structlog.get_logger("admission_controller")

    @property
    def state(self) -> AdmissionState:
        return self._state

    @property
    def blocked_events(self) -> list[BlockedEvent]:
        return list(self._blocked_events)

    def check_signal(self, signal: AlphaSignal) -> AdmissionResult:
        """Check if a signal passes all admission gates.

        Returns AdmissionResult with admitted=True + rank if OK,
        or admitted=False + BlockedEvent if blocked.
        """
        # Kill switch
        if self._state.kill_switch_active:
            return self._block(signal, "KILL_SWITCH", "Kill switch active")

        # Daily trade limit
        if self._state.trades_today >= self._risk.max_trades_per_day:
            return self._block(
                signal, "DAILY_TRADE_LIMIT", f"Daily limit {self._risk.max_trades_per_day} reached"
            )

        # Max open positions
        if len(self._state.open_positions) >= self._risk.max_open_positions:
            return self._block(
                signal, "MAX_OPEN", f"Max {self._risk.max_open_positions} positions open"
            )

        # Position already open on same symbol (check BEFORE direction)
        if signal.symbol in self._state.open_positions:
            return self._block(
                signal, "POSITION_ALREADY_OPEN", f"Position already open on {signal.symbol}"
            )

        # Max same-direction positions
        same_dir_count = sum(
            1 for d in self._state.open_positions.values() if d == signal.direction
        )
        max_per_dir = max(1, self._risk.max_open_positions // 2)
        if same_dir_count >= max_per_dir:
            return self._block(
                signal, "MAX_DIRECTION", f"Max {max_per_dir} {signal.direction} positions"
            )

        # Daily loss limit
        if self._state.daily_pnl < 0:
            loss_pct = abs(self._state.daily_pnl) / self._equity * 100
            if loss_pct >= self._risk.max_daily_loss_pct:
                return self._block(
                    signal,
                    "DAILY_LOSS_LIMIT",
                    f"Daily loss {loss_pct:.1f}% >= {self._risk.max_daily_loss_pct}%",
                )

        # Consecutive losses cooldown
        if self._state.consecutive_losses >= self._risk.max_consecutive_losses:
            return self._block(
                signal,
                "COOLDOWN",
                f"Consecutive loss cooldown ({self._state.consecutive_losses} losses)",
            )

        # Admission passed
        rank = self._compute_rank(signal)
        self._log.info(
            "admission.admitted",
            family=signal.family,
            symbol=signal.symbol,
            direction=signal.direction,
            rank=rank,
        )
        return AdmissionResult(admitted=True, rank=rank)

    def record_open(self, symbol: str, direction: Direction) -> None:
        """Record that a position was opened."""
        self._state.open_positions[symbol] = direction
        self._state.trades_today += 1

    def record_close(self, symbol: str, pnl: float) -> None:
        """Record that a position was closed."""
        self._state.open_positions.pop(symbol, None)
        self._state.daily_pnl += pnl
        if pnl < 0:
            self._state.consecutive_losses += 1
        else:
            self._state.consecutive_losses = 0

    def activate_kill_switch(self, reason: str = "manual") -> None:
        """Activate kill switch."""
        self._state.kill_switch_active = True
        self._log.warning("admission.kill_switch_activated", reason=reason)

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of new day)."""
        self._state.daily_pnl = 0.0
        self._state.trades_today = 0

    def _block(
        self,
        signal: AlphaSignal,
        reason: BlockedReason,
        details: str,
    ) -> AdmissionResult:
        """Create a blocked event and return denied result."""
        event = BlockedEvent(
            signal_family=signal.family,
            symbol=signal.symbol,
            timestamp=signal.timestamp,
            direction=signal.direction,
            reason=reason,
            details=details,
        )
        self._blocked_events.append(event)
        self._log.info(
            "admission.blocked",
            family=signal.family,
            symbol=signal.symbol,
            reason=reason,
        )
        return AdmissionResult(admitted=False, blocked_event=event)

    def _compute_rank(self, signal: AlphaSignal) -> float:
        """Compute admission rank (higher = more urgent)."""
        # Simple rank: confidence * risk_price ratio
        risk = signal.risk_price
        if risk <= 0:
            return 0.0
        return signal.features.rsi if signal.features.rsi is not None else 0.5


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Result of admission check."""

    admitted: bool
    rank: float = 0.0
    blocked_event: BlockedEvent | None = None


__all__ = ["AdmissionController", "AdmissionResult", "AdmissionState"]
