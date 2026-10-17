"""Paper-broker: simulated fill engine with SL/TP + position tracking.

Replaces the TSK-105 stub with a real paper-trade simulator.
No real orders, no exchange connection, no credentials.

Fail-loud contract (DEF-3, paper operational phase): an order without a
risk-approved ``notional_usdt`` raises ``BrokerOrderError`` — the broker
never invents sizing, and silent fallbacks are forbidden on the decision
path. Exceptions raised here are caught by ``PaperCycleEngine`` (stage
``broker``, reason recorded, zero orders) or propagate to the session
runner, which fails the session explicitly.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.strategies.types import Signal

from .types import PaperExecutionSummary


class BrokerOrderError(Exception):
    """Raised when an order cannot be constructed deterministically.

    The paper broker NEVER invents sizing: if a signal arrives without the
    risk-approved ``notional_usdt`` metadata, this is a pipeline integrity
    failure (Risk must have sized the order) — fail loud, never fall back to
    a silent equity percentage.
    """


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
    # AUDIT-V1 provenance: originating strategy (travels to ClosedTrade for
    # PnL-by-strategy attribution).
    strategy_name: str = ""
    # WP-EDGE-015/P0.3: stable identity. A position is named by the broker, not
    # inferred from a wall-clock field two fast fills can share.
    position_id: str = ""
    entry_order_id: str = ""

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

    def to_row(self) -> dict[str, Any]:
        """JSON-safe row for the durable state store (GAP-R1)."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "notional_usdt": self.notional_usdt,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "opened_at": self.opened_at,
            "position_id": self.position_id,
            "entry_order_id": self.entry_order_id,
            "entry_commission": self.entry_commission,
            "strategy_name": self.strategy_name,
        }

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
    """A completed paper trade.

    ``pnl`` is net of both commissions; ``gross_pnl`` and the two commission
    legs are carried so a reader can rebuild that number instead of trusting
    it (WP-EDGE-015/P0.4).
    """

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    exit_reason: str  # stop_loss / take_profit / signal
    opened_at: float
    closed_at: float
    strategy_name: str = ""  # AUDIT-V1 provenance
    # WP-EDGE-015/P0.3-P0.4: identity and the decomposition of ``pnl``.
    trade_id: str = ""
    position_id: str = ""
    entry_order_id: str = ""
    exit_order_id: str = ""
    gross_pnl: float = 0.0
    entry_commission: float = 0.0
    exit_commission: float = 0.0


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
        book_id: str | None = None,
    ) -> None:
        del db_url  # legacy compat, unused
        #: Names the book these identifiers belong to. Callers that replay a
        #: fixed dataset pass a fixed one so the identifiers are reproducible;
        #: otherwise it is unique per broker instance, so two books can never
        #: mint the same id (the defect `(symbol, opened_at)` had).
        self._book_id = (
            book_id or hashlib.sha256(f"{equity}|{time.time_ns()}".encode()).hexdigest()[:8]
        )
        self._sequence = 0
        self._equity = equity
        self._initial_equity = equity
        self._slippage_bps = slippage_bps
        self._commission_bps = commission_bps
        self._positions: dict[str, PaperPosition] = {}
        self._closed_trades: list[ClosedTrade] = []
        self._fills_opened = 0
        self._fills_closed = 0
        # BURN-IN-V1 DEF-101: count of closed trades already reported to the
        # risk engine. reconcile_session reports ONLY the delta each call,
        # so the runner never re-feeds historical PnL into RiskManager
        # (a cumulative double-count that inflated trades_today/daily_pnl
        # until the daily trade limit vetoed everything).
        self._risk_reported_closed = 0
        self._risk_events: list[str] = []
        self._log = structlog.get_logger("paper_broker")

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def book_id(self) -> str:
        return self._book_id

    def _next_id(self, kind: str) -> str:
        """Mint a stable, unique identifier: ``<kind>-<book>-<sequence>``.

        Purely sequential inside the book, so a replay of the same input
        sequence mints the same identifiers, and no two events of one book
        share one. Uniqueness across books comes from ``book_id``.
        """
        self._sequence += 1
        return f"{kind}-{self._book_id}-{self._sequence:08d}"

    @property
    def positions(self) -> dict[str, PaperPosition]:
        return dict(self._positions)

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        """Read-only view of realized trades (observability/recovery)."""
        return list(self._closed_trades)

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

        # Compute quantity from position size in metadata.
        # Risk authority invariant: execute_signal is only reachable with a
        # risk-approved size; a missing/invalid notional means the signal
        # bypassed the RiskManager rebuild — reject loudly instead of
        # silently sizing at an arbitrary equity fraction (false success).
        notional = float(signal.metadata.get("notional_usdt", 0.0) or 0.0)
        if notional <= 0:
            raise BrokerOrderError(
                f"signal for {symbol} lacks risk-approved notional_usdt metadata "
                "(pipeline integrity: order must be sized by RiskManager)"
            )

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
            strategy_name=str(signal.strategy_name or ""),
            position_id=self._next_id("pos"),
            entry_order_id=self._next_id("ord"),
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
            strategy_name=pos.strategy_name,
            trade_id=self._next_id("trd"),
            position_id=pos.position_id,
            entry_order_id=pos.entry_order_id,
            exit_order_id=self._next_id("ordx"),
            gross_pnl=gross_pnl,
            entry_commission=entry_commission,
            exit_commission=exit_commission,
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

        Fail-closed (DEF-205): prices <= 0 are NEVER valid mark prices.
        An inactive scanner snapshot carries ``last_price=0.0``; honoring
        it would close positions at price zero (observed in
        PAPER-BURN-IN-V2: BTC position closed at 0 → -100% notional loss
        and a cascading Daily loss limit lockout). Such prices are
        skipped exactly like missing ones.

        Returns list of closed trades (if any SL/TP triggered).
        """
        closed: list[ClosedTrade] = []
        symbols_to_check = list(self._positions.keys())
        for symbol in symbols_to_check:
            if symbol not in self._positions:
                continue
            price = prices.get(symbol)
            if price is None or price <= 0:
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
            self._risk_events.append(f"{symbol}:{exit_reason} at {trigger_price:.2f} (ohlc)")

        return closed

    def reconcile_session(
        self,
        session_id: str,
        snapshots: Any,
        risk: Any,
    ) -> PaperExecutionSummary:
        """Reconcile: check positions against latest snapshot prices.

        This is called by PaperSessionRunner after the scanner run.
        Returns the FULL ledger (observability/reporting), but the
        ``new_closed_trades`` field carries only the delta since the last
        call — the runner feeds THAT to RiskManager (DEF-101: re-feeding
        the whole ledger double-counted PnL and trade counts).
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

        new_closed = tuple(self._closed_trades[self._risk_reported_closed :])
        # Advance the report cursor: the caller feeds exactly this delta to
        # the risk engine, so the next reconcile must not re-report it.
        self._risk_reported_closed = len(self._closed_trades)
        return PaperExecutionSummary(
            fills_opened=self._fills_opened,
            fills_closed=self._fills_closed,
            closed_trades=tuple(self._closed_trades),
            new_closed_trades=new_closed,
            realized_pnl=sum(t.pnl for t in self._closed_trades),
            ending_equity=self._equity,
            risk_events=tuple(self._risk_events),
        )

    # -- mark-to-market (AUDIT-V1 §13) ----------------------------------------

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Sum unrealized PnL over open positions at valid PIT prices.

        Positions without a price in ``prices`` are skipped (never guessed):
        the caller passes the latest closed-candle closes per symbol.
        """
        total = 0.0
        for symbol, pos in self._positions.items():
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue
            total += pos.unrealized_pnl(price)
        return total

    def accrued_entry_commissions(self) -> float:
        """Entry commissions of positions still open, withheld from equity.

        The broker charges both legs at close (``_close_position``), so while a
        position is open its entry commission is an accrual, not yet a cash
        movement. It is kept as its own term so the accounting identity closes
        instead of being quietly omitted.
        """
        return sum(pos.entry_commission for pos in self._positions.values())

    def unrealized_pnl_net(self, prices: dict[str, float]) -> float:
        """Open-position PnL net of the entry commissions still accrued."""
        return self.unrealized_pnl(prices) - self.accrued_entry_commissions()

    def mark_to_market_equity(self, prices: dict[str, float]) -> float:
        """Ledger cash plus open PnL, net of the accrued entry commissions.

        This is the economically complete view requested in WP-EDGE-015/P0.4:
        a position that is open at the end of a replay contributes its marked
        PnL *and* the commission already owed on its entry.
        """
        return self._equity + self.unrealized_pnl_net(prices)

    def accounting_snapshot(self, prices: dict[str, float] | None = None) -> dict[str, Any]:
        """The four quantities kept apart, with their identities checked.

        ``realised_pnl`` is the sum of closed trades net of both commissions;
        ``cash`` is the ledger (initial + realised); ``unrealised_pnl`` is the
        mark of the positions still open; ``equity_mark_to_market`` is cash plus
        that mark net of accrued entry commissions. Returning them separately,
        and returning the residuals of the identities, is the point: a single
        "equity" number cannot show which of the four went wrong.
        """
        mark_prices = dict(prices or {})
        realised = sum(trade.pnl for trade in self._closed_trades)
        gross = self.unrealized_pnl(mark_prices)
        accrued = self.accrued_entry_commissions()
        cash = self._initial_equity + realised
        equity = cash + gross - accrued
        return {
            "initial_equity": self._initial_equity,
            "cash": cash,
            "realised_pnl": realised,
            "unrealised_pnl": gross,
            "accrued_entry_commissions": accrued,
            "unrealised_pnl_net": gross - accrued,
            "equity_mark_to_market": equity,
            "ledger_equity": self._equity,
            "open_positions": [
                {
                    "position_id": pos.position_id,
                    "entry_order_id": pos.entry_order_id,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "quantity": pos.quantity,
                    "notional_usdt": pos.notional_usdt,
                    "unrealised_pnl": pos.unrealized_pnl(mark_prices[pos.symbol])
                    if mark_prices.get(pos.symbol, 0.0) > 0
                    else 0.0,
                    "mark_price": mark_prices.get(pos.symbol, 0.0),
                }
                for pos in self._positions.values()
            ],
            "identities": {
                "cash_equals_initial_plus_realised": abs(cash - (self._initial_equity + realised))
                <= 1e-9,
                "ledger_equity_equals_initial_plus_realised": abs(self._equity - cash) <= 1e-9,
                "equity_equals_cash_plus_net_unrealised": abs(equity - (cash + gross - accrued))
                <= 1e-9,
                "closed_trade_pnl_rebuilds": all(
                    abs(
                        trade.pnl
                        - (trade.gross_pnl - trade.entry_commission - trade.exit_commission)
                    )
                    <= 1e-9
                    for trade in self._closed_trades
                ),
            },
        }

    # -- durable state (GAP-R1) ----------------------------------------------

    def extract_state(self) -> dict[str, Any]:
        """JSON-safe economic state for the durable store."""
        return {
            "equity": self._equity,
            "initial_equity": self._initial_equity,
            "fills_opened": self._fills_opened,
            "fills_closed": self._fills_closed,
        }

    def closed_trades_rows(self) -> list[dict[str, Any]]:
        """Realized trades as JSON-safe rows (true-net PnL records)."""
        return [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "exit_reason": t.exit_reason,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
                "strategy_name": t.strategy_name,
                "trade_id": t.trade_id,
                "position_id": t.position_id,
                "entry_order_id": t.entry_order_id,
                "exit_order_id": t.exit_order_id,
                "gross_pnl": t.gross_pnl,
                "entry_commission": t.entry_commission,
                "exit_commission": t.exit_commission,
            }
            for t in self._closed_trades
        ]

    def restore(
        self,
        *,
        equity: float,
        initial_equity: float,
        fills_opened: int,
        fills_closed: int,
        open_positions: list[PaperPosition],
        closed_trades: list[dict[str, Any]],
    ) -> None:
        """Replace the in-memory book with the persisted one (deterministic).

        Callers must pass rows produced by ``closed_trades_rows`` (or an
        identical shape). No validation here beyond types: the equity
        identity check belongs to the reconciler (fail closed).
        """
        self._equity = float(equity)
        self._initial_equity = float(initial_equity)
        self._fills_opened = int(fills_opened)
        self._fills_closed = int(fills_closed)
        self._positions = {p.symbol: p for p in open_positions}
        self._closed_trades = [_closed_trade_from_row(row) for row in closed_trades]
        # Continue the identifier sequence past everything the restored book
        # already minted, so a recovered session never reuses an id.
        for token in [p.position_id for p in self._positions.values()] + [
            p.entry_order_id for p in self._positions.values()
        ]:
            self._sequence = max(self._sequence, _sequence_of(token))
        for trade in self._closed_trades:
            for token in (
                trade.trade_id,
                trade.position_id,
                trade.entry_order_id,
                trade.exit_order_id,
            ):
                self._sequence = max(self._sequence, _sequence_of(token))
        # Restored history was ALREADY accounted by Risk before the crash
        # (counters travel in risk_state) — mark it as reported so the next
        # reconcile_session does not re-feed it (DEF-101).
        self._risk_reported_closed = len(self._closed_trades)

    def replace_position(self, position: PaperPosition) -> None:
        """Upsert one position (crash-recovery of the fill boundary)."""
        self._positions[position.symbol] = position

    def register_external_fill(self) -> None:
        """Count an externally-materialized fill (reconciliation bookkeeping)."""
        self._fills_opened += 1

    def apply_pnl(self, pnl: float) -> None:
        """Apply a realized PnL to equity without creating a trade row
        (used only by recovery paths; normal trading always goes through
        ``_close_position`` so the closed-trade ledger stays complete)."""
        self._equity += float(pnl)


def _sequence_of(identifier: str) -> int:
    """The sequence number inside ``<kind>-<book>-<sequence>``, or 0."""
    tail = identifier.rsplit("-", 1)[-1] if identifier else ""
    return int(tail) if tail.isdigit() else 0


def _closed_trade_from_row(row: dict[str, Any]) -> ClosedTrade:
    """Rebuild a ClosedTrade from a persisted row, newest fields defaulted."""
    known = {f for f in ClosedTrade.__dataclass_fields__}
    payload = {key: value for key, value in row.items() if key in known}
    return ClosedTrade(**payload)


__all__ = ["BrokerOrderError", "ClosedTrade", "PaperBroker", "PaperPosition"]
