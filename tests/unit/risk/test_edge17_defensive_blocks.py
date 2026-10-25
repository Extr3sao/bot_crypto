"""WP-EDGE-017/P0.4 — the four declared blocks are evaluated, and fail closed.

``config/risk.yaml`` declared an excessive-spread block, an extreme-ATR block, a
high-latency block and a weekend block, and WP-EDGE-016's audit found that no
runtime component read any of them. These tests pin the evaluation: each rule
fires at its declared threshold, an unmeasured input blocks rather than passes,
and the canonical cycle records the block and creates no order.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_bot.config.risk import DefensiveBlocks, Risk
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.risk.defensive_blocks import MarketConditions, evaluate_blocks
from trading_bot.risk.manager import RiskManager

BLOCKS = DefensiveBlocks(
    excessive_spread_bps=50,
    extreme_atr_pct=8.0,
    high_latency_ms=2_000,
    weekend_trading=False,
)
WEDNESDAY = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday
SATURDAY = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _calm(**overrides: object) -> MarketConditions:
    payload: dict[str, object] = {
        "at": WEDNESDAY,
        "spread_bps": 5.0,
        "atr_pct": 1.0,
        "latency_ms": 200.0,
    }
    payload.update(overrides)
    return MarketConditions(**payload)  # type: ignore[arg-type]


def test_calm_conditions_pass() -> None:
    verdict = evaluate_blocks(BLOCKS, _calm())
    assert verdict.blocked is False
    assert verdict.blocked_by is None


def test_spread_block_fires_at_the_declared_threshold() -> None:
    assert evaluate_blocks(BLOCKS, _calm(spread_bps=50.0)).blocked is False
    verdict = evaluate_blocks(BLOCKS, _calm(spread_bps=50.1))
    assert verdict.blocked is True
    assert verdict.blocked_by == "excessive_spread_bps"


def test_atr_block_fires_at_the_declared_threshold() -> None:
    assert evaluate_blocks(BLOCKS, _calm(atr_pct=8.0)).blocked is False
    verdict = evaluate_blocks(BLOCKS, _calm(atr_pct=12.5))
    assert verdict.blocked is True
    assert verdict.blocked_by == "extreme_atr_pct"


def test_latency_block_fires_at_the_declared_threshold() -> None:
    assert evaluate_blocks(BLOCKS, _calm(latency_ms=2_000.0)).blocked is False
    verdict = evaluate_blocks(BLOCKS, _calm(latency_ms=2_001.0))
    assert verdict.blocked is True
    assert verdict.blocked_by == "high_latency_ms"


def test_weekend_block_follows_the_policy_and_not_the_caller() -> None:
    verdict = evaluate_blocks(BLOCKS, _calm(at=SATURDAY))
    assert verdict.blocked is True
    assert verdict.blocked_by == "weekend_trading"

    # the flag is the policy: this asserts the evaluator reads it, it does not
    # change config/risk.yaml
    permissive = DefensiveBlocks(
        excessive_spread_bps=50,
        extreme_atr_pct=8.0,
        high_latency_ms=2_000,
        weekend_trading=True,
    )
    assert evaluate_blocks(permissive, _calm(at=SATURDAY)).blocked is False


@pytest.mark.parametrize(
    "missing, expected",
    [
        ("spread_bps", "spread_unknown"),
        ("atr_pct", "atr_unknown"),
        ("latency_ms", "latency_unknown"),
    ],
)
def test_an_unmeasured_condition_blocks(missing: str, expected: str) -> None:
    verdict = evaluate_blocks(BLOCKS, _calm(**{missing: None}))
    assert verdict.blocked is True
    assert verdict.blocked_by == expected


def test_no_conditions_at_all_blocks() -> None:
    verdict = evaluate_blocks(BLOCKS, None)
    assert verdict.blocked is True
    assert verdict.blocked_by == "market_conditions_unknown"


def test_the_verdict_publishes_the_inputs_it_used() -> None:
    verdict = evaluate_blocks(BLOCKS, _calm(spread_bps=51.0))
    observed = verdict.observed or {}
    assert observed["spread_bps"] == 51.0
    assert observed["declared"]["excessive_spread_bps"] == 50
    assert verdict.as_dict()["blocked_by"] == "excessive_spread_bps"


# -- the canonical cycle honours the verdict --------------------------------------------


def _engine() -> PaperCycleEngine:
    policy = Risk(
        max_risk_per_trade_pct=0.25,
        max_daily_loss_pct=1.0,
        max_weekly_loss_pct=3.0,
        max_daily_drawdown_pct=2.0,
        max_total_drawdown_pct=5.0,
        max_open_positions=3,
        max_trades_per_day=20,
        max_consecutive_losses=3,
        max_asset_exposure_pct=10,
        max_total_exposure_pct=25,
        min_order_notional_usdt=20,
        max_order_notional_usdt=500,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=0.75,
        blocks=BLOCKS,
    )
    return PaperCycleEngine(
        asset_registry=object(),  # type: ignore[arg-type]
        router=object(),  # type: ignore[arg-type]
        strategy_map={},
        families={},
        risk_manager=RiskManager(risk=policy, equity=10_000.0, _clock=lambda: 1.0),
        broker=object(),
        defensive_blocks=BLOCKS,
    )


def test_the_cycle_blocks_on_measured_conditions_and_records_the_rule() -> None:
    engine = _engine()
    verdict = engine._defensive_verdict("BTC/USDT", {"BTC/USDT": _calm(spread_bps=80.0)})
    assert verdict is not None and verdict.blocked is True
    assert verdict.blocked_by == "excessive_spread_bps"


def test_the_cycle_blocks_a_symbol_with_no_conditions() -> None:
    engine = _engine()
    verdict = engine._defensive_verdict("BTC/USDT", {})
    assert verdict is not None and verdict.blocked is True
    assert verdict.blocked_by == "market_conditions_unknown"


def test_an_engine_without_the_policy_keeps_its_historical_behaviour() -> None:
    engine = _engine()
    engine._defensive_blocks = None
    assert engine._defensive_verdict("BTC/USDT", {}) is None
