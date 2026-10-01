"""Health monitor tests: degradation detection is deterministic (§8)."""

from __future__ import annotations

from trading_bot.strategy_lifecycle.config import HealthPolicy
from trading_bot.strategy_lifecycle.contracts import ContextKey, HealthState
from trading_bot.strategy_lifecycle.health import (
    Flag,
    HealthInputs,
    StrategyHealthMonitor,
)

from ._helpers import cell

KEY = ContextKey("mom", "BTC", "5m", "TREND_UP")


def _inputs(**overrides) -> HealthInputs:
    medium = overrides.pop("medium", cell(regime="TREND_UP"))
    long = overrides.pop("long", cell(window="long", regime="TREND_UP"))
    short = overrides.pop("short", cell(window="short", sample_count=30, regime="TREND_UP"))
    return HealthInputs(
        context=overrides.pop("context", KEY),
        cells={"short": short, "medium": medium, "long": long},
        **overrides,
    )


def test_insufficient_data_is_not_healthy() -> None:
    monitor = StrategyHealthMonitor(policy=HealthPolicy(min_samples=50))
    report = monitor.evaluate(_inputs(medium=cell(sample_count=10, regime="TREND_UP")))
    assert report.health_state is HealthState.INSUFFICIENT_DATA
    assert report.score == 0.0


def test_a_healthy_strategy_is_healthy() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(_inputs())
    assert report.health_state is HealthState.HEALTHY
    assert report.degradation_flags == ()


def test_expectancy_decay_is_flagged() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(
        _inputs(
            medium=cell(net_expectancy=1.0, gross_expectancy=15.0, regime="TREND_UP"),
            long=cell(window="long", net_expectancy=10.0, regime="TREND_UP"),
        )
    )
    assert Flag.EXPECTANCY_DECAY in report.degradation_flags
    assert report.health_state in (HealthState.WATCH, HealthState.DEGRADED, HealthState.CRITICAL)


def test_drawdown_deterioration_degrades() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(
        _inputs(
            medium=cell(max_drawdown=400.0, regime="TREND_UP"),
            long=cell(window="long", max_drawdown=50.0, regime="TREND_UP"),
        )
    )
    assert Flag.DRAWDOWN_DETERIORATION in report.degradation_flags
    assert report.health_state is HealthState.DEGRADED


def test_cost_sensitivity_is_flagged() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(
        _inputs(
            medium=cell(gross_expectancy=5.0, cost_bps=4.0, regime="TREND_UP"),
        )
    )
    assert Flag.COST_SENSITIVITY in report.degradation_flags


def test_loss_clustering_is_flagged() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(_inputs(net_series=(-1.0,) * 6 + (5.0,)))
    assert Flag.LOSS_CLUSTERING in report.degradation_flags


def test_regime_mismatch_is_flagged() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(
        _inputs(
            medium=cell(net_expectancy=-8.0, profit_factor=0.7, regime="RANGE"),
            long=cell(window="long", net_expectancy=12.0, regime="RANGE"),
        )
    )
    assert Flag.REGIME_MISMATCH in report.degradation_flags


def test_critical_when_profit_factor_below_one_and_negative() -> None:
    monitor = StrategyHealthMonitor()
    report = monitor.evaluate(
        _inputs(medium=cell(net_expectancy=-20.0, profit_factor=0.4, regime="TREND_UP"))
    )
    assert report.health_state is HealthState.CRITICAL


def test_inactivity_flag_requires_bar_denominator() -> None:
    monitor = StrategyHealthMonitor(policy=HealthPolicy(inactivity_samples=60))
    report = monitor.evaluate(
        _inputs(medium=cell(sample_count=0, regime="TREND_UP"), bar_count=100)
    )
    assert Flag.ABNORMAL_INACTIVITY in report.degradation_flags
