"""RFC-030 continuation §13 — exploratory, NON-CERTIFIABLE borrow-cost bounds.

When historical borrow *availability* is unknown but a *rate* series exists, the
only honest thing that can be produced is a labelled sensitivity analysis: an upper
and lower bound on the short-leg cost, and a break-even borrow rate at which a gross
spread stops surviving.

These results are **exploratory**. Every object here carries
``certifiable = False`` and can never unlock a G3 promotion, feed a DEV/VALIDATION
result, or be reported as an economic verdict. If availability is unknown, a real
short could not have been placed at all, so a bound is a *hypothetical*.

Research/PAPER only. Deterministic, no clock, no RNG.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["BoundScenario", "ScenarioResult", "borrow_cost_bounds"]

BPS = 10_000.0


@dataclass(frozen=True, slots=True)
class BoundScenario:
    """One labelled borrow-rate assumption for the sensitivity sweep."""

    label: str
    borrow_bps_per_day: float

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "borrow_bps_per_day": self.borrow_bps_per_day}


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """§13 — an explicitly non-certifiable scenario outcome."""

    label: str
    borrow_bps_per_day: float
    borrow_cost: float
    pair_net_pnl: float
    survives: bool
    certifiable: bool = False
    note: str = "EXPLORATORY_NON_CERTIFIABLE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "borrow_bps_per_day": self.borrow_bps_per_day,
            "borrow_cost": self.borrow_cost,
            "pair_net_pnl": self.pair_net_pnl,
            "survives": self.survives,
            "certifiable": self.certifiable,
            "note": self.note,
        }


def borrow_cost_bounds(
    *,
    pair_gross_pnl: float,
    short_notional: float,
    holding_days: float,
    borrow_bps_per_day: Sequence[float],
    other_costs: float = 0.0,
) -> tuple[list[ScenarioResult], float | None]:
    """Sweep borrow rates and report the break-even borrow rate.

    Returns ``(results, break_even_bps_per_day)``. The break-even is the borrow rate
    at which ``pair_net_pnl == 0``; ``None`` when no non-negative rate can reach it
    (the spread already loses before borrow, or the gross spread is non-positive).
    Every ``ScenarioResult`` is ``certifiable=False`` by construction.
    """
    results: list[ScenarioResult] = []
    for rate in borrow_bps_per_day:
        borrow_cost = rate * holding_days * short_notional / BPS
        net = pair_gross_pnl - other_costs - borrow_cost
        results.append(
            ScenarioResult(
                label=f"borrow_{rate:g}_bps_per_day",
                borrow_bps_per_day=rate,
                borrow_cost=borrow_cost,
                pair_net_pnl=net,
                survives=net > 0.0,
            )
        )

    denom = holding_days * short_notional
    if denom <= 0.0 or pair_gross_pnl - other_costs <= 0.0:
        break_even: float | None = None
    else:
        break_even = (pair_gross_pnl - other_costs) * BPS / denom
        if not math.isfinite(break_even) or break_even < 0.0:
            break_even = None
    return results, break_even
