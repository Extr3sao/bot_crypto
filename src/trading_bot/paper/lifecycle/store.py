"""Durable event store, order-state projection and the fill ledger.

Three separate things, kept separate on purpose:

* :class:`DurableEventStore` -- append-only, hash-chained, deduplicating. It never
  interprets an event; it preserves it and proves afterwards that it was not altered.
* :func:`project_orders` -- the state machine of RFC-003P 5.3 applied to the preserved
  events in causal order, reporting anomalies instead of silently repairing them.
* :class:`FillLedger` -- accounting applied exactly once per fill key inside its own
  provenance namespace.

Nothing here talks to a venue, a broker or a file descriptor unless asked to.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .contracts import (
    ALLOWED_TRANSITIONS,
    EVENT_STATES,
    TERMINAL_STATES,
    ExecutionEnvelope,
    FillFact,
    LifecycleViolation,
    canonical_json,
)

GENESIS_DIGEST: Final = "sha256:" + "0" * 64


def _chain_head(previous: str, row: dict[str, Any]) -> str:
    payload = previous.encode("utf-8") + b"\n" + canonical_json(row).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """One persisted event with the chain digest that binds it to its predecessor."""

    seq: int
    envelope: ExecutionEnvelope
    chain_digest: str

    def to_row(self) -> dict[str, Any]:
        return {"seq": self.seq, "chain_digest": self.chain_digest, **self.envelope.to_row()}


class DurableEventStore:
    """Append-only store with per-event dedupe and a sha256 chain over the sequence.

    ``append`` is the only mutator. It returns the sequence number of the event it
    accepted, or ``None`` when the event is a duplicate -- the caller learns that the
    duplicate was *seen* without the store pretending to have accepted it twice. A
    duplicate is reported, never dropped in silence.
    """

    def __init__(self) -> None:
        self._events: list[StoredEvent] = []
        self._seen: dict[tuple[str, str, str], int] = {}
        self._duplicates: list[dict[str, Any]] = []
        self._head: str = GENESIS_DIGEST

    # -- mutation -------------------------------------------------------------

    def append(self, envelope: ExecutionEnvelope) -> int | None:
        key = envelope.dedupe_key
        if key in self._seen:
            self._duplicates.append(
                {
                    "event_id": envelope.event_id,
                    "client_order_id": envelope.client_order_id,
                    "provenance": envelope.provenance,
                    "provider_environment": envelope.provider_environment,
                    "first_seq": self._seen[key],
                    "event_time_utc": envelope.event_time_utc,
                }
            )
            return None
        seq = len(self._events) + 1
        row = {**envelope.to_row(), "seq": seq}
        chain = _chain_head(self._head, row)
        self._events.append(StoredEvent(seq=seq, envelope=envelope, chain_digest=chain))
        self._head = chain
        self._seen[key] = seq
        return seq

    # -- read-only views ------------------------------------------------------

    @property
    def events(self) -> tuple[StoredEvent, ...]:
        return tuple(self._events)

    @property
    def envelopes(self) -> tuple[ExecutionEnvelope, ...]:
        return tuple(event.envelope for event in self._events)

    @property
    def duplicates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._duplicates)

    @property
    def head_digest(self) -> str:
        return self._head

    def rows(self) -> list[dict[str, Any]]:
        return [event.to_row() for event in self._events]

    def digest(self) -> str:
        """Canonical digest of the whole sequence, used for run-to-run comparison."""

        return "sha256:" + hashlib.sha256(
            canonical_json(self.rows()).encode("utf-8")
        ).hexdigest()

    # -- persistence ----------------------------------------------------------

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for event in self._events:
                handle.write(canonical_json(event.to_row()) + "\n")

    @classmethod
    def load_jsonl(cls, path: Path) -> DurableEventStore:
        """Re-read a persisted trace and re-verify every link of the chain.

        A single altered byte anywhere in the file breaks the chain and raises: the store
        refuses to build a projection on evidence it cannot authenticate.
        """

        store = cls()
        previous = GENESIS_DIGEST
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                declared = str(row.pop("chain_digest"))
                # The chain is checked over the bytes as written, before any semantic
                # validation: a row edited on disk is an integrity failure, and calling it
                # a provenance mismatch would name the wrong defect.
                expected = _chain_head(previous, row)
                if declared != expected:
                    raise LifecycleViolation(
                        f"integrity failure at {path.name}:{index}: chain digest {declared} "
                        f"does not match {expected}"
                    )
                envelope = ExecutionEnvelope.from_row(row)
                if envelope.dedupe_key in store._seen:
                    raise LifecycleViolation(
                        f"integrity failure at {path.name}:{index}: duplicate event id "
                        f"{envelope.event_id} in a persisted trace"
                    )
                store._events.append(
                    StoredEvent(seq=index, envelope=envelope, chain_digest=declared)
                )
                store._seen[envelope.dedupe_key] = index
                previous = declared
                store._head = declared
        return store


@dataclass
class OrderProjection:
    """The state machine's view of one order, derived only from stored events."""

    order_key: str
    client_order_id: str
    asset: str
    state: str = "CREATED"
    ordered_qty: float | None = None
    cum_filled_qty: float = 0.0
    acked: bool = False
    terminal: bool = False
    fills: list[dict[str, Any]] = field(default_factory=list)
    event_count: int = 0
    first_event_utc: str = ""
    last_event_utc: str = ""
    venue_order_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "order_key": self.order_key,
            "client_order_id": self.client_order_id,
            "asset": self.asset,
            "state": self.state,
            "ordered_qty": self.ordered_qty,
            "cum_filled_qty": self.cum_filled_qty,
            "acked": self.acked,
            "terminal": self.terminal,
            "fills": list(self.fills),
            "event_count": self.event_count,
            "first_event_utc": self.first_event_utc,
            "last_event_utc": self.last_event_utc,
            "venue_order_id": self.venue_order_id,
        }


@dataclass(frozen=True, slots=True)
class Anomaly:
    code: str
    order_key: str
    event_id: str
    detail: str

    def to_row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "order_key": self.order_key,
            "event_id": self.event_id,
            "detail": self.detail,
        }


@dataclass
class Projection:
    orders: dict[str, OrderProjection] = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)
    applied_seq: list[int] = field(default_factory=list)

    def codes(self) -> list[str]:
        return [anomaly.code for anomaly in self.anomalies]

    def to_row(self) -> dict[str, Any]:
        return {
            "orders": [order.to_row() for order in self.orders.values()],
            "anomalies": [anomaly.to_row() for anomaly in self.anomalies],
            "orders_seen": len(self.orders),
            "anomaly_count": len(self.anomalies),
        }


def project_orders(events: list[tuple[int, ExecutionEnvelope]]) -> Projection:
    """Apply the state machine in causal order and report every violation it found.

    Events are grouped per order and ordered by ``(event_time_utc, arrival order)``. That
    is the causal reading: a fact that happened earlier is applied earlier, whichever
    order the transport delivered it in. An event whose arrival contradicted that order is
    still preserved by the store, and this function records ``OUT_OF_ORDER_EVENT`` for it.
    """

    projection = Projection()
    grouped: dict[str, list[tuple[int, ExecutionEnvelope]]] = {}
    for seq, envelope in events:
        grouped.setdefault(envelope.order_key, []).append((seq, envelope))

    for order_key in sorted(grouped):
        raw = grouped[order_key]
        ordered = sorted(raw, key=lambda item: (item[1].event_time_utc, item[0]))
        projection.applied_seq.extend(seq for seq, _ in ordered)
        # Out-of-order transport: the arrival sequence disagreed with the event times.
        arrivals = [seq for seq, _ in raw]
        causal = [seq for seq, _ in ordered]
        for seq, envelope in raw:
            if arrivals.index(seq) != causal.index(seq):
                projection.anomalies.append(
                    Anomaly(
                        code="OUT_OF_ORDER_EVENT",
                        order_key=order_key,
                        event_id=envelope.event_id,
                        detail=(
                            f"arrived as #{arrivals.index(seq) + 1} but belongs at "
                            f"#{causal.index(seq) + 1} by event_time_utc"
                        ),
                    )
                )
        order = OrderProjection(
            order_key=order_key,
            client_order_id=ordered[0][1].client_order_id,
            asset=ordered[0][1].asset,
        )
        for seq, envelope in ordered:
            _apply(projection, order, seq, envelope)
        projection.orders[order_key] = order
    return projection


def _apply(
    projection: Projection, order: OrderProjection, seq: int, envelope: ExecutionEnvelope
) -> None:
    target = EVENT_STATES[envelope.event_type]
    if envelope.event_type == "ORDER_STATE_RESOLVED":
        # The state a primary source confirmed, not the generic landing state.
        target = str(envelope.payload.get("confirmed_state") or target)
    order.event_count += 1
    if not order.first_event_utc:
        order.first_event_utc = envelope.event_time_utc
    order.last_event_utc = max(order.last_event_utc, envelope.event_time_utc)
    if envelope.venue_order_id and order.venue_order_id is None:
        order.venue_order_id = envelope.venue_order_id
    if target == "CREATED":
        ordered_qty = envelope.payload.get("quantity")
        if ordered_qty is not None:
            order.ordered_qty = float(ordered_qty)

    fill = envelope.payload.get("fill")
    # A fill is a fact about quantity. It can arrive before the acknowledgement of the order
    # that produced it; that is a defect to report, not a sequence to invent.
    if fill is not None and not order.acked:
        projection.anomalies.append(
            Anomaly(
                code="FILL_WITHOUT_ACK",
                order_key=order.order_key,
                event_id=envelope.event_id,
                detail="a fill was observed before any acknowledgement of this order",
            )
        )

    if order.terminal:
        projection.anomalies.append(
            Anomaly(
                code="TERMINAL_STATE_MUTATION",
                order_key=order.order_key,
                event_id=envelope.event_id,
                detail=f"{order.state} is terminal; {envelope.event_type} may not reopen it",
            )
        )
        return

    if target != order.state and target not in ALLOWED_TRANSITIONS.get(order.state, frozenset()):
        code = "ILLEGAL_TRANSITION"
        if target == "ACKNOWLEDGED" and fill is not None:
            code = "FILL_WITHOUT_ACK"
        projection.anomalies.append(
            Anomaly(
                code=code,
                order_key=order.order_key,
                event_id=envelope.event_id,
                detail=f"{order.state} -> {target} via {envelope.event_type}",
            )
        )
        return

    order.state = target
    order.terminal = target in TERMINAL_STATES
    if target == "ACKNOWLEDGED":
        order.acked = True
    if fill is not None:
        quantity = float(fill["filled_quantity"])
        if quantity <= 0:
            projection.anomalies.append(
                Anomaly(
                    code="NEGATIVE_QUANTITY",
                    order_key=order.order_key,
                    event_id=envelope.event_id,
                    detail=f"fill quantity {quantity} is not positive",
                )
            )
            return
        order.cum_filled_qty += quantity
        order.fills.append(
            {
                "event_id": envelope.event_id,
                "venue_order_id": envelope.venue_order_id,
                "filled_quantity": quantity,
                "fill_price": float(fill["fill_price"]),
                "fee_amount": float(fill.get("fee_amount", 0.0)),
                "fee_currency": str(fill.get("fee_currency", "")),
                "filled_at_utc": envelope.event_time_utc,
                "provenance": envelope.provenance,
            }
        )
        if order.ordered_qty is not None and order.cum_filled_qty > order.ordered_qty + 1e-9:
            projection.anomalies.append(
                Anomaly(
                    code="QUANTITY_EXCEEDED",
                    order_key=order.order_key,
                    event_id=envelope.event_id,
                    detail=(
                        f"cumulative {order.cum_filled_qty} exceeds ordered "
                        f"{order.ordered_qty}"
                    ),
                )
            )


@dataclass
class FillLedger:
    """Accounting applied exactly once per ``(provenance, fill_key)``.

    Cash, position quantity, fees and realised PnL are derived from the fills the venue
    reported, never from an acknowledgement and never from an intent. Fees keep their own
    currency: a fee in a currency with no verified conversion rate makes the net PnL
    ``NOT_AVAILABLE`` instead of being quietly treated as zero.
    """

    _applied: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    _cash: dict[str, float] = field(default_factory=dict)
    _positions: dict[str, dict[str, float]] = field(default_factory=dict)
    _fees: dict[str, float] = field(default_factory=dict)
    _realized: dict[str, float] = field(default_factory=dict)
    _unpriced_fees: list[dict[str, Any]] = field(default_factory=list)
    _rejected: list[dict[str, Any]] = field(default_factory=list)

    # -- application ----------------------------------------------------------

    def apply(self, fill: FillFact) -> bool:
        """Apply one fill. Returns ``False`` (and records why) when it was a duplicate."""

        if fill.namespace_key in self._applied:
            self._rejected.append(
                {
                    "reason": "DUPLICATE_FILL",
                    "fill_key": fill.fill_key,
                    "provenance": fill.provenance,
                }
            )
            return False
        self._applied[fill.namespace_key] = fill.to_row()
        self._book(fill)
        return True

    def _book(self, fill: FillFact) -> None:
        asset = fill.asset
        signed = float(fill.filled_quantity) * (1.0 if fill.side == "buy" else -1.0)
        position = self._positions.setdefault(asset, {"quantity": 0.0, "cost_basis": 0.0})
        cash = -signed * float(fill.fill_price)
        self._cash[asset] = self._cash.get(asset, 0.0) + cash

        current = float(position["quantity"])
        if current == 0.0 or current * signed > 0:
            # Opening or adding: the basis grows by what the new quantity cost.
            position["quantity"] = current + signed
            position["cost_basis"] = float(position["cost_basis"]) + float(fill.notional)
        else:
            closing = min(abs(signed), abs(current))
            average = float(position["cost_basis"]) / abs(current) if current else 0.0
            if current > 0:
                realized = (float(fill.fill_price) - average) * closing
            else:
                realized = (average - float(fill.fill_price)) * closing
            self._realized[asset] = self._realized.get(asset, 0.0) + realized
            position["quantity"] = current + signed
            position["cost_basis"] = abs(float(position["quantity"])) * average
            remainder = abs(signed) - closing
            if remainder > 0:
                position["cost_basis"] += remainder * float(fill.fill_price)

        currency = fill.fee_currency or "UNSPECIFIED"
        self._fees[currency] = self._fees.get(currency, 0.0) + float(fill.fee_amount)
        if currency != "USDT" and float(fill.fee_amount) > 0 and fill.fee_conversion_rate is None:
            self._unpriced_fees.append(
                {"fill_key": fill.fill_key, "fee_currency": currency,
                 "fee_amount": fill.fee_amount}
            )

    # -- views ----------------------------------------------------------------

    @property
    def applied_count(self) -> int:
        return len(self._applied)

    def raw_fills(self) -> list[dict[str, Any]]:
        """The applied fill rows, in key order: what reconciliation reads."""

        return [self._applied[key] for key in sorted(self._applied)]

    @property
    def duplicates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._rejected)

    @property
    def cash(self) -> dict[str, float]:
        return dict(self._cash)

    @property
    def positions(self) -> dict[str, dict[str, float]]:
        return {asset: dict(value) for asset, value in self._positions.items()}

    @property
    def fees_by_currency(self) -> dict[str, float]:
        return dict(self._fees)

    @property
    def realized_pnl(self) -> dict[str, float]:
        return dict(self._realized)

    @property
    def net_realized_pnl_usdt(self) -> float | None:
        """``None`` when a fee exists in a currency with no verified conversion."""

        if self._unpriced_fees:
            return None
        fees = sum(
            amount for currency, amount in self._fees.items() if currency in ("USDT", "UNSPECIFIED")
        )
        return round(sum(self._realized.values()) - fees, 10)

    def unrealized_pnl(self, marks: dict[str, float] | None) -> float | None:
        """``None`` when there is no point-in-time mark: never a zero by default."""

        if not marks:
            return None
        missing = [
            asset
            for asset, row in self._positions.items()
            if abs(row["quantity"]) > 0 and asset not in marks
        ]
        if missing:
            return None
        total = 0.0
        for asset, row in self._positions.items():
            quantity = row["quantity"]
            if quantity == 0:
                continue
            average = row["cost_basis"] / abs(quantity)
            price = float(marks[asset])
            total += (price - average) * quantity
        return round(total, 10)

    def to_row(self, marks: dict[str, float] | None = None) -> dict[str, Any]:
        return {
            "fills_applied": self.applied_count,
            "fills_rejected": len(self._rejected),
            "rejected": list(self._rejected),
            "cash": {asset: round(value, 10) for asset, value in sorted(self._cash.items())},
            "positions": {
                asset: {
                    "quantity": round(row["quantity"], 12),
                    "cost_basis": round(row["cost_basis"], 10),
                }
                for asset, row in sorted(self._positions.items())
            },
            "fees_by_currency": {key: round(value, 10) for key, value in sorted(self._fees.items())},
            "realized_pnl": {key: round(value, 10) for key, value in sorted(self._realized.items())},
            "net_realized_pnl_usdt": self.net_realized_pnl_usdt,
            "unrealized_pnl_usdt": self.unrealized_pnl(marks),
            "unpriced_fees": list(self._unpriced_fees),
        }

    def digest(self) -> str:
        payload = [self._applied[key] for key in sorted(self._applied)]
        return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def fills_from_events(events: list[tuple[int, ExecutionEnvelope]]) -> list[FillFact]:
    """Every fill the preserved events assert, in causal order, deduplicated by key."""

    facts: list[FillFact] = []
    seen: set[tuple[str, str]] = set()
    for _seq, envelope in sorted(events, key=lambda item: (item[1].event_time_utc, item[0])):
        payload = envelope.payload.get("fill")
        if payload is None:
            continue
        fact = FillFact(
            fill_key=str(payload["fill_key"]),
            client_order_id=envelope.client_order_id,
            asset=envelope.asset,
            side=str(payload.get("side", "")),
            filled_quantity=float(payload["filled_quantity"]),
            fill_price=float(payload["fill_price"]),
            fee_amount=float(payload.get("fee_amount", 0.0)),
            fee_currency=str(payload.get("fee_currency", "")),
            event_time_utc=envelope.event_time_utc,
            provenance=envelope.provenance,
            provider_environment=envelope.provider_environment,
            raw_event_digest=envelope.payload_digest,
            venue_order_id=envelope.venue_order_id,
            fee_conversion_rate=payload.get("fee_conversion_rate"),
            fee_conversion_currency=payload.get("fee_conversion_currency"),
        )
        if fact.namespace_key in seen:
            continue
        seen.add(fact.namespace_key)
        facts.append(fact)
    return facts


__all__ = [
    "GENESIS_DIGEST",
    "Anomaly",
    "DurableEventStore",
    "FillLedger",
    "OrderProjection",
    "Projection",
    "StoredEvent",
    "fills_from_events",
    "project_orders",
]
