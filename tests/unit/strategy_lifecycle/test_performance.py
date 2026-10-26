"""Performance store tests: rolling windows, context keys, regime matrix (§6/§7/§14)."""

from __future__ import annotations

import pytest

from trading_bot.strategy_lifecycle.config import RollingWindows
from trading_bot.strategy_lifecycle.contracts import ContextKey, ExecutionMode
from trading_bot.strategy_lifecycle.performance import (
    ContextualPerformanceStore,
    PerformanceObservation,
)

from ._helpers import observation, series


def _store() -> ContextualPerformanceStore:
    return ContextualPerformanceStore(windows=RollingWindows(short=20, medium=60, long=120))


def test_windows_are_sized_and_ordered() -> None:
    store = _store()
    values = [20.0] * 40 + [-10.0] * 20  # 60 observations
    store.record_many(series("mom", values))
    key = ContextKey("mom", "BTC", "5m", "TREND_UP")
    short = store.cell(key, "short")
    medium = store.cell(key, "medium")
    long = store.cell(key, "long")
    assert short.sample_count == 20
    assert medium.sample_count == 60
    assert long.sample_count == 60  # only 60 total
    # medium uses the LAST 60 → mixed wins/losses
    assert medium.net_expectancy_bps == pytest.approx(10.0)
    assert medium.hit_rate == pytest.approx(40 / 60)
    # the fixture records all gross as positive, so there are no gross losses
    assert medium.profit_factor is None


def test_profit_factor_uses_gross_signs() -> None:
    store = _store()
    obs = []
    for i in range(40):
        obs.append(observation("mom", net_bps=20.0, gross_bps=25.0, timestamp_ms=i))
    for i in range(40, 60):
        obs.append(observation("mom", net_bps=-10.0, gross_bps=-5.0, timestamp_ms=i))
    store.record_many(obs)
    key = ContextKey("mom", "BTC", "5m", "TREND_UP")
    medium = store.cell(key, "medium")
    assert medium.profit_factor == pytest.approx((40 * 25) / (20 * 5))


def test_windows_are_the_last_n_in_time_order() -> None:
    store = _store()
    # 25 observations: first 20 losing, last 5 winning.
    store.record_many(series("mom", [-5.0] * 20 + [50.0] * 5))
    key = ContextKey("mom", "BTC", "5m", "TREND_UP")
    short = store.cell(key, "short")  # last 20 → 15 losses + 5 wins
    assert short.sample_count == 20
    assert short.net_expectancy_bps == pytest.approx((15 * -5.0 + 5 * 50.0) / 20)


def test_context_isolation() -> None:
    store = _store()
    store.record_many(series("mom", [10.0] * 10, regime="TREND_UP"))
    store.record_many(series("mom", [-10.0] * 10, regime="RANGE"))
    up = store.cell(ContextKey("mom", "BTC", "5m", "TREND_UP"), "medium")
    rng = store.cell(ContextKey("mom", "BTC", "5m", "RANGE"), "medium")
    assert up.net_expectancy_bps == pytest.approx(10.0)
    assert rng.net_expectancy_bps == pytest.approx(-10.0)


def test_regime_matrix_covers_all_regimes() -> None:
    store = _store()
    for regime, value in (("TREND_UP", 10.0), ("RANGE", -3.0), ("TREND_DOWN", 5.0)):
        store.record_many(series("mom", [value] * 30, regime=regime))
    matrix = store.regime_matrix("mom", "BTC", "5m")
    assert set(matrix) == {"TREND_UP", "RANGE", "TREND_DOWN"}
    assert matrix["RANGE"].net_expectancy_bps == pytest.approx(-3.0)


def test_max_drawdown_is_peak_to_trough() -> None:
    store = _store()
    # 20 losses then 40 wins → peak-to-trough of the cumulative curve.
    store.record_many(series("mom", [-10.0] * 20 + [10.0] * 40))
    key = ContextKey("mom", "BTC", "5m", "TREND_UP")
    long = store.cell(key, "long")
    assert long.max_drawdown_bps == pytest.approx(200.0)


def test_observations_require_regime_label() -> None:
    with pytest.raises(ValueError):
        PerformanceObservation(
            context=ContextKey("mom", "BTC", "5m", ""),
            timestamp_ms=0,
            gross_bps=1.0,
            net_bps=1.0,
            cost_bps=0.0,
            notional_usdt=1.0,
            correct=True,
        )


def test_sequence_is_assigned_monotonically() -> None:
    store = _store()
    a = store.record(observation("mom", timestamp_ms=100))
    b = store.record(observation("mom", timestamp_ms=100))
    assert a.sequence == 0
    assert b.sequence == 1


def test_live_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        PerformanceObservation(
            context=ContextKey("mom", "BTC", "5m", "TREND_UP"),
            timestamp_ms=0,
            gross_bps=1.0,
            net_bps=1.0,
            cost_bps=0.0,
            notional_usdt=1.0,
            correct=True,
            execution_mode=ExecutionMode.LIVE,
        )
