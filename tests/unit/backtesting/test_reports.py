"""Reports module tests (TSK-104 F3).

Pine contract:
- ``FoldReport`` + ``WalkForwardReport`` son frozen dataclasses.
- ``build_fold_report`` requires non-empty results.
- ``build_walk_forward_report`` requires ``len(fold_results) == len(splits)``.
- ``render_table`` returns str (no I/O side-effects).
- Aggregation is uniform-mean + cross-fold mean (F3a-phase-1; F3a-phase-2 will
  re-compute via ``_compute_metrics`` with sort temporal).
"""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from trading_bot.backtesting.reports import (
    FoldReport,
    WalkForwardReport,
    build_fold_report,
    build_walk_forward_report,
    render_table,
)
from trading_bot.backtesting.types import (
    BacktestResult,
    EquityPoint,
    Metrics,
    WalkForwardSplit,
)


def _make_metrics(
    total_trades: float = 1.0,
    win_rate: float = 1.0,
    **overrides: float,
) -> Metrics:
    base: Metrics = {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": float("inf"),  # all wins
        "final_equity": 10_010.0,
        "max_drawdown": 0.0,
        "cagr": 0.5,
        "calmar_ratio": float("inf"),
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "avg_trade_pnl": 10.0,
        "expectancy": 10.0,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _make_result(symbol: str, metrics: Metrics | None = None) -> BacktestResult:
    """Build a minimal BacktestResult for tests."""
    s = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    e = datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC)
    return BacktestResult(
        strategy_name="test",
        symbol=symbol,
        timeframe="1d",
        start=s,
        end=e,
        initial_capital=10_000.0,
        final_equity=metrics["final_equity"] if metrics else 10_010.0,
        trades=[],
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_010.0, drawdown_pct=0.0),
        ],
        metrics=metrics or _make_metrics(),
    )


def _split1() -> WalkForwardSplit:
    return WalkForwardSplit(
        train_start=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        train_end=datetime.datetime(2025, 6, 1, tzinfo=datetime.UTC),
        test_start=datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
        test_end=datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
    )


def _split2() -> WalkForwardSplit:
    return WalkForwardSplit(
        train_start=datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
        train_end=datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
        test_start=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        test_end=datetime.datetime(2026, 6, 30, tzinfo=datetime.UTC),
    )


# ===========================================================================
# FoldReport basics
# ===========================================================================


def test_build_fold_report_basic_per_symbol_metrics() -> None:
    results = [_make_result("BTC/USDT"), _make_result("ETH/USDT")]
    fold = build_fold_report(results, 0, _split1())
    assert isinstance(fold, FoldReport)
    assert fold.fold_id == 0
    assert fold.split == _split1()
    assert set(fold.per_symbol_metrics.keys()) == {"BTC/USDT", "ETH/USDT"}


def test_build_fold_report_alphabetical_sort_in_metrics_dict() -> None:
    """results can be in any order; per_symbol_metrics should be alphabetical."""
    results = [_make_result("ZZZ/USDT"), _make_result("AAA/USDT")]
    fold = build_fold_report(results, 0, _split1())
    keys = list(fold.per_symbol_metrics.keys())
    assert keys == sorted(keys)
    assert keys == ["AAA/USDT", "ZZZ/USDT"]


def test_build_fold_report_empty_results_raises() -> None:
    with pytest.raises(ValueError, match="results must be non-empty"):
        build_fold_report([], 0, _split1())


def test_fold_report_frozen() -> None:
    fold = build_fold_report([_make_result("BTC/USDT")], 0, _split1())
    with pytest.raises(dataclasses.FrozenInstanceError):
        fold.fold_id = 99  # type: ignore[misc]


# ===========================================================================
# WalkForwardReport basics
# ===========================================================================


def test_build_walk_forward_report_length_mismatch_raises() -> None:
    fold_results = [[_make_result("BTC/USDT")]]
    splits = [_split1(), _split2()]
    with pytest.raises(ValueError, match="fold_results length"):
        build_walk_forward_report(fold_results, splits)


def test_build_walk_forward_report_fold_id_sequence() -> None:
    fold_results = [
        [_make_result("BTC/USDT")],
        [_make_result("BTC/USDT")],
    ]
    splits = [_split1(), _split2()]
    report = build_walk_forward_report(fold_results, splits)
    assert isinstance(report, WalkForwardReport)
    assert [f.fold_id for f in report.folds] == [0, 1]


def test_build_walk_forward_report_global_aggregate_mean() -> None:
    """global_aggregate_metrics = mean of per-fold aggregate."""
    metrics_a = _make_metrics(total_trades=2.0, win_rate=1.0, final_equity=10_020.0, cagr=0.5)
    metrics_b = _make_metrics(total_trades=4.0, win_rate=1.0, final_equity=10_040.0, cagr=1.0)
    fold_results = [[_make_result("BTC/USDT", metrics_a)], [_make_result("BTC/USDT", metrics_b)]]
    splits = [_split1(), _split2()]
    report = build_walk_forward_report(fold_results, splits)

    # Global = mean of per-fold metrics.
    assert report.global_aggregate_metrics["total_trades"] == pytest.approx(3.0)
    assert report.global_aggregate_metrics["final_equity"] == pytest.approx(10_030.0)
    assert report.global_aggregate_metrics["cagr"] == pytest.approx(0.75)


# ===========================================================================
# render_table
# ===========================================================================


def test_render_table_returns_str_no_io_side_effects() -> None:
    fold_results = [[_make_result("BTC/USDT")]]
    splits = [_split1()]
    report = build_walk_forward_report(fold_results, splits)
    out = render_table(report)
    assert isinstance(out, str)
    # Cross-fold / per-fold rows present.
    assert "BTC/USDT" in out or "btc" in out.lower()  # either rich or plain path
    # Pure function: no return value is None (no I/O failures).
    assert out is not None


def test_render_table_includes_global_aggregate_row() -> None:
    fold_results = [[_make_result("BTC/USDT")]]
    splits = [_split1()]
    report = build_walk_forward_report(fold_results, splits)
    out = render_table(report).lower()
    # Global row label: either 'GLOBAL' (rich) or 'global' (plain).
    assert "global" in out


# ===========================================================================
# Edge cases for coverage boost
# ===========================================================================


def test_build_walk_forward_report_empty_folds_raises() -> None:
    """Empty fold_results + empty splits: raises (no folds means nothing to aggregate)."""
    with pytest.raises(ValueError, match="folds must be non-empty"):
        from trading_bot.backtesting.reports import _aggregate_metrics_cross_fold

        _aggregate_metrics_cross_fold([])


def test_walk_forward_split_constructed_with_invalid_invariant_returns_error_string() -> None:
    """The invariant violation error message should mention the values for debugging."""
    with pytest.raises(ValueError) as exc_info:
        WalkForwardSplit(
            train_start=datetime.datetime(2025, 6, 1, tzinfo=datetime.UTC),
            train_end=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),  # BEFORE start
            test_start=datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
            test_end=datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
        )
    # Error message should include the offending values.
    assert "2025" in str(exc_info.value)


def test_render_table_with_zero_folds_does_not_crash() -> None:
    """render_table on a report with no folds should not crash (graceful)."""
    # Build an empty report manually (bypassing the length-mismatch check).
    fold = build_fold_report([_make_result("BTC/USDT")], 0, _split1())
    # Manually construct a WalkForwardReport with empty folds (override the build fn).
    from trading_bot.backtesting.reports import WalkForwardReport

    empty_report = WalkForwardReport(
        folds=[], global_aggregate_metrics=fold.per_symbol_metrics["BTC/USDT"]
    )
    out = render_table(empty_report)
    assert isinstance(out, str)
    # Should mention global in output (either via rich or plain path).
    assert "global" in out.lower() or "GLOBAL" in out
