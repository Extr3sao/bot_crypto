"""A deterministic offline venue, and the scripts that make it misbehave on purpose.

This is **not** a second execution platform: it is a test double of a venue. It decides
nothing about risk, sizing or policy, it holds no book that is used for accounting, and
every event it produces is tagged ``OFFLINE_SIMULATED`` by the caller. Its only job is to
produce venue-shaped messages -- acknowledgement, partial fills, rejects, timeouts -- at
instants the rehearsal can reproduce byte for byte.

The scripts exist so that ``PARTIALLY_FILLED``, ``UNKNOWN`` and duplicate delivery are
reachable facts in the controls instead of clauses in a document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

VENUE_MODES: Final = (
    "FULL_FILL",
    "PARTIAL_THEN_FILL",
    "PARTIAL_THEN_CANCEL",
    "REJECT_AT_SUBMIT",
    "TIMEOUT_UNKNOWN",
    "ACK_WITHOUT_FILL",
)

#: The instant at which the venue answers a submit. Kept as a constant of the venue, not
#: of the caller, so a rehearsal cannot accidentally produce a zero-latency fantasy.
ACK_DELAY_MS: Final = 5

#: Offline fee schedule. One number, declared, so the rehearsal pays *something* and the
#: ledger has a fee to reconcile instead of a comforting zero.
OFFLINE_FEE_BPS: Final = 4.0


@dataclass(frozen=True, slots=True)
class VenueScript:
    """How one order behaves at the venue, in one frozen description."""

    mode: str = "FULL_FILL"
    #: Fractions of the ordered quantity, in order. Must sum to 1.0 for a full fill.
    tranches: tuple[float, ...] = (1.0,)
    #: Milliseconds between the acknowledgement and each fill.
    fill_delays_ms: tuple[int, ...] = (120,)
    #: Deliver the last message twice, as a flaky transport would.
    duplicate_last: bool = False
    #: Deliver the fills before the acknowledgement, as a reordering transport would.
    deliver_fills_before_ack: bool = False
    #: Fill price as a fraction of the intent's reference price.
    price_ratio: float = 1.0
    fee_bps: float = OFFLINE_FEE_BPS

    def __post_init__(self) -> None:
        if self.mode not in VENUE_MODES:
            raise ValueError(f"unknown venue mode {self.mode!r}")
        if len(self.fill_delays_ms) != len(self.tranches):
            raise ValueError("each tranche needs one delay")
        if any(value <= 0 for value in self.tranches) and self.mode == "PARTIAL_THEN_FILL":
            raise ValueError("tranches must be positive fractions")


@dataclass(frozen=True, slots=True)
class VenueMessage:
    """One message the venue emits. ``fill`` is present only when quantity moved."""

    kind: str  # ACK | FILL | REJECT | CANCELED | EXPIRED | UNKNOWN
    event_time_ms: int
    venue_order_id: str
    event_id: str
    fill: dict[str, Any] | None = None
    reason: str = ""


@dataclass
class SimulatedPaperVenue:
    """Deterministic, offline, and deliberately honest about what it is."""

    adapter_id: str = "OFFLINE_SIM_PAPER_VENUE"
    environment: str = "OFFLINE"
    venue_prefix: str = "SIM"
    _sequence: int = field(default=0, init=False)
    _emitted: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    def next_order_id(self) -> str:
        self._sequence += 1
        return f"{self.venue_prefix}-{self._sequence:06d}"

    def script_for(self, client_order_id: str, *, salt: int = 0) -> VenueScript:
        """The default script of a healthy book: one acknowledgement, one full fill.

        ``salt`` lets a caller vary the price slightly per order without randomness: the
        value is a function of its inputs, so two runs agree.
        """

        return VenueScript(price_ratio=1.0 + ((salt % 7) - 3) * 1e-6)

    def submit(
        self,
        *,
        client_order_id: str,
        ordered_qty: float,
        reference_price: float,
        submit_ms: int,
        script: VenueScript,
    ) -> list[VenueMessage]:
        """Produce the venue's answer to one submit, in delivery order."""

        venue_order_id = self.next_order_id()
        messages: list[VenueMessage] = []
        ack = VenueMessage(
            kind="ACK",
            event_time_ms=submit_ms + ACK_DELAY_MS,
            venue_order_id=venue_order_id,
            event_id=f"{client_order_id}:ACK",
        )
        if script.mode == "REJECT_AT_SUBMIT":
            messages.append(
                VenueMessage(
                    kind="REJECT",
                    event_time_ms=submit_ms + ACK_DELAY_MS,
                    venue_order_id=venue_order_id,
                    event_id=f"{client_order_id}:REJECT",
                    reason="VENUE_REJECTED",
                )
            )
            return self._deliver(messages, script)
        if script.mode == "TIMEOUT_UNKNOWN":
            messages.append(
                VenueMessage(
                    kind="UNKNOWN",
                    event_time_ms=submit_ms + ACK_DELAY_MS,
                    venue_order_id=venue_order_id,
                    event_id=f"{client_order_id}:UNKNOWN",
                    reason="ACK_TIMEOUT",
                )
            )
            return self._deliver(messages, script)

        fill_messages: list[VenueMessage] = []
        cumulative = 0.0
        tranches = script.tranches
        if script.mode == "ACK_WITHOUT_FILL":
            tranches = ()
        if script.mode == "PARTIAL_THEN_CANCEL":
            tranches = script.tranches
        for index, fraction in enumerate(tranches):
            quantity = ordered_qty * float(fraction)
            cumulative += quantity
            last = index == len(tranches) - 1
            # A tranche that does not complete the order is a partial fill; the venue can
            # only call an order FILLED when the whole quantity has traded.
            complete = bool(last and cumulative >= ordered_qty - 1e-12)
            price = float(reference_price) * float(script.price_ratio)
            fill_messages.append(
                VenueMessage(
                    kind="FILL",
                    event_time_ms=submit_ms + ACK_DELAY_MS + int(script.fill_delays_ms[index]),
                    venue_order_id=venue_order_id,
                    event_id=f"{client_order_id}:FILL:{index + 1}",
                    fill={
                        "fill_key": f"{venue_order_id}:{index + 1}",
                        "filled_quantity": quantity,
                        "fill_price": price,
                        "fee_amount": quantity * price * script.fee_bps / 10_000.0,
                        "fee_currency": "USDT",
                        "complete": complete,
                    },
                )
            )
        if script.mode == "PARTIAL_THEN_CANCEL":
            messages.append(ack)
            messages.extend(fill_messages)
            messages.append(
                VenueMessage(
                    kind="CANCELED",
                    event_time_ms=submit_ms + ACK_DELAY_MS + int(script.fill_delays_ms[-1]) + 60,
                    venue_order_id=venue_order_id,
                    event_id=f"{client_order_id}:CANCELED",
                    reason="CLIENT_CANCEL_REMAINDER",
                )
            )
            return self._deliver(messages, script)

        if script.deliver_fills_before_ack:
            messages.extend(fill_messages)
            messages.append(ack)
        else:
            messages.append(ack)
            messages.extend(fill_messages)
        return self._deliver(messages, script)

    def _deliver(
        self, messages: list[VenueMessage], script: VenueScript
    ) -> list[VenueMessage]:
        delivered = list(messages)
        if script.duplicate_last and delivered:
            delivered.append(delivered[-1])
        self._remember(delivered)
        return delivered

    def _remember(self, messages: list[VenueMessage]) -> None:
        seen: set[str] = set()
        for message in messages:
            if message.fill is None:
                continue
            if message.event_id in seen:
                # The transport delivered it twice; the venue executed it once. Its own
                # book applies each fill exactly once, like every other book must.
                continue
            seen.add(message.event_id)
            row = self._emitted.setdefault(
                message.venue_order_id,
                {"quantity": 0.0, "notional": 0.0, "fees": 0.0},
            )
            quantity = float(message.fill["filled_quantity"])
            row["quantity"] += quantity
            row["notional"] += quantity * float(message.fill["fill_price"])
            row["fees"] += float(message.fill["fee_amount"])

    def snapshot(self) -> dict[str, Any]:
        """The venue's own tally of what it says it executed.

        Computed from the messages it emitted, not from the ledger or the broker, so a
        reconciliation against it is a comparison of two independent derivations.
        """

        return {
            "adapter_id": self.adapter_id,
            "provider_environment": self.environment,
            "orders": {
                order_id: {
                    "quantity": round(value["quantity"], 12),
                    "notional": round(value["notional"], 10),
                    "fees_usdt": round(value["fees"], 10),
                }
                for order_id, value in sorted(self._emitted.items())
            },
        }


__all__ = [
    "ACK_DELAY_MS",
    "OFFLINE_FEE_BPS",
    "VENUE_MODES",
    "SimulatedPaperVenue",
    "VenueMessage",
    "VenueScript",
]
