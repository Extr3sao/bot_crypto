"""Deterministic TradeIntent identity and execution reliability primitives.

EXECUTION-RELIABILITY-01 (checkpoint EXTERNAL-AUDIT-RECONCILIATION-01):

- ``TradeIntent``: immutable economic intent with a deterministic ``intent_id``
  derived from canonical economic fields. Same economic intent -> same
  ``intent_id``. Wall-clock and randomness are excluded from identity; they may
  exist only in metadata.
- ``derive_client_order_id``: stable client order identity derived from the
  intent id (never from uuid4/time).
- ``FillLedger``: venue-fill-identity idempotency. A duplicate or out-of-order
  fill applies position/fee/PnL deltas exactly once.
- ``AmbiguousAckRecovery``: timeout after submit != safe retry. Resolves
  ACK_UNKNOWN via venue query by stable identity: ADOPT / CONTROLLED_RETRY /
  BLOCK. Never creates a second economic order while ambiguity exists.
- ``IdempotentSubmitGate``: enforces ECONOMIC_ORDERS_PER_INTENT <= 1 under
  retries and recovery ambiguity.

No live trading is enabled by this module. It is adapter-agnostic: the submit
function is injected by the caller (fake exchange, simulated adapter, paper
broker, or a future live adapter gated by ``execution.live_gate``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Canonical economic fields that define intent identity. Order matters only
# for documentation: the hash canonicalizes by sorting field names.
CANONICAL_INTENT_FIELDS: tuple[str, ...] = (
    "account_id",
    "venue",
    "symbol",
    "side",
    "order_type",
    "quantity",
    "limit_price",
    "reduce_only",
)


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """Immutable economic intent to trade.

    ``metadata`` is explicitly excluded from identity: it may carry wall-clock
    timestamps, request ids, or strategy provenance without changing the
    intent id.
    """

    symbol: str
    side: str  # "buy" / "sell"
    quantity: float
    order_type: str = "market"  # "market" / "limit"
    limit_price: float | None = None
    venue: str = ""
    account_id: str = ""
    reduce_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError(f"intent side must be buy/sell, got {self.side!r}")
        if self.quantity <= 0:
            raise ValueError(f"intent quantity must be > 0, got {self.quantity!r}")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit intent requires limit_price")
        if self.order_type not in ("market", "limit"):
            raise ValueError(f"order_type must be market/limit, got {self.order_type!r}")

    def canonical_identity_payload(self) -> dict[str, Any]:
        """Canonical economic payload used for identity (metadata excluded)."""
        return {
            "account_id": self.account_id,
            "limit_price": _norm_number(self.limit_price),
            "order_type": self.order_type,
            "quantity": _norm_number(self.quantity),
            "reduce_only": self.reduce_only,
            "side": self.side,
            "symbol": self.symbol,
            "venue": self.venue,
        }


def _norm_number(value: float | None) -> str:
    """Normalize a float to a stable decimal representation for hashing."""
    if value is None:
        return ""
    return format(float(value), ".12f").rstrip("0").rstrip(".")


def compute_intent_id(intent: TradeIntent) -> str:
    """Deterministic intent id: same economic intent -> same id.

    SHA-256 over the canonical JSON of the economic fields. The id is prefixed
    with ``TI-`` and truncated to 32 hex chars for venue client-id budgets.
    """
    payload = intent.canonical_identity_payload()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"TI-{digest}"


def derive_client_order_id(intent_id: str) -> str:
    """Stable client order id derived from the intent id (no wall clock)."""
    return f"CO-{intent_id.removeprefix('TI-')}"


class AckQueryResult(Enum):
    """Outcome of querying the venue for an order submitted under ambiguity."""

    FOUND = "found"  # venue knows the order -> ADOPT
    ABSENT = "absent"  # venue definitively never accepted -> CONTROLLED_RETRY
    UNCERTAIN = "uncertain"  # query failed/inconclusive -> BLOCK


class RecoveryDecision(Enum):
    """Recovery decision after an ambiguous submit."""

    ADOPT = "adopt"
    CONTROLLED_RETRY = "controlled_retry"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class RecoveryVerdict:
    """Decision plus evidence for an ACK_UNKNOWN resolution."""

    decision: RecoveryDecision
    query_result: AckQueryResult
    reason: str
    venue_order_id: str | None = None


@dataclass
class AmbiguousAckRecovery:
    """Resolve ambiguous ACKs without ever duplicating economic exposure.

    Invariant: timeout after submit != safe retry. The submitter moves to
    ACK_UNKNOWN; the venue is queried by stable identity (intent_id /
    client_order_id). Only a definitive ABSENT allows a controlled retry with
    the SAME intent_id (hence the same client_order_id).
    """

    intent_id: str
    client_order_id: str
    state: str = "SUBMITTING"  # SUBMITTING / ACK_UNKNOWN / ADOPTED / RETRYABLE / BLOCKED

    def on_submit_timeout(self) -> RecoveryVerdict:
        """Enter ACK_UNKNOWN after a submit timeout."""
        if self.state != "SUBMITTING":
            raise ExecutionReliabilityError(
                f"on_submit_timeout requires SUBMITTING state, got {self.state}"
            )
        self.state = "ACK_UNKNOWN"
        return RecoveryVerdict(
            decision=RecoveryDecision.BLOCK,
            query_result=AckQueryResult.UNCERTAIN,
            reason="submit timed out; venue query required before any retry",
        )

    def resolve(
        self, query_result: AckQueryResult, *, venue_order_id: str | None = None
    ) -> RecoveryVerdict:
        """Resolve ACK_UNKNOWN with a venue query outcome."""
        if self.state == "ADOPTED":
            return RecoveryVerdict(
                decision=RecoveryDecision.ADOPT,
                query_result=query_result,
                reason="order already adopted; no further submits allowed",
                venue_order_id=venue_order_id,
            )
        if self.state == "BLOCKED":
            return RecoveryVerdict(
                decision=RecoveryDecision.BLOCK,
                query_result=AckQueryResult.UNCERTAIN,
                reason="already blocked; remains blocked until reconciliation",
            )
        if self.state != "ACK_UNKNOWN":
            raise ExecutionReliabilityError(f"resolve requires ACK_UNKNOWN state, got {self.state}")
        if query_result is AckQueryResult.FOUND:
            self.state = "ADOPTED"
            return RecoveryVerdict(
                decision=RecoveryDecision.ADOPT,
                query_result=query_result,
                reason="venue holds the order; adopt venue_order_id, never resubmit",
                venue_order_id=venue_order_id,
            )
        if query_result is AckQueryResult.ABSENT:
            self.state = "RETRYABLE"
            return RecoveryVerdict(
                decision=RecoveryDecision.CONTROLLED_RETRY,
                query_result=query_result,
                reason="venue definitively lacks the order; retry SAME intent_id",
            )
        self.state = "BLOCKED"
        return RecoveryVerdict(
            decision=RecoveryDecision.BLOCK,
            query_result=query_result,
            reason="venue query inconclusive; block new economic orders for this intent",
        )


class ExecutionReliabilityError(RuntimeError):
    """Raised when an execution-reliability invariant would be violated."""


@dataclass
class IdempotentSubmitGate:
    """Gate that guarantees ECONOMIC_ORDERS_PER_INTENT <= 1.

    Wraps any submit callable (fake exchange, simulated adapter, paper broker).
    The first submit for an intent id executes; every subsequent submit with
    the same intent id returns the first outcome without touching the adapter.
    ADOPTED intents (recovered after ACK_UNKNOWN) are also sealed.
    """

    _submitted: dict[str, str] = field(default_factory=dict)
    _sealed: set[str] = field(default_factory=set)

    def submit(self, intent: TradeIntent, submit_fn: Callable[[TradeIntent, str], str]) -> str:
        """Submit the intent at most once; returns the venue/order reference.

        ``submit_fn(intent, client_order_id)`` performs the actual economic
        submission and returns a venue order reference. It is invoked exactly
        zero or one times per intent id.
        """
        intent_id = compute_intent_id(intent)
        if intent_id in self._sealed:
            raise ExecutionReliabilityError(
                f"intent {intent_id} is sealed (adopted/terminal); resubmission forbidden"
            )
        if intent_id in self._submitted:
            return self._submitted[intent_id]
        client_order_id = derive_client_order_id(intent_id)
        reference = submit_fn(intent, client_order_id)
        self._submitted[intent_id] = reference
        return reference

    def seal(self, intent_id: str) -> None:
        """Seal an intent after adoption/terminal state; further submits raise."""
        self._sealed.add(intent_id)

    def economic_order_count(self, intent_id: str) -> int:
        """Number of economic submissions performed for an intent (0 or 1)."""
        return 1 if intent_id in self._submitted else 0


@dataclass(frozen=True, slots=True)
class FillRecord:
    """A single applied venue fill (journal-once)."""

    venue_fill_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float
    applied: bool
    intent_id: str = ""


@dataclass(frozen=True, slots=True)
class FillApplication:
    """Deltas produced by applying a fill (empty when duplicate)."""

    applied: bool
    position_delta: float
    fee_delta: float
    pnl_delta: float
    duplicate: bool
    record: FillRecord


@dataclass
class FillLedger:
    """Venue-fill-identity idempotency.

    Each venue fill id applies its deltas exactly once regardless of delivery
    multiplicity or ordering. Out-of-order partial fills accumulate correctly.
    """

    _applied: dict[str, FillRecord] = field(default_factory=dict)

    def apply_fill(
        self,
        *,
        venue_fill_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        intent_id: str = "",
    ) -> FillApplication:
        """Apply a fill; duplicates return zero deltas with ``duplicate=True``."""
        if venue_fill_id in self._applied:
            record = self._applied[venue_fill_id]
            return FillApplication(
                applied=False,
                position_delta=0.0,
                fee_delta=0.0,
                pnl_delta=0.0,
                duplicate=True,
                record=record,
            )
        signed = quantity if side == "buy" else -quantity
        # Cash flow from this fill: sell -> +qty*price (money in),
        # buy -> -qty*price (money out); fees always negative.
        # PnL is realized as the signed cash flow.
        cash = (quantity * price) if side == "sell" else -(quantity * price)
        pnl_delta = cash - fee
        record = FillRecord(
            venue_fill_id=venue_fill_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            applied=True,
            intent_id=intent_id,
        )
        self._applied[venue_fill_id] = record
        return FillApplication(
            applied=True,
            position_delta=signed,
            fee_delta=fee,
            pnl_delta=pnl_delta,
            duplicate=False,
            record=record,
        )

    def is_known(self, venue_fill_id: str) -> bool:
        return venue_fill_id in self._applied

    def applied_count(self) -> int:
        return len(self._applied)
