"""Tests for walk-forward aggregate reports (TSK-104 F3b residuo)."""

from __future__ import annotations

import datetime
import json
import math
from dataclasses import replace

import pytest

from trading_bot.backtesting import FoldReport
from trading_bot.backtesting.walk_forward_reports import (
    MetricAggregate,
    WalkForwardAggregateReport,
    build_walk_forward_aggregate,
    build_walk_forward_aggregate_payload,
    render_walk_forward_aggregate_markdown,
)


def _fold_report(
    *,
    final_equity: float = 11_000.0,
    initial_capital: float = 10_000.0,
    total_trades: int = 10,
    win_rate: float = 0.6,
    profit_factor: float = 1.5,
    expectancy: float = 100.0,
    max_drawdown: float = 0.05,
    cagr: float = 0.10,
    sharpe_ratio: float = 1.2,
) -> FoldReport:
    return FoldReport(
        strategy_name="test_strategy",
        symbol="BTC/USDT",
        timeframe="1m",
        start=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        end=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        avg_trade_pnl=10.0,
        max_drawdown=max_drawdown,
        cagr=cagr,
        calmar_ratio=2.0,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=1.5,
        avg_bars_held=5.0,
        best_trade_pnl=200.0,
        worst_trade_pnl=-100.0,
        max_consecutive_losses=2,
        reward_risk_ratio=2.0,
        total_commissions=50.0,
        total_slippage=20.0,
    )


def test_aggregate_raises_on_empty_list() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        build_walk_forward_aggregate([])


def test_aggregate_single_fold_returns_perfect_match() -> None:
    fold = _fold_report(win_rate=0.6, sharpe_ratio=1.2, profit_factor=1.5)
    agg = build_walk_forward_aggregate([fold])
    assert agg.total_folds == 1
    assert agg.total_trades == 10
    assert agg.total_realized_pnl == pytest.approx(1000.0)
    assert agg.consistency_score == 1.0
    assert agg.win_rate.mean == pytest.approx(0.6)
    assert agg.win_rate.std == 0.0
    assert agg.win_rate.min == pytest.approx(0.6)
    assert agg.win_rate.max == pytest.approx(0.6)
    assert agg.sharpe_ratio.mean == pytest.approx(1.2)
    assert agg.profit_factor.mean == pytest.approx(1.5)


def test_aggregate_consistency_score_all_profitable() -> None:
    folds = [_fold_report(final_equity=11_000.0) for _ in range(3)]
    agg = build_walk_forward_aggregate(folds)
    assert agg.consistency_score == 1.0


def test_aggregate_consistency_score_all_unprofitable() -> None:
    folds = [_fold_report(final_equity=9_000.0) for _ in range(3)]
    agg = build_walk_forward_aggregate(folds)
    assert agg.consistency_score == 0.0


def test_aggregate_consistency_score_mixed() -> None:
    folds = [
        _fold_report(final_equity=11_000.0),
        _fold_report(final_equity=9_000.0),
        _fold_report(final_equity=12_000.0),
        _fold_report(final_equity=8_000.0),
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.consistency_score == pytest.approx(0.5)


def test_aggregate_consistency_score_three_fold_mix_with_breakeven() -> None:
    """Hardens the formula with a 3-fold mix: 1 profitable, 1 break-even,
    1 unprofitable. consistency_score must equal 1/3 (~0.333).
    """
    folds = [
        _fold_report(final_equity=11_000.0),  # profitable
        _fold_report(final_equity=10_000.0),  # break-even (NOT profitable per strict >)
        _fold_report(final_equity=9_000.0),  # unprofitable
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.consistency_score == pytest.approx(1.0 / 3.0)


def test_aggregate_zero_pnl_is_not_profitable() -> None:
    """Pine contract: pnl == 0 does NOT count as profitable."""
    folds = [
        _fold_report(final_equity=10_000.0),  # pnl = 0
        _fold_report(final_equity=11_000.0),
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.consistency_score == pytest.approx(0.5)


def test_aggregate_filters_inf_and_nan_from_metric_aggregate() -> None:
    folds = [
        _fold_report(win_rate=0.5, profit_factor=1.2, sharpe_ratio=1.0),
        _fold_report(win_rate=0.6, profit_factor=float("inf"), sharpe_ratio=float("nan")),
        _fold_report(win_rate=0.7, profit_factor=1.5, sharpe_ratio=1.2),
    ]
    agg = build_walk_forward_aggregate(folds)
    # win_rate: 3 finite values, mean = (0.5 + 0.6 + 0.7) / 3 = 0.6
    assert agg.win_rate.mean == pytest.approx(0.6)
    # profit_factor: 2 finite values (1.2, 1.5) after filtering inf
    assert agg.profit_factor.mean == pytest.approx(1.35)
    assert math.isfinite(agg.profit_factor.mean)
    # sharpe_ratio: 2 finite values (1.0, 1.2) after filtering nan
    assert agg.sharpe_ratio.mean == pytest.approx(1.1)


def test_aggregate_handles_all_inf_metrics() -> None:
    """Pine contract: all-inf metric -> zeros (no inf in aggregate)."""
    folds = [
        _fold_report(profit_factor=float("inf"), sharpe_ratio=float("inf")),
        _fold_report(profit_factor=float("inf"), sharpe_ratio=float("inf")),
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.profit_factor.mean == 0.0
    assert agg.profit_factor.std == 0.0
    assert agg.profit_factor.min == 0.0
    assert agg.profit_factor.max == 0.0
    assert agg.sharpe_ratio.mean == 0.0


def test_aggregate_total_realized_pnl() -> None:
    folds = [
        _fold_report(final_equity=11_000.0, initial_capital=10_000.0),
        _fold_report(final_equity=12_000.0, initial_capital=10_000.0),
        _fold_report(final_equity=9_000.0, initial_capital=10_000.0),
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.total_realized_pnl == pytest.approx(2000.0)


def test_aggregate_total_trades_sums_across_folds() -> None:
    folds = [
        _fold_report(total_trades=10),
        _fold_report(total_trades=20),
        _fold_report(total_trades=15),
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.total_trades == 45


def test_aggregate_metric_stats_with_two_finite_values() -> None:
    """Pine contract: 2 finite values -> std computed (not 0)."""
    folds = [
        _fold_report(win_rate=0.4),
        _fold_report(win_rate=0.6),
    ]
    agg = build_walk_forward_aggregate(folds)
    assert agg.win_rate.mean == pytest.approx(0.5)
    assert agg.win_rate.std == pytest.approx(math.sqrt(0.02))
    assert agg.win_rate.min == pytest.approx(0.4)
    assert agg.win_rate.max == pytest.approx(0.6)


def test_aggregate_does_not_mutate_input_reports() -> None:
    """Pine contract: aggregate is a pure function over FoldReport inputs.

    Uses ``dataclasses.replace`` to make a copy (FoldReport is a frozen
    dataclass with ``slots=True``, so it has no ``__dict__``).
    """
    fold = _fold_report(win_rate=0.6)
    original = replace(fold)
    build_walk_forward_aggregate([fold])
    assert fold == original


def test_render_markdown_contains_key_fields() -> None:
    folds = [_fold_report(), _fold_report(win_rate=0.5)]
    agg = build_walk_forward_aggregate(folds)
    md = render_walk_forward_aggregate_markdown(agg)
    assert "Walk-Forward Aggregate Report" in md
    assert "Total folds: 2" in md
    assert "Total trades: 20" in md
    assert "Consistency score: 100.00%" in md
    assert "win_rate" in md
    assert "profit_factor" in md
    assert "sharpe_ratio" in md
    assert "max_drawdown" in md


def test_payload_contains_all_fields() -> None:
    folds = [_fold_report(), _fold_report(win_rate=0.7)]
    agg = build_walk_forward_aggregate(folds)
    payload = build_walk_forward_aggregate_payload(agg)
    assert payload["total_folds"] == 2
    assert payload["total_trades"] == 20
    assert payload["consistency_score"] == pytest.approx(1.0)
    assert "win_rate" in payload
    assert set(payload["win_rate"]) == {"mean", "std", "min", "max"}
    assert "profit_factor" in payload
    assert "expectancy" in payload
    assert "max_drawdown" in payload
    assert "cagr" in payload
    assert "sharpe_ratio" in payload


def test_payload_keys_track_dataclass_fields() -> None:
    """Pine contract: payload keys = dataclass fields (no shape-drift).

    If a new field is added to ``WalkForwardAggregateReport`` (or to
    ``MetricAggregate``), the payload picks it up automatically
    (recursion via ``dataclasses.fields``). This test guards the
    contract by asserting the payload keys are exactly the field names
    of the dataclass.
    """
    import dataclasses

    fold = _fold_report()
    agg = build_walk_forward_aggregate([fold])
    payload = build_walk_forward_aggregate_payload(agg)
    expected_top_keys = {field.name for field in dataclasses.fields(agg)}
    assert set(payload) == expected_top_keys
    for field in dataclasses.fields(agg):
        value = getattr(agg, field.name)
        if dataclasses.is_dataclass(value):
            expected_metric_keys = {f.name for f in dataclasses.fields(value)}
            assert set(payload[field.name]) == expected_metric_keys


def test_payload_is_json_serializable() -> None:
    """Pine contract: payload must be JSON-serializable (json.dumps default)."""
    folds = [_fold_report(), _fold_report(final_equity=11_500.0)]
    agg = build_walk_forward_aggregate(folds)
    payload = build_walk_forward_aggregate_payload(agg)
    # Should not raise.
    encoded = json.dumps(payload)
    assert "consistency_score" in encoded
    assert "win_rate" in encoded


def test_metric_aggregate_is_immutable() -> None:
    """Pine contract: MetricAggregate is a frozen dataclass."""
    ma = MetricAggregate(mean=1.0, std=0.5, min=0.0, max=2.0)
    with pytest.raises((AttributeError, TypeError)):
        ma.mean = 99.0  # type: ignore[misc]


def test_walk_forward_aggregate_report_is_immutable() -> None:
    """Pine contract: WalkForwardAggregateReport is a frozen dataclass."""
    fold = _fold_report()
    agg: WalkForwardAggregateReport = build_walk_forward_aggregate([fold])
    with pytest.raises((AttributeError, TypeError)):
        agg.total_folds = 99  # type: ignore[misc]
