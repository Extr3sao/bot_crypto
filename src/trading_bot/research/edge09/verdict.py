"""The classification of one hypothesis, derived from the registered thresholds.

One function, one order of filters, no discretion: an experiment either produces
the numbers this function needs or it is reported as ``INSUFFICIENT_SAMPLE``.

The order matters and is the registered one:

1. sample floor                     → ``INSUFFICIENT_SAMPLE``
2. information content (|IC|)       → ``NO_INFORMATION``
3. positive gross move              → ``NO_GROSS_EDGE``
4. gross at or above the cost       → ``COST_KILLED``   (filter F2)
5. gross at or above 1.5x the cost  → ``COST_KILLED``   (filter F3, stated apart)
6. measurable capacity at the size  → ``CAPACITY_KILLED``
7. opportunity rate for the track   → ``FREQUENCY_KILLED``
8. otherwise                        → ``ADMIT_RESEARCH``

``ADMIT_RESEARCH`` is not a promotion: it means "this deserves the next, more
expensive experiment", and it still carries ``promotion: NONE``.
"""

from __future__ import annotations

from typing import Any

from .registration import (
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    MIN_GROSS_SAFETY_MULTIPLE,
    MIN_OBSERVATIONS,
)

#: Below this, a relationship is not measured at all (registered in the ladder F0).
MIN_ABS_IC = 0.01


def classify(
    *,
    n: int,
    ic: float | None,
    gross_bps: float | None,
    cost_bps: float | None,
    track: str,
    capacity_ok: bool | None = None,
    opportunities_per_day: float | None = None,
    sample_floor: int = MIN_OBSERVATIONS,
) -> dict[str, Any]:
    """Return the classification, the filter that produced it and why."""
    failed = "—"
    reason = ""

    if n < sample_floor:
        return _result(
            "INSUFFICIENT_SAMPLE",
            "F0",
            f"n={n} below the registered floor of {sample_floor}",
            gross_bps,
            cost_bps,
            n,
        )
    if ic is None or abs(ic) < MIN_ABS_IC:
        return _result(
            "NO_INFORMATION",
            "F0",
            f"information content {ic} below the registered |IC| floor of {MIN_ABS_IC}",
            gross_bps,
            cost_bps,
            n,
        )
    if gross_bps is None:
        return _result("INSUFFICIENT_SAMPLE", "F1", "no gross measurement", None, cost_bps, n)
    if gross_bps <= 0.0:
        return _result(
            "NO_GROSS_EDGE",
            "F1",
            f"mean gross move {gross_bps:.4f} bps is not positive",
            gross_bps,
            cost_bps,
            n,
        )
    if cost_bps is None:
        return _result(
            "NO_VIABLE_DATA",
            "F2",
            "the cost of the venue/asset could not be measured",
            gross_bps,
            None,
            n,
        )
    if gross_bps < cost_bps:
        return _result(
            "COST_KILLED",
            "F2",
            f"gross {gross_bps:.4f} bps is below the measured round trip {cost_bps:.4f} bps",
            gross_bps,
            cost_bps,
            n,
        )
    required = cost_bps * MIN_GROSS_SAFETY_MULTIPLE
    if gross_bps < required:
        failed = "F3"
        reason = (
            f"gross {gross_bps:.4f} bps clears the break-even {cost_bps:.4f} bps but not the "
            f"registered {MIN_GROSS_SAFETY_MULTIPLE}x admission margin ({required:.4f} bps)"
        )
        return _result("COST_KILLED", failed, reason, gross_bps, cost_bps, n)
    if capacity_ok is False:
        return _result(
            "CAPACITY_KILLED",
            "F4",
            "the measured book cannot absorb the registered order size inside the barrier",
            gross_bps,
            cost_bps,
            n,
        )
    if (
        track == "ACTIVE"
        and opportunities_per_day is not None
        and opportunities_per_day < ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY
    ):
        return _result(
            "FREQUENCY_KILLED",
            "F5",
            f"{opportunities_per_day:.3f} opportunities/day is below the ACTIVE target "
            f"of {ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY}",
            gross_bps,
            cost_bps,
            n,
        )
    return _result(
        "ADMIT_RESEARCH",
        "—",
        f"gross {gross_bps:.4f} bps clears {required:.4f} bps (1.5x of {cost_bps:.4f} bps)",
        gross_bps,
        cost_bps,
        n,
    )


def _result(
    classification: str,
    failed_filter: str,
    reason: str,
    gross_bps: float | None,
    cost_bps: float | None,
    n: int,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "failed_filter": failed_filter,
        "reason": reason,
        "gross_bps": None if gross_bps is None else round(gross_bps, 6),
        "cost_bps": None if cost_bps is None else round(cost_bps, 6),
        "required_bps": None
        if cost_bps is None
        else round(cost_bps * MIN_GROSS_SAFETY_MULTIPLE, 6),
        "n": n,
        "promotion": "NONE",
    }


def positive(classification: str) -> bool:
    """True only for the one classification that may continue to a next stage."""
    return classification == "ADMIT_RESEARCH"


__all__ = ["MIN_ABS_IC", "classify", "positive"]
