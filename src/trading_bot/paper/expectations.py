"""Bridge helpers between backtesting summaries and paper expectations."""

from __future__ import annotations

from trading_bot.backtesting import BacktestResult, FoldReport, build_fold_report

from .types import PaperBacktestExpectation


def build_expectation_from_fold_report(
    report: FoldReport,
    *,
    expected_median_spread_bps: float,
    active_snapshots_per_trade: float = 1.0,
    min_active_ratio: float = 0.30,
    max_scanner_errors: int = 3,
) -> PaperBacktestExpectation:
    """Translate a backtest fold summary into paper-mode proxy expectations.

    This is intentionally a proxy mapping. The current paper harness compares
    scanner-level signals against backtest-level trade activity, so the caller
    must still provide a spread estimate in bps until paper fills exist.
    """

    if expected_median_spread_bps < 0.0:
        raise ValueError("expected_median_spread_bps debe ser >= 0.")
    if active_snapshots_per_trade < 0.0:
        raise ValueError("active_snapshots_per_trade debe ser >= 0.")

    expected_active_snapshots = round(report.total_trades * active_snapshots_per_trade)
    return PaperBacktestExpectation(
        expected_active_snapshots=max(expected_active_snapshots, 0),
        expected_median_spread_bps=float(expected_median_spread_bps),
        expected_realized_pnl=report.final_equity - report.initial_capital,
        min_active_ratio=min_active_ratio,
        min_win_rate_closed=0.30,
        max_scanner_errors=max_scanner_errors,
    )


def build_expectation_from_backtest_result(
    result: BacktestResult,
    *,
    expected_median_spread_bps: float,
    active_snapshots_per_trade: float = 1.0,
    min_active_ratio: float = 0.30,
    max_scanner_errors: int = 3,
) -> PaperBacktestExpectation:
    """Build paper expectations from a raw backtest run via ``FoldReport``."""

    return build_expectation_from_fold_report(
        build_fold_report(result),
        expected_median_spread_bps=expected_median_spread_bps,
        active_snapshots_per_trade=active_snapshots_per_trade,
        min_active_ratio=min_active_ratio,
        max_scanner_errors=max_scanner_errors,
    )


__all__ = [
    "build_expectation_from_backtest_result",
    "build_expectation_from_fold_report",
]
