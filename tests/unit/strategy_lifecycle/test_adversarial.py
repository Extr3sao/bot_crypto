"""Adversarial suite — the mandatory §22 cases. Each asserts a REFUSAL.

If any of these ever passes by promoting/executing instead of refusing, the
dynamic ecosystem has a false-success bug.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_bot.research.router_gates import RouterGates
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.strategy_lifecycle.champion import ChampionChallenger
from trading_bot.strategy_lifecycle.config import LifecyclePolicy
from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    HealthState,
    LifecycleState,
    LifecycleStateError,
    RationaleCode,
    assert_no_future_data,
)
from trading_bot.strategy_lifecycle.lifecycle import (
    ControllerInputs,
    StrategyLifecycleController,
)
from trading_bot.strategy_lifecycle.pods import (
    ParallelShadowRuntime,
    PodSignal,
    ShadowLeakError,
    StrategyPod,
)
from trading_bot.strategy_lifecycle.portfolio import (
    PortfolioProposal,
    StrategyPortfolioManager,
)

from ._helpers import cell, descriptor, health

KEY = ContextKey("mom", "BTC", "5m", "TREND_UP")
POLICY = LifecyclePolicy(minimum_samples=100, minimum_regime_samples=30)


def _ctrl_inputs(state, **overrides) -> ControllerInputs:
    medium = overrides.pop("medium", cell(strategy_id="mom", regime="TREND_UP"))
    return ControllerInputs(
        descriptor=overrides.pop("descriptor", descriptor("mom", state=state)),
        context=KEY,
        cells={"medium": medium, "long": cell(strategy_id="mom", window="long", regime="TREND_UP")},
        health=overrides.pop("health", health(HealthState.HEALTHY, strategy_id="mom")),
        regime_cell=overrides.pop("regime_cell", cell(strategy_id="mom", regime="TREND_UP")),
        now_ms=overrides.pop("now_ms", 1_000_000),
        **overrides,
    )


def test_five_winning_trades_cannot_activate() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _ctrl_inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            medium=cell(strategy_id="mom", sample_count=5, net_expectancy=100.0, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert d.promotion is None


def test_insufficient_sample_denies_promotion() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _ctrl_inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            medium=cell(strategy_id="mom", sample_count=10, regime="TREND_UP"),
        )
    )
    assert RationaleCode.INSUFFICIENT_EVIDENCE.value in d.reason_codes


def test_high_drawdown_blocks_promotion() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _ctrl_inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            medium=cell(strategy_id="mom", max_drawdown=999.0, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert RationaleCode.DRAWDOWN_BREACH.value in d.reason_codes


def test_regime_mismatch_is_not_selected() -> None:
    router = StrategyRouter(gates=RouterGates(require_confirmed=False, timeframe="5m"))
    ctx = SimpleNamespace(
        asset="BTC", timestamp=1000, window_end_ts=900,
        data_quality={"bars_in_window": 120}, market_regime="TREND_UP",
    )
    smap = {"mr": {"family": "mean_reversion", "regimes": ["RANGE"], "direction": "BOTH", "enabled": True}}
    selection = router.select_eligible_strategies(ctx, "TREND_UP", smap, lifecycle={"mr": "ACTIVE"})
    assert selection.selected == ()
    assert "REGIME_MISMATCH" in selection.by_verdict()


def test_champion_losing_one_window_does_not_demote() -> None:
    # Health still HEALTHY after a single weak window → the controller keeps ACTIVE.
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_ctrl_inputs(LifecycleState.ACTIVE, health=health(HealthState.HEALTHY, strategy_id="mom")))
    assert d.to_state is LifecycleState.ACTIVE


def test_challenger_winning_one_window_does_not_promote() -> None:
    from trading_bot.strategy_lifecycle.champion import ChallengerEvaluation, ComparisonOutcome

    cc = ChampionChallenger(required_window_wins=3)
    champ = ChallengerEvaluation("champ", 200, 10.0, 1.5, 50.0, window_net_bps=(10.0, 10.0, 10.0))
    chal = ChallengerEvaluation("chal", 200, 30.0, 2.5, 50.0, window_net_bps=(40.0, 0.0, 0.0))
    result = cc.compare(context=KEY, champion=champ, challengers=[chal])
    assert result.outcome is ComparisonOutcome.CHAMPION_RETAINED


def test_correlated_same_asset_buys_are_capped() -> None:
    mgr = StrategyPortfolioManager(equity=10_000, max_asset_exposure_pct=100, max_same_direction_per_asset=2)
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    proposals = [
        PortfolioProposal("m", "BTC", "LONG", 100.0, 30.0, tuple(series)),
        PortfolioProposal("t", "BTC", "LONG", 100.0, 20.0, tuple(series)),
        PortfolioProposal("b", "BTC", "LONG", 100.0, 10.0, tuple(series)),
    ]
    decision = mgr.arbitrate(proposals)
    assert len(decision.accepted_proposals) <= 2
    assert "b" in decision.rejected_proposals


def test_paused_strong_shadow_still_only_reaches_shadow() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _ctrl_inputs(
            LifecycleState.PAUSED,
            recovery_streak=10,
            medium=cell(strategy_id="mom", net_expectancy=99.0, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW


def test_stale_context_is_rejected() -> None:
    router = StrategyRouter(gates=RouterGates(require_confirmed=False, timeframe="5m"))
    ctx = SimpleNamespace(
        asset="BTC", timestamp=10_000_000, window_end_ts=0,
        data_quality={"bars_in_window": 120}, market_regime="TREND_UP",
    )
    selection = router.select_eligible_strategies(
        ctx, "TREND_UP", {"a": {"family": "momentum", "regimes": ["TREND_UP"], "direction": "BOTH", "enabled": True}},
        lifecycle={"a": "ACTIVE"},
    )
    assert selection.selected == ()


def test_future_data_is_rejected() -> None:
    with pytest.raises(LifecycleStateError):
        assert_no_future_data(data_time_ms=2000, decision_time_ms=1000, label="htf_candle")
    # equal or past data is fine
    assert_no_future_data(data_time_ms=1000, decision_time_ms=1000)


def test_shadow_result_cannot_reach_execution() -> None:
    pod = StrategyPod(
        descriptor=descriptor("mom", state=LifecycleState.SHADOW),
        runtime=lambda ctx, bars: PodSignal(direction="LONG", entry_reference=100.0, confidence=0.5),
    )
    runtime = ParallelShadowRuntime()
    runtime.add(pod)
    out = runtime.evaluate_all(context=None, bars=[], context_key=KEY, timestamp_ms=1)
    with pytest.raises(ShadowLeakError):
        ParallelShadowRuntime.guard_not_executable(out)


def test_pod_tries_to_set_leverage_is_forbidden() -> None:
    with pytest.raises(ValueError):
        PodSignal(direction="LONG", entry_reference=1.0, confidence=0.5, advisory_metadata={"leverage": 10})


def test_llm_proposed_state_change_is_ignored() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _ctrl_inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            advisory_proposed_state="ACTIVE",
            medium=cell(strategy_id="mom", sample_count=5, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert any("IGNORED" in e for e in d.evidence)


def test_missing_evidence_never_promotes() -> None:
    from trading_bot.strategy_lifecycle.contracts import assert_transition

    with pytest.raises(LifecycleStateError):
        assert_transition("mom", LifecycleState.ELIGIBLE, LifecycleState.ACTIVE)
