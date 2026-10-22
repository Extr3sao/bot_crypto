"""WP-EDGE-14B (second half) — what 144.061/day and 48.018/day actually count.

The brief flags a second contradiction: "the selector reports 144.061/day and the tape
bound 48.018/day at 60s" and asks whether they are even the same metric. They are not,
and the difference is the window rule:

* the **tape bound** (``gates.frequency_pooled``) is computed over **non-overlapping**
  60-second windows. It de-overlaps first (``non_overlapping_windows``) and counts how
  many of those windows contain a move that clears the barrier. At 60s only three of the
  ten streams clear at all, giving 12.003 + 24.010 + 12.005 = **48.018**. This is the
  ceiling on *distinct non-overlapping trades* the tape offers.
* the **selector** (``experiments.E-05_frequency``) conditions on ``|imbalance| >= 0.9588``
  and counts, over **overlapping** windows, every second where the selection and a
  barrier-clearing long coincide. Only the two SOLUSDT streams contribute: 84.035 +
  60.026 = **144.061**.

So 144.061 > 48.018 not because the selector finds more trades but because it counts the
same price movement at many overlapping start points. The overlapping count is an
*opportunity* denominator; the non-overlapping count is the *trade* denominator. Reading
144.061 as "trades per day" or 48.018 as "the selector's ceiling" is the defect; the two
coexist only if each is labelled with its window rule and its direction filter.

The non-overlapping tape bound is the number the ACTIVE target (>= 3/day) is measured
against, and at 60s it clears it, which is why the brief can say the target is "not what
blocks the edge".
"""

from __future__ import annotations

from typing import Any

from .evidence import EDGE09_EXPERIMENTS, EDGE09_GATES, read_json, sha256_file

__all__ = [
    "DEFINITIONS",
    "frequency_reconciliation",
    "pooled_by_horizon",
]

#: The three numbers a reader of WP-EDGE-09 meets at 60s, each with its rule stated.
DEFINITIONS = (
    {
        "name": "tape_bound_non_overlapping",
        "source": "gates.frequency_pooled.clearing_per_day",
        "unit": "barrier-clearing windows per day, summed across streams",
        "window_rule": "non-overlapping",
        "direction_filter": "any",
        "selector_conditioned": False,
        "reads_as": "the ceiling on distinct non-overlapping trades the tape offers",
        "is_the_active_denominator": True,
    },
    {
        "name": "tape_any_overlapping",
        "source": "gates.frequency[*].clearing_windows_per_day_overlapping",
        "unit": "barrier-clearing windows per day, per stream",
        "window_rule": "overlapping",
        "direction_filter": "any",
        "selector_conditioned": False,
        "reads_as": "how often a barrier-clearing move starts, counting every second",
        "is_the_active_denominator": False,
    },
    {
        "name": "selector_long_only_overlapping",
        "source": "experiments.E-05_frequency.opportunities_per_day",
        "unit": "selector-conditioned long-only opportunities per day, summed across streams",
        "window_rule": "overlapping",
        "direction_filter": "long_only",
        "selector_conditioned": True,
        "reads_as": "of the seconds the imbalance selector fires, how many clear the barrier long",
        "is_the_active_denominator": False,
    },
)


def _rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def pooled_by_horizon() -> dict[str, Any]:
    """Both pooled curves, kept apart and labelled, for every horizon."""
    gates = read_json(EDGE09_GATES) or {}
    experiments = read_json(EDGE09_EXPERIMENTS) or {}
    tape = _rows(gates, "frequency_pooled")
    selector_rows = _rows((experiments.get("experiments") or {}), "E-05_frequency")

    horizons = sorted(
        {int(row["horizon_seconds"]) for row in tape}
        | {int(row["horizon_seconds"]) for row in selector_rows}
    )
    out: dict[str, Any] = {}
    for horizon in horizons:
        tape_row = next((r for r in tape if int(r["horizon_seconds"]) == horizon), None)
        sel = [r for r in selector_rows if int(r["horizon_seconds"]) == horizon]
        selector_pooled = 0.0
        for row in sel:
            selector_pooled += float(row.get("opportunities_per_day") or 0.0)
        out[str(horizon)] = {
            "horizon_seconds": horizon,
            "tape_bound_non_overlapping_per_day": None
            if tape_row is None
            else tape_row.get("clearing_per_day"),
            "tape_streams_clearing": None
            if tape_row is None
            else len(tape_row.get("streams_with_any_clearing") or {}),
            "tape_total_streams": None if tape_row is None else tape_row.get("streams_summed"),
            "selector_long_only_overlapping_per_day": round(selector_pooled, 6),
            "selector_streams_with_an_opportunity": sum(
                1 for row in sel if (row.get("opportunities_per_day") or 0.0) > 0
            ),
            "selector_condition": sel[0].get("selector") if sel else None,
            "ratio_selector_over_tape": (
                round(selector_pooled / float(tape_row["clearing_per_day"]), 6)
                if tape_row and tape_row.get("clearing_per_day")
                else None
            ),
        }
    return out


def frequency_reconciliation() -> dict[str, Any]:
    """The definitions and both curves, plus the one-line statement of the defect."""
    curves = pooled_by_horizon()
    at_60 = curves.get("60", {})
    return {
        "schema_version": "EDGE14_FREQUENCY_DEFINITIONS_V1",
        "work_package": "WP-EDGE-14B",
        "primary_sources": {
            "gates": {
                "path": str(EDGE09_GATES),
                "sha256": sha256_file(EDGE09_GATES),
            },
            "experiments": {
                "path": str(EDGE09_EXPERIMENTS),
                "sha256": sha256_file(EDGE09_EXPERIMENTS),
            },
        },
        "definitions": list(DEFINITIONS),
        "by_horizon": curves,
        "the_two_numbers": {
            "selector_long_only_overlapping_per_day": at_60.get(
                "selector_long_only_overlapping_per_day"
            ),
            "tape_bound_non_overlapping_per_day": at_60.get("tape_bound_non_overlapping_per_day"),
            "same_metric": False,
            "why": (
                "the selector counts overlapping 60s start points conditioned on extreme "
                "imbalance; the tape bound de-overlaps before counting. Only the "
                "non-overlapping bound maps to distinct trades."
            ),
        },
        "active_target_measured_against": "tape_bound_non_overlapping_per_day",
        "active_target": 3.0,
        "verdict": "FREQUENCY_RECONCILED_BY_WINDOW_RULE",
        "order_sent": False,
        "promotion": "NONE",
    }
