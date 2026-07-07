"""Minimal persistent paper broker driven by scanner snapshots."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from trading_bot.config.risk import Risk
from trading_bot.scanner import MarketSnapshot
from trading_bot.storage.ohlcv_store import _parse_sqlite_url

from .types import (
    PaperClosedTrade,
    PaperExecutionSummary,
    PaperFill,
    PaperPosition,
)


class PaperBroker:
    """Executes a simple snapshot-driven paper portfolio policy.

    Policy for the current TSK-105 slice:
    - Open a position when a symbol becomes active and there is free capacity.
    - Keep the position while the symbol remains active.
    - Close the position when the symbol is no longer active.
    - Position size is capped by the configured risk notionals.
    """

    def __init__(
        self,
        database_url: str,
        *,
        initial_cash: float = 10_000.0,
        commission_rate: float = 0.001,
    ) -> None:
        if initial_cash <= 0.0:
            raise ValueError("initial_cash debe ser > 0.")
        if commission_rate < 0.0:
            raise ValueError("commission_rate debe ser >= 0.")

        db_path = _parse_sqlite_url(database_url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._commission_rate = commission_rate
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_account (
                account_id INTEGER PRIMARY KEY CHECK (account_id = 1),
                cash_balance REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO paper_account (account_id, cash_balance)
            VALUES (1, ?)
            ON CONFLICT (account_id) DO NOTHING
            """,
            (initial_cash,),
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol TEXT PRIMARY KEY,
                qty REAL NOT NULL,
                entry_price REAL NOT NULL,
                entry_commission REAL NOT NULL,
                opened_at_ms INTEGER NOT NULL,
                last_price REAL NOT NULL,
                marked_at_ms INTEGER NOT NULL,
                notional_usdt REAL NOT NULL,
                sessions_held INTEGER NOT NULL,
                entry_fill_id TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_fills (
                fill_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                fill_price REAL NOT NULL,
                reference_price REAL NOT NULL,
                commission REAL NOT NULL,
                slippage_bps REAL NOT NULL,
                notional_usdt REAL NOT NULL,
                timestamp INTEGER NOT NULL,
                reason TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_closed_trades (
                trade_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                qty REAL NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                opened_at_ms INTEGER NOT NULL,
                closed_at_ms INTEGER NOT NULL,
                realized_pnl REAL NOT NULL,
                realized_pnl_pct REAL NOT NULL,
                total_commission REAL NOT NULL,
                sessions_held INTEGER NOT NULL,
                entry_fill_id TEXT NOT NULL,
                exit_fill_id TEXT NOT NULL
            )
            """
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    def reconcile_session(
        self,
        session_id: str,
        snapshots: list[MarketSnapshot],
        risk: Risk,
    ) -> PaperExecutionSummary:
        if not snapshots:
            cash_balance = self._get_cash_balance()
            return PaperExecutionSummary(
                ending_cash=cash_balance,
                ending_equity=cash_balance,
            )

        snapshot_by_symbol = {snapshot.symbol: snapshot for snapshot in snapshots}
        active_symbols = [
            snapshot.symbol
            for snapshot in sorted(
                (snapshot for snapshot in snapshots if snapshot.active),
                key=lambda snapshot: snapshot.rank_score,
                reverse=True,
            )[: risk.max_open_positions]
        ]
        open_positions = self._load_open_positions()
        fills: list[PaperFill] = []
        closed_trades: list[PaperClosedTrade] = []
        cash_balance = self._get_cash_balance()

        for symbol, position in list(open_positions.items()):
            snapshot = snapshot_by_symbol.get(symbol)
            if snapshot is None:
                continue
            if symbol not in active_symbols:
                sell_fill = self._build_sell_fill(
                    session_id=session_id,
                    snapshot=snapshot,
                    position=position,
                )
                cash_balance += sell_fill.notional_usdt - sell_fill.commission
                self._set_cash_balance(cash_balance)
                fills.append(sell_fill)
                closed_trade = self._close_position(
                    session_id=session_id,
                    position=position,
                    sell_fill=sell_fill,
                )
                closed_trades.append(closed_trade)
                del open_positions[symbol]
            else:
                updated_position = self._mark_position(position, snapshot)
                self._upsert_position(updated_position)
                open_positions[symbol] = updated_position

        for symbol in active_symbols:
            if symbol in open_positions:
                continue
            if len(open_positions) >= risk.max_open_positions:
                break
            snapshot = snapshot_by_symbol[symbol]
            slots_remaining = max(risk.max_open_positions - len(open_positions), 1)
            target_notional = min(
                risk.max_order_notional_usdt,
                cash_balance / slots_remaining,
            )
            if target_notional < risk.min_order_notional_usdt:
                continue
            buy_fill = self._build_buy_fill(
                session_id=session_id,
                snapshot=snapshot,
                notional_usdt=target_notional,
            )
            total_cash_required = buy_fill.notional_usdt + buy_fill.commission
            if total_cash_required > cash_balance:
                continue
            cash_balance -= total_cash_required
            self._set_cash_balance(cash_balance)
            fills.append(buy_fill)
            position = PaperPosition(
                symbol=snapshot.symbol,
                qty=buy_fill.qty,
                entry_price=buy_fill.fill_price,
                entry_commission=buy_fill.commission,
                opened_at_ms=buy_fill.timestamp,
                last_price=snapshot.last_price,
                marked_at_ms=snapshot.timestamp,
                notional_usdt=buy_fill.notional_usdt,
                unrealized_pnl=(snapshot.last_price - buy_fill.fill_price) * buy_fill.qty,
                sessions_held=1,
            )
            self._insert_position(position, buy_fill.fill_id)
            open_positions[symbol] = position

        current_positions: list[PaperPosition] = []
        unrealized_pnl = 0.0
        for position in self._load_open_positions().values():
            snapshot = snapshot_by_symbol.get(position.symbol)
            current_position = position
            if snapshot is not None:
                current_position = self._mark_position(position, snapshot)
                self._upsert_position(current_position)
            current_positions.append(current_position)
            unrealized_pnl += current_position.unrealized_pnl

        realized_pnl = sum(trade.realized_pnl for trade in closed_trades)
        ending_cash = self._get_cash_balance()
        ending_equity = ending_cash + unrealized_pnl
        closed_wins = sum(1 for trade in closed_trades if trade.realized_pnl > 0.0)
        win_rate_closed = (closed_wins / len(closed_trades)) if closed_trades else 0.0

        return PaperExecutionSummary(
            fills=fills,
            open_positions=sorted(current_positions, key=lambda position: position.symbol),
            closed_trades=closed_trades,
            fills_opened=sum(1 for fill in fills if fill.side == "buy"),
            fills_closed=sum(1 for fill in fills if fill.side == "sell"),
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            ending_cash=ending_cash,
            ending_equity=ending_equity,
            win_rate_closed=win_rate_closed,
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PaperBroker:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _get_cash_balance(self) -> float:
        row = self._conn.execute(
            "SELECT cash_balance FROM paper_account WHERE account_id = 1"
        ).fetchone()
        return float(row[0]) if row is not None else 0.0

    def _set_cash_balance(self, cash_balance: float) -> None:
        self._conn.execute(
            "UPDATE paper_account SET cash_balance = ? WHERE account_id = 1",
            (cash_balance,),
        )

    def _load_open_positions(self) -> dict[str, PaperPosition]:
        cur = self._conn.execute(
            """
            SELECT symbol, qty, entry_price, entry_commission, opened_at_ms,
                   last_price, marked_at_ms, notional_usdt, sessions_held
            FROM paper_positions
            ORDER BY symbol ASC
            """
        )
        return {
            str(row[0]): PaperPosition(
                symbol=str(row[0]),
                qty=float(row[1]),
                entry_price=float(row[2]),
                entry_commission=float(row[3]),
                opened_at_ms=int(row[4]),
                last_price=float(row[5]),
                marked_at_ms=int(row[6]),
                notional_usdt=float(row[7]),
                unrealized_pnl=(float(row[5]) - float(row[2])) * float(row[1]),
                sessions_held=int(row[8]),
            )
            for row in cur.fetchall()
        }

    def _insert_position(self, position: PaperPosition, entry_fill_id: str) -> None:
        self._conn.execute(
            """
            INSERT INTO paper_positions (
                symbol, qty, entry_price, entry_commission, opened_at_ms, last_price,
                marked_at_ms, notional_usdt, sessions_held, entry_fill_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.symbol,
                position.qty,
                position.entry_price,
                position.entry_commission,
                position.opened_at_ms,
                position.last_price,
                position.marked_at_ms,
                position.notional_usdt,
                position.sessions_held,
                entry_fill_id,
            ),
        )

    def _upsert_position(self, position: PaperPosition) -> None:
        self._conn.execute(
            """
            UPDATE paper_positions
            SET qty = ?, entry_price = ?, entry_commission = ?, opened_at_ms = ?,
                last_price = ?, marked_at_ms = ?, notional_usdt = ?, sessions_held = ?
            WHERE symbol = ?
            """,
            (
                position.qty,
                position.entry_price,
                position.entry_commission,
                position.opened_at_ms,
                position.last_price,
                position.marked_at_ms,
                position.notional_usdt,
                position.sessions_held,
                position.symbol,
            ),
        )

    def _build_buy_fill(
        self,
        *,
        session_id: str,
        snapshot: MarketSnapshot,
        notional_usdt: float,
    ) -> PaperFill:
        slippage_bps = snapshot.spread_bps / 2.0
        fill_price = snapshot.last_price * (1.0 + slippage_bps / 10_000.0)
        qty = notional_usdt / fill_price
        commission = notional_usdt * self._commission_rate
        fill = PaperFill(
            fill_id=uuid4().hex,
            symbol=snapshot.symbol,
            side="buy",
            qty=qty,
            fill_price=fill_price,
            reference_price=snapshot.last_price,
            commission=commission,
            slippage_bps=slippage_bps,
            notional_usdt=notional_usdt,
            timestamp=snapshot.timestamp,
            reason="entered_on_active_signal",
        )
        self._insert_fill(fill, session_id)
        return fill

    def _build_sell_fill(
        self,
        *,
        session_id: str,
        snapshot: MarketSnapshot,
        position: PaperPosition,
    ) -> PaperFill:
        slippage_bps = snapshot.spread_bps / 2.0
        fill_price = snapshot.last_price * (1.0 - slippage_bps / 10_000.0)
        notional_usdt = fill_price * position.qty
        commission = notional_usdt * self._commission_rate
        fill = PaperFill(
            fill_id=uuid4().hex,
            symbol=snapshot.symbol,
            side="sell",
            qty=position.qty,
            fill_price=fill_price,
            reference_price=snapshot.last_price,
            commission=commission,
            slippage_bps=slippage_bps,
            notional_usdt=notional_usdt,
            timestamp=snapshot.timestamp,
            reason="exited_on_inactive_signal",
        )
        self._insert_fill(fill, session_id)
        return fill

    def _insert_fill(self, fill: PaperFill, session_id: str) -> None:
        self._conn.execute(
            """
            INSERT INTO paper_fills (
                fill_id, session_id, symbol, side, qty, fill_price, reference_price,
                commission, slippage_bps, notional_usdt, timestamp, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill.fill_id,
                session_id,
                fill.symbol,
                fill.side,
                fill.qty,
                fill.fill_price,
                fill.reference_price,
                fill.commission,
                fill.slippage_bps,
                fill.notional_usdt,
                fill.timestamp,
                fill.reason,
            ),
        )

    def _close_position(
        self,
        *,
        session_id: str,
        position: PaperPosition,
        sell_fill: PaperFill,
    ) -> PaperClosedTrade:
        row = self._conn.execute(
            "SELECT entry_fill_id FROM paper_positions WHERE symbol = ?",
            (position.symbol,),
        ).fetchone()
        entry_fill_id = str(row[0]) if row is not None else ""
        total_commission = position.entry_commission + sell_fill.commission
        realized_pnl = (
            (sell_fill.fill_price - position.entry_price) * position.qty - total_commission
        )
        invested = position.entry_price * position.qty + position.entry_commission
        realized_pnl_pct = realized_pnl / invested if invested > 0.0 else 0.0
        trade = PaperClosedTrade(
            trade_id=uuid4().hex,
            symbol=position.symbol,
            qty=position.qty,
            entry_price=position.entry_price,
            exit_price=sell_fill.fill_price,
            opened_at_ms=position.opened_at_ms,
            closed_at_ms=sell_fill.timestamp,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            total_commission=total_commission,
            sessions_held=position.sessions_held,
            entry_fill_id=entry_fill_id,
            exit_fill_id=sell_fill.fill_id,
        )
        self._conn.execute(
            """
            INSERT INTO paper_closed_trades (
                trade_id, session_id, symbol, qty, entry_price, exit_price,
                opened_at_ms, closed_at_ms, realized_pnl, realized_pnl_pct,
                total_commission, sessions_held, entry_fill_id, exit_fill_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.trade_id,
                session_id,
                trade.symbol,
                trade.qty,
                trade.entry_price,
                trade.exit_price,
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.realized_pnl,
                trade.realized_pnl_pct,
                trade.total_commission,
                trade.sessions_held,
                trade.entry_fill_id,
                trade.exit_fill_id,
            ),
        )
        self._conn.execute("DELETE FROM paper_positions WHERE symbol = ?", (position.symbol,))
        return trade

    def _mark_position(self, position: PaperPosition, snapshot: MarketSnapshot) -> PaperPosition:
        return PaperPosition(
            symbol=position.symbol,
            qty=position.qty,
            entry_price=position.entry_price,
            entry_commission=position.entry_commission,
            opened_at_ms=position.opened_at_ms,
            last_price=snapshot.last_price,
            marked_at_ms=snapshot.timestamp,
            notional_usdt=position.notional_usdt,
            unrealized_pnl=(snapshot.last_price - position.entry_price) * position.qty,
            sessions_held=position.sessions_held + 1,
        )


__all__ = ["PaperBroker"]
