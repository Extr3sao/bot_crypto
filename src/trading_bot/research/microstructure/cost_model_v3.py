"""COST_MODEL_V3 — parametrisable execution-cost model (research-only).

Supersedes ``cost_model.py`` (COST_MODEL_V2), which was a set of four fixed
scalar scenarios. V3 makes every dimension the research phase asked for
explicit and separately labelled (§PHASE 1):

    venue · product · jurisdiction · account/fee tier · fee-payment mode ·
    maker/taker · entry order type · exit order type · spread · slippage ·
    size · liquidity · volatility · fill probability · partial fills ·
    adverse selection · funding/carry · holding period

Every number carries a ``KnowledgeClass``:

    KNOWN     published by the exchange, unambiguous
    OBSERVED  measured by us against a live read-only endpoint
    ESTIMATED derived from evidence with a stated method
    ASSUMED   a modelling choice with no direct evidence (stress envelope)

The four classes are never mixed inside a single component, and no component
is ever silently promoted from ASSUMED to OBSERVED.

Design rules inherited from V2 and still enforced:
  * never assume maker fee == 0 or that a rebate exists as a baseline,
  * never treat a limit order as a free fill,
  * discounts/promotions are recorded with an ``Applicability`` verdict,
    never assumed to apply to our account,
  * ZERO_COST is diagnostic only, never an admission model.

RESEARCH_ONLY. Does not touch ``trading_bot.execution.cost_model`` nor any
production path (§50).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "ADMISSION_SCENARIO_ID",
    "APPLICABILITY_ALIASES",
    "COST_STRESS_MULTIPLES",
    "VENUE_SPECS",
    "AllInCost",
    "Applicability",
    "CostComponent",
    "CostModelV3",
    "FeePaymentMode",
    "KnowledgeClass",
    "LiquidityRegime",
    "OrderType",
    "VenueSpec",
    "cost_model_v3_all_in",
    "cost_stress_table",
    "default_model",
    "scenario_ids",
    "venue_matrix_rows",
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

KnowledgeClass = Literal["KNOWN", "OBSERVED", "ESTIMATED", "ASSUMED"]
Applicability = Literal["CONFIRMED", "POSSIBLE", "NOT_APPLICABLE", "UNKNOWN"]
FeePaymentMode = Literal["quote_asset", "bnb", "exchange_token"]
OrderType = Literal["market", "limit_post_only", "limit_ioc", "limit_gtc"]
LiquidityRegime = Literal["deep", "normal", "thin"]
_KNOWN_CLASSES: tuple[KnowledgeClass, ...] = ("KNOWN", "OBSERVED", "ESTIMATED", "ASSUMED")
_APPLICABILITY: tuple[Applicability, ...] = (
    "CONFIRMED",
    "POSSIBLE",
    "NOT_APPLICABLE",
    "UNKNOWN",
)

# Documented alias so callers can talk about "CONFIRMED" discounts.
APPLICABILITY_ALIASES: dict[str, Applicability] = {a: a for a in _APPLICABILITY}

COST_STRESS_MULTIPLES: tuple[float, ...] = (1.0, 1.25, 1.5, 2.0)

# Liquidity regime -> multiplier applied to the base slippage/impact terms.
# ESTIMATED from the observed majors' book depth; deliberately coarse.
_LIQUIDITY_MULTIPLIER: dict[LiquidityRegime, float] = {
    "deep": 0.5,
    "normal": 1.0,
    "thin": 2.5,
}

# Reference notional (USD) at which the size term doubles the base slippage.
# ASSUMED modelling constant; documented, not fitted to outcomes.
_REFERENCE_NOTIONAL_USD: float = 10_000.0

_FUNDING_INTERVALS_PER_DAY: float = 3.0  # Binance USD-M: every 8h


def _check_knowledge(knowledge: str) -> None:
    if knowledge not in _KNOWN_CLASSES:
        raise ValueError(f"knowledge must be one of {_KNOWN_CLASSES}, got {knowledge!r}")


def _require_bps(value: float, name: str) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be >= 0 (costs are non-negative), got {value}")


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostComponent:
    """One additive term of the round-trip cost, with its evidence class."""

    name: str
    value_bps: float
    knowledge: KnowledgeClass
    source_id: str
    note: str = ""

    def __post_init__(self) -> None:
        _check_knowledge(self.knowledge)
        if self.value_bps < -1e-9:
            # A negative component is only legitimate for an explicitly
            # declared rebate; we never model one, so fail closed.
            raise ValueError(
                f"component {self.name!r} is negative ({self.value_bps}); "
                "maker rebates are not modelled (§7)"
            )

    def as_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "value_bps": round(self.value_bps, 6),
            "knowledge": self.knowledge,
            "source_id": self.source_id,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class AllInCost:
    """Result of evaluating a venue spec for a concrete execution intent."""

    scenario_id: str
    venue: str
    product: str
    size_usd: float
    liquidity_regime: LiquidityRegime
    horizon_minutes: float
    entry_order_type: OrderType
    exit_order_type: OrderType
    components: tuple[CostComponent, ...]
    round_trip_bps: float
    knowledge_class: KnowledgeClass
    evidence: str

    def _by_name(self, name: str) -> float:
        return sum(c.value_bps for c in self.components if c.name == name)

    def component(self, name: str) -> float:
        return self._by_name(name)

    def minimum_gross_edge_bps(self) -> float:
        """Break-even: net expectancy == 0."""
        return self.round_trip_bps

    def required_edge_bps(self, safety_multiple: float = 1.5) -> float:
        """§42 — edge needed for promotion, including a model-error margin."""
        if safety_multiple < 1.0:
            raise ValueError("safety_multiple must be >= 1.0")
        return self.round_trip_bps * safety_multiple

    def stress(self, multiple: float) -> float:
        """Cost under an N-times stress envelope (>= 1.0)."""
        if multiple < 1.0:
            raise ValueError("stress multiple must be >= 1.0")
        return self.round_trip_bps * multiple

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "venue": self.venue,
            "product": self.product,
            "size_usd": self.size_usd,
            "liquidity_regime": self.liquidity_regime,
            "horizon_minutes": self.horizon_minutes,
            "entry_order_type": self.entry_order_type,
            "exit_order_type": self.exit_order_type,
            "components": [c.as_dict() for c in self.components],
            "round_trip_bps": round(self.round_trip_bps, 4),
            "minimum_gross_edge_bps": round(self.minimum_gross_edge_bps(), 4),
            "required_edge_bps_1p5x": round(self.required_edge_bps(1.5), 4),
            "stress_bps": {f"{m}x": round(self.stress(m), 4) for m in COST_STRESS_MULTIPLES},
            "knowledge_class": self.knowledge_class,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Venue registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VenueSpec:
    """One venue/product/account-tiers combination.

    Fees are the *published* headline numbers for the stated tier and payment
    mode. ``discount_applicability`` records whether a promotional rate may
    legitimately be used for OUR account; it is never CONFIRMED without a
    governance decision.
    """

    scenario_id: str
    venue: str
    product: str
    jurisdiction: str
    symbol_class: str
    tier: str
    fee_payment_mode: FeePaymentMode
    maker_fee_bps: float
    taker_fee_bps: float
    discount_program: str
    discount_applicability: Applicability
    default_taker_spread_bps: float
    min_notional_usd: float
    fee_source_id: str
    spread_source_id: str
    funding_source_id: str
    notes: str = ""
    integration_status: str = "RESEARCH_CANDIDATE"

    def __post_init__(self) -> None:
        _require_bps(self.maker_fee_bps, "maker_fee_bps")
        _require_bps(self.taker_fee_bps, "taker_fee_bps")
        _require_bps(self.default_taker_spread_bps, "default_taker_spread_bps")
        if self.tier == "VIP0" and self.fee_payment_mode == "quote_asset":
            pass
        if self.tier == "VIP0" and self.fee_payment_mode == "bnb" and self.discount_applicability == "CONFIRMED":
            raise ValueError(
                f"{self.scenario_id}: a BNB-discounted rate cannot be CONFIRMED "
                "for our account without a governance decision (§7)"
            )


# Default spread estimates come from the live bookTicker observation recorded
# in COST_MODEL_V2 (BTC 0.001, ETH 0.04, SOL 0.83 bps) rounded up to a
# conservative 1.0 bps for majors. Knowledge class: ESTIMATED.
_MAJORS_SPREAD_BPS = 1.0
_MINOR_SPREAD_BPS = 5.0

VENUE_SPECS: dict[str, VenueSpec] = {
    # --- Binance Spot (the runtime venue) ---------------------------------
    "BINANCE_SPOT_STANDARD_TAKER": VenueSpec(
        scenario_id="BINANCE_SPOT_STANDARD_TAKER",
        venue="Binance",
        product="Spot",
        jurisdiction="global (testnet for the runtime)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0 (regular user, 30d volume < 1,000,000 USD)",
        fee_payment_mode="quote_asset",
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        discount_program="none",
        discount_applicability="NOT_APPLICABLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-01",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="Baseline for the current runtime. Fee is identical maker/taker at VIP0.",
        integration_status="BASELINE",
    ),
    "BINANCE_SPOT_STANDARD_MAKER": VenueSpec(
        scenario_id="BINANCE_SPOT_STANDARD_MAKER",
        venue="Binance",
        product="Spot",
        jurisdiction="global (testnet for the runtime)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0 (regular user)",
        fee_payment_mode="quote_asset",
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        discount_program="none",
        discount_applicability="NOT_APPLICABLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-01",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="VIP0 maker == taker on Binance Spot, so passive execution saves NO fee.",
        integration_status="BASELINE",
    ),
    "BINANCE_SPOT_BNB_TAKER": VenueSpec(
        scenario_id="BINANCE_SPOT_BNB_TAKER",
        venue="Binance",
        product="Spot",
        jurisdiction="global",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0 with BNB 25% discount",
        fee_payment_mode="bnb",
        maker_fee_bps=7.5,
        taker_fee_bps=7.5,
        discount_program="pay trading fee in BNB (-25%)",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-01",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="Requires holding BNB; applicability to our account is UNCONFIRMED (§7).",
    ),
    "BINANCE_SPOT_BNB_MAKER": VenueSpec(
        scenario_id="BINANCE_SPOT_BNB_MAKER",
        venue="Binance",
        product="Spot",
        jurisdiction="global",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0 with BNB 25% discount",
        fee_payment_mode="bnb",
        maker_fee_bps=7.5,
        taker_fee_bps=7.5,
        discount_program="pay trading fee in BNB (-25%)",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-01",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="Maker still pays 7.5 bps; no rebate. Fill risk is unmodelled here.",
    ),
    # --- Binance USD-M perpetual (research only, NOT integrated) ----------
    "BINANCE_USDM_PERP_TAKER": VenueSpec(
        scenario_id="BINANCE_USDM_PERP_TAKER",
        venue="Binance",
        product="USDⓈ-M Perpetual",
        jurisdiction="global (excluded from our runtime)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0",
        fee_payment_mode="quote_asset",
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        discount_program="periodic 0% maker promotions",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-02",
        spread_source_id="SRC-07",
        funding_source_id="SRC-05",
        notes="Carries funding (8h). Leverage and margin change the risk model entirely.",
        integration_status="NEEDS_GOVERNANCE_DECISION",
    ),
    "BINANCE_USDM_PERP_MAKER": VenueSpec(
        scenario_id="BINANCE_USDM_PERP_MAKER",
        venue="Binance",
        product="USDⓈ-M Perpetual",
        jurisdiction="global (excluded from our runtime)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0",
        fee_payment_mode="quote_asset",
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        discount_program="periodic 0% maker promotions",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-02",
        spread_source_id="SRC-07",
        funding_source_id="SRC-05",
        notes="Maker 2 bps nominal; a 0% promo is NOT assumed as a baseline.",
        integration_status="NEEDS_GOVERNANCE_DECISION",
    ),
    # --- Other spot venues (research only) --------------------------------
    "BYBIT_SPOT_TAKER": VenueSpec(
        scenario_id="BYBIT_SPOT_TAKER",
        venue="Bybit",
        product="Spot",
        jurisdiction="global (not US)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="VIP0",
        fee_payment_mode="quote_asset",
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        discount_program="none at VIP0",
        discount_applicability="NOT_APPLICABLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=1.0,
        fee_source_id="SRC-09",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="Same headline spot fee as Binance at VIP0.",
    ),
    "OKX_SPOT_TAKER": VenueSpec(
        scenario_id="OKX_SPOT_TAKER",
        venue="OKX",
        product="Spot",
        jurisdiction="global (not US)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="Lv1 (< 500 OKB, < 100k USD 30d)",
        fee_payment_mode="quote_asset",
        maker_fee_bps=8.0,
        taker_fee_bps=10.0,
        discount_program="OKB holdings / volume tiers",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=1.0,
        fee_source_id="SRC-10",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="Maker 8 bps at entry tier -> passive execution saves 2 bps.",
    ),
    "MEXC_SPOT_TAKER": VenueSpec(
        scenario_id="MEXC_SPOT_TAKER",
        venue="MEXC",
        product="Spot",
        jurisdiction="global (not US)",
        symbol_class="majors BTC/ETH/SOL vs USDT",
        tier="standard",
        fee_payment_mode="quote_asset",
        maker_fee_bps=0.0,
        taker_fee_bps=5.0,
        discount_program="permanent 0% maker; 0-fee spot campaign on eligible pairs",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MINOR_SPREAD_BPS,
        min_notional_usd=1.0,
        fee_source_id="SRC-11",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes=(
            "Lowest headline spot taker fee researched. 0% maker is a REAL "
            "published rate, not a rebate; the cost that remains is adverse "
            "selection and fill risk (unmodelled). Wider spreads/less depth "
            "than Binance are ASSUMED, not observed."
        ),
    ),
    "KRAKENPRO_SPOT_TAKER": VenueSpec(
        scenario_id="KRAKENPRO_SPOT_TAKER",
        venue="Kraken Pro",
        product="Spot",
        jurisdiction="global (incl. US/EU)",
        symbol_class="majors BTC/ETH/SOL vs USD/USDT",
        tier="lowest volume tier (< 10,000 USD 30d)",
        fee_payment_mode="quote_asset",
        maker_fee_bps=25.0,
        taker_fee_bps=40.0,
        discount_program="volume/AoP tiers",
        discount_applicability="POSSIBLE",
        default_taker_spread_bps=_MAJORS_SPREAD_BPS,
        min_notional_usd=5.0,
        fee_source_id="SRC-12",
        spread_source_id="SRC-07",
        funding_source_id="n/a (spot: no funding)",
        notes="Regulatory-accessibility upside, but the entry-tier fee is prohibitive for intraday.",
    ),
}

ADMISSION_SCENARIO_ID = "BINANCE_SPOT_STANDARD_TAKER"


def scenario_ids() -> list[str]:
    return sorted(VENUE_SPECS)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CostInputs:
    size_usd: float
    liquidity_regime: LiquidityRegime
    horizon_minutes: float
    entry_order_type: OrderType
    exit_order_type: OrderType
    volatility_bps: float
    funding_rate_bps_per_interval: float
    maker_fill_prob: float
    maker_adverse_selection_bps: float
    maker_partial_fill_penalty_bps: float
    spread_bps: float | None


@dataclass(frozen=True, slots=True)
class CostModelV3:
    """Evaluate one ``VenueSpec`` under explicit execution assumptions."""

    spec: VenueSpec
    base_slippage_bps: float = 1.0
    base_impact_bps: float = 0.25
    maker_adverse_selection_bps: float = 0.5
    maker_fill_prob: float = 0.5
    maker_partial_fill_penalty_bps: float = 0.25
    volatility_reference_bps: float = 50.0
    extras: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_bps(self.base_slippage_bps, "base_slippage_bps")
        _require_bps(self.base_impact_bps, "base_impact_bps")
        _require_bps(self.maker_adverse_selection_bps, "maker_adverse_selection_bps")
        _require_bps(self.maker_partial_fill_penalty_bps, "maker_partial_fill_penalty_bps")
        if not 0.0 <= self.maker_fill_prob <= 1.0:
            raise ValueError("maker_fill_prob must be in [0, 1]")

    # -- helpers ------------------------------------------------------------

    def _fee_bps(self, order_type: OrderType) -> float:
        return (
            self.spec.maker_fee_bps
            if order_type in ("limit_post_only", "limit_gtc")
            else self.spec.taker_fee_bps
        )

    def _liquidity_factor(self, regime: LiquidityRegime) -> float:
        if regime not in _LIQUIDITY_MULTIPLIER:
            raise ValueError(f"unknown liquidity regime {regime!r}")
        return _LIQUIDITY_MULTIPLIER[regime]

    def _size_factor(self, size_usd: float) -> float:
        if size_usd <= 0.0:
            raise ValueError("size_usd must be > 0")
        return 1.0 + math.sqrt(size_usd / _REFERENCE_NOTIONAL_USD)

    def _volatility_factor(self, volatility_bps: float) -> float:
        if volatility_bps < 0.0:
            raise ValueError("volatility_bps must be >= 0")
        return 1.0 + volatility_bps / self.volatility_reference_bps

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self,
        size_usd: float = 1_000.0,
        liquidity_regime: LiquidityRegime = "normal",
        horizon_minutes: float = 25.0,
        entry_order_type: OrderType | None = None,
        exit_order_type: OrderType | None = None,
        volatility_bps: float = 0.0,
        funding_rate_bps_per_interval: float = 0.0,
        spread_bps: float | None = None,
        maker_fill_prob: float | None = None,
    ) -> AllInCost:
        """Assemble the all-in round-trip cost for one execution intent."""
        if horizon_minutes < 0.0:
            raise ValueError("horizon_minutes must be >= 0")
        _require_bps(funding_rate_bps_per_interval, "funding_rate_bps_per_interval")
        if maker_fill_prob is not None and not 0.0 <= maker_fill_prob <= 1.0:
            raise ValueError("maker_fill_prob must be in [0, 1]")
        default_maker = self.spec.scenario_id.endswith("_MAKER")
        entry = entry_order_type or ("limit_post_only" if default_maker else "market")
        exit_ = exit_order_type or ("limit_post_only" if default_maker else "market")
        spread = self.spec.default_taker_spread_bps if spread_bps is None else spread_bps
        _require_bps(spread, "spread_bps")

        liq = self._liquidity_factor(liquidity_regime)
        size_f = self._size_factor(size_usd)
        vol_f = self._volatility_factor(volatility_bps)

        components: list[CostComponent] = []

        # --- fees (KNOWN: published schedule for the stated tier/mode) -----
        entry_fee = self._fee_bps(entry)
        exit_fee = self._fee_bps(exit_)
        components.append(
            CostComponent(
                "exchange_fee_entry",
                entry_fee,
                "KNOWN",
                self.spec.fee_source_id,
                f"{self.spec.tier}, pay in {self.spec.fee_payment_mode}",
            )
        )
        components.append(
            CostComponent(
                "exchange_fee_exit",
                exit_fee,
                "KNOWN",
                self.spec.fee_source_id,
                f"{self.spec.tier}, pay in {self.spec.fee_payment_mode}",
            )
        )

        # --- candidate legs: maker-ness comes from the ORDER TYPES, never
        # --- from the scenario name (a taker scenario may still place a
        # --- passive entry, and vice versa).
        taker_legs = int(entry == "market") + int(exit_ == "market")
        maker_legs = int(entry.startswith("limit")) + int(exit_.startswith("limit"))
        assert taker_legs + maker_legs == 2

        # --- spread (OBSERVED when supplied, else ESTIMATED) ---------------
        spread_cost = spread * (0.5 * taker_legs)
        spread_knowledge: KnowledgeClass = "OBSERVED" if spread_bps is not None else "ESTIMATED"
        if spread_cost > 0.0:
            components.append(
                CostComponent(
                    "spread",
                    spread_cost,
                    spread_knowledge,
                    self.spec.spread_source_id,
                    f"{taker_legs} taker leg(s) x half-spread",
                )
            )

        # --- slippage / impact (ESTIMATED; size, liquidity, vol dependent) --
        if taker_legs > 0:
            slip = self.base_slippage_bps * liq * size_f * vol_f * taker_legs
            impact = self.base_impact_bps * liq * (size_f - 1.0) * vol_f * taker_legs
            components.append(
                CostComponent(
                    "slippage",
                    slip,
                    "ESTIMATED",
                    "MODEL-V3",
                    f"base {self.base_slippage_bps} bps x liq {liq} x size {size_f:.3f} x vol {vol_f:.3f}",
                )
            )
            components.append(
                CostComponent(
                    "market_impact",
                    impact,
                    "ESTIMATED",
                    "MODEL-V3",
                    "size-driven displacement above the base slippage",
                )
            )

        # --- maker-specific: adverse selection + fill risk -----------------
        if maker_legs > 0:
            components.append(
                CostComponent(
                    "adverse_selection",
                    self.maker_adverse_selection_bps * maker_legs,
                    "ASSUMED",
                    "MODEL-V3",
                    "expected loss just after a passive fill; needs a forward fill model",
                )
            )
            p = self.maker_fill_prob if maker_fill_prob is None else maker_fill_prob
            components.append(
                CostComponent(
                    "missed_fill_penalty",
                    self.maker_partial_fill_penalty_bps * (1.0 - p) * maker_legs,
                    "ASSUMED",
                    "MODEL-V3",
                    f"fill probability {p:.2f}; an unfilled leg is not free (§12/§47)",
                )
            )
            # A passive fee is only realised on a filled order, so the fee
            # portion of the maker leg is inflated by 1/p. This keeps a 0% maker
            # fee from collapsing the scenario to "free".
            if 0.0 < p < 1.0:
                maker_fee_share = (entry_fee if entry.startswith("limit") else 0.0) + (
                    exit_fee if exit_.startswith("limit") else 0.0
                )
                inflation = maker_fee_share * (1.0 / p - 1.0)
                if inflation > 0.0:
                    components.append(
                        CostComponent(
                            "fill_probability_inflation",
                            inflation,
                            "ASSUMED",
                            "MODEL-V3",
                            f"maker fee realised only on filled orders (p={p:.2f})",
                        )
                    )

        # --- funding / carry (KNOWN schedule, ESTIMATED rate) --------------
        if funding_rate_bps_per_interval > 0.0 and horizon_minutes > 0.0:
            intervals = horizon_minutes / (24 * 60 / _FUNDING_INTERVALS_PER_DAY)
            carry = funding_rate_bps_per_interval * intervals
            components.append(
                CostComponent(
                    "funding_carry",
                    carry,
                    "ESTIMATED",
                    self.spec.funding_source_id,
                    f"{intervals:.4f} funding interval(s) over {horizon_minutes:.0f} min",
                )
            )

        total = sum(c.value_bps for c in components)
        if total < 0.0:
            raise ValueError("computed round-trip cost is negative; impossible")

        classes = {c.knowledge for c in components}
        overall: KnowledgeClass
        if classes <= {"KNOWN", "OBSERVED"}:
            overall = "OBSERVED" if "OBSERVED" in classes else "KNOWN"
        elif "ASSUMED" in classes:
            overall = "ASSUMED"
        else:
            overall = "ESTIMATED"

        return AllInCost(
            scenario_id=self.spec.scenario_id,
            venue=self.spec.venue,
            product=self.spec.product,
            size_usd=size_usd,
            liquidity_regime=liquidity_regime,
            horizon_minutes=horizon_minutes,
            entry_order_type=entry,
            exit_order_type=exit_,
            components=tuple(components),
            round_trip_bps=total,
            knowledge_class=overall,
            evidence=(
                f"fees {self.spec.fee_source_id}; spread {self.spec.spread_source_id}; "
                f"model {self.spec.scenario_id}"
            ),
        )


def default_model(scenario_id: str = ADMISSION_SCENARIO_ID) -> CostModelV3:
    if scenario_id not in VENUE_SPECS:
        raise KeyError(f"unknown scenario {scenario_id!r}")
    return CostModelV3(spec=VENUE_SPECS[scenario_id])


def cost_model_v3_all_in(
    spec: VenueSpec,
    size_usd: float = 1_000.0,
    liquidity_regime: LiquidityRegime = "normal",
    horizon_minutes: float = 25.0,
    entry_order_type: OrderType | None = None,
    exit_order_type: OrderType | None = None,
    base_slippage_bps: float = 1.0,
    base_impact_bps: float = 0.25,
    maker_adverse_selection_bps: float = 0.5,
    maker_fill_prob: float = 0.5,
    maker_partial_fill_penalty_bps: float = 0.25,
) -> AllInCost:
    """Convenience wrapper: build the model for ``spec`` and evaluate once.

    The model overrides are explicit rather than ``**kwargs`` so a typo can
    never be silently swallowed.
    """
    model = CostModelV3(
        spec=spec,
        base_slippage_bps=base_slippage_bps,
        base_impact_bps=base_impact_bps,
        maker_adverse_selection_bps=maker_adverse_selection_bps,
        maker_fill_prob=maker_fill_prob,
        maker_partial_fill_penalty_bps=maker_partial_fill_penalty_bps,
    )
    return model.evaluate(
        size_usd=size_usd,
        liquidity_regime=liquidity_regime,
        horizon_minutes=horizon_minutes,
        entry_order_type=entry_order_type,
        exit_order_type=exit_order_type,
    )


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def cost_stress_table(
    scenario_id: str = ADMISSION_SCENARIO_ID,
    *,
    size_usd: float = 1_000.0,
    liquidity_regime: LiquidityRegime = "normal",
    horizon_minutes: float = 25.0,
) -> list[dict[str, Any]]:
    """Minimum required gross edge at 1.0/1.25/1.5/2.0x for one scenario."""
    model = default_model(scenario_id)
    rows: list[dict[str, Any]] = []
    for multiple in COST_STRESS_MULTIPLES:
        cost = model.evaluate(
            size_usd=size_usd,
            liquidity_regime=liquidity_regime,
            horizon_minutes=horizon_minutes,
            entry_order_type="market",
            exit_order_type="market",
        )
        rows.append(
            {
                "scenario_id": scenario_id,
                "size_usd": size_usd,
                "liquidity_regime": liquidity_regime,
                "stress_multiple": multiple,
                "round_trip_cost_bps": round(cost.round_trip_bps * multiple, 4),
                "minimum_gross_edge_bps": round(cost.round_trip_bps * multiple, 4),
            }
        )
    return rows


def venue_matrix_rows(
    *,
    size_usd: float = 1_000.0,
    liquidity_regime: LiquidityRegime = "normal",
    horizon_minutes: float = 25.0,
) -> list[dict[str, Any]]:
    """One row per venue/product scenario, for VENUE_EXECUTION_MATRIX_V1.json."""
    rows: list[dict[str, Any]] = []
    for sid in scenario_ids():
        spec = VENUE_SPECS[sid]
        model = default_model(sid)
        taker = model.evaluate(
            size_usd=size_usd,
            liquidity_regime=liquidity_regime,
            horizon_minutes=horizon_minutes,
            entry_order_type="market",
            exit_order_type="market",
        )
        maker = model.evaluate(
            size_usd=size_usd,
            liquidity_regime=liquidity_regime,
            horizon_minutes=horizon_minutes,
            entry_order_type="limit_post_only",
            exit_order_type="limit_post_only",
        )
        rows.append(
            {
                "scenario_id": sid,
                "venue": spec.venue,
                "product": spec.product,
                "jurisdiction": spec.jurisdiction,
                "tier": spec.tier,
                "fee_payment_mode": spec.fee_payment_mode,
                "maker_fee_bps": spec.maker_fee_bps,
                "taker_fee_bps": spec.taker_fee_bps,
                "discount_program": spec.discount_program,
                "discount_applicability": spec.discount_applicability,
                "min_notional_usd": spec.min_notional_usd,
                "integration_status": spec.integration_status,
                "taker_rt_cost_bps": round(taker.round_trip_bps, 4),
                "maker_rt_cost_bps_theoretical": round(maker.round_trip_bps, 4),
                "taker_required_edge_bps_1p5x": round(taker.required_edge_bps(1.5), 4),
                "taker_stress_1p25x": round(taker.stress(1.25), 4),
                "taker_stress_1p5x": round(taker.stress(1.5), 4),
                "taker_stress_2x": round(taker.stress(2.0), 4),
                "knowledge_class": taker.knowledge_class,
                "fee_source_id": spec.fee_source_id,
                "spread_source_id": spec.spread_source_id,
                "funding_source_id": spec.funding_source_id,
                "notes": spec.notes,
            }
        )
    return rows
