"""Contract tests: transition graph, forbidden states, execution modes (§5/§12)."""

from __future__ import annotations

import itertools

import pytest

from trading_bot.strategy_lifecycle.contracts import (
    EVIDENCE_REQUIRED_EDGES,
    STATE_TRANSITIONS,
    ExecutionMode,
    LifecycleState,
    LifecycleStateError,
    PromotionRecord,
    assert_transition,
    can_transition,
)


def test_paused_never_reaches_active() -> None:
    assert not can_transition(LifecycleState.PAUSED, LifecycleState.ACTIVE)
    with pytest.raises(LifecycleStateError):
        assert_transition("s", LifecycleState.PAUSED, LifecycleState.ACTIVE)


def test_candidate_never_reaches_active() -> None:
    assert not can_transition(LifecycleState.CANDIDATE, LifecycleState.ACTIVE)


def test_happy_promotion_path_is_walkable() -> None:
    path = [
        LifecycleState.CANDIDATE,
        LifecycleState.VALIDATING,
        LifecycleState.SHADOW,
    ]
    for source, target in itertools.pairwise(path):
        assert can_transition(source, target)
    # SHADOW -> ELIGIBLE and ELIGIBLE -> ACTIVE need evidence, checked below.
    assert can_transition(LifecycleState.SHADOW, LifecycleState.ELIGIBLE)
    assert can_transition(LifecycleState.ELIGIBLE, LifecycleState.ACTIVE)


def test_degradation_and_recovery_paths() -> None:
    assert can_transition(LifecycleState.ACTIVE, LifecycleState.DEGRADED)
    assert can_transition(LifecycleState.DEGRADED, LifecycleState.THROTTLED)
    assert can_transition(LifecycleState.THROTTLED, LifecycleState.PAUSED)
    assert can_transition(LifecycleState.PAUSED, LifecycleState.SHADOW)


def test_every_edge_is_defined_and_self_loops_allowed() -> None:
    for state, targets in STATE_TRANSITIONS.items():
        assert state in targets
        for target in targets:
            assert isinstance(target, LifecycleState)


def test_no_live_state_exists() -> None:
    assert not any("LIVE" in s.value.upper() for s in LifecycleState)
    assert not any(
        "LIVE" in t.value.upper() for targets in STATE_TRANSITIONS.values() for t in targets
    )


def test_evidence_required_edges_refuse_without_record() -> None:
    for source, target in EVIDENCE_REQUIRED_EDGES:
        with pytest.raises(LifecycleStateError):
            assert_transition("s", source, target)


def test_a_promotion_record_cannot_be_built_without_evidence() -> None:
    with pytest.raises(ValueError):
        PromotionRecord(
            promotion_id="p",
            strategy_id="s",
            from_state=LifecycleState.ELIGIBLE,
            to_state=LifecycleState.ACTIVE,
            evidence=(),
            policy_version="v1",
        )


def test_evidence_required_edge_refuses_a_record_for_another_strategy() -> None:
    record = PromotionRecord(
        promotion_id="p",
        strategy_id="other",
        from_state=LifecycleState.ELIGIBLE,
        to_state=LifecycleState.ACTIVE,
        evidence=("unit-evidence",),
        policy_version="v1",
    )
    with pytest.raises(LifecycleStateError):
        assert_transition("s", LifecycleState.ELIGIBLE, LifecycleState.ACTIVE, promotion=record)


def test_evidence_required_edges_accept_with_record() -> None:
    record = PromotionRecord(
        promotion_id="p",
        strategy_id="s",
        from_state=LifecycleState.ELIGIBLE,
        to_state=LifecycleState.ACTIVE,
        evidence=("unit-evidence",),
        policy_version="v1",
    )
    assert_transition("s", LifecycleState.ELIGIBLE, LifecycleState.ACTIVE, promotion=record)


def test_forbidden_execution_mode_is_live() -> None:
    from trading_bot.strategy_lifecycle.contracts import FORBIDDEN_EXECUTION_MODES

    assert ExecutionMode.LIVE in FORBIDDEN_EXECUTION_MODES
    assert ExecutionMode.SHADOW not in FORBIDDEN_EXECUTION_MODES
