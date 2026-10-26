"""EDGE-01 cost plane — one venue, components visible, nothing hardcoded.

The candidates trade **Binance spot** (``BINANCE_SPOT_STANDARD_TAKER``, VIP0
taker), which is the venue the runtime itself models, so the fee/spread/slippage
plane is read from ``COST_MODEL_V3`` instead of being typed into the research
code. A commission model from another product (futures maker rebates, BNB
discounts, a different tier) is never carried over: the scenario id is explicit
in every artefact.

Two stress variants are derived from the same components, never from fresh
assumptions:

* ``2X_FEES``   — the fee component doubled (a tier change or taker/maker slip);
* ``ADVERSE``   — fees doubled and slippage/impact tripled (thin book).

``round_trip_bps`` is always re-derived as the sum of the scaled components, so
a scenario cannot disagree with its own parts.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_bot.research.microstructure.cost_model_v3 import (
    ADMISSION_SCENARIO_ID,
    VENUE_SPECS,
    CostModelV3,
    default_model,
)

__all__ = [
    "ADMISSION_SCENARIO",
    "COST_SCENARIOS",
    "CostPlane",
    "cost_plane",
]

ADMISSION_SCENARIO = ADMISSION_SCENARIO_ID

#: Scenario name -> (fee multiplier, slippage/impact multiplier).
COST_SCENARIOS: dict[str, tuple[float, float]] = {
    "BASE": (1.0, 1.0),
    "2X_FEES": (2.0, 1.0),
    "ADVERSE": (2.0, 3.0),
}

_FEE_COMPONENTS = ("exchange_fee_entry", "exchange_fee_exit")


@dataclass(frozen=True, slots=True)
class CostPlane:
    """Round-trip cost of one execution intent, in basis points of notional."""

    scenario_id: str
    cost_model_version: str
    size_usd: float
    horizon_minutes: float
    fee_bps: float
    spread_bps: float
    slippage_bps: float
    impact_bps: float
    funding_bps: float
    other_bps: float
    round_trip_bps: float

    @property
    def components(self) -> dict[str, float]:
        return {
            "fee_bps": self.fee_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "impact_bps": self.impact_bps,
            "funding_bps": self.funding_bps,
            "other_bps": self.other_bps,
        }

    def scaled(self, name: str) -> CostPlane:
        """Stress variant derived from THIS plane's own components."""
        if name not in COST_SCENARIOS:
            raise KeyError(f"unknown cost scenario {name!r}")
        fee_mult, slip_mult = COST_SCENARIOS[name]
        fee = self.fee_bps * fee_mult
        slip = self.slippage_bps * slip_mult
        impact = self.impact_bps * slip_mult
        round_trip = fee + self.spread_bps + slip + impact + self.funding_bps + self.other_bps
        return CostPlane(
            scenario_id=name,
            cost_model_version=self.cost_model_version,
            size_usd=self.size_usd,
            horizon_minutes=self.horizon_minutes,
            fee_bps=fee,
            spread_bps=self.spread_bps,
            slippage_bps=slip,
            impact_bps=impact,
            funding_bps=self.funding_bps,
            other_bps=self.other_bps,
            round_trip_bps=round_trip,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "cost_model_version": self.cost_model_version,
            "size_usd": self.size_usd,
            "horizon_minutes": self.horizon_minutes,
            **{k: round(v, 6) for k, v in self.components.items()},
            "round_trip_bps": round(self.round_trip_bps, 6),
        }


def cost_plane(
    *,
    size_usd: float,
    horizon_minutes: float,
    scenario_id: str = ADMISSION_SCENARIO,
    spread_bps: float | None = None,
) -> CostPlane:
    """Evaluate one intent through COST_MODEL_V3 and flatten it into components.

    ``spread_bps=None`` leaves the spread at the venue's modelled default and the
    resulting plane records it as such: the research window has no per-bar book,
    and pretending to have observed a spread would be a claim the data cannot
    support.
    """
    if scenario_id not in VENUE_SPECS:
        raise KeyError(f"unknown cost scenario {scenario_id!r}")
    model: CostModelV3 = default_model(scenario_id)
    all_in = model.evaluate(
        size_usd=size_usd,
        horizon_minutes=horizon_minutes,
        spread_bps=spread_bps,
    )
    named = {c.name: c.value_bps for c in all_in.components}
    fee = sum(named.get(name, 0.0) for name in _FEE_COMPONENTS)
    spread = named.get("spread", 0.0)
    slip = named.get("slippage", 0.0)
    impact = named.get("market_impact", 0.0)
    funding = named.get("funding_carry", 0.0)
    other = all_in.round_trip_bps - (fee + spread + slip + impact + funding)
    return CostPlane(
        scenario_id=scenario_id,
        cost_model_version="COST_MODEL_V3",
        size_usd=size_usd,
        horizon_minutes=horizon_minutes,
        fee_bps=fee,
        spread_bps=spread,
        slippage_bps=slip,
        impact_bps=impact,
        funding_bps=funding,
        other_bps=other,
        round_trip_bps=all_in.round_trip_bps,
    )
