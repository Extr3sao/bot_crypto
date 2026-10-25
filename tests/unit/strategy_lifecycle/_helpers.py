"""Shared builders for the dynamic strategy lifecycle tests."""

from __future__ import annotations

from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    ExecutionMode,
    HealthReport,
    HealthState,
    LifecycleState,
    PerformanceCell,
    StrategyDescriptor,
)
from trading_bot.strategy_lifecycle.performance import PerformanceObservation

DEFAULT_ASSETS = ("BTC", "ETH")
DEFAULT_TFS = ("5m", "15m")


def descriptor(
    strategy_id: str,
    *,
    version: str = "v1",
    family: str = "momentum",
    state: LifecycleState = LifecycleState.DISCOVERED,
    assets: tuple[str, ...] = DEFAULT_ASSETS,
    timeframes: tuple[str, ...] = DEFAULT_TFS,
    regimes: tuple[str, ...] = ("TREND_UP", "TREND_DOWN", "RANGE"),
    created_ms: int = 0,
) -> StrategyDescriptor:
    return StrategyDescriptor(
        strategy_id=strategy_id,
        strategy_version=version,
        family=family,
        assets=assets,
        timeframes=timeframes,
        supported_regimes=regimes,
        runtime_implementation=f"trading_bot.research.families.{family}",
        lifecycle_state=state,
        provenance={"dataset": "unit-fixture", "commit": "deadbeef"},
        created_at_ms=created_ms,
        updated_at_ms=created_ms,
    )


def health(
    state: HealthState = HealthState.HEALTHY,
    *,
    strategy_id: str = "s",
    asset: str = "BTC",
    timeframe: str = "5m",
    regime: str = "TREND_UP",
    score: float = 1.0,
) -> HealthReport:
    return HealthReport(
        strategy_id=strategy_id,
        context=ContextKey(strategy_id, asset, timeframe, regime),
        health_state=state,
        score=score,
        metrics={},
        baseline={},
        current={},
    )


def observation(
    strategy_id: str,
    *,
    asset: str = "BTC",
    timeframe: str = "5m",
    regime: str = "TREND_UP",
    net_bps: float = 10.0,
    gross_bps: float = 15.0,
    cost_bps: float = 5.0,
    timestamp_ms: int = 0,
    notional_usdt: float = 100.0,
    mode: ExecutionMode = ExecutionMode.SHADOW,
) -> PerformanceObservation:
    return PerformanceObservation(
        context=ContextKey(strategy_id, asset, timeframe, regime),
        timestamp_ms=timestamp_ms,
        gross_bps=gross_bps,
        net_bps=net_bps,
        cost_bps=cost_bps,
        notional_usdt=notional_usdt,
        correct=net_bps > 0,
        execution_mode=mode,
    )


def cell(
    *,
    strategy_id: str = "s",
    asset: str = "BTC",
    timeframe: str = "5m",
    regime: str = "TREND_UP",
    window: str = "medium",
    sample_count: int = 120,
    net_expectancy: float = 10.0,
    gross_expectancy: float = 15.0,
    profit_factor: float | None = 2.0,
    hit_rate: float = 0.6,
    max_drawdown: float = 50.0,
    cost_bps: float = 5.0,
    positive_windows: int = 3,
    window_count: int = 4,
    mode: ExecutionMode = ExecutionMode.SHADOW,
) -> PerformanceCell:
    return PerformanceCell(
        context=ContextKey(strategy_id, asset, timeframe, regime),
        window=window,
        sample_count=sample_count,
        trade_count=sample_count,
        gross_pnl_usdt=gross_expectancy,
        net_pnl_usdt=net_expectancy,
        gross_expectancy_bps=gross_expectancy,
        net_expectancy_bps=net_expectancy,
        profit_factor=profit_factor,
        hit_rate=hit_rate,
        avg_win_bps=gross_expectancy,
        avg_loss_bps=-gross_expectancy,
        max_drawdown_bps=max_drawdown,
        exposure_usdt=0.0,
        turnover_usdt=0.0,
        cost_bps=cost_bps,
        slippage_bps=None,
        positive_windows=positive_windows,
        window_count=window_count,
        last_updated_ms=0,
        execution_mode=mode,
    )


def series(
    strategy_id: str,
    net_values: list[float],
    *,
    asset: str = "BTC",
    timeframe: str = "5m",
    regime: str = "TREND_UP",
    start_ts: int = 0,
    step_ms: int = 300_000,
    **kwargs,
):
    return [
        observation(
            strategy_id,
            asset=asset,
            timeframe=timeframe,
            regime=regime,
            net_bps=v,
            timestamp_ms=start_ts + i * step_ms,
            **kwargs,
        )
        for i, v in enumerate(net_values)
    ]
