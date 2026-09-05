"""MA-4 decision contracts: immutable, auditable decision artifacts.

The Decision Engine transforms TradeProposals + MetaRanker V1 results +
DebateReports + evidence into an immutable ``DecisionPackage``. It never
executes: no broker/order/sizing fields exist here, and ``NO_TRADE`` is a
first-class outcome, never an error state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .debate import DebateOutcome
from .trace import TraceContext, VerificationMetadata


class DecisionOutcome(StrEnum):
    """Closed set of decision outcomes.

    ``NO_TRADE`` is first-class information, not an error or missing result.
    Package-level outcome is ``SELECTED`` or ``NO_TRADE``; ``REJECTED``
    manifests at candidate level via ``rejected_alternatives``.
    """

    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"


class DecisionEligibility(StrEnum):
    """Deterministic admissibility verdict for one candidate."""

    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_STALE = "INELIGIBLE_STALE"
    INELIGIBLE_EXPIRED = "INELIGIBLE_EXPIRED"
    INELIGIBLE_FUTURE_DATED = "INELIGIBLE_FUTURE_DATED"
    INELIGIBLE_INVALID_EVIDENCE = "INELIGIBLE_INVALID_EVIDENCE"
    INELIGIBLE_INSUFFICIENT_EVIDENCE = "INELIGIBLE_INSUFFICIENT_EVIDENCE"
    INELIGIBLE_INVALID_REVISION_LINEAGE = "INELIGIBLE_INVALID_REVISION_LINEAGE"
    INELIGIBLE_UNRESOLVED_CONFLICT = "INELIGIBLE_UNRESOLVED_CONFLICT"
    INELIGIBLE_INVALID_TRACE = "INELIGIBLE_INVALID_TRACE"


class DecisionReason(StrEnum):
    """Closed deterministic reason taxonomy (no opaque free-text reasons)."""

    HIGHEST_ADMISSIBLE_SCORE = "HIGHEST_ADMISSIBLE_SCORE"
    NO_VALID_CANDIDATES = "NO_VALID_CANDIDATES"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    FUTURE_DATED = "FUTURE_DATED"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    INVALID_TRACE = "INVALID_TRACE"
    INVALID_REVISION_LINEAGE = "INVALID_REVISION_LINEAGE"
    SUPERSEDED_BY_REVISION = "SUPERSEDED_BY_REVISION"
    LOWER_RANKED_ALTERNATIVE = "LOWER_RANKED_ALTERNATIVE"


class ScoreComponentSource(StrEnum):
    """Declared provenance of every score component (anti-double-counting)."""

    META_RANKER = "META_RANKER"
    DEBATE = "DEBATE"


class DecisionEventType(StrEnum):
    """Typed observability events for the decision plane."""

    DECISION_STARTED = "decision.started"
    DECISION_CANDIDATE_ADMITTED = "decision.candidate_admitted"
    DECISION_CANDIDATE_REJECTED = "decision.candidate_rejected"
    DECISION_SELECTED = "decision.selected"
    DECISION_NO_TRADE = "decision.no_trade"
    DECISION_VERIFIED = "decision.verified"
    DECISION_REJECTED_BY_VERIFIER = "decision.rejected_by_verifier"


class DecisionScoreBreakdown(BaseModel):
    """Decomposable decision score with per-component provenance.

    V1 formula (committed, deterministic):

        final = clamp01(meta_ranker_score - counter_evidence_materiality)

    ``meta_ranker_score`` (source ``META_RANKER``) is the canonical MA-2
    base opportunity score; ``counter_evidence_materiality`` (source
    ``DEBATE``) is the mean materiality of standing unresolved challenges.
    The same information never contributes twice: revisions flow through
    the revised proposal's confidence (already inside the MetaRanker score),
    and only *standing* challenges feed the debate component.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    final_score: float = Field(ge=0.0, le=1.0)
    components: tuple[tuple[str, float, str], ...] = Field(min_length=1)

    @field_validator("components")
    @classmethod
    def _validate_components(
        cls, value: tuple[tuple[str, float, str], ...]
    ) -> tuple[tuple[str, float, str], ...]:
        names = [name for name, _, _ in value]
        if len(names) != len(set(names)):
            raise ValueError("score components must have unique names")
        for _, component_value, source in value:
            if not 0.0 <= component_value <= 1.0:
                raise ValueError("score component values must be within [0, 1]")
            try:
                ScoreComponentSource(source)
            except ValueError as exc:
                raise ValueError(f"unknown score component source: {source}") from exc
        return tuple((name, float(val), source) for name, val, source in value)

    def component(self, name: str) -> float | None:
        """Return one component value by name, or None when absent."""
        for component_name, component_value, _ in self.components:
            if component_name == name:
                return component_value
        return None


class DecisionCandidate(BaseModel):
    """One terminal proposal lineage evaluated by the decision engine."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    final_proposal_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    meta_rank: int = Field(ge=1)
    meta_score: float = Field(ge=0.0, le=1.0)
    debate_id: str | None = None
    debate_outcome: DebateOutcome | None = None
    eligibility: DecisionEligibility
    decision_score: float = Field(ge=0.0, le=1.0)
    score_breakdown: DecisionScoreBreakdown
    supporting_evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    material_dissent: bool = False
    # MA-4F: dissent must survive the decision — who challenged (critic ids).
    challenged_by: tuple[str, ...] = ()
    rejection_reasons: tuple[DecisionReason, ...] = ()
    revision_lineage: tuple[str, ...] = Field(min_length=1)
    trace: TraceContext | None = None

    @field_validator("supporting_evidence_refs", "counter_evidence_refs", mode="before")
    @classmethod
    def _reject_empty_refs(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("candidate evidence references must be non-empty identifiers")
        return value


class RejectedAlternative(BaseModel):
    """Explicitly preserved non-selected alternative (no silent losers)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    proposal_id: str = Field(min_length=1)
    final_proposal_id: str = Field(min_length=1)
    rejection_reasons: tuple[DecisionReason, ...] = Field(min_length=1)
    meta_score: float = Field(ge=0.0, le=1.0)
    decision_score: float = Field(ge=0.0, le=1.0)
    summary: str = ""

    @field_validator("rejection_reasons")
    @classmethod
    def _require_reasons(
        cls, value: tuple[DecisionReason, ...]
    ) -> tuple[DecisionReason, ...]:
        if not value:
            raise ValueError("rejected alternatives require at least one typed reason")
        return value


class DecisionPackage(BaseModel):
    """Immutable, fully auditable decision artifact. Never executes."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    decision_time: datetime
    candidate_set: tuple[DecisionCandidate, ...]
    selected_candidate_id: str | None = None
    rejected_alternatives: tuple[RejectedAlternative, ...] = ()
    outcome: DecisionOutcome
    decision_reasons: tuple[DecisionReason, ...]
    evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    unresolved_conflicts: tuple[str, ...] = ()
    events: tuple[tuple[str, str], ...] = ()
    trace: TraceContext | None = None
    verification_metadata: VerificationMetadata

    @field_validator("decision_time")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        return value

    @field_validator("candidate_set")
    @classmethod
    def _unique_candidates(
        cls, value: tuple[DecisionCandidate, ...]
    ) -> tuple[DecisionCandidate, ...]:
        final_ids = [candidate.final_proposal_id for candidate in value]
        if len(final_ids) != len(set(final_ids)):
            raise ValueError("candidate set must contain unique terminal proposal ids")
        return value

    @field_validator("evidence_refs", "counter_evidence_refs", mode="before")
    @classmethod
    def _reject_empty_refs(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("package evidence references must be non-empty identifiers")
        return value

    @model_validator(mode="after")
    def _validate_package(self) -> DecisionPackage:
        if self.outcome is DecisionOutcome.SELECTED and self.selected_candidate_id is None:
            raise ValueError("SELECTED outcome requires selected_candidate_id")
        if self.outcome is DecisionOutcome.NO_TRADE and self.selected_candidate_id is not None:
            raise ValueError("NO_TRADE outcome cannot carry a selected candidate")
        if self.selected_candidate_id is not None:
            final_ids = {candidate.final_proposal_id for candidate in self.candidate_set}
            if self.selected_candidate_id not in final_ids:
                raise ValueError("selected candidate must exist in the candidate set")
            rejected_ids = {
                alternative.final_proposal_id for alternative in self.rejected_alternatives
            }
            for candidate in self.candidate_set:
                if candidate.final_proposal_id == self.selected_candidate_id:
                    if candidate.eligibility is not DecisionEligibility.ELIGIBLE:
                        raise ValueError("selected candidate must be eligible")
                elif candidate.final_proposal_id not in rejected_ids:
                    raise ValueError(
                        "every non-selected candidate must appear in rejected_alternatives"
                    )
        return self

    def to_dict(self) -> dict[str, Any]:
        """Deterministic JSON-compatible projection for audit/dashboards."""
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "decision_time": self.decision_time.isoformat(),
            "candidate_set": [self._candidate_dict(c) for c in self.candidate_set],
            "selected_candidate_id": self.selected_candidate_id,
            "rejected_alternatives": [a.model_dump(mode="json") for a in self.rejected_alternatives],
            "outcome": self.outcome.value,
            "decision_reasons": [reason.value for reason in self.decision_reasons],
            "evidence_refs": list(self.evidence_refs),
            "counter_evidence_refs": list(self.counter_evidence_refs),
            "unresolved_conflicts": list(self.unresolved_conflicts),
            "events": [[kind, payload] for kind, payload in self.events],
            "trace": self.trace.model_dump(mode="json") if self.trace else None,
            "verification_metadata": self.verification_metadata.model_dump(mode="json"),
        }

    @staticmethod
    def _candidate_dict(candidate: DecisionCandidate) -> dict[str, Any]:
        return {
            "schema_version": candidate.schema_version,
            "proposal_id": candidate.proposal_id,
            "final_proposal_id": candidate.final_proposal_id,
            "asset": candidate.asset,
            "strategy": candidate.strategy,
            "direction": candidate.direction,
            "meta_rank": candidate.meta_rank,
            "meta_score": candidate.meta_score,
            "debate_id": candidate.debate_id,
            "debate_outcome": (
                candidate.debate_outcome.value if candidate.debate_outcome else None
            ),
            "eligibility": candidate.eligibility.value,
            "decision_score": candidate.decision_score,
            "score_breakdown": {
                "final_score": candidate.score_breakdown.final_score,
                "components": [
                    [name, value, source]
                    for name, value, source in candidate.score_breakdown.components
                ],
            },
            "supporting_evidence_refs": list(candidate.supporting_evidence_refs),
            "counter_evidence_refs": list(candidate.counter_evidence_refs),
            "material_dissent": candidate.material_dissent,
            "challenged_by": list(candidate.challenged_by),
            "rejection_reasons": [reason.value for reason in candidate.rejection_reasons],
            "revision_lineage": list(candidate.revision_lineage),
            "trace": candidate.trace.model_dump(mode="json") if candidate.trace else None,
        }


__all__ = [
    "DecisionCandidate",
    "DecisionEligibility",
    "DecisionEventType",
    "DecisionOutcome",
    "DecisionPackage",
    "DecisionReason",
    "DecisionScoreBreakdown",
    "RejectedAlternative",
    "ScoreComponentSource",
]
