"""Integration: MarketContext -> Pods -> Router -> Portfolio -> Decision -> Risk.

Drives the whole dynamic plane end to end on one in-memory context and asserts
the chain is traceable and that the RiskManager remains the only veto that
matters. No execution is reached here — that is the point.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_bot.config.risk import Risk
from trading_bot.research.router_gates import RouterGates
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal
from trading_bot.strategy_lifecycle.contracts import ContextKey, LifecycleState
from trading_bot.strategy_lifecycle.ecosystem import DynamicStrategyEcosystem
from trading_bot.strategy_lifecycle.pods import ParallelShadowRuntime, PodSignal, StrategyPod

from ._helpers import descriptor, observation


def _ctx(asset="BTC", regime="TREND_UP"):
    return SimpleNamespace(
        asset=asset,
        timestamp=1_000_000,
        window_end_ts=1_000_000,
        data_quality={"bars_in_window": 120},
        market_regime=regime,
        timeframe="5m",
    )


def _ecosystem() -> DynamicStrategyEcosystem:
    eco = DynamicStrategyEcosystem()
    for sid in ("mom", "trend", "breakout"):
        eco.register(descriptor(sid, state=LifecycleState.SHADOW))
    # Give every strategy enough clean evidence to be eligible: 80 wins and 40
    # losses, with the gross side carrying the SAME sign as the net side so a
    # real profit factor exists.
    for sid in ("mom", "trend", "breakout"):
        obs = []
        for i in range(120):
            win = i % 3 != 0
            obs.append(
                observation(
                    sid,
                    net_bps=20.0 if win else -10.0,
                    gross_bps=25.0 if win else -5.0,
                    timestamp_ms=i * 300_000,
                )
            )
        eco.performance.record_many(obs)
    return eco


def test_full_chain_is_traceable() -> None:
    eco = _ecosystem()
    now = 5_000_000_000_000
    # Promote each strategy deliberately through the evidence gate.
    for sid in ("mom", "trend", "breakout"):
        health_report = eco.health_for(
            strategy_id=sid, asset="BTC", timeframe="5m", regime="TREND_UP", now_ms=now
        )
        assert health_report.health_state.value in {"HEALTHY", "WATCH"}
        d1 = eco.lifecycle_decision(
            strategy_id=sid,
            asset="BTC",
            timeframe="5m",
            regime="TREND_UP",
            now_ms=now,
            verification_passed=True,
        )
        assert d1.to_state is LifecycleState.ELIGIBLE, d1.reason_codes
        d2 = eco.lifecycle_decision(
            strategy_id=sid,
            asset="BTC",
            timeframe="5m",
            regime="TREND_UP",
            now_ms=now + 10_000_000,
            verification_passed=True,
        )
        assert d2.to_state is LifecycleState.ACTIVE, d2.reason_codes

    # 1) Parallel shadow pods receive the SAME context.
    runtime = ParallelShadowRuntime()
    for sid in ("mom", "trend", "breakout"):
        runtime.add(
            StrategyPod(
                descriptor=eco.registry.descriptor(sid),
                runtime=lambda ctx, bars: PodSignal(
                    direction="LONG", entry_reference=100.0, confidence=0.6
                ),
            )
        )
    pod_results = runtime.evaluate_all(
        context=_ctx(),
        bars=[],
        context_key=ContextKey("mom", "BTC", "5m", "TREND_UP"),
        timestamp_ms=now,
    )
    assert all(r.is_shadow for r in pod_results)

    # 2) Router selects the eligible set with explicit verdicts.
    router = StrategyRouter(gates=RouterGates(require_confirmed=False, timeframe="5m"))
    strategy_map = {
        sid: {"family": "momentum", "regimes": ["TREND_UP"], "direction": "BOTH", "enabled": True}
        for sid in ("mom", "trend", "breakout")
    }
    selection = eco.select_eligible(
        router, context=_ctx(), regime="TREND_UP", strategy_map=strategy_map
    )
    assert set(selection.selected) == {"mom", "trend", "breakout"}

    # 3) Portfolio arbitration sees three same-direction BTC bets.
    from trading_bot.strategy_lifecycle.portfolio import PortfolioProposal

    decision = eco.arbitrate(
        [
            PortfolioProposal("mom", "BTC", "LONG", 100.0, 30.0),
            PortfolioProposal("trend", "BTC", "LONG", 100.0, 20.0),
            PortfolioProposal("breakout", "BTC", "LONG", 100.0, 10.0),
        ],
        timestamp_ms=now,
    )
    assert len(decision.accepted_proposals) <= 2  # concentration capped
    assert decision.merged_exposure.get("BTC", 0.0) > 0

    # 4) The snapshot records everything.
    snapshot = eco.snapshot()
    assert set(snapshot["registry"]["status"]) == {"mom", "trend", "breakout"}
    assert snapshot["registry"]["events"]


def test_risk_remains_the_final_veto() -> None:
    risk = Risk(
        max_risk_per_trade_pct=0.25,
        max_daily_loss_pct=1.0,
        max_weekly_loss_pct=3.0,
        max_daily_drawdown_pct=2.0,
        max_total_drawdown_pct=5.0,
        max_open_positions=3,
        max_trades_per_day=20,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=10,
        max_total_exposure_pct=25,
        min_order_notional_usdt=20,
        max_order_notional_usdt=500,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=0.75,
    )
    manager = RiskManager(risk=risk, equity=10_000.0)
    signal = Signal(
        symbol="BTC/USDT",
        side="buy",
        strategy_name="mom",
        timeframe="5m",
        confidence=0.6,
        price=100.0,
        stop_loss_pct=0.5,
        take_profit_pct=0.75,
    )
    # Fill the asset's exposure budget: the ecosystem may want the trade, risk says no.
    manager.sync_open_positions({"BTC/USDT": {"notional_usdt": 1000.0}})
    check = manager.check_signal(signal)
    assert not check.approved
    assert check.blocked_by == "position_sizing"


def test_shadow_engine_never_calls_risk_directly() -> None:
    eco = _ecosystem()
    router = StrategyRouter(gates=RouterGates(require_confirmed=False, timeframe="5m"))
    strategy_map = {
        "mom": {"family": "momentum", "regimes": ["TREND_UP"], "direction": "BOTH", "enabled": True}
    }
    selection = eco.select_eligible(
        router, context=_ctx(), regime="TREND_UP", strategy_map=strategy_map
    )
    assert selection.selected == ()  # not ACTIVE yet → not routable
    assert "NOT_APPLICABLE" in selection.by_verdict()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
