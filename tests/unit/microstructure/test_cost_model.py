"""Tests for research COST_MODEL_V2 (§40, §64)."""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.cost_model import (
    ADMISSION_COST_MODEL,
    COST_MODEL_V2,
    REALISTIC_MAKER_COST_MODEL,
    REALISTIC_RETAIL_COST_MODEL,
    STRESS_COST_MODEL,
    CostScenario,
    component_table,
    cost_model_status,
)


def test_current_model_matches_legacy_12bps() -> None:
    assert COST_MODEL_V2["CURRENT_PROJECT_COST_MODEL"].round_trip_bps() == 12.0


def test_realistic_retail_round_trip() -> None:
    # 2 * (10 fee + 1 slip + 0.25 impact) + 1 spread = 23.5
    assert REALISTIC_RETAIL_COST_MODEL.round_trip_bps() == pytest.approx(23.5)


def test_stress_round_trip() -> None:
    # 2 * (10 + 3 + 1) + 2 = 30
    assert STRESS_COST_MODEL.round_trip_bps() == pytest.approx(30.0)


def test_required_edge_is_cost_times_multiple() -> None:
    assert ADMISSION_COST_MODEL.required_edge_bps(1.5) == pytest.approx(35.25)


def test_required_edge_rejects_multiple_below_one() -> None:
    with pytest.raises(ValueError):
        ADMISSION_COST_MODEL.required_edge_bps(0.5)


def test_maker_effective_cost_exceeds_filled_cost_when_partial() -> None:
    filled = REALISTIC_MAKER_COST_MODEL.round_trip_bps()
    eff = REALISTIC_MAKER_COST_MODEL.effective_maker_cost_bps(0.5)
    assert eff == pytest.approx(filled * 1.5)


def test_maker_effective_cost_full_fill_equals_round_trip() -> None:
    assert REALISTIC_MAKER_COST_MODEL.effective_maker_cost_bps(1.0) == pytest.approx(
        REALISTIC_MAKER_COST_MODEL.round_trip_bps()
    )


def test_negative_component_rejected() -> None:
    with pytest.raises(ValueError):
        CostScenario(
            name="bad", fee_bps_per_side=-1.0, spread_bps=0.0, slippage_bps_per_side=0.0
        )


def test_negative_funding_rejected() -> None:
    with pytest.raises(ValueError):
        CostScenario(
            name="bad", fee_bps_per_side=1.0, spread_bps=0.0,
            slippage_bps_per_side=0.0, funding_bps_per_day=-0.1,
        )


def test_fill_prob_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        CostScenario(
            name="bad", fee_bps_per_side=1.0, spread_bps=0.0,
            slippage_bps_per_side=0.0, maker_fill_prob=1.5,
        )


def test_no_rebate_baseline() -> None:
    # Non-negotiable: no scenario may assume a negative fee (rebate) as baseline.
    for scenario in COST_MODEL_V2.values():
        assert scenario.fee_bps_per_side >= 0.0


def test_cost_model_status_is_optimistic() -> None:
    assert cost_model_status() == "OPTIMISTIC"


def test_component_table_shape() -> None:
    rows = component_table()
    assert len(rows) == len(COST_MODEL_V2)
    for row in rows:
        assert "round_trip_bps" in row
        assert "required_edge_bps_1p5x" in row
