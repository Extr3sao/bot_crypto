"""EXECUTION_COST_MODEL_V4 — per-asset all-in round-trip cost (research-only).

V3 answered "what does one *scenario* cost?" using a single flat majors spread
(1.0 bps) and a flat volatility factor. V4 answers the question the experiment
ladder actually needs:

    for THIS asset, at THIS measured spread and THIS measured volatility,
    what does a round trip cost, and how much gross edge must a candidate
    show before it is even worth testing out-of-sample?

Three things change versus V3, and nothing else:

1. **Spread is per asset and OBSERVED**, not a flat majors constant. The
   measured values come from real read-only bookTicker captures
   (``reports/microstructure-v2/forward/*.jsonl``); the observation count and
   the provenance path travel with the number.
2. **Volatility is per asset and OBSERVED**, measured from real 5m klines, so
   the V3 volatility factor stops being a modelling assumption of 1.0.
3. **A maker row is reported but never promotable.** At Binance Spot VIP0 the
   maker fee equals the taker fee, so passive execution saves *no* fee, and
   there is no ``FillEvidence`` anywhere in this phase. The maker row is
   therefore labelled ``EXECUTION_DEPENDENT``: informative, never an admission
   cost.

The fee/slippage/impact/funding arithmetic itself is NOT reimplemented here —
V4 composes :mod:`trading_bot.research.microstructure.cost_model_v3` so there is
exactly one place where a fee is turned into basis points. If V3 changes, V4
changes with it.

RESEARCH_ONLY (DISCOVERY PLANE). Not imported by the runtime.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .cost_model_v3 import (
    ADMISSION_SCENARIO_ID,
    VENUE_SPECS,
    AllInCost,
    LiquidityRegime,
    default_model,
)

__all__ = [
    "ADMISSION_SAFETY_MULTIPLE",
    "COST_MODEL_V4_VERSION",
    "MAKER_STATUS_EXECUTION_DEPENDENT",
    "AssetCostV4",
    "AssetMarketInput",
    "asset_cost_v4",
    "execution_cost_model_v4",
    "required_gross_edge_bps",
]

COST_MODEL_V4_VERSION = "EXECUTION_COST_MODEL_V4"

#: Pre-registered safety multiple on top of the break-even cost (§42): a
#: candidate whose gross edge merely equals the cost is rejected.
ADMISSION_SAFETY_MULTIPLE = 1.5

#: No venue in this phase has a measured fill model, so a maker cost can never
#: be treated as an achievable cost.
MAKER_STATUS_EXECUTION_DEPENDENT = "EXECUTION_DEPENDENT"

_COMPONENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fee", ("fee",)),
    ("spread", ("spread",)),
    ("slippage_impact", ("slippage", "impact", "adverse", "partial", "walk")),
    ("funding_carry", ("funding", "carry", "borrow")),
)


def _component_bucket(name: str) -> str:
    lowered = name.lower()
    for bucket, needles in _COMPONENT_GROUPS:
        if any(needle in lowered for needle in needles):
            return bucket
    return "other"


def required_gross_edge_bps(
    round_trip_bps: float, safety_multiple: float = ADMISSION_SAFETY_MULTIPLE
) -> float:
    """Gross edge a candidate must show for admission, including the margin."""
    if round_trip_bps < 0.0:
        raise ValueError("round_trip_bps must be >= 0")
    if safety_multiple < 1.0:
        raise ValueError("safety_multiple must be >= 1.0")
    return round_trip_bps * safety_multiple


@dataclass(frozen=True, slots=True)
class AssetMarketInput:
    """One asset's *measured* market state, with provenance.

    ``observed_spread_bps`` and ``realized_vol_bps`` are measurements, not
    assumptions: each carries the source that produced it and, for the spread,
    the number of independent observations behind the number.
    """

    asset: str
    symbol: str
    observed_spread_bps: float
    spread_observations: int
    spread_source: str
    realized_vol_bps: float
    vol_source: str

    def __post_init__(self) -> None:
        if not self.asset or not self.symbol:
            raise ValueError("asset and symbol must be non-empty")
        if self.observed_spread_bps < 0.0:
            raise ValueError("observed_spread_bps must be >= 0")
        if self.spread_observations < 1:
            raise ValueError(
                "observed_spread_bps requires at least one observation; an "
                "unobserved spread must not be modelled as zero"
            )
        if not self.spread_source:
            raise ValueError("spread_source must name the capture that produced it")
        if self.realized_vol_bps < 0.0:
            raise ValueError("realized_vol_bps must be >= 0")
        if not self.vol_source:
            raise ValueError("vol_source must name the series that produced it")

    def as_dict(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "symbol": self.symbol,
            "observed_spread_bps": round(self.observed_spread_bps, 4),
            "spread_observations": self.spread_observations,
            "spread_source": self.spread_source,
            "realized_vol_bps": round(self.realized_vol_bps, 4),
            "vol_source": self.vol_source,
        }


@dataclass(frozen=True, slots=True)
class AssetCostV4:
    """The measured cost of one round trip in one asset, with its breakdown."""

    asset: str
    symbol: str
    scenario_id: str
    venue: str
    product: str
    size_usd: float
    liquidity_regime: str
    horizon_minutes: float
    observed_spread_bps: float
    realized_vol_bps: float
    fee_bps: float
    spread_bps: float
    slippage_impact_bps: float
    funding_carry_bps: float
    other_bps: float
    taker_round_trip_bps: float
    required_gross_edge_bps: float
    stress_bps: dict[str, float]
    maker_round_trip_bps_theoretical: float
    maker_status: str
    maker_note: str
    knowledge_class: str
    evidence: str
    components: tuple[dict[str, Any], ...]

    @property
    def minimum_gross_edge_bps(self) -> float:
        """Break-even: the gross edge at which net expectancy is exactly zero."""
        return self.taker_round_trip_bps

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "symbol": self.symbol,
            "scenario_id": self.scenario_id,
            "venue": self.venue,
            "product": self.product,
            "size_usd": self.size_usd,
            "liquidity_regime": self.liquidity_regime,
            "horizon_minutes": self.horizon_minutes,
            "observed_spread_bps": round(self.observed_spread_bps, 4),
            "realized_vol_bps": round(self.realized_vol_bps, 4),
            "components_bps": {
                "fee": round(self.fee_bps, 4),
                "spread": round(self.spread_bps, 4),
                "slippage_impact": round(self.slippage_impact_bps, 4),
                "funding_carry": round(self.funding_carry_bps, 4),
                "other": round(self.other_bps, 4),
            },
            "taker_round_trip_bps": round(self.taker_round_trip_bps, 4),
            "minimum_gross_edge_bps": round(self.minimum_gross_edge_bps, 4),
            "required_gross_edge_bps": round(self.required_gross_edge_bps, 4),
            "stress_bps": {k: round(v, 4) for k, v in self.stress_bps.items()},
            "maker_round_trip_bps_theoretical": round(self.maker_round_trip_bps_theoretical, 4),
            "maker_status": self.maker_status,
            "maker_note": self.maker_note,
            "knowledge_class": self.knowledge_class,
            "evidence": self.evidence,
            "components": [dict(c) for c in self.components],
        }


def _bucket_totals(
    components: tuple[Any, ...],
) -> dict[str, float]:
    totals = {"fee": 0.0, "spread": 0.0, "slippage_impact": 0.0, "funding_carry": 0.0, "other": 0.0}
    for component in components:
        totals[_component_bucket(str(component.name))] += float(component.value_bps)
    return totals


def asset_cost_v4(
    market: AssetMarketInput,
    *,
    scenario_id: str = ADMISSION_SCENARIO_ID,
    size_usd: float = 1_000.0,
    liquidity_regime: LiquidityRegime = "normal",
    horizon_minutes: float = 25.0,
    safety_multiple: float = ADMISSION_SAFETY_MULTIPLE,
) -> AssetCostV4:
    """Evaluate one asset's round-trip cost under the V3 arithmetic.

    The only V3 inputs overridden are ``spread_bps`` (the asset's *measured*
    spread) and ``volatility_bps`` (the asset's *measured* realized
    volatility). Fees, size scaling, impact, funding and the stress envelopes
    are V3's, unchanged.
    """
    if scenario_id not in VENUE_SPECS:
        raise KeyError(f"unknown scenario {scenario_id!r}")
    if size_usd <= 0.0:
        raise ValueError("size_usd must be > 0")
    if horizon_minutes < 0.0:
        raise ValueError("horizon_minutes must be >= 0")

    model = default_model(scenario_id)
    spec = VENUE_SPECS[scenario_id]

    taker: AllInCost = model.evaluate(
        size_usd=size_usd,
        liquidity_regime=liquidity_regime,
        horizon_minutes=horizon_minutes,
        entry_order_type="market",
        exit_order_type="market",
        volatility_bps=market.realized_vol_bps,
        spread_bps=market.observed_spread_bps,
    )
    maker: AllInCost = model.evaluate(
        size_usd=size_usd,
        liquidity_regime=liquidity_regime,
        horizon_minutes=horizon_minutes,
        entry_order_type="limit_post_only",
        exit_order_type="limit_post_only",
        volatility_bps=market.realized_vol_bps,
        spread_bps=market.observed_spread_bps,
    )

    totals = _bucket_totals(taker.components)
    maker_saves_fee = spec.maker_fee_bps < spec.taker_fee_bps
    maker_note = (
        f"maker fee {spec.maker_fee_bps} bps vs taker {spec.taker_fee_bps} bps at "
        f"{spec.tier}; "
        + (
            "passive execution does not reduce the fee"
            if not maker_saves_fee
            else "a fee advantage exists but no FillEvidence supports assuming fills"
        )
    )

    return AssetCostV4(
        asset=market.asset,
        symbol=market.symbol,
        scenario_id=scenario_id,
        venue=spec.venue,
        product=spec.product,
        size_usd=size_usd,
        liquidity_regime=liquidity_regime,
        horizon_minutes=horizon_minutes,
        observed_spread_bps=market.observed_spread_bps,
        realized_vol_bps=market.realized_vol_bps,
        fee_bps=totals["fee"],
        spread_bps=totals["spread"],
        slippage_impact_bps=totals["slippage_impact"],
        funding_carry_bps=totals["funding_carry"],
        other_bps=totals["other"],
        taker_round_trip_bps=taker.round_trip_bps,
        required_gross_edge_bps=required_gross_edge_bps(taker.round_trip_bps, safety_multiple),
        stress_bps={
            "1.25x": taker.stress(1.25),
            "1.5x": taker.stress(1.5),
            "2.0x": taker.stress(2.0),
        },
        maker_round_trip_bps_theoretical=maker.round_trip_bps,
        maker_status=MAKER_STATUS_EXECUTION_DEPENDENT,
        maker_note=maker_note,
        knowledge_class=taker.knowledge_class,
        evidence=taker.evidence,
        components=tuple(c.as_dict() for c in taker.components),
    )


def execution_cost_model_v4(
    markets: Sequence[AssetMarketInput],
    *,
    scenario_id: str = ADMISSION_SCENARIO_ID,
    size_usd: float = 1_000.0,
    liquidity_regime: LiquidityRegime = "normal",
    horizon_minutes: float = 25.0,
    safety_multiple: float = ADMISSION_SAFETY_MULTIPLE,
) -> dict[str, Any]:
    """Machine-readable EXECUTION_COST_MODEL_V4 payload for the versioned docs."""
    if not markets:
        raise ValueError("at least one asset market input is required")
    names = [m.asset for m in markets]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate asset in cost model inputs: {names}")
    spec = VENUE_SPECS[scenario_id]
    rows = [
        asset_cost_v4(
            m,
            scenario_id=scenario_id,
            size_usd=size_usd,
            liquidity_regime=liquidity_regime,
            horizon_minutes=horizon_minutes,
            safety_multiple=safety_multiple,
        ).as_dict()
        for m in markets
    ]
    maker_gate_pass = spec.maker_fee_bps < spec.taker_fee_bps
    return {
        "model": COST_MODEL_V4_VERSION,
        "supersedes": "COST_MODEL_V3 (flat majors spread, volatility factor 1.0)",
        "admission_scenario": scenario_id,
        "safety_multiple": safety_multiple,
        "reference_intent": {
            "size_usd": size_usd,
            "liquidity_regime": liquidity_regime,
            "horizon_minutes": horizon_minutes,
            "entry_order_type": "market",
            "exit_order_type": "market",
        },
        "asset_market_inputs": [m.as_dict() for m in markets],
        "assets": rows,
        "maker_gate": {
            "status": "PASS" if maker_gate_pass else "FAIL",
            "reason": (
                "maker fee equals taker fee at this tier, so passive execution "
                "saves no fee; and no FillEvidence exists in this phase, so no "
                "maker cost may be used for admission"
            ),
            "maker_fee_bps": spec.maker_fee_bps,
            "taker_fee_bps": spec.taker_fee_bps,
            "fill_evidence_available": False,
        },
        "notes": [
            "spread is measured per asset from a real read-only capture; the "
            "observation count and source path are part of the model input",
            "volatility is measured per asset from real 5m klines",
            "fee/slippage/impact/funding arithmetic is unchanged from COST_MODEL_V3",
            "zero-cost is never an admission model (unchanged from V3)",
        ],
    }
