"""Paper trading session orchestration (TSK-105)."""

from .archive import PaperSnapshotArchive
from .broker import PaperBroker
from .expectations import (
    build_expectation_from_backtest_result,
    build_expectation_from_fold_report,
)
from .harness import PaperSessionRunner
from .reporting import (
    build_session_alerts,
    build_session_metrics,
    build_session_report_payload,
    render_session_markdown,
    write_session_report,
)
from .types import (
    PaperBacktestExpectation,
    PaperClosedTrade,
    PaperExecutionSummary,
    PaperFill,
    PaperPosition,
    PaperSessionAlert,
    PaperSessionMetrics,
    PaperSessionResult,
)

__all__ = [
    "PaperBacktestExpectation",
    "PaperBroker",
    "PaperClosedTrade",
    "PaperExecutionSummary",
    "PaperFill",
    "PaperPosition",
    "PaperSessionAlert",
    "PaperSessionMetrics",
    "PaperSessionResult",
    "PaperSessionRunner",
    "PaperSnapshotArchive",
    "build_expectation_from_backtest_result",
    "build_expectation_from_fold_report",
    "build_session_alerts",
    "build_session_metrics",
    "build_session_report_payload",
    "render_session_markdown",
    "write_session_report",
]
