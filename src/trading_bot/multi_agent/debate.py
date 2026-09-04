"""Deterministic structured debate for MA-3.

Bounded, evidence-driven debate over the certified MA-1 substrate
(``AgentBus``/``Blackboard`` contracts). MA-3 does NOT select the final
opportunity (MA-4) and never touches execution: critics hold READ/WRITE only
and every decision time derives from the injected run clock via
``AgentBus.now()`` (MA-2 temporal contract).

Artifact flow (all immutable, all on the certified bus):

    OpportunityBoard snapshot / ConflictCase
        → DebateRouter (NO_DEBATE | DEBATE_REQUIRED)
        → critics (EvidenceCritic, RegimeCritic, CounterSignalCritic)
        → CRITIQUE AgentMessage + CritiqueRecord (+ audit evidence)
        → EVIDENCE_REQUEST / EVIDENCE_RESPONSE (owner supplies or ABSTAINs)
        → revised canonical TradeProposal + ProposalRevision (optional)
        → DebateReport (RESOLVED | UNRESOLVED | INSUFFICIENT_EVIDENCE |
                        NO_NEW_EVIDENCE | MAX_ROUNDS | TIMEOUT | FAILED)
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Final

from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.communication_errors import CommunicationError
from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentEvidence,
    AgentLifecycleState,
    AgentManifest,
    AgentMessage,
    AgentMessageType,
    AgentRole,
    CritiqueRecord,
    CritiqueStance,
    DebateEventType,
    DebateOutcome,
    DebatePosition,
    DebateReport,
    DebateRouterDecision,
    DebateRouteReason,
    DebateTerminationReason,
    EvidenceItem,
    ForbiddenAction,
    ProposalRevision,
    RequestedAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.opportunity import OpportunitySnapshot
from trading_bot.multi_agent.registry import (
    AgentRegistry,
    CapabilityPolicy,
    CapabilityRegistry,
)
from trading_bot.multi_agent.specialists import PROPOSAL_VALIDITY

DEBATE_SCHEMA_VERSION = "ma-3-v1"
DEBATE_CRITIC_VERSION = "1.0.0"
MAX_DEBATE_ROUNDS: Final[int] = 3
EVIDENCE_STALE_AFTER: Final[timedelta] = timedelta(hours=24)
REVISION_SUFFIX_LENGTH: Final[int] = 8

RevisionFactory = Callable[[TradeProposal, CritiqueRecord, datetime], TradeProposal | None]


class DebateStatus(StrEnum):
    """Live session status, mirroring MA-1 session semantics."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    MAX_ROUNDS = "MAX_ROUNDS"


class DebateError(ValueError):
    """Raised when a debate cannot be orchestrated fail-closed."""


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()


def _canonical_json(payload: Mapping[str, str]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# MA-3A — DebateRouter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DebateRoute:
    """Deterministic router verdict for one proposal set."""

    decision: DebateRouterDecision
    reasons: tuple[DebateRouteReason, ...]
    debated_proposal_ids: tuple[str, ...]
    non_debated_proposal_ids: tuple[str, ...]


class DebateRouter:
    """Closed-set, LLM-free routing: debate only when material reasons exist.

    A clean, uncontested, well-evidenced, regime-coherent proposal stays
    ``NO_DEBATE`` (fast path preserved).
    """

    version = "debate-router-v1"

    def route(
        self,
        snapshot: OpportunitySnapshot,
        *,
        positions: Mapping[str, DebatePosition],
        regime_by_asset: Mapping[str, str] | None = None,
        evidence_registry: Mapping[str, AgentEvidence] | None = None,
    ) -> DebateRoute:
        debated: list[str] = []
        reasons: set[DebateRouteReason] = set()

        conflicting = {
            proposal_id
            for conflict in snapshot.conflicts
            for proposal_id in conflict.proposal_ids
        }
        if conflicting:
            debated.extend(sorted(conflicting))
            reasons.add(DebateRouteReason.DIRECTIONAL_CONFLICT)
            reasons.add(DebateRouteReason.MATERIAL_COUNTER_SIGNAL)

        registry = evidence_registry or {}
        regimes = regime_by_asset or {}
        for proposal_id in sorted(positions):
            position = positions[proposal_id]
            if proposal_id in conflicting:
                continue
            if any(ref not in registry for ref in position.evidence_refs):
                debated.append(proposal_id)
                reasons.add(DebateRouteReason.EVIDENCE_INSUFFICIENCY)
            canonical_regime = regimes.get(position.asset)
            if canonical_regime is not None and self._regime_inconsistent(
                position, canonical_regime
            ):
                debated.append(proposal_id)
                reasons.add(DebateRouteReason.REGIME_INCONSISTENCY)

        debated_ids = tuple(sorted(set(debated)))
        all_ids = tuple(sorted(positions))
        non_debated = tuple(pid for pid in all_ids if pid not in set(debated_ids))
        decision = (
            DebateRouterDecision.DEBATE_REQUIRED if debated_ids else DebateRouterDecision.NO_DEBATE
        )
        return DebateRoute(
            decision=decision,
            reasons=tuple(sorted(reasons, key=lambda item: item.value)),
            debated_proposal_ids=debated_ids,
            non_debated_proposal_ids=non_debated,
        )

    @staticmethod
    def _regime_inconsistent(position: DebatePosition, canonical_regime: str) -> bool:
        if position.direction is TradeDirection.NO_TRADE:
            return False
        if canonical_regime == "UNKNOWN":
            return False
        if position.strategy in {"momentum", "trend", "breakout"}:
            coherent = {
                "TREND_UP": TradeDirection.LONG,
                "TREND_DOWN": TradeDirection.SHORT,
            }.get(canonical_regime)
            return coherent is not None and position.direction is not coherent
        return False


# ---------------------------------------------------------------------------
# Debate read model shared by critics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DebateContext:
    """Immutable per-round read model handed to every critic."""

    positions: tuple[DebatePosition, ...]
    evidence: Mapping[str, AgentEvidence]
    regime_by_asset: Mapping[str, str]
    clock: datetime
    revision_chain: Mapping[str, str] = field(default_factory=dict)  # revised -> original

    def lineage_of(self, proposal_id: str) -> frozenset[str]:
        """Return the proposal id plus all its revision ancestors."""
        chain = {proposal_id}
        cursor = proposal_id
        while cursor in self.revision_chain:
            cursor = self.revision_chain[cursor]
            chain.add(cursor)
        return frozenset(chain)


# ---------------------------------------------------------------------------
# MA-3B — Critic agents (orthogonal, deterministic)
# ---------------------------------------------------------------------------


class BaseCritic:
    """Shared critic manifest construction; READ/WRITE only, execution denied."""

    agent_id: str
    description: str

    def __init__(self) -> None:
        self._manifest = AgentManifest(
            schema_version=DEBATE_SCHEMA_VERSION,
            agent_id=self.agent_id,
            agent_version=DEBATE_CRITIC_VERSION,
            role=AgentRole.CRITIC,
            description=self.description,
            capabilities=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            input_contracts=("TradeProposal", "AgentEvidence"),
            output_contracts=("CritiqueRecord",),
            allowed_tools=(),
            forbidden_actions=frozenset(ForbiddenAction),
            lifecycle_state=AgentLifecycleState.ENABLED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    def critique(
        self, position: DebatePosition, context: DebateContext, trace: TraceContext
    ) -> CritiqueRecord:
        """Produce this critic's verdict for one position."""
        raise NotImplementedError

    def _record(
        self,
        *,
        position: DebatePosition,
        stance: CritiqueStance,
        materiality: float,
        claim: str,
        evidence_refs: Sequence[str],
        counter_evidence_refs: Sequence[str],
        requested_action: RequestedAction,
        clock: datetime,
        trace: TraceContext,
    ) -> CritiqueRecord:
        refs = tuple(sorted(set(evidence_refs)))
        counter = tuple(sorted(set(counter_evidence_refs)))
        critique_id = "critique:" + _canonical_hash(
            {
                "critic": self.agent_id,
                "proposal_id": position.proposal_id,
                "stance": stance.value,
                "claim": claim,
                "evidence_refs": refs,
                "counter_evidence_refs": counter,
                "requested_action": requested_action.value,
            }
        )[:24]
        return CritiqueRecord(
            schema_version=DEBATE_SCHEMA_VERSION,
            critique_id=critique_id,
            proposal_id=position.proposal_id,
            critic_agent_id=self.agent_id,
            critic_version=DEBATE_CRITIC_VERSION,
            stance=stance,
            materiality=round(materiality, 6),
            claim=claim,
            evidence_refs=refs,
            counter_evidence_refs=counter,
            confidence=1.0,
            requested_action=requested_action,
            trace=trace,
            created_at=clock,
        )


class EvidenceCritic(BaseCritic):
    """Evidence presence, validity, PIT-freshness and claim support."""

    agent_id = "critic-evidence"
    description = "Deterministic evidence integrity critic (MA-3)."

    def critique(
        self, position: DebatePosition, context: DebateContext, trace: TraceContext
    ) -> CritiqueRecord:
        refs = position.evidence_refs
        if not refs:
            return self._record(
                position=position,
                stance=CritiqueStance.ABSTAIN,
                materiality=0.0,
                claim="no evidence bound to position; nothing to evaluate",
                evidence_refs=(),
                counter_evidence_refs=(),
                requested_action=RequestedAction.NONE,
                clock=context.clock,
                trace=trace,
            )
        missing = [ref for ref in refs if ref not in context.evidence]
        if missing:
            return self._record(
                position=position,
                stance=CritiqueStance.CHALLENGE,
                materiality=0.9,
                claim=f"missing evidence references: {sorted(missing)}",
                evidence_refs=refs,
                counter_evidence_refs=(),
                requested_action=RequestedAction.PROVIDE_EVIDENCE,
                clock=context.clock,
                trace=trace,
            )
        unavailable = [
            ref for ref in refs if not context.evidence[ref].is_valid_at(context.clock)
        ]
        if unavailable:
            return self._record(
                position=position,
                stance=CritiqueStance.CHALLENGE,
                materiality=0.9,
                claim=f"evidence not available at decision time: {sorted(unavailable)}",
                evidence_refs=refs,
                counter_evidence_refs=(),
                requested_action=RequestedAction.PROVIDE_EVIDENCE,
                clock=context.clock,
                trace=trace,
            )
        stale = [
            ref
            for ref in refs
            if context.clock - context.evidence[ref].observed_at > EVIDENCE_STALE_AFTER
        ]
        if stale:
            return self._record(
                position=position,
                stance=CritiqueStance.CHALLENGE,
                materiality=0.5,
                claim=f"stale evidence (older than {EVIDENCE_STALE_AFTER}): {sorted(stale)}",
                evidence_refs=refs,
                counter_evidence_refs=(),
                requested_action=RequestedAction.PROVIDE_EVIDENCE,
                clock=context.clock,
                trace=trace,
            )
        supported = any(
            context.lineage_of(position.proposal_id)
            & set(context.evidence[ref].claim_refs)
            for ref in refs
        )
        if not supported:
            return self._record(
                position=position,
                stance=CritiqueStance.CHALLENGE,
                materiality=0.6,
                claim="bound evidence does not reference this proposal claim",
                evidence_refs=refs,
                counter_evidence_refs=(),
                requested_action=RequestedAction.REVISE,
                clock=context.clock,
                trace=trace,
            )
        lineage = context.lineage_of(position.proposal_id)
        contradictory = tuple(
            sorted(
                item.evidence_id
                for item in context.evidence.values()
                if lineage & set(item.claim_refs) and item.evidence_id not in refs
            )
        )
        if contradictory:
            return self._record(
                position=position,
                stance=CritiqueStance.CHALLENGE,
                materiality=0.7,
                claim="contradictory evidence surfaced for this claim",
                evidence_refs=refs,
                counter_evidence_refs=contradictory,
                requested_action=RequestedAction.NONE,
                clock=context.clock,
                trace=trace,
            )
        return self._record(
            position=position,
            stance=CritiqueStance.SUPPORT,
            materiality=0.2,
            claim="evidence present, PIT-valid, fresh and claim-supported",
            evidence_refs=refs,
            counter_evidence_refs=(),
            requested_action=RequestedAction.NONE,
            clock=context.clock,
            trace=trace,
        )


class RegimeCritic(BaseCritic):
    """Coherence of strategy/direction with the canonical regime context.

    Does NOT replace the deterministic regime engine; only checks alignment.
    """

    agent_id = "critic-regime"
    description = "Deterministic regime-coherence critic (MA-3)."

    def critique(
        self, position: DebatePosition, context: DebateContext, trace: TraceContext
    ) -> CritiqueRecord:
        regime = context.regime_by_asset.get(position.asset)
        if regime is None or regime == "UNKNOWN":
            return self._record(
                position=position,
                stance=CritiqueStance.ABSTAIN,
                materiality=0.0,
                claim="no canonical regime available for asset",
                evidence_refs=position.evidence_refs,
                counter_evidence_refs=(),
                requested_action=RequestedAction.NONE,
                clock=context.clock,
                trace=trace,
            )
        if position.strategy in {"momentum", "trend", "breakout"} and position.direction in (
            TradeDirection.LONG,
            TradeDirection.SHORT,
        ):
            coherent = {
                "TREND_UP": TradeDirection.LONG,
                "TREND_DOWN": TradeDirection.SHORT,
            }.get(regime)
            if coherent is not None and position.direction is not coherent:
                return self._record(
                    position=position,
                    stance=CritiqueStance.CHALLENGE,
                    materiality=0.7,
                    claim=(
                        f"direction {position.direction.value} inconsistent with "
                        f"canonical regime {regime}"
                    ),
                    evidence_refs=position.evidence_refs,
                    counter_evidence_refs=(),
                    requested_action=RequestedAction.REVISE,
                    clock=context.clock,
                    trace=trace,
                )
        return self._record(
            position=position,
            stance=CritiqueStance.SUPPORT,
            materiality=0.1,
            claim=f"strategy/direction coherent with canonical regime {regime}",
            evidence_refs=position.evidence_refs,
            counter_evidence_refs=(),
            requested_action=RequestedAction.NONE,
            clock=context.clock,
            trace=trace,
        )


class CounterSignalCritic(BaseCritic):
    """Adversarial search for opposing proposals inside the MA-2 set.

    Surfaces counter-signals; never rejects a proposal by itself.
    """

    agent_id = "critic-counter-signal"
    description = "Deterministic counter-signal critic (MA-3)."

    def critique(
        self, position: DebatePosition, context: DebateContext, trace: TraceContext
    ) -> CritiqueRecord:
        others = [
            item
            for item in context.positions
            if item.proposal_id != position.proposal_id and item.asset == position.asset
        ]
        opposing = sorted(
            (
                item
                for item in others
                if item.direction is not position.direction
                and item.direction is not TradeDirection.NO_TRADE
                and position.direction is not TradeDirection.NO_TRADE
            ),
            key=lambda item: item.proposal_id,
        )
        if opposing:
            counter_refs = tuple(
                sorted(ref for item in opposing for ref in item.evidence_refs)
            )
            return self._record(
                position=position,
                stance=CritiqueStance.CHALLENGE,
                materiality=0.8,
                claim="opposing proposals surfaced: "
                + ",".join(item.proposal_id for item in opposing),
                evidence_refs=position.evidence_refs,
                counter_evidence_refs=counter_refs,
                requested_action=(
                    RequestedAction.NONE if counter_refs else RequestedAction.PROVIDE_EVIDENCE
                ),
                clock=context.clock,
                trace=trace,
            )
        corroborating = sorted(
            (item for item in others if item.direction is position.direction),
            key=lambda item: item.proposal_id,
        )
        if corroborating:
            return self._record(
                position=position,
                stance=CritiqueStance.SUPPORT,
                materiality=0.3,
                claim="no counter-signal; corroborating same-direction proposals exist",
                evidence_refs=tuple(
                    sorted(
                        (
                            *position.evidence_refs,
                            *(ref for item in corroborating for ref in item.evidence_refs),
                        )
                    )
                ),
                counter_evidence_refs=(),
                requested_action=RequestedAction.NONE,
                clock=context.clock,
                trace=trace,
            )
        return self._record(
            position=position,
            stance=CritiqueStance.SUPPORT,
            materiality=0.2,
            claim="no counter-signal present in proposal set",
            evidence_refs=position.evidence_refs,
            counter_evidence_refs=(),
            requested_action=RequestedAction.NONE,
            clock=context.clock,
            trace=trace,
        )


CRITIC_FACTORIES: Final[dict[str, type[BaseCritic]]] = {
    "evidence": EvidenceCritic,
    "regime": RegimeCritic,
    "counter_signal": CounterSignalCritic,
}


def register_debate_agents(
    agent_registry: AgentRegistry,
    capability_registry: CapabilityRegistry,
) -> tuple[AgentManifest, ...]:
    """Register the three MA-3 critics (idempotent, fail-closed)."""
    manifests = [factory().manifest for factory in CRITIC_FACTORIES.values()]
    for manifest in manifests:
        try:
            existing = agent_registry.get(manifest.agent_id, manifest.agent_version)
        except ValueError:
            agent_registry.register(manifest)
            existing = manifest
        if existing != manifest:
            raise DebateError(f"conflicting MA-3 critic manifest: {manifest.agent_id}")
        capability_registry.register_agent(existing)
        capability_registry.register_policy(
            CapabilityPolicy(
                agent_id=existing.agent_id,
                agent_version=existing.agent_version,
                grants=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            )
        )
    return tuple(manifests)


# ---------------------------------------------------------------------------
# MA-3H — evidence deduplication ledger
# ---------------------------------------------------------------------------


class DebateLedger:
    """Canonicalized evidence accounting: identity, not repetition.

    Five agents referencing the same evidence item count as ONE unique item;
    attribution (who referenced it) is preserved separately.
    """

    def __init__(self) -> None:
        self._items: dict[str, EvidenceItem] = {}
        self._alias: dict[tuple[str, str], str] = {}

    def canonical_id(self, evidence: AgentEvidence) -> str:
        return self._alias.get((evidence.source_ref, evidence.content_hash), evidence.evidence_id)

    def add(self, evidence: AgentEvidence, referrer: str) -> EvidenceItem:
        canonical_id = self.canonical_id(evidence)
        existing = self._items.get(canonical_id)
        if existing is None:
            item = EvidenceItem.from_agent_evidence(evidence, referrer)
            if canonical_id != evidence.evidence_id:
                item = item.model_copy(update={"evidence_id": canonical_id})
            self._items[canonical_id] = item
        else:
            self._items[canonical_id] = existing.merged(referrer)
        self._alias.setdefault((evidence.source_ref, evidence.content_hash), canonical_id)
        return self._items[canonical_id]

    def unique_count(self) -> int:
        return len(self._items)

    def attribution(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(
            (evidence_id, item.referenced_by) for evidence_id, item in sorted(self._items.items())
        )

    def items(self) -> tuple[EvidenceItem, ...]:
        return tuple(self._items[key] for key in sorted(self._items))


# ---------------------------------------------------------------------------
# MA-3F — DebateSession (bounded, over the certified MA-1 bus)
# ---------------------------------------------------------------------------


class DebateSession:
    """Bounded debate orchestration without a second communication runtime."""

    def __init__(
        self,
        *,
        debate_id: str,
        bus: AgentBus,
        positions: Sequence[DebatePosition],
        proposals: Mapping[str, TradeProposal] | None = None,
        regime_by_asset: Mapping[str, str] | None = None,
        evidence_registry: Mapping[str, AgentEvidence] | None = None,
        max_rounds: int = MAX_DEBATE_ROUNDS,
        timeout: timedelta | None = None,
        critics: Sequence[BaseCritic] | None = None,
        revision_factory: RevisionFactory | None = None,
    ) -> None:
        if not debate_id:
            raise DebateError("debate_id is required")
        if max_rounds < 1:
            raise DebateError("max_rounds must be positive")
        if not positions:
            raise DebateError("debate requires at least one position")
        proposals_by_id = dict(proposals or {})
        for position in positions:
            if position.proposal_id in proposals_by_id:
                proposal = proposals_by_id[position.proposal_id]
                if proposal.run_id != bus.blackboard.run_id:
                    raise DebateError("proposal run does not match bus run")
        if critics is not None and not critics:
            raise DebateError("debate requires at least one critic")
        active_critics: tuple[BaseCritic, ...] = tuple(
            critics if critics is not None else (EvidenceCritic(), RegimeCritic(), CounterSignalCritic())
        )
        owner_ids = {position.owner_agent_id for position in positions}
        critic_ids = {critic.agent_id for critic in active_critics}
        if not critic_ids - owner_ids:
            raise DebateError("builder/critic separation violated: proposal owner is the only critic")
        self.debate_id = debate_id
        self.bus = bus
        self.max_rounds = max_rounds
        self.timeout = timeout
        self.critics = active_critics
        self.revision_factory: RevisionFactory = revision_factory or self._default_revision
        self.round = 0
        self.status = DebateStatus.ACTIVE
        self.termination_reason: DebateTerminationReason | None = None
        self.revised_proposals: dict[str, TradeProposal] = {}
        self.revisions: tuple[ProposalRevision, ...] = ()
        self.events: tuple[tuple[str, str], ...] = ()
        self._proposals = proposals_by_id
        self._ledger = DebateLedger()
        self._ref_to_canonical: dict[str, str] = {}
        self._critiques: list[CritiqueRecord] = []
        self._request_ids: list[str] = []
        self._response_ids: list[str] = []
        self._audit_evidence_ids: dict[str, str] = {}
        self._insufficient = False
        self._trace = TraceContext(
            run_id=bus.blackboard.run_id,
            trace_id=bus.blackboard.trace_id,
            correlation_id=debate_id,
            causation_id=debate_id,
        )
        self._positions: tuple[DebatePosition, ...] = tuple(
            sorted(positions, key=lambda item: item.proposal_id)
        )
        self._regime_by_asset = regime_by_asset or {}
        self._evidence_registry = evidence_registry or {}

    # -- public result -----------------------------------------------------

    @property
    def ledger(self) -> DebateLedger:
        return self._ledger

    @property
    def critiques(self) -> tuple[CritiqueRecord, ...]:
        return tuple(self._critiques)

    def build_report(self) -> DebateReport:
        if self.status is DebateStatus.ACTIVE or self.termination_reason is None:
            raise DebateError("debate has not terminated")
        critiques = tuple(self._critiques)
        supporting = tuple(
            sorted(
                {
                    ref
                    for critique in critiques
                    if critique.stance is CritiqueStance.SUPPORT
                    for ref in critique.evidence_refs
                }
            )
        )
        counter = tuple(
            sorted({ref for critique in critiques for ref in critique.counter_evidence_refs})
        )
        standing = any(critique.stance is CritiqueStance.CHALLENGE for critique in critiques)
        if self._insufficient:
            outcome = DebateOutcome.INSUFFICIENT_EVIDENCE
        elif self.revisions:
            outcome = DebateOutcome.REVISED
        elif standing:
            outcome = DebateOutcome.UNRESOLVED
        elif any(critique.stance is CritiqueStance.SUPPORT for critique in critiques):
            outcome = DebateOutcome.SUPPORTED
        else:
            outcome = DebateOutcome.UNRESOLVED
        return DebateReport(
            schema_version=DEBATE_SCHEMA_VERSION,
            debate_id=self.debate_id,
            run_id=self.bus.blackboard.run_id,
            proposal_ids=tuple(item.proposal_id for item in self._positions),
            participants=tuple(
                sorted(
                    {item.owner_agent_id for item in self._positions}
                    | {critic.agent_id for critic in self.critics}
                )
            ),
            initial_claims=tuple(item.claim for item in self._positions),
            critiques=critiques,
            supporting_evidence=supporting,
            counter_evidence=counter,
            unique_supporting_evidence_count=len(
                {self._ref_to_canonical[ref] for ref in supporting if ref in self._ref_to_canonical}
            ),
            unique_counter_evidence_count=len(
                {self._ref_to_canonical[ref] for ref in counter if ref in self._ref_to_canonical}
            ),
            evidence_attribution=self._ledger.attribution(),
            evidence_requests=tuple(self._request_ids),
            evidence_responses=tuple(self._response_ids),
            revisions=self.revisions,
            unresolved_conflicts=tuple(
                critique.critique_id
                for critique in critiques
                if critique.stance is CritiqueStance.CHALLENGE
            ),
            round_count=max(self.round, 1),
            max_rounds=self.max_rounds,
            termination_reason=self.termination_reason,
            outcome=outcome,
            events=self.events,
            trace=self._trace,
            created_at=self.bus.now(),
        )

    # -- orchestration -----------------------------------------------------

    def run(self) -> DebateReport:
        deadline = self.bus.now() + self.timeout if self.timeout is not None else None
        self._record_event(DebateEventType.DEBATE_STARTED, {"debate_id": self.debate_id})
        current: dict[str, DebatePosition] = {
            item.proposal_id: item for item in self._positions
        }
        revised_from: dict[str, str] = {}

        while self.round < self.max_rounds and self.status is DebateStatus.ACTIVE:
            if deadline is not None and self.bus.now() >= deadline:
                self._terminate(DebateTerminationReason.TIMEOUT, DebateStatus.TIMEOUT)
                break
            self.round += 1
            evidence_before = self._ledger.unique_count()
            claims_before = {
                _canonical_hash(critique.claim) for critique in self._critiques
            }
            round_context = DebateContext(
                positions=tuple(current[pid] for pid in sorted(current)),
                evidence=self._evidence_registry,
                regime_by_asset=self._regime_by_asset,
                clock=self.bus.now(),
                revision_chain=dict(revised_from),
            )

            round_critiques: list[CritiqueRecord] = []
            round_responses: list[AgentMessage] = []
            round_revisions = 0
            owner_requested = False
            for proposal_id in sorted(current):
                position = current[proposal_id]
                for critic in self.critics:
                    critique = critic.critique(position, round_context, self._trace)
                    try:
                        self._publish_critique(critique)
                    except CommunicationError as exc:
                        self._fail(f"critique rejected: {type(exc).__name__}: {exc}")
                        break
                    round_critiques.append(critique)
                if self.status is not DebateStatus.ACTIVE:
                    break
            if self.status is not DebateStatus.ACTIVE:
                break
            self._critiques.extend(round_critiques)

            standing_challenges = [
                critique
                for critique in round_critiques
                if critique.stance is CritiqueStance.CHALLENGE
            ]

            # Owner response phase (MA-3D): structured answers via the bus.
            for critique in round_critiques:
                if critique.requested_action is not RequestedAction.PROVIDE_EVIDENCE:
                    continue
                owner_requested = True
                request_id = f"request:{critique.critique_id}"
                self._request_ids.append(request_id)
                self._record_event(
                    DebateEventType.DEBATE_EVIDENCE_REQUESTED,
                    {"critique_id": critique.critique_id},
                )
                try:
                    supplied, response = self._publish_evidence_response(
                        current, critique, request_id
                    )
                except CommunicationError as exc:
                    self._fail(f"evidence response rejected: {type(exc).__name__}: {exc}")
                    break
                round_responses.append(response)
                if not supplied:
                    self._insufficient = True
                    self._record_event(
                        DebateEventType.DEBATE_EVIDENCE_INSUFFICIENT,
                        {"critique_id": critique.critique_id},
                    )
            if self.status is not DebateStatus.ACTIVE:
                break

            # Revision phase (MA-3E): new canonical proposals, immutable lineage.
            # A claim the owner has already answered (in an earlier round or
            # earlier this round) carries no new material information, so it
            # must not trigger another revision cycle (MA-3G anti-loop).
            answered_claims = set(claims_before)
            rev_targets: dict[str, list[CritiqueRecord]] = {}
            for critique in round_critiques:
                if critique.requested_action is not RequestedAction.REVISE:
                    continue
                if _canonical_hash(critique.claim) in answered_claims:
                    continue
                rev_targets.setdefault(critique.proposal_id, []).append(critique)
            for original_id in sorted(rev_targets):
                triggers = rev_targets[original_id]
                rev_position = current.get(original_id)
                original = self._proposals.get(original_id)
                if rev_position is None or original is None:
                    continue
                revised = self.revision_factory(
                    original, triggers[0], self.bus.now()
                )
                if revised is None:
                    continue
                if revised.run_id != self._trace.run_id:
                    self._fail("revision run does not match bus run")
                    break
                revision = ProposalRevision(
                    schema_version=DEBATE_SCHEMA_VERSION,
                    original_proposal_id=original.proposal_id,
                    revised_proposal_id=revised.proposal_id,
                    triggering_critique_ids=tuple(
                        critique.critique_id for critique in triggers
                    ),
                    revision_reason=triggers[0].claim,
                    trace=self._trace,
                    created_at=self.bus.now(),
                )
                try:
                    self._publish_revision(revised, rev_position.owner_agent_id)
                except CommunicationError as exc:
                    self._fail(f"revision rejected: {type(exc).__name__}: {exc}")
                    break
                self.revisions = (*self.revisions, revision)
                self.revised_proposals[revised.proposal_id] = revised
                self._proposals[revised.proposal_id] = revised
                revised_from[revised.proposal_id] = original.proposal_id
                for critique in triggers:
                    answered_claims.add(_canonical_hash(critique.claim))
                current[revised.proposal_id] = DebatePosition(
                    proposal_id=revised.proposal_id,
                    owner_agent_id=rev_position.owner_agent_id,
                    asset=revised.asset,
                    direction=revised.direction,
                    strategy=revised.strategy,
                    claim=f"revised from {original.proposal_id}",
                    evidence_refs=revised.evidence_refs,
                )
                del current[original.proposal_id]
                round_revisions += 1
                self._record_event(
                    DebateEventType.DEBATE_PROPOSAL_REVISED,
                    {
                        "original": revision.original_proposal_id,
                        "revised": revision.revised_proposal_id,
                    },
                )
            if self.status is not DebateStatus.ACTIVE:
                break

            # Termination accounting (MA-3G anti-loop, fail-closed ordering).
            if owner_requested and self._insufficient:
                self._terminate(
                    DebateTerminationReason.INSUFFICIENT_EVIDENCE, DebateStatus.COMPLETED
                )
                break
            new_evidence = self._ledger.unique_count() - evidence_before
            new_claims = {
                _canonical_hash(critique.claim) for critique in round_critiques
            } - claims_before
            material_round = bool(new_evidence or new_claims or round_revisions)
            if not standing_challenges:
                self._terminate(DebateTerminationReason.RESOLVED, DebateStatus.COMPLETED)
                break
            if self.round >= self.max_rounds:
                self._terminate(DebateTerminationReason.MAX_ROUNDS, DebateStatus.MAX_ROUNDS)
                break
            if not material_round and self.round > 1:
                self._terminate(
                    DebateTerminationReason.NO_NEW_EVIDENCE, DebateStatus.COMPLETED
                )
                break
            if not owner_requested:
                # Challenges stand but nobody was asked to act; give owners a
                # round only when new material information could still arrive.
                # With a fixed critic configuration nothing new can appear, so
                # the loop guard above terminates deterministically next round.
                continue

        if self.status is DebateStatus.ACTIVE:  # pragma: no cover - safety net
            self._terminate(DebateTerminationReason.MAX_ROUNDS, DebateStatus.MAX_ROUNDS)
        self._record_event(
            DebateEventType.DEBATE_TERMINATED,
            {"reason": (self.termination_reason or DebateTerminationReason.FAILED).value},
        )
        return self.build_report()

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _default_revision(
        original: TradeProposal, critique: CritiqueRecord, clock: datetime
    ) -> TradeProposal | None:
        """Deterministic owner-side revision: down-weight confidence by materiality.

        Produces a NEW canonical TradeProposal; the original is never mutated.
        """
        if critique.requested_action is not RequestedAction.REVISE:
            return None
        reduced = round(max(0.0, original.confidence - critique.materiality / 2.0), 6)
        if reduced >= original.confidence:
            return None
        revision_tag = _canonical_hash(
            {
                "original": original.proposal_id,
                "critique": critique.critique_id,
                "confidence": reduced,
            }
        )[:REVISION_SUFFIX_LENGTH]
        return original.model_copy(
            update={
                "proposal_id": f"{original.proposal_id}:r-{revision_tag}",
                "confidence": reduced,
                "data_time": clock,
                "created_at": clock,
                "expires_at": clock + PROPOSAL_VALIDITY,
                "trace": original.trace,
            }
        )

    def _publish_critique(self, critique: CritiqueRecord) -> AgentMessage:
        # Bind every registered referenced evidence into the shared ledger.
        for ref in (*critique.evidence_refs, *critique.counter_evidence_refs):
            evidence = self._evidence_registry.get(ref)
            if evidence is not None:
                self.bus.register_evidence(evidence)
                item = self._ledger.add(evidence, critique.critic_agent_id)
                self._ref_to_canonical[ref] = item.evidence_id
        # Every CRITIQUE message must carry registered evidence (MA-1
        # invariant). The critic's audit finding is itself evidence: it never
        # invents market data, it records the critic's deterministic verdict.
        audit_id = self._audit_evidence_id(critique)
        self._audit_evidence_ids[critique.critique_id] = audit_id
        if critique.stance is CritiqueStance.CHALLENGE:
            self._record_event(
                DebateEventType.DEBATE_CHALLENGE,
                {
                    "critique_id": critique.critique_id,
                    "proposal_id": critique.proposal_id,
                },
            )
        payload = {
            "critique_id": critique.critique_id,
            "materiality": f"{critique.materiality:.6f}",
            "requested_action": critique.requested_action.value,
            "stance": critique.stance.value,
        }
        if critique.counter_evidence_refs:
            payload["counter_evidence_refs"] = ",".join(critique.counter_evidence_refs)
        return self.bus.publish(
            AgentMessage(
                schema_version=DEBATE_SCHEMA_VERSION,
                message_id=f"critique:{critique.critique_id}",
                run_id=self._trace.run_id,
                trace_id=self._trace.trace_id,
                sender=critique.critic_agent_id,
                receiver="opportunity-board",
                message_type=AgentMessageType.CRITIQUE,
                claim=critique.claim,
                evidence_refs=(audit_id,),
                confidence=critique.confidence,
                created_at=critique.created_at,
                data_time=critique.created_at,
                trace=self._trace,
                payload=tuple(sorted(payload.items())),
            )
        )

    def _audit_evidence_id(self, critique: CritiqueRecord) -> str:
        evidence_id = f"evidence:{critique.critique_id}"
        audit = AgentEvidence(
            schema_version=DEBATE_SCHEMA_VERSION,
            evidence_id=evidence_id,
            run_id=self._trace.run_id,
            producer_agent_id=critique.critic_agent_id,
            evidence_type="critique_audit",
            source_ref=f"debate:{self.debate_id}",
            claim_refs=(critique.proposal_id,),
            observed_at=critique.created_at,
            available_at=critique.created_at,
            content_hash=_canonical_hash(
                {
                    "critique_id": critique.critique_id,
                    "stance": critique.stance.value,
                    "claim": critique.claim,
                    "materiality": critique.materiality,
                }
            ),
            metadata=(),
            trace=self._trace,
        )
        self.bus.register_evidence(audit)
        self._ledger.add(audit, critique.critic_agent_id)
        return evidence_id

    def _publish_evidence_response(
        self,
        current: Mapping[str, DebatePosition],
        critique: CritiqueRecord,
        request_id: str,
    ) -> tuple[bool, AgentMessage]:
        """Route the owner's structured answer through the MA-1 bus.

        Returns ``(supplied, response_message)``. An ABSTAIN is explicit and
        never replaced with fabricated evidence.
        """
        position = current.get(critique.proposal_id)
        owner = position.owner_agent_id if position else self._owner_fallback(critique.proposal_id)
        # Only evidence that actually exists may be supplied (MA-3D).
        owner_refs = tuple(
            sorted(
                ref
                for ref in (position.evidence_refs if position else ())
                if ref in self._evidence_registry
            )
        )
        for ref in owner_refs:
            evidence = self._evidence_registry[ref]
            self.bus.register_evidence(evidence)
            item = self._ledger.add(evidence, owner)
            self._ref_to_canonical[ref] = item.evidence_id
        supplied = bool(owner_refs)
        response_payload = {
            "critique_id": critique.critique_id,
            "response": "EVIDENCE" if supplied else "ABSTAIN",
        }
        if owner_refs:
            response_payload["evidence_refs"] = ",".join(owner_refs)
        self.bus.request(
            AgentMessage(
                schema_version=DEBATE_SCHEMA_VERSION,
                message_id=request_id,
                run_id=self._trace.run_id,
                trace_id=self._trace.trace_id,
                sender=critique.critic_agent_id,
                receiver="opportunity-board",
                message_type=AgentMessageType.EVIDENCE_REQUEST,
                claim=f"evidence requested for {critique.proposal_id}: {critique.claim}",
                evidence_refs=(),
                confidence=1.0,
                created_at=self.bus.now(),
                data_time=self.bus.now(),
                requires_response=True,
                trace=self._trace,
                payload=(
                    ("critique_id", critique.critique_id),
                    ("proposal_id", critique.proposal_id),
                ),
            )
        )
        response_message = AgentMessage(
            schema_version=DEBATE_SCHEMA_VERSION,
            message_id=f"response:{request_id}",
            run_id=self._trace.run_id,
            trace_id=self._trace.trace_id,
            sender=owner,
            receiver=critique.critic_agent_id,
            message_type=AgentMessageType.EVIDENCE_RESPONSE,
            claim=(
                "evidence supplied" if supplied else "owner abstains: required evidence unavailable"
            ),
            # EVIDENCE_RESPONSE is evidence-required on the bus: abstains bind
            # the critique's audit evidence (already registered) instead of
            # inventing new evidence.
            evidence_refs=owner_refs or (self._audit_evidence_ids[critique.critique_id],),
            confidence=1.0,
            created_at=self.bus.now(),
            data_time=self.bus.now(),
            causation_id=request_id,
            trace=self._trace,
            payload=tuple(sorted(response_payload.items())),
        )
        self.bus.reply(response_message, request_id=request_id)
        self._response_ids.append(response_message.message_id)
        self._record_event(
            DebateEventType.DEBATE_EVIDENCE_RECEIVED,
            {"critique_id": critique.critique_id, "response": response_payload["response"]},
        )
        return supplied, response_message

    def _owner_fallback(self, proposal_id: str) -> str:
        position = next(
            (item for item in self._positions if item.proposal_id == proposal_id), None
        )
        if position is None:
            raise DebateError(f"unknown position: {proposal_id}")
        return position.owner_agent_id

    def _publish_revision(self, revised: TradeProposal, owner: str) -> AgentMessage:
        return self.bus.publish(
            AgentMessage(
                schema_version=DEBATE_SCHEMA_VERSION,
                message_id=f"revision:{revised.proposal_id}",
                run_id=self._trace.run_id,
                trace_id=self._trace.trace_id,
                sender=owner,
                receiver="opportunity-board",
                message_type=AgentMessageType.COUNTERPROPOSAL,
                claim=f"revised proposal {revised.proposal_id}",
                evidence_refs=(),
                confidence=1.0,
                created_at=self.bus.now(),
                data_time=self.bus.now(),
                trace=self._trace,
                payload=(("revised_proposal_id", revised.proposal_id),),
            )
        )

    def _fail(self, reason: str) -> None:
        self.status = DebateStatus.FAILED
        self.termination_reason = DebateTerminationReason.FAILED

    def _terminate(self, reason: DebateTerminationReason, status: DebateStatus) -> None:
        self.termination_reason = reason
        self.status = status

    def _record_event(self, event_type: DebateEventType, payload: Mapping[str, str]) -> None:
        self.events = (*self.events, (event_type.value, _canonical_json(payload)))


__all__ = [
    "CRITIC_FACTORIES",
    "DEBATE_CRITIC_VERSION",
    "DEBATE_SCHEMA_VERSION",
    "MAX_DEBATE_ROUNDS",
    "CounterSignalCritic",
    "DebateContext",
    "DebateError",
    "DebateLedger",
    "DebatePosition",
    "DebateRoute",
    "DebateRouter",
    "DebateSession",
    "DebateStatus",
    "EvidenceCritic",
    "RegimeCritic",
    "register_debate_agents",
]
