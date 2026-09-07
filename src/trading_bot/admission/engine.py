"""ADMISSION-FOUNDATION-01 — StrategyAdmissionEngine (the BUILDER).

The engine COLLECTS artifacts and PROPOSES promotions with an evidence
bundle. It never certifies: every proposal must pass the independent
:class:`trading_bot.admission.verifier.StrategyAdmissionVerifier`
(BUILDER != VERIFIER, ADM-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .registry import EvidenceRef, StrategyRegistry, StrategyVersionRecord, canonical_hash
from .states import AdmissionState, validate_transition


@dataclass(frozen=True, slots=True)
class PromotionProposal:
    """A builder-proposed promotion. Never authoritative by itself."""

    strategy_identity: str
    from_state: AdmissionState
    to_state: AdmissionState
    evidence: tuple[EvidenceRef, ...]
    proposed_at: str
    proposal_sha256: str

    @classmethod
    def create(
        cls,
        record: StrategyVersionRecord,
        to_state: AdmissionState,
        evidence: tuple[EvidenceRef, ...],
        proposed_at: str,
    ) -> PromotionProposal:
        validate_transition(record.admission_state, to_state)
        body = {
            "strategy_identity": record.identity_hash(),
            "from_state": record.admission_state.value,
            "to_state": to_state.value,
            "evidence": [e.to_dict() for e in evidence],
            "proposed_at": proposed_at,
        }
        return cls(
            strategy_identity=record.identity_hash(),
            from_state=record.admission_state,
            to_state=to_state,
            evidence=tuple(evidence),
            proposed_at=proposed_at,
            proposal_sha256=canonical_hash(body),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_identity": self.strategy_identity,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "proposed_at": self.proposed_at,
            "proposal_sha256": self.proposal_sha256,
        }


class StrategyAdmissionEngine:
    """Builder: collects artifacts and proposes promotions (§3)."""

    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def propose(
        self,
        strategy_identity: str,
        to_state: AdmissionState,
        evidence: tuple[EvidenceRef, ...],
        *,
        proposed_at: str,
    ) -> PromotionProposal:
        record = self._registry.get(strategy_identity)
        return PromotionProposal.create(record, to_state, evidence, proposed_at)
