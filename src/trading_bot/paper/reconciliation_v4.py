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

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.paper.broker import PaperBroker, PaperPosition
from trading_bot.paper.paper_runtime_state import extract_state
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
    materialized_orders: int = 0
    blocked_intents: list[str] = field(default_factory=list)
    recovery_persisted: bool = False

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
            "materialized_orders": self.materialized_orders,
            "blocked_intents": list(self.blocked_intents),
            "recovery_persisted": self.recovery_persisted,
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
        materialized = 0
        blocked: list[str] = []
        updated_orders = [dict(row) for row in state.orders]
        try:
            restored_equity = self._restore_broker(state, details)
            self._restore_risk(state, details)
            self._restore_intents(state, details)
            materialized, blocked, updated_orders = self._restore_orders(updated_orders, details)
            self._sync_risk_book(details)
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
                materialized_orders=materialized,
                blocked_intents=list(blocked),
            )

        # Make the recovered decision durable: an order materialized from a
        # FILLED row becomes ACCOUNTED, and a PREPARED intent with an unknown
        # broker outcome becomes BLOCKED_UNKNOWN.  A kill during this write
        # leaves the previous complete document (atomic replace), so the next
        # start re-runs the same deterministic recovery.
        recovery_persisted = False
        if updated_orders != [dict(row) for row in state.orders]:
            try:
                recovered = dataclasses.replace(
                    extract_state(
                        run_id=state.run_id,
                        broker=self._broker,
                        risk=self._risk,
                        idempotency=self._idempotency,
                        orders=updated_orders,
                    ),
                    updated_at_ms=state.updated_at_ms,
                )
                self._store.save(recovered)
                recovery_persisted = True
                details.append("recovery outcome persisted")
            except Exception as exc:
                self._log.error("reconcile.fatal_recovery_persist", error=str(exc))
                return ReconciliationReportV4(
                    status=ReconciliationStatusV4.FATAL,
                    restored_open_positions=len(self._broker.positions),
                    restored_closed_trades=len(self._broker.closed_trades),
                    restored_intents=len(state.sent_intents),
                    restored_equity=restored_equity,
                    restored_risk=dict(state.risk_state),
                    restored_run_id=state.run_id,
                    checked_at_ms=checked_at_ms,
                    details=[*details, f"recovery_persist_failed: {type(exc).__name__}: {exc}"],
                    materialized_orders=materialized,
                    blocked_intents=list(blocked),
                )

        # The durable broker adopts the reconciled order ledger, so a later
        # session snapshot cannot overwrite it with an empty list.
        setter = getattr(self._broker, "set_orders", None)
        if callable(setter):
            setter(updated_orders)

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
            materialized_orders=materialized,
            blocked_intents=list(blocked),
            recovery_persisted=recovery_persisted,
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

    def _restore_orders(
        self, orders: list[dict[str, Any]], details: list[str]
    ) -> tuple[int, list[str], list[dict[str, Any]]]:
        """Reconcile the durable order ledger against the restored book.

        PREPARED (or FAILED) means the broker may or may not have acted: the
        cloid is already in the intent ledger, so it stays blocked.  FILLED
        carries the exact position row but the accounting snapshot predates
        the fill: materialize it once.  ACCOUNTED must already be present in
        the restored book; a missing row is a fatal inconsistency.
        """
        materialized = 0
        blocked: list[str] = []
        updated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in orders:
            row = dict(raw)
            cloid = str(row.get("cloid", ""))
            status = str(row.get("status", ""))
            if not cloid:
                raise ValueError("durable order row has no cloid")
            if cloid in seen:
                raise ValueError(f"duplicate durable order row for cloid {cloid}")
            seen.add(cloid)

            if status in {"PREPARED", "FAILED"}:
                # Unknown outcome: never resend.  The idempotency ledger was
                # restored above and permanently suppresses this cloid.
                row["status"] = "BLOCKED_UNKNOWN"
                row["blocked_reason"] = "broker outcome unknown after forced termination"
                blocked.append(cloid)
                details.append(f"intent blocked (unknown outcome): {cloid}")
                updated.append(row)
                continue

            if status == "FILLED":
                position_row = row.get("position")
                if not isinstance(position_row, dict):
                    raise ValueError(f"FILLED order {cloid} has no position row")
                position = PaperPosition(**position_row)
                existing = self._broker.positions.get(position.symbol)
                if existing is not None:
                    if not self._same_position(existing, position):
                        raise ValueError(
                            f"order {cloid} conflicts with restored position "
                            f"{existing.symbol} (id {existing.position_id})"
                        )
                    details.append(
                        f"FILLED order {cloid} already present in the book; not duplicated"
                    )
                else:
                    self._broker.replace_position(position)
                    self._broker.register_external_fill()
                    materialized += 1
                    details.append(
                        f"FILLED order {cloid} materialized position {position.symbol} "
                        f"id={position.position_id}"
                    )
                row["status"] = "ACCOUNTED"
                updated.append(row)
                continue

            if status == "ACCOUNTED":
                position_row = row.get("position")
                if not isinstance(position_row, dict):
                    raise ValueError(f"ACCOUNTED order {cloid} has no position row")
                expected = PaperPosition(**position_row)
                actual = self._broker.positions.get(expected.symbol)
                if actual is None:
                    # A legitimate close removes the position while the entry
                    # order row remains in the ledger.  Accept it only when the
                    # restored closed-trade ledger names that exact position or
                    # entry order; otherwise the book is inconsistent.
                    closed = any(
                        (
                            trade.get("position_id")
                            and trade.get("position_id") == expected.position_id
                        )
                        or (
                            trade.get("entry_order_id")
                            and trade.get("entry_order_id") == expected.entry_order_id
                        )
                        for trade in self._broker.closed_trades_rows()
                    )
                    if not closed:
                        raise ValueError(
                            f"ACCOUNTED order {cloid} has no restored position "
                            f"or matching closed trade for {expected.symbol}"
                        )
                    row["status"] = "CLOSED"
                    details.append(f"ACCOUNTED order {cloid} already closed by a persisted trade")
                    updated.append(row)
                    continue
                if not self._same_position(actual, expected):
                    raise ValueError(
                        f"ACCOUNTED order {cloid} position mismatch for {expected.symbol}"
                    )
                updated.append(row)
                continue

            if status in {"NO_FILL", "CLOSED", "BLOCKED_UNKNOWN"}:
                updated.append(row)
                continue

            raise ValueError(f"order {cloid} has unknown durable status {status!r}")

        return materialized, blocked, updated

    @staticmethod
    def _same_position(left: PaperPosition, right: PaperPosition) -> bool:
        if left.position_id and right.position_id:
            return left.position_id == right.position_id
        return (
            left.symbol == right.symbol
            and left.side == right.side
            and abs(left.entry_price - right.entry_price) <= 1e-9
            and abs(left.quantity - right.quantity) <= 1e-12
            and abs(left.notional_usdt - right.notional_usdt) <= 1e-9
        )

    def _sync_risk_book(self, details: list[str]) -> None:
        """Expose materialized positions to Risk before the first decision."""
        if self._risk is None:
            return
        book = {
            symbol: {
                "notional_usdt": float(position.notional_usdt),
                "side": str(position.side),
                "entry_price": float(position.entry_price),
                "quantity": float(position.quantity),
            }
            for symbol, position in self._broker.positions.items()
        }
        try:
            self._risk.open_positions = book
        except (AttributeError, TypeError, ValueError):
            details.append("risk book sync skipped (risk engine has no mutable book)")
            return
        details.append(f"risk book synced: {len(book)} open position(s)")

    def _restore_intents(self, state: Any, details: list[str]) -> None:
        if self._idempotency is None:
            return
        for cloid in state.sent_intents:
            self._idempotency.register(cloid)
        details.append(f"intent ledger restored: {len(state.sent_intents)} cloids")
