"""MA-3 debate contracts: critiques, revisions, and debate reports.

Smallest immutable typed artifacts for structured debate. These extend the
canonical MA-0 contracts; they never replace them. No trading decision is
encoded here: stances and outcomes describe debate state, not execution
authority (MA-4 owns selection; RiskManager stays outside MA-3).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import TradeDirection
from .evidence import AgentEvidence
from .trace import TraceContext


class CritiqueStance(StrEnum):
    """Critic stance on a proposal (debate state, not execution authority)."""

    SUPPORT = "SUPPORT"
    CHALLENGE = "CHALLENGE"
    ABSTAIN = "ABSTAIN"


class RequestedAction(StrEnum):
    """What the critic asks the proposal owner to do next."""

    NONE = "NONE"
    PROVIDE_EVIDENCE = "PROVIDE_EVIDENCE"
    REVISE = "REVISE"
    WITHDRAW = "WITHDRAW"


class DebateTerminationReason(StrEnum):
    """Terminal states of a bounded debate session.

    ``UNRESOLVED`` and ``INSUFFICIENT_EVIDENCE`` are first-class information
    for MA-4, not system failures.
    """

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_NEW_EVIDENCE = "NO_NEW_EVIDENCE"
    MAX_ROUNDS = "MAX_ROUNDS"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class DebateOutcome(StrEnum):
    """Qualitative debate outcome; describes state, never execution."""

    SUPPORTED = "SUPPORTED"
    CHALLENGED = "CHALLENGED"
    REVISED = "REVISED"
    UNRESOLVED = "UNRESOLVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DebateEventType(StrEnum):
    """Typed observability events emitted during a debate."""

    DEBATE_STARTED = "debate.started"
    DEBATE_CHALLENGE = "debate.challenge"
    DEBATE_EVIDENCE_REQUESTED = "debate.evidence_requested"
    DEBATE_EVIDENCE_RECEIVED = "debate.evidence_received"
    DEBATE_EVIDENCE_INSUFFICIENT = "debate.evidence_insufficient"
    DEBATE_PROPOSAL_REVISED = "debate.proposal_revised"
    DEBATE_TERMINATED = "debate.terminated"


class DebateRouterDecision(StrEnum):
    """Router verdict for one conflict/proposal group."""

    NO_DEBATE = "NO_DEBATE"
    DEBATE_REQUIRED = "DEBATE_REQUIRED"


class DebateRouteReason(StrEnum):
    """Deterministic, closed-set reasons for requiring a debate."""

    DIRECTIONAL_CONFLICT = "directional_conflict"
    MATERIAL_COUNTER_SIGNAL = "material_counter_signal"
    EVIDENCE_INSUFFICIENCY = "evidence_insufficiency"
    REGIME_INCONSISTENCY = "regime_inconsistency"
    MATERIAL_DISAGREEMENT = "material_disagreement"


class CritiqueRecord(BaseModel):
    """Immutable typed critique artifact produced by one critic.

    Carries stance and materiality only; never a final trading decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    critique_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    critic_agent_id: str = Field(min_length=1)
    critic_version: str = Field(min_length=1)
    stance: CritiqueStance
    materiality: float = Field(ge=0.0, le=1.0)
    claim: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    requested_action: RequestedAction = RequestedAction.NONE
    trace: TraceContext | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("critique timestamps must be timezone-aware")
        return value

    @field_validator("evidence_refs", "counter_evidence_refs", mode="before")
    @classmethod
    def _reject_empty_refs(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("critique evidence references must be non-empty identifiers")
        return value

    @model_validator(mode="after")
    def _validate_stance(self) -> CritiqueRecord:
        if self.stance is CritiqueStance.SUPPORT and self.requested_action in (
            RequestedAction.REVISE,
            RequestedAction.WITHDRAW,
        ):
            raise ValueError("SUPPORT cannot request REVISE or WITHDRAW")
        if self.stance is CritiqueStance.CHALLENGE and self.claim.strip().lower() in {
            "",
            "ok",
            "none",
        }:
            raise ValueError("CHALLENGE requires a substantive claim")
        if self.stance is CritiqueStance.CHALLENGE and not (
            self.counter_evidence_refs or self.requested_action is not RequestedAction.NONE
        ):
            raise ValueError("CHALLENGE must bind counter-evidence or request an action")
        return self


class ProposalRevision(BaseModel):
    """Immutable lineage record linking a revised proposal to its critique.

    Historical ``TradeProposal`` objects are never mutated: a revision always
    emits a new canonical proposal and records the link here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    original_proposal_id: str = Field(min_length=1)
    revised_proposal_id: str = Field(min_length=1)
    triggering_critique_ids: tuple[str, ...] = Field(min_length=1)
    revision_reason: str = Field(min_length=1)
    trace: TraceContext | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("revision timestamps must be timezone-aware")
        return value

    @field_validator("triggering_critique_ids", mode="before")
    @classmethod
    def _reject_empty_critique_ids(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("triggering_critique_ids must be non-empty identifiers")
        return value

    @model_validator(mode="after")
    def _validate_distinct(self) -> ProposalRevision:
        if self.original_proposal_id == self.revised_proposal_id:
            raise ValueError("revised proposal must differ from the original")
        return self


class DebateReport(BaseModel):
    """Immutable, fully auditable record of one completed debate session.

    Holds only debate state: critiques, evidence, requests, revisions and
    termination metadata. No BUY/SELL decision and no execution authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    debate_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    proposal_ids: tuple[str, ...] = Field(min_length=1)
    participants: tuple[str, ...] = Field(min_length=1)
    initial_claims: tuple[str, ...]
    critiques: tuple[CritiqueRecord, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    unique_supporting_evidence_count: int = Field(ge=0)
    unique_counter_evidence_count: int = Field(ge=0)
    evidence_attribution: tuple[tuple[str, tuple[str, ...]], ...] = ()
    evidence_requests: tuple[str, ...] = ()
    evidence_responses: tuple[str, ...] = ()
    revisions: tuple[ProposalRevision, ...] = ()
    unresolved_conflicts: tuple[str, ...] = ()
    round_count: int = Field(ge=1)
    max_rounds: int = Field(ge=1)
    termination_reason: DebateTerminationReason
    outcome: DebateOutcome
    events: tuple[tuple[str, str], ...] = ()
    trace: TraceContext | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("report timestamps must be timezone-aware")
        return value

    def to_dict(self) -> dict[str, Any]:
        """Deterministic JSON-compatible projection for reports/dashboards."""
        return {
            "schema_version": self.schema_version,
            "debate_id": self.debate_id,
            "run_id": self.run_id,
            "proposal_ids": list(self.proposal_ids),
            "participants": list(self.participants),
            "initial_claims": list(self.initial_claims),
            "critiques": [c.model_dump(mode="json") for c in self.critiques],
            "supporting_evidence": list(self.supporting_evidence),
            "counter_evidence": list(self.counter_evidence),
            "unique_supporting_evidence_count": self.unique_supporting_evidence_count,
            "unique_counter_evidence_count": self.unique_counter_evidence_count,
            "evidence_attribution": {k: list(v) for k, v in self.evidence_attribution},
            "evidence_requests": list(self.evidence_requests),
            "evidence_responses": list(self.evidence_responses),
            "revisions": [r.model_dump(mode="json") for r in self.revisions],
            "unresolved_conflicts": list(self.unresolved_conflicts),
            "round_count": self.round_count,
            "max_rounds": self.max_rounds,
            "termination_reason": self.termination_reason.value,
            "outcome": self.outcome.value,
            "events": [[kind, payload] for kind, payload in self.events],
            "trace": self.trace.model_dump(mode="json") if self.trace else None,
            "created_at": self.created_at.isoformat(),
        }


class DebatePosition(BaseModel):
    """One canonical proposal plus its owner inside a debate."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    proposal_id: str = Field(min_length=1)
    owner_agent_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    direction: TradeDirection
    strategy: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()


class EvidenceItem(BaseModel):
    """Canonicalized evidence view used for dedup-safe debate accounting."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    evidence_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    referenced_by: tuple[str, ...] = Field(min_length=1)

    @classmethod
    def from_agent_evidence(cls, evidence: AgentEvidence, referrer: str) -> EvidenceItem:
        return cls(
            evidence_id=evidence.evidence_id,
            source_ref=evidence.source_ref,
            content_hash=evidence.content_hash,
            referenced_by=(referrer,),
        )

    def merged(self, referrer: str) -> EvidenceItem:
        if referrer in self.referenced_by:
            return self
        return self.model_copy(
            update={"referenced_by": tuple(sorted((*self.referenced_by, referrer)))}
        )


__all__ = [
    "CritiqueRecord",
    "CritiqueStance",
    "DebateEventType",
    "DebateOutcome",
    "DebatePosition",
    "DebateReport",
    "DebateRouteReason",
    "DebateRouterDecision",
    "DebateTerminationReason",
    "EvidenceItem",
    "ProposalRevision",
    "RequestedAction",
]
