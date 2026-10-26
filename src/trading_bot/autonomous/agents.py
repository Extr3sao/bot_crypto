"""Specialist agents — deterministic, structured, capability-bounded (§10).

These are NOT chat agents and NOT LLM calls. Each one is a small pure
function over the decision packet that emits ONE typed review
(``OBSERVATION`` / ``CRITIQUE`` / ``AGREEMENT`` / ``RISK_WARNING`` / ``VETO``)
with its evidence and counter-evidence. That keeps the review layer
reproducible and replayable: the same packet always yields the same reviews.

Hard boundaries (enforced, not documented):

* an agent declares its ``AgentCapability``; declaring a forbidden capability
  (execute_order, modify_risk_limits, modify_accounting, modify_risk_engine,
  escalate_permissions, modify_portfolio) makes registration fail;
* agents receive an immutable packet and return an immutable message — they
  cannot mutate the proposal, the risk state or the portfolio;
* no agent can approve size, leverage or limits: that stays deterministic in
  ``RiskManager``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .contracts import (
    AdmissionEntry,
    AdmissionStatus,
    AgentCapability,
    AgentMessage,
    ReviewType,
    StrategyPerformance,
    TradeProposal,
)

__all__ = [
    "AGENT_VERSION",
    "AgentRegistry",
    "CostEconomicsAgent",
    "DataIntegrityAgent",
    "EvidenceProvenanceAgent",
    "RegimeAlignmentAgent",
    "ReviewInputs",
    "RiskAdversaryAgent",
    "SpecialistAgent",
    "default_agent_registry",
]

AGENT_VERSION = "autonomous-agents-v1"

FORBIDDEN_AGENT_ACTIONS: tuple[str, ...] = (
    "execute_order",
    "modify_risk_limits",
    "modify_accounting",
    "modify_risk_engine",
    "escalate_permissions",
    "modify_portfolio",
)

#: Minimum research sample before any edge claim is treated as meaningful.
MIN_SAMPLE_TRADES = 200


@dataclass(frozen=True, slots=True)
class ReviewInputs:
    """Immutable packet handed to every agent (nothing can be modified)."""

    run_id: str
    decision_id: str
    asset: str
    symbol: str
    decision_time_ms: int
    regime: str | None
    bars_in_window: int
    data_quality: dict[str, Any]
    data_fingerprint: str
    window_end_ts: int
    context_issues: tuple[str, ...]
    admission: AdmissionEntry
    proposal: TradeProposal | None
    performance: StrategyPerformance | None = None
    min_sample_trades: int = MIN_SAMPLE_TRADES


@runtime_checkable
class SpecialistAgent(Protocol):
    """Contract every runtime agent satisfies."""

    @property
    def capability(self) -> AgentCapability: ...

    def review(self, inputs: ReviewInputs) -> AgentMessage | None: ...


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DataIntegrityAgent:
    """Audits the point-in-time integrity of the context the decision uses."""

    capability: AgentCapability = field(
        default_factory=lambda: AgentCapability(
            agent_id="data-integrity",
            capabilities=("inspect_data_integrity",),
            inputs=("asset_context", "ohlcv_window"),
            outputs=("AgentMessage",),
            permissions=("read_context",),
            forbidden_actions=FORBIDDEN_AGENT_ACTIONS,
        )
    )

    def review(self, inputs: ReviewInputs) -> AgentMessage:
        issues = list(inputs.context_issues)
        if inputs.window_end_ts > inputs.decision_time_ms:
            issues.append("future_bar_in_window")
        if not inputs.data_fingerprint:
            issues.append("missing_data_fingerprint")
        if inputs.bars_in_window <= 0:
            issues.append("empty_window")

        if issues:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.VETO,
                asset=inputs.asset,
                statement="context is not point-in-time safe; decision must fail closed",
                evidence=tuple(issues),
                confidence=0.95,
                payload={"bars_in_window": inputs.bars_in_window},
            )
        return AgentMessage(
            run_id=inputs.run_id,
            decision_id=inputs.decision_id,
            agent_id=self.capability.agent_id,
            review_type=ReviewType.OBSERVATION,
            asset=inputs.asset,
            statement="context is point-in-time safe",
            evidence=(
                f"fingerprint={inputs.data_fingerprint[:16]}",
                f"bars={inputs.bars_in_window}",
                f"window_end_ts={inputs.window_end_ts}<=decision_ts={inputs.decision_time_ms}",
            ),
            confidence=0.95,
            payload={"data_quality": dict(inputs.data_quality)},
        )


@dataclass(frozen=True, slots=True)
class CostEconomicsAgent:
    """Audits the economics: the proposal must be net-positive to be a trade."""

    capability: AgentCapability = field(
        default_factory=lambda: AgentCapability(
            agent_id="cost-economics",
            capabilities=("inspect_execution_cost",),
            inputs=("trade_proposal", "cost_breakdown"),
            outputs=("AgentMessage",),
            permissions=("read_costs",),
            forbidden_actions=FORBIDDEN_AGENT_ACTIONS,
        )
    )

    def review(self, inputs: ReviewInputs) -> AgentMessage | None:
        proposal = inputs.proposal
        if proposal is None:
            return None
        if proposal.expected_cost_bps <= 0:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.VETO,
                asset=inputs.asset,
                statement="zero/absent execution cost is not a valid cost model result",
                evidence=("expected_cost_bps<=0",),
                confidence=1.0,
            )
        if not proposal.cost.components:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.VETO,
                asset=inputs.asset,
                statement="cost breakdown is empty: cost model was not applied (§19)",
                evidence=("cost.components=[]",),
                confidence=1.0,
            )

        gross = proposal.expected_gross_edge_bps
        cost = proposal.expected_cost_bps
        net = proposal.expected_net_edge_bps
        economics = (
            f"gross={gross:.3f}bps cost={cost:.3f}bps net={net:.3f}bps "
            f"({proposal.cost.scenario_id}, spread {proposal.cost.spread_bps:.4f}bps "
            f"{proposal.cost.spread_knowledge})"
        )
        if net <= 0:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.CRITIQUE,
                asset=inputs.asset,
                statement="expected gross edge does not cover realistic execution cost",
                evidence=(economics,),
                counter_evidence=(f"break_even_bps={cost:.3f}",),
                confidence=0.9,
                payload={"classification": "COST_KILLED" if gross > 0 else "NO_GROSS_EDGE"},
            )
        return AgentMessage(
            run_id=inputs.run_id,
            decision_id=inputs.decision_id,
            agent_id=self.capability.agent_id,
            review_type=ReviewType.AGREEMENT,
            asset=inputs.asset,
            statement="expected gross edge covers realistic execution cost",
            evidence=(economics,),
            confidence=0.8,
        )


@dataclass(frozen=True, slots=True)
class EvidenceProvenanceAgent:
    """Audits that the expected edge has real research provenance."""

    capability: AgentCapability = field(
        default_factory=lambda: AgentCapability(
            agent_id="evidence-provenance",
            capabilities=("inspect_evidence_provenance",),
            inputs=("trade_proposal", "admission_ledger"),
            outputs=("AgentMessage",),
            permissions=("read_ledger",),
            forbidden_actions=FORBIDDEN_AGENT_ACTIONS,
        )
    )

    def review(self, inputs: ReviewInputs) -> AgentMessage | None:
        proposal = inputs.proposal
        if proposal is None:
            return None
        evidence = proposal.edge_evidence
        if not evidence.source_doc or not evidence.metric:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.VETO,
                asset=inputs.asset,
                statement="expected gross edge has no source document",
                evidence=("edge_evidence.source_doc empty",),
                confidence=1.0,
            )
        if evidence.sample_trades < inputs.min_sample_trades:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.CRITIQUE,
                asset=inputs.asset,
                statement="research sample is below the pre-registered minimum",
                evidence=(f"sample_trades={evidence.sample_trades}<{inputs.min_sample_trades}",),
                confidence=0.85,
            )
        admission_note = (
            f"admission={inputs.admission.status.value} "
            f"admitted_for_paper={inputs.admission.admitted_for_paper}"
        )
        if not inputs.admission.admitted_for_paper:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.CRITIQUE,
                asset=inputs.asset,
                statement="strategy is not admitted: PAPER execution is forbidden",
                evidence=(admission_note, f"source={evidence.source_doc}"),
                counter_evidence=(inputs.admission.rationale,),
                confidence=0.95,
                payload={"classification": "NOT_ADMITTED"},
            )
        return AgentMessage(
            run_id=inputs.run_id,
            decision_id=inputs.decision_id,
            agent_id=self.capability.agent_id,
            review_type=ReviewType.OBSERVATION,
            asset=inputs.asset,
            statement="strategy is admitted for PAPER with sourced evidence",
            evidence=(admission_note, f"source={evidence.source_doc}"),
            confidence=0.9,
        )


@dataclass(frozen=True, slots=True)
class RegimeAlignmentAgent:
    """Audits that the strategy matches the regime where it was researched."""

    capability: AgentCapability = field(
        default_factory=lambda: AgentCapability(
            agent_id="regime-alignment",
            capabilities=("inspect_regime_alignment",),
            inputs=("asset_context", "trade_proposal"),
            outputs=("AgentMessage",),
            permissions=("read_context",),
            forbidden_actions=FORBIDDEN_AGENT_ACTIONS,
        )
    )
    expected_regimes: tuple[str, ...] = ()

    def review(self, inputs: ReviewInputs) -> AgentMessage | None:
        if inputs.proposal is None:
            return None
        regime = inputs.regime or "UNKNOWN"
        if self.expected_regimes and regime not in self.expected_regimes:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.CRITIQUE,
                asset=inputs.asset,
                statement="current regime is outside the researched regime scope",
                evidence=(f"regime={regime} not in {list(self.expected_regimes)}",),
                confidence=0.7,
            )
        return AgentMessage(
            run_id=inputs.run_id,
            decision_id=inputs.decision_id,
            agent_id=self.capability.agent_id,
            review_type=ReviewType.AGREEMENT,
            asset=inputs.asset,
            statement="current regime is consistent with the strategy scope",
            evidence=(f"regime={regime}",),
            confidence=0.6,
        )


@dataclass(frozen=True, slots=True)
class RiskAdversaryAgent:
    """Adversarial review: tries to find a reason NOT to trade."""

    capability: AgentCapability = field(
        default_factory=lambda: AgentCapability(
            agent_id="risk-adversary",
            capabilities=("challenge_proposal",),
            inputs=("trade_proposal", "strategy_performance"),
            outputs=("AgentMessage",),
            permissions=("read_performance",),
            forbidden_actions=FORBIDDEN_AGENT_ACTIONS,
        )
    )

    def review(self, inputs: ReviewInputs) -> AgentMessage | None:
        if inputs.proposal is None:
            return None
        warnings: list[str] = []
        if inputs.admission.status is AdmissionStatus.UNKNOWN:
            warnings.append("strategy is unknown to the admission ledger (fail closed)")
        if inputs.performance is None:
            warnings.append("no realised outcome history for this strategy/asset/regime")
        elif inputs.performance.sample_size < inputs.min_sample_trades:
            warnings.append(f"realised sample below minimum ({inputs.performance.sample_size})")
        elif inputs.performance.net_expectancy_bps < 0:
            warnings.append(
                f"realised net expectancy is negative "
                f"({inputs.performance.net_expectancy_bps:.3f}bps)"
            )
        if inputs.admission.expected_gross_edge_bps is None:
            warnings.append("expected gross edge has no measured value")

        if not warnings:
            return AgentMessage(
                run_id=inputs.run_id,
                decision_id=inputs.decision_id,
                agent_id=self.capability.agent_id,
                review_type=ReviewType.AGREEMENT,
                asset=inputs.asset,
                statement="no adversarial finding against this proposal",
                evidence=("admission known", "realised sample adequate"),
                confidence=0.6,
            )
        return AgentMessage(
            run_id=inputs.run_id,
            decision_id=inputs.decision_id,
            agent_id=self.capability.agent_id,
            review_type=ReviewType.RISK_WARNING,
            asset=inputs.asset,
            statement="adversarial findings recorded (informational; risk stays deterministic)",
            evidence=tuple(warnings),
            confidence=0.75,
            payload={"warning_count": len(warnings)},
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AgentRegistry:
    """Capability-bounded registry of the runtime's specialist agents."""

    def __init__(self, agents: tuple[SpecialistAgent, ...] | None = None) -> None:
        self._agents: list[SpecialistAgent] = []
        if agents is None:
            agents = (
                DataIntegrityAgent(),
                CostEconomicsAgent(),
                EvidenceProvenanceAgent(),
                RegimeAlignmentAgent(),
                RiskAdversaryAgent(),
            )
        for agent in agents:
            self.register(agent)

    def register(self, agent: SpecialistAgent) -> None:
        """Register an agent, refusing forbidden capability declarations."""
        cap = agent.capability
        forbidden = sorted(set(cap.capabilities) & set(FORBIDDEN_AGENT_ACTIONS))
        if forbidden:
            raise ValueError(
                f"agent {cap.agent_id!r} declares forbidden capabilities: {forbidden} (§10)"
            )
        if cap.agent_id in {a.capability.agent_id for a in self._agents}:
            raise ValueError(f"duplicate agent_id {cap.agent_id!r}")
        self._agents.append(agent)

    def agent_ids(self) -> list[str]:
        return [a.capability.agent_id for a in self._agents]

    def capabilities(self) -> list[AgentCapability]:
        return [a.capability for a in self._agents]

    def review(self, inputs: ReviewInputs) -> tuple[AgentMessage, ...]:
        """Run every agent once; a failing agent yields a VETO, never silence."""
        messages: list[AgentMessage] = []
        for agent in self._agents:
            try:
                message = agent.review(inputs)
            except Exception as exc:  # a failing reviewer must fail closed
                message = AgentMessage(
                    run_id=inputs.run_id,
                    decision_id=inputs.decision_id,
                    agent_id=agent.capability.agent_id,
                    review_type=ReviewType.VETO,
                    asset=inputs.asset,
                    statement="agent raised an exception; decision must fail closed",
                    evidence=(f"{type(exc).__name__}: {exc}",),
                    confidence=1.0,
                )
            if message is not None:
                messages.append(message)
        return tuple(messages)


def default_agent_registry() -> AgentRegistry:
    return AgentRegistry()
