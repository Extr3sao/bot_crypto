"""ADMISSION-FOUNDATION-01 — StrategyRouter plane-authority contract (§5, ADM-18).

Enforcement contract only: the frozen POC01 runtime is NOT modified here.
A future runtime router must call ``router_authorizes`` before letting a
strategy version execute on a given plane.
"""

from __future__ import annotations

from .states import AdmissionState, require_minimum_state

PLANE = {
    "LIVE": "LIVE",
    "PAPER": "PAPER",
    "SHADOW": "SHADOW",
    "RESEARCH": "RESEARCH",
}


class PlaneAuthorityError(PermissionError):
    """Raised when a strategy state does not authorize a runtime plane."""


def router_authorizes(admission_state: AdmissionState, plane: str) -> bool:
    """Pure authority mapping (§5):

    PAPER  : state == PAPER_ELIGIBLE or PAPER_ACTIVE
    SHADOW : state >= DISCOVERY_PASS on the promotion chain
    RESEARCH: CANDIDATE and beyond
    LIVE   : never authorized by this contract (no LIVE path exists)
    """
    if plane == "PAPER":
        return admission_state in {AdmissionState.PAPER_ELIGIBLE, AdmissionState.PAPER_ACTIVE}
    if plane == "SHADOW":
        return require_minimum_state(admission_state, AdmissionState.DISCOVERY_PASS)
    if plane == "RESEARCH":
        return require_minimum_state(admission_state, AdmissionState.CANDIDATE)
    return False  # LIVE and unknown planes: fail closed


def assert_plane(admission_state: AdmissionState, plane: str) -> None:
    if not router_authorizes(admission_state, plane):
        raise PlaneAuthorityError(
            f"admission state {admission_state.value} does not authorize plane '{plane}'"
        )
