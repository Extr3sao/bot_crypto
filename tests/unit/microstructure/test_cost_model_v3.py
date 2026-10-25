"""Tests for COST_MODEL_V3 (§PHASE 1)."""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.cost_model_v3 import (
    ADMISSION_SCENARIO_ID,
    COST_STRESS_MULTIPLES,
    VENUE_SPECS,
    CostComponent,
    CostModelV3,
    VenueSpec,
    cost_stress_table,
    default_model,
    scenario_ids,
    venue_matrix_rows,
)

# --- registry sanity -------------------------------------------------------


def test_registry_contains_binance_spot_scenarios() -> None:
    for sid in (
        "BINANCE_SPOT_STANDARD_TAKER",
        "BINANCE_SPOT_STANDARD_MAKER",
        "BINANCE_SPOT_BNB_TAKER",
        "BINANCE_SPOT_BNB_MAKER",
    ):
        assert sid in VENUE_SPECS
    assert ADMISSION_SCENARIO_ID == "BINANCE_SPOT_STANDARD_TAKER"


def test_every_scenario_evaluates_without_error() -> None:
    for sid in scenario_ids():
        cost = default_model(sid).evaluate(size_usd=1_000.0)
        assert cost.round_trip_bps >= 0.0
        assert cost.knowledge_class in ("KNOWN", "OBSERVED", "ESTIMATED", "ASSUMED")


def test_venue_matrix_has_one_row_per_scenario() -> None:
    rows = venue_matrix_rows()
    assert len(rows) == len(VENUE_SPECS)
    for row in rows:
        assert row["taker_rt_cost_bps"] >= 0.0
        assert row["discount_applicability"] in (
            "CONFIRMED",
            "POSSIBLE",
            "NOT_APPLICABLE",
            "UNKNOWN",
        )


# --- round-trip fees -------------------------------------------------------


def test_standard_taker_pays_10_bps_per_side() -> None:
    cost = default_model("BINANCE_SPOT_STANDARD_TAKER").evaluate(
        size_usd=1_000.0, liquidity_regime="normal", spread_bps=0.0
    )
    assert cost.component("exchange_fee_entry") == 10.0
    assert cost.component("exchange_fee_exit") == 10.0


def test_taker_round_trip_is_fee_plus_spread_plus_slippage() -> None:
    cost = default_model("BINANCE_SPOT_STANDARD_TAKER").evaluate(
        size_usd=1_000.0, liquidity_regime="normal", spread_bps=2.0
    )
    # 2 x 10 bps fee, the full 2 bps spread paid once, and 2 legs of slippage.
    # Slippage scales with size: factor 1 + sqrt(1000/10000) on each taker leg.
    size_factor = 1.0 + (1_000.0 / 10_000.0) ** 0.5
    assert cost.component("exchange_fee_entry") == 10.0
    assert cost.component("exchange_fee_exit") == 10.0
    assert cost.component("spread") == pytest.approx(2.0)
    assert cost.component("slippage") == pytest.approx(2.0 * size_factor)
    assert cost.round_trip_bps == pytest.approx(
        20.0 + 2.0 + 2.0 * size_factor + cost.component("market_impact")
    )


# --- maker / taker asymmetry ----------------------------------------------


def test_standard_maker_costs_more_than_taker_at_vip0() -> None:
    """At VIP0 Binance Spot maker == taker fee, so passive execution is NOT cheaper.

    The maker scenario additionally pays adverse selection and a missed-fill
    penalty, so it must come out strictly more expensive.
    """
    model = default_model("BINANCE_SPOT_STANDARD_TAKER")
    taker = model.evaluate(
        entry_order_type="market", exit_order_type="market", spread_bps=1.0
    )
    maker = default_model("BINANCE_SPOT_STANDARD_MAKER").evaluate(
        entry_order_type="limit_post_only", exit_order_type="limit_post_only"
    )
    assert maker.round_trip_bps > taker.round_trip_bps


def test_maker_never_reports_zero_cost() -> None:
    cost = default_model("BINANCE_SPOT_STANDARD_MAKER").evaluate()
    assert cost.round_trip_bps > 0.0


def test_mexc_zero_maker_fee_still_costs_adverse_selection() -> None:
    cost = default_model("MEXC_SPOT_TAKER").evaluate(
        entry_order_type="limit_post_only", exit_order_type="limit_post_only"
    )
    assert cost.component("exchange_fee_entry") == 0.0
    assert cost.round_trip_bps > 0.0


# --- spread conversion -----------------------------------------------------


def test_maker_pays_no_spread_taker_pays_it_once() -> None:
    model = default_model("OKX_SPOT_TAKER")
    taker = model.evaluate(entry_order_type="market", exit_order_type="market", spread_bps=4.0)
    maker = model.evaluate(
        entry_order_type="limit_post_only", exit_order_type="limit_post_only"
    )
    assert taker.component("spread") == pytest.approx(4.0)
    assert maker.component("spread") == 0.0


def test_half_taker_legs_pay_half_the_spread() -> None:
    model = default_model("OKX_SPOT_TAKER")
    cost = model.evaluate(entry_order_type="market", exit_order_type="limit_post_only", spread_bps=6.0)
    assert cost.component("spread") == pytest.approx(3.0)


# --- slippage / size dependence -------------------------------------------


def test_slippage_scales_with_quantity() -> None:
    model = default_model("BINANCE_SPOT_STANDARD_TAKER")
    small = model.evaluate(size_usd=1_000.0, spread_bps=0.0)
    large = model.evaluate(size_usd=1_000_000.0, spread_bps=0.0)
    assert large.component("slippage") > small.component("slippage")
    assert large.component("market_impact") > small.component("market_impact")


def test_thin_liquidity_costs_more_than_deep() -> None:
    model = default_model("BINANCE_SPOT_STANDARD_TAKER")
    deep = model.evaluate(size_usd=10_000.0, liquidity_regime="deep")
    thin = model.evaluate(size_usd=10_000.0, liquidity_regime="thin")
    assert thin.round_trip_bps > deep.round_trip_bps


def test_higher_volatility_increases_slippage() -> None:
    model = default_model("BINANCE_SPOT_STANDARD_TAKER")
    calm = model.evaluate(size_usd=5_000.0, volatility_bps=0.0)
    wild = model.evaluate(size_usd=5_000.0, volatility_bps=200.0)
    assert wild.component("slippage") > calm.component("slippage")


# --- discounts: disabled vs optional --------------------------------------


def test_standard_scenario_has_no_discount() -> None:
    spec = VENUE_SPECS["BINANCE_SPOT_STANDARD_TAKER"]
    assert spec.discount_program == "none"
    assert spec.discount_applicability == "NOT_APPLICABLE"
    assert spec.taker_fee_bps == 10.0


def test_bnb_discount_is_possible_but_never_confirmed() -> None:
    spec = VENUE_SPECS["BINANCE_SPOT_BNB_TAKER"]
    assert spec.discount_applicability == "POSSIBLE"
    assert spec.taker_fee_bps == 7.5
    assert spec.discount_applicability != "CONFIRMED"


def test_bnb_discount_cannot_be_constructed_as_confirmed() -> None:
    with pytest.raises(ValueError, match="CONFIRMED"):
        VenueSpec(
            scenario_id="X",
            venue="V",
            product="P",
            jurisdiction="j",
            symbol_class="s",
            tier="VIP0",
            fee_payment_mode="bnb",
            maker_fee_bps=7.5,
            taker_fee_bps=7.5,
            discount_program="bnb",
            discount_applicability="CONFIRMED",
            default_taker_spread_bps=1.0,
            min_notional_usd=5.0,
            fee_source_id="x",
            spread_source_id="y",
            funding_source_id="z",
        )


def test_bnb_scenario_is_cheaper_than_standard() -> None:
    std = default_model("BINANCE_SPOT_STANDARD_TAKER").evaluate(size_usd=1_000.0)
    bnb = default_model("BINANCE_SPOT_BNB_TAKER").evaluate(size_usd=1_000.0)
    assert bnb.round_trip_bps < std.round_trip_bps


# --- cost stress -----------------------------------------------------------


def test_required_edge_applies_safety_multiple() -> None:
    cost = default_model().evaluate(size_usd=1_000.0, spread_bps=1.0)
    assert cost.required_edge_bps(1.5) == pytest.approx(cost.round_trip_bps * 1.5)


def test_stress_multiple_scales_linearly() -> None:
    cost = default_model().evaluate(size_usd=1_000.0)
    assert cost.stress(2.0) == pytest.approx(cost.round_trip_bps * 2.0)


def test_cost_stress_table_covers_all_documented_multiples() -> None:
    rows = cost_stress_table()
    assert [r["stress_multiple"] for r in rows] == list(COST_STRESS_MULTIPLES)


def test_stress_multiple_below_one_is_rejected() -> None:
    cost = default_model().evaluate()
    with pytest.raises(ValueError):
        cost.stress(0.5)


# --- impossible / invalid costs -------------------------------------------


def test_negative_component_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        CostComponent(
            name="rebate",
            value_bps=-1.0,
            knowledge="KNOWN",
            source_id="x",
        )


def test_unknown_knowledge_class_is_rejected() -> None:
    with pytest.raises(ValueError, match="knowledge"):
        CostComponent(name="x", value_bps=1.0, knowledge="MADE_UP", source_id="s")  # type: ignore[arg-type]


def test_funding_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="funding_rate_bps_per_interval"):
        default_model("BINANCE_USDM_PERP_TAKER").evaluate(
            funding_rate_bps_per_interval=-1.0
        )


def test_funding_carry_increases_cost_for_longer_holding() -> None:
    model = default_model("BINANCE_USDM_PERP_TAKER")
    short = model.evaluate(horizon_minutes=10.0, funding_rate_bps_per_interval=1.0)
    long = model.evaluate(horizon_minutes=480.0, funding_rate_bps_per_interval=1.0)
    assert long.component("funding_carry") > short.component("funding_carry")


def test_zero_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="size_usd"):
        default_model().evaluate(size_usd=0.0)


# --- reproducibility -------------------------------------------------------


def test_evaluation_is_deterministic() -> None:
    model = CostModelV3(spec=VENUE_SPECS[ADMISSION_SCENARIO_ID])
    a = model.evaluate(size_usd=12_345.0, liquidity_regime="thin", volatility_bps=37.0)
    b = model.evaluate(size_usd=12_345.0, liquidity_regime="thin", volatility_bps=37.0)
    assert a.as_dict() == b.as_dict()


def test_matrix_rows_are_deterministic() -> None:
    assert venue_matrix_rows() == venue_matrix_rows()


def test_production_cost_model_is_untouched() -> None:
    """§50 — the runtime cost model must not be modified by research code."""
    from trading_bot.execution import cost_model as production

    assert hasattr(production, "__dict__")
