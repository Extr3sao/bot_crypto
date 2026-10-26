"""Regression tests for DEF-VERIFY-006 (bounded store) and DEF-VERIFY-007 (PIT).

DEF-VERIFY-006: ``ContextualPerformanceStore`` was append-only with no ceiling,
so a long-running lifecycle grew without bound. It now keeps at most
``max_observations_per_cell`` observations per cell (default finite; <= 0 opts
back into unbounded retention).

DEF-VERIFY-007: ``assert_no_future_data`` was referenced only by a test. The
store now ENFORCES the point-in-time invariant when the caller supplies the
decision time, refusing a future-dated observation instead of silently
re-sorting it into the history.
"""

from __future__ import annotations

import pytest

from trading_bot.strategy_lifecycle.contracts import ContextKey, LifecycleStateError
from trading_bot.strategy_lifecycle.performance import (
    DEFAULT_MAX_OBSERVATIONS_PER_CELL,
    ContextualPerformanceStore,
)

from ._helpers import observation

KEY = ContextKey("mom", "BTC", "5m", "TREND_UP")


def test_default_bound_is_finite() -> None:
    assert ContextualPerformanceStore().max_observations_per_cell == (
        DEFAULT_MAX_OBSERVATIONS_PER_CELL
    )
    assert DEFAULT_MAX_OBSERVATIONS_PER_CELL > 250  # never truncates a window
    assert DEFAULT_MAX_OBSERVATIONS_PER_CELL > 0


def test_cell_memory_is_bounded_and_keeps_the_newest() -> None:
    store = ContextualPerformanceStore(max_observations_per_cell=3)
    for i in range(5):
        store.record(observation("mom", net_bps=float(i), timestamp_ms=i))
    retained = store.observations(KEY)
    assert len(retained) == 3
    # the OLDEST are dropped; the newest survive in order
    assert [o.timestamp_ms for o in retained] == [2, 3, 4]


def test_zero_bound_means_unbounded() -> None:
    store = ContextualPerformanceStore(max_observations_per_cell=0)
    for i in range(10):
        store.record(observation("mom", timestamp_ms=i))
    assert len(store.observations(KEY)) == 10


def test_bound_survives_persistence_round_trip() -> None:
    store = ContextualPerformanceStore(max_observations_per_cell=7)
    store.record(observation("mom", timestamp_ms=1))
    restored = ContextualPerformanceStore.from_state(store.to_state())
    assert restored.max_observations_per_cell == 7


def test_future_observation_is_refused_when_decision_time_is_given() -> None:
    store = ContextualPerformanceStore()
    with pytest.raises(LifecycleStateError):
        store.record(
            observation("mom", timestamp_ms=2_000),
            decision_time_ms=1_000,
        )
    # the refused observation left no trace
    assert store.observations(KEY) == ()


def test_pit_boundary_is_inclusive() -> None:
    store = ContextualPerformanceStore()
    store.record(observation("mom", timestamp_ms=1_000), decision_time_ms=1_000)
    assert len(store.observations(KEY)) == 1


def test_without_decision_time_behaviour_is_unchanged() -> None:
    store = ContextualPerformanceStore()
    store.record(observation("mom", timestamp_ms=9_999_999))
    assert len(store.observations(KEY)) == 1
