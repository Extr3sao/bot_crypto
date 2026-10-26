"""Deterministic classification of live orders for authorisation.

P0 introduced ``_live_order_boundary(opens_risk=...)``. The boolean was supplied
by the call site, so the exemption from the live gate was a claim about a name —
``close-position``, ``sell``, ``--trade-side CLOSE`` — not about an order the
venue can be proven to treat as a reduction. DEF-EXEC-003 is that gap.

This module replaces the claim with a derivation:

* ``OPEN_OR_INCREASE`` — the order can open, add to or reverse exposure;
* ``PROVEN_REDUCTION`` — the venue itself enforces the reduction, and the
  position it acts on exists, is fresh, is one-way, is on the opposite side and
  is at least as large as the order;
* ``UNKNOWN`` — anything not proven. It is **not** exempt: it takes the same
  confirmation, hot-stop and ten gate checks as an opening order.

Only two shapes can be proven with the current adapters:

1. ``place_order(trade_side="CLOSE", reduce_only=True, position_id=...)`` on a
   futures venue that propagates ``reduceOnly`` to the wire payload;
2. ``flash_close_position(position_id)``, whose payload has no side or size.

Spot sells have no reduce-only primitive, and ``place_position_tpsl`` has no
side and no ``reduceOnly``; the positions endpoint does not return the current
TP/SL, so no code can prove that a TP/SL change tightens protection. Both are
``UNKNOWN`` by construction.

The classification is a *precondition*. Because the proof is about the final
wire payload, ``build_reduction_payload_guard`` re-checks that payload inside
the adapter, immediately before the HTTP request. A reduction whose payload
loses ``reduceOnly`` or gains a side is refused with zero broker calls.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final


class OrderCategory(StrEnum):
    """What an order can do to exposure."""

    OPEN_OR_INCREASE = "OPEN_OR_INCREASE"
    PROVEN_REDUCTION = "PROVEN_REDUCTION"
    UNKNOWN = "UNKNOWN"


class OrderPrimitive(StrEnum):
    """The adapter call that will leave the process."""

    FUTURES_PLACE_ORDER = "futures.place_order"
    FUTURES_FLASH_CLOSE = "futures.flash_close_position"
    FUTURES_TP_SL = "futures.place_position_tpsl"
    SPOT_PLACE_ORDER = "spot.place_spot_order"
    CONNECTOR_CREATE_ORDER = "connector.create_order"

    @property
    def market_kind(self) -> str:
        if self in {
            OrderPrimitive.SPOT_PLACE_ORDER,
            OrderPrimitive.CONNECTOR_CREATE_ORDER,
        }:
            return "spot"
        return "futures"


@dataclass(frozen=True, slots=True)
class VenueCapabilities:
    """What an adapter actually sends, not what its documentation claims."""

    venue: str
    supports_reduce_only: bool
    supports_flash_close: bool


#: ``BitunixFuturesClient.place_order`` always emits both ``tradeSide`` and
#: ``reduceOnly``; ``flash_close_position`` has its own endpoint.
BITUNIX_FUTURES: Final[VenueCapabilities] = VenueCapabilities(
    venue="bitunix-futures", supports_reduce_only=True, supports_flash_close=True
)

#: The spot adapter has no reduce-only flag and no position object. A sell can
#: only sell inventory, but nothing in the payload makes the venue enforce it,
#: so it is not proof under REQ-03.
BITUNIX_SPOT: Final[VenueCapabilities] = VenueCapabilities(
    venue="bitunix-spot", supports_reduce_only=False, supports_flash_close=False
)

#: ``MultiExchangeConnector.create_order`` is exchange-neutral and exposes no
#: reduce-only capability. Only buys use it today.
CONNECTOR: Final[VenueCapabilities] = VenueCapabilities(
    venue="multi-exchange-connector", supports_reduce_only=False, supports_flash_close=False
)

#: A position read older than this is not evidence. The gate and the stop are
#: the authority; the snapshot is only a precondition for the exemption.
MAX_POSITION_AGE_SECONDS: Final[float] = 30.0

#: Entrypoints whose invocation is a live dispatch. They must carry the
#: operator's explicit consent into the sink; repair commands
#: (``close-position``, ``set-tpsl``) do not, because the command itself is the
#: explicit act and the gate still applies to anything unproven.
CONFIRMATION_REQUIRED_ENTRYPOINTS: Final[frozenset[str]] = frozenset({"run", "place-order"})

_QTY_EPSILON: Final[float] = 1e-12


def _symbol_key(value: str) -> str:
    return value.upper().replace("/", "").replace(":USDT", "")


@dataclass(frozen=True, slots=True)
class PositionState:
    """The position an order would act on, as read by the caller."""

    position_id: str
    symbol: str
    side: str
    qty: float
    position_mode: str
    observed_at: float

    @property
    def closing_side(self) -> str:
        return "SELL" if self.side.upper() == "BUY" else "BUY"

    def is_fresh(self, now: float, max_age_seconds: float = MAX_POSITION_AGE_SECONDS) -> bool:
        age = now - self.observed_at
        return 0.0 <= age <= max_age_seconds


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Typed description of the order, independent of the command that asked."""

    entrypoint: str
    primitive: OrderPrimitive
    symbol: str
    side: str
    qty: float
    trade_side: str | None = None
    reduce_only: bool = False
    position_id: str | None = None
    order_type: str = "MARKET"
    changes_protection: bool = False

    @property
    def market_kind(self) -> str:
        return self.primitive.market_kind

    @property
    def requires_confirmation(self) -> bool:
        return self.entrypoint in CONFIRMATION_REQUIRED_ENTRYPOINTS


@dataclass(frozen=True, slots=True)
class OrderDecision:
    """The category, the rule that produced it and the evidence it used."""

    category: OrderCategory
    rule: str
    reason: str
    position: PositionState | None = None

    @property
    def exempt_from_opening_gate(self) -> bool:
        return self.category is OrderCategory.PROVEN_REDUCTION


def classify_order(
    intent: OrderIntent,
    *,
    position: PositionState | None,
    capabilities: VenueCapabilities,
    now: float,
) -> OrderDecision:
    """Derive the category. Never raise: an unreadable input is ``UNKNOWN``."""

    if intent.changes_protection or intent.primitive is OrderPrimitive.FUTURES_TP_SL:
        # REQ-04. `get_pending_positions` does not return the live TP/SL levels,
        # so "this change tightens protection" is not checkable. Removing or
        # loosening a stop can increase risk without changing size.
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-TPSL-NOT-MONOTONIC",
            "protective change cannot be proven to tighten protection",
        )

    if intent.primitive in {
        OrderPrimitive.SPOT_PLACE_ORDER,
        OrderPrimitive.CONNECTOR_CREATE_ORDER,
    }:
        if intent.side.upper() == "SELL":
            return OrderDecision(
                OrderCategory.UNKNOWN,
                "R-SPOT-SELL-NO-VENUE-PROOF",
                "spot sell has no broker-enforced reduction primitive",
            )
        return OrderDecision(
            OrderCategory.OPEN_OR_INCREASE,
            "R-SPOT-BUY",
            "spot buy acquires exposure",
        )

    if intent.primitive is OrderPrimitive.FUTURES_FLASH_CLOSE:
        return _classify_flash_close(intent, position=position, capabilities=capabilities, now=now)

    return _classify_futures_place_order(
        intent, position=position, capabilities=capabilities, now=now
    )


def _classify_flash_close(
    intent: OrderIntent,
    *,
    position: PositionState | None,
    capabilities: VenueCapabilities,
    now: float,
) -> OrderDecision:
    if not capabilities.supports_flash_close:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-FLASH-UNSUPPORTED", "venue has no flash-close primitive"
        )
    if position is None:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-FLASH-NO-POSITION", "position being closed is not observable"
        )
    if _symbol_key(intent.symbol) != _symbol_key(position.symbol):
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-FLASH-SYMBOL-MISMATCH", "symbol does not match the position"
        )
    if intent.position_id and position.position_id != intent.position_id:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-FLASH-ID-MISMATCH", "observed position id does not match"
        )
    if position.qty <= 0:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-FLASH-ZERO-POSITION", "position has no size to close"
        )
    if not position.is_fresh(now):
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-FLASH-STALE", "position snapshot is older than the window"
        )
    # The payload is `{positionId}` only: there is no side or size to mutate into
    # an opening order, and the endpoint closes exactly that position.
    return OrderDecision(
        OrderCategory.PROVEN_REDUCTION,
        "R-FLASH-CLOSE",
        "venue closes the identified position by id",
        position,
    )


def _classify_futures_place_order(
    intent: OrderIntent,
    *,
    position: PositionState | None,
    capabilities: VenueCapabilities,
    now: float,
) -> OrderDecision:
    trade_side = (intent.trade_side or "").upper()
    if trade_side != "CLOSE":
        if intent.reduce_only:
            return OrderDecision(
                OrderCategory.UNKNOWN,
                "R-CLOSE-WRONG-TRADE-SIDE",
                "reduceOnly without tradeSide=CLOSE is not a proven reduction",
            )
        return OrderDecision(OrderCategory.OPEN_OR_INCREASE, "R-OPEN", "tradeSide is not CLOSE")
    if not intent.reduce_only:
        # T07: `tradeSide=CLOSE` alone is a label, not a venue guarantee.
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-CLOSE-NO-REDUCE-ONLY",
            "tradeSide=CLOSE without reduceOnly is not enforced by the venue",
        )
    if not capabilities.supports_reduce_only:
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-VENUE-NO-REDUCE-ONLY",
            "venue adapter does not propagate reduceOnly",
        )
    if not intent.position_id:
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-CLOSE-NO-POSITION-ID",
            "close order does not name the position it reduces",
        )
    if position is None:
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-CLOSE-NO-POSITION",
            "position being reduced is not observable",
        )
    if position.position_id != intent.position_id:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-CLOSE-ID-MISMATCH", "observed position id does not match"
        )
    if _symbol_key(position.symbol) != _symbol_key(intent.symbol):
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-CLOSE-SYMBOL-MISMATCH", "symbol does not match the position"
        )
    if not position.is_fresh(now):
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-CLOSE-STALE", "position snapshot is older than the window"
        )
    if position.position_mode.upper() != "ONE_WAY":
        # Hedge mode makes "sell" ambiguous without a positionSide the adapter
        # does not send. Ambiguity is UNKNOWN, never an exemption.
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-CLOSE-HEDGE-AMBIGUOUS",
            "position mode is not a verified one-way account",
        )
    if position.qty <= 0:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-CLOSE-ZERO-POSITION", "position has no size to reduce"
        )
    if intent.side.upper() != position.closing_side:
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-CLOSE-WRONG-SIDE",
            "side would add to or reverse the position",
        )
    if intent.qty <= 0:
        return OrderDecision(
            OrderCategory.UNKNOWN, "R-CLOSE-QTY-INVALID", "quantity is not positive"
        )
    if intent.qty > position.qty + _QTY_EPSILON:
        return OrderDecision(
            OrderCategory.UNKNOWN,
            "R-CLOSE-QTY-EXCESS",
            "quantity exceeds the position it claims to reduce",
        )
    return OrderDecision(
        OrderCategory.PROVEN_REDUCTION,
        "R-REDUCE-ONLY",
        "reduceOnly + CLOSE + matching one-way position",
        position,
    )


def is_definitely_opening(intent: OrderIntent) -> bool:
    """Cheap pre-classification for the CLI's fail-fast gate check.

    The sink re-classifies with the real position; this only decides whether to
    show the operator a refusal before an exchange client is constructed.
    """

    if intent.changes_protection or intent.primitive is OrderPrimitive.FUTURES_TP_SL:
        return False
    if intent.primitive in {
        OrderPrimitive.SPOT_PLACE_ORDER,
        OrderPrimitive.CONNECTOR_CREATE_ORDER,
    }:
        return intent.side.upper() == "BUY"
    if intent.primitive is OrderPrimitive.FUTURES_FLASH_CLOSE:
        return False
    return (intent.trade_side or "").upper() != "CLOSE" or not intent.reduce_only


class LiveOrderAuthorizationError(RuntimeError):
    """The final payload no longer matches the reduction that was authorised."""

    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("live order payload is not a proven reduction: " + ", ".join(violations))


def reduction_payload_violations(
    *,
    intent: OrderIntent,
    payload: Mapping[str, Any],
    position: PositionState,
) -> tuple[str, ...]:
    """Check the wire payload at the last point before the HTTP request.

    This is deliberately about the payload, not the intent: an adapter that
    drops ``reduceOnly``, rewrites ``tradeSide`` or injects a side must not
    inherit the exemption its caller was granted.
    """

    violations: list[str] = []

    if intent.primitive is OrderPrimitive.FUTURES_FLASH_CLOSE:
        unexpected = set(payload) - {"positionId"}
        if unexpected:
            violations.append("flash_close_extra_fields:" + ",".join(sorted(unexpected)))
        if str(payload.get("positionId", "")) != position.position_id:
            violations.append("flash_close_position_id_mismatch")
        return tuple(violations)

    if intent.primitive is not OrderPrimitive.FUTURES_PLACE_ORDER:
        return ("not_a_reduction_primitive",)

    if payload.get("reduceOnly") is not True:
        violations.append("reduce_only_not_true")
    if str(payload.get("tradeSide", "")).upper() != "CLOSE":
        violations.append("trade_side_not_close")
    if str(payload.get("side", "")).upper() != position.closing_side:
        violations.append("side_does_not_close_position")
    if str(payload.get("positionId", "")) != position.position_id:
        violations.append("position_id_mismatch")
    if payload.get("positionSide") not in (None, ""):
        violations.append("unexpected_position_side")

    try:
        payload_qty = float(payload.get("qty", "nan"))
    except (TypeError, ValueError):
        payload_qty = math.nan
    if not math.isfinite(payload_qty) or payload_qty <= 0:
        violations.append("payload_qty_invalid")
    elif payload_qty > position.qty + _QTY_EPSILON:
        violations.append("payload_qty_exceeds_position")
    elif abs(payload_qty - intent.qty) > _QTY_EPSILON:
        violations.append("payload_qty_differs_from_authorised_intent")

    return tuple(violations)


def build_reduction_payload_guard(
    *,
    intent: OrderIntent,
    position: PositionState,
) -> Callable[[dict[str, Any]], None]:
    """Return the guard the adapter calls immediately before the request."""

    def guard(payload: dict[str, Any]) -> None:
        violations = reduction_payload_violations(intent=intent, payload=payload, position=position)
        if violations:
            raise LiveOrderAuthorizationError(violations)

    return guard


__all__ = [
    "BITUNIX_FUTURES",
    "BITUNIX_SPOT",
    "CONFIRMATION_REQUIRED_ENTRYPOINTS",
    "CONNECTOR",
    "MAX_POSITION_AGE_SECONDS",
    "LiveOrderAuthorizationError",
    "OrderCategory",
    "OrderDecision",
    "OrderIntent",
    "OrderPrimitive",
    "PositionState",
    "VenueCapabilities",
    "build_reduction_payload_guard",
    "classify_order",
    "is_definitely_opening",
    "reduction_payload_violations",
]
