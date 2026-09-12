import pytest

from trading_bot.execution.cost_model import ExecutionCostModel
from trading_bot.execution_realism.cost_authority import (
    BINANCE_USDM_VIP0,
    BINANCE_USDM_VIP0_BNB,
)
from trading_bot.execution_realism.funding import funding_cost_bps, funding_cost_usdt, funding_events_in_holding
from trading_bot.execution_realism.realism_estimate import ExecutionRealismEstimate, OrderType
from trading_bot.execution_realism.false_profitability import (
    ExecutionCostInput,
    ProfitabilityVerdict,
    StrategyCostInput,
    classify,
)


def test_bps_conversions_are_exact():
    assert ExecutionCostModel.bps_to_decimal(5) == 0.0005
    assert ExecutionCostModel.bps_to_percent(5) == 0.05
    assert ExecutionCostModel.percent_to_bps(0.05) == 5.0


def test_fiat_fees_are_notional_times_decimal():
    m = ExecutionCostModel(commission_bps=5, slippage_bps=1)
    assert m.entry_commission_usdt(10_000.0) == pytest.approx(5.0)
    assert m.exit_commission_usdt(10_000.0) == pytest.approx(5.0)


def test_binance_profiles_round_trip():
    assert BINANCE_USDM_VIP0.round_trip_bps() == pytest.approx(10.0)  # taker+taker
    assert BINANCE_USDM_VIP0.round_trip_bps(maker_maker=True) == pytest.approx(4.0)
    assert BINANCE_USDM_VIP0_BNB.round_trip_bps() == pytest.approx(9.0)
    assert BINANCE_USDM_VIP0_BNB.round_trip_bps(maker_maker=True) == pytest.approx(3.6)


def test_long_short_fee_symmetry():
    m = ExecutionCostModel(commission_bps=5, slippage_bps=1)
    long = m.compute_costs(notional_usdt=10_000, entry_price=100, exit_price=101, quantity=100, side="buy")
    short = m.compute_costs(notional_usdt=10_000, entry_price=101, exit_price=100, quantity=100, side="sell")
    # Fees are symmetric per notional
    assert long.entry_fee_usdt == short.entry_fee_usdt == pytest.approx(5.0)
    assert long.exit_fee_usdt == short.exit_fee_usdt == pytest.approx(5.0)
    # Gross pnls opposite sign but same magnitude for mirrored prices
    assert abs(long.gross_pnl) == pytest.approx(abs(short.gross_pnl))


def test_funding_long_pays_positive_rate():
    assert funding_cost_usdt(position_notional=10_000, direction="long", funding_rate=0.0001, held_across_funding_event=True) == pytest.approx(1.0)
    assert funding_cost_usdt(position_notional=10_000, direction="short", funding_rate=0.0001, held_across_funding_event=True) == pytest.approx(-1.0)
    assert funding_cost_usdt(position_notional=10_000, direction="long", funding_rate=0.0001, held_across_funding_event=False) == 0.0
    assert funding_cost_bps(funding_rate=0.0001, held_across_funding_event=True) == pytest.approx(1.0)
    assert funding_cost_bps(funding_rate=0.0001, held_across_funding_event=False) == 0.0


def test_funding_events_in_one_hour_holding():
    # Entry 07:00, exit 08:00 — straddles 08:00 funding => 1 event
    assert funding_events_in_holding(entry_ms=7*3600*1000, exit_ms=8*3600*1000) == 1
    # Entry 00:30, exit 01:30 — no boundary
    assert funding_events_in_holding(entry_ms=30*60*1000, exit_ms=90*60*1000) == 0
    # Entry at funding instant exclusive: 08:00 to 09:00 => 0 (next is 16:00)
    assert funding_events_in_holding(entry_ms=8*3600*1000, exit_ms=9*3600*1000) == 0


def test_realism_estimate_unknown_propagation():
    est = ExecutionRealismEstimate.build(
        asset="BTCUSDT", direction="long", order_type=OrderType.MARKET,
        notional_usdt=500, holding_period="1h",
        fee_cost_bps=10.0, spread_cost_bps=None, slippage_bps=None,
        impact_bps=0.0, funding_bps=0.0,
    )
    assert est.total_cost_bps is None
    assert set(est.missing_components) == {"spread", "slippage"}
    assert est.net_edge_bps(50.0) is None


def test_realism_estimate_total_when_known():
    est = ExecutionRealismEstimate.build(
        asset="BTCUSDT", direction="long", order_type=OrderType.MARKET,
        notional_usdt=500, holding_period="1h",
        fee_cost_bps=10.0, spread_cost_bps=0.7, slippage_bps=1.0,
        impact_bps=0.0, funding_bps=0.0,
    )
    assert est.total_cost_bps == pytest.approx(11.7)
    assert est.missing_components == ()
    assert est.net_edge_bps(20.0) == pytest.approx(8.3)


def test_false_profitability_detector():
    # Gross negative => GROSS_NEGATIVE regardless of costs
    assert classify(StrategyCostInput(gross_edge_bps=-5.0), ExecutionCostInput(base_cost_bps=10.0)) == ProfitabilityVerdict.GROSS_NEGATIVE
    # Unknown costs => INSUFFICIENT
    assert classify(StrategyCostInput(gross_edge_bps=50.0), ExecutionCostInput(base_cost_bps=None, is_unknown=True)) == ProfitabilityVerdict.INSUFFICIENT_EXECUTION_EVIDENCE
    # Negative after base
    assert classify(StrategyCostInput(gross_edge_bps=5.0), ExecutionCostInput(base_cost_bps=10.0)) == ProfitabilityVerdict.NEGATIVE_AFTER_COSTS
    # Cost sensitive: base ok but stressed fails
    assert classify(StrategyCostInput(gross_edge_bps=50.0), ExecutionCostInput(base_cost_bps=10.0, stressed_cost_bps=60.0)) == ProfitabilityVerdict.COST_SENSITIVE
    # Robust: all pass
    assert classify(StrategyCostInput(gross_edge_bps=50.0), ExecutionCostInput(base_cost_bps=10.0, stressed_cost_bps=20.0, severe_cost_bps=30.0)) == ProfitabilityVerdict.ROBUST_POSITIVE
