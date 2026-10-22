"""Startup reconciliation V4 (GAP-R1) — restore the paper book from durable state.

Contract (docs/STARTUP_RECONCILIATION_CONTRACT.md):

    What did we intend?          -> sent_intents ledger (cloids)
    What did we send?            -> sent_intents (persisted at broker call)
    What was accepted?           -> open_positions + closed_trades (post-fill)
    What was filled?             -> open_positions / closed_trades rows
    What position should exist?  -> recomputed from persisted rows
    What position is recorded?   -> in-memory broker after restore
    What balance should exist?   -> initial_equity + sum(closed pnl)
    What balance is recorded?    -> broker.equity
    What remains unresolved?     -> statuses other than CONSISTENT/RECOVERED

Explicit statuses — inconsistency is NEVER converted into a normal state:

    CONSISTENT           empty store: fresh book (or nothing to reconcile)
    RECOVERED            durable state restored into the runtime objects
    DUPLICATE_SUPPRESSED execution-time outcome (kept for contract naming)
    MISMATCH             equity identity violated by the persisted data
                         itself (initial + sum(pnl) != equity) — fatal today
    FATAL                unreadable/corrupt state file (fail closed)

PARTIAL_RECOVERY is not RECOVERED: if any restore step fails, the outcome is
``FATAL`` — the runtime must not continue on a half-restored book.

This module is deterministic: no LLM, no network, no sizing decisions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.paper.broker import PaperBroker, PaperPosition
from trading_bot.paper.paper_state_store import CorruptStateFile, PaperStateStore
from trading_bot.risk.manager import RiskManager

__all__ = [
    "ReconciliationReportV4",
    "ReconciliationStatusV4",
    "StartupReconcilerV4",
]


class ReconciliationStatusV4:  # namespace of JSON-safe strings
    CONSISTENT = "CONSISTENT"
    RECOVERED = "RECOVERED"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    MISMATCH = "MISMATCH"
    FATAL = "FATAL"


@dataclass(frozen=True, slots=True)
class ReconciliationReportV4:
    """Observable, JSON-serialisable reconciliation outcome."""

    status: str
    restored_open_positions: int
    restored_closed_trades: int
    restored_intents: int
    restored_equity: float | None
    restored_risk: dict[str, Any]
    restored_run_id: str
    checked_at_ms: int
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "restored_open_positions": self.restored_open_positions,
            "restored_closed_trades": self.restored_closed_trades,
            "restored_intents": self.restored_intents,
            "restored_equity": self.restored_equity,
            "restored_risk": dict(self.restored_risk),
            "restored_run_id": self.restored_run_id,
            "checked_at_ms": self.checked_at_ms,
            "details": list(self.details),
        }


def _eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


class StartupReconcilerV4:
    """Restores broker + risk + intent ledger from :class:`PaperStateStore`.

    Policy: RESTORE_EXACTLY (deterministic replay of the persisted book).
    Risk receives the restored state BEFORE evaluating any new signal, so
    daily-loss / drawdown / cooldown limits see pre-restart exposure.
    """

    def __init__(
        self,
        *,
        store: PaperStateStore,
        broker: PaperBroker,
        risk_manager: RiskManager | None = None,
        idempotency: Any | None = None,
    ) -> None:
        self._store = store
        self._broker = broker
        self._risk = risk_manager
        self._idempotency = idempotency
        self._log = structlog.get_logger("startup_reconciler_v4")

    def reconcile(self) -> ReconciliationReportV4:
        checked_at_ms = int(time.time() * 1000)

        try:
            state = self._store.load_or_recover()
        except CorruptStateFile as exc:
            self._log.error("reconcile.fatal", error=str(exc))
            return ReconciliationReportV4(
                status=ReconciliationStatusV4.FATAL,
                restored_open_positions=0,
                restored_closed_trades=0,
                restored_intents=0,
                restored_equity=None,
                restored_risk={},
                restored_run_id="",
                checked_at_ms=checked_at_ms,
                details=[str(exc)],
            )

        if not (
            state.broker_state
            or state.risk_state
            or state.open_positions
            or state.closed_trades
            or state.sent_intents
        ):
            self._log.info("reconcile.consistent_fresh_book")
            return ReconciliationReportV4(
                status=ReconciliationStatusV4.CONSISTENT,
                restored_open_positions=0,
                restored_closed_trades=0,
                restored_intents=0,
                restored_equity=None,
                restored_risk={},
                restored_run_id=state.run_id,
                checked_at_ms=checked_at_ms,
                details=["no persisted state: starting with a fresh book"],
            )

        details: list[str] = []
        try:
            restored_equity = self._restore_broker(state, details)
            self._restore_risk(state, details)
            self._restore_intents(state, details)
        except Exception as exc:  # half-restored book must never continue
            self._log.error("reconcile.fatal_restore", error=str(exc))
            return ReconciliationReportV4(
                status=ReconciliationStatusV4.FATAL,
                restored_open_positions=0,
                restored_closed_trades=0,
                restored_intents=0,
                restored_equity=None,
                restored_risk={},
                restored_run_id=state.run_id,
                checked_at_ms=checked_at_ms,
                details=[*details, f"restore_failed: {type(exc).__name__}: {exc}"],
            )

        status = ReconciliationStatusV4.RECOVERED
        self._log.info(
            "reconcile.recovered",
            open_positions=len(state.open_positions),
            closed_trades=len(state.closed_trades),
            intents=len(state.sent_intents),
            equity=restored_equity,
        )
        return ReconciliationReportV4(
            status=status,
            restored_open_positions=len(state.open_positions),
            restored_closed_trades=len(state.closed_trades),
            restored_intents=len(state.sent_intents),
            restored_equity=restored_equity,
            restored_risk=dict(state.risk_state),
            restored_run_id=state.run_id,
            checked_at_ms=checked_at_ms,
            details=details,
        )

    # -- restore steps (deterministic) --------------------------------------

    def _restore_broker(self, state: Any, details: list[str]) -> float:
        broker_state = dict(state.broker_state)
        equity = float(broker_state.get("equity", 0.0))
        initial_equity = float(broker_state.get("initial_equity", 0.0))
        if equity <= 0 or initial_equity <= 0:
            raise ValueError(
                f"persisted broker_state has non-positive equity ({equity}) "
                f"or initial_equity ({initial_equity})"
            )

        closed_rows = [dict(row) for row in state.closed_trades]
        pnl_sum = sum(float(row.get("pnl", 0.0)) for row in closed_rows)
        expected_equity = initial_equity + pnl_sum
        if not _eq(expected_equity, equity):
            raise ValueError(
                f"equity identity violated by persisted state: "
                f"initial {initial_equity} + sum(closed pnl) {pnl_sum} != equity {equity}"
            )

        self._broker.restore(
            equity=equity,
            initial_equity=initial_equity,
            fills_opened=int(broker_state.get("fills_opened", 0)),
            fills_closed=int(broker_state.get("fills_closed", 0)),
            open_positions=[PaperPosition(**dict(row)) for row in state.open_positions],
            closed_trades=closed_rows,
        )
        details.append(
            f"broker restored: equity={equity:.2f} "
            f"open={len(state.open_positions)} closed={len(state.closed_trades)}"
        )
        return equity

    def _restore_risk(self, state: Any, details: list[str]) -> None:
        if self._risk is None:
            return
        risk_state = dict(state.risk_state)
        if not risk_state:
            return
        # DEF-VERIFY-011: old snapshots serialised an empty ``open_positions``
        # in the risk block. The authoritative book is the broker's, persisted
        # at the top level of the same document, so fall back to it whenever the
        # risk block carries nothing — the exposure clamps must never restore
        # blind.
        book = dict(risk_state.get("open_positions", {}) or {})
        if not book:
            book = {
                str(row.get("symbol")): dict(row)
                for row in state.open_positions
                if row.get("symbol")
            }
        # WP-EDGE-017F/P0.1: the weekly window anchor travels with the counters.
        # A snapshot written before the anchor existed has no key here, and the
        # manager then anchors it on restore instead of forgiving the loss.
        stored_week = risk_state.get("weekly_start_ms")
        self._risk.restore_state(
            daily_pnl=float(risk_state.get("daily_pnl", 0.0)),
            weekly_pnl=float(risk_state.get("weekly_pnl", 0.0)),
            trades_today=int(risk_state.get("trades_today", 0)),
            consecutive_losses=int(risk_state.get("consecutive_losses", 0)),
            peak_equity=float(risk_state.get("peak_equity", 0.0)),
            open_positions=book,
            kill_switch_active=bool(risk_state.get("kill_switch_active", False)),
            weekly_start_ms=int(stored_week) if stored_week is not None else None,
        )
        # Equity must reflect the restored book BEFORE any new risk check.
        self._risk.equity = float(self._broker.equity)
        self._risk.peak_equity = max(self._risk.peak_equity, self._risk.equity)
        details.append("risk state restored before first decision")

    def _restore_intents(self, state: Any, details: list[str]) -> None:
        if self._idempotency is None:
            return
        for cloid in state.sent_intents:
            self._idempotency.register(cloid)
        details.append(f"intent ledger restored: {len(state.sent_intents)} cloids")
