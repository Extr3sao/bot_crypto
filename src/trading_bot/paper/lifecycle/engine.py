"""The lifecycle engine: intents in, authenticated events and ledger rows out.

This is the one place that turns a decision into lifecycle events. In code it enforces:

* nothing is submitted without a risk-passed intent and a policy verification id
  (:class:`~trading_bot.paper.lifecycle.contracts.RiskGateViolation`);
* event identifiers are deterministic, so re-delivering the same venue message is a
  duplicate the store recognises instead of a second fact;
* a fill only books against the ledger after the store accepted the event that carries
  it, so a refused event can never move money;
* an ``UNKNOWN`` order cannot be submitted again until a primary source has resolved it.

The engine holds no policy of its own. It is the wiring between the frozen contracts and
the durable store, and every branch it can take is one of those two modules' rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    ExecutionEnvelope,
    FillFact,
    OrderIntent,
    RiskGateViolation,
    utc_ms,
)
from .store import DurableEventStore, FillLedger
from .venue import VenueMessage, VenueScript


@dataclass(frozen=True, slots=True)
class RunContext:
    """Identity of one rehearsal: what was run, from which commit, under which config."""

    run_id: str
    commit_sha: str
    config_digest: str
    adapter_id: str
    provenance: str
    provider_environment: str
    clock_source: str


@dataclass
class _OrderState:
    ordered_qty: float
    filled_qty: float = 0.0
    risk_approved: bool = False
    submitted: bool = False
    resolve_pending: bool = False
    #: A resolved order is closed for its intent. A new attempt would be a new order
    #: identity and therefore a new decision, not a retry of this one.
    closed: bool = False
    venue_order_id: str | None = None
    counters: dict[str, int] = field(default_factory=dict)


class LifecycleEngine:
    """Drives the order lifecycle and writes every step into the store and the ledger."""

    def __init__(
        self,
        *,
        context: RunContext,
        store: DurableEventStore | None = None,
        ledger: FillLedger | None = None,
    ) -> None:
        self.context = context
        self.store = store or DurableEventStore()
        self.ledger = ledger or FillLedger()
        self._orders: dict[str, _OrderState] = {}
        self._intents: dict[str, OrderIntent] = {}
        #: Messages the store refused because it had already authenticated them.
        self.duplicate_deliveries = 0

    # -- introspection --------------------------------------------------------

    @property
    def envelopes(self) -> tuple[ExecutionEnvelope, ...]:
        return self.store.envelopes

    def trace_rows(self) -> list[dict[str, Any]]:
        return self.store.rows()

    def state_of(self, client_order_id: str) -> _OrderState:
        return self._orders[client_order_id]

    # -- event construction ---------------------------------------------------

    def _next_event_id(self, client_order_id: str, kind: str) -> str:
        state = self._orders.get(client_order_id)
        counters = state.counters if state is not None else self._counters(client_order_id)
        counters[kind] = counters.get(kind, 0) + 1
        return f"{client_order_id}:{kind}:{counters[kind]}"

    def _counters(self, client_order_id: str) -> dict[str, int]:
        return self._orders.setdefault(
            client_order_id, _OrderState(ordered_qty=0.0)
        ).counters

    def _emit(
        self,
        *,
        client_order_id: str,
        asset: str,
        strategy_id: str,
        event_type: str,
        event_time_ms: int,
        payload: dict[str, Any],
        intent: OrderIntent | None = None,
        venue_order_id: str | None = None,
        received_ms: int | None = None,
        event_id: str | None = None,
        correlation_parent_id: str | None = None,
    ) -> ExecutionEnvelope:
        state = self._orders.get(client_order_id)
        envelope = ExecutionEnvelope(
            run_id=self.context.run_id,
            commit_sha=self.context.commit_sha,
            config_digest=self.context.config_digest,
            decision_id=(intent.decision_id if intent else None),
            proposal_id=(intent.proposal_id if intent else None),
            signal_id=(intent.signal_id if intent else None),
            client_order_id=client_order_id,
            venue_order_id=venue_order_id or (state.venue_order_id if state else None),
            event_id=event_id or self._next_event_id(client_order_id, event_type),
            asset=asset,
            strategy_id=strategy_id,
            adapter_id=self.context.adapter_id,
            event_type=event_type,
            event_time_utc=utc_ms(event_time_ms),
            received_time_utc=utc_ms(event_time_ms if received_ms is None else received_ms),
            clock_source=self.context.clock_source,
            provenance=self.context.provenance,
            provider_environment=self.context.provider_environment,
            correlation_parent_id=correlation_parent_id or client_order_id,
            payload=payload,
        )
        self.store.append(envelope)
        return envelope

    # -- lifecycle steps ------------------------------------------------------

    def create(
        self,
        intent: OrderIntent,
        *,
        now_ms: int,
        risk_approved: bool,
        rejection_reason: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[ExecutionEnvelope]:
        """Register the intent. A rejected intent ends here, with no submit event."""

        self._intents[intent.client_order_id] = intent
        state = self._orders.setdefault(
            intent.client_order_id, _OrderState(ordered_qty=float(intent.quantity))
        )
        state.ordered_qty = float(intent.quantity)
        state.risk_approved = bool(risk_approved)
        payload = {
            "quantity": float(intent.quantity),
            "side": intent.side,
            "order_type": intent.order_type,
            "notional_usdt": float(intent.notional_usdt),
            "idempotency_key": intent.idempotency_key,
            "risk_evaluation_id": intent.risk_evaluation_id,
            "policy_verification_id": intent.policy_verification_id,
            "decision_time_utc": intent.decision_time_utc,
            "data_cutoff_utc": intent.data_cutoff_utc,
            "stop_loss_pct": intent.stop_loss_pct,
            **(meta or {}),
        }
        created = self._emit(
            client_order_id=intent.client_order_id,
            asset=intent.asset,
            strategy_id=intent.strategy_id,
            event_type="ORDER_CREATED",
            event_time_ms=now_ms,
            payload=payload,
            intent=intent,
        )
        events = [created]
        if not risk_approved:
            events.append(
                self._emit(
                    client_order_id=intent.client_order_id,
                    asset=intent.asset,
                    strategy_id=intent.strategy_id,
                    event_type="ORDER_RISK_REJECTED",
                    event_time_ms=now_ms,
                    payload={
                        "reason": rejection_reason or "RISK_NOT_APPROVED",
                        "stage": "risk",
                    },
                    intent=intent,
                )
            )
        return events

    def submit(
        self, client_order_id: str, *, now_ms: int, policy_verification_id: str | None = None
    ) -> ExecutionEnvelope:
        """Move the order to ``SUBMITTING``. Refused unless risk approved it."""

        state = self._orders.get(client_order_id)
        if state is None:
            raise RiskGateViolation(f"unknown order {client_order_id!r}: nothing to submit")
        if not state.risk_approved:
            raise RiskGateViolation(
                f"{client_order_id} was not approved by risk; a submit would be an "
                "unauthorised transmission"
            )
        if state.resolve_pending:
            raise RiskGateViolation(
                f"{client_order_id} is UNKNOWN: it must be reconciled before anything "
                "else is sent for it"
            )
        if state.closed:
            raise RiskGateViolation(
                f"{client_order_id} is closed: a primary source already resolved it, and "
                "re-sending it would transmit a second order for one intent"
            )
        if state.submitted:
            raise RiskGateViolation(
                f"{client_order_id} has already been sent; the same intent cannot be "
                "transmitted twice"
            )
        intent = self._intents.get(client_order_id)
        policy = policy_verification_id or (intent.policy_verification_id if intent else "")
        if intent is not None and not policy:
            raise RiskGateViolation(
                f"{client_order_id} carries no policy verification id; the send is refused"
            )
        state.submitted = True
        return self._emit(
            client_order_id=client_order_id,
            asset=intent.asset if intent else "",
            strategy_id=intent.strategy_id if intent else "",
            event_type="ORDER_SUBMITTED",
            event_time_ms=now_ms,
            payload={
                "risk_evaluation_id": intent.risk_evaluation_id if intent else "",
                "policy_verification_id": policy,
            },
            intent=intent,
        )

    def ingest(
        self,
        message: VenueMessage,
        *,
        client_order_id: str,
        received_ms: int | None = None,
    ) -> ExecutionEnvelope | None:
        """Record one venue message. ``None`` means the store saw it as a duplicate."""

        state = self._orders[client_order_id]
        intent = self._intents.get(client_order_id)
        if message.venue_order_id:
            state.venue_order_id = message.venue_order_id
        asset = intent.asset if intent else ""
        strategy_id = intent.strategy_id if intent else ""

        if message.kind == "ACK":
            return self._record(
                client_order_id=client_order_id,
                asset=asset,
                strategy_id=strategy_id,
                event_type="ORDER_ACKNOWLEDGED",
                message=message,
                received_ms=received_ms,
                payload={"venue_order_id": message.venue_order_id},
                intent=intent,
            )
        if message.kind == "REJECT":
            return self._record(
                client_order_id=client_order_id,
                asset=asset,
                strategy_id=strategy_id,
                event_type="ORDER_REJECTED",
                message=message,
                received_ms=received_ms,
                payload={"reason": message.reason or "VENUE_REJECTED"},
                intent=intent,
            )
        if message.kind == "CANCELED":
            return self._record(
                client_order_id=client_order_id,
                asset=asset,
                strategy_id=strategy_id,
                event_type="ORDER_CANCELED",
                message=message,
                received_ms=received_ms,
                payload={"reason": message.reason or "CANCELED"},
                intent=intent,
            )
        if message.kind == "EXPIRED":
            return self._record(
                client_order_id=client_order_id,
                asset=asset,
                strategy_id=strategy_id,
                event_type="ORDER_EXPIRED",
                message=message,
                received_ms=received_ms,
                payload={"reason": message.reason or "EXPIRED"},
                intent=intent,
            )
        if message.kind == "UNKNOWN":
            event = self._record(
                client_order_id=client_order_id,
                asset=asset,
                strategy_id=strategy_id,
                event_type="ORDER_UNKNOWN",
                message=message,
                received_ms=received_ms,
                payload={"reason": message.reason or "NO_CONFIRMATION"},
                intent=intent,
            )
            if event is not None:
                state.resolve_pending = True
            return event
        if message.kind == "FILL":
            return self._record_fill(
                message, client_order_id=client_order_id, received_ms=received_ms
            )
        raise ValueError(f"unknown venue message kind {message.kind!r}")

    def _record(
        self,
        *,
        client_order_id: str,
        asset: str,
        strategy_id: str,
        event_type: str,
        message: VenueMessage,
        received_ms: int | None,
        payload: dict[str, Any],
        intent: OrderIntent | None,
    ) -> ExecutionEnvelope | None:
        before = len(self.store.events)
        envelope = self._emit(
            client_order_id=client_order_id,
            asset=asset,
            strategy_id=strategy_id,
            event_type=event_type,
            event_time_ms=message.event_time_ms,
            received_ms=received_ms,
            payload=payload,
            intent=intent,
            venue_order_id=message.venue_order_id,
            event_id=message.event_id,
        )
        return envelope if len(self.store.events) != before else None

    def _record_fill(
        self,
        message: VenueMessage,
        *,
        client_order_id: str,
        received_ms: int | None,
    ) -> ExecutionEnvelope | None:
        if message.fill is None:
            raise ValueError("a FILL message without a fill payload cannot be recorded")
        state = self._orders[client_order_id]
        intent = self._intents.get(client_order_id)
        quantity = float(message.fill["filled_quantity"])
        price = float(message.fill["fill_price"])
        cumulative = state.filled_qty + quantity
        ordered = state.ordered_qty
        complete = bool(message.fill.get("complete")) or (
            ordered > 0 and cumulative >= ordered - 1e-12
        )
        event_type = "ORDER_FILLED" if complete else "ORDER_PARTIALLY_FILLED"
        payload = {
            "fill": {
                "fill_key": message.fill["fill_key"],
                "filled_quantity": quantity,
                "fill_price": price,
                "fee_amount": float(message.fill.get("fee_amount", 0.0)),
                "fee_currency": str(message.fill.get("fee_currency", "")),
                "fee_conversion_rate": message.fill.get("fee_conversion_rate"),
                "side": (intent.side if intent else "buy"),
                "decision_time_utc": intent.decision_time_utc if intent else None,
                "data_cutoff_utc": intent.data_cutoff_utc if intent else None,
            },
            "venue_order_id": message.venue_order_id,
        }
        before = len(self.store.events)
        envelope = self._emit(
            client_order_id=client_order_id,
            asset=intent.asset if intent else "",
            strategy_id=intent.strategy_id if intent else "",
            event_type=event_type,
            event_time_ms=message.event_time_ms,
            received_ms=received_ms,
            payload=payload,
            intent=intent,
            venue_order_id=message.venue_order_id,
            event_id=message.event_id,
        )
        if len(self.store.events) == before:
            # The store already holds this fact, so the ledger must not see it at all: the
            # re-delivery is counted where it belongs (the transport), not in accounting.
            self.duplicate_deliveries += 1
            return None
        state.filled_qty = cumulative
        self.ledger.apply(
            FillFact(
                fill_key=str(message.fill["fill_key"]),
                client_order_id=client_order_id,
                asset=intent.asset if intent else "",
                side=(intent.side if intent else "buy"),
                filled_quantity=quantity,
                fill_price=price,
                fee_amount=float(message.fill.get("fee_amount", 0.0)),
                fee_currency=str(message.fill.get("fee_currency", "")),
                event_time_utc=envelope.event_time_utc,
                provenance=self.context.provenance,
                provider_environment=self.context.provider_environment,
                raw_event_digest=envelope.payload_digest,
                venue_order_id=message.venue_order_id,
                fee_conversion_rate=message.fill.get("fee_conversion_rate"),
                fee_conversion_currency=message.fill.get("fee_conversion_currency"),
            )
        )
        return envelope

    def resolve_unknown(
        self,
        client_order_id: str,
        *,
        confirmed_state: str,
        now_ms: int,
        evidence: str,
        venue_order_id: str | None = None,
    ) -> ExecutionEnvelope:
        """Resolve an ``UNKNOWN`` order from a primary source, without resending it."""

        state = self._orders[client_order_id]
        if not state.resolve_pending:
            raise RiskGateViolation(
                f"{client_order_id} is not UNKNOWN; resolving it would fabricate a query"
            )
        intent = self._intents.get(client_order_id)
        if confirmed_state not in (
            "ACKNOWLEDGED",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELED",
            "REJECTED",
            "EXPIRED",
        ):
            raise RiskGateViolation(
                f"{confirmed_state!r} is not a state a primary source can confirm"
            )
        state.resolve_pending = False
        state.closed = True
        return self._emit(
            client_order_id=client_order_id,
            asset=intent.asset if intent else "",
            strategy_id=intent.strategy_id if intent else "",
            event_type="ORDER_STATE_RESOLVED",
            event_time_ms=now_ms,
            payload={"confirmed_state": confirmed_state, "evidence": evidence},
            intent=intent,
            venue_order_id=venue_order_id,
        )

    def drive(
        self,
        intent: OrderIntent,
        *,
        script: VenueScript,
        venue_any: Any,
        submit_ms: int,
        decision_ms: int | None = None,
    ) -> list[ExecutionEnvelope]:
        """One whole order: create → submit → every message the venue returns.

        ``venue_any`` is any object with the ``submit`` method of
        :class:`~trading_bot.paper.lifecycle.venue.SimulatedPaperVenue`.
        """

        messages = venue_any.submit(
            client_order_id=intent.client_order_id,
            ordered_qty=float(intent.quantity),
            reference_price=float(intent.notional_usdt) / float(intent.quantity)
            if intent.quantity
            else 0.0,
            submit_ms=submit_ms,
            script=script,
        )
        return self.drive_messages(intent, messages=messages, submit_ms=submit_ms)

    def drive_messages(
        self,
        intent: OrderIntent,
        *,
        messages: list[VenueMessage],
        submit_ms: int,
    ) -> list[ExecutionEnvelope]:
        events: list[ExecutionEnvelope] = []
        events.extend(
            self.create(intent, now_ms=submit_ms, risk_approved=bool(intent.risk_evaluation_id))
        )
        events.append(self.submit(intent.client_order_id, now_ms=submit_ms))
        for message in messages:
            event = self.ingest(message, client_order_id=intent.client_order_id)
            if event is not None:
                events.append(event)
        return events


__all__ = ["LifecycleEngine", "RunContext"]
