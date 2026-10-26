"""Registry tests: versioning, append-only history, events, churn (§15/§16/§24)."""

from __future__ import annotations

import pytest

from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    LifecycleState,
    LifecycleStateError,
    PromotionRecord,
)
from trading_bot.strategy_lifecycle.lifecycle import LifecycleDecision
from trading_bot.strategy_lifecycle.registry import DynamicStrategyRegistry

from ._helpers import descriptor


def _reg() -> DynamicStrategyRegistry:
    reg = DynamicStrategyRegistry()
    reg.register(descriptor("mom", state=LifecycleState.SHADOW))
    return reg


def _promo(source, target, sid="mom"):
    return PromotionRecord(
        promotion_id="p",
        strategy_id=sid,
        from_state=source,
        to_state=target,
        evidence=("unit-evidence",),
        policy_version="v1",
    )


def _decision(source, target, *, promotion=None, ts=1000, sid="mom") -> LifecycleDecision:
    return LifecycleDecision(
        strategy_id=sid,
        context=ContextKey(sid, "BTC", "5m", "TREND_UP"),
        from_state=source,
        to_state=target,
        reason_codes=("PROMOTION_EARNED",),
        metrics_snapshot={"net_expectancy_bps": 12.0},
        evidence=("unit-evidence",),
        policy_version="v1",
        promotion=promotion,
        timestamp_ms=ts,
    )


def test_register_is_idempotent_and_does_not_promote() -> None:
    reg = _reg()
    with pytest.raises(ValueError):
        reg.register(descriptor("mom", state=LifecycleState.ACTIVE))
    assert reg.state_of("mom") is LifecycleState.SHADOW


def test_register_cannot_create_a_strategy_in_an_authorising_state() -> None:
    """DEF-VERIFY-001: register() must not mint an already-promoted strategy."""
    reg = DynamicStrategyRegistry()
    for state in (
        LifecycleState.ACTIVE,
        LifecycleState.ELIGIBLE,
        LifecycleState.DEGRADED,
        LifecycleState.THROTTLED,
        LifecycleState.PAUSED,
        LifecycleState.RETIRED,
    ):
        with pytest.raises(LifecycleStateError):
            reg.register(descriptor(f"sneaky-{state.value}", state=state))
    assert reg.strategy_ids() == []


def test_register_accepts_only_non_authorising_entry_states() -> None:
    from trading_bot.strategy_lifecycle.contracts import REGISTRATION_ENTRY_STATES

    reg = DynamicStrategyRegistry()
    for state in REGISTRATION_ENTRY_STATES:
        reg.register(descriptor(f"ok-{state.value}", state=state))
        assert reg.state_of(f"ok-{state.value}") is state


def test_events_are_append_only() -> None:
    reg = _reg()
    events = reg.events()
    assert events[0]["event_type"] == "STRATEGY_REGISTERED"
    reg.apply(
        _decision(
            LifecycleState.SHADOW,
            LifecycleState.ELIGIBLE,
            promotion=_promo(LifecycleState.SHADOW, LifecycleState.ELIGIBLE),
        )
    )
    assert reg.events()[-1]["event_type"] == "STRATEGY_ELIGIBLE"


def test_version_history_keeps_every_state() -> None:
    reg = _reg()
    reg.apply(
        _decision(
            LifecycleState.SHADOW,
            LifecycleState.ELIGIBLE,
            promotion=_promo(LifecycleState.SHADOW, LifecycleState.ELIGIBLE),
        )
    )
    history = reg.version_history("mom")
    assert [d.lifecycle_state for d in history] == [
        LifecycleState.SHADOW,
        LifecycleState.ELIGIBLE,
    ]
    assert [h["to_state"] for h in reg.history("mom")] == ["ELIGIBLE"]


def test_stale_decision_is_refused() -> None:
    reg = _reg()
    with pytest.raises(ValueError):
        reg.apply(_decision(LifecycleState.ACTIVE, LifecycleState.DEGRADED))


def test_evidence_required_transition_needs_a_record() -> None:
    reg = _reg()
    with pytest.raises(LifecycleStateError):
        reg.apply(_decision(LifecycleState.SHADOW, LifecycleState.ELIGIBLE))


def test_activation_and_churn_are_counted() -> None:
    reg = _reg()
    record = PromotionRecord(
        promotion_id="p1",
        strategy_id="mom",
        from_state=LifecycleState.SHADOW,
        to_state=LifecycleState.ELIGIBLE,
        evidence=("ev",),
        policy_version="v1",
    )
    reg.apply(_decision(LifecycleState.SHADOW, LifecycleState.ELIGIBLE, promotion=record, ts=1000))
    record2 = PromotionRecord(
        promotion_id="p2",
        strategy_id="mom",
        from_state=LifecycleState.ELIGIBLE,
        to_state=LifecycleState.ACTIVE,
        evidence=("ev",),
        policy_version="v1",
    )
    reg.apply(_decision(LifecycleState.ELIGIBLE, LifecycleState.ACTIVE, promotion=record2, ts=2000))
    churn = reg.churn("mom")
    assert churn["activations"] == 1
    assert churn["promotions"] == 1
    assert churn["time_shadow_ms"] == 1000


def test_paused_reactivation_counts() -> None:
    reg = DynamicStrategyRegistry()
    # Registration cannot start PAUSED (DEF-VERIFY-001); reach it honestly.
    reg.register(descriptor("mom", state=LifecycleState.SHADOW))
    reg.apply(_decision(LifecycleState.SHADOW, LifecycleState.PAUSED))
    reg.apply(_decision(LifecycleState.PAUSED, LifecycleState.SHADOW))
    assert reg.churn("mom")["reactivations"] == 1


def test_by_state_and_active_ids() -> None:
    reg = DynamicStrategyRegistry()
    reg.register(descriptor("b", state=LifecycleState.SHADOW))
    reg.register(descriptor("a", state=LifecycleState.SHADOW))
    # An ACTIVE strategy is reached only through the evidence-gated edges.
    reg.apply(
        _decision(
            LifecycleState.SHADOW,
            LifecycleState.ELIGIBLE,
            promotion=_promo(LifecycleState.SHADOW, LifecycleState.ELIGIBLE, sid="a"),
            sid="a",
        )
    )
    reg.apply(
        _decision(
            LifecycleState.ELIGIBLE,
            LifecycleState.ACTIVE,
            promotion=_promo(LifecycleState.ELIGIBLE, LifecycleState.ACTIVE, sid="a"),
            sid="a",
            ts=2000,
        )
    )
    assert reg.active_ids() == ["a"]
    assert reg.by_state(LifecycleState.SHADOW) == ["b"]
