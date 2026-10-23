"""RFC-030 §12/§13/§15/§16/§17 — short-leg cost contract and PAIR_COST_MODEL_V1.

Two rules drive this module:

* **Zero is not a default.** ``zero_borrow_forbidden = True`` for any instrument
  that requires borrow. Missing cost data is ``UNKNOWN``/``BLOCKED``, never ``0``
  (§13), so no DEV result can become economically eligible under
  ``SHORT_LEG_UNCOSTED``.
* **Borrow and funding are different economics** (§15). A SPOT/MARGIN short pays a
  borrow rate; a PERPETUAL pays funding. The model supports both but an experiment
  uses only the one its instrument contractually declares.

PAIR_COST_MODEL_V1 does **not** replace COST_MODEL_V3 globally: it consumes the
long leg's per-leg cost from the existing CostEngine/COST_MODEL_V3 (or an injected
per-leg cost function) and adds the short-leg transaction, borrow/funding and
basis economics. Every component is tagged with its evidence class
(``OBSERVED`` / ``CONFIGURED`` / ``ESTIMATED`` / ``UNKNOWN``).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .instruments import LegInstrumentContract

__all__ = [
    "PAIR_COST_MODEL_V1",
    "CostKnowledge",
    "PairCostBreakdown",
    "PairCostModelV1",
    "ShortLegCost",
]

BPS = 10_000.0


class CostKnowledge(StrEnum):
    """Evidence class of a cost component (§16)."""

    OBSERVED = "OBSERVED"
    CONFIGURED = "CONFIGURED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class ShortLegCostError(ValueError):
    """Raised when a short leg is priced with invented or missing data."""


@dataclass(frozen=True, slots=True)
class ShortLegCost:
    """§12 — the complete, timestamped short-leg cost record.

    ``UNKNOWN`` costs carry ``None`` for their numeric fields: the leg is then not
    economically executable. ``source_timestamp`` / ``availability_timestamp``
    make the record PIT-checkable: a cost observed *after* the decision time can
    never be used at that decision time.
    """

    instrument_id: str
    borrow_rate: float | None = None
    borrow_rate_unit: str = "bps_per_day"
    borrow_start: int = 0
    borrow_end: int = 0
    borrow_cost: float | None = None

    funding_rate: float | None = None
    funding_period: int = 0
    funding_cost: float | None = None

    basis_open: float | None = None
    basis_close: float | None = None
    basis_effect: float | None = None

    fees: float | None = None
    spread_cost: float | None = None
    slippage_cost: float | None = None

    total_short_cost: float | None = None

    source: str = "NONE"
    source_timestamp: int = 0
    availability_timestamp: int = 0
    fingerprint: str = ""

    @property
    def is_known(self) -> bool:
        """True only when the total short cost is a real, non-invented number."""
        return self.total_short_cost is not None

    @property
    def is_pit_safe(self) -> bool:
        """§14/§41 — availability must not be in the future relative to its source."""
        if self.availability_timestamp and self.source_timestamp:
            return self.availability_timestamp <= self.source_timestamp + 86_400_000
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "borrow_rate": self.borrow_rate,
            "borrow_rate_unit": self.borrow_rate_unit,
            "borrow_start": self.borrow_start,
            "borrow_end": self.borrow_end,
            "borrow_cost": self.borrow_cost,
            "funding_rate": self.funding_rate,
            "funding_period": self.funding_period,
            "funding_cost": self.funding_cost,
            "basis_open": self.basis_open,
            "basis_close": self.basis_close,
            "basis_effect": self.basis_effect,
            "fees": self.fees,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "total_short_cost": self.total_short_cost,
            "source": self.source,
            "source_timestamp": self.source_timestamp,
            "availability_timestamp": self.availability_timestamp,
            "fingerprint": self.fingerprint,
            "is_known": self.is_known,
        }


def _build_short_leg_cost(
    instrument: LegInstrumentContract,
    *,
    notional: float,
    holding_days: float,
    short_leg_cost: ShortLegCost | None,
    decision_time: int,
    zero_borrow_forbidden: bool = True,
) -> ShortLegCost:
    """Validate and normalise a declared short-leg cost, or fail closed.

    A short leg that requires borrow but carries no borrow evidence is returned as
    an ``UNKNOWN`` cost — never zero — and callers must refuse to execute it.
    """
    if not instrument.borrow_required and not instrument.funding_applicable:
        # A genuinely costless short (e.g. an inverse of a fully-collateralised
        # long) must still declare its transaction costs explicitly.
        if short_leg_cost is not None and short_leg_cost.is_known:
            return short_leg_cost
        raise ShortLegCostError(
            f"short leg {instrument.instrument_id!r} declares no borrow/funding but "
            "supplies no explicit transaction cost; missing cost is not zero (§13)"
        )

    if short_leg_cost is None:
        return ShortLegCost(instrument_id=instrument.instrument_id)

    if (
        zero_borrow_forbidden
        and instrument.borrow_required
        and short_leg_cost.borrow_rate is None
        and short_leg_cost.borrow_cost is None
    ):
        # Explicitly blocked: no invented zero.
        return ShortLegCost(
            instrument_id=instrument.instrument_id,
            source=short_leg_cost.source,
            source_timestamp=short_leg_cost.source_timestamp,
            availability_timestamp=short_leg_cost.availability_timestamp,
            fingerprint=short_leg_cost.fingerprint,
        )

    # PIT guard: cost evidence available after the decision cannot price it.
    if decision_time and short_leg_cost.availability_timestamp > decision_time:
        raise ShortLegCostError(
            f"short cost for {instrument.instrument_id!r} is not PIT-safe: "
            f"available {short_leg_cost.availability_timestamp} > decision {decision_time}"
        )

    borrow_cost = short_leg_cost.borrow_cost
    if borrow_cost is None and short_leg_cost.borrow_rate is not None:
        borrow_cost = short_leg_cost.borrow_rate * holding_days * notional / BPS
    # A component the instrument does not declare is exactly zero, not unknown: a
    # perpetual short has no borrow, a spot instrument has no funding/basis (§15).
    borrow_component = borrow_cost if instrument.borrow_required else 0.0

    funding_cost = short_leg_cost.funding_cost
    if (
        funding_cost is None
        and short_leg_cost.funding_rate is not None
        and short_leg_cost.funding_period > 0
    ):
        intervals = max(1.0, holding_days * 86_400_000.0 / short_leg_cost.funding_period)
        funding_cost = short_leg_cost.funding_rate * intervals * notional / BPS

    basis_effect = short_leg_cost.basis_effect
    if (
        basis_effect is None
        and short_leg_cost.basis_open is not None
        and short_leg_cost.basis_close is not None
    ):
        basis_effect = (short_leg_cost.basis_close - short_leg_cost.basis_open) * notional

    # A component the instrument does not declare is exactly zero, not unknown:
    # a spot/margin short has no funding, a spot instrument has no basis (§15).
    funding_component = funding_cost if instrument.funding_applicable else 0.0
    basis_component = basis_effect if instrument.basis_applicable else 0.0

    parts = [
        short_leg_cost.fees,
        short_leg_cost.spread_cost,
        short_leg_cost.slippage_cost,
        borrow_component,
        funding_component,
        basis_component,
    ]
    if any(p is None for p in parts):
        return ShortLegCost(
            instrument_id=instrument.instrument_id,
            borrow_rate=short_leg_cost.borrow_rate,
            borrow_rate_unit=short_leg_cost.borrow_rate_unit,
            borrow_start=short_leg_cost.borrow_start,
            borrow_end=short_leg_cost.borrow_end,
            borrow_cost=borrow_component,
            funding_rate=short_leg_cost.funding_rate,
            funding_period=short_leg_cost.funding_period,
            funding_cost=funding_component,
            basis_open=short_leg_cost.basis_open,
            basis_close=short_leg_cost.basis_close,
            basis_effect=basis_component,
            fees=short_leg_cost.fees,
            spread_cost=short_leg_cost.spread_cost,
            slippage_cost=short_leg_cost.slippage_cost,
            total_short_cost=None,
            source=short_leg_cost.source,
            source_timestamp=short_leg_cost.source_timestamp,
            availability_timestamp=short_leg_cost.availability_timestamp,
            fingerprint=short_leg_cost.fingerprint,
        )

    total = math.fsum(p for p in parts if p is not None)
    return ShortLegCost(
        instrument_id=instrument.instrument_id,
        borrow_rate=short_leg_cost.borrow_rate,
        borrow_rate_unit=short_leg_cost.borrow_rate_unit,
        borrow_start=short_leg_cost.borrow_start,
        borrow_end=short_leg_cost.borrow_end,
        borrow_cost=borrow_component,
        funding_rate=short_leg_cost.funding_rate,
        funding_period=short_leg_cost.funding_period,
        funding_cost=funding_component,
        basis_open=short_leg_cost.basis_open,
        basis_close=short_leg_cost.basis_close,
        basis_effect=basis_component,
        fees=short_leg_cost.fees,
        spread_cost=short_leg_cost.spread_cost,
        slippage_cost=short_leg_cost.slippage_cost,
        total_short_cost=total,
        source=short_leg_cost.source,
        source_timestamp=short_leg_cost.source_timestamp,
        availability_timestamp=short_leg_cost.availability_timestamp,
        fingerprint=short_leg_cost.fingerprint,
    )


@dataclass(frozen=True, slots=True)
class PairCostBreakdown:
    """§16 — component-by-component pair cost with explicit evidence classes."""

    long_cost: float | None
    short_cost: float | None
    borrow: float | None
    funding: float | None
    basis: float | None
    long_knowledge: CostKnowledge
    short_knowledge: CostKnowledge
    total_pair_cost: float | None
    economically_executable: bool
    blocked_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "long_cost": self.long_cost,
            "short_cost": self.short_cost,
            "borrow": self.borrow,
            "funding": self.funding,
            "basis": self.basis,
            "long_knowledge": self.long_knowledge.value,
            "short_knowledge": self.short_knowledge.value,
            "total_pair_cost": self.total_pair_cost,
            "economically_executable": self.economically_executable,
            "blocked_reason": self.blocked_reason,
        }


LongCostFn = Callable[[float, float], float]


@dataclass(frozen=True, slots=True)
class PairCostModelV1:
    """§16/§17 — both legs pay their own costs, independently.

    ``long_cost_fn(notional, horizon_minutes) -> usdt`` is normally the existing
    COST_MODEL_V3 evaluation for one leg; injecting it keeps V3 as the single
    authority for the long leg while this model adds the short-leg economics.
    """

    long_cost_fn: LongCostFn | None = None
    long_cost_bps: float | None = None
    long_knowledge: CostKnowledge = CostKnowledge.CONFIGURED
    zero_borrow_forbidden: bool = True
    model_version: str = "PAIR_COST_MODEL_V1"

    def long_leg_cost(self, notional: float, horizon_minutes: float) -> float:
        if self.long_cost_fn is not None:
            return float(self.long_cost_fn(notional, horizon_minutes))
        if self.long_cost_bps is not None:
            return notional * self.long_cost_bps / BPS
        raise ShortLegCostError(
            "no long-leg cost source configured; a pair cannot be priced without it"
        )

    def price_pair(
        self,
        *,
        long_instrument: LegInstrumentContract,
        short_instrument: LegInstrumentContract,
        long_notional: float,
        short_notional: float,
        holding_days: float,
        horizon_minutes: float,
        short_leg_cost: ShortLegCost | None,
        decision_time: int = 0,
    ) -> PairCostBreakdown:
        """Price both legs, charging each independently (§17)."""
        long_cost = self.long_leg_cost(long_notional, horizon_minutes)

        short = _build_short_leg_cost(
            short_instrument,
            notional=short_notional,
            holding_days=holding_days,
            short_leg_cost=short_leg_cost,
            decision_time=decision_time,
            zero_borrow_forbidden=self.zero_borrow_forbidden,
        )

        if not short.is_known:
            reason = (
                "SHORT_LEG_UNCOSTED" if short_instrument.borrow_required else "SHORT_COST_UNKNOWN"
            )
            return PairCostBreakdown(
                long_cost=long_cost,
                short_cost=None,
                borrow=short.borrow_cost,
                funding=short.funding_cost,
                basis=short.basis_effect,
                long_knowledge=self.long_knowledge,
                short_knowledge=CostKnowledge.UNKNOWN,
                total_pair_cost=None,
                economically_executable=False,
                blocked_reason=reason,
            )

        assert short.total_short_cost is not None  # guaranteed by is_known above
        short_total = float(short.total_short_cost)
        short_knowledge = (
            CostKnowledge.OBSERVED if short.source not in ("", "NONE") else CostKnowledge.CONFIGURED
        )
        total = long_cost + short_total
        return PairCostBreakdown(
            long_cost=long_cost,
            short_cost=short_total,
            borrow=short.borrow_cost,
            funding=short.funding_cost,
            basis=short.basis_effect,
            long_knowledge=self.long_knowledge,
            short_knowledge=short_knowledge,
            total_pair_cost=total,
            economically_executable=True,
            blocked_reason="",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "long_knowledge": self.long_knowledge.value,
            "long_cost_bps": self.long_cost_bps,
            "zero_borrow_forbidden": self.zero_borrow_forbidden,
        }


#: Declared singleton name (§16) — PAIR_COST_MODEL_V1 never replaces V3 globally.
PAIR_COST_MODEL_V1 = PairCostModelV1()
