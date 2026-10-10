"""FUTURES_COST_MODEL — separate from the spot model (RFC-048 §8).

The spot round trip (23.7906 bps, COST_MODEL_V3) is NOT reused here: futures
carry commissions, spread, slippage, book-depth impact, funding over the holding
period and liquidation costs, none of which the spot figure contains.

Three honest states:

``COST_KNOWN``      every required component was measured from a named snapshot
                    taken at or before the decision timestamp;
``COST_ESTIMATED``  at least one component comes from a declared assumption or a
                    venue-published schedule that was not verified against the
                    account — all assumptions are charged as costs, never as
                    income;
``COST_UNKNOWN``    a required component has no data at all. The engine refuses
                    the position; a missing cost is never a zero cost.

Funding is point-in-time: only settlements whose timestamp is at or before the
decision instant may inform the estimate. Funding that had not been published
when the decision was taken can never be used (RFC-048 §8, no look-ahead).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .contracts import CostStatus, Direction
from .instruments import InstrumentSpec

__all__ = ["CostBreakdown", "FundingContext", "FuturesCostModel"]

#: Half of the quoted spread is paid on entry and half on exit.
_SPREAD_SIDES = 2.0
#: Fees are paid on both the opening and the closing notional.
_FEE_SIDES = 2.0


def _finite_number(value: Any) -> bool:
    """True only for a real, finite number (rejects NaN/None/strings)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


@dataclass(frozen=True, slots=True)
class FundingContext:
    """Everything the funding term needs, with its point-in-time evidence."""

    interval_ms: int | None
    settlements_in_horizon: int
    #: Base case: the last funding rate published at/before the decision instant.
    observed_rate: float | None
    #: Stress case: the most adverse funding rate known at the decision instant.
    adverse_rate: float | None
    observed_at_ms: int | None
    history_points: int
    source_hash: str = ""

    @property
    def usable(self) -> bool:
        return (
            self.settlements_in_horizon > 0
            and self.observed_rate is not None
            and self.adverse_rate is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_ms": self.interval_ms,
            "settlements_in_horizon": self.settlements_in_horizon,
            "observed_rate": self.observed_rate,
            "adverse_rate": self.adverse_rate,
            "observed_at_ms": self.observed_at_ms,
            "history_points": self.history_points,
            "source_hash": self.source_hash,
            "usable": self.usable,
        }


def funding_context(
    *,
    funding_observations: list[dict[str, Any]],
    decision_timestamp_ms: int,
    instrument: InstrumentSpec,
    horizon_minutes: float,
    source_hash: str = "",
) -> FundingContext:
    """Build the PIT funding context for a holding horizon.

    Only observations with ``funding_time_ms <= decision_timestamp_ms`` are
    visible. The adverse rate is the worst rate of the same sign as what a
    position of each direction could POSSIBLY pay; it is returned unsigned and
    the caller applies it against the position's direction.
    """
    visible = [
        o
        for o in funding_observations
        if _finite_number(o.get("funding_time_ms"))
        and _finite_number(o.get("funding_rate"))
        and int(o["funding_time_ms"]) <= decision_timestamp_ms
    ]
    interval = instrument.funding_interval_ms
    if interval is None:
        # Without a funding interval the number of settlements inside the
        # horizon cannot be established at all: the funding term is unmeasurable.
        return FundingContext(
            interval_ms=None,
            settlements_in_horizon=0,
            observed_rate=None,
            adverse_rate=None,
            observed_at_ms=None,
            history_points=len(visible),
            source_hash=source_hash,
        )
    settlements = int(horizon_minutes * 60_000 // interval)
    if not visible:
        # The interval is known, so the settlement COUNT is contractual, but no
        # rate was published at the decision instant: the cost is unknown and
        # must be refused, never zeroed.
        return FundingContext(
            interval_ms=interval,
            settlements_in_horizon=settlements,
            observed_rate=None,
            adverse_rate=None,
            observed_at_ms=None,
            history_points=0,
            source_hash=source_hash,
        )
    last = max(visible, key=lambda o: int(o["funding_time_ms"]))
    rates = [float(o["funding_rate"]) for o in visible]
    adverse = max(abs(r) for r in rates)
    return FundingContext(
        interval_ms=interval,
        settlements_in_horizon=settlements,
        observed_rate=float(last["funding_rate"]),
        adverse_rate=adverse,
        observed_at_ms=int(last["funding_time_ms"]),
        history_points=len(visible),
        source_hash=source_hash,
    )


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Round-trip cost of a simulated position, component by component."""

    status: CostStatus
    notional: float
    entry_fee_usdt: float
    exit_fee_usdt: float
    spread_cost_usdt: float
    slippage_usdt: float
    impact_entry_usdt: float
    impact_exit_usdt: float
    funding_usdt: float
    funding_expected_usdt: float
    liquidation_fee_usdt: float | None
    total_round_trip_usdt: float
    total_round_trip_bps: float
    #: Worst case of a NORMAL round trip: fees + spread + adverse slippage +
    #: impact + adverse funding, at the stress slippage assumption. It excludes
    #: the liquidation fee, which belongs to the liquidation scenario and is
    #: charged there (into the liquidation price and the stress buffer) so it is
    #: not counted twice.
    worst_case_cost_usdt: float
    worst_case_cost_bps: float
    #: Cost of the catastrophic path: adverse funding plus the venue's
    #: liquidation fee. Reported, and charged by the margin model, never by the
    #: ordinary sizer.
    liquidation_scenario_cost_usdt: float
    unknown_components: tuple[str, ...] = ()
    estimated_components: tuple[str, ...] = ()
    known_components: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "notional": self.notional,
            "entry_fee_usdt": self.entry_fee_usdt,
            "exit_fee_usdt": self.exit_fee_usdt,
            "spread_cost_usdt": self.spread_cost_usdt,
            "slippage_usdt": self.slippage_usdt,
            "impact_entry_usdt": self.impact_entry_usdt,
            "impact_exit_usdt": self.impact_exit_usdt,
            "funding_usdt": self.funding_usdt,
            "funding_expected_usdt": self.funding_expected_usdt,
            "liquidation_fee_usdt": self.liquidation_fee_usdt,
            "total_round_trip_usdt": self.total_round_trip_usdt,
            "total_round_trip_bps": self.total_round_trip_bps,
            "worst_case_cost_usdt": self.worst_case_cost_usdt,
            "worst_case_cost_bps": self.worst_case_cost_bps,
            "liquidation_scenario_cost_usdt": self.liquidation_scenario_cost_usdt,
            "unknown_components": list(self.unknown_components),
            "estimated_components": list(self.estimated_components),
            "known_components": list(self.known_components),
            "notes": list(self.notes),
        }


class FuturesCostModel:
    """Charges commission, spread, slippage, impact and funding on a notional."""

    def __init__(self, spec: InstrumentSpec, *, spread_bps: float | None) -> None:
        self._spec = spec
        self._spread_bps = spread_bps

    # -- book depth impact ---------------------------------------------------

    def depth_impact_bps(
        self, *, notional: float, side: Direction, depth: dict[str, Any] | None
    ) -> float | None:
        """Average price impact of consuming ``notional`` from the visible book.

        Returns ``None`` when the visible book cannot absorb the notional: an
        extrapolated impact would be invented data, so the cost model reports it
        as unknown and the engine refuses the position.
        """
        if not depth or notional <= 0:
            return None
        levels = depth.get("asks" if side is Direction.LONG else "bids") or []
        remaining = notional
        consumed_notional = 0.0
        consumed_qty = 0.0
        for price, size in levels:
            level_price = float(price)
            level_qty = float(size)
            if (
                not math.isfinite(level_price)
                or not math.isfinite(level_qty)
                or level_price <= 0
                or level_qty <= 0
            ):
                # A level the model cannot read is not a level it may ignore:
                # an unreadable book means the impact is unknown, and an unknown
                # cost is refused by the engine. (RFC-048V DEF-048V-04.)
                return None
            level_notional = level_price * level_qty
            take = min(remaining, level_notional)
            consumed_qty += take / level_price
            consumed_notional += take
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0 or consumed_qty <= 0:
            return None
        vwap = consumed_notional / consumed_qty
        best = float(levels[0][0])
        if not math.isfinite(vwap) or not math.isfinite(best) or best <= 0:
            return None
        return abs(vwap - best) / best * 10_000.0

    # -- the model -----------------------------------------------------------

    def compute(
        self,
        *,
        notional: float,
        direction: Direction,
        horizon_minutes: float,
        funding: FundingContext,
        depth: dict[str, Any] | None,
        slippage_bps: float | None,
        stress_slippage_bps: float | None,
        maker: bool = False,
    ) -> CostBreakdown:
        unknown: list[str] = []
        estimated: list[str] = []
        known: list[str] = []
        notes: list[str] = []

        if notional <= 0:
            return CostBreakdown(
                status=CostStatus.COST_UNKNOWN,
                notional=notional,
                entry_fee_usdt=0.0,
                exit_fee_usdt=0.0,
                spread_cost_usdt=0.0,
                slippage_usdt=0.0,
                impact_entry_usdt=0.0,
                impact_exit_usdt=0.0,
                funding_usdt=0.0,
                funding_expected_usdt=0.0,
                liquidation_fee_usdt=None,
                total_round_trip_usdt=0.0,
                total_round_trip_bps=0.0,
                worst_case_cost_usdt=0.0,
                worst_case_cost_bps=0.0,
                liquidation_scenario_cost_usdt=0.0,
                unknown_components=("notional",),
                notes=("a non-positive notional has no meaningful cost",),
            )

        # -- commissions
        fee_bps = self._spec.maker_bps if maker else self._spec.taker_bps
        if fee_bps is None:
            unknown.append("commission")
        else:
            if self._spec.fee_verified:
                known.append("commission")
            else:
                estimated.append("commission")
                notes.append(f"commission from published schedule: {self._spec.fee_source}")

        entry_fee_usdt = notional * (fee_bps or 0.0) / 10_000.0
        exit_fee_usdt = entry_fee_usdt

        # -- spread
        if self._spread_bps is None or not math.isfinite(self._spread_bps):
            unknown.append("spread")
            spread_cost = 0.0
        else:
            spread_cost = notional * self._spread_bps / 10_000.0 * _SPREAD_SIDES
            known.append("spread")

        # -- slippage (assumption) and impact (measured from the book)
        if slippage_bps is None or not math.isfinite(slippage_bps):
            unknown.append("slippage")
            slippage = 0.0
        else:
            slippage = notional * slippage_bps / 10_000.0 * 2.0
            estimated.append("slippage")

        # Entering consumes the book on the entry side; closing consumes it on
        # the opposite side (closing a long is a sell), so both are measured.
        exit_side = Direction.SHORT if direction is Direction.LONG else Direction.LONG
        impact_entry_bps = self.depth_impact_bps(notional=notional, side=direction, depth=depth)
        impact_exit_bps = self.depth_impact_bps(notional=notional, side=exit_side, depth=depth)
        if impact_entry_bps is None or impact_exit_bps is None:
            unknown.append("market_impact")
            impact_entry = 0.0
            impact_exit = 0.0
        else:
            impact_entry = notional * impact_entry_bps / 10_000.0
            impact_exit = notional * impact_exit_bps / 10_000.0
            known.append("market_impact")

        # -- funding (point in time)
        if funding.interval_ms is not None and funding.settlements_in_horizon == 0:
            # The venue's own funding interval proves no settlement can occur
            # inside this horizon: a zero funding cost here is a contractual
            # fact, not missing data.
            funding_paid = 0.0
            funding_expected = 0.0
            known.append("funding")
            notes.append(
                "no funding settlement inside the horizon (interval "
                f"{funding.interval_ms} ms > horizon)"
            )
        elif not funding.usable:
            unknown.append("funding")
            funding_paid = 0.0
            funding_expected = 0.0
            notes.append("funding history is not visible at the decision instant")
        else:
            observed = float(funding.observed_rate or 0.0)
            adverse = float(funding.adverse_rate or 0.0)
            # A long pays a positive rate; a short receives it. Only the payment
            # side is charged; a receipt is never counted as income.
            expected_rate = observed if direction is Direction.LONG else -observed
            funding_expected = (
                notional * expected_rate * funding.settlements_in_horizon
                if expected_rate > 0
                else 0.0
            )
            funding_paid = notional * adverse * funding.settlements_in_horizon
            known.append("funding")

        # -- liquidation cost (a stress term, not a routine cost)
        liquidation_fee = (
            None
            if self._spec.liquidation_fee_rate is None
            else notional * self._spec.liquidation_fee_rate
        )
        if liquidation_fee is None:
            unknown.append("liquidation_fee")
        else:
            known.append("liquidation_fee")

        total = (
            entry_fee_usdt
            + exit_fee_usdt
            + spread_cost
            + slippage
            + impact_entry
            + impact_exit
            + funding_expected
        )
        worst = total - funding_expected + funding_paid
        if (
            stress_slippage_bps is not None
            and math.isfinite(stress_slippage_bps)
            and slippage_bps is not None
            and math.isfinite(slippage_bps)
        ):
            worst += notional * (stress_slippage_bps - slippage_bps) / 10_000.0 * 2.0
        liquidation_scenario = funding_paid + (liquidation_fee or 0.0)

        status = (
            CostStatus.COST_UNKNOWN
            if unknown
            else (CostStatus.COST_ESTIMATED if estimated else CostStatus.COST_KNOWN)
        )
        return CostBreakdown(
            status=status,
            notional=notional,
            entry_fee_usdt=entry_fee_usdt,
            exit_fee_usdt=exit_fee_usdt,
            spread_cost_usdt=spread_cost,
            slippage_usdt=slippage,
            impact_entry_usdt=impact_entry,
            impact_exit_usdt=impact_exit,
            funding_usdt=funding_paid,
            funding_expected_usdt=funding_expected,
            liquidation_fee_usdt=liquidation_fee,
            total_round_trip_usdt=total,
            total_round_trip_bps=total / notional * 10_000.0,
            worst_case_cost_usdt=worst,
            worst_case_cost_bps=worst / notional * 10_000.0,
            liquidation_scenario_cost_usdt=liquidation_scenario,
            unknown_components=tuple(dict.fromkeys(unknown)),
            estimated_components=tuple(dict.fromkeys(estimated)),
            known_components=tuple(dict.fromkeys(known)),
            notes=tuple(notes),
        )
