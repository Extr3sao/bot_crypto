"""Paper-broker stub (TSK-105 in-progress).

Real implementation lands as TSK-105 sub-tasks ship. This stub keeps
``harness.PaperSessionRunner`` import-clean for downstream tests.
"""

from __future__ import annotations

from typing import Any

from .types import PaperExecutionSummary


class PaperBroker:
    """Paper-trade fill simulator (stub)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs

    def reconcile_session(self, *args: Any, **kwargs: Any) -> Any:
        """No-op stub; real implementation pending TSK-105."""
        return PaperExecutionSummary()


__all__ = ["PaperBroker"]
