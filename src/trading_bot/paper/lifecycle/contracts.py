"""Typed contracts for the paper execution lifecycle (EXP-003P).

What lives here: the vocabulary of an observed order — provenance, order states and
their legal transitions, the execution envelope every persisted event must satisfy,
the intent/fill/reconciliation records, and the canonical serialisation used to hash
them. What deliberately does *not* live here: any venue, any risk policy, any decision
about whether to trade. This module is import-only and side-effect free.

Every field exists because an auditor has to be able to answer, from the event alone,
which program produced it, in which environment, on which clock, for which decision.
A field that cannot be justified that way is not in the envelope.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

SCHEMA_VERSION: Final = "AI_BOTS_003P_ENVELOPE_V1"

#: Where an event came from. These three are not interchangeable and none of them can be
#: promoted by relabelling: ``OFFLINE_SIMULATED`` proves what the code does, never that a
#: venue accepted anything.
PROVENANCES: Final = ("OFFLINE_SIMULATED", "REPLAY_CAPTURED", "VENUE_REPORTED_PAPER")

PROVIDER_ENVIRONMENTS: Final = ("OFFLINE", "REPLAY", "TESTNET", "PAPER")

#: The only pairs a coherent statement can take. A ``VENUE_REPORTED_PAPER`` event claiming
#: to come from ``OFFLINE`` is a provenance defect, not a nuance.
PROVENANCE_ENVIRONMENTS: Final[dict[str, frozenset[str]]] = {
    "OFFLINE_SIMULATED": frozenset({"OFFLINE"}),
    "REPLAY_CAPTURED": frozenset({"REPLAY", "OFFLINE"}),
    "VENUE_REPORTED_PAPER": frozenset({"TESTNET", "PAPER"}),
}

ORDER_STATES: Final = (
    "CREATED",
    "RISK_REJECTED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELED",
    "REJECTED",
    "EXPIRED",
    "UNKNOWN",
)

TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"RISK_REJECTED", "FILLED", "CANCELED", "REJECTED", "EXPIRED"}
)

#: The transition table of RFC-003P §5.3, expressed once. ``UNKNOWN`` is not terminal: it
#: is the state that forces a query against the primary source before anything else moves.
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "CREATED": frozenset({"RISK_REJECTED", "SUBMITTING"}),
    "SUBMITTING": frozenset({"ACKNOWLEDGED", "REJECTED", "UNKNOWN"}),
    "ACKNOWLEDGED": frozenset(
        {"PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "UNKNOWN"}
    ),
    "PARTIALLY_FILLED": frozenset({"FILLED", "CANCELED", "EXPIRED", "UNKNOWN"}),
    "UNKNOWN": frozenset({"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED"}),
    "RISK_REJECTED": frozenset(),
    "FILLED": frozenset(),
    "CANCELED": frozenset(),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset(),
}

#: Event type → the state the event asserts. An event that asserts nothing is not an
#: order event and belongs in the decision trace instead.
EVENT_STATES: Final[dict[str, str]] = {
    "ORDER_CREATED": "CREATED",
    "ORDER_RISK_REJECTED": "RISK_REJECTED",
    "ORDER_SUBMITTED": "SUBMITTING",
    "ORDER_ACKNOWLEDGED": "ACKNOWLEDGED",
    "ORDER_PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "ORDER_FILLED": "FILLED",
    "ORDER_CANCELED": "CANCELED",
    "ORDER_REJECTED": "REJECTED",
    "ORDER_EXPIRED": "EXPIRED",
    "ORDER_UNKNOWN": "UNKNOWN",
    "ORDER_STATE_RESOLVED": "ACKNOWLEDGED",
}

#: Closed vocabulary of defects a projection may report. A failure outside this set is a
#: crash, never a verdict: "some exception happened" is exactly the PASS-by-accident the
#: negative controls must not accept.
ANOMALIES: Final = (
    "DUPLICATE_EVENT",
    "DUPLICATE_FILL",
    "OUT_OF_ORDER_EVENT",
    "FILL_WITHOUT_ACK",
    "ILLEGAL_TRANSITION",
    "TERMINAL_STATE_MUTATION",
    "QUANTITY_EXCEEDED",
    "NEGATIVE_QUANTITY",
    "CAUSALITY_VIOLATION",
    "PROVENANCE_MISMATCH",
    "DATA_INTEGRITY_FAIL",
    "RISK_GATE_VIOLATION",
    "LIVE_MODE_FORBIDDEN",
    "EXIT_WITHOUT_POSITION",
    "FEE_UNPRICED",
    "LEDGER_MISMATCH",
    "UNKNOWN_REQUIRES_RECONCILIATION",
)

RECONCILIATION_RESULTS: Final = ("PASS", "FAIL", "INCOMPLETE")


class LifecycleViolation(Exception):
    """Base class: a lifecycle statement that cannot be made true."""

    #: The anomaly code this violation means, so a control can demand *this* class.
    code: str = "DATA_INTEGRITY_FAIL"


class IllegalTransition(LifecycleViolation):
    code = "ILLEGAL_TRANSITION"


class ProvenanceViolation(LifecycleViolation):
    code = "PROVENANCE_MISMATCH"


class CausalityViolation(LifecycleViolation):
    code = "CAUSALITY_VIOLATION"


class RiskGateViolation(LifecycleViolation):
    code = "RISK_GATE_VIOLATION"


class LiveModeForbidden(ProvenanceViolation):
    """A statement about live execution dressed as a paper event."""

    code = "LIVE_MODE_FORBIDDEN"


def utc_ms(ms: int) -> str:
    """Fixed-width ISO-8601 UTC with milliseconds: lexicographic order == time order."""

    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_utc(text: str) -> int:
    """Inverse of :func:`utc_ms`, tolerant of a missing millisecond block."""

    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1]
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in value else "%Y-%m-%dT%H:%M:%S"
    return int(datetime.strptime(value, fmt).replace(tzinfo=UTC).timestamp() * 1000)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest_of(payload: Any) -> str:
    """Content digest of any JSON-representable value (the payload digest)."""

    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionEnvelope:
    """One observed execution event, complete enough to stand alone as evidence.

    ``event_id`` is minted by the producer; the store dedupes on
    ``(provenance, provider_environment, event_id)`` because two venues may legitimately
    reuse an identifier. ``correlation_parent_id`` links an event back to the intent that
    caused it, so a trace can be walked backwards without guessing.
    """

    run_id: str
    commit_sha: str
    config_digest: str
    client_order_id: str
    event_id: str
    asset: str
    strategy_id: str
    adapter_id: str
    event_type: str
    event_time_utc: str
    received_time_utc: str
    clock_source: str
    provenance: str
    provider_environment: str
    decision_id: str | None = None
    proposal_id: str | None = None
    signal_id: str | None = None
    venue_order_id: str | None = None
    correlation_parent_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    # -- validation -----------------------------------------------------------

    def validate(self) -> None:
        """Fail before the event is written; a bad event is never persisted."""

        if self.event_type not in EVENT_STATES:
            raise LifecycleViolation(f"unknown event_type {self.event_type!r}")
        if self.provenance not in PROVENANCES:
            raise ProvenanceViolation(f"unknown provenance {self.provenance!r}")
        if self.provider_environment == "LIVE":
            raise LiveModeForbidden("LIVE is not a paper environment")
        allowed = PROVENANCE_ENVIRONMENTS[self.provenance]
        if self.provider_environment not in allowed:
            raise ProvenanceViolation(
                f"{self.provenance} cannot claim provider_environment "
                f"{self.provider_environment!r}; allowed {sorted(allowed)}"
            )
        for name in ("run_id", "client_order_id", "event_id", "asset", "adapter_id"):
            if not str(getattr(self, name)).strip():
                raise LifecycleViolation(f"{name} must not be empty")
        # Causal order: a producer that cannot place its own event after its inputs is not
        # reporting an execution, it is guessing.
        if parse_utc(self.received_time_utc) < parse_utc(self.event_time_utc):
            raise CausalityViolation(
                f"event {self.event_id} was received before it happened "
                f"({self.received_time_utc} < {self.event_time_utc})"
            )
        intent_ms = self.payload.get("decision_time_utc")
        cutoff_ms = self.payload.get("data_cutoff_utc")
        if intent_ms and cutoff_ms and parse_utc(str(cutoff_ms)) > parse_utc(str(intent_ms)):
            raise CausalityViolation(
                f"event {self.event_id} decided at {intent_ms} on data cut at {cutoff_ms}"
            )
        if intent_ms and parse_utc(str(intent_ms)) > parse_utc(self.event_time_utc):
            raise CausalityViolation(
                f"event {self.event_id} claims an intent from the future ({intent_ms})"
            )

    # -- derived values -------------------------------------------------------

    @property
    def state(self) -> str:
        return EVENT_STATES[self.event_type]

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        return (self.provenance, self.provider_environment, self.event_id)

    @property
    def payload_digest(self) -> str:
        return digest_of(self.payload)

    @property
    def order_key(self) -> str:
        """The identity a state machine walks: the client id plus its venue namespace."""

        return f"{self.provider_environment}:{self.client_order_id}"

    def to_row(self) -> dict[str, Any]:
        row = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "commit_sha": self.commit_sha,
            "config_digest": self.config_digest,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "signal_id": self.signal_id,
            "client_order_id": self.client_order_id,
            "venue_order_id": self.venue_order_id,
            "event_id": self.event_id,
            "asset": self.asset,
            "strategy_id": self.strategy_id,
            "adapter_id": self.adapter_id,
            "event_type": self.event_type,
            "event_time_utc": self.event_time_utc,
            "received_time_utc": self.received_time_utc,
            "clock_source": self.clock_source,
            "provenance": self.provenance,
            "provider_environment": self.provider_environment,
            "correlation_parent_id": self.correlation_parent_id,
            "payload_digest": self.payload_digest,
            "payload": dict(self.payload),
        }
        return row

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ExecutionEnvelope:
        known = {
            "run_id",
            "commit_sha",
            "config_digest",
            "decision_id",
            "proposal_id",
            "signal_id",
            "client_order_id",
            "venue_order_id",
            "event_id",
            "asset",
            "strategy_id",
            "adapter_id",
            "event_type",
            "event_time_utc",
            "received_time_utc",
            "clock_source",
            "provenance",
            "provider_environment",
            "correlation_parent_id",
            "schema_version",
        }
        kwargs = {key: row[key] for key in known if key in row}
        envelope = cls(payload=dict(row.get("payload") or {}), **kwargs)
        declared = row.get("payload_digest")
        if declared is not None and declared != envelope.payload_digest:
            raise ProvenanceViolation(
                f"event {envelope.event_id} payload digest {declared} does not match its "
                f"content {envelope.payload_digest}"
            )
        return envelope


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """What the system asks the venue to do, before the venue has said anything."""

    client_order_id: str
    asset: str
    side: str
    order_type: str
    quantity: float
    strategy_id: str
    decision_time_utc: str
    data_cutoff_utc: str
    limit_price: float | None = None
    time_in_force: str | None = None
    risk_evaluation_id: str = ""
    policy_verification_id: str = ""
    notional_usdt: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    decision_id: str | None = None
    proposal_id: str | None = None
    signal_id: str | None = None

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise LifecycleViolation(f"unknown side {self.side!r}")
        if not (self.quantity > 0):
            raise LifecycleViolation(f"quantity must be > 0, got {self.quantity!r}")
        if parse_utc(self.data_cutoff_utc) > parse_utc(self.decision_time_utc):
            raise CausalityViolation(
                f"intent {self.client_order_id} decided at {self.decision_time_utc} "
                f"on data cut at {self.data_cutoff_utc}"
            )
        if not self.risk_evaluation_id:
            # Sending is gated on this; an intent without it can only be risk-rejected.
            return

    @property
    def idempotency_key(self) -> str:
        """Stable across retries by construction: it is the intent, not the attempt."""

        return digest_of(
            {
                "asset": self.asset,
                "client_order_id": self.client_order_id,
                "decision_time_utc": self.decision_time_utc,
                "side": self.side,
                "strategy_id": self.strategy_id,
            }
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "asset": self.asset,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force,
            "strategy_id": self.strategy_id,
            "risk_evaluation_id": self.risk_evaluation_id,
            "policy_verification_id": self.policy_verification_id,
            "idempotency_key": self.idempotency_key,
            "decision_time_utc": self.decision_time_utc,
            "data_cutoff_utc": self.data_cutoff_utc,
            "notional_usdt": self.notional_usdt,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "signal_id": self.signal_id,
        }


@dataclass(frozen=True, slots=True)
class FillFact:
    """One execution against one order, keyed inside its own provenance namespace.

    ``fill_key`` is the dedupe identity \u2014 provider fill id when one exists, a documented
    deterministic substitute when the venue publishes none. Two facts with the same key in
    the same namespace are the same fill, however many times they arrive.
    """

    fill_key: str
    client_order_id: str
    asset: str
    side: str
    filled_quantity: float
    fill_price: float
    fee_amount: float
    fee_currency: str
    event_time_utc: str
    provenance: str
    provider_environment: str
    raw_event_digest: str
    venue_order_id: str | None = None
    fee_conversion_rate: float | None = None
    fee_conversion_currency: str | None = None

    def __post_init__(self) -> None:
        if not (self.filled_quantity > 0):
            raise LifecycleViolation(f"fill {self.fill_key} has non-positive quantity")
        if not (self.fill_price > 0):
            raise LifecycleViolation(f"fill {self.fill_key} has non-positive price")
        if self.fee_amount < 0:
            raise LifecycleViolation(f"fill {self.fill_key} has a negative fee")
        if self.provenance not in PROVENANCES:
            raise ProvenanceViolation(f"fill {self.fill_key} provenance {self.provenance!r}")

    @property
    def namespace_key(self) -> tuple[str, str]:
        return (self.provenance, self.fill_key)

    @property
    def notional(self) -> float:
        return float(self.filled_quantity) * float(self.fill_price)

    def to_row(self) -> dict[str, Any]:
        return {
            "fill_key": self.fill_key,
            "client_order_id": self.client_order_id,
            "venue_order_id": self.venue_order_id,
            "asset": self.asset,
            "side": self.side,
            "filled_quantity": self.filled_quantity,
            "fill_price": self.fill_price,
            "fee_amount": self.fee_amount,
            "fee_currency": self.fee_currency,
            "fee_conversion_rate": self.fee_conversion_rate,
            "fee_conversion_currency": self.fee_conversion_currency,
            "event_time_utc": self.event_time_utc,
            "provenance": self.provenance,
            "provider_environment": self.provider_environment,
            "raw_event_digest": self.raw_event_digest,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    run_id: str
    source: str
    as_of_time: str
    local_order_state: dict[str, Any]
    provider_order_state: dict[str, Any] | None
    local_qty: float
    provider_qty: float | None
    cash_delta: float | None
    position_delta: float | None
    fee_delta: float | None
    differences: tuple[dict[str, Any], ...]
    result: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.result not in RECONCILIATION_RESULTS:
            raise LifecycleViolation(f"unknown reconciliation result {self.result!r}")
        if self.result == "PASS" and self.differences:
            raise LifecycleViolation("a PASS with unexplained differences is not a PASS")

    def to_row(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source": self.source,
            "as_of_time": self.as_of_time,
            "local_order_state": self.local_order_state,
            "provider_order_state": self.provider_order_state,
            "local_qty": self.local_qty,
            "provider_qty": self.provider_qty,
            "cash_delta": self.cash_delta,
            "position_delta": self.position_delta,
            "fee_delta": self.fee_delta,
            "differences": [dict(item) for item in self.differences],
            "result": self.result,
            "evidence_refs": list(self.evidence_refs),
        }


def transition_error(current: str, target: str) -> IllegalTransition | None:
    """``None`` when the move is legal, the exception to raise when it is not."""

    if current not in ALLOWED_TRANSITIONS:
        return IllegalTransition(f"unknown current state {current!r}")
    if target not in ALLOWED_TRANSITIONS:
        return IllegalTransition(f"unknown target state {target!r}")
    if target in ALLOWED_TRANSITIONS[current]:
        return None
    return IllegalTransition(f"{current} -> {target} is not an allowed transition")


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ANOMALIES",
    "EVENT_STATES",
    "PROVENANCES",
    "PROVENANCE_ENVIRONMENTS",
    "PROVIDER_ENVIRONMENTS",
    "RECONCILIATION_RESULTS",
    "SCHEMA_VERSION",
    "TERMINAL_STATES",
    "CausalityViolation",
    "ExecutionEnvelope",
    "FillFact",
    "IllegalTransition",
    "LifecycleViolation",
    "LiveModeForbidden",
    "OrderIntent",
    "ProvenanceViolation",
    "ReconciliationResult",
    "RiskGateViolation",
    "canonical_json",
    "digest_of",
    "parse_utc",
    "transition_error",
    "utc_ms",
]
