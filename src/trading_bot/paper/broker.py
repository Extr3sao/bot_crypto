"""Paper-broker: simulated fill engine with SL/TP + position tracking.

Replaces the TSK-105 stub with a real paper-trade simulator.
No real orders, no exchange connection, no credentials.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.strategies.types import Signal

from .types import PaperExecutionSummary


@dataclass(frozen=True, slots=True)
class PaperPosition:
    """An open paper position."""

    symbol: str
    side: str  # buy / sell
    entry_price: float
    quantity: float
    notional_usdt: float
    stop_loss_pct: float
    take_profit_pct: float
    opened_at: float = field(default_factory=time.time)
    entry_commission: float = 0.0  # tracked for true-net PnL at close

    @property
    def stop_loss_price(self) -> float:
        if self.side == "buy":
            return self.entry_price * (1.0 - self.stop_loss_pct / 100.0)
        return self.entry_price * (1.0 + self.stop_loss_pct / 100.0)

    @property
    def take_profit_price(self) -> float:
        if self.side == "buy":
            return self.entry_price * (1.0 + self.take_profit_pct / 100.0)
        return self.entry_price * (1.0 - self.take_profit_pct / 100.0)

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "buy":
            return (current_price - self.entry_price) * self.quantity
        return (self.entry_price - current_price) * self.quantity

    def check_exit(self, current_price: float) -> str | None:
        """Check if SL or TP is hit. Returns 'stop_loss' | 'take_profit' | None."""
        if self.side == "buy":
            if current_price <= self.stop_loss_price:
                return "stop_loss"
            if current_price >= self.take_profit_price:
                return "take_profit"
        else:
            if current_price >= self.stop_loss_price:
                return "stop_loss"
            if current_price <= self.take_profit_price:
                return "take_profit"
        return None


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """A completed paper trade."""

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    exit_reason: str  # stop_loss / take_profit / signal
    opened_at: float
    closed_at: float


class PaperBroker:
    """Paper-trade fill simulator.

    - Simulates fills at market price with configurable slippage.
    - Tracks open positions with SL/TP.
    - Checks SL/TP on each tick (reconcile_session).
    - Computes realized PnL.
    - Respects risk policy limits.
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        equity: float = 10_000.0,
        slippage_bps: float = 1.0,
        commission_bps: float = 5.0,
    ) -> None:
        del db_url  # legacy compat, unused
        self._equity = equity
        self._initial_equity = equity
        self._slippage_bps = slippage_bps
        self._commission_bps = commission_bps
        self._positions: dict[str, PaperPosition] = {}
        self._closed_trades: list[ClosedTrade] = []
        self._fills_opened = 0
        self._fills_closed = 0
        self._risk_events: list[str] = []
        self._log = structlog.get_logger("paper_broker")

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def positions(self) -> dict[str, PaperPosition]:
        return dict(self._positions)

    def __enter__(self) -> PaperBroker:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def execute_signal(self, signal: Signal) -> ClosedTrade | PaperPosition | None:
        """Execute a signal: open a new position.

        Returns the new PaperPosition if filled, None if rejected.
        Does NOT check risk — that's the RiskManager's job.
        """
        symbol = signal.symbol

        # Close existing position on same symbol if opposite side
        if symbol in self._positions:
            existing = self._positions[symbol]
            if existing.side != signal.side:
                self._log.info(
                    "paper.closing_opposite",
                    symbol=symbol,
                    existing_side=existing.side,
                    new_side=signal.side,
                )
                return self._close_position(symbol, signal.price, "signal")

        # Skip if already have position on this symbol (same side)
        if symbol in self._positions:
            self._log.info("paper.skip_duplicate", symbol=symbol)
            return None

        # Compute fill price with slippage
        slippage_mult = 1.0 + (self._slippage_bps / 10_000.0)
        if signal.side == "buy":
            fill_price = signal.price * slippage_mult
        else:
            fill_price = signal.price / slippage_mult

        # Compute quantity from position size in metadata
        notional = signal.metadata.get("notional_usdt", 0.0)
        if notional <= 0:
            # Fallback: use 1% of equity
            notional = self._equity * 0.01

        quantity = notional / fill_price
        commission = notional * (self._commission_bps / 10_000.0)

        # Create position
        sl_pct = signal.stop_loss_pct or 1.0
        tp_pct = signal.take_profit_pct or 2.0
        position = PaperPosition(
            symbol=symbol,
            side=signal.side,
            entry_price=fill_price,
            quantity=quantity,
            notional_usdt=notional,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            entry_commission=commission,
        )

        self._positions[symbol] = position
        self._fills_opened += 1
        # Do NOT deduct entry commission from equity here.
        # Entry commission is deducted at close time as part of true-net PnL
        # so that ClosedTrade.pnl = gross_pnl - entry_commission - exit_commission.
        # This ensures: equity == initial_equity + sum(ClosedTrade.pnl).

        self._log.info(
            "paper.fill_opened",
            symbol=symbol,
            side=signal.side,
            price=fill_price,
            quantity=quantity,
            notional=notional,
            entry_commission=commission,
        )

        return position

    def _close_position(self, symbol: str, exit_price: float, reason: str) -> ClosedTrade:
        """Close an existing position and compute PnL.

        PnL includes BOTH entry and exit commissions (true net PnL).
        This ensures: equity == initial_equity + sum(ClosedTrade.pnl).
        """
        pos = self._positions.pop(symbol)

        # Apply slippage on exit
        slippage_mult = 1.0 + (self._slippage_bps / 10_000.0)
        if pos.side == "buy":
            actual_exit = exit_price / slippage_mult
        else:
            actual_exit = exit_price * slippage_mult

        if pos.side == "buy":
            gross_pnl = (actual_exit - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - actual_exit) * pos.quantity

        # Deduct BOTH entry and exit commissions for true-net PnL
        entry_commission = pos.entry_commission
        exit_commission = pos.notional_usdt * (self._commission_bps / 10_000.0)
        net_pnl = gross_pnl - entry_commission - exit_commission

        trade = ClosedTrade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=actual_exit,
            quantity=pos.quantity,
            pnl=net_pnl,
            exit_reason=reason,
            opened_at=pos.opened_at,
            closed_at=time.time(),
        )

        self._closed_trades.append(trade)
        self._fills_closed += 1
        self._equity += net_pnl

        self._log.info(
            "paper.fill_closed",
            symbol=symbol,
            gross_pnl=gross_pnl,
            entry_commission=entry_commission,
            exit_commission=exit_commission,
            net_pnl=net_pnl,
            reason=reason,
            equity=self._equity,
        )

        return trade

    def check_positions(self, prices: dict[str, float]) -> list[ClosedTrade]:
        """Check all open positions against current prices for SL/TP.

        Uses only the close price. For OHLC-based checking, use
        ``check_positions_ohlc`` instead.

        Returns list of closed trades (if any SL/TP triggered).
        """
        closed: list[ClosedTrade] = []
        symbols_to_check = list(self._positions.keys())
        for symbol in symbols_to_check:
            if symbol not in self._positions:
                continue
            price = prices.get(symbol)
            if price is None:
                continue
            pos = self._positions[symbol]
            exit_reason = pos.check_exit(price)
            if exit_reason is not None:
                trade = self._close_position(symbol, price, exit_reason)
                closed.append(trade)
                self._risk_events.append(f"{symbol}:{exit_reason} at {price:.2f}")
        return closed

    def check_positions_ohlc(
        self,
        candles: dict[str, tuple[float, float, float, float]],
        *,
        both_hit_policy: str = "stop_first",
    ) -> list[ClosedTrade]:
        """Check positions using OHLC data (high/low) for more accurate SL/TP.

        For LONG positions:
            - SL triggered if low <= stop_price
            - TP triggered if high >= target_price
        For SHORT positions:
            - SL triggered if high >= stop_price
            - TP triggered if low <= target_price

        If both SL and TP are touched in the same candle, use ``both_hit_policy``:
            - "stop_first" (default): assume SL was hit first (conservative)
            - "tp_first": assume TP was hit first (optimistic)

        Args:
            candles: dict of symbol -> (open, high, low, close)
            both_hit_policy: How to handle simultaneous SL/TP hits.

        Returns:
            List of closed trades.
        """
        closed: list[ClosedTrade] = []
        symbols_to_check = list(self._positions.keys())

        for symbol in symbols_to_check:
            if symbol not in self._positions:
                continue
            ohlc = candles.get(symbol)
            if ohlc is None:
                continue

            _open, high, low, close = ohlc
            pos = self._positions[symbol]

            sl_hit = False
            tp_hit = False
            trigger_price = close  # default to close

            if pos.side == "buy":
                sl_price = pos.stop_loss_price
                tp_price = pos.take_profit_price
                sl_hit = low <= sl_price
                tp_hit = high >= tp_price

                if sl_hit and tp_hit:
                    # Both hit — apply policy
                    if both_hit_policy == "tp_first":
                        trigger_price = tp_price
                        exit_reason = "take_profit"
                    else:  # stop_first (default, conservative)
                        trigger_price = sl_price
                        exit_reason = "stop_loss"
                elif sl_hit:
                    trigger_price = sl_price
                    exit_reason = "stop_loss"
                elif tp_hit:
                    trigger_price = tp_price
                    exit_reason = "take_profit"
                else:
                    continue  # Neither hit

            else:  # sell (short)
                sl_price = pos.stop_loss_price
                tp_price = pos.take_profit_price
                sl_hit = high >= sl_price
                tp_hit = low <= tp_price

                if sl_hit and tp_hit:
                    if both_hit_policy == "tp_first":
                        trigger_price = tp_price
                        exit_reason = "take_profit"
                    else:
                        trigger_price = sl_price
                        exit_reason = "stop_loss"
                elif sl_hit:
                    trigger_price = sl_price
                    exit_reason = "stop_loss"
                elif tp_hit:
                    trigger_price = tp_price
                    exit_reason = "take_profit"
                else:
                    continue

            trade = self._close_position(symbol, trigger_price, exit_reason)
            closed.append(trade)
            self._risk_events.append(
                f"{symbol}:{exit_reason} at {trigger_price:.2f} (ohlc)"
            )

        return closed

    def reconcile_session(
        self,
        session_id: str,
        snapshots: Any,
        risk: Any,
    ) -> PaperExecutionSummary:
        """Reconcile: check positions against latest snapshot prices.

        This is called by PaperSessionRunner after the scanner run.
        """
        # Build price map from snapshots
        prices: dict[str, float] = {}
        for snap in snapshots:
            symbol = getattr(snap, "symbol", None)
            price = getattr(snap, "last_price", None)
            if symbol and price is not None:
                prices[symbol] = price

        # Check positions
        self.check_positions(prices)

        return PaperExecutionSummary(
            fills_opened=self._fills_opened,
            fills_closed=self._fills_closed,
            closed_trades=tuple(self._closed_trades),
            realized_pnl=sum(t.pnl for t in self._closed_trades),
            ending_equity=self._equity,
            risk_events=tuple(self._risk_events),
        )


__all__ = ["ClosedTrade", "PaperBroker", "PaperPosition"]
