"""P6 — spec drift guard.

Runtime economic constants must be derived from the frozen spec, not
independently editable defaults.
"""

from __future__ import annotations

from trading_bot.research.h6.contracts import DATASET_SHA256, SPEC_SHA256
from trading_bot.research.h6.cost import COST_SENSITIVITY_BPS, COST_TOTAL_ROUND_TRIP_BPS
from trading_bot.research.h6.funding import (
    FUNDING_DISCOVERY_ACCOUNTING,
    FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION,
)

EXPECTED_COST_TOTAL_ROUND_TRIP_BPS = 10
EXPECTED_COST_SENSITIVITY_BPS = (0, 10, 20, 40)
EXPECTED_FUNDING_DISCOVERY_ACCOUNTING = "EXCLUDED_WITH_LIMITATION"
EXPECTED_FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION = True
EXPECTED_SPEC_SHA256 = SPEC_SHA256
EXPECTED_DATASET_SHA256 = DATASET_SHA256


def assert_runtime_matches_frozen_spec() -> None:
    """Hard-fail if runtime constants drift from frozen spec."""
    checks = {
        "cost_total_round_trip_bps": (
            COST_TOTAL_ROUND_TRIP_BPS,
            EXPECTED_COST_TOTAL_ROUND_TRIP_BPS,
        ),
        "cost_sensitivity_bps": (
            tuple(COST_SENSITIVITY_BPS),
            EXPECTED_COST_SENSITIVITY_BPS,
        ),
        "funding_policy": (
            FUNDING_DISCOVERY_ACCOUNTING,
            EXPECTED_FUNDING_DISCOVERY_ACCOUNTING,
        ),
        "funding_materiality_gate_before_promotion": (
            FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION,
            EXPECTED_FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION,
        ),
        "spec_sha256": (
            SPEC_SHA256,
            EXPECTED_SPEC_SHA256,
        ),
        "dataset_sha256": (
            DATASET_SHA256,
            EXPECTED_DATASET_SHA256,
        ),
    }

    problems: list[str] = []
    for name, (runtime, expected) in checks.items():
        if runtime != expected:
            problems.append(f"{name}: runtime={runtime!r} expected={expected!r}")

    if problems:
        raise RuntimeError("H6_SPEC_DRIFT: " + "; ".join(problems))
