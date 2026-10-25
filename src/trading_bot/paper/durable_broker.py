"""Durable paper broker: persist the intent/order/fill boundary (G-6).

``PaperBroker`` mutates only memory.  G-5 persisted once per session, so a
forced process death inside a cycle could lose an accepted fill, or lose the
intent that made the fill happen.  This subclass adds the smallest durable
boundary that closes those windows while keeping the broker's accounting
rules unchanged:

    BEFORE_INTENT_PERSIST          no state written (nothing happened)
    AFTER_INTENT_PERSIST           intent + PREPARED order on disk
    AFTER_ORDER_RECORD             FILLED order + position row on disk,
                                   broker accounting still PRE-fill
    AFTER_ACCOUNTING_COMMIT        ACCOUNTED order + post-fill accounting

The last two are deliberately separate.  The FILLED snapshot is enough for
``StartupReconcilerV4`` to materialize the position deterministically, while
the ACCOUNTED snapshot is the ordinary recovered book.  A PREPARED order
without a fill has an unknown outcome: recovery blocks its cloid forever and
never resends it.

All writes go through ``PaperStateStore`` (tmp file + fsync + replace), so a
kill between writes leaves exactly one of the boundaries above.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trading_bot.paper.broker import BrokerOrderError, ClosedTrade, PaperBroker, PaperPosition
from trading_bot.paper.crash_injection import crash_point
from trading_bot.paper.paper_runtime_state import extract_state
from trading_bot.paper.paper_state_store import PaperStateStore
from trading_bot.strategies.types import Signal

__all__ = ["DurablePaperBroker"]

_STATUS_PREPARED = "PREPARED"
_STATUS_FILLED = "FILLED"
_STATUS_ACCOUNTED = "ACCOUNTED"
_STATUS_NO_FILL = "NO_FILL"
_STATUS_FAILED = "FAILED"
_STATUS_CLOSED = "CLOSED"


def _now_ms() -> int:
    return int(time.time() * 1000)


class DurablePaperBroker(PaperBroker):
    """A ``PaperBroker`` that persists each execution boundary atomically."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._store: PaperStateStore | None = None
        self._risk: Any | None = None
        self._idempotency: Any | None = None
        self._run_id: str = ""
        self._orders: list[dict[str, Any]] = []
        self._crash: Callable[..., None] = crash_point

    # -- wiring -------------------------------------------------------------

    def attach_durability(
        self,
        *,
        store: PaperStateStore,
        risk: Any | None,
        idempotency: Any | None,
        run_id: str,
        crash: Callable[..., None] | None = None,
    ) -> None:
        self._store = store
        self._risk = risk
        self._idempotency = idempotency
        self._run_id = run_id
        if crash is not None:
            self._crash = crash

    @property
    def durable(self) -> bool:
        return self._store is not None

    def set_orders(self, orders: list[dict[str, Any]]) -> None:
        """Adopt the order ledger restored by startup reconciliation."""
        self._orders = [dict(row) for row in orders]

    def orders_snapshot(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._orders]

    # -- execution boundary -------------------------------------------------

    def execute_signal(self, signal: Signal) -> ClosedTrade | PaperPosition | None:
        if self._store is None:
            return super().execute_signal(signal)

        cloid = str(signal.metadata.get("cloid", "") or "")
        if not cloid:
            raise BrokerOrderError(
                f"durable paper execution for {signal.symbol} requires metadata['cloid']"
            )
        if any(str(row.get("cloid")) == cloid for row in self._orders):
            raise BrokerOrderError(f"durable paper intent already recorded: {cloid}")

        prepared = {
            "cloid": cloid,
            "symbol": signal.symbol,
            "side": signal.side,
            "strategy_id": signal.strategy_name or "",
            "timeframe": signal.timeframe,
            "status": _STATUS_PREPARED,
            "created_at_ms": _now_ms(),
            "position": None,
        }
        prior_orders = [dict(row) for row in self._orders]
        sent = set(getattr(self._idempotency, "sent_cloids", set()) or set())
        sent.add(cloid)

        # Boundary 0: kill BEFORE the intent reaches disk.  Nothing durable
        # exists; the intent had no economic effect.
        self._crash(
            "before_intent_persist",
            cloid=cloid,
            symbol=signal.symbol,
            state_path=str(self._store.path),
        )
        pre_state = extract_state(
            run_id=self._run_id,
            broker=self,
            risk=self._risk,
            idempotency=self._idempotency,
            orders=[*prior_orders, prepared],
            sent_intents=sorted(sent),
        )
        self._store.save(pre_state)

        # Boundary 1: the intent is durable, the broker has not been called.
        self._crash(
            "after_intent_persist_before_order",
            cloid=cloid,
            symbol=signal.symbol,
            state_path=str(self._store.path),
        )

        try:
            result = super().execute_signal(signal)
        except Exception as exc:
            failed = dict(prepared)
            failed["status"] = _STATUS_FAILED
            failed["error"] = f"{type(exc).__name__}: {exc}"
            # Conservative: leave the cloid in the intent ledger.  A broker
            # exception may happen after a partial side effect; an uncertain
            # execution is never resent.
            self._store.save(
                extract_state(
                    run_id=self._run_id,
                    broker=self,
                    risk=self._risk,
                    idempotency=self._idempotency,
                    orders=[*prior_orders, failed],
                    sent_intents=sorted(sent),
                )
            )
            self._orders = [*prior_orders, failed]
            raise

        if result is None:
            # Confirmed no fill (same-side skip / duplicate): the intent had no
            # economic effect and may be retried by a future cycle.
            no_fill = dict(prepared)
            no_fill["status"] = _STATUS_NO_FILL
            self._store.save(
                extract_state(
                    run_id=self._run_id,
                    broker=self,
                    risk=self._risk,
                    idempotency=self._idempotency,
                    orders=[*prior_orders, no_fill],
                    sent_intents=sorted(
                        set(getattr(self._idempotency, "sent_cloids", set()) or set())
                    ),
                )
            )
            self._orders = [*prior_orders, no_fill]
            return None

        if isinstance(result, ClosedTrade):
            closed = dict(prepared)
            closed["status"] = _STATUS_CLOSED
            trade_rows = self.closed_trades_rows()
            closed["trade"] = trade_rows[-1] if trade_rows else None
            # Reversal close: the broker accounting already contains the close.
            # There is no separate FILLED boundary for a close in this scope;
            # the closed trade and the intent are persisted together.
            self._store.save(
                extract_state(
                    run_id=self._run_id,
                    broker=self,
                    risk=self._risk,
                    idempotency=self._idempotency,
                    orders=[*prior_orders, closed],
                    sent_intents=sorted(sent),
                )
            )
            self._orders = [*prior_orders, closed]
            self._crash(
                "after_accounting_commit_before_cycle",
                cloid=cloid,
                symbol=signal.symbol,
                state_path=str(self._store.path),
                result="closed_trade",
            )
            return result

        # Normal entry: the fill exists in memory.  First persist the order row
        # against the PRE-fill accounting snapshot.
        filled = dict(prepared)
        filled["status"] = _STATUS_FILLED
        filled["position"] = result.to_row()
        filled["filled_at_ms"] = _now_ms()
        self._store.save(dataclasses.replace(pre_state, orders=[*prior_orders, filled]))
        self._orders = [*prior_orders, filled]

        # Boundary 2: order/fill committed, accounting snapshot still pre-fill.
        self._crash(
            "after_order_record_before_accounting",
            cloid=cloid,
            symbol=signal.symbol,
            state_path=str(self._store.path),
        )

        accounted = dict(filled)
        accounted["status"] = _STATUS_ACCOUNTED
        accounted["accounted_at_ms"] = _now_ms()
        self._store.save(
            extract_state(
                run_id=self._run_id,
                broker=self,
                risk=self._risk,
                idempotency=self._idempotency,
                orders=[*prior_orders, accounted],
                sent_intents=sorted(sent),
            )
        )
        self._orders = [*prior_orders, accounted]

        # Boundary 3: durable economic commit, cycle confirmation still pending.
        self._crash(
            "after_accounting_commit_before_cycle",
            cloid=cloid,
            symbol=signal.symbol,
            state_path=str(self._store.path),
            position_id=result.position_id,
        )
        return result


def state_path_of(broker: DurablePaperBroker) -> Path | None:
    """Test/evidence helper: the durable path currently attached."""
    return None if broker._store is None else broker._store.path
