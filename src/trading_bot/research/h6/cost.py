"""P13 — cost accounting implemented exactly from frozen H6 spec.

Frozen total round-trip cost is 10 bps (single canonical number, not
decomposed into per-side fees/slippage). No real historical execution
is performed here. Synthetic tests only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

COST_TOTAL_ROUND_TRIP_BPS = 10
COST_SENSITIVITY_BPS: Sequence[int] = (0, 10, 20, 40)


@dataclass(frozen=True, slots=True)
class H6CostResult:
    gross_return: float
    cost_bps: int
    cost_return: float
    net_return: float
    net_R: float | None


def compute_cost_result(
    entry: float,
    exit: float,
    cost_bps: int = COST_TOTAL_ROUND_TRIP_BPS,
    *,
    quantity: float = 1.0,
) -> H6CostResult:
    if entry <= 0 or exit <= 0:
        raise ValueError("entry/exit must be positive")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")

    gross = (exit - entry) * quantity if exit >= entry else (entry - exit) * quantity
    cost = (abs(exit - entry) if exit != entry else entry) * (cost_bps / 10000.0) * quantity
    net = gross - cost

    risk_per_unit = abs(entry - exit) if exit != entry else entry
    net_R: float | None = net / risk_per_unit if risk_per_unit > 0 else None

    return H6CostResult(
        gross_return=gross / entry if entry > 0 else float("nan"),
        cost_bps=cost_bps,
        cost_return=cost / entry if entry > 0 else float("nan"),
        net_return=net / entry if entry > 0 else float("nan"),
        net_R=net_R,
    )
