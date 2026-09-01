"""Trade Journal for V0.3 — persists all paper trades.

V0.3 requires full audit trail of all paper trading decisions.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog


@dataclass(frozen=True, slots=True)
class TradeEntry:
    """A single trade entry in the journal."""

    trade_id: str
    strategy_id: str
    symbol: str
    side: str  # "buy" / "sell"
    timeframe: str

    # Entry details
    signal_timestamp: float
    entry_timestamp: float
    entry_price: float
    quantity: float
    notional: float

    # Exit details (filled when closed)
    exit_timestamp: float | None = None
    exit_price: float | None = None
    exit_reason: str = ""  # "stop_loss" / "take_profit" / "signal" / "kill_switch"

    # PnL (filled when closed)
    gross_pnl: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    net_pnl: float = 0.0

    # Decision audit
    signal_confidence: float = 0.0
    risk_check_passed: bool = True
    risk_check_reason: str = ""
    portfolio_decision: str = ""  # "EXECUTE" / "BLOCK"

    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "timeframe": self.timeframe,
            "signal_timestamp": self.signal_timestamp,
            "entry_timestamp": self.entry_timestamp,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "notional": self.notional,
            "exit_timestamp": self.exit_timestamp,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "gross_pnl": self.gross_pnl,
            "fees": self.fees,
            "slippage": self.slippage,
            "net_pnl": self.net_pnl,
            "signal_confidence": self.signal_confidence,
            "risk_check_passed": self.risk_check_passed,
            "risk_check_reason": self.risk_check_reason,
            "portfolio_decision": self.portfolio_decision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TradeJournal:
    """Persists all paper trades with full audit trail.

    V0.3: Every decision must be recorded.
    """

    def __init__(self, journal_dir: Path = Path("data/paper_journal")) -> None:
        self._journal_dir = journal_dir
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, TradeEntry] = {}
        self._log = structlog.get_logger("trade_journal")
        self._load_entries()

    def _load_entries(self) -> None:
        """Load existing entries from disk."""
        index_path = self._journal_dir / "index.json"
        if not index_path.exists():
            return

        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for trade_id in index.get("trade_ids", []):
                entry_path = self._journal_dir / f"{trade_id}.json"
                if entry_path.exists():
                    data = json.loads(entry_path.read_text(encoding="utf-8"))
                    entry = TradeEntry(**data)
                    self._entries[trade_id] = entry
        except Exception as e:
            self._log.warning("journal.load_failed", error=str(e))

    def _save_index(self) -> None:
        """Save trade ID index."""
        index_path = self._journal_dir / "index.json"
        index = {
            "trade_ids": list(self._entries.keys()),
            "updated_at": time.time(),
        }
        index_path.write_text(
            json.dumps(index, indent=2),
            encoding="utf-8",
        )

    def record_signal(
        self,
        trade_id: str,
        strategy_id: str,
        symbol: str,
        side: str,
        timeframe: str,
        signal_timestamp: float,
        entry_price: float,
        quantity: float,
        notional: float,
        signal_confidence: float = 0.0,
        risk_check_passed: bool = True,
        risk_check_reason: str = "",
        portfolio_decision: str = "EXECUTE",
    ) -> TradeEntry:
        """Record a new trade signal."""
        entry = TradeEntry(
            trade_id=trade_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            timeframe=timeframe,
            signal_timestamp=signal_timestamp,
            entry_timestamp=signal_timestamp,
            entry_price=entry_price,
            quantity=quantity,
            notional=notional,
            signal_confidence=signal_confidence,
            risk_check_passed=risk_check_passed,
            risk_check_reason=risk_check_reason,
            portfolio_decision=portfolio_decision,
        )

        self._entries[trade_id] = entry
        self._save_entry(entry)
        self._save_index()

        self._log.info(
            "journal.signal_recorded",
            trade_id=trade_id,
            symbol=symbol,
            side=side,
        )

        return entry

    def record_exit(
        self,
        trade_id: str,
        exit_timestamp: float,
        exit_price: float,
        exit_reason: str,
        gross_pnl: float,
        fees: float,
        slippage: float,
        net_pnl: float,
    ) -> TradeEntry | None:
        """Record trade exit."""
        entry = self._entries.get(trade_id)
        if entry is None:
            self._log.warning("journal.trade_not_found", trade_id=trade_id)
            return None

        # Create updated entry (frozen dataclass)
        updated = TradeEntry(
            trade_id=entry.trade_id,
            strategy_id=entry.strategy_id,
            symbol=entry.symbol,
            side=entry.side,
            timeframe=entry.timeframe,
            signal_timestamp=entry.signal_timestamp,
            entry_timestamp=entry.entry_timestamp,
            entry_price=entry.entry_price,
            quantity=entry.quantity,
            notional=entry.notional,
            exit_timestamp=exit_timestamp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees=fees,
            slippage=slippage,
            net_pnl=net_pnl,
            signal_confidence=entry.signal_confidence,
            risk_check_passed=entry.risk_check_passed,
            risk_check_reason=entry.risk_check_reason,
            portfolio_decision=entry.portfolio_decision,
            created_at=entry.created_at,
            updated_at=time.time(),
        )

        self._entries[trade_id] = updated
        self._save_entry(updated)

        self._log.info(
            "journal.exit_recorded",
            trade_id=trade_id,
            exit_reason=exit_reason,
            net_pnl=net_pnl,
        )

        return updated

    def get_trade(self, trade_id: str) -> TradeEntry | None:
        """Get a trade by ID."""
        return self._entries.get(trade_id)

    def get_strategy_trades(self, strategy_id: str) -> list[TradeEntry]:
        """Get all trades for a strategy."""
        return [e for e in self._entries.values() if e.strategy_id == strategy_id]

    def get_open_trades(self) -> list[TradeEntry]:
        """Get all open trades (no exit)."""
        return [e for e in self._entries.values() if e.exit_timestamp is None]

    def get_closed_trades(self) -> list[TradeEntry]:
        """Get all closed trades."""
        return [e for e in self._entries.values() if e.exit_timestamp is not None]

    def get_summary(self) -> dict[str, Any]:
        """Get journal summary."""
        closed = self.get_closed_trades()
        open_trades = self.get_open_trades()

        total_pnl = sum(t.net_pnl for t in closed)
        wins = [t for t in closed if t.net_pnl > 0]
        losses = [t for t in closed if t.net_pnl <= 0]

        return {
            "total_trades": len(self._entries),
            "open_trades": len(open_trades),
            "closed_trades": len(closed),
            "total_pnl": total_pnl,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) if closed else 0.0,
            "avg_pnl": total_pnl / len(closed) if closed else 0.0,
        }

    def _save_entry(self, entry: TradeEntry) -> None:
        """Save a single entry to disk."""
        path = self._journal_dir / f"{entry.trade_id}.json"
        path.write_text(
            json.dumps(entry.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )


__all__ = [
    "TradeEntry",
    "TradeJournal",
]
