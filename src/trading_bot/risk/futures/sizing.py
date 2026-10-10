"""Risk-bounded position sizing (RFC-048 §5).

The conceptual constraint is

    EXPECTED_STOP_LOSS_WITH_COSTS <= RISK_BUDGET

and a stop is NOT an execution guarantee, so the modelled worst loss includes the
cost of the round trip, adverse slippage and an explicit gap reserve. Dividing
equity by the stop distance is exactly the mistake this module exists to prevent.

Three invariants are enforced by construction and pinned by tests:

1. rounding to the quantity step only ever REDUCES the size;
2. a larger worst-case cost can never produce a larger approved notional;
3. the modelled worst loss of the result never exceeds the risk budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .contracts import CostStatus, Direction, RejectionCode
from .costs import CostBreakdown
from .instruments import InstrumentSpec

__all__ = ["SizingResult", "risk_bounded_sizing"]


@dataclass(frozen=True, slots=True)
class SizingResult:
    """Outcome of a sizing attempt. ``approved`` is False on any refusal."""

    approved: bool
    quantity: float
    notional: float
    risk_budget: float
    modeled_worst_loss: float
    worst_loss_per_unit: float
    stop_distance_pct: float
    gap_reserve_usdt: float
    cost_usdt: float
    reasons: tuple[RejectionCode, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "quantity": self.quantity,
            "notional": self.notional,
            "risk_budget": self.risk_budget,
            "modeled_worst_loss": self.modeled_worst_loss,
            "worst_loss_per_unit": self.worst_loss_per_unit,
            "stop_distance_pct": self.stop_distance_pct,
            "gap_reserve_usdt": self.gap_reserve_usdt,
            "cost_usdt": self.cost_usdt,
            "reasons": [r.value for r in self.reasons],
            "notes": list(self.notes),
        }


def risk_bounded_sizing(
    *,
    spec: InstrumentSpec,
    direction: Direction,
    entry_price: float,
    stop_price: float | None,
    equity: float,
    risk_budget: float,
    costs: CostBreakdown,
    gap_reserve_pct: float | None,
    requested_notional: float | None = None,
) -> SizingResult:
    """Size the position so that the modelled worst loss fits the risk budget."""
    notes: list[str] = []
    reasons: list[RejectionCode] = []

    if equity <= 0 or risk_budget <= 0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=0.0,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.INSUFFICIENT_EQUITY,),
            notes=("equity and risk budget must be positive",),
        )
    if entry_price <= 0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=0.0,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.MISSING_MARK_PRICE,),
            notes=("entry price must be positive",),
        )
    if stop_price is None:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=0.0,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.STOP_MISSING,),
            notes=("a futures position without an invalidation price is refused",),
        )
    if gap_reserve_pct is None or gap_reserve_pct < 0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=0.0,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.GAP_RESERVE_MISSING,),
            notes=(
                "no justifiable slippage/gap reserve was supplied: refusing rather "
                "than assuming the stop is a guaranteed fill",
            ),
        )
    if costs.status is CostStatus.COST_UNKNOWN:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=0.0,
            gap_reserve_usdt=0.0,
            cost_usdt=0.0,
            reasons=(RejectionCode.COST_UNKNOWN,),
            notes=(f"unknown cost components: {list(costs.unknown_components)}",),
        )

    stop_distance = _stop_distance(direction=direction, entry=entry_price, stop=stop_price)
    if stop_distance <= 0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=0.0,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.STOP_TOO_CLOSE,),
            notes=("stop is on the wrong side of entry or coincides with it",),
        )

    stop_distance_pct = stop_distance / entry_price
    # Per-unit worst loss: the stop distance, plus the gap/slippage reserve (the
    # stop may trade far worse than its level), plus the round-trip cost of the
    # unit itself. Costs scale with the notional, which scales with quantity; the
    # cost-per-unit term is therefore evaluated at the candidate notional below
    # and re-checked against the budget (no circularity: both bounds are exact).
    gap_reserve_per_unit = entry_price * gap_reserve_pct
    worst_loss_per_unit = stop_distance + gap_reserve_per_unit
    if worst_loss_per_unit <= 0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=0.0,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.STOP_TOO_CLOSE,),
            notes=("worst loss per unit is not positive",),
        )

    # Quantity bounded above by the risk budget; the cost term is proportional to
    # the notional, so it is charged as bps of the notional in the denominator.
    cost_bps = costs.worst_case_cost_bps / 10_000.0
    if cost_bps >= 1.0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=worst_loss_per_unit,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.RISK_BUDGET_EXCEEDED,),
            notes=("round-trip cost alone consumes the risk budget",),
        )
    quantity = risk_budget / (worst_loss_per_unit + entry_price * cost_bps)
    quantity = spec.round_quantity_down(quantity)
    notes.append("quantity floored to the venue step; rounding never increases risk")

    if quantity <= 0:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=worst_loss_per_unit,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.BELOW_MIN_NOTIONAL,),
            notes=(*notes, "risk budget is smaller than one quantity step"),
        )

    if spec.quantity_min and quantity < spec.quantity_min:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=worst_loss_per_unit,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.BELOW_MIN_NOTIONAL,),
            notes=(*notes, f"quantity below venue minimum {spec.quantity_min}"),
        )
    if spec.quantity_max is not None and quantity > spec.quantity_max:
        quantity = spec.round_quantity_down(spec.quantity_max)
        notes.append(f"quantity capped at the venue maximum {spec.quantity_max}")

    notional = quantity * entry_price
    if requested_notional is not None and requested_notional > 0 and notional > requested_notional:
        # The proposal asked for less than the risk budget would allow: honour the
        # request (never inflate a position because the budget is generous).
        quantity = spec.round_quantity_down(requested_notional / entry_price)
        notional = quantity * entry_price
        notes.append("notional clipped to the requested notional")

    if notional < spec.minimum_notional:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=worst_loss_per_unit,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.BELOW_MIN_NOTIONAL,),
            notes=(
                *notes,
                f"notional {notional:.4f} below venue minimum {spec.minimum_notional}",
            ),
        )
    if spec.maximum_notional is not None and notional > spec.maximum_notional:
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=worst_loss_per_unit,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.ABOVE_MAX_NOTIONAL,),
            notes=(*notes, "notional above the instrument maximum"),
        )

    # Cost is charged on the realised notional, and the budget re-checked.
    realised_cost = costs.worst_case_cost_bps / 10_000.0 * notional
    modeled_worst_loss = notional * stop_distance_pct + notional * gap_reserve_pct + realised_cost
    if modeled_worst_loss > risk_budget + 1e-9:
        # Shrink once, monotonically, and never grow back.
        excess_ratio = risk_budget / modeled_worst_loss
        quantity = spec.round_quantity_down(quantity * excess_ratio)
        notional = quantity * entry_price
        realised_cost = costs.worst_case_cost_bps / 10_000.0 * notional
        modeled_worst_loss = (
            notional * stop_distance_pct + notional * gap_reserve_pct + realised_cost
        )
        notes.append("size reduced after the post-rounding budget re-check")
        if quantity <= 0 or notional < spec.minimum_notional or (
            spec.quantity_min and quantity < spec.quantity_min
        ):
            return SizingResult(
                approved=False,
                quantity=0.0,
                notional=0.0,
                risk_budget=risk_budget,
                modeled_worst_loss=0.0,
                worst_loss_per_unit=worst_loss_per_unit,
                stop_distance_pct=stop_distance_pct,
                gap_reserve_usdt=0.0,
                cost_usdt=costs.worst_case_cost_usdt,
                reasons=(RejectionCode.BELOW_MIN_NOTIONAL,),
                notes=(*notes, "no size both inside the budget and above the venue minimum"),
            )
        if modeled_worst_loss > risk_budget + 1e-9:
            return SizingResult(
                approved=False,
                quantity=0.0,
                notional=0.0,
                risk_budget=risk_budget,
                modeled_worst_loss=modeled_worst_loss,
                worst_loss_per_unit=worst_loss_per_unit,
                stop_distance_pct=stop_distance_pct,
                gap_reserve_usdt=notional * gap_reserve_pct,
                cost_usdt=realised_cost,
                reasons=(RejectionCode.RISK_BUDGET_EXCEEDED,),
                notes=(*notes, "the discrete quantity step cannot fit the budget"),
            )

    if not math.isfinite(modeled_worst_loss) or not math.isfinite(notional):
        return SizingResult(
            approved=False,
            quantity=0.0,
            notional=0.0,
            risk_budget=risk_budget,
            modeled_worst_loss=0.0,
            worst_loss_per_unit=worst_loss_per_unit,
            stop_distance_pct=stop_distance_pct,
            gap_reserve_usdt=0.0,
            cost_usdt=costs.worst_case_cost_usdt,
            reasons=(RejectionCode.RISK_BUDGET_EXCEEDED,),
            notes=(*notes, "non-finite sizing arithmetic"),
        )

    return SizingResult(
        approved=True,
        quantity=quantity,
        notional=notional,
        risk_budget=risk_budget,
        modeled_worst_loss=modeled_worst_loss,
        worst_loss_per_unit=worst_loss_per_unit,
        stop_distance_pct=stop_distance_pct,
        gap_reserve_usdt=notional * gap_reserve_pct,
        cost_usdt=realised_cost,
        reasons=tuple(reasons),
        notes=tuple(notes),
    )


def _stop_distance(*, direction: Direction, entry: float, stop: float) -> float:
    """Distance to the stop in price units; <= 0 when the stop is malformed."""
    if direction is Direction.LONG:
        return entry - stop
    return stop - entry
