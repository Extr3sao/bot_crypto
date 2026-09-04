"""Deterministic opportunity collection and ranking for MA-2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trading_bot.multi_agent.contracts import AgentEvidence, TradeDirection, TradeProposal
from trading_bot.multi_agent.specialists import AssetAssessment


class OpportunityError(ValueError):
    """Raised when an opportunity cannot be admitted fail-closed."""


@dataclass(frozen=True, slots=True)
class ConflictCase:
    conflict_id: str
    asset: str
    proposal_ids: tuple[str, ...]
    directions: tuple[str, ...]
    status: str = "CONFLICTED"


@dataclass(frozen=True, slots=True)
class Opportunity:
    proposal: TradeProposal
    evidence_refs: tuple[str, ...]
    source_agent_id: str
    source_agent_version: str


@dataclass(frozen=True, slots=True)
class RankedOpportunity:
    rank: int
    proposal_id: str
    score: float
    score_components: tuple[tuple[str, float], ...]
    evidence_refs: tuple[str, ...]
    conflict_status: str
    agent_id: str
    agent_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "proposal_id": self.proposal_id,
            "score": self.score,
            "score_components": dict(self.score_components),
            "evidence_refs": self.evidence_refs,
            "conflict_status": self.conflict_status,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
        }


@dataclass(frozen=True, slots=True)
class OpportunitySnapshot:
    opportunities: tuple[Opportunity, ...]
    conflicts: tuple[ConflictCase, ...]

    def proposal_ids(self) -> tuple[str, ...]:
        return tuple(item.proposal.proposal_id for item in self.opportunities)


class OpportunityBoard:
    """Proposal board with deterministic semantic identity and snapshots."""

    def __init__(self, *, run_id: str, now: datetime) -> None:
        if not run_id:
            raise ValueError("run_id is required")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        self.run_id = run_id
        self.now = now
        self._opportunities: dict[str, Opportunity] = {}
        self._semantic_ids: dict[tuple[object, ...], str] = {}
        self._evidence: dict[str, AgentEvidence] = {}

    def add_evidence(self, evidence: AgentEvidence) -> None:
        if evidence.run_id != self.run_id:
            raise OpportunityError("evidence run does not match board")
        existing = self._evidence.get(evidence.evidence_id)
        if existing is not None and existing != evidence:
            raise OpportunityError("evidence ID already exists with different content")
        self._evidence[evidence.evidence_id] = evidence

    def add(
        self,
        proposal: TradeProposal,
        *,
        source_agent_id: str,
        source_agent_version: str,
    ) -> Opportunity:
        """Admit a fresh, evidenced canonical proposal idempotently."""
        if proposal.run_id != self.run_id:
            raise OpportunityError("proposal run does not match board")
        if proposal.direction is TradeDirection.NO_TRADE:
            raise OpportunityError("NO_TRADE is a valid evaluation result, not an opportunity")
        if proposal.data_time > self.now:
            raise OpportunityError("future proposal data is not admissible")
        if proposal.expires_at is not None and self.now >= proposal.expires_at:
            raise OpportunityError("proposal is expired")
        if not proposal.evidence_refs:
            raise OpportunityError("proposal requires evidence")
        for ref in proposal.evidence_refs:
            evidence = self._evidence.get(ref)
            if evidence is None:
                raise OpportunityError(f"proposal evidence is not registered: {ref}")
            if evidence.producer_agent_id != source_agent_id:
                raise OpportunityError(f"evidence source does not match proposal source: {ref}")
            if evidence.run_id != proposal.run_id or (
                evidence.trace is not None and evidence.trace.trace_id != proposal.trace_id
            ):
                raise OpportunityError(f"proposal evidence trace mismatch: {ref}")
            if not evidence.is_valid_at(proposal.created_at):
                raise OpportunityError(f"proposal evidence unavailable at creation: {ref}")

        candidate = Opportunity(
            proposal=proposal,
            evidence_refs=proposal.evidence_refs,
            source_agent_id=source_agent_id,
            source_agent_version=source_agent_version,
        )
        existing_by_id = self._opportunities.get(proposal.proposal_id)
        if existing_by_id is not None:
            if existing_by_id != candidate:
                raise OpportunityError("proposal ID already exists with different content")
            return existing_by_id

        semantic_key = self._semantic_key(proposal)
        existing_id = self._semantic_ids.get(semantic_key)
        if existing_id is not None:
            return self._opportunities[existing_id]
        self._opportunities[proposal.proposal_id] = candidate
        self._semantic_ids[semantic_key] = proposal.proposal_id
        return candidate

    def expire_stale(self, *, now: datetime | None = None) -> tuple[str, ...]:
        current = now or self.now
        expired = tuple(
            sorted(
                proposal_id
                for proposal_id, opportunity in self._opportunities.items()
                if opportunity.proposal.expires_at is not None
                and current >= opportunity.proposal.expires_at
            )
        )
        for proposal_id in expired:
            opportunity = self._opportunities.pop(proposal_id)
            self._semantic_ids.pop(self._semantic_key(opportunity.proposal), None)
        return expired

    def snapshot(self) -> OpportunitySnapshot:
        opportunities = tuple(self._opportunities[key] for key in sorted(self._opportunities))
        conflicts: list[ConflictCase] = []
        for index, left in enumerate(opportunities):
            for right in opportunities[index + 1 :]:
                if self._conflicts(left.proposal, right.proposal):
                    ids = tuple(sorted((left.proposal.proposal_id, right.proposal.proposal_id)))
                    by_id = {item.proposal.proposal_id: item.proposal for item in opportunities}
                    conflicts.append(
                        ConflictCase(
                            conflict_id=f"conflict:{left.proposal.asset}:{':'.join(ids)}",
                            asset=left.proposal.asset,
                            proposal_ids=ids,
                            directions=tuple(by_id[item].direction.value for item in ids),
                        )
                    )
        conflicts.sort(key=lambda item: item.conflict_id)
        return OpportunitySnapshot(opportunities=opportunities, conflicts=tuple(conflicts))

    def rank(
        self,
        *,
        assessments: dict[str, AssetAssessment] | None = None,
        now: datetime | None = None,
    ) -> tuple[RankedOpportunity, ...]:
        current = now or self.now
        snapshot = self.snapshot()
        conflicted = {
            proposal_id
            for conflict in snapshot.conflicts
            for proposal_id in conflict.proposal_ids
        }
        ranker = MetaRanker()
        ranked = [
            ranker.score(
                opportunity,
                assessment=(assessments or {}).get(opportunity.proposal.asset),
                conflicted=opportunity.proposal.proposal_id in conflicted,
            )
            for opportunity in snapshot.opportunities
            if opportunity.proposal.expires_at is None
            or current < opportunity.proposal.expires_at
        ]
        ranked.sort(key=lambda item: (-item.score, item.proposal_id))
        return tuple(
            RankedOpportunity(
                rank=index,
                proposal_id=item.proposal_id,
                score=item.score,
                score_components=item.score_components,
                evidence_refs=item.evidence_refs,
                conflict_status=item.conflict_status,
                agent_id=item.agent_id,
                agent_version=item.agent_version,
            )
            for index, item in enumerate(ranked, start=1)
        )

    @staticmethod
    def _semantic_key(proposal: TradeProposal) -> tuple[object, ...]:
        """Canonical identity excluding proposal ID and evidence IDs."""
        return (
            proposal.asset,
            proposal.direction.value,
            proposal.strategy,
            proposal.timeframe,
            proposal.regime,
            proposal.data_time,
            proposal.created_at,
            proposal.expires_at,
            proposal.invalidation,
            proposal.confidence,
        )

    @staticmethod
    def _conflicts(left: TradeProposal, right: TradeProposal) -> bool:
        if left.asset != right.asset or left.direction is right.direction:
            return False
        left_end = left.expires_at or left.created_at
        right_end = right.expires_at or right.created_at
        return left.data_time < right_end and right.data_time < left_end


class MetaRanker:
    """Transparent deterministic ranker with inspectable score components."""

    version = "meta-ranker-v1"

    def score(
        self,
        opportunity: Opportunity,
        *,
        assessment: AssetAssessment | None,
        conflicted: bool,
    ) -> RankedOpportunity:
        proposal = opportunity.proposal
        components = (
            ("proposal_confidence", round(proposal.confidence, 6)),
            ("evidence_quality", 1.0 if opportunity.evidence_refs else 0.0),
            ("asset_assessment", round(assessment.confidence, 6) if assessment else 0.0),
            ("freshness", round(self._freshness(proposal), 6)),
            (
                "regime_fit",
                1.0 if assessment is not None and assessment.regime == proposal.regime else 0.5,
            ),
            (
                "strategy_applicability",
                round(assessment.market_quality, 6) if assessment else 0.0,
            ),
        )
        return RankedOpportunity(
            rank=0,
            proposal_id=proposal.proposal_id,
            score=round(sum(value for _, value in components) / len(components), 6),
            score_components=components,
            evidence_refs=opportunity.evidence_refs,
            conflict_status="CONFLICTED" if conflicted else "CLEAR",
            agent_id=opportunity.source_agent_id,
            agent_version=opportunity.source_agent_version,
        )

    @staticmethod
    def _freshness(proposal: TradeProposal) -> float:
        if proposal.expires_at is None:
            return 1.0
        total = (proposal.expires_at - proposal.created_at).total_seconds()
        remaining = (proposal.expires_at - proposal.data_time).total_seconds()
        return max(0.0, min(1.0, remaining / total if total > 0 else 0.0))


__all__ = [
    "ConflictCase",
    "MetaRanker",
    "Opportunity",
    "OpportunityBoard",
    "OpportunityError",
    "OpportunitySnapshot",
    "RankedOpportunity",
]
