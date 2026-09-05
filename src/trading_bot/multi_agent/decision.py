"""MA-4 deterministic Evidence-Based Decision Engine V1.

Transforms TradeProposals + MetaRanker V1 results + DebateReports + evidence
into an immutable ``DecisionPackage`` with explicit ``SELECTED`` / ``REJECTED``
/ ``NO_TRADE`` outcomes. The engine never executes and holds no execution
authority: no sizing, no broker, no risk override.

Central principles (committed):

* No majority voting — three correlated agents are not three independent
  pieces of evidence; decisions reason over unique evidence, debate outcome
  and material dissent.
* Score provenance: every score component declares its source and the same
  information never contributes twice (revisions are already reflected in
  the revised proposal's MetaRanker score, so only *standing* challenges
  feed the debate-derived penalty).
* Single temporal authority: every decision time derives from the injected
  run clock (``AgentBus.now()``); no wall-clock calls exist in this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final

from trading_bot.multi_agent.contracts import (
    DebateOutcome,
    DebateReport,
    TradeProposal,
    VerificationMetadata,
)
from trading_bot.multi_agent.contracts.decision import (
    DecisionCandidate,
    DecisionEligibility,
    DecisionEventType,
    DecisionOutcome,
    DecisionPackage,
    DecisionReason,
    DecisionScoreBreakdown,
    RejectedAlternative,
    ScoreComponentSource,
)
from trading_bot.multi_agent.opportunity import MetaRanker, Opportunity, OpportunitySnapshot
from trading_bot.multi_agent.specialists import AssetAssessment

DECISION_SCHEMA_VERSION: Final[str] = "ma-4-v1"
DECISION_ENGINE_ID: Final[str] = "decision-engine"
DECISION_VERIFIER_ID: Final[str] = "decision-package-verifier"
# A proposal whose data_time is older than this is stale at decision time
# (aligned with the MA-3 evidence staleness horizon).
PROPOSAL_STALE_AFTER: Final = timedelta(hours=24)

_ELIGIBILITY_REASON: Final[dict[DecisionEligibility, DecisionReason]] = {
    DecisionEligibility.INELIGIBLE_STALE: DecisionReason.STALE,
    DecisionEligibility.INELIGIBLE_EXPIRED: DecisionReason.EXPIRED,
    DecisionEligibility.INELIGIBLE_FUTURE_DATED: DecisionReason.FUTURE_DATED,
    DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE: DecisionReason.INVALID_EVIDENCE,
    DecisionEligibility.INELIGIBLE_INSUFFICIENT_EVIDENCE: DecisionReason.INSUFFICIENT_EVIDENCE,
    DecisionEligibility.INELIGIBLE_INVALID_REVISION_LINEAGE: (
        DecisionReason.INVALID_REVISION_LINEAGE
    ),
    DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT: DecisionReason.UNRESOLVED_CONFLICT,
    DecisionEligibility.INELIGIBLE_INVALID_TRACE: DecisionReason.INVALID_TRACE,
}


class DecisionError(ValueError):
    """Raised when a decision cannot be produced fail-closed."""


class DecisionVerificationStatus(StrEnum):
    """Verdict of the independent deterministic package verifier."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# MA-4B — deterministic terminal revision resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineageResolution:
    """Terminal proposal per lineage root, plus superseded members."""

    terminal_by_root: Mapping[str, str]
    lineage_of: Mapping[str, str]  # any known member -> lineage root
    depth_of: Mapping[str, int]  # proposal id -> revision depth (root = 0)
    invalid_roots: frozenset[str]  # roots with cyclic or branched lineage


class TerminalProposalResolver:
    """Resolves revision lineages to one terminal proposal per root.

    Fail-closed: a cycle or a branch inside a lineage marks that root
    invalid; the root's candidates become ineligible and can never be
    selected. Structural corruption never silently selects anything.
    """

    def resolve(
        self,
        reports: Sequence[DebateReport],
        proposals: Mapping[str, TradeProposal],
    ) -> LineageResolution:
        edges: dict[str, str] = {}
        for report in sorted(reports, key=lambda item: item.debate_id):
            for revision in report.revisions:
                original = revision.original_proposal_id
                revised = revision.revised_proposal_id
                if revised not in proposals:
                    raise DecisionError(
                        f"revision references unknown proposal: {revised}"
                    )
                existing = edges.get(original)
                if existing is not None and existing != revised:
                    # A branch: two children claim the same original.
                    edges[original] = f"BRANCHED:{existing}|{revised}"
                elif existing is None:
                    edges[original] = revised

        # Every known proposal participates in resolution: a proposal without
        # revisions is its own terminal lineage root.
        members: set[str] = set(proposals)
        for original, revised in edges.items():
            members.add(original)
            members.add(revised)

        targets = {value for value in edges.values() if not value.startswith("BRANCHED:")}
        roots = sorted(member for member in members if member not in targets)

        terminal_by_root: dict[str, str] = {}
        lineage_of: dict[str, str] = {}
        depth_of: dict[str, int] = {}
        invalid: set[str] = set()
        visited: set[str] = set()

        for root in roots:
            lineage = {root}
            depth_of[root] = 0
            lineage_of[root] = root
            visited.add(root)
            cursor = root
            depth = 0
            terminal = root
            valid = True
            while cursor in edges:
                nxt = edges[cursor]
                if nxt.startswith("BRANCHED:"):
                    valid = False
                    break
                if nxt in lineage:
                    valid = False  # cycle
                    break
                lineage.add(nxt)
                lineage_of[nxt] = root
                visited.add(nxt)
                depth += 1
                depth_of[nxt] = depth
                cursor = terminal = nxt
            if not valid:
                invalid.add(root)
                for member in lineage:
                    lineage_of[member] = root
                continue
            terminal_by_root[root] = terminal

        # Members unreachable from any root sit on (or descend from) a cycle:
        # fail closed by making each an invalid pseudo-root.
        for member in sorted(members - visited):
            lineage_of[member] = member
            depth_of[member] = 0
            invalid.add(member)

        return LineageResolution(
            terminal_by_root=terminal_by_root,
            lineage_of=lineage_of,
            depth_of=depth_of,
            invalid_roots=frozenset(invalid),
        )


# ---------------------------------------------------------------------------
# Debate-derived read model (provenance: DEBATE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DebateFacts:
    """Debate information for one proposal lineage root."""

    debate_id: str | None
    outcome: DebateOutcome | None
    supporting_refs: tuple[str, ...]
    counter_refs: tuple[str, ...]
    standing_challenge_materiality: float  # mean materiality of standing challenges
    challenged_by: tuple[str, ...]  # critic ids of all CHALLENGE critiques


def _debate_facts(reports: Sequence[DebateReport], root: str) -> DebateFacts:
    report = next((item for item in reports if root in item.proposal_ids), None)
    if report is None:
        return DebateFacts(
            debate_id=None,
            outcome=None,
            supporting_refs=(),
            counter_refs=(),
            standing_challenge_materiality=0.0,
            challenged_by=(),
        )
    answered: set[str] = set()
    for revision in report.revisions:
        answered.update(revision.triggering_critique_ids)
    challenges = [
        critique
        for critique in report.critiques
        if critique.stance.value == "CHALLENGE"
    ]
    standing = [c for c in challenges if c.critique_id not in answered]
    materiality = (
        round(sum(c.materiality for c in standing) / len(standing), 6) if standing else 0.0
    )
    return DebateFacts(
        debate_id=report.debate_id,
        outcome=report.outcome,
        supporting_refs=report.supporting_evidence,
        counter_refs=report.counter_evidence,
        standing_challenge_materiality=materiality,
        challenged_by=tuple(sorted({c.critic_agent_id for c in challenges})),
    )


# ---------------------------------------------------------------------------
# MA-4C/D/E/J — eligibility, scoring, deterministic selection
# ---------------------------------------------------------------------------


class DecisionEngine:
    """Deterministic, non-executing decision engine (V1)."""

    version = "decision-engine-v1"

    def __init__(self, *, run_id: str) -> None:
        if not run_id:
            raise DecisionError("run_id is required")
        self.run_id = run_id
        self._resolver = TerminalProposalResolver()

    def decide(
        self,
        *,
        snapshot: OpportunitySnapshot,
        proposals: Mapping[str, TradeProposal],
        evidence_registry: Mapping[str, Any],
        reports: Sequence[DebateReport] = (),
        assessments: Mapping[str, AssetAssessment] | None = None,
        now: datetime,
    ) -> DecisionPackage:
        if now.tzinfo is None or now.utcoffset() is None:
            raise DecisionError("decision time must be timezone-aware")
        # -- Run authority (ADR-MA-0006) -------------------------------------
        # Every consumed artifact must belong to this run. ``trace_id`` is
        # scoped *inside* ``run_id``: a matching trace never overrides a run
        # mismatch. Foreign-run artifacts fail closed explicitly — never
        # silently ignored, remapped or rewritten.
        #   RUN_BOUND: TradeProposal (mapping + board path), DebateReport
        #   (which scopes its ProposalRevisions), AgentEvidence,
        #   AssetAssessment (via its required trace).
        #   GLOBAL_SAFE: ConflictCase (derived board metadata, no authority).
        if any(proposal.run_id != self.run_id for proposal in proposals.values()):
            raise DecisionError("proposal run does not match engine run")
        # Sibling artifact: snapshot proposals are the same TradeProposal
        # class via the OpportunityBoard path — enforce the identical rule.
        if any(
            opportunity.proposal.run_id != self.run_id
            for opportunity in snapshot.opportunities
        ):
            raise DecisionError("board proposal run does not match engine run")
        # DEF-MA4-001: a foreign-run DebateReport must never influence
        # eligibility, counter-evidence, dissent, scores or selection.
        if any(report.run_id != self.run_id for report in reports):
            raise DecisionError("debate report run does not match engine run")
        # Sibling artifact: AssetAssessment feeds the MetaRanker regime fit
        # and always carries a trace — foreign-run assessments rejected too.
        if assessments is not None and any(
            assessment.trace.run_id != self.run_id
            for assessment in assessments.values()
        ):
            raise DecisionError("assessment run does not match engine run")

        events: list[tuple[str, str]] = []
        events.append((DecisionEventType.DECISION_STARTED.value, json.dumps({})))

        resolution = self._resolver.resolve(reports, proposals)
        reports_sorted = tuple(sorted(reports, key=lambda item: item.debate_id))
        conflicted_ids = {
            proposal_id
            for conflict in snapshot.conflicts
            for proposal_id in conflict.proposal_ids
        }

        # -- MA-4U: canonical iteration order (sorted terminal ids) ----------
        board_opportunities = {
            opportunity.proposal.proposal_id: opportunity
            for opportunity in snapshot.opportunities
        }
        terminal_ids = sorted(resolution.terminal_by_root)

        candidates: list[DecisionCandidate] = []
        alternatives: list[RejectedAlternative] = []

        meta_scores: dict[str, float] = {}
        for root in terminal_ids:
            final_id = resolution.terminal_by_root[root]
            final_proposal = proposals.get(final_id)
            if final_proposal is None:
                raise DecisionError(f"terminal proposal missing: {final_id}")
            owner_opportunity = board_opportunities.get(root) or board_opportunities.get(final_id)
            source_agent = owner_opportunity.source_agent_id if owner_opportunity else "unknown"
            source_version = owner_opportunity.source_agent_version if owner_opportunity else "0"
            lineage_conflicted = any(
                pid in conflicted_ids for pid in self._lineage_members(resolution, root)
            )
            scored = MetaRanker().score(
                Opportunity(
                    proposal=final_proposal,
                    evidence_refs=tuple(final_proposal.evidence_refs),
                    source_agent_id=source_agent,
                    source_agent_version=source_version,
                ),
                assessment=(assessments or {}).get(final_proposal.asset),
                conflicted=lineage_conflicted,
            )
            meta_scores[root] = scored.score
        ranked = sorted(meta_scores, key=lambda pid: (-meta_scores[pid], pid))
        rank_of = {pid: index for index, pid in enumerate(ranked, start=1)}

        for root in terminal_ids:
            final_id = resolution.terminal_by_root[root]
            final_proposal = proposals[final_id]
            facts = _debate_facts(reports_sorted, root)
            eligibility, blocking_reasons = self._eligibility(
                final_proposal,
                resolution=resolution,
                root=root,
                facts=facts,
                evidence_registry=evidence_registry,
                now=now,
                conflicted_ids=conflicted_ids,
            )
            counter_materiality = (
                facts.standing_challenge_materiality
                if eligibility is DecisionEligibility.ELIGIBLE
                else 0.0
            )
            breakdown = DecisionScoreBreakdown(
                final_score=round(
                    max(0.0, min(1.0, meta_scores[root] - counter_materiality)), 6
                ),
                components=(
                    ("meta_ranker_score", meta_scores[root], ScoreComponentSource.META_RANKER.value),
                    (
                        "counter_evidence_materiality",
                        counter_materiality,
                        ScoreComponentSource.DEBATE.value,
                    ),
                ),
            )
            supporting = tuple(
                sorted({*final_proposal.evidence_refs, *facts.supporting_refs})
            )
            counter = tuple(sorted(set(facts.counter_refs)))
            candidates.append(
                DecisionCandidate(
                    schema_version=DECISION_SCHEMA_VERSION,
                    proposal_id=root,
                    final_proposal_id=final_id,
                    asset=final_proposal.asset,
                    strategy=final_proposal.strategy,
                    direction=final_proposal.direction.value,
                    meta_rank=rank_of[root],
                    meta_score=meta_scores[root],
                    debate_id=facts.debate_id,
                    debate_outcome=facts.outcome,
                    eligibility=eligibility,
                    decision_score=breakdown.final_score,
                    score_breakdown=breakdown,
                    supporting_evidence_refs=supporting,
                    counter_evidence_refs=counter,
                    material_dissent=bool(facts.challenged_by),
                    challenged_by=facts.challenged_by,
                    rejection_reasons=blocking_reasons,
                    revision_lineage=tuple(self._lineage_members(resolution, root)),
                    trace=final_proposal.trace,
                )
            )
            events.append(
                (
                    DecisionEventType.DECISION_CANDIDATE_ADMITTED.value
                    if eligibility is DecisionEligibility.ELIGIBLE
                    else DecisionEventType.DECISION_CANDIDATE_REJECTED.value,
                    json.dumps({"proposal_id": root, "eligibility": eligibility.value}),
                )
            )

        # -- MA-4J: deterministic selection -----------------------------------
        eligible = sorted(
            (c for c in candidates if c.eligibility is DecisionEligibility.ELIGIBLE),
            key=lambda c: (-c.decision_score, c.final_proposal_id),
        )
        decision_reasons: tuple[DecisionReason, ...]
        if eligible:
            winner = eligible[0]
            selected_id: str | None = winner.final_proposal_id
            outcome = DecisionOutcome.SELECTED
            decision_reasons = (DecisionReason.HIGHEST_ADMISSIBLE_SCORE,)
            events.append(
                (DecisionEventType.DECISION_SELECTED.value, json.dumps({"proposal_id": selected_id}))
            )
        else:
            winner = None
            selected_id = None
            outcome = DecisionOutcome.NO_TRADE
            decision_reasons = self._no_trade_reasons(candidates)
            events.append((DecisionEventType.DECISION_NO_TRADE.value, json.dumps({})))

        # -- MA-4G: explicit rejected alternatives (no silent losers) --------
        alternatives = self._rejected_alternatives(candidates, selected_id, decision_reasons)

        evidence_refs = tuple(
            sorted({ref for c in candidates for ref in c.supporting_evidence_refs})
        )
        counter_refs = tuple(
            sorted({ref for c in candidates for ref in c.counter_evidence_refs})
        )
        unresolved = tuple(
            sorted(
                c.debate_id
                for c in candidates
                if c.debate_outcome is DebateOutcome.UNRESOLVED and c.debate_id is not None
            )
        )
        decision_id = (
            "decision:"
            + _canonical_hash(
                {
                    "run_id": self.run_id,
                    "decision_time": now.isoformat(),
                    "terminal_ids": terminal_ids,
                    "outcome": outcome.value,
                    "selected": selected_id,
                }
            )[:16]
        )
        return DecisionPackage(
            schema_version=DECISION_SCHEMA_VERSION,
            decision_id=decision_id,
            run_id=self.run_id,
            decision_time=now,
            candidate_set=tuple(
                sorted(candidates, key=lambda c: c.final_proposal_id)
            ),
            selected_candidate_id=selected_id,
            rejected_alternatives=tuple(
                sorted(alternatives, key=lambda a: a.final_proposal_id)
            ),
            outcome=outcome,
            decision_reasons=decision_reasons,
            evidence_refs=evidence_refs,
            counter_evidence_refs=counter_refs,
            unresolved_conflicts=unresolved,
            events=tuple(events),
            trace=None,
            verification_metadata=VerificationMetadata(
                artifact_id=decision_id,
                builder_agent_id=DECISION_ENGINE_ID,
                verifier_agent_id=DECISION_VERIFIER_ID,
                independent_verification_required=True,
            ),
        )

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _lineage_members(resolution: LineageResolution, root: str) -> tuple[str, ...]:
        members = [pid for pid, lineage in resolution.lineage_of.items() if lineage == root]
        return tuple(sorted(members)) or (root,)

    def _eligibility(
        self,
        final_proposal: TradeProposal,
        *,
        resolution: LineageResolution,
        root: str,
        facts: DebateFacts,
        evidence_registry: Mapping[str, Any],
        now: datetime,
        conflicted_ids: set[str],
    ) -> tuple[DecisionEligibility, tuple[DecisionReason, ...]]:
        if root in resolution.invalid_roots:
            return (
                DecisionEligibility.INELIGIBLE_INVALID_REVISION_LINEAGE,
                (DecisionReason.INVALID_REVISION_LINEAGE,),
            )
        # Temporal gates (single authority: ``now`` is the injected run clock).
        # Staleness (data recency) is checked before expiry (validity window).
        if final_proposal.data_time > now:
            return (
                DecisionEligibility.INELIGIBLE_FUTURE_DATED,
                (DecisionReason.FUTURE_DATED,),
            )
        if now - final_proposal.data_time > PROPOSAL_STALE_AFTER:
            return (DecisionEligibility.INELIGIBLE_STALE, (DecisionReason.STALE,))
        if final_proposal.expires_at is not None and now >= final_proposal.expires_at:
            return (DecisionEligibility.INELIGIBLE_EXPIRED, (DecisionReason.EXPIRED,))
        # Trace gate.
        if final_proposal.trace is not None and final_proposal.trace.run_id != self.run_id:
            return (DecisionEligibility.INELIGIBLE_INVALID_TRACE, (DecisionReason.INVALID_TRACE,))
        # Evidence binding gate.
        for ref in final_proposal.evidence_refs:
            evidence = evidence_registry.get(ref)
            if evidence is None:
                return (
                    DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE,
                    (DecisionReason.INVALID_EVIDENCE,),
                )
            # DEF-MA4-002: run authority is a first-class evidence boundary —
            # a forged matching trace_id never grants run authority.
            if getattr(evidence, "run_id", None) != self.run_id:
                return (
                    DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE,
                    (DecisionReason.INVALID_EVIDENCE,),
                )
            if getattr(evidence, "available_at", now) > now:
                return (
                    DecisionEligibility.INELIGIBLE_FUTURE_DATED,
                    (DecisionReason.FUTURE_DATED,),
                )
            trace = getattr(evidence, "trace", None)
            if trace is not None and trace.trace_id != final_proposal.trace_id:
                return (
                    DecisionEligibility.INELIGIBLE_INVALID_EVIDENCE,
                    (DecisionReason.INVALID_EVIDENCE,),
                )
        # Evidence completeness gate.
        if not final_proposal.evidence_refs:
            return (
                DecisionEligibility.INELIGIBLE_INSUFFICIENT_EVIDENCE,
                (DecisionReason.INSUFFICIENT_EVIDENCE,),
            )
        if facts.outcome is DebateOutcome.INSUFFICIENT_EVIDENCE:
            return (
                DecisionEligibility.INELIGIBLE_INSUFFICIENT_EVIDENCE,
                (DecisionReason.INSUFFICIENT_EVIDENCE,),
            )
        # Conservative unresolved-conflict gate (MA-4C/MA-4S).
        if facts.outcome is DebateOutcome.UNRESOLVED:
            return (
                DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT,
                (DecisionReason.UNRESOLVED_CONFLICT,),
            )
        lineage_conflicted = any(pid in conflicted_ids for pid in self._lineage_members(resolution, root))
        if lineage_conflicted and facts.outcome is None:
            # A directional conflict exists on the board but no debate ever
            # covered this lineage: fail closed rather than pick a side.
            return (
                DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT,
                (DecisionReason.UNRESOLVED_CONFLICT,),
            )
        return (DecisionEligibility.ELIGIBLE, ())

    @staticmethod
    def _rejected_alternatives(
        candidates: list[DecisionCandidate],
        selected_id: str | None,
        selection_reasons: tuple[DecisionReason, ...],
    ) -> list[RejectedAlternative]:
        alternatives: list[RejectedAlternative] = []
        for candidate in candidates:
            if selected_id is not None and candidate.final_proposal_id == selected_id:
                continue
            if candidate.eligibility is DecisionEligibility.ELIGIBLE:
                reasons: tuple[DecisionReason, ...] = (
                    DecisionReason.LOWER_RANKED_ALTERNATIVE,
                )
                summary = "eligible but outranked by the highest admissible score"
            else:
                reasons = candidate.rejection_reasons
                summary = ""
            alternatives.append(
                RejectedAlternative(
                    proposal_id=candidate.proposal_id,
                    final_proposal_id=candidate.final_proposal_id,
                    rejection_reasons=reasons or selection_reasons,
                    meta_score=candidate.meta_score,
                    decision_score=candidate.decision_score,
                    summary=summary,
                )
            )
        return alternatives

    @staticmethod
    def _no_trade_reasons(candidates: list[DecisionCandidate]) -> tuple[DecisionReason, ...]:
        if not candidates:
            return (DecisionReason.NO_VALID_CANDIDATES,)
        reasons: set[DecisionReason] = set()
        for candidate in candidates:
            reasons.update(candidate.rejection_reasons)
        return tuple(sorted(reasons, key=lambda item: item.value))


# ---------------------------------------------------------------------------
# MA-4P — independent deterministic verifier (builder != verifier)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionVerification:
    """Immutable result of an independent DecisionPackage verification."""

    package_id: str
    verdict: DecisionVerificationStatus
    checks: tuple[tuple[str, str, str], ...]  # (check, PASS/FAIL, detail)

    @property
    def passed(self) -> bool:
        return self.verdict is DecisionVerificationStatus.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "verdict": self.verdict.value,
            "checks": [[name, status, detail] for name, status, detail in self.checks],
        }


class DecisionPackageVerifier:
    """Independent deterministic verification of a DecisionPackage.

    This is NOT RiskManager: it checks internal decision consistency only.
    The builder of a package can never be its verifier (enforced via
    ``VerificationMetadata`` and by this class being stateless/separate).

    Evidence authority for the selected candidate originates from the
    canonical terminal ``TradeProposal`` — the package's own evidence lists
    are never trusted as their own source of truth (CP-MA-004.2).
    """

    version = "decision-package-verifier-v2"

    def __init__(self) -> None:
        self._resolver = TerminalProposalResolver()

    def verify(
        self,
        package: DecisionPackage,
        *,
        proposals: Mapping[str, TradeProposal],
        evidence_registry: Mapping[str, Any],
        now: datetime,
        reports: Sequence[DebateReport] = (),
    ) -> DecisionVerification:
        checks: list[tuple[str, str, str]] = []

        def record(name: str, ok: bool, detail: str = "") -> None:
            checks.append((name, "PASS" if ok else "FAIL", detail))

        meta = package.verification_metadata
        record(
            "builder_verifier_separation",
            meta.builder_agent_id != meta.verifier_agent_id,
            f"builder={meta.builder_agent_id} verifier={meta.verifier_agent_id}",
        )

        selected = package.selected_candidate_id
        record(
            "outcome_consistency",
            (package.outcome is DecisionOutcome.SELECTED) == (selected is not None),
            f"outcome={package.outcome.value} selected={selected}",
        )
        selected_candidate = next(
            (c for c in package.candidate_set if c.final_proposal_id == selected), None
        )
        record(
            "selected_exists_and_eligible",
            selected_candidate is not None
            and selected_candidate.eligibility is DecisionEligibility.ELIGIBLE,
            f"selected={selected}",
        )
        if selected_candidate is not None:
            proposal = proposals.get(selected_candidate.final_proposal_id)
            temporal_ok = proposal is not None and (
                (proposal.expires_at is None or now < proposal.expires_at)
                and proposal.data_time <= now
            )
            record(
                "no_stale_or_expired_selection",
                temporal_ok,
                f"final={selected_candidate.final_proposal_id}",
            )

        non_selected = {
            c.final_proposal_id
            for c in package.candidate_set
            if c.final_proposal_id != selected
        }
        rejected_ids = {a.final_proposal_id for a in package.rejected_alternatives}
        record(
            "rejected_alternatives_accounted",
            non_selected == rejected_ids,
            f"missing={sorted(non_selected - rejected_ids)} extra={sorted(rejected_ids - non_selected)}",
        )

        reasons_ok = bool(package.decision_reasons) and all(
            isinstance(reason, DecisionReason) for reason in package.decision_reasons
        )
        if package.outcome is DecisionOutcome.SELECTED:
            reasons_ok = reasons_ok and DecisionReason.HIGHEST_ADMISSIBLE_SCORE in (
                package.decision_reasons
            )
        record("decision_reasons_valid", reasons_ok, str([r.value for r in package.decision_reasons]))

        trace_ok = package.trace is None or (
            package.trace.run_id == package.run_id
        )
        record("trace_complete", trace_ok, f"run_id={package.run_id}")

        unresolved_selected = selected_candidate is not None and (
            selected_candidate.eligibility is DecisionEligibility.INELIGIBLE_UNRESOLVED_CONFLICT
        )
        record("no_unresolved_blocking_conflict_selected", not unresolved_selected)

        # Score decomposition + anti-double-counting.
        score_ok = True
        detail = ""
        if selected_candidate is not None:
            breakdown = selected_candidate.score_breakdown
            meta_component = breakdown.component("meta_ranker_score")
            counter_component = breakdown.component("counter_evidence_materiality")
            names = [name for name, _, _ in breakdown.components]
            sources = {
                name: source
                for name, _, source in breakdown.components
            }
            recomputed = round(
                max(0.0, min(1.0, (meta_component or 0.0) - (counter_component or 0.0))), 6
            )
            provenance_ok = sources.get("meta_ranker_score") == ScoreComponentSource.META_RANKER.value and (
                "counter_evidence_materiality" not in sources
                or sources["counter_evidence_materiality"] == ScoreComponentSource.DEBATE.value
            )
            score_ok = (
                len(names) == len(set(names))
                and meta_component is not None
                and recomputed == breakdown.final_score
                and selected_candidate.decision_score == breakdown.final_score
                and provenance_ok
            )
            detail = f"final={breakdown.final_score} recomputed={recomputed}"
        record("score_decomposition_valid", score_ok, detail)

        double_count_ok = True
        detail = ""
        if selected_candidate is not None:
            meta_component = selected_candidate.score_breakdown.component("meta_ranker_score")
            double_count_ok = meta_component is not None and (
                abs(meta_component - selected_candidate.meta_score) < 1e-9
            )
            detail = f"meta_component={meta_component} meta_score={selected_candidate.meta_score}"
        record("no_score_component_double_counting", double_count_ok, detail)

        evidence_ok = all(
            ref in evidence_registry
            for candidate in package.candidate_set
            for ref in (*candidate.supporting_evidence_refs, *candidate.counter_evidence_refs)
            if candidate.final_proposal_id == selected
        )
        record("material_evidence_resolvable", evidence_ok)

        # -- Cross-run authority (CP-MA-004.1 / ADR-MA-0006) ------------------
        # Independent authority audit: every consumed artifact must belong to
        # the package run. trace_id equality never overrides run mismatch.
        foreign_proposals = sorted(
            pid
            for pid in {c.final_proposal_id for c in package.candidate_set}
            if pid in proposals and proposals[pid].run_id != package.run_id
        )
        record(
            "run_authority_proposals",
            not foreign_proposals,
            f"foreign={foreign_proposals}",
        )

        foreign_evidence: list[str] = []
        if selected_candidate is not None:
            foreign_evidence = sorted(
                ref
                for ref in selected_candidate.supporting_evidence_refs
                if ref in evidence_registry
                and getattr(evidence_registry[ref], "run_id", None) != package.run_id
            )
        record(
            "run_authority_evidence",
            not foreign_evidence,
            f"foreign={foreign_evidence}",
        )

        report_by_id = {report.debate_id: report for report in reports}
        foreign_reports = sorted(
            debate_id
            for debate_id in {c.debate_id for c in package.candidate_set if c.debate_id}
            if debate_id in report_by_id and report_by_id[debate_id].run_id != package.run_id
        )
        record(
            "run_authority_debate_reports",
            not foreign_reports,
            f"foreign={foreign_reports}",
        )
        # Registry-side report authority: a report not referenced by any
        # candidate (or fed under a forged debate_id) still must not belong
        # to another run — closure covers the candidate-referenced subset.
        record(
            "run_authority_reports_registry",
            all(report.run_id == package.run_id for report in reports),
            f"checked={len(reports)}",
        )

        # -- CP-MA-004.2: selected evidence authority binding -----------------
        # Evidence authority originates from the canonical terminal
        # TradeProposal, NOT from the package's own lists (a stripped list
        # would otherwise pass resolvability vacuously). Canonical comparison
        # is by evidence identity SET — input ordering carries no semantics.
        # Policy: SELECTED_AUTHORITY_CRITICAL (exact binding), rejected
        # candidates REJECTED_AUDIT_ONLY (registered subset, no exact set).
        binding_ok = False
        binding_detail = "selected candidate missing"
        if selected_candidate is not None:
            final = proposals.get(selected_candidate.final_proposal_id)
            if final is None:
                binding_ok, binding_detail = False, "terminal proposal missing from registry"
            else:
                proposal_authority = frozenset(final.evidence_refs)
                candidate_refs = frozenset(selected_candidate.supporting_evidence_refs)
                duplicates = len(selected_candidate.supporting_evidence_refs) != len(
                    candidate_refs
                )
                unknown = sorted(candidate_refs - set(evidence_registry))
                foreign = sorted(
                    ref
                    for ref in candidate_refs
                    if ref in evidence_registry
                    and getattr(evidence_registry[ref], "run_id", None) != package.run_id
                )
                foreign_trace = sorted(
                    ref
                    for ref in candidate_refs
                    if ref in evidence_registry
                    and getattr(evidence_registry[ref], "trace", None) is not None
                    and evidence_registry[ref].trace.trace_id != final.trace_id
                )
                binding_ok = (
                    bool(proposal_authority)
                    and bool(candidate_refs)
                    and not duplicates
                    and candidate_refs == proposal_authority
                    and not unknown
                    and not foreign
                    and not foreign_trace
                )
                binding_detail = (
                    f"proposal={sorted(proposal_authority)} candidate={sorted(candidate_refs)} "
                    f"unknown={unknown} foreign_run={foreign} foreign_trace={foreign_trace}"
                )
        record("selected_evidence_binding", binding_ok, binding_detail)

        # REJECTED_AUDIT_ONLY: every candidate-declared ref must at least
        # resolve to registered, current-run evidence (no exact set equality).
        rejected_audit_bad: list[str] = []
        for candidate in package.candidate_set:
            if candidate.final_proposal_id == selected:
                continue
            for ref in (
                *candidate.supporting_evidence_refs,
                *candidate.counter_evidence_refs,
            ):
                evidence = evidence_registry.get(ref)
                if evidence is None or getattr(evidence, "run_id", None) != package.run_id:
                    rejected_audit_bad.append(ref)
        record(
            "rejected_candidates_evidence_audit",
            not rejected_audit_bad,
            f"violations={sorted(set(rejected_audit_bad))}",
        )

        # -- CP-MA-004.2: final proposal identity binding ----------------------
        # Independently re-resolve lineages: the package must point at the
        # canonical terminal proposal, never at an ancestor carrying later
        # evidence.
        lineage_ok = False
        lineage_detail = ""
        try:
            resolution = self._resolver.resolve(reports, proposals)
            lineage_ok = True
            for candidate in package.candidate_set:
                root = candidate.proposal_id
                expected = resolution.terminal_by_root.get(root, root)
                if root in resolution.invalid_roots or candidate.final_proposal_id != expected:
                    lineage_ok = False
                    lineage_detail = f"candidate {root}: final={candidate.final_proposal_id} terminal={expected}"
                    break
            if lineage_ok:
                lineage_detail = f"roots={len(resolution.terminal_by_root)} all terminal-bound"
        except DecisionError as exc:
            lineage_ok = False
            lineage_detail = f"lineage resolution failed: {exc}"
        record("final_proposal_binding", lineage_ok, lineage_detail)

        verdict = (
            DecisionVerificationStatus.VERIFIED
            if all(status == "PASS" for _, status, _ in checks)
            else DecisionVerificationStatus.REJECTED
        )
        return DecisionVerification(
            package_id=package.decision_id,
            verdict=verdict,
            checks=tuple(checks),
        )


__all__ = [
    "DECISION_ENGINE_ID",
    "DECISION_SCHEMA_VERSION",
    "DECISION_VERIFIER_ID",
    "PROPOSAL_STALE_AFTER",
    "DebateFacts",
    "DecisionEngine",
    "DecisionError",
    "DecisionPackageVerifier",
    "DecisionVerification",
    "DecisionVerificationStatus",
    "LineageResolution",
    "TerminalProposalResolver",
]
