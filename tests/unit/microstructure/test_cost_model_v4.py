"""EXECUTION_COST_MODEL_V4 tests.

The point of V4 is that the per-asset inputs are *measurements with provenance*
rather than a flat majors constant, so the tests check three things:

1. the per-asset spread/volatility really do reach the V3 arithmetic;
2. break-even, required edge and stress stay in a coherent relationship;
3. an unobserved spread cannot be smuggled in as zero, and the maker row can
   never be promoted.
"""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.cost_model_v3 import ADMISSION_SCENARIO_ID
from trading_bot.research.microstructure.cost_model_v4 import (
    ADMISSION_SAFETY_MULTIPLE,
    COST_MODEL_V4_VERSION,
    MAKER_STATUS_EXECUTION_DEPENDENT,
    AssetMarketInput,
    asset_cost_v4,
    execution_cost_model_v4,
    required_gross_edge_bps,
)


def _market(asset: str = "BTC", spread: float = 0.001, vol: float = 8.0) -> AssetMarketInput:
    return AssetMarketInput(
        asset=asset,
        symbol=f"{asset}USDT",
        observed_spread_bps=spread,
        spread_observations=42,
        spread_source="reports/microstructure-v2/forward/forward_test.jsonl",
        realized_vol_bps=vol,
        vol_source="reports/microstructure-v1/data/KLINES_BTCUSDT_5m.json",
    )


# --- input validation ------------------------------------------------------


def test_market_input_rejects_negative_spread() -> None:
    with pytest.raises(ValueError, match="observed_spread_bps"):
        AssetMarketInput(
            asset="BTC",
            symbol="BTCUSDT",
            observed_spread_bps=-1.0,
            spread_observations=1,
            spread_source="s",
            realized_vol_bps=1.0,
            vol_source="v",
        )


def test_market_input_rejects_unobserved_spread() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        AssetMarketInput(
            asset="BTC",
            symbol="BTCUSDT",
            observed_spread_bps=0.0,
            spread_observations=0,
            spread_source="s",
            realized_vol_bps=1.0,
            vol_source="v",
        )


def test_market_input_requires_provenance_for_both_numbers() -> None:
    with pytest.raises(ValueError, match="spread_source"):
        AssetMarketInput(
            asset="BTC",
            symbol="BTCUSDT",
            observed_spread_bps=1.0,
            spread_observations=2,
            spread_source="",
            realized_vol_bps=1.0,
            vol_source="v",
        )
    with pytest.raises(ValueError, match="vol_source"):
        AssetMarketInput(
            asset="BTC",
            symbol="BTCUSDT",
            observed_spread_bps=1.0,
            spread_observations=2,
            spread_source="s",
            realized_vol_bps=1.0,
            vol_source="",
        )


def test_market_input_rejects_empty_asset() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        AssetMarketInput(
            asset="",
            symbol="BTCUSDT",
            observed_spread_bps=1.0,
            spread_observations=1,
            spread_source="s",
            realized_vol_bps=1.0,
            vol_source="v",
        )


# --- required edge arithmetic ----------------------------------------------


def test_required_gross_edge_applies_the_safety_multiple() -> None:
    assert required_gross_edge_bps(20.0) == pytest.approx(20.0 * ADMISSION_SAFETY_MULTIPLE)
    assert required_gross_edge_bps(20.0, 2.0) == pytest.approx(40.0)


def test_required_gross_edge_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="round_trip_bps"):
        required_gross_edge_bps(-1.0)
    with pytest.raises(ValueError, match="safety_multiple"):
        required_gross_edge_bps(10.0, 0.5)


def test_asset_cost_rejects_unknown_scenario() -> None:
    with pytest.raises(KeyError, match="NOPE"):
        asset_cost_v4(_market(), scenario_id="NOPE")


def test_asset_cost_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="size_usd"):
        asset_cost_v4(_market(), size_usd=0.0)


# --- per-asset arithmetic --------------------------------------------------


def test_asset_cost_breakdown_sums_to_round_trip() -> None:
    cost = asset_cost_v4(_market())
    parts = (
        cost.fee_bps
        + cost.spread_bps
        + cost.slippage_impact_bps
        + cost.funding_carry_bps
        + cost.other_bps
    )
    assert parts == pytest.approx(cost.taker_round_trip_bps)


def test_asset_cost_is_internally_coherent() -> None:
    cost = asset_cost_v4(_market())
    assert cost.minimum_gross_edge_bps == pytest.approx(cost.taker_round_trip_bps)
    assert cost.required_gross_edge_bps == pytest.approx(
        cost.taker_round_trip_bps * ADMISSION_SAFETY_MULTIPLE
    )
    assert cost.required_gross_edge_bps > cost.taker_round_trip_bps
    assert cost.stress_bps["1.25x"] < cost.stress_bps["1.5x"] < cost.stress_bps["2.0x"]
    assert cost.scenario_id == ADMISSION_SCENARIO_ID


def test_wider_spread_costs_more_for_the_same_asset() -> None:
    tight = asset_cost_v4(_market("BTC", spread=0.001))
    wide = asset_cost_v4(_market("BTC", spread=2.0))
    assert wide.taker_round_trip_bps > tight.taker_round_trip_bps
    assert wide.spread_bps > tight.spread_bps


def test_higher_volatility_costs_more_for_the_same_asset() -> None:
    calm = asset_cost_v4(_market("BTC", vol=1.0))
    wild = asset_cost_v4(_market("BTC", vol=120.0))
    assert wild.taker_round_trip_bps > calm.taker_round_trip_bps


def test_larger_size_costs_more_than_smaller_size() -> None:
    small = asset_cost_v4(_market(), size_usd=100.0)
    large = asset_cost_v4(_market(), size_usd=100_000.0)
    assert large.taker_round_trip_bps > small.taker_round_trip_bps


def test_asset_cost_is_serializable_and_keeps_component_audit_trail() -> None:
    cost = asset_cost_v4(_market())
    payload = cost.as_dict()
    assert payload["asset"] == "BTC"
    assert payload["components_bps"]["fee"] > 0.0
    assert isinstance(payload["components"], list) and payload["components"]
    assert payload["maker_status"] == MAKER_STATUS_EXECUTION_DEPENDENT


def test_maker_row_is_never_cheaper_by_assumption() -> None:
    cost = asset_cost_v4(_market())
    # At Binance Spot VIP0 maker == taker, so the maker row cannot undercut the
    # taker row by a fee rebate that does not exist.
    assert cost.maker_round_trip_bps_theoretical >= cost.taker_round_trip_bps - 1e-9
    assert cost.maker_status == MAKER_STATUS_EXECUTION_DEPENDENT
    assert "no FillEvidence" in cost.maker_note or "does not reduce the fee" in cost.maker_note


# --- model payload ---------------------------------------------------------


def test_model_payload_is_deterministic_and_multi_asset() -> None:
    markets = [_market("BTC"), _market("ETH", spread=0.04, vol=10.0), _market("SOL", spread=0.83, vol=18.0)]
    first = execution_cost_model_v4(markets)
    second = execution_cost_model_v4(markets)
    assert first == second
    assert first["model"] == COST_MODEL_V4_VERSION
    assert [row["asset"] for row in first["assets"]] == ["BTC", "ETH", "SOL"]
    assert first["maker_gate"]["status"] == "FAIL"
    assert first["maker_gate"]["fill_evidence_available"] is False
    assert len(first["asset_market_inputs"]) == 3


def test_model_payload_rejects_empty_and_duplicate_assets() -> None:
    with pytest.raises(ValueError, match="at least one"):
        execution_cost_model_v4([])
    with pytest.raises(ValueError, match="duplicate"):
        execution_cost_model_v4([_market("BTC"), _market("BTC")])


def test_model_payload_reports_per_asset_ordering_for_real_spreads() -> None:
    markets = [
        _market("BTC", spread=0.001, vol=8.0),
        _market("SOL", spread=0.833, vol=25.0),
    ]
    total = {
        row["asset"]: row["taker_round_trip_bps"]
        for row in execution_cost_model_v4(markets)["assets"]
    }
    assert total["SOL"] > total["BTC"]
