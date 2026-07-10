"""Paper-trading reporting stub (TSK-105 in-progress).

Stubs for build_session_metrics / build_session_alerts /
write_session_report. Real implementation lands as TSK-105 sub-tasks
ship.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .types import PaperSessionMetrics


def build_session_metrics(
    snapshots: Any,
    counters: Any,
    execution_summary: Any,
) -> Any:
    """No-op stub; real implementation pending TSK-105."""
    return PaperSessionMetrics()


def build_session_alerts(result: Any, expectation: Any) -> list[Any]:
    """No-op stub returning an empty alert list."""
    return []


def write_session_report(
    result: Any,
    output_dir: Path | str | None,
    expectation: Any,
) -> tuple[Path | None, Path | None]:
    """No-op stub returning (None, None) so harness stays import-clean."""
    return (None, None)


__all__ = [
    "build_session_alerts",
    "build_session_metrics",
    "write_session_report",
]
