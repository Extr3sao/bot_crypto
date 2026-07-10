"""Paper trading (TSK-105 in-progress).

Surface (stable contract):
- ``PaperSessionRunner``: top-level orchestrator (TSK-105).
- ``PaperBroker``: simulator for live-vs-paper reconciliation.
- ``PaperSnapshotArchive``: on-disk persistence of session snapshots.
- ``PaperBacktestExpectation``: pre-session settlement contract sourced
  from a FoldReport (used by Reporting to emit alerts).

Behavioural implementation lands incrementally as the TSK-105 sub-tasks
ship. Currently the broker/archive/expectations/reporting modules are
intentional no-op stubs that just keep ``harness.PaperSessionRunner``
import-clean for downstream tests.
"""

from __future__ import annotations

from .archive import PaperSnapshotArchive
from .broker import PaperBroker
from .harness import PaperSessionRunner
from .types import PaperBacktestExpectation, PaperSessionResult

__all__ = [
    "PaperBacktestExpectation",
    "PaperBroker",
    "PaperSessionResult",
    "PaperSessionRunner",
    "PaperSnapshotArchive",
]
