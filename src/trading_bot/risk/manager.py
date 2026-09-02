"""Risk Manager — position sizing, kill switch, daily limits.

Fase 5: the single authority for trade sizing and risk checks.
No sizing is calculated outside this module.

Reglas duras:
- Ningún sizing se calcula fuera de este módulo.
- KillSwitch solo se desactiva manualmente.
- Toda decisión se registra en logs/risk-decisions.log.
- Tests con hypothesis para invariantes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from trading_bot.config.risk import Risk

if TYPE_CHECKING:
    from trading_bot.strategies.types import Signal


@dataclass(frozen=True, slots=True)
class PositionSize:
    """Computed position size for a signal."""

    symbol: str
    side: str
    notional_usdt: float
    quantity: float
    stop_loss_pct: float
    take_profit_pct: float
    risk_amount_usdt: float


@dataclass(frozen=True, slots=True)
class RiskCheck:
    """Result of evaluating a signal against risk policy."""

    approved: bool
    reason: str | None = None
    position_size: PositionSize | None = None
    blocked_by: str | None = None


@dataclass
class RiskManager:
    """Stateful risk manager that tracks daily P&L, positions, and limits.

    One instance per trading session. Thread-safe not required (single-threaded
    trading loop).
    """

    risk: Risk
    equity: float
    open_positions: dict[str, Any] = field(default_factory=dict)
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    peak_equity: float = 0.0
    _kill_switch_active: bool = field(default=False)
    _log: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._log is None:
            self._log = structlog.get_logger("risk_manager")
        self.peak_equity = max(self.peak_equity, self.equity)

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str = "manual") -> None:
        """Activate kill switch. Cannot be undone programmatically."""
        self._kill_switch_active = True
        self._log.warning("risk.kill_switch_activated", reason=reason)

    def check_signal(self, signal: Signal) -> RiskCheck:
        """Evaluate a signal against all risk constraints.

        Returns RiskCheck with approved=True + PositionSize if OK,
        or approved=False with reason if blocked.
        """
        # Kill switch
        if self._kill_switch_active or not self.risk.kill_switch_enabled:
            return RiskCheck(
                approved=False,
                reason="Kill switch active" if self._kill_switch_active else "Kill switch disabled",
                blocked_by="kill_switch",
            )

        # Daily trade limit
        if self.trades_today >= self.risk.max_trades_per_day:
            return RiskCheck(
                approved=False,
                reason=f"Daily trade limit reached ({self.risk.max_trades_per_day})",
                blocked_by="daily_trade_limit",
            )

        # Open positions limit
        if len(self.open_positions) >= self.risk.max_open_positions:
            return RiskCheck(
                approved=False,
                reason=f"Max open positions reached ({self.risk.max_open_positions})",
                blocked_by="max_positions",
            )

        # Consecutive losses cooldown
        if self.consecutive_losses >= self.risk.max_consecutive_losses:
            return RiskCheck(
                approved=False,
                reason=f"Consecutive loss cooldown ({self.consecutive_losses} losses)",
                blocked_by="consecutive_loss_cooldown",
            )

        # Daily loss limit
        if self.daily_pnl < 0 and abs(self.daily_pnl) >= self.equity * (
            self.risk.max_daily_loss_pct / 100.0
        ):
            return RiskCheck(
                approved=False,
                reason=f"Daily loss limit reached ({self.risk.max_daily_loss_pct}%)",
                blocked_by="daily_loss_limit",
            )

        # Max drawdown
        drawdown_pct = (
            ((self.peak_equity - self.equity) / self.peak_equity * 100.0)
            if self.peak_equity > 0
            else 0.0
        )
        if drawdown_pct >= self.risk.max_total_drawdown_pct:
            return RiskCheck(
                approved=False,
                reason=f"Max drawdown reached ({drawdown_pct:.1f}% >= {self.risk.max_total_drawdown_pct}%)",
                blocked_by="max_drawdown",
            )

        # Position sizing
        position_size = self._compute_position_size(signal)
        if position_size is None:
            return RiskCheck(
                approved=False,
                reason="Position size below minimum or above maximum",
                blocked_by="position_sizing",
            )

        self._log.info(
            "risk.signal_approved",
            symbol=signal.symbol,
            side=signal.side,
            notional=position_size.notional_usdt,
            confidence=signal.confidence,
        )

        return RiskCheck(approved=True, position_size=position_size)

    def _compute_position_size(self, signal: Signal) -> PositionSize | None:
        """Compute position size respecting all limits."""
        if signal.price <= 0:
            return None

        # Risk-based sizing
        risk_amount = self.equity * (self.risk.max_risk_per_trade_pct / 100.0)
        stop_loss_pct = signal.stop_loss_pct or self.risk.default_stop_loss_pct
        take_profit_pct = signal.take_profit_pct or self.risk.default_take_profit_pct

        # Notional = risk_amount / (stop_loss_pct / 100)
        notional = risk_amount / (stop_loss_pct / 100.0) if stop_loss_pct > 0 else risk_amount

        # Clamp to min/max
        notional = max(
            self.risk.min_order_notional_usdt, min(notional, self.risk.max_order_notional_usdt)
        )

        # Check total exposure — handle both dict and object positions
        current_exposure = 0.0
        for pos in self.open_positions.values():
            if isinstance(pos, dict):
                current_exposure += pos.get("notional_usdt", 0.0)
            else:
                current_exposure += getattr(pos, "notional_usdt", 0.0)
        max_remaining = self.equity * (self.risk.max_total_exposure_pct / 100.0) - current_exposure
        if notional > max_remaining:
            notional = max_remaining

        if notional < self.risk.min_order_notional_usdt:
            return None

        quantity = notional / signal.price

        return PositionSize(
            symbol=signal.symbol,
            side=signal.side,
            notional_usdt=round(notional, 2),
            quantity=quantity,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_amount_usdt=round(risk_amount, 2),
        )

    def record_trade_result(self, pnl: float) -> None:
        """Record a completed trade's P&L."""
        self.trades_today += 1
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self._log.info(
            "risk.trade_recorded",
            pnl=pnl,
            daily_pnl=self.daily_pnl,
            equity=self.equity,
            consecutive_losses=self.consecutive_losses,
        )

    def add_position(self, symbol: str, position: Any) -> None:
        """Register an open position."""
        self.open_positions[symbol] = position

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position."""
        self.open_positions.pop(symbol, None)

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of each trading day)."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0

    def snapshot(self) -> dict[str, Any]:
        """Read-only snapshot of risk state."""
        drawdown_pct = (
            ((self.peak_equity - self.equity) / self.peak_equity * 100.0)
            if self.peak_equity > 0
            else 0.0
        )
        return {
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "drawdown_pct": round(drawdown_pct, 2),
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": len(self.open_positions),
            "kill_switch_active": self._kill_switch_active,
        }


__all__ = ["PositionSize", "RiskCheck", "RiskManager"]
