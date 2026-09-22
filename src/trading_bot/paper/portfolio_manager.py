"""Portfolio Manager for V0.3 — position sizing, exposure limits, drawdown protection.

V0.3 requires portfolio-level risk management for paper trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog


@dataclass(frozen=True, slots=True)
class PositionSize:
    """Computed position size for a trade."""

    symbol: str
    side: str
    quantity: float
    notional: float
    risk_budget_usdt: float
    risk_per_trade_pct: float
    max_exposure_pct: float
    within_limits: bool = True
    rejection_reason: str = ""


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    """Current exposure state."""

    total_exposure: float
    max_exposure: float
    exposure_pct: float
    positions: dict[str, float] = field(default_factory=dict)  # symbol -> notional


class PortfolioManager:
    """Portfolio-level risk management for paper trading.

    V0.3: Enforces position sizing, exposure limits, drawdown protection.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        risk_per_trade_pct: float = 0.0025,
        max_exposure_pct: float = 0.25,
        max_positions: int = 6,
        max_daily_loss_pct: float = 0.05,
        max_drawdown_pct: float = 0.10,
    ) -> None:
        self._initial_capital = initial_capital
        self._capital = initial_capital
        self._risk_per_trade = risk_per_trade_pct
        self._max_exposure = max_exposure_pct
        self._max_positions = max_positions
        self._max_daily_loss = max_daily_loss_pct
        self._max_drawdown = max_drawdown_pct

        self._positions: dict[str, float] = {}  # symbol -> notional
        self._daily_pnl = 0.0
        self._peak_equity = initial_capital
        self._last_reset_day = ""

        self._log = structlog.get_logger("portfolio_manager")

    @property
    def capital(self) -> float:
        return self._capital

    @property
    def equity(self) -> float:
        """Current equity = capital + unrealized PnL."""
        return self._capital

    def compute_position_size(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_distance_pct: float,
        current_equity: float | None = None,
    ) -> PositionSize:
        """Compute position size based on risk budget.

        V0.3: Risk-based sizing, not fixed notional.
        """
        equity = current_equity or self._capital

        # Risk budget
        risk_budget = equity * self._risk_per_trade

        # Position size from risk
        if stop_distance_pct <= 0 or entry_price <= 0:
            return PositionSize(
                symbol=symbol,
                side=side,
                quantity=0.0,
                notional=0.0,
                risk_budget_usdt=risk_budget,
                risk_per_trade_pct=self._risk_per_trade,
                max_exposure_pct=self._max_exposure,
                within_limits=False,
                rejection_reason="Invalid stop distance or entry price",
            )

        qty = risk_budget / (entry_price * stop_distance_pct)

        # Cap by max exposure
        max_notional = equity * self._max_exposure
        notional = qty * entry_price
        if notional > max_notional:
            qty = max_notional / entry_price
            notional = max_notional

        # Check position count
        if len(self._positions) >= self._max_positions:
            return PositionSize(
                symbol=symbol,
                side=side,
                quantity=0.0,
                notional=0.0,
                risk_budget_usdt=risk_budget,
                risk_per_trade_pct=self._risk_per_trade,
                max_exposure_pct=self._max_exposure,
                within_limits=False,
                rejection_reason=f"Max positions reached: {self._max_positions}",
            )

        # Check total exposure
        total_exposure = sum(self._positions.values()) + notional
        max_total = equity * self._max_exposure * self._max_positions
        if total_exposure > max_total:
            return PositionSize(
                symbol=symbol,
                side=side,
                quantity=0.0,
                notional=0.0,
                risk_budget_usdt=risk_budget,
                risk_per_trade_pct=self._risk_per_trade,
                max_exposure_pct=self._max_exposure,
                within_limits=False,
                rejection_reason="Total exposure would exceed limit",
            )

        return PositionSize(
            symbol=symbol,
            side=side,
            quantity=qty,
            notional=notional,
            risk_budget_usdt=risk_budget,
            risk_per_trade_pct=self._risk_per_trade,
            max_exposure_pct=self._max_exposure,
            within_limits=True,
        )

    def open_position(self, symbol: str, notional: float) -> bool:
        """Record an open position."""
        if symbol in self._positions:
            self._log.warning("portfolio.duplicate_position", symbol=symbol)
            return False

        self._positions[symbol] = notional
        self._log.info("portfolio.position_opened", symbol=symbol, notional=notional)
        return True

    def close_position(self, symbol: str, pnl: float) -> None:
        """Record a position closure."""
        self._positions.pop(symbol, 0.0)
        self._capital += pnl
        self._daily_pnl += pnl

        if self._capital > self._peak_equity:
            self._peak_equity = self._capital

        self._log.info(
            "portfolio.position_closed",
            symbol=symbol,
            pnl=pnl,
            equity=self._capital,
        )

    def get_exposure(self) -> ExposureSnapshot:
        """Get current exposure state."""
        total = sum(self._positions.values())
        max_allowed = self._capital * self._max_exposure * self._max_positions

        return ExposureSnapshot(
            total_exposure=total,
            max_exposure=max_allowed,
            exposure_pct=total / max_allowed if max_allowed > 0 else 0.0,
            positions=dict(self._positions),
        )

    def check_risk_limits(self, equity: float) -> tuple[bool, str]:
        """Check if risk limits are breached."""
        # Check drawdown
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown >= self._max_drawdown:
                return False, f"Drawdown {drawdown:.2%} >= {self._max_drawdown:.2%}"

        # Check daily loss
        if self._initial_capital > 0:
            daily_loss_pct = abs(self._daily_pnl) / self._initial_capital
            if self._daily_pnl < 0 and daily_loss_pct >= self._max_daily_loss:
                return False, f"Daily loss {daily_loss_pct:.2%} >= {self._max_daily_loss:.2%}"

        return True, "OK"

    def reset_daily(self) -> None:
        """Reset daily tracking."""
        self._daily_pnl = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize state."""
        return {
            "capital": self._capital,
            "initial_capital": self._initial_capital,
            "positions": dict(self._positions),
            "daily_pnl": self._daily_pnl,
            "peak_equity": self._peak_equity,
            "exposure": self.get_exposure().total_exposure,
        }


__all__ = [
    "ExposureSnapshot",
    "PortfolioManager",
    "PositionSize",
]
