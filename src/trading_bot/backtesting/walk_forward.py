"""Walk-forward helpers for TSK-104 F3b."""

from __future__ import annotations

from .engine import BacktestEngine
from .types import BacktestInputs, BacktestResult


def walk_forward_run(engine: BacktestEngine, inputs: BacktestInputs) -> list[BacktestResult]:
    """Execute the test window of each configured fold.

    Training windows are carried in ``BacktestInputs.walk_forward_splits`` for
    auditability and leakage checks, but this F3b slice only replays the test
    window because the engine itself is strategy-agnostic and has no fitting
    phase yet.
    """
    if not inputs.walk_forward_splits:
        raise ValueError("walk_forward_run requiere al menos un fold configurado.")

    results: list[BacktestResult] = []
    for _, _, test_start, test_end in inputs.walk_forward_splits:
        fold_result = engine.run(inputs.symbols, test_start, test_end, timeframe=inputs.timeframe)
        if isinstance(fold_result, list):
            results.extend(fold_result)
        else:
            results.append(fold_result)
    return results


__all__ = ["walk_forward_run"]
