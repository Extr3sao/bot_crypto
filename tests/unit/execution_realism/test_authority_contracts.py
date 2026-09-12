import json

from trading_bot.execution_realism.cost_authority import (
    BINANCE_USDM_VIP0,
    CostComponent,
    CostScenario,
    CostScenarioKind,
    Confidence,
    ExecutionCostAuthority,
)
from trading_bot.execution_realism.realism_estimate import ExecutionRealismEstimate, OrderType


def test_profile_fingerprint_deterministic():
    assert BINANCE_USDM_VIP0.fingerprint() == BINANCE_USDM_VIP0.fingerprint()
    assert len(BINANCE_USDM_VIP0.fingerprint()) == 16


def test_authority_serializes_and_fingerprints_deterministically():
    auth = ExecutionCostAuthority(
        authority_id="ER-AUTH-BTCUSDT-VIP0-20260101",
        provider="binance",
        market="usdm",
        asset="BTCUSDT",
        profile=BINANCE_USDM_VIP0,
        valid_from="2026-01-01",
        valid_to="present",
        scenarios=(
            CostScenario(
                kind=CostScenarioKind.IDEALIZED,
                label="fees only",
                components=(
                    CostComponent("exchange_fees", 10.0, Confidence.HIGH, "OFFICIAL_EXCHANGE_DOC:binance.com/fee/futureFee"),
                ),
                confidence=Confidence.HIGH,
            ),
        ),
        source_refs=("OFFICIAL_EXCHANGE_DOC:binance.com/fee/futureFee",),
        limitations="VIP0 taker+taker; 10% BNB variant separate",
    )
    d1 = auth.to_dict()
    d2 = auth.to_dict()
    assert d1 == d2
    assert auth.fingerprint() == auth.fingerprint()
    # Valid JSON round-trip
    assert json.loads(json.dumps(d1)) == d1
    assert auth.scenario(CostScenarioKind.IDEALIZED) is not None
    assert auth.scenario(CostScenarioKind.BASE) is None


def test_realism_estimate_rejects_bad_direction():
    try:
        ExecutionRealismEstimate.build(
            asset="BTCUSDT", direction="sideways", order_type=OrderType.MARKET,
            notional_usdt=100, holding_period="1h",
            fee_cost_bps=10.0, spread_cost_bps=1.0, slippage_bps=1.0, impact_bps=0.0, funding_bps=0.0,
        )
        assert False, "should have raised"
    except ValueError:
        pass


def test_cost_component_is_known():
    assert CostComponent("fees", 10.0).is_known()
    assert not CostComponent("spread", None).is_known()


def test_scenario_derived_total_with_unknown_is_none():
    s = CostScenario(
        kind=CostScenarioKind.BASE,
        label="base",
        components=(
            CostComponent("exchange_fees", 10.0, Confidence.HIGH, "x"),
            CostComponent("spread", None, Confidence.UNKNOWN, "unknown"),
        ),
    )
    assert s.derived_total() is None


def test_scenario_derived_total_when_all_known():
    s = CostScenario(
        kind=CostScenarioKind.BASE,
        label="base",
        components=(
            CostComponent("exchange_fees", 10.0, Confidence.HIGH, "x"),
            CostComponent("spread", 1.0, Confidence.MEDIUM, "y"),
        ),
    )
    assert s.derived_total() == 11.0
