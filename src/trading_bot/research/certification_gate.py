"""Reusable candidate-certification gate (extracted after RFC-031/RFC-032).

Thin, low-risk validator that encodes the certification invariant discovered the
hard way in RFC-031: a candidate is PROMOTABLE only if *every* mandatory gate
passes, and a positive later gate can never compensate a failed earlier gate.

RFC-031 certified EXT-TSMOM-001 as REJECTED because it opened unsupported short
spot positions (TRADABILITY FAIL) even though reproduction and economics passed.
RFC-030 had already labelled EXT-XMOM-001 a paper candidate despite a failed
robustness gate.  Both defects are the same bug class: gate *order* / gate
*compensation*.  This module makes that invariant executable and testable.

It intentionally contains no strategy logic and no PnL maths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class GateStatus(StrEnum):
    """Outcome of a single certification gate."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REACHED = "NOT_REACHED"


#: Mandatory gates, in evaluation order.  All must PASS for promotion (§61).
MANDATORY_GATES: tuple[str, ...] = (
    "G_VALIDATION",
    "G_ROBUSTNESS",
    "G_HOLDOUT",
    "G_TRADABILITY",
    "G_INDEPENDENT_VERIFICATION",
)


@dataclass(frozen=True, slots=True)
class GateCheck:
    """Single implementation-level feasibility check."""

    check_id: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CertificationGateResult:
    """Result of evaluating the certification invariant."""

    gates: Mapping[str, str]
    promotable: bool
    blocking_gates: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)


def evaluate_promotion(gates: Mapping[str, str]) -> CertificationGateResult:
    """Apply the certification invariant PROMOTABLE = AND(mandatory gates).

    A gate absent from ``gates`` is treated as NOT_REACHED, which is not a PASS,
    so a missing mandatory gate blocks promotion.  A later gate returning PASS
    while an earlier mandatory gate FAILs does not lift the result (§61).
    """
    blocking: list[str] = []
    notes: list[str] = []
    for gate in MANDATORY_GATES:
        status = str(gates.get(gate, GateStatus.NOT_REACHED)).upper()
        if status != GateStatus.PASS:
            blocking.append(gate)
    promotable = len(blocking) == 0
    if not promotable:
        notes.append("a later positive gate cannot compensate a failed mandatory gate")
    return CertificationGateResult(
        gates=dict(gates),
        promotable=promotable,
        blocking_gates=tuple(blocking),
        notes=tuple(notes),
    )


def check_no_unsupported_short_spot(negative_weight_count: int,
                                    borrow_evidence_present: bool) -> GateCheck:
    """Spot books must not carry short exposure without explicit borrow evidence."""
    passed = negative_weight_count == 0 or borrow_evidence_present
    return GateCheck(
        check_id="no_unsupported_short_spot",
        passed=passed,
        detail=(f"negative_weights={negative_weight_count} "
                f"borrow_evidence={borrow_evidence_present}"),
    )


def check_instrument_feasible(spot_variants: Mapping[str, bool]) -> GateCheck:
    """The instrument must be executable on spot (long yes, short needs borrow)."""
    long_ok = bool(spot_variants.get("LONG_SPOT"))
    short_ok = bool(spot_variants.get("SHORT_SPOT"))
    passed = long_ok and not short_ok
    return GateCheck(
        check_id="instrument_feasible",
        passed=passed,
        detail=f"variants={dict(spot_variants)}",
    )


def check_execution_timing(signal_time_index: int, execution_time_index: int,
                           require_t_plus_1: bool) -> GateCheck:
    """Execution must be strictly after the decision data when T+1 is required."""
    passed = (execution_time_index > signal_time_index) if require_t_plus_1 else True
    return GateCheck(
        check_id="execution_timing",
        passed=passed,
        detail=(f"signal_index={signal_time_index} "
                f"execution_index={execution_time_index} "
                f"require_t_plus_1={require_t_plus_1}"),
    )


def check_cost_reconciled(max_abs_diff_bps: float, tol_bps: float = 1e-6) -> GateCheck:
    """Cost accounting must reconcile against its stated convention."""
    return GateCheck(
        check_id="cost_reconciled",
        passed=max_abs_diff_bps <= tol_bps,
        detail=f"max_abs_diff_bps={max_abs_diff_bps} tol_bps={tol_bps}",
    )


def check_universe_pit(listing_dates_respected: bool,
                       forward_fill_before_listing: bool) -> GateCheck:
    """Universe construction must respect listing dates and avoid forward-fill."""
    passed = listing_dates_respected and not forward_fill_before_listing
    return GateCheck(
        check_id="universe_pit",
        passed=passed,
        detail=(f"listing_dates_respected={listing_dates_respected} "
                f"forward_fill_before_listing={forward_fill_before_listing}"),
    )


def check_gate_order(gates: Mapping[str, str]) -> GateCheck:
    """A later PASS must not be reported as promotion when an earlier gate failed."""
    order_violation = False
    seen_fail = False
    for gate in MANDATORY_GATES:
        status = str(gates.get(gate, GateStatus.NOT_REACHED)).upper()
        if status == GateStatus.FAIL:
            seen_fail = True
        elif status == GateStatus.PASS and seen_fail:
            order_violation = True
    return GateCheck(
        check_id="gate_order",
        passed=not order_violation,
        detail=("later gate PASS after earlier FAIL" if order_violation
                else "no later-pass/earlier-fail ordering violation"),
    )
