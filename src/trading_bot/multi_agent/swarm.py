"""Deterministic specialist opportunity swarm orchestration for MA-2."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentLifecycleState,
    AgentManifest,
    AgentMessage,
    AgentMessageType,
    AgentRole,
    TraceContext,
)
from trading_bot.multi_agent.opportunity import OpportunityBoard
from trading_bot.multi_agent.registry import (
    AgentRegistry,
    CapabilityPolicy,
    CapabilityRegistry,
)
from trading_bot.multi_agent.specialists import (
    ASSET_EXPERT_FACTORIES,
    PROPOSAL_VALIDITY,
    STRATEGY_EXPERT_FACTORIES,
    AssetAssessment,
    StrategyEvaluation,
)
from trading_bot.research.asset_intelligence.models import AssetContext


@dataclass(frozen=True, slots=True)
class SwarmRun:
    assessments: tuple[AssetAssessment, ...]
    evaluations: tuple[StrategyEvaluation, ...]
    board: OpportunityBoard
    messages: tuple[AgentMessage, ...]


def register_swarm_agents(
    agent_registry: AgentRegistry,
    capability_registry: CapabilityRegistry,
) -> tuple[AgentManifest, ...]:
    """Register all MA-2 endpoints with only READ/WRITE capabilities.

    Registration is idempotent for an already registered identical version;
    conflicting identities fail closed through the canonical registries.
    """
    manifests = [
        ASSET_EXPERT_FACTORIES[asset]().manifest
        for asset in sorted(ASSET_EXPERT_FACTORIES)
    ]
    manifests.extend(
        STRATEGY_EXPERT_FACTORIES[strategy]().manifest
        for strategy in sorted(STRATEGY_EXPERT_FACTORIES)
    )
    manifests.append(
        AgentManifest(
            schema_version="ma-2-v1",
            agent_id="opportunity-board",
            agent_version="1.0.0",
            role=AgentRole.ORCHESTRATOR,
            description="Deterministic MA-2 opportunity board endpoint.",
            capabilities=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            input_contracts=("AssetAssessment", "TradeProposal"),
            output_contracts=("OpportunitySnapshot", "RankedOpportunity"),
            forbidden_actions=frozenset(),
            lifecycle_state=AgentLifecycleState.ENABLED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    for manifest in manifests:
        try:
            existing = agent_registry.get(manifest.agent_id, manifest.agent_version)
        except ValueError:
            agent_registry.register(manifest)
            existing = manifest
        if existing != manifest:
            raise ValueError(f"conflicting MA-2 manifest: {manifest.agent_id}")
        capability_registry.register_agent(existing)
        capability_registry.register_policy(
            CapabilityPolicy(
                agent_id=existing.agent_id,
                agent_version=existing.agent_version,
                grants=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            )
        )
    return tuple(manifests)


class SpecialistSwarm:
    """Run asset and strategy experts without any execution integration."""

    def __init__(self, *, bus: AgentBus, board: OpportunityBoard) -> None:
        self.bus = bus
        self.board = board

    def evaluate(
        self,
        contexts: Mapping[str, AssetContext],
        candles_by_asset: Mapping[str, Sequence[OHLCV]],
        *,
        trace: TraceContext,
        now_ts: int | None = None,
        timeframe: str = "5m",
        run_time: datetime | None = None,
        strategy_names: tuple[str, ...] = (
            "momentum",
            "trend",
            "breakout",
            "mean_reversion",
            "volatility",
        ),
    ) -> SwarmRun:
        # Single temporal authority: run_time overrides bus clock for
        # all message timestamps within this evaluation pass.
        decision_time = run_time if run_time is not None else self.bus._clock()
        assessments: list[AssetAssessment] = []
        evaluations: list[StrategyEvaluation] = []
        messages: list[AgentMessage] = []
        ordered_assets = tuple(sorted(contexts))
        ordered_strategies = tuple(sorted(strategy_names))

        for asset in ordered_assets:
            normalized_asset = asset.upper()
            context = contexts[asset]
            asset_expert = ASSET_EXPERT_FACTORIES[normalized_asset]()
            assessment = asset_expert.evaluate(context, trace=trace, now_ts=now_ts)
            assessments.append(assessment)
            for evidence in assessment.evidence:
                self.bus.register_evidence(evidence)
            messages.append(
                self.bus.publish(
                    self._message(
                        message_id=f"assessment:{normalized_asset}:{context.timestamp}",
                        sender=assessment.agent_id,
                        receiver="opportunity-board",
                        message_type=AgentMessageType.OBSERVATION,
                        claim=f"Asset assessment available for {normalized_asset}",
                        evidence_refs=assessment.evidence_refs,
                        confidence=assessment.confidence,
                        created_at=decision_time,
                        data_time=self._datetime(context.timestamp),
                        trace=assessment.trace,
                        asset=normalized_asset,
                        timeframe=timeframe,
                        regime=assessment.regime,
                    )
                )
            )

        assessment_by_asset = {item.asset: item for item in assessments}
        for asset in ordered_assets:
            normalized_asset = asset.upper()
            context = contexts[asset]
            asset_candles = candles_by_asset.get(asset, candles_by_asset.get(normalized_asset, ()))
            for strategy in ordered_strategies:
                strategy_expert = STRATEGY_EXPERT_FACTORIES[strategy]()
                evaluation = strategy_expert.evaluate(
                    context,
                    asset_candles,
                    trace=trace,
                    assessment=assessment_by_asset[normalized_asset],
                    now_ts=now_ts,
                    timeframe=timeframe,
                )
                evaluations.append(evaluation)
                evidence_by_proposal = {
                    proposal.proposal_id: evidence
                    for proposal, evidence in zip(
                        evaluation.proposals, evaluation.evidence, strict=True
                    )
                }
                for proposal in evaluation.proposals:
                    evidence = evidence_by_proposal[proposal.proposal_id]
                    self.bus.register_evidence(evidence)
                    self.board.add_evidence(evidence)
                    messages.append(
                        self.bus.publish(
                            self._message(
                                message_id=f"message:{proposal.proposal_id}",
                                sender=strategy_expert.manifest.agent_id,
                                receiver="opportunity-board",
                                message_type=AgentMessageType.PROPOSAL,
                                claim=f"{proposal.strategy} proposal for {proposal.asset}",
                                evidence_refs=proposal.evidence_refs,
                                confidence=proposal.confidence,
                                created_at=decision_time,
                                data_time=proposal.data_time,
                                expires_at=decision_time + PROPOSAL_VALIDITY,
                                trace=proposal.trace or trace,
                                asset=proposal.asset,
                                timeframe=proposal.timeframe,
                                regime=proposal.regime,
                            )
                        )
                    )
                    self.board.add(
                        proposal,
                        source_agent_id=strategy_expert.manifest.agent_id,
                        source_agent_version=strategy_expert.manifest.agent_version,
                    )
                messages.append(
                    self.bus.publish(
                        self._message(
                            message_id=f"status:{normalized_asset}:{strategy}:{context.timestamp}",
                            sender=strategy_expert.manifest.agent_id,
                            receiver="opportunity-board",
                            message_type=AgentMessageType.STATUS,
                            claim=evaluation.result_type,
                            evidence_refs=(),
                            confidence=1.0,
                            created_at=decision_time,
                            data_time=self._datetime(context.timestamp),
                            trace=trace,
                            asset=normalized_asset,
                            timeframe=timeframe,
                            regime=context.market_regime,
                        )
                    )
                )
        return SwarmRun(
            assessments=tuple(assessments),
            evaluations=tuple(evaluations),
            board=self.board,
            messages=tuple(messages),
        )

    @staticmethod
    def _datetime(timestamp: int) -> datetime:
        return datetime.fromtimestamp(timestamp / 1000, tz=UTC)

    @staticmethod
    def _message(
        *,
        message_id: str,
        sender: str,
        receiver: str,
        message_type: AgentMessageType,
        claim: str,
        evidence_refs: tuple[str, ...],
        confidence: float,
        created_at: datetime,
        data_time: datetime,
        trace: TraceContext,
        asset: str | None = None,
        timeframe: str | None = None,
        regime: str | None = None,
        expires_at: datetime | None = None,
    ) -> AgentMessage:
        return AgentMessage(
            schema_version="ma-2-v1",
            message_id=message_id,
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            sender=sender,
            receiver=receiver,
            message_type=message_type,
            claim=claim,
            evidence_refs=evidence_refs,
            confidence=confidence,
            created_at=created_at,
            data_time=data_time,
            expires_at=expires_at,
            trace=trace,
            asset=asset,
            timeframe=timeframe,
            regime=regime,
        )


__all__ = ["SpecialistSwarm", "SwarmRun", "register_swarm_agents"]
