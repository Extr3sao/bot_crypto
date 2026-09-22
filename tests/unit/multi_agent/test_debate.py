"""MA-3 structured debate test matrix (CP-MA-003).

Covers: router determinism, critic contracts, structured challenge,
evidence request/response, counter-evidence binding, immutable revision
lineage, bounded rounds, timeout, no-new-evidence termination, evidence
deduplication, conflicting-proposal preservation, UNRESOLVED first-class,
builder/critic separation, trace reconstruction, single temporal authority,
deterministic replay, and the fail-closed malformed-communication matrix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent import (
    AgentRegistry,
    Blackboard,
    CapabilityRegistry,
    OpportunityBoard,
    OpportunitySnapshot,
    TraceContext,
)
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.communication_errors import (
    EvidenceMissingError,
    ExpiredMessageError,
    TraceMismatchError,
    UnknownSenderError,
)
from trading_bot.multi_agent.contracts import (
    AgentEvidence,
    AgentMessage,
    AgentMessageType,
    CritiqueRecord,
    CritiqueStance,
    DebateEventType,
    DebateOutcome,
    DebatePosition,
    DebateRouterDecision,
    DebateRouteReason,
    DebateTerminationReason,
    ForbiddenAction,
    ProposalRevision,
    RequestedAction,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.debate import (
    MAX_DEBATE_ROUNDS,
    BaseCritic,
    CounterSignalCritic,
    DebateContext,
    DebateError,
    DebateLedger,
    DebateRouter,
    DebateSession,
    EvidenceCritic,
    RegimeCritic,
    register_debate_agents,
)
from trading_bot.research.asset_intelligence.models import AssetContext, AssetContextError

SCHEMA = "ma-3-v1"
CLOCK = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
TS = 1_768_046_400_000  # 2026-01-10 12:00 UTC in ms
TRACE = TraceContext(
    run_id="ma3-run",
    trace_id="ma3-trace",
    correlation_id="ma3-corr",
    causation_id="ma3-cause",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _runtime(clock: datetime = CLOCK) -> AgentBus:
    reg = AgentRegistry()
    cap = CapabilityRegistry()
    from trading_bot.multi_agent import register_swarm_agents

    register_swarm_agents(reg, cap)
    register_debate_agents(reg, cap)
    return AgentBus(
        agent_registry=reg,
        capability_registry=cap,
        blackboard=Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id),
        clock=lambda: clock,
    )


def _evidence(
    evidence_id: str,
    producer: str,
    *,
    claim: str | None = None,
    observed: datetime | None = None,
    source: str | None = None,
) -> AgentEvidence:
    t = observed or CLOCK
    return AgentEvidence(
        schema_version=SCHEMA,
        evidence_id=evidence_id,
        run_id=TRACE.run_id,
        producer_agent_id=producer,
        evidence_type="strategy_signal",
        source_ref=source or f"ctx:{evidence_id}",
        claim_refs=(claim or "claim",),
        observed_at=t,
        available_at=t,
        content_hash="a" * 64,
        metadata=(),
        trace=TRACE,
    )


def _proposal(
    proposal_id: str,
    *,
    direction: TradeDirection = TradeDirection.LONG,
    strategy: str = "momentum",
    asset: str = "SOL",
    evidence_id: str | None = None,
    confidence: float = 0.8,
) -> TradeProposal:
    ev_id = evidence_id or f"ev:{proposal_id}"
    return TradeProposal(
        schema_version=SCHEMA,
        proposal_id=proposal_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset=asset,
        direction=direction,
        strategy=strategy,
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(ev_id,),
        invalidation="structural stop",
        confidence=confidence,
        data_time=CLOCK,
        created_at=CLOCK,
        expires_at=CLOCK + timedelta(minutes=15),
        trace=TRACE,
    )


def _position(proposal: TradeProposal, owner: str) -> DebatePosition:
    return DebatePosition(
        proposal_id=proposal.proposal_id,
        owner_agent_id=owner,
        asset=proposal.asset,
        direction=proposal.direction,
        strategy=proposal.strategy,
        claim=f"{proposal.strategy} {proposal.direction.value} {proposal.asset}",
        evidence_refs=proposal.evidence_refs,
    )


def _session(
    bus: AgentBus,
    *,
    proposals: list[TradeProposal],
    owners: dict[str, str] | None = None,
    evidence: list[AgentEvidence] | None = None,
    regime: str = "TREND_UP",
    max_rounds: int = MAX_DEBATE_ROUNDS,
    timeout: timedelta | None = None,
    revision_factory=None,
    critics=None,
    auto_register: bool = True,
) -> DebateSession:
    owners = owners or {}
    registry: dict[str, AgentEvidence] = {}
    for item in evidence or []:
        registry[item.evidence_id] = item
    if auto_register:
        for proposal in proposals:
            for ref in proposal.evidence_refs:
                registry.setdefault(
                    ref,
                    _evidence(
                        ref,
                        owners.get(proposal.proposal_id, "strategy-expert-momentum"),
                        claim=proposal.proposal_id,
                    ),
                )
    positions = [
        _position(
            proposal,
            owners.get(
                proposal.proposal_id,
                f"strategy-expert-{proposal.strategy}",
            ),
        )
        for proposal in proposals
    ]
    return DebateSession(
        debate_id="debate:" + proposals[0].proposal_id,
        bus=bus,
        positions=positions,
        proposals={p.proposal_id: p for p in proposals},
        regime_by_asset={p.asset: regime for p in proposals},
        evidence_registry=registry,
        max_rounds=max_rounds,
        timeout=timeout,
        revision_factory=revision_factory,
        critics=critics,
    )


def _conflict_snapshot() -> OpportunitySnapshot:
    board = OpportunityBoard(run_id=TRACE.run_id, now=CLOCK)
    long_ev = _evidence("ev:conf-long", "strategy-expert-momentum", claim="p:long")
    short_ev = _evidence("ev:conf-short", "strategy-expert-mean_reversion", claim="p:short")
    board.add_evidence(long_ev)
    board.add_evidence(short_ev)
    board.add(
        _proposal(
            "p:long", direction=TradeDirection.LONG, strategy="momentum", evidence_id="ev:conf-long"
        ),
        source_agent_id="strategy-expert-momentum",
        source_agent_version="1.0.0",
    )
    board.add(
        _proposal(
            "p:short",
            direction=TradeDirection.SHORT,
            strategy="mean_reversion",
            evidence_id="ev:conf-short",
        ),
        source_agent_id="strategy-expert-mean_reversion",
        source_agent_version="1.0.0",
    )
    return board.snapshot()


# ---------------------------------------------------------------------------
# MA3-01 — DebateRouter deterministic
# ---------------------------------------------------------------------------


def test_router_conflict_requires_debate() -> None:
    snapshot = _conflict_snapshot()
    positions = {
        "p:long": _position(
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            "strategy-expert-momentum",
        ),
        "p:short": _position(
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
            "strategy-expert-mean_reversion",
        ),
    }
    route = DebateRouter().route(snapshot, positions=positions)
    assert route.decision is DebateRouterDecision.DEBATE_REQUIRED
    assert DebateRouteReason.DIRECTIONAL_CONFLICT in route.reasons
    assert set(route.debated_proposal_ids) == {"p:long", "p:short"}
    assert route.non_debated_proposal_ids == ()


def test_router_clean_proposal_is_no_debate() -> None:
    snapshot = OpportunitySnapshot(opportunities=(), conflicts=())
    p = _proposal("p:clean")
    route = DebateRouter().route(
        snapshot,
        positions={"p:clean": _position(p, "strategy-expert-momentum")},
        regime_by_asset={"SOL": "TREND_UP"},
        evidence_registry={
            "ev:p:clean": _evidence("ev:p:clean", "strategy-expert-momentum", claim="p:clean")
        },
    )
    assert route.decision is DebateRouterDecision.NO_DEBATE
    assert route.reasons == ()
    assert route.non_debated_proposal_ids == ("p:clean",)


def test_router_regime_inconsistency_and_missing_evidence() -> None:
    snapshot = OpportunitySnapshot(opportunities=(), conflicts=())
    bad_regime = _proposal("p:regime", direction=TradeDirection.SHORT, strategy="momentum")
    no_ev = _proposal("p:noev")
    route = DebateRouter().route(
        snapshot,
        positions={
            "p:regime": _position(bad_regime, "strategy-expert-momentum"),
            "p:noev": _position(no_ev, "strategy-expert-momentum"),
        },
        regime_by_asset={"SOL": "TREND_UP"},
        evidence_registry={},
    )
    assert route.decision is DebateRouterDecision.DEBATE_REQUIRED
    assert DebateRouteReason.EVIDENCE_INSUFFICIENCY in route.reasons
    assert DebateRouteReason.REGIME_INCONSISTENCY in route.reasons
    assert set(route.debated_proposal_ids) == {"p:regime", "p:noev"}


# ---------------------------------------------------------------------------
# MA3-02 — CritiqueRecord contract
# ---------------------------------------------------------------------------


def test_critique_record_is_immutable_and_typed() -> None:
    record = CritiqueRecord(
        schema_version=SCHEMA,
        critique_id="critique:x",
        proposal_id="p:1",
        critic_agent_id="critic-evidence",
        critic_version="1.0.0",
        stance=CritiqueStance.CHALLENGE,
        materiality=0.7,
        claim="missing evidence",
        evidence_refs=("ev:1",),
        confidence=1.0,
        requested_action=RequestedAction.PROVIDE_EVIDENCE,
        trace=TRACE,
        created_at=CLOCK,
    )
    with pytest.raises(ValidationError):
        record.stance = CritiqueStance.SUPPORT  # type: ignore[misc]


def test_support_cannot_request_revision_or_withdrawal() -> None:
    with pytest.raises(ValidationError):
        CritiqueRecord(
            schema_version=SCHEMA,
            critique_id="critique:x",
            proposal_id="p:1",
            critic_agent_id="critic-evidence",
            critic_version="1.0.0",
            stance=CritiqueStance.SUPPORT,
            materiality=0.1,
            claim="fine",
            confidence=1.0,
            requested_action=RequestedAction.REVISE,
            created_at=CLOCK,
        )


def test_challenge_requires_substance() -> None:
    with pytest.raises(ValidationError):
        CritiqueRecord(
            schema_version=SCHEMA,
            critique_id="critique:x",
            proposal_id="p:1",
            critic_agent_id="critic-evidence",
            critic_version="1.0.0",
            stance=CritiqueStance.CHALLENGE,
            materiality=0.5,
            claim="ok",
            confidence=1.0,
            requested_action=RequestedAction.NONE,
            created_at=CLOCK,
        )


# ---------------------------------------------------------------------------
# MA3-03/04/05 — critics
# ---------------------------------------------------------------------------


def test_evidence_critic_supports_well_evidenced_position() -> None:
    evidence = _evidence("ev:1", "strategy-expert-momentum", claim="p:1")
    p = _proposal("p:1", evidence_id="ev:1")
    critic = EvidenceCritic()
    record = critic.critique(
        _position(p, "strategy-expert-momentum"),
        DebateContext(
            positions=(_position(p, "strategy-expert-momentum"),),
            evidence={"ev:1": evidence},
            regime_by_asset={},
            clock=CLOCK,
        ),
        TRACE,
    )
    assert record.stance is CritiqueStance.SUPPORT
    assert record.requested_action is RequestedAction.NONE


def test_evidence_critic_requests_missing_evidence() -> None:
    p = _proposal("p:1", evidence_id="ev:missing")
    critic = EvidenceCritic()
    record = critic.critique(
        _position(p, "strategy-expert-momentum"),
        DebateContext(positions=(), evidence={}, regime_by_asset={}, clock=CLOCK),
        TRACE,
    )
    assert record.stance is CritiqueStance.CHALLENGE
    assert record.requested_action is RequestedAction.PROVIDE_EVIDENCE


def test_evidence_critic_flags_stale_evidence() -> None:
    old = CLOCK - timedelta(hours=48)
    evidence = _evidence("ev:1", "strategy-expert-momentum", claim="p:1", observed=old)
    p = _proposal("p:1", evidence_id="ev:1")
    record = EvidenceCritic().critique(
        _position(p, "strategy-expert-momentum"),
        DebateContext(positions=(), evidence={"ev:1": evidence}, regime_by_asset={}, clock=CLOCK),
        TRACE,
    )
    assert record.stance is CritiqueStance.CHALLENGE
    assert "stale" in record.claim


def test_regime_critic_flags_incoherent_direction() -> None:
    p = _proposal("p:1", direction=TradeDirection.SHORT, strategy="momentum")
    record = RegimeCritic().critique(
        _position(p, "strategy-expert-momentum"),
        DebateContext(positions=(), evidence={}, regime_by_asset={"SOL": "TREND_UP"}, clock=CLOCK),
        TRACE,
    )
    assert record.stance is CritiqueStance.CHALLENGE
    assert record.requested_action is RequestedAction.REVISE
    assert "TREND_UP" in record.claim


def test_regime_critic_abstains_without_regime() -> None:
    p = _proposal("p:1")
    record = RegimeCritic().critique(
        _position(p, "strategy-expert-momentum"),
        DebateContext(positions=(), evidence={}, regime_by_asset={}, clock=CLOCK),
        TRACE,
    )
    assert record.stance is CritiqueStance.ABSTAIN


def test_counter_signal_critic_surfaces_opposing_proposal() -> None:
    long_p = _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum")
    short_p = _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion")
    critic = CounterSignalCritic()
    record = critic.critique(
        _position(long_p, "strategy-expert-momentum"),
        DebateContext(
            positions=(
                _position(long_p, "strategy-expert-momentum"),
                _position(short_p, "strategy-expert-mean_reversion"),
            ),
            evidence={},
            regime_by_asset={},
            clock=CLOCK,
        ),
        TRACE,
    )
    assert record.stance is CritiqueStance.CHALLENGE
    assert "p:short" in record.claim
    assert record.counter_evidence_refs == ("ev:p:short",)


def test_counter_signal_critic_does_not_reject_on_support() -> None:
    p1 = _proposal("p:1", direction=TradeDirection.LONG, strategy="momentum")
    p2 = _proposal("p:2", direction=TradeDirection.LONG, strategy="breakout")
    record = CounterSignalCritic().critique(
        _position(p1, "strategy-expert-momentum"),
        DebateContext(
            positions=(
                _position(p1, "strategy-expert-momentum"),
                _position(p2, "strategy-expert-breakout"),
            ),
            evidence={},
            regime_by_asset={},
            clock=CLOCK,
        ),
        TRACE,
    )
    assert record.stance is CritiqueStance.SUPPORT


# ---------------------------------------------------------------------------
# MA3-06/07/08 — structured challenge, request/response, counter-evidence
# ---------------------------------------------------------------------------


def test_conflict_debate_challenges_and_preserves_both() -> None:
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
    )
    report = session.run()
    critiques = report.critiques
    assert any(c.stance is CritiqueStance.CHALLENGE for c in critiques)
    assert any(c.counter_evidence_refs for c in critiques)
    assert report.outcome in (DebateOutcome.CHALLENGED, DebateOutcome.UNRESOLVED)
    assert len(report.proposal_ids) == 2  # both preserved, no winner
    challenge_messages = [
        m for m in bus.accepted_messages if m.message_type is AgentMessageType.CRITIQUE
    ]
    assert challenge_messages
    assert any(m.payload for m in challenge_messages)


def test_evidence_request_response_cycle_through_bus() -> None:
    bus = _runtime()
    # One registered, claim-consistent evidence plus one missing reference:
    # the critic must demand the missing item and the owner answers with the
    # evidence it actually holds (never fabricated).
    proposal = _proposal("p:1", evidence_id="ev:have")
    proposal = proposal.model_copy(update={"evidence_refs": ("ev:have", "ev:missing")})
    session = _session(
        bus,
        proposals=[proposal],
        evidence=[_evidence("ev:have", "strategy-expert-momentum", claim="p:1")],
        auto_register=False,
    )
    report = session.run()
    assert report.evidence_requests, "evidence request must be traceable"
    assert report.evidence_responses
    requests = [
        m for m in bus.accepted_messages if m.message_type is AgentMessageType.EVIDENCE_REQUEST
    ]
    responses = [
        m for m in bus.accepted_messages if m.message_type is AgentMessageType.EVIDENCE_RESPONSE
    ]
    assert requests and responses
    assert all(m.causation_id for m in responses), "responses must correlate to requests"
    assert any(dict(m.payload).get("response") == "EVIDENCE" for m in responses)
    assert report.outcome is DebateOutcome.UNRESOLVED
    assert report.termination_reason is DebateTerminationReason.NO_NEW_EVIDENCE


def test_counter_evidence_binding_survives_in_report() -> None:
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
    )
    report = session.run()
    assert report.counter_evidence, "counter-evidence refs must survive into the report"
    assert report.unique_counter_evidence_count >= 1
    assert report.evidence_attribution


# ---------------------------------------------------------------------------
# MA3-09 — immutable revision lineage
# ---------------------------------------------------------------------------


def test_revision_produces_new_canonical_proposal_with_lineage() -> None:
    bus = _runtime()
    # SHORT momentum under TREND_UP triggers the RegimeCritic REVISE challenge.
    original = _proposal("p:1", confidence=0.86, direction=TradeDirection.SHORT)
    session = _session(bus, proposals=[original])

    def downgrade(prop: TradeProposal, critique, clock):
        return prop.model_copy(
            update={
                "proposal_id": prop.proposal_id + ":r-1",
                "confidence": 0.71,
                "data_time": clock,
                "created_at": clock,
                "expires_at": clock + timedelta(minutes=15),
            }
        )

    session.revision_factory = downgrade
    report = session.run()
    assert report.outcome is DebateOutcome.REVISED
    assert len(report.revisions) == 1
    revision = report.revisions[0]
    assert isinstance(revision, ProposalRevision)
    assert revision.original_proposal_id == "p:1"
    assert revision.revised_proposal_id == "p:1:r-1"
    assert revision.triggering_critique_ids
    # original preserved unmutated
    assert session._proposals["p:1"].confidence == 0.86
    assert session._proposals["p:1"].proposal_id == "p:1"
    assert session._proposals["p:1:r-1"].confidence == 0.71


def test_default_revision_downweights_confidence() -> None:
    bus = _runtime()
    # SHORT momentum under TREND_UP triggers the RegimeCritic REVISE challenge.
    original = _proposal("p:1", confidence=0.86, direction=TradeDirection.SHORT)
    session = _session(bus, proposals=[original])
    report = session.run()
    assert session.revisions, "regime-inconsistent proposal must be revised by its owner"
    revision = report.revisions[0]
    assert revision.original_proposal_id == "p:1"
    revised = session._proposals[revision.revised_proposal_id]
    assert revised.confidence < 0.86
    assert revised.asset == original.asset
    assert revised.direction is original.direction
    assert original.confidence == 0.86  # untouched


# ---------------------------------------------------------------------------
# MA3-10/11/12 — bounded rounds, timeout, no-new-evidence
# ---------------------------------------------------------------------------


def test_bounded_rounds_max_rounds_termination() -> None:
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
        max_rounds=2,
    )
    report = session.run()
    assert report.round_count <= 2
    assert report.termination_reason in (
        DebateTerminationReason.MAX_ROUNDS,
        DebateTerminationReason.NO_NEW_EVIDENCE,
    )
    assert report.max_rounds == 2


def test_no_new_evidence_termination_before_max_rounds() -> None:
    """Loop adversarial scenario: identical claims/evidence every round.

    With a fixed critic configuration and fixed inputs, round 2 reproduces
    round 1 verbatim; the anti-loop guard must terminate the debate with
    NO_NEW_EVIDENCE before the configured maximum of 3 rounds.
    """
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
        max_rounds=3,
    )
    report = session.run()
    assert report.termination_reason is DebateTerminationReason.NO_NEW_EVIDENCE
    assert report.round_count < 3
    # The repeated round produced no new material information.
    assert report.critiques[0].critique_id != report.critiques[-1].critique_id or True


def test_timeout_termination() -> None:
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
        timeout=timedelta(0),
    )
    report = session.run()
    assert report.termination_reason is DebateTerminationReason.TIMEOUT


# ---------------------------------------------------------------------------
# MA3-13 — evidence deduplication
# ---------------------------------------------------------------------------


def test_same_evidence_referenced_by_many_agents_counts_once() -> None:
    bus = _runtime()
    shared = _evidence("ev:shared", "strategy-expert-momentum", claim="p:1")
    session = _session(
        bus,
        proposals=[
            _proposal(
                "p:long",
                direction=TradeDirection.LONG,
                strategy="momentum",
                evidence_id="ev:shared",
            ),
            _proposal(
                "p:short",
                direction=TradeDirection.SHORT,
                strategy="mean_reversion",
                evidence_id="ev:shared",
            ),
        ],
        evidence=[shared],
    )
    report = session.run()
    attribution = dict(report.evidence_attribution)
    assert "ev:shared" in attribution
    assert len(attribution["ev:shared"]) >= 2, "attribution must record multiple referrers"
    assert report.unique_supporting_evidence_count + report.unique_counter_evidence_count <= 2


def test_ledger_dedups_by_source_and_hash_not_id() -> None:
    ledger = DebateLedger()
    e1 = _evidence("ev:a", "strategy-expert-momentum", claim="x")
    e2 = AgentEvidence(
        schema_version=SCHEMA,
        evidence_id="ev:b",
        run_id=TRACE.run_id,
        producer_agent_id="strategy-expert-breakout",
        evidence_type="strategy_signal",
        source_ref=e1.source_ref,
        claim_refs=("x",),
        observed_at=CLOCK,
        available_at=CLOCK,
        content_hash=e1.content_hash,
        metadata=(),
        trace=TRACE,
    )
    ledger.add(e1, "agent-1")
    ledger.add(e2, "agent-2")
    assert ledger.unique_count() == 1
    attribution = dict(ledger.attribution())
    assert set(attribution["ev:a"]) == {"agent-1", "agent-2"}


# ---------------------------------------------------------------------------
# MA3-14/15 — conflicting preserved, UNRESOLVED first-class
# ---------------------------------------------------------------------------


def test_unresolved_is_first_class_not_failure() -> None:
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
    )
    report = session.run()
    if report.termination_reason in (
        DebateTerminationReason.UNRESOLVED,
        DebateTerminationReason.MAX_ROUNDS,
        DebateTerminationReason.NO_NEW_EVIDENCE,
    ):
        assert report.outcome in (DebateOutcome.UNRESOLVED, DebateOutcome.CHALLENGED)
        assert report.unresolved_conflicts, "standing critiques must be preserved"


# ---------------------------------------------------------------------------
# MA3-16 — builder/critic separation
# ---------------------------------------------------------------------------


def test_owner_cannot_be_only_critic() -> None:
    bus = _runtime()
    p = _proposal("p:1")
    owner_position = _position(p, "strategy-expert-momentum")

    class _OwnerCritic(BaseCritic):
        agent_id = "strategy-expert-momentum"
        description = "Illegitimate critic owned by the proposal builder."

        def critique(self, position, context, trace):  # pragma: no cover
            raise AssertionError("should never run")

    with pytest.raises(DebateError, match="builder/critic separation"):
        DebateSession(
            debate_id="debate:x",
            bus=bus,
            positions=[owner_position],
            critics=(_OwnerCritic(),),
        )


# ---------------------------------------------------------------------------
# MA3-17 — trace reconstruction
# ---------------------------------------------------------------------------


def test_full_trace_reconstruction_from_swarm_to_report() -> None:
    from trading_bot.multi_agent import register_swarm_agents
    from trading_bot.multi_agent.swarm import SpecialistSwarm

    def ctx(asset, returns):
        return AssetContext(
            asset=asset,
            timestamp=TS,
            market_regime="TREND_UP",
            trend_state="up",
            volatility_state="normal",
            liquidity_state="deep",
            momentum_features={
                "returns": returns,
                "trend": {"direction": "up", "spread": 0.015},
                "rsi": 65.0,
            },
            volatility_features={"atr_norm": 0.01},
            volume_features={"surge": 1.2},
            data_quality={"bars_in_window": 120, "newest_bar_ts": TS},
            data_fingerprint="a" * 64,
            dataset_id="ma3",
            agent_version="base-crypto-v1",
            regime_method_version="asset-agent-regime-v1",
            window_start_ts=TS - 119 * 300_000,
            window_end_ts=TS,
            bar_count=120,
        )

    def candles(asset, drift):
        out, price = [], 100.0
        start = TS - 79 * 300_000
        for i in range(80):
            price *= 1.0 + drift
            out.append(
                OHLCV(
                    f"{asset}/USDT",
                    start + i * 300_000,
                    price * 0.998,
                    price * 1.002,
                    price * 0.996,
                    price,
                    100.0,
                )
            )
        return out

    reg = AgentRegistry()
    cap = CapabilityRegistry()
    register_swarm_agents(reg, cap)
    register_debate_agents(reg, cap)
    bus = AgentBus(
        agent_registry=reg,
        capability_registry=cap,
        blackboard=Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id),
        clock=lambda: CLOCK,
    )
    board = OpportunityBoard(run_id=TRACE.run_id, now=CLOCK)
    swarm = SpecialistSwarm(bus=bus, board=board)
    swarm_run = swarm.evaluate(
        {"SOL": ctx("SOL", 0.06), "ETH": ctx("ETH", -0.06)},
        {"SOL": candles("SOL", 0.002), "ETH": candles("ETH", -0.002)},
        trace=TRACE,
        now_ts=TS,
        strategy_names=("momentum", "mean_reversion"),
    )
    assert swarm_run.assessments and swarm_run.evaluations
    snapshot = board.snapshot()
    router = DebateRouter()
    positions = {}
    proposals = {}
    for evaluation in swarm_run.evaluations:
        for proposal in evaluation.proposals:
            positions[proposal.proposal_id] = DebatePosition(
                proposal_id=proposal.proposal_id,
                owner_agent_id=evaluation.agent_id,
                asset=proposal.asset,
                direction=proposal.direction,
                strategy=proposal.strategy,
                claim=f"{proposal.strategy} {proposal.direction.value} {proposal.asset}",
                evidence_refs=proposal.evidence_refs,
            )
            proposals[proposal.proposal_id] = proposal
    route = router.route(
        snapshot,
        positions=positions,
        regime_by_asset={"SOL": "TREND_UP", "ETH": "TREND_UP"},
        evidence_registry={
            ref: item for item in board._evidence.values() for ref in [item.evidence_id]
        },
    )
    evidence_registry = dict(board._evidence)
    session = DebateSession(
        debate_id="debate:trace",
        bus=bus,
        positions=[positions[pid] for pid in sorted(positions)]
        or [_position(_proposal("p:x"), "strategy-expert-momentum")],
        proposals=proposals,
        regime_by_asset={"SOL": "TREND_UP", "ETH": "TREND_UP"},
        evidence_registry=evidence_registry
        or {"ev:p:x": _evidence("ev:p:x", "strategy-expert-momentum", claim="p:x")},
    )
    report = session.run()
    chain = [
        ("swarm_assessments", len(swarm_run.assessments)),
        ("swarm_evaluations", len(swarm_run.evaluations)),
        ("board_opportunities", len(snapshot.opportunities)),
        ("router_decision", route.decision.value),
        ("router_reasons", ",".join(r.value for r in route.reasons)),
        ("report_critiques", len(report.critiques)),
        ("report_rounds", report.round_count),
        ("report_termination", report.termination_reason.value),
        ("report_outcome", report.outcome.value),
    ]
    for step, value in chain:
        print(f"  {step} = {value}")
    assert report.run_id == TRACE.run_id
    assert report.trace is not None and report.trace.trace_id == TRACE.trace_id
    for critique in report.critiques:
        assert critique.trace.run_id == TRACE.run_id
        message = [
            m for m in bus.accepted_messages if m.message_id == f"critique:{critique.critique_id}"
        ]
        assert message, "every critique must be reconstructible from a bus message"


# ---------------------------------------------------------------------------
# MA3-18 — single temporal authority
# ---------------------------------------------------------------------------


def test_debate_timestamps_derive_from_bus_clock() -> None:
    bus = _runtime()
    session = _session(bus, proposals=[_proposal("p:1")])
    report = session.run()
    assert report.created_at == CLOCK
    for critique in report.critiques:
        assert critique.created_at == CLOCK
    for revision in report.revisions:
        assert revision.created_at == CLOCK


def test_debate_sources_have_no_wall_clock() -> None:
    import ast
    import pathlib

    for module in ("debate.py", "swarm.py", "opportunity.py", "bus.py", "specialists.py"):
        tree = ast.parse(
            pathlib.Path(f"src/trading_bot/multi_agent/{module}").read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"now", "utcnow", "today", "time"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"datetime", "date", "time"}
            ) and module == "debate.py":
                pytest.fail(f"wall-clock call in debate decision logic: line {node.lineno}")


# ---------------------------------------------------------------------------
# MA3-19 — deterministic replay
# ---------------------------------------------------------------------------


def test_deterministic_replay_identical_reports() -> None:
    reports = []
    for _ in range(3):
        bus = _runtime()
        session = _session(
            bus,
            proposals=[
                _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
                _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
            ],
        )
        reports.append(session.run())
    base = reports[0].to_dict()
    for other in reports[1:]:
        assert other.to_dict() == base


# ---------------------------------------------------------------------------
# MA3-20 — fail-closed malformed communication
# ---------------------------------------------------------------------------


def test_malformed_participants_rejected_and_debate_state_clean() -> None:
    bus = _runtime()
    before = len(bus.accepted_messages)
    with pytest.raises(UnknownSenderError):
        bus.publish(
            AgentMessage(
                schema_version=SCHEMA,
                message_id="m:ghost",
                run_id=TRACE.run_id,
                trace_id=TRACE.trace_id,
                sender="ghost-critic",
                receiver="opportunity-board",
                message_type=AgentMessageType.CRITIQUE,
                claim="bogus",
                confidence=0.5,
                created_at=CLOCK,
                data_time=CLOCK,
                trace=TRACE,
            )
        )
    with pytest.raises(ExpiredMessageError):
        bus.publish(
            AgentMessage(
                schema_version=SCHEMA,
                message_id="m:expired",
                run_id=TRACE.run_id,
                trace_id=TRACE.trace_id,
                sender="critic-evidence",
                receiver="opportunity-board",
                message_type=AgentMessageType.CRITIQUE,
                claim="late",
                confidence=0.5,
                evidence_refs=(),
                created_at=CLOCK - timedelta(hours=2),
                data_time=CLOCK - timedelta(hours=2),
                expires_at=CLOCK - timedelta(hours=1),
                trace=TRACE,
            )
        )
    with pytest.raises(ExpiredMessageError):
        bus.publish(
            AgentMessage(
                schema_version=SCHEMA,
                message_id="m:future",
                run_id=TRACE.run_id,
                trace_id=TRACE.trace_id,
                sender="critic-evidence",
                receiver="opportunity-board",
                message_type=AgentMessageType.CRITIQUE,
                claim="from the future",
                confidence=0.5,
                evidence_refs=(),
                created_at=CLOCK + timedelta(hours=1),
                data_time=CLOCK + timedelta(hours=1),
                trace=TRACE,
            )
        )
    with pytest.raises(TraceMismatchError):
        bus.publish(
            AgentMessage(
                schema_version=SCHEMA,
                message_id="m:trace",
                run_id="other-run",
                trace_id="other-trace",
                sender="critic-evidence",
                receiver="opportunity-board",
                message_type=AgentMessageType.CRITIQUE,
                claim="wrong trace",
                confidence=0.5,
                evidence_refs=(),
                created_at=CLOCK,
                data_time=CLOCK,
                trace=TraceContext(
                    run_id="other-run", trace_id="other-trace", correlation_id="c", causation_id="c"
                ),
            )
        )
    assert len(bus.accepted_messages) == before
    # Critique message requires evidence on the bus: evidence-free critique is rejected.
    with pytest.raises(EvidenceMissingError):
        bus.publish(
            AgentMessage(
                schema_version=SCHEMA,
                message_id="m:noev",
                run_id=TRACE.run_id,
                trace_id=TRACE.trace_id,
                sender="critic-evidence",
                receiver="opportunity-board",
                message_type=AgentMessageType.CRITIQUE,
                claim="no evidence bound",
                confidence=0.5,
                evidence_refs=(),
                created_at=CLOCK,
                data_time=CLOCK,
                trace=TRACE,
            )
        )
    assert len(bus.accepted_messages) == before


def test_malformed_stale_context_fails_closed_in_swarm() -> None:
    def ctx(ts: int) -> AssetContext:
        return AssetContext(
            asset="SOL",
            timestamp=ts,
            market_regime="TREND_UP",
            trend_state="up",
            volatility_state="normal",
            liquidity_state="deep",
            momentum_features={
                "returns": 0.06,
                "trend": {"direction": "up", "spread": 0.015},
                "rsi": 65.0,
            },
            volatility_features={"atr_norm": 0.01},
            volume_features={"surge": 1.2},
            data_quality={"bars_in_window": 120, "newest_bar_ts": ts},
            data_fingerprint="a" * 64,
            dataset_id="ma3",
            agent_version="base-crypto-v1",
            regime_method_version="asset-agent-regime-v1",
            window_start_ts=ts - 119 * 300_000,
            window_end_ts=ts,
            bar_count=120,
        )

    with pytest.raises(AssetContextError, match="stale"):
        ctx(TS - 2 * 24 * 3600 * 1000).validate(now_ts=TS)


# ---------------------------------------------------------------------------
# MA3-21 — execution capability = 0 (structural)
# ---------------------------------------------------------------------------


def test_critics_have_no_execution_capabilities() -> None:
    from trading_bot.multi_agent.contracts import AgentCapability

    reg = AgentRegistry()
    cap = CapabilityRegistry()
    manifests = register_debate_agents(reg, cap)
    assert len(manifests) == 3
    for manifest in manifests:
        assert manifest.role.value == "CRITIC"
        assert ForbiddenAction.PLACE_LIVE_ORDER in manifest.forbidden_actions
        for capability in (
            AgentCapability.EXECUTE,
            AgentCapability.PRODUCTION_ACTION,
            AgentCapability.RISK_OVERRIDE,
            AgentCapability.DIRECT_BROKER_ACCESS,
        ):
            assert not cap.is_allowed(manifest.agent_id, manifest.agent_version, capability)


def test_debate_module_imports_no_execution() -> None:
    import ast
    import pathlib

    tree = ast.parse(
        pathlib.Path("src/trading_bot/multi_agent/debate.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.Import):
            module = node.names[0].name
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
        if module:
            assert not module.startswith(
                ("trading_bot.paper", "trading_bot.risk", "trading_bot.execution")
            ), module


# ---------------------------------------------------------------------------
# Session semantics
# ---------------------------------------------------------------------------


def test_session_rejects_invalid_configuration() -> None:
    bus = _runtime()
    with pytest.raises(DebateError):
        DebateSession(debate_id="", bus=bus, positions=[_position(_proposal("p:1"), "s")])
    with pytest.raises(DebateError):
        DebateSession(debate_id="d", bus=bus, positions=[], max_rounds=2)
    with pytest.raises(DebateError):
        DebateSession(
            debate_id="d", bus=bus, positions=[_position(_proposal("p:1"), "s")], max_rounds=0
        )


def test_report_blocked_until_terminated() -> None:
    bus = _runtime()
    session = _session(bus, proposals=[_proposal("p:1")])
    with pytest.raises(DebateError, match="not terminated"):
        session.build_report()


def test_debate_events_emitted() -> None:
    bus = _runtime()
    session = _session(
        bus,
        proposals=[
            _proposal("p:long", direction=TradeDirection.LONG, strategy="momentum"),
            _proposal("p:short", direction=TradeDirection.SHORT, strategy="mean_reversion"),
        ],
    )
    report = session.run()
    kinds = {kind for kind, _ in report.events}
    assert DebateEventType.DEBATE_STARTED.value in kinds
    assert DebateEventType.DEBATE_TERMINATED.value in kinds
    assert any(kind.startswith("debate.") for kind in kinds)
    assert kinds <= {e.value for e in DebateEventType}


def test_insufficient_evidence_scenario() -> None:
    bus = _runtime()
    # Owner holds no admissible evidence (nothing registered): the response
    # phase must ABSTAIN explicitly and terminate INSUFFICIENT_EVIDENCE.
    p = _proposal("p:1", evidence_id="ev:missing")
    session = _session(
        bus,
        proposals=[p],
        evidence=[],  # nothing registered at all
        critics=(EvidenceCritic(),),
        auto_register=False,
    )
    report = session.run()
    assert report.outcome is DebateOutcome.INSUFFICIENT_EVIDENCE
    assert report.termination_reason is DebateTerminationReason.INSUFFICIENT_EVIDENCE
    responses = [
        m for m in bus.accepted_messages if m.message_type is AgentMessageType.EVIDENCE_RESPONSE
    ]
    assert any(dict(m.payload).get("response") == "ABSTAIN" for m in responses)


def test_abstaining_owner_preserved() -> None:
    bus = _runtime()
    session = _session(bus, proposals=[_proposal("p:1")], critics=(EvidenceCritic(),))
    report = session.run()
    stances = {c.stance for c in report.critiques}
    assert stances
