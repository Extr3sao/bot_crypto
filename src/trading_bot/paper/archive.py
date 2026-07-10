"""Paper-trading archive stub (TSK-105 in-progress).

Full implementation lands as TSK-105 sub-tasks ship.
This stub keeps ``harness.PaperSessionRunner`` import-clean
without blocking unrelated post-mergequality gates.
"""

from __future__ import annotations

from typing import Any


class PaperSnapshotArchive:
    """On-disk persistence of session snapshots (stub)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs

    def archive_session(self, *args: Any, **kwargs: Any) -> None:
        """No-op stub; real implementation pending TSK-105."""
        return None

    def purge_older_than(self, *args: Any, **kwargs: Any) -> None:
        """No-op stub; real implementation pending TSK-105."""
        return None


__all__ = ["PaperSnapshotArchive"]
