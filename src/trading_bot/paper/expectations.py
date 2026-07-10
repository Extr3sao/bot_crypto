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
    """No-op stub returning a zeroed PaperBacktestExpectation."""
    return PaperBacktestExpectation(
        expected_median_spread_bps=expected_median_spread_bps,
        active_snapshots_per_trade=active_snapshots_per_trade,
        min_active_ratio=min_active_ratio,
        max_scanner_errors=max_scanner_errors,
    )


__all__ = ["build_expectation_from_fold_report"]
