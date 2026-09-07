"""ADMISSION-FOUNDATION-01 — StrategyAdmissionVerifier (the VERIFIER).

Independent of the builder engine: re-derives every gate from the evidence
bundle itself. A proposal without complete, hash-consistent evidence is
rejected (NO EVIDENCE → NO PROMOTION, §4 / ADM-04). This module never
imports :mod:`trading_bot.admission.engine` (BUILDER != VERIFIER).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from .registry import StrategyRegistry, StrategyVersionRecord, canonical_hash
from .states import AdmissionState, validate_transition

#: Required evidence claims per TARGET state (§4). The verifier matches
#: evidence by claim keywords, not by builder assertion.
REQUIRED_EVIDENCE_CLAIMS: dict[AdmissionState, frozenset[str]] = {
    AdmissionState.CANDIDATE: frozenset({"idea"}),
    AdmissionState.SPECIFIED: frozenset({"spec"}),
    AdmissionState.IMPLEMENTED: frozenset({"implementation"}),
    AdmissionState.TESTED: frozenset({"test"}),
    AdmissionState.BACKTEST_PASS: frozenset({"backtest", "cost"}),
    AdmissionState.ROBUSTNESS_PASS: frozenset({"robustness"}),
    AdmissionState.DISCOVERY_PASS: frozenset(
        {"discovery_manifest", "data_fingerprint", "pit_proof", "results", "stability"}
    ),
    AdmissionState.CONFIRMATION_PASS: frozenset(
        {
            "discovery_manifest",
            "execution_manifest",
            "data_fingerprint",
            "cost_model",
            "pit_proof",
            "results",
            "stability",
            "confirmation_manifest",
        }
    ),
    AdmissionState.HOLDOUT_PASS: frozenset({"holdout_results", "pit_proof"}),
    AdmissionState.SHADOW_PASS: frozenset({"shadow_ledger", "shadow_isolation"}),
    AdmissionState.PAPER_ELIGIBLE: frozenset({"shadow_ledger", "router_authority"}),
}


class VerificationError(ValueError):
    """Raised when a promotion proposal fails independent verification."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    accepted: bool
    reason: str
    checked: tuple[str, ...]


def _claim_matches(evidence_claim: str, required: str) -> bool:
    ec = evidence_claim.lower()
    if required in ec:
        return True
    aliases = {
        "discovery_manifest": ("discovery",),
        "execution_manifest": ("execution",),
        "data_fingerprint": ("fingerprint", "manifest"),
        "cost_model": ("cost",),
        "pit_proof": ("pit",),
        "results": ("result",),
        "stability": ("stability", "thirds", "halves"),
        "confirmation_manifest": ("confirmation_manifest", "confirmation manifest", "confirmation protocol", "confirmation"),
        "shadow_ledger": ("shadow",),
        "shadow_isolation": ("isolation",),
        "router_authority": ("router",),
        "holdout_results": ("holdout",),
    }
    return any(a in ec for a in aliases.get(required, ()))


class StrategyAdmissionVerifier:
    """Independent verifier: BUILDER != VERIFIER (§3, ADM-03)."""

    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def verify(self, proposal: Any) -> VerificationResult:
        """Verify a PromotionProposal from the builder (duck-typed, no import)."""
        checked: list[str] = []
        record = self._registry.get(proposal.strategy_identity)

        # 1) transition legality re-derived independently
        try:
            validate_transition(record.admission_state, proposal.to_state)
        except ValueError as exc:
            return VerificationResult(False, str(exc), tuple(checked))
        checked.append("transition_legal")

        # 2) proposal integrity
        body = {
            "strategy_identity": proposal.strategy_identity,
            "from_state": record.admission_state.value,
            "to_state": proposal.to_state.value,
            "evidence": [e.to_dict() for e in proposal.evidence],
            "proposed_at": proposal.proposed_at,
        }
        if canonical_hash(body) != proposal.proposal_sha256:
            return VerificationResult(False, "proposal hash mismatch", tuple(checked))
        checked.append("proposal_integrity")

        # 3) state consistency: proposal must originate from the recorded state
        if proposal.from_state != record.admission_state:
            return VerificationResult(
                False,
                f"stale proposal: from_state {proposal.from_state} != registry {record.admission_state}",
                tuple(checked),
            )
        checked.append("state_consistency")

        # 4) required evidence present (by claim) and hash-consistent
        required = REQUIRED_EVIDENCE_CLAIMS.get(proposal.to_state, frozenset())
        claims: list[str] = []
        for req in sorted(required):
            hit = any(_claim_matches(e.claim, req) for e in proposal.evidence)
            claims.append(f"evidence:{req}:{'ok' if hit else 'MISSING'}")
            if not hit:
                return VerificationResult(
                    False, f"missing required evidence: {req}", tuple(checked)
                )
        for e in proposal.evidence:
            recomputed = canonical_hash(
                {"claim": e.claim, "source": e.source, "evidence": e.evidence, "decision": e.decision}
            )
            if e.sha256 != recomputed:
                return VerificationResult(
                    False, f"evidence hash mismatch: {e.claim}", tuple(checked)
                )
        checked.append("evidence_complete")
        checked.append("evidence_hashes_ok")

        # 5) PIT proof must be explicit for any market-data-consuming promotion
        if proposal.to_state in {
            AdmissionState.DISCOVERY_PASS,
            AdmissionState.CONFIRMATION_PASS,
            AdmissionState.HOLDOUT_PASS,
        }:
            pit_ok = any("pit" in e.claim.lower() for e in proposal.evidence)
            if not pit_ok:
                return VerificationResult(False, "PIT proof absent", tuple(checked))
            checked.append("pit_proof_present")

        return VerificationResult(True, "verified", tuple(checked))

    def apply(
        self, proposal: Any, *, decision: str, decided_at: str
    ) -> StrategyVersionRecord:
        """Apply a VERIFIED proposal: returns the updated registry record.

        The verifier — not the builder — is the only component allowed to
        move a record's admission state.
        """
        result = self.verify(proposal)
        if not result.accepted:
            raise VerificationError(result.reason)
        old = self._registry.get(proposal.strategy_identity)
        updated = dataclasses.replace(
            old,
            admission_state=proposal.to_state,
            promotion_history=(
                *tuple(old.promotion_history),
                {
                    "from": old.admission_state.value,
                    "to": proposal.to_state.value,
                    "decision": decision,
                    "decided_at": decided_at,
                    "proposal_sha256": proposal.proposal_sha256,
                },
            ),
        )
        identity = self._registry.register(updated)
        # keep the record reachable under the same identity lineage
        if identity != proposal.strategy_identity:
            # identity includes only immutable fields, so it must not change
            raise VerificationError("internal identity drift on apply")
        return updated
