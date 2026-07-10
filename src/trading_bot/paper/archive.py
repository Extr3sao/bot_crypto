"""Paper-trading archive stub (TSK-105 in-progress).

Full implementation lands as TSK-105 sub-tasks ship.
This stub keeps ``harness.PaperSessionRunner`` import-clean
without blocking unrelated post-mergequality gates.
"""

from __future__ import annotations

from typing import Any


class PaperSnapshotArchive:
    """On-disk persistence of session snapshots (stub).

    Stub surface (lands fully in TSK-105 sub-tasks):

    - Context-manager protocol: ``__enter__``/``__exit__`` so tests can
      write ``with PaperSnapshotArchive(...) as archive:`` AND nest it in
      a multi-manager ``with`` (e.g. with ``PaperBroker``).
    - ``archive_session(session_id, started_at_ms, snapshots)``: stores
      the snapshots list under ``session_id``. In-memory stub only.
    - ``list_session(session_id) -> list``: returns the stored snapshots
      for that session (or empty list if absent).
    - ``purge_older_than(cutoff_ms)``: no-op stub.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs
        # In-memory snapshot store keyed by session_id. Full SQL-backed
        # implementation lands as part of TSK-105; this stub keeps
        # ``PaperSessionRunner`` import-clean and unblocks the 14
        # ``tests/unit/paper/test_harness.py`` runner tests that use the
        # archive as a context manager (with the broker in nested with).
        self._sessions: dict[str, list[Any]] = {}

    def __enter__(self) -> PaperSnapshotArchive:
        """Pine contract: conftest fixtures + ``PaperSessionRunner`` runs the archive via ``with ... as archive:``."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """No-op close path; full ``sqlite3`` shutdown lands with TSK-105."""

    def archive_session(
        self,
        session_id: str,
        started_at_ms: int,  # forwarded to TSK-105 retention index
        snapshots: list[Any],
    ) -> None:
        """Store ``snapshots`` (defensively copied) under ``session_id``."""
        # ``started_at_ms`` retained in the signature for retention/purge
        # queries in TSK-105; not consumed by the in-memory stub.
        del started_at_ms
        self._sessions[session_id] = list(snapshots)

    def list_session(self, session_id: str) -> list[Any]:
        """Return stored snapshots for ``session_id``; empty list if absent."""
        return self._sessions.get(session_id, [])

    def purge_older_than(self, *args: Any, **kwargs: Any) -> None:
        """No-op stub; real implementation pending TSK-105."""
        return None


__all__ = ["PaperSnapshotArchive"]
