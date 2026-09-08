"""Execution gateway — runtime bridge between intents, journal and venues.

EXECUTION-RELIABILITY-RUNTIME-01 (checkpoint INTELLIGENCE-AND-EXECUTION-HARDENING-01,
Track A). Composes the 814f0e4 primitives into a single authority path:

    TradeIntent -> stable intent_id -> stable client_order_id
      -> ExecutionJournal (CREATED/SUBMITTING/...)
      -> venue port (submit/query/cancel/fills/open_orders)
      -> ACK_UNKNOWN recovery / fill idempotency / reconciliation

The gateway is adapter-agnostic: adapters implement ``VenuePort``. Wall clock
is metadata only — economic identity comes exclusively from canonical intent
fields. LIVE remains disabled: callers decide which port to inject (fake /
simulated / paper); the gateway performs no network I/O itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from trading_bot.execution.feed_guard import FeedDeadManGuard, FeedFreshness, FeedGuardVerdict
from trading_bot.execution.intent import (
    AckQueryResult,
    AmbiguousAckRecovery,
    ExecutionReliabilityError,
    FillApplication,
    FillLedger,
    IdempotentSubmitGate,
    TradeIntent,
    compute_intent_id,
    derive_client_order_id,
)
from trading_bot.execution.journal import ExecutionJournal, ExecutionState


class VenuePort(Protocol):
    """Venue boundary the gateway drives (fake/simulated/paper today)."""

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        """Submit an economic order; return the venue order id."""
        ...

    def query(self, client_order_id: str) -> AckQueryResult:
        """Query the venue for an order by stable client identity."""
        ...

    def venue_order_id_of(self, client_order_id: str) -> str | None:
        """Venue order id for a client order id, if the venue knows it."""
        ...


@dataclass(frozen=True, slots=True)
class GatewayReceipt:
    """Result of one gateway round (submit or recovery)."""

    intent_id: str
    client_order_id: str
    venue_order_id: str | None
    journal_state: ExecutionState
    submitted_now: bool
    detail: str


@dataclass
class ExecutionGateway:
    """Single authority path from an economic intent to a venue.

    Guarantees (enforced by composition of the certified primitives):

    - Same economic intent -> same intent_id -> same client_order_id,
      regardless of wall clock or retry count.
    - At most ONE economic submission per intent id while any ambiguity
      exists (ECONOMIC_ORDERS_PER_INTENT <= 1).
    - Every state transition is journaled append-only with reason + evidence.
    - Duplicate venue fills apply deltas exactly once.
    """

    journal: ExecutionJournal = field(default_factory=ExecutionJournal)
    fills: FillLedger = field(default_factory=FillLedger)
    submit_gate: IdempotentSubmitGate = field(default_factory=IdempotentSubmitGate)
    feed_guard: FeedDeadManGuard = field(default_factory=FeedDeadManGuard)
    _recoveries: dict[str, AmbiguousAckRecovery] = field(default_factory=dict)
    _venue_refs: dict[str, str] = field(default_factory=dict)

    # -- intent identity ----------------------------------------------------
    def intent_id(self, intent: TradeIntent) -> str:
        return compute_intent_id(intent)

    def client_order_id(self, intent: TradeIntent) -> str:
        return derive_client_order_id(self.intent_id(intent))

    # -- feed gating ----------------------------------------------------------
    def evaluate_feeds(self, freshness: tuple[FeedFreshness, ...]) -> FeedGuardVerdict:
        """Dead-man evaluation; BLOCK verdicts forbid new entries."""
        return self.feed_guard.evaluate(freshness)

    # -- submit path ----------------------------------------------------------
    def submit(
        self,
        intent: TradeIntent,
        venue: VenuePort,
        *,
        reason: str = "gateway submit",
        evidence: dict[str, Any] | None = None,
    ) -> GatewayReceipt:
        """Submit an intent at most once; journal every transition.

        Raises ``ExecutionReliabilityError`` if a stale-feed BLOCK verdict is
        active for this call (the caller must evaluate feeds first and pass
        ``allow_new_entries=True`` evidence) — expressed via ``evidence``
        contract: the caller includes ``feed_verdict`` in evidence; a
        ``block_new_entries`` verdict aborts before any venue call.
        """
        verdict = (evidence or {}).get("feed_verdict")
        if verdict is not None and not self.feed_guard.allow_new_entries(verdict):
            raise ExecutionReliabilityError(
                f"feed dead-man BLOCK active ({verdict.action.value}); new entries forbidden"
            )
        intent_id = self.intent_id(intent)
        cloid = self.client_order_id(intent)
        current = self.journal.current_state(intent_id)
        # Short-circuit: post-submit states are never re-submitted. A retry of
        # an accepted/filled/cancelling intent returns the known venue
        # reference without touching the venue (ECONOMIC_ORDERS_PER_INTENT <= 1).
        if current in (
            ExecutionState.ACCEPTED,
            ExecutionState.PARTIALLY_FILLED,
            ExecutionState.FILLED,
            ExecutionState.CANCEL_PENDING,
            ExecutionState.CANCELLED,
            ExecutionState.REJECTED,
        ):
            return GatewayReceipt(
                intent_id=intent_id,
                client_order_id=cloid,
                venue_order_id=self._venue_refs.get(intent_id),
                journal_state=current,
                submitted_now=False,
                detail=f"intent already {current.value}; submit suppressed",
            )
        if intent_id not in self.journal.intents():
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.CREATED,
                reason="intent registered",
                evidence={"symbol": intent.symbol, "side": intent.side},
            )
        self.journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.SUBMITTING,
            reason=reason,
            evidence=dict(evidence or {}),
        )

        def _venue_submit(intent: TradeIntent, client_order_id: str) -> str:
            return venue.submit(intent, client_order_id)

        try:
            venue_order_id = self.submit_gate.submit(intent, _venue_submit)
        except Exception:
            # Submit raised before/after ack: treat as ambiguity, never retry blindly.
            recovery = self._recovery_for(intent_id, cloid)
            recovery.on_submit_timeout()
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.ACK_UNKNOWN,
                reason="submit raised; ambiguity recorded",
                evidence={"error_class": type(Exception).__name__},
            )
            raise
        self.journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.ACCEPTED,
            reason="venue ack",
            venue_order_id=venue_order_id,
            evidence=dict(evidence or {}),
        )
        self._venue_refs[intent_id] = venue_order_id
        return GatewayReceipt(
            intent_id=intent_id,
            client_order_id=cloid,
            venue_order_id=venue_order_id,
            journal_state=ExecutionState.ACCEPTED,
            submitted_now=self.submit_gate.economic_order_count(intent_id) == 1,
            detail="submitted once under idempotent gate",
        )

    # -- ACK_UNKNOWN recovery -------------------------------------------------
    def _recovery_for(self, intent_id: str, cloid: str) -> AmbiguousAckRecovery:
        if intent_id not in self._recoveries:
            self._recoveries[intent_id] = AmbiguousAckRecovery(
                intent_id=intent_id, client_order_id=cloid
            )
        return self._recoveries[intent_id]

    def resolve_ack_unknown(
        self,
        intent: TradeIntent,
        venue: VenuePort,
        *,
        query_result: AckQueryResult | None = None,
    ) -> GatewayReceipt:
        """Resolve an ambiguous submit by querying the venue by stable identity.

        - FOUND -> ADOPT (journal ACCEPTED with venue order id; no resubmit).
        - ABSENT -> CONTROLLED_RETRY with the SAME identity (single retry submit).
        - UNCERTAIN -> BLOCK (journal RECONCILING; no economic order).
        """
        intent_id = self.intent_id(intent)
        cloid = self.client_order_id(intent)
        recovery = self._recovery_for(intent_id, cloid)
        if recovery.state == "SUBMITTING":
            recovery.on_submit_timeout()
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.ACK_UNKNOWN,
                reason="ack unknown entered",
            )
        outcome = query_result if query_result is not None else venue.query(cloid)
        verdict = recovery.resolve(outcome, venue_order_id=venue.venue_order_id_of(cloid))
        if verdict.decision.value == "adopt":
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.ACCEPTED,
                reason="adopted after venue query",
                venue_order_id=verdict.venue_order_id,
            )
            if verdict.venue_order_id is not None:
                self._venue_refs[intent_id] = verdict.venue_order_id
            return GatewayReceipt(
                intent_id=intent_id,
                client_order_id=cloid,
                venue_order_id=verdict.venue_order_id,
                journal_state=ExecutionState.ACCEPTED,
                submitted_now=False,
                detail="adopted existing venue order",
            )
        if verdict.decision.value == "controlled_retry":
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.RECONCILING,
                reason="controlled retry authorized with same identity",
            )

            def _retry_submit(retry_intent: TradeIntent, retry_cloid: str) -> str:
                return venue.submit(retry_intent, retry_cloid)

            # The idempotent gate governs the retry too: if the original
            # submit registered before the raise, this returns the cached
            # reference; otherwise it performs the ONE controlled submit.
            venue_order_id = self.submit_gate.submit(intent, _retry_submit)
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.ACCEPTED,
                reason="controlled retry accepted",
                venue_order_id=venue_order_id,
            )
            self._venue_refs[intent_id] = venue_order_id
            return GatewayReceipt(
                intent_id=intent_id,
                client_order_id=cloid,
                venue_order_id=venue_order_id,
                journal_state=ExecutionState.ACCEPTED,
                submitted_now=True,
                detail="controlled retry with same client_order_id",
            )
        self.journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.RECONCILING,
            reason="venue query inconclusive; blocked",
        )
        return GatewayReceipt(
            intent_id=intent_id,
            client_order_id=cloid,
            venue_order_id=None,
            journal_state=ExecutionState.RECONCILING,
            submitted_now=False,
            detail="blocked: venue query inconclusive",
        )

    # -- fills ---------------------------------------------------------------
    def apply_fill(
        self,
        intent: TradeIntent,
        *,
        venue_fill_id: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        timestamp: float | None = None,
    ) -> FillApplication:
        """Apply a venue fill exactly once (duplicates are no-ops)."""
        intent_id = self.intent_id(intent)
        cloid = self.client_order_id(intent)
        application = self.fills.apply_fill(
            venue_fill_id=venue_fill_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            price=price,
            fee=fee,
            intent_id=intent_id,
        )
        if application.applied:
            current = self.journal.current_state(intent_id)
            # A fill is a live event while the order is ACCEPTED / already
            # PARTIALLY_FILLED / CANCEL_PENDING (fill racing the cancel).
            if current in (
                ExecutionState.ACCEPTED,
                ExecutionState.PARTIALLY_FILLED,
                ExecutionState.CANCEL_PENDING,
            ):
                self.journal.record(
                    intent_id=intent_id,
                    client_order_id=cloid,
                    new_state=ExecutionState.PARTIALLY_FILLED,
                    reason="partial fill applied",
                    timestamp=timestamp,
                    evidence={"venue_fill_id": venue_fill_id},
                )
        return application

    # -- cancel ---------------------------------------------------------------
    def request_cancel(self, intent: TradeIntent, venue: VenuePort) -> GatewayReceipt:
        """Move to CANCEL_PENDING; CANCELLED only on venue confirmation."""
        intent_id = self.intent_id(intent)
        cloid = self.client_order_id(intent)
        self.journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.CANCEL_PENDING,
            reason="cancel requested",
        )
        return GatewayReceipt(
            intent_id=intent_id,
            client_order_id=cloid,
            venue_order_id=None,
            journal_state=ExecutionState.CANCEL_PENDING,
            submitted_now=False,
            detail="cancel pending venue confirmation",
        )

    def confirm_cancel(self, intent: TradeIntent) -> GatewayReceipt:
        """Record venue-confirmed cancellation (CANCELLED is terminal)."""
        intent_id = self.intent_id(intent)
        cloid = self.client_order_id(intent)
        self.journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.CANCELLED,
            reason="venue confirmed cancel",
        )
        return GatewayReceipt(
            intent_id=intent_id,
            client_order_id=cloid,
            venue_order_id=None,
            journal_state=ExecutionState.CANCELLED,
            submitted_now=False,
            detail="cancelled",
        )

    # -- reconciliation ---------------------------------------------------------
    def reconcile(
        self,
        intent: TradeIntent,
        *,
        venue_holds_order: bool,
        venue_order_id: str | None = None,
    ) -> GatewayReceipt:
        """Orphan/startup reconciliation for one intent.

        venue_holds_order=True -> adopt back to ACCEPTED (no replacement submit).
        venue_holds_order=False -> CANCELLED after authoritative reconciliation.
        """
        intent_id = self.intent_id(intent)
        cloid = self.client_order_id(intent)
        self.journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.RECONCILING,
            reason="reconciliation started",
        )
        if venue_holds_order:
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.ACCEPTED,
                reason="venue holds order; adopted",
                venue_order_id=venue_order_id,
            )
            detail = "adopted venue order"
        else:
            self.journal.record(
                intent_id=intent_id,
                client_order_id=cloid,
                new_state=ExecutionState.CANCELLED,
                reason="venue definitively lacks order; reconciled closed",
            )
            detail = "reconciled closed"
        return GatewayReceipt(
            intent_id=intent_id,
            client_order_id=cloid,
            venue_order_id=venue_order_id,
            journal_state=self.journal.current_state(intent_id) or ExecutionState.RECONCILING,
            submitted_now=False,
            detail=detail,
        )

    # -- startup readiness ------------------------------------------------------
    def execution_ready(
        self,
        *,
        instrument_metadata_loaded: bool,
        account_loaded: bool,
        positions_loaded: bool,
        open_orders_loaded: bool,
        recent_fills_loaded: bool,
    ) -> tuple[bool, tuple[str, ...]]:
        """Fail-closed EXECUTION_READY gate for a future live runtime.

        Returns (ready, missing). Ready only when every prerequisite
        reconciliation input has been loaded; otherwise lists what is missing.
        This does NOT enable live trading by itself.
        """
        checks = {
            "instrument_metadata": instrument_metadata_loaded,
            "account": account_loaded,
            "positions": positions_loaded,
            "open_orders": open_orders_loaded,
            "recent_fills": recent_fills_loaded,
        }
        missing = tuple(name for name, ok in checks.items() if not ok)
        return (not missing, missing)
