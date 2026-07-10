"""Paper-trading expectations builder stub (TSK-105 in-progress).

Maps a FoldReport's risk profile onto the pre-session
PaperBacktestExpectation contract used by Reporting to emit alerts.
"""

from __future__ import annotations

from typing import Any

from .types import PaperBacktestExpectation


def build_expectation_from_fold_report(
    fold_report: Any,
    *,
    expected_median_spread_bps: float = 0.0,
    active_snapshots_per_trade: float = 1.0,
    min_active_ratio: float = 0.30,
    max_scanner_errors: int = 3,
) -> PaperBacktestExpectation:
    """Build a ``PaperBacktestExpectation`` from a ``FoldReport``.

    Pine contract pinned by ``tests/unit/paper/test_harness.py``::

        expected_active_snapshots = active_snapshots_per_trade * fold_report.total_trades

    This makes the JSON written by ``reporting.write_session_report``
    contain ``"expected_active_snapshots": N`` for the
    ``test_runner_can_be_built_from_backtest_result`` contract test, and
    also primes the alert heuristic in ``reporting.build_session_alerts``
    with the active-snapshot bound.
    """
    total_trades = int(getattr(fold_report, "total_trades", 0) or 0)
    expected_active_snapshots = (
        int(active_snapshots_per_trade * total_trades) if total_trades else None
    )
    return PaperBacktestExpectation(
        expected_median_spread_bps=expected_median_spread_bps,
        active_snapshots_per_trade=active_snapshots_per_trade,
        min_active_ratio=min_active_ratio,
        max_scanner_errors=max_scanner_errors,
        expected_active_snapshots=expected_active_snapshots,
    )


__all__ = ["build_expectation_from_fold_report"]
