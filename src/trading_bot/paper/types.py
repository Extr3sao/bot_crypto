"""Paper-trading domain types (TSK-105 in-progress).

Minimal type stubs used by ``harness.py`` and ``test_harness.py``. The
behavioural surface is filled in incrementally as TSK-105 lands
subsequent commits; the dataclass shapes below are the canonical
contract between ``harness.py``, the reporting layer, and tests.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PaperBacktestExpectation:
    """Settlement contract built from a FoldReport before the session.

    Filled in by ``paper/expectations.build_expectation_from_fold_report``.
    The default-zero values let ``harness.PaperSessionRunner`` instantiate
    without blocking tests of the surrounding plumbing.
    """

    expected_median_spread_bps: float = 0.0
    active_snapshots_per_trade: float = 1.0
    min_active_ratio: float = 0.30
    max_scanner_errors: int = 3
    expected_active_snapshots: int | None = None


@dataclass(frozen=True, slots=True)
class PaperSessionResult:
    """Outcome snapshot of one PaperSessionRunner.run_session invocation."""

    session_id: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    duration_ms: int
    snapshots: tuple[Any, ...] = ()
    counters: Any = None
    metrics: Any = None
    execution_summary: Any = None
    report_markdown_path: Any = None
    report_json_path: Any = None


@dataclass(frozen=True, slots=True)
class PaperExecutionSummary:
    """Stub execution summary returned by PaperBroker.reconcile_session().

    Shape-compatible with the eventual TSK-105 implementation; all
    fields default to zero/empty so TDD tests of the surrounding
    plumbing don't blow up while broker logic is unimplemented.
    """

    fills_opened: int = 0
    fills_closed: int = 0
    closed_trades: tuple[Any, ...] = ()
    realized_pnl: float = 0.0
    ending_equity: float = 0.0
    risk_events: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class PaperSessionMetrics:
    """Stub metrics returned by ``build_session_metrics()`` (TSK-105 in-progress).

    Shape-compatible with the eventual TSK-105 implementation. Beyond the
    basic snapshot-derived counters, we pin the broker-derived fields
    ``fills_opened`` and ``ending_equity`` so the contract tests under
    ``tests/unit/paper/test_harness.py`` (``test_runner_includes_execution_summary_when_broker_is_enabled``)
    can assert the values post-broker reconciliation without further
    dataclass mutations when TSK-105 ships the real broker math.
    """

    total_snapshots: int = 0
    active_snapshots: int = 0
    inactive_snapshots: int = 0
    scanner_errors: int = 0
    fills_opened: int = 0
    ending_equity: float = 0.0


__all__ = [
    "PaperBacktestExpectation",
    "PaperExecutionSummary",
    "PaperSessionMetrics",
    "PaperSessionResult",
]
