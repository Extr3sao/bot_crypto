"""COST_MODEL_V2 — research-only realistic execution cost models.

Phase A of EXECUTION-COST & MICROSTRUCTURE-EDGE-V1.

This module is RESEARCH_ONLY. It does not touch the production execution path
(§50). The production model lives in ``trading_bot.execution.cost_model`` and
is left untouched.

It separates the effective round-trip cost into economically distinct
components (§8) so a strategy's edge can be compared against something
defensible:

    exchange fee      per-side, depends on maker/taker and VIP tier
    spread            full spread paid when crossing on both sides
    slippage          adverse move beyond the quoted price, per side
    market impact     size-driven price displacement, per side
    adverse selection maker-only expected loss just after a passive fill
    funding / carry   derivatives holding cost, per day

Design rules (non-negotiable):
  * Never assume maker fee == 0 or that rebates exist as a baseline.
  * Never assume a limit order is a free fill (fill probability multiplies
    the maker scenario's *effective* cost only when a fill model exists).
  * ZERO_COST is a diagnostic, never an admission cost model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CostModelStatus = Literal["REALISTIC", "OPTIMISTIC", "CONSERVATIVE", "INVALID"]

# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostScenario:
    """One named execution-cost scenario.

    All bps are in basis points of notional (1 bps = 0.01% = 0.0001).

    ``spread_bps`` is the FULL quoted spread (best ask - best bid) in bps of
    mid. Crossing the book on both legs pays the full spread once per round
    trip (half on entry, half on exit relative to mid).

    ``maker_fill_prob`` is the probability a passive order actually fills.
    For a taker scenario it is 1.0. It does NOT enter ``round_trip_bps``
    directly: a maker scenario with imperfect fills has an *effective*
    cost that must be computed by the caller with a fill model
    (``effective_maker_cost_bps``); until then maker cost stays THEORETICAL.
    """

    name: str
    fee_bps_per_side: float
    spread_bps: float
    slippage_bps_per_side: float
    impact_bps_per_side: float = 0.0
    adverse_selection_bps_per_side: float = 0.0
    funding_bps_per_day: float = 0.0
    holding_days: float = 0.0
    maker_fill_prob: float = 1.0
    is_maker: bool = False
    evidence: str = ""

    # -- validation ---------------------------------------------------------

    def __post_init__(self) -> None:
        for field_name in (
            "fee_bps_per_side",
            "spread_bps",
            "slippage_bps_per_side",
            "impact_bps_per_side",
            "adverse_selection_bps_per_side",
        ):
            value = getattr(self, field_name)
            if value < 0.0:
                raise ValueError(f"{field_name} must be >= 0, got {value}")
        if self.funding_bps_per_day < 0.0:
            raise ValueError("funding_bps_per_day must be >= 0 (carry is a cost, not a rebate)")
        if not 0.0 <= self.maker_fill_prob <= 1.0:
            raise ValueError(f"maker_fill_prob must be in [0, 1], got {self.maker_fill_prob}")

    # -- cost math ----------------------------------------------------------

    def round_trip_bps(self) -> float:
        """Effective round-trip cost in bps of notional, including carry.

        For maker scenarios this is the *theoretical* cost assuming a fill;
        it always adds adverse selection. Use ``effective_maker_cost_bps``
        once a fill model exists.
        """
        per_side = (
            self.fee_bps_per_side
            + self.slippage_bps_per_side
            + self.impact_bps_per_side
            + self.adverse_selection_bps_per_side
        )
        return 2.0 * per_side + self.spread_bps + self.funding_bps_per_day * self.holding_days

    def minimum_gross_edge_bps(self) -> float:
        """Edge at which net == 0 (break-even)."""
        return self.round_trip_bps()

    def required_edge_bps(self, safety_multiple: float = 1.5) -> float:
        """Edge required for admission: break-even times a safety multiple.

        §42: a strategy whose edge is only ``cost + epsilon`` must not be
        promoted. The multiple encodes model-error tolerance.
        """
        if safety_multiple < 1.0:
            raise ValueError("safety_multiple must be >= 1.0")
        return self.round_trip_bps() * safety_multiple

    def effective_maker_cost_bps(self, fill_prob: float | None = None) -> float:
        """Maker cost when fills are uncertain (§8, §12, §47).

        A limit order that does not fill is not free — it misses the move and
        leaves the position unhedged relative to intent. We model the
        *expected* effective cost as:

            cost_if_filled + (1 - fill_prob) * missed_opportunity_penalty

        where the penalty is proxied by the round-trip cost itself (a missed
        fill costs at least the execution it was trying to avoid). This is a
        deliberately conservative lower bound; the true adverse-selection
        drag must come from a forward-collected fill model.
        """
        p = self.maker_fill_prob if fill_prob is None else fill_prob
        if not 0.0 <= p <= 1.0:
            raise ValueError("fill_prob must be in [0, 1]")
        filled = self.round_trip_bps()
        return filled + (1.0 - p) * filled


# ---------------------------------------------------------------------------
# The four pre-registered scenarios (§7)
# ---------------------------------------------------------------------------

# Standard Binance Spot VIP0 with the fee paid in the quote asset (no BNB
# discount): maker 0.1000% / taker 0.1000% = 10 bps per side. Paying with BNB
# grants 25% off -> 7.5 bps. VIP tiers require >= 1M USD 30d volume for VIP1.
CURRENT_PROJECT_COST_MODEL = CostScenario(
    name="CURRENT_PROJECT_COST_MODEL",
    fee_bps_per_side=5.0,
    spread_bps=0.0,
    slippage_bps_per_side=1.0,
    impact_bps_per_side=0.0,
    holding_days=0.0,
    evidence="scripts/multi_family_backtest.py: FEES=0.0005, SLIP=0.0001 -> 12 bps RT",
)

REALISTIC_RETAIL_COST_MODEL = CostScenario(
    name="REALISTIC_RETAIL_COST_MODEL",
    fee_bps_per_side=10.0,
    spread_bps=1.0,
    slippage_bps_per_side=1.0,
    impact_bps_per_side=0.25,
    holding_days=0.0,
    evidence="Binance Spot VIP0 taker 10 bps/side; observed majors spread ~0.2-1 bp",
)

REALISTIC_RETAIL_BNB_COST_MODEL = CostScenario(
    name="REALISTIC_RETAIL_BNB_COST_MODEL",
    fee_bps_per_side=7.5,
    spread_bps=1.0,
    slippage_bps_per_side=1.0,
    impact_bps_per_side=0.25,
    holding_days=0.0,
    evidence="Binance Spot VIP0 with BNB 25% off -> 7.5 bps/side (not a baseline)",
)

# Maker is modelled only as a theoretical scenario: VIP0 maker fee on Binance
# Spot is ALSO 10 bps, so passive execution does not reduce fees for a retail
# account. It only becomes cheaper from VIP1 (maker 8 bps) upward, which
# requires >= 1M USD 30d volume. Fill probability is left at a nominal value
# so callers are forced through effective_maker_cost_bps.
REALISTIC_MAKER_COST_MODEL = CostScenario(
    name="REALISTIC_MAKER_COST_MODEL",
    fee_bps_per_side=10.0,
    spread_bps=0.0,
    slippage_bps_per_side=0.0,
    impact_bps_per_side=0.0,
    adverse_selection_bps_per_side=0.5,
    holding_days=0.0,
    maker_fill_prob=0.5,
    is_maker=True,
    evidence="Binance Spot VIP0 maker 10 bps/side; no rebate baseline assumed",
)

STRESS_COST_MODEL = CostScenario(
    name="STRESS_COST_MODEL",
    fee_bps_per_side=10.0,
    spread_bps=2.0,
    slippage_bps_per_side=3.0,
    impact_bps_per_side=1.0,
    holding_days=0.0,
    evidence="2x realistic slippage + widened spread; model-error envelope",
)

COST_MODEL_V2: dict[str, CostScenario] = {
    "CURRENT_PROJECT_COST_MODEL": CURRENT_PROJECT_COST_MODEL,
    "REALISTIC_RETAIL_COST_MODEL": REALISTIC_RETAIL_COST_MODEL,
    "REALISTIC_RETAIL_BNB_COST_MODEL": REALISTIC_RETAIL_BNB_COST_MODEL,
    "REALISTIC_MAKER_COST_MODEL": REALISTIC_MAKER_COST_MODEL,
    "STRESS_COST_MODEL": STRESS_COST_MODEL,
}

# The scenario used for admission decisions (§41-42). Deliberately the taker
# retail model: the researched strategies are taker-ish market/limit entries
# and there is no demonstrated maker fill model.
ADMISSION_COST_MODEL = REALISTIC_RETAIL_COST_MODEL
ADMISSION_SAFETY_MULTIPLE = 1.5


def cost_model_status() -> CostModelStatus:
    """Classify the project's previously used 12 bps model (§9).

    The previous model used 5 bps/side while the real Binance Spot VIP0 fee is
    10 bps/side (20 bps round trip before spread/slippage). It therefore
    under-states the dominant cost term, so it is OPTIMISTIC. It is not
    INVALID: it is internally consistent (bps conversion correct, tests cover
    it) — it is simply too low for the real venue.
    """
    return "OPTIMISTIC"


def component_table() -> list[dict[str, float | str]]:
    """Machine-readable component breakdown for docs/COST_MODEL_V2.json."""
    rows: list[dict[str, float | str]] = []
    for scenario in COST_MODEL_V2.values():
        rows.append(
            {
                "scenario": scenario.name,
                "fee_bps_per_side": scenario.fee_bps_per_side,
                "spread_bps": scenario.spread_bps,
                "slippage_bps_per_side": scenario.slippage_bps_per_side,
                "impact_bps_per_side": scenario.impact_bps_per_side,
                "adverse_selection_bps_per_side": scenario.adverse_selection_bps_per_side,
                "funding_bps_per_day": scenario.funding_bps_per_day,
                "round_trip_bps": round(scenario.round_trip_bps(), 3),
                "min_gross_edge_bps": round(scenario.minimum_gross_edge_bps(), 3),
                "required_edge_bps_1p5x": round(scenario.required_edge_bps(1.5), 3),
                "is_maker": scenario.is_maker,
                "evidence": scenario.evidence,
            }
        )
    return rows


__all__ = [
    "ADMISSION_COST_MODEL",
    "ADMISSION_SAFETY_MULTIPLE",
    "COST_MODEL_V2",
    "CURRENT_PROJECT_COST_MODEL",
    "REALISTIC_MAKER_COST_MODEL",
    "REALISTIC_RETAIL_BNB_COST_MODEL",
    "REALISTIC_RETAIL_COST_MODEL",
    "STRESS_COST_MODEL",
    "CostModelStatus",
    "CostScenario",
    "component_table",
    "cost_model_status",
]
