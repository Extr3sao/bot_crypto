"""Cost bridge — COST_MODEL_V3 evaluated per cycle, never hardcoded (§11).

Two rules from the research phase are enforced here:

* the spread is **OBSERVED** from this cycle's market snapshot when available
  (the scanner publishes ``spread_bps`` per symbol) and only falls back to
  the model's ESTIMATED default when it is not, with the class recorded;
* the model is applied for a concrete size and holding horizon, so a
  proposal's economics are recomputed every cycle instead of being carried
  over from a previous assumption.

The production execution cost model is NOT touched: this module is
research/paper-side and only reads COST_MODEL_V3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.research.microstructure.cost_model_v3 import (
    ADMISSION_SCENARIO_ID,
    VENUE_SPECS,
    AllInCost,
    CostModelV3,
    LiquidityRegime,
    OrderType,
    default_model,
)

from .contracts import CostBreakdown

__all__ = [
    "ADMISSION_SCENARIO",
    "COST_MODEL_VERSION",
    "MODEL_V3_COMPONENT_NAMES",
    "CostEngine",
]

COST_MODEL_VERSION = "COST_MODEL_V3"
ADMISSION_SCENARIO = ADMISSION_SCENARIO_ID

MODEL_V3_COMPONENT_NAMES: tuple[str, ...] = (
    "exchange_fee_entry",
    "exchange_fee_exit",
    "spread",
    "slippage",
    "market_impact",
    "adverse_selection",
    "missed_fill_penalty",
    "fill_probability_inflation",
    "funding_carry",
)


@dataclass(frozen=True, slots=True)
class CostEngine:
    """Evaluate the admission venue scenario for one execution intent."""

    scenario_id: str = ADMISSION_SCENARIO

    def __post_init__(self) -> None:
        if self.scenario_id not in VENUE_SPECS:
            raise KeyError(f"unknown cost scenario {self.scenario_id!r}")

    @property
    def model(self) -> CostModelV3:
        return default_model(self.scenario_id)

    @property
    def venue(self) -> str:
        return VENUE_SPECS[self.scenario_id].venue

    @property
    def product(self) -> str:
        return VENUE_SPECS[self.scenario_id].product

    def evaluate(
        self,
        *,
        size_usd: float,
        horizon_minutes: float,
        spread_bps: float | None = None,
        liquidity_regime: LiquidityRegime = "normal",
        volatility_bps: float = 0.0,
        entry_order_type: OrderType | None = None,
        exit_order_type: OrderType | None = None,
        created_at_ms: int = 0,
    ) -> CostBreakdown:
        """All-in round-trip cost for this intent, component by component."""
        model = self.model
        all_in: AllInCost = model.evaluate(
            size_usd=size_usd,
            liquidity_regime=liquidity_regime,
            horizon_minutes=horizon_minutes,
            entry_order_type=entry_order_type,
            exit_order_type=exit_order_type,
            volatility_bps=volatility_bps,
            spread_bps=spread_bps,
        )
        resolved_spread = (
            VENUE_SPECS[self.scenario_id].default_taker_spread_bps
            if spread_bps is None
            else spread_bps
        )
        spread_component = next(
            (c for c in all_in.components if c.name == "spread"),
            None,
        )
        return CostBreakdown(
            scenario_id=self.scenario_id,
            cost_model_version=COST_MODEL_VERSION,
            size_usd=size_usd,
            horizon_minutes=horizon_minutes,
            spread_bps=resolved_spread,
            spread_knowledge=(
                spread_component.knowledge if spread_component is not None else "ESTIMATED"
            ),
            fee_bps=all_in.component("exchange_fee_entry") + all_in.component("exchange_fee_exit"),
            slippage_bps=all_in.component("slippage"),
            impact_bps=all_in.component("market_impact"),
            funding_bps=all_in.component("funding_carry"),
            round_trip_bps=all_in.round_trip_bps,
            components=tuple(c.as_dict() for c in all_in.components),
            created_at_ms=created_at_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        spec = VENUE_SPECS[self.scenario_id]
        return {
            "cost_model_version": COST_MODEL_VERSION,
            "scenario_id": self.scenario_id,
            "venue": spec.venue,
            "product": spec.product,
            "tier": spec.tier,
            "maker_fee_bps": spec.maker_fee_bps,
            "taker_fee_bps": spec.taker_fee_bps,
            "fee_source_id": spec.fee_source_id,
            "spread_source_id": spec.spread_source_id,
        }
