"""Lifecycle controller tests: promotion, demotion, recovery, churn (§9/§24)."""

from __future__ import annotations

from trading_bot.strategy_lifecycle.config import LifecyclePolicy
from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    HealthState,
    LifecycleState,
    RationaleCode,
)
from trading_bot.strategy_lifecycle.lifecycle import (
    ControllerInputs,
    StrategyLifecycleController,
)

from ._helpers import cell, descriptor, health

KEY = ContextKey("mom", "BTC", "5m", "TREND_UP")
POLICY = LifecyclePolicy(
    minimum_samples=100,
    minimum_regime_samples=30,
    degrade_persistence=2,
    activation_cooldown_ms=1_000,
    eligibility_dwell_ms=1_000,
    demotion_quiet_ms=1_000,
)


def _inputs(state: LifecycleState, **overrides) -> ControllerInputs:
    d = overrides.pop("descriptor", descriptor("mom", state=state))
    medium = overrides.pop("medium", cell(strategy_id="mom", regime="TREND_UP"))
    long = overrides.pop("long", cell(strategy_id="mom", window="long", regime="TREND_UP"))
    regime_cell = overrides.pop("regime_cell", cell(strategy_id="mom", regime="TREND_UP"))
    h = overrides.pop("health", health(HealthState.HEALTHY, strategy_id="mom"))
    return ControllerInputs(
        descriptor=d,
        context=KEY,
        cells={"medium": medium, "long": long, "short": cell(strategy_id="mom", window="short")},
        health=h,
        regime_cell=regime_cell,
        now_ms=overrides.pop("now_ms", 1_000_000),
        **overrides,
    )


def test_active_stays_active_when_healthy() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_inputs(LifecycleState.ACTIVE))
    assert d.to_state is LifecycleState.ACTIVE
    assert not d.changed


def test_active_degrades_when_health_degrades() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _inputs(
            LifecycleState.ACTIVE,
            health=health(HealthState.DEGRADED, strategy_id="mom"),
        )
    )
    assert d.to_state is LifecycleState.DEGRADED
    assert RationaleCode.HEALTH_DEGRADED.value in d.reason_codes


def test_shadow_with_insufficient_samples_does_not_promote() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _inputs(
            LifecycleState.SHADOW, medium=cell(strategy_id="mom", sample_count=5, regime="TREND_UP")
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert RationaleCode.INSUFFICIENT_EVIDENCE.value in d.reason_codes
    assert d.promotion is None


def test_shadow_promotes_to_eligible_with_full_evidence_and_verification() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_inputs(LifecycleState.SHADOW, verification_passed=True, last_demotion_ms=0))
    assert d.to_state is LifecycleState.ELIGIBLE
    assert d.promotion is not None
    assert d.promotion.evidence


def test_shadow_promotion_blocked_without_independent_verification() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_inputs(LifecycleState.SHADOW, verification_passed=False))
    assert d.to_state is LifecycleState.SHADOW
    assert RationaleCode.INSUFFICIENT_EVIDENCE.value in d.reason_codes


def test_eligible_activates_only_after_dwell_and_cooldown() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    blocked = c.evaluate(
        _inputs(
            LifecycleState.ELIGIBLE,
            verification_passed=True,
            eligible_since_ms=999_500,
            now_ms=1_000_000,
        )
    )
    assert blocked.to_state is LifecycleState.ELIGIBLE
    assert RationaleCode.COOLDOWN_ACTIVE.value in blocked.reason_codes

    allowed = c.evaluate(
        _inputs(
            LifecycleState.ELIGIBLE,
            verification_passed=True,
            eligible_since_ms=900_000,
            now_ms=1_000_000,
        )
    )
    assert allowed.to_state is LifecycleState.ACTIVE
    assert allowed.promotion is not None


def test_paused_never_goes_straight_to_active() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    # Even with excellent numbers, PAUSED only reaches SHADOW.
    d = c.evaluate(
        _inputs(
            LifecycleState.PAUSED,
            recovery_streak=5,
            medium=cell(strategy_id="mom", net_expectancy=50.0, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert d.to_state is not LifecycleState.ACTIVE


def test_advisory_proposed_state_is_ignored() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _inputs(
            LifecycleState.SHADOW,
            medium=cell(strategy_id="mom", sample_count=5, regime="TREND_UP"),
            advisory_proposed_state="ACTIVE",
        )
    )
    # The advisory proposal did NOT move the machine.
    assert d.to_state is LifecycleState.SHADOW
    assert any("IGNORED" in e for e in d.evidence)


def test_five_winning_trades_cannot_promote() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            medium=cell(strategy_id="mom", sample_count=5, net_expectancy=100.0, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW


def test_regime_mismatch_blocks_promotion() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            regime_cell=cell(strategy_id="mom", sample_count=1, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert RationaleCode.REGIME_MISMATCH.value in d.reason_codes


def test_high_drawdown_blocks_promotion() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(
        _inputs(
            LifecycleState.SHADOW,
            verification_passed=True,
            medium=cell(strategy_id="mom", max_drawdown=999.0, regime="TREND_UP"),
        )
    )
    assert d.to_state is LifecycleState.SHADOW
    assert RationaleCode.DRAWDOWN_BREACH.value in d.reason_codes
