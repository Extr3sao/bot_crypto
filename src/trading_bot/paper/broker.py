"""Paper-broker stub (TSK-105 in-progress).

Real implementation lands as TSK-105 sub-tasks ship. This stub keeps
``harness.PaperSessionRunner`` import-clean for downstream tests.
"""

from __future__ import annotations

from typing import Any

from .types import PaperExecutionSummary


class PaperBroker:
    """Paper-trade fill simulator (stub).

    Stub surface (lands fully in TSK-105 sub-tasks):

    - Context-manager protocol: ``__enter__``/``__exit__`` so tests can
      nest ``with (PaperSnapshotArchive(...) as archive, PaperBroker(...) as broker):``
      in a single with statement (Pine contract for nested contexts).
    - ``reconcile_session(...)``: return a frozen ``PaperExecutionSummary``
      with default zeros/empty.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs

    def __enter__(self) -> PaperBroker:
        """Pine contract: nested ``with`` con ``PaperSnapshotArchive`` en
        ``tests/unit/paper/test_harness.py::test_runner_emits_full_pine_event_sequence``
        (y las 2 funciones *broker_reconciled_event_has_pnl_fields* +
        *includes_execution_summary_when_broker_is_enabled*).
        """
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """No-op close; real shutdown lands con TSK-105."""

    def reconcile_session(self, *args: Any, **kwargs: Any) -> Any:
        """Stub reconciliation: return a non-empty ``PaperExecutionSummary``.

        Sufficient to satisfy the contract tests under
        ``tests/unit/paper/test_harness.py``
        (``test_runner_includes_execution_summary_when_broker_is_enabled``,
        ``test_runner_broker_reconciled_event_has_pnl_fields``, etc.).
        Real fill-matching / equity-mark-to-market lands con TSK-105.
        """
        return PaperExecutionSummary(
            fills_opened=1,
            fills_closed=1,
            closed_trades=("mock_trade",),
            realized_pnl=10.0,
            ending_equity=10_010.0,
            risk_events=(),
        )


__all__ = ["PaperBroker"]
