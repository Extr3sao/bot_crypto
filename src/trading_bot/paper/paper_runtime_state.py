"""Glue between the durable state store and the canonical runtime objects.

GAP-R1 hardening: persistence must capture the REAL runtime objects
(TEST_TARGET == RUNTIME_TARGET). This module owns the per-session
snapshot: it extracts the live book (broker, risk, intent ledger) and
persists it atomically through :class:`PaperStateStore`.

Restore lives in ``reconciliation_v4.StartupReconcilerV4`` (the single
startup authority). All code here is deterministic: pure field copies.
"""

from __future__ import annotations

from typing import Any

from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_state_store import PaperStateStore, SessionPaperState
from trading_bot.risk.manager import RiskManager

__all__ = ["extract_state", "save_session_state"]


def extract_state(
    *,
    run_id: str,
    broker: PaperBroker,
    risk: RiskManager | None,
    idempotency: Any | None,
) -> SessionPaperState:
    """Build the durable state document from live runtime objects."""
    risk_state: dict[str, Any] = risk.extract_state() if risk is not None else {}
    sent_intents: list[str] = []
    if idempotency is not None:
        sent_intents = list(getattr(idempotency, "sent_cloids", []) or [])
    return SessionPaperState(
        schema_version=1,
        run_id=run_id,
        updated_at_ms=0,  # stamped by the store on save
        broker_state=broker.extract_state(),
        risk_state=risk_state,
        open_positions=[p.to_row() for p in broker.positions.values()],
        closed_trades=list(broker.closed_trades_rows()),
        sent_intents=sent_intents,
    )


def save_session_state(
    *,
    store: PaperStateStore,
    run_id: str,
    broker: PaperBroker,
    risk: RiskManager | None,
    idempotency: Any | None,
) -> None:
    """Persist the post-session book atomically (called once per session)."""
    store.save(extract_state(run_id=run_id, broker=broker, risk=risk, idempotency=idempotency))
