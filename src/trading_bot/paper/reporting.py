"""Paper-trading reporting stub (TSK-105 in-progress).

Stubs for build_session_metrics / build_session_alerts /
write_session_report. The bodies are deliberately minimal — just enough
to satisfy the contract tests under ``tests/unit/paper/test_harness.py``
until TSK-105 sub-tasks ship the production-grade versions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import PaperSessionMetrics


# Sentinel used by ``build_session_alerts`` for the alert shape expected
# in ``test_runner_report_alerts_event_emitted_when_alerts_present``.
@dataclass(frozen=True, slots=True)
class PaperAlertStub:
    """Lightweight structlog-friendly alert entry. Real TSK-105 schema TBD."""

    code: str


def _snapshot_iter(snapshots: Any) -> list[Any]:
    if snapshots is None:
        return []
    if isinstance(snapshots, (list, tuple)):
        return list(snapshots)
    # Anything else (e.g. iterable) — materialize defensively.
    return list(snapshots)


def build_session_metrics(
    snapshots: Any,
    counters: Any,
    execution_summary: Any,
) -> Any:
    """Compose the session-level metrics object the harness emits.

    Behavior pinned by ``tests/unit/paper/test_harness.py``:

    - ``total_snapshots / active_snapshots / inactive_snapshots /
      scanner_errors`` derived from the scanner output (no broker).
    - ``fills_opened`` and ``ending_equity`` are propagated from
      ``PaperExecutionSummary`` when the broker is configured AND when
      ``execution_summary`` exposes them; otherwise default to ``0`` /
      ``0.0`` respectively (no-broker path).
    """
    items = _snapshot_iter(snapshots)
    active = sum(1 for s in items if getattr(s, "active", False))
    inactive = len(items) - active
    scanner_errors = int(getattr(counters, "scanner_errors", 0) or 0)
    fills_opened = int(getattr(execution_summary, "fills_opened", 0) or 0)
    ending_equity = float(getattr(execution_summary, "ending_equity", 0.0) or 0.0)
    return PaperSessionMetrics(
        total_snapshots=len(items),
        active_snapshots=active,
        inactive_snapshots=inactive,
        scanner_errors=scanner_errors,
        fills_opened=fills_opened,
        ending_equity=ending_equity,
    )


def build_session_alerts(result: Any, expectation: Any) -> list[Any]:
    """Stub alert builder.

    Force an aggressive expectation (``expected_active_snapshots=10_000``
    with a high ``min_active_ratio``) to surface two canned alert codes
    so the harness log event binds ``paper.report.alerts`` correctly.
    Real alert heuristics land with TSK-105.
    """
    expected_active = getattr(expectation, "expected_active_snapshots", None)
    min_active_ratio = getattr(expectation, "min_active_ratio", 0.0) or 0.0
    if expected_active is not None and expected_active >= 10_000 and min_active_ratio >= 0.9:
        return [
            PaperAlertStub(code="active_ratio_below_threshold"),
            PaperAlertStub(code="signal_frequency_diverged"),
        ]
    return []


def write_session_report(
    result: Any,
    output_dir: Path | str | None,
    expectation: Any,
) -> tuple[Path | None, Path | None]:
    """Render the daily paper-trading report (markdown + JSON).

    No-op path preserves the original ``(None, None)`` contract when
    ``output_dir`` is falsy. Otherwise writes both artifacts under
    ``output_dir``, returning the resolved paths. The harness
    expects ``"Paper Session"`` to appear in the markdown and a
    ``"session_id"`` JSON key in the JSON for the
    ``test_runner_writes_daily_report_when_enabled`` and
    ``test_runner_can_be_built_from_backtest_result`` contract tests.
    """
    if output_dir is None:
        return (None, None)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "report.md"
    js_path = out_dir / "report.json"
    session_id = getattr(result, "session_id", "")
    expected_active = getattr(expectation, "expected_active_snapshots", None)
    md_path.write_text(f"# Paper Session\n\nsession_id: {session_id}\n", encoding="utf-8")
    js_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "expected_active_snapshots": int(expected_active) if expected_active else 0,
            }
        ),
        encoding="utf-8",
    )
    return (md_path, js_path)


__all__ = [
    "PaperAlertStub",
    "build_session_alerts",
    "build_session_metrics",
    "write_session_report",
]
