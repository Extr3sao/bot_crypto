"""Startup reconciliation — broker vs journal position alignment.

Fase 8: On startup, broker and journal must agree on open positions.
Never ignore discrepancies: either RESTORE_FROM_JOURNAL or CLOSE_ORPHANED.

Produces a startup_reconciliation_report.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from trading_bot.observability.journal import TradeJournal


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Result of broker-vs-journal reconciliation."""

    timestamp: float
    broker_open_count: int
    journal_open_count: int
    matched: int
    orphaned_in_broker: list[str]  # in broker but not journal
    orphaned_in_journal: list[str]  # in journal but not broker
    reconciled: list[str]  # actions taken
    status: str  # "ok" / "discrepancies_found" / "errors"


@dataclass
class StartupReconciler:
    """Reconciles broker positions with journal on startup.

    Policy: CLOSE_ORPHANED — positions in journal but not in broker
    are closed with reason "position_missing_on_startup".
    """

    def __init__(
        self,
        journal: TradeJournal,
        report_dir: str = "data/storage",
    ) -> None:
        self._journal = journal
        self._report_dir = Path(report_dir)
        self._log = structlog.get_logger("reconciliation")

    def reconcile(
        self,
        broker_positions: dict[str, Any],
    ) -> ReconciliationResult:
        """Reconcile broker positions with journal open trades.

        Args:
            broker_positions: dict of symbol -> position from broker.

        Returns:
            ReconciliationResult with details of what was found/fixed.
        """
        now = time.time()

        # Get journal open trades
        journal_open = self._journal.get_open_trades()
        journal_symbols = {t["symbol"] for t in journal_open}
        broker_symbols = set(broker_positions.keys())

        # Find orphans
        orphaned_in_broker = sorted(broker_symbols - journal_symbols)
        orphaned_in_journal = sorted(journal_symbols - broker_symbols)
        matched = sorted(broker_symbols & journal_symbols)

        reconciled: list[str] = []

        # Close orphaned journal positions (policy: CLOSE_ORPHANED)
        for symbol in orphaned_in_journal:
            for trade in journal_open:
                if trade["symbol"] == symbol:
                    trade_id = trade["trade_id"]
                    try:
                        # Record as closed with reason
                        from trading_bot.paper.broker import ClosedTrade
                        fake_close = ClosedTrade(
                            symbol=symbol,
                            side=trade.get("side", "buy"),
                            entry_price=trade.get("entry_price", 0.0),
                            exit_price=trade.get("entry_price", 0.0),  # assume breakeven
                            quantity=trade.get("quantity", 0.0),
                            pnl=0.0,
                            exit_reason="position_missing_on_startup",
                            opened_at=trade.get("opened_at", 0.0),
                            closed_at=now,
                        )
                        self._journal.record_close(trade_id, fake_close)
                        reconciled.append(f"closed_journal:{trade_id}")
                        self._log.warning(
                            "reconciliation.closed_orphan",
                            trade_id=trade_id,
                            symbol=symbol,
                        )
                    except Exception as exc:
                        self._log.error(
                            "reconciliation.close_failed",
                            trade_id=trade_id,
                            error=str(exc),
                        )
                    break

        # Determine status
        if not orphaned_in_broker and not orphaned_in_journal:
            status = "ok"
        else:
            status = "discrepancies_found"

        result = ReconciliationResult(
            timestamp=now,
            broker_open_count=len(broker_positions),
            journal_open_count=len(journal_open),
            matched=len(matched),
            orphaned_in_broker=orphaned_in_broker,
            orphaned_in_journal=orphaned_in_journal,
            reconciled=reconciled,
            status=status,
        )

        # Save report
        self._save_report(result)

        return result

    def _save_report(self, result: ReconciliationResult) -> None:
        """Save reconciliation report to JSON."""
        self._report_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._report_dir / "startup_reconciliation_report.json"

        report = {
            "timestamp": result.timestamp,
            "status": result.status,
            "broker_open_count": result.broker_open_count,
            "journal_open_count": result.journal_open_count,
            "matched": result.matched,
            "orphaned_in_broker": result.orphaned_in_broker,
            "orphaned_in_journal": result.orphaned_in_journal,
            "reconciled": result.reconciled,
        }

        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        self._log.info(
            "reconciliation.report_saved",
            path=str(report_path),
            status=result.status,
        )
