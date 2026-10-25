"""Health window tests — GATE STRAT-PERSIST-003 §9/§10 (DEF-VERIFY-004).

DEF-VERIFY-004: `HealthPolicy.windows` was inert — the health monitor read
whatever windows the performance store happened to have, so a configured window
never applied. Resolution (option B, per §9): windowing is owned by the
`ContextualPerformanceStore` (a single owner) and the duplicate/inert
`HealthPolicy.windows` field is removed, so a second silently-ignored window set
is no longer possible.

These tests pin that the store is the single owner and that its windows are the
ones the health monitor actually sees.
"""

from __future__ import annotations

import pytest

from trading_bot.strategy_lifecycle.config import HealthPolicy, RollingWindows
from trading_bot.strategy_lifecycle.contracts import HealthState
from trading_bot.strategy_lifecycle.ecosystem import DynamicStrategyEcosystem
from trading_bot.strategy_lifecycle.performance import ContextualPerformanceStore

from ._helpers import observation

KEY = dict(strategy_id="s", asset="BTC", timeframe="5m", regime="TREND_UP")


def _series(eco: DynamicStrategyEcosystem, values: list[float]) -> None:
    for i, net in enumerate(values):
        eco.performance.record(observation("s", net_bps=net, timestamp_ms=i * 1000))


def _eco(windows: RollingWindows, *, min_samples: int = 10, n: int = 30) -> DynamicStrategyEcosystem:
    eco = DynamicStrategyEcosystem(
        performance=ContextualPerformanceStore(windows=windows),
        health_policy=HealthPolicy(min_samples=min_samples),
    )
    _series(eco, [10.0] * n)
    return eco


def test_health_policy_no_longer_carries_an_inert_window_config() -> None:
    assert not hasattr(HealthPolicy(), "windows")


def test_store_is_the_single_owner_of_windows() -> None:
    assert DynamicStrategyEcosystem().performance.windows == RollingWindows(50, 100, 250)


def test_configured_store_window_drives_the_medium_sample_count() -> None:
    eco = _eco(RollingWindows(10, 20, 40), min_samples=20, n=30)
    # The medium working window is the store's 20 samples, not the default 100.
    assert eco.health_for(**KEY, now_ms=10**9).metrics["sample_count"] == 20.0


def test_different_store_windows_produce_different_results() -> None:
    small = _eco(RollingWindows(5, 10, 20))
    large = _eco(RollingWindows(50, 100, 250))
    for eco in (small, large):
        # Overwrite with a single series: 30 obs, the last 10 negative, so the
        # small (10-sample) window sees only losses.
        eco.performance = ContextualPerformanceStore(windows=eco.performance.windows)
        _series(eco, [10.0] * 20 + [-10.0] * 10)
    small_metrics = small.health_for(**KEY, now_ms=10**9).metrics
    large_metrics = large.health_for(**KEY, now_ms=10**9).metrics
    assert small_metrics["sample_count"] == 10.0
    assert large_metrics["sample_count"] == 30.0
    assert small_metrics["net_expectancy_bps"] < large_metrics["net_expectancy_bps"]


def test_insufficient_samples_is_first_class() -> None:
    eco = _eco(RollingWindows(5, 10, 20), min_samples=20, n=5)
    assert eco.health_for(**KEY, now_ms=10**9).health_state is HealthState.INSUFFICIENT_DATA


def test_missing_window_data_is_not_healthy() -> None:
    assert (
        DynamicStrategyEcosystem().health_for(**KEY, now_ms=10**9).health_state
        is HealthState.INSUFFICIENT_DATA
    )


def test_boundary_sample_count_promotes_from_insufficient() -> None:
    eco = _eco(RollingWindows(5, 10, 20), min_samples=10, n=9)
    assert eco.health_for(**KEY, now_ms=10**9).health_state is HealthState.INSUFFICIENT_DATA
    eco.performance.record(observation("s", net_bps=10.0, timestamp_ms=9_000))
    assert eco.health_for(**KEY, now_ms=10**9).health_state is not HealthState.INSUFFICIENT_DATA


def test_invalid_window_ordering_is_refused() -> None:
    with pytest.raises(ValueError):
        RollingWindows(short=30, medium=10, long=5)
