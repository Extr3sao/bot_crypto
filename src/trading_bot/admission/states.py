"""ADMISSION-FOUNDATION-01 — admission states and the fail-closed state machine.

The admission pipeline is a strictly linear promotion chain with explicit
terminal/side states. Every transition not present in ``LEGAL_TRANSITIONS``
raises :class:`IllegalTransitionError` (fail-closed, ADM-05).
"""

from __future__ import annotations

import enum


class AdmissionState(enum.StrEnum):
    """Explicit admission states (checkpoint §2)."""
    IDEA = "IDEA"
    CANDIDATE = "CANDIDATE"
    SPECIFIED = "SPECIFIED"
    IMPLEMENTED = "IMPLEMENTED"
    TESTED = "TESTED"
    BACKTEST_PASS = "BACKTEST_PASS"
    ROBUSTNESS_PASS = "ROBUSTNESS_PASS"
    DISCOVERY_PASS = "DISCOVERY_PASS"
    CONFIRMATION_PASS = "CONFIRMATION_PASS"
    HOLDOUT_PASS = "HOLDOUT_PASS"
    SHADOW_PASS = "SHADOW_PASS"
    PAPER_ELIGIBLE = "PAPER_ELIGIBLE"

    # side states (non-linear but sanctioned)
    CONFIRMATION_BLOCKED = "CONFIRMATION_BLOCKED"
    PAPER_ACTIVE = "PAPER_ACTIVE"

    # terminal states
    REJECTED = "REJECTED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    BLOCKED = "BLOCKED"
    RETIRED = "RETIRED"

    # explicit grandfathered status for pre-registry runtime strategies
    LEGACY_PAPER_BASELINE = "LEGACY_PAPER_BASELINE"


#: Terminal states accept no further promotion.
TERMINAL_STATES: frozenset[AdmissionState] = frozenset(
    {
        AdmissionState.REJECTED,
        AdmissionState.INSUFFICIENT_SAMPLE,
        AdmissionState.RETIRED,
    }
)

#: BLOCKED is recoverable only to the state it was blocked from is NOT allowed
#: generically; unblocking requires a new explicit evidence-bound transition.
LEGAL_TRANSITIONS: dict[AdmissionState, frozenset[AdmissionState]] = {
    AdmissionState.IDEA: frozenset({AdmissionState.CANDIDATE, AdmissionState.REJECTED}),
    AdmissionState.CANDIDATE: frozenset({AdmissionState.SPECIFIED, AdmissionState.REJECTED, AdmissionState.BLOCKED}),
    AdmissionState.SPECIFIED: frozenset({AdmissionState.IMPLEMENTED, AdmissionState.REJECTED, AdmissionState.BLOCKED}),
    AdmissionState.IMPLEMENTED: frozenset({AdmissionState.TESTED, AdmissionState.REJECTED, AdmissionState.BLOCKED}),
    AdmissionState.TESTED: frozenset(
        {AdmissionState.BACKTEST_PASS, AdmissionState.INSUFFICIENT_SAMPLE, AdmissionState.REJECTED, AdmissionState.BLOCKED}
    ),
    AdmissionState.BACKTEST_PASS: frozenset(
        {AdmissionState.ROBUSTNESS_PASS, AdmissionState.INSUFFICIENT_SAMPLE, AdmissionState.REJECTED, AdmissionState.BLOCKED}
    ),
    AdmissionState.ROBUSTNESS_PASS: frozenset(
        {AdmissionState.DISCOVERY_PASS, AdmissionState.INSUFFICIENT_SAMPLE, AdmissionState.REJECTED, AdmissionState.BLOCKED}
    ),
    AdmissionState.DISCOVERY_PASS: frozenset(
        {
            AdmissionState.CONFIRMATION_PASS,
            AdmissionState.CONFIRMATION_BLOCKED,
            AdmissionState.INSUFFICIENT_SAMPLE,
            AdmissionState.REJECTED,
            AdmissionState.BLOCKED,
        }
    ),
    AdmissionState.CONFIRMATION_BLOCKED: frozenset(
        {AdmissionState.CONFIRMATION_PASS, AdmissionState.REJECTED, AdmissionState.RETIRED, AdmissionState.BLOCKED}
    ),
    AdmissionState.CONFIRMATION_PASS: frozenset(
        {AdmissionState.HOLDOUT_PASS, AdmissionState.INSUFFICIENT_SAMPLE, AdmissionState.REJECTED, AdmissionState.BLOCKED}
    ),
    AdmissionState.HOLDOUT_PASS: frozenset(
        {AdmissionState.SHADOW_PASS, AdmissionState.INSUFFICIENT_SAMPLE, AdmissionState.REJECTED, AdmissionState.BLOCKED}
    ),
    AdmissionState.SHADOW_PASS: frozenset({AdmissionState.PAPER_ELIGIBLE, AdmissionState.REJECTED, AdmissionState.RETIRED}),
    AdmissionState.PAPER_ELIGIBLE: frozenset({AdmissionState.PAPER_ACTIVE, AdmissionState.RETIRED}),
    AdmissionState.PAPER_ACTIVE: frozenset({AdmissionState.RETIRED, AdmissionState.PAPER_ELIGIBLE}),
    # grandfathered strategies may only retire or be re-baselined explicitly
    AdmissionState.LEGACY_PAPER_BASELINE: frozenset({AdmissionState.RETIRED, AdmissionState.BLOCKED}),
    AdmissionState.BLOCKED: frozenset(set()),  # unblocking = new evidence-bound promotion via engine+verifier
}


class IllegalTransitionError(ValueError):
    """Raised when a transition is not in LEGAL_TRANSITIONS (fail-closed)."""


def validate_transition(current: AdmissionState, target: AdmissionState) -> None:
    """Fail closed on any transition not explicitly sanctioned (ADM-05)."""
    if current in TERMINAL_STATES:
        raise IllegalTransitionError(f"{current} is terminal; no transitions allowed")
    allowed = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransitionError(f"illegal admission transition: {current} -> {target}")


def require_minimum_state(current: AdmissionState, minimum: AdmissionState) -> bool:
    """Plane-authority ordering check used by the router contract (ADM-18).

    Returns True only if ``current`` is at or beyond ``minimum`` on the
    linear promotion chain. Side/terminal states never satisfy a minimum.
    """
    chain = [
        AdmissionState.IDEA,
        AdmissionState.CANDIDATE,
        AdmissionState.SPECIFIED,
        AdmissionState.IMPLEMENTED,
        AdmissionState.TESTED,
        AdmissionState.BACKTEST_PASS,
        AdmissionState.ROBUSTNESS_PASS,
        AdmissionState.DISCOVERY_PASS,
        AdmissionState.CONFIRMATION_PASS,
        AdmissionState.HOLDOUT_PASS,
        AdmissionState.SHADOW_PASS,
        AdmissionState.PAPER_ELIGIBLE,
        AdmissionState.PAPER_ACTIVE,
    ]
    if current not in chain or minimum not in chain:
        return False
    return chain.index(current) >= chain.index(minimum)
