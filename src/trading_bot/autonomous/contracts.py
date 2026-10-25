"""Autonomous PAPER/SHADOW runtime — canonical contracts.

One vocabulary for the whole autonomous path:

    REAL MARKET DATA → context → router → TradeProposal → agent reviews
    → IndependentVerifier → DecisionEngine → deterministic Risk
    → TRADE_PAPER / SHADOW_TRADE / NO_TRADE → DecisionTrace
    → OutcomeRecord → StrategyPerformance

Design rules (§3/§4/§5 of AUTONOMOUS-PAPER-RUNTIME-V1):

* ``NO_TRADE`` is a first-class decision, never an error.
* ``SHADOW_TRADE`` never creates an order, never touches the portfolio and
  cannot be confused with PAPER: the mode is part of every persisted record.
* ``TRADE_PAPER`` requires a formally admitted PAPER_CANDIDATE strategy,
  an IndependentVerifier PASS and a deterministic Risk PASS/ADJUST.
* Evidence classes are explicit: a value is either OBSERVED (measured by us
  in this cycle), KNOWN (published), ESTIMATED (derived with a stated
  method) or ASSUMED (modelling choice). Never silent promotion.
* Every record is JSON-serialisable and carries its schema version so a
  replay can rebuild it exactly.

RESEARCH_ONLY: nothing here touches exchange execution or production risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "DECISION_CONTRACT_VERSION",
    "OUTCOME_SCHEMA_VERSION",
    "PAPER_AUTHORISING_STATUSES",
    "PAPER_PROMOTABLE_STATUSES",
    "PERFORMANCE_SCHEMA_VERSION",
    "SHADOW_ELIGIBLE_STATUSES",
    "TRACE_SCHEMA_VERSION",
    "AdmissionEntry",
    "AdmissionStatus",
    "AgentCapability",
    "AgentMessage",
    "CostBreakdown",
    "DecisionMode",
    "DecisionTrace",
    "EdgeEvidence",
    "NoTradeKind",
    "OutcomeRecord",
    "OutcomeStatus",
    "ReplayStatus",
    "ReviewType",
    "RiskReview",
    "RiskState",
    "RiskVerdict",
    "RuntimeFailureKind",
    "ShadowTradeDecision",
    "StrategyPerformance",
    "TradeProposal",
    "VerificationCheck",
    "VerificationResult",
    "VerifierVerdict",
]

DECISION_CONTRACT_VERSION = "autonomous-decision-v1"
TRACE_SCHEMA_VERSION = "decision-trace-v1"
OUTCOME_SCHEMA_VERSION = "outcome-record-v1"
PERFORMANCE_SCHEMA_VERSION = "strategy-performance-v1"
AGENT_CAPABILITY_SCHEMA_VERSION = "agent-capability-v1"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DecisionMode(StrEnum):
    """First-class decision outcomes. ``NO_TRADE`` is never a failure."""

    TRADE_PAPER = "TRADE_PAPER"
    SHADOW_TRADE = "SHADOW_TRADE"
    NO_TRADE = "NO_TRADE"


class ReviewType(StrEnum):
    """Structured multi-agent communication vocabulary (§10).

    Free chat is NOT a contract: every message between components is one of
    these typed reviews.
    """

    OBSERVATION = "OBSERVATION"
    PROPOSAL = "PROPOSAL"
    CRITIQUE = "CRITIQUE"
    COUNTERPROPOSAL = "COUNTERPROPOSAL"
    RISK_WARNING = "RISK_WARNING"
    VETO = "VETO"
    AGREEMENT = "AGREEMENT"
    DECISION = "DECISION"


class AdmissionStatus(StrEnum):
    """Formal lifecycle state of one strategy (research → paper → archive) (§17).

    The operational states are ``RESEARCH_REQUIRED`` / ``PAPER_CANDIDATE`` /
    ``PAPER_ACTIVE`` / ``PAPER_RETIRED`` / ``REJECTED``; the remaining values are
    the research verdicts that justify them. There is deliberately no ``LIVE``
    member and no transition that creates one: PAPER can never promote itself,
    and the vocabulary cannot even name the state it would have to reach.
    """

    # -- operational lifecycle -------------------------------------------------
    RESEARCH_REQUIRED = "RESEARCH_REQUIRED"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    PAPER_ACTIVE = "PAPER_ACTIVE"
    PAPER_RETIRED = "PAPER_RETIRED"
    REJECTED = "REJECTED"
    # -- research verdicts (why the lifecycle looks the way it does) -----------
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    COST_KILLED = "COST_KILLED"
    NO_GROSS_EDGE = "NO_GROSS_EDGE"
    UNKNOWN = "UNKNOWN"


class VerifierVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class RiskVerdict(StrEnum):
    """Deterministic risk review for the autonomous path (§12)."""

    PASS = "PASS"
    ADJUST = "ADJUST"
    VETO = "VETO"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RiskState(StrEnum):
    """Observable risk outcome for ONE decision (§12).

    These are the states a trace may carry. ``NOT_EVALUATED`` exists so that a
    verdict nobody actually produced can never be read as a pass: a PASS that
    did not come from a real ``RiskManager.check_signal`` run is reported as
    ``NOT_EVALUATED``, never as ``APPROVED``.
    """

    APPROVED = "APPROVED"
    VETOED = "VETOED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


class NoTradeKind(StrEnum):
    """Why a NO_TRADE happened — the honest NO_TRADE classes (§4).

    An operational failure (provider outage, adapter error, internal error) is
    NOT one of these: see ``RuntimeFailureKind``. Mixing the two would turn an
    incident into a fake trading decision.

    A universe exclusion is the mirror-image mistake and is kept apart too
    (DEF-WP00-01): when the scanner's deterministic filters leave an asset
    inactive, the runtime *chose* not to evaluate it, so the record says so
    instead of reporting the missing bars as if the market had been unreadable.
    """

    NO_TRADE_STRATEGIC = "NO_TRADE_STRATEGIC"
    NO_TRADE_RISK = "NO_TRADE_RISK"
    NO_TRADE_DATA = "NO_TRADE_DATA"
    NO_TRADE_UNIVERSE = "NO_TRADE_UNIVERSE"
    NO_TRADE_CONFLICT = "NO_TRADE_CONFLICT"


class RuntimeFailureKind(StrEnum):
    """Operational failures. Never a decision, never a measurable hypothesis."""

    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_DATA = "INVALID_DATA"
    ADAPTER_FAILURE = "ADAPTER_FAILURE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class OutcomeStatus(StrEnum):
    RESOLVED = "RESOLVED"
    PENDING_OUTCOME = "PENDING_OUTCOME"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReplayStatus(StrEnum):
    """Honest replay coverage for one decision (§17).

    ``FULL``          every artefact the decision produced is reconstructed,
                      including its resolved outcome;
    ``PARTIAL``       the decision is fully reconstructed but its horizon has
                      not closed yet (no outcome exists to replay);
    ``NOT_AVAILABLE`` at least one invariant failed, or the record is absent.
    """

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"


#: Admission statuses that authorise PAPER execution.
#:
#: ``PAPER_CANDIDATE`` is the state a strategy is *admitted* in and
#: ``PAPER_ACTIVE`` is the state it runs in, so both authorise PAPER. Nothing
#: else does: a research verdict, however promising, cannot trade.
PAPER_AUTHORISING_STATUSES: frozenset[AdmissionStatus] = frozenset(
    {AdmissionStatus.PAPER_CANDIDATE, AdmissionStatus.PAPER_ACTIVE}
)

#: §17 — the only status a strategy may be *promoted to* by an explicit record.
PAPER_PROMOTABLE_STATUSES: frozenset[AdmissionStatus] = frozenset(
    {AdmissionStatus.PAPER_CANDIDATE}
)

#: Statuses that may still be observed in SHADOW (research interest only).
SHADOW_ELIGIBLE_STATUSES: frozenset[AdmissionStatus] = frozenset(
    {
        AdmissionStatus.PAPER_CANDIDATE,
        AdmissionStatus.RESEARCH_CANDIDATE,
        AdmissionStatus.RESEARCH_REQUIRED,
        AdmissionStatus.COST_KILLED,
        AdmissionStatus.NO_GROSS_EDGE,
        AdmissionStatus.REJECTED,
        AdmissionStatus.PAPER_RETIRED,
    }
)


@dataclass(frozen=True, slots=True)
class AdmissionEntry:
    """One strategy's formal admission verdict, with its evidence."""

    strategy_id: str
    family: str
    status: AdmissionStatus
    admitted_for_paper: bool
    expected_gross_edge_bps: float | None
    edge_evidence: EdgeEvidence | None
    source_doc: str
    rationale: str
    timeframe: str = "5m"
    known: bool = True

    def __post_init__(self) -> None:
        if self.admitted_for_paper and self.status not in PAPER_AUTHORISING_STATUSES:
            raise ValueError(
                f"{self.strategy_id}: admitted_for_paper requires one of "
                f"{sorted(s.value for s in PAPER_AUTHORISING_STATUSES)} "
                f"(got {self.status.value})"
            )
        if self.admitted_for_paper and self.edge_evidence is None:
            raise ValueError(
                f"{self.strategy_id}: PAPER admission without edge evidence is forbidden"
            )
        if self.admitted_for_paper and (
            self.expected_gross_edge_bps is None or self.expected_gross_edge_bps <= 0
        ):
            raise ValueError(f"{self.strategy_id}: PAPER admission requires positive gross edge")
        # §17 — the lifecycle itself is an invariant, not a convention: an active
        # strategy must be admitted, and a retired one must not be trading.
        if self.status is AdmissionStatus.PAPER_ACTIVE and not self.admitted_for_paper:
            raise ValueError(
                f"{self.strategy_id}: PAPER_ACTIVE requires admitted_for_paper=True "
                "(a strategy cannot be active without an admission)"
            )
        if self.status is AdmissionStatus.PAPER_RETIRED and self.admitted_for_paper:
            raise ValueError(
                f"{self.strategy_id}: PAPER_RETIRED cannot be admitted for paper"
            )

    @property
    def shadow_eligible(self) -> bool:
        """A non-admitted but researched strategy may be observed in SHADOW."""
        return not self.admitted_for_paper and (
            self.status in SHADOW_ELIGIBLE_STATUSES and self.expected_gross_edge_bps is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "family": self.family,
            "status": self.status.value,
            "admitted_for_paper": self.admitted_for_paper,
            "expected_gross_edge_bps": self.expected_gross_edge_bps,
            "edge_evidence": None if self.edge_evidence is None else self.edge_evidence.to_dict(),
            "source_doc": self.source_doc,
            "rationale": self.rationale,
            "timeframe": self.timeframe,
            "known": self.known,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AdmissionEntry:
        data = dict(payload)
        data["status"] = AdmissionStatus(data["status"])
        evidence = data.get("edge_evidence")
        data["edge_evidence"] = None if evidence is None else EdgeEvidence(**evidence)
        return cls(**data)


# ---------------------------------------------------------------------------
# Agent contracts (§10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentCapability:
    """Declared capability surface of one runtime agent.

    ``forbidden_actions`` is part of the contract, not documentation: the
    runtime refuses to build an agent that claims a forbidden capability.
    """

    agent_id: str
    capabilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = (
        "execute_order",
        "modify_risk_limits",
        "modify_accounting",
        "modify_risk_engine",
        "escalate_permissions",
        "modify_portfolio",
    )
    schema_version: str = AGENT_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id must be non-empty")
        overlap = set(self.capabilities) & set(self.forbidden_actions)
        if overlap:
            raise ValueError(
                f"agent {self.agent_id!r} declares forbidden capabilities: {sorted(overlap)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capabilities": list(self.capabilities),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "forbidden_actions": list(self.forbidden_actions),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """One structured review emitted by an agent about one proposal."""

    run_id: str
    decision_id: str
    agent_id: str
    review_type: ReviewType
    asset: str
    statement: str
    evidence: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    @property
    def is_veto(self) -> bool:
        return self.review_type is ReviewType.VETO

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "agent_id": self.agent_id,
            "review_type": self.review_type.value,
            "asset": self.asset,
            "statement": self.statement,
            "evidence": list(self.evidence),
            "counter_evidence": list(self.counter_evidence),
            "confidence": round(self.confidence, 6),
            "payload": self.payload,
        }


# ---------------------------------------------------------------------------
# Cost / edge evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """All-in round-trip cost with per-component knowledge classes (§11)."""

    scenario_id: str
    cost_model_version: str
    size_usd: float
    horizon_minutes: float
    spread_bps: float
    spread_knowledge: str
    fee_bps: float
    slippage_bps: float
    impact_bps: float
    funding_bps: float
    round_trip_bps: float
    components: tuple[dict[str, Any], ...] = ()
    created_at_ms: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CostBreakdown:
        data = dict(payload)
        data["components"] = tuple(dict(c) for c in data.get("components") or ())
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "cost_model_version": self.cost_model_version,
            "size_usd": round(self.size_usd, 8),
            "horizon_minutes": round(self.horizon_minutes, 6),
            "spread_bps": round(self.spread_bps, 8),
            "spread_knowledge": self.spread_knowledge,
            "fee_bps": round(self.fee_bps, 8),
            "slippage_bps": round(self.slippage_bps, 8),
            "impact_bps": round(self.impact_bps, 8),
            "funding_bps": round(self.funding_bps, 8),
            "round_trip_bps": round(self.round_trip_bps, 8),
            "components": [dict(c) for c in self.components],
            "created_at_ms": self.created_at_ms,
        }


@dataclass(frozen=True, slots=True)
class EdgeEvidence:
    """Provenance of the expected gross edge (never invented in-cycle).

    A HISTORICAL_ESTIMATE is a research measurement, not a promise: it carries
    its source, the sample it was measured on, the period it covers, the
    timeframe it belongs to and the status it earned. It is used ONLY as the
    prior of a candidate — never as a universal statement about future return.
    """

    source_doc: str
    metric: str
    value_bps: float
    knowledge: str
    sample_trades: int
    note: str = ""
    evidence_class: str = "HISTORICAL_ESTIMATE"
    period: str = ""
    timeframe: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        if not self.source_doc:
            raise ValueError("edge evidence must name its source document")
        if not self.metric:
            raise ValueError("edge evidence must name its metric")

    @property
    def is_historical_estimate(self) -> bool:
        return self.evidence_class == "HISTORICAL_ESTIMATE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_doc": self.source_doc,
            "metric": self.metric,
            "value_bps": round(self.value_bps, 8),
            "knowledge": self.knowledge,
            "sample_trades": self.sample_trades,
            "note": self.note,
            "evidence_class": self.evidence_class,
            "period": self.period,
            "timeframe": self.timeframe,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """A candidate trade with its full economics and provenance.

    No proposal may exist without expected gross edge, expected cost and
    expected net edge — a proposal without economics is a contract error.
    """

    run_id: str
    decision_id: str
    asset: str
    symbol: str
    strategy_id: str
    strategy_version: str
    family: str
    direction: str
    timeframe: str
    market_time_ms: int
    decision_time_ms: int
    entry_reference: float
    structural_stop: float | None
    horizon_minutes: float
    expected_gross_edge_bps: float
    expected_cost_bps: float
    expected_net_edge_bps: float
    cost: CostBreakdown
    edge_evidence: EdgeEvidence
    admission_status: AdmissionStatus
    regime: str | None = None
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    context_fingerprint: str = ""
    contract_version: str = DECISION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError(f"proposal direction must be LONG/SHORT, got {self.direction!r}")
        if self.market_time_ms > self.decision_time_ms:
            raise ValueError(
                "point-in-time violation: market_time_ms > decision_time_ms "
                f"({self.market_time_ms} > {self.decision_time_ms})"
            )
        if self.entry_reference <= 0:
            raise ValueError("entry_reference must be > 0")
        if self.expected_cost_bps < 0:
            raise ValueError("expected_cost_bps must be >= 0")
        if not self.evidence:
            raise ValueError("a proposal without evidence is not a proposal (§19)")
        expected_net = self.expected_gross_edge_bps - self.expected_cost_bps
        if abs(expected_net - self.expected_net_edge_bps) > 1e-6:
            raise ValueError(
                "expected_net_edge_bps must equal gross - cost "
                f"({expected_net!r} != {self.expected_net_edge_bps!r})"
            )

    @property
    def cost_survives(self) -> bool:
        return self.expected_net_edge_bps > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "asset": self.asset,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "family": self.family,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "market_time_ms": self.market_time_ms,
            "decision_time_ms": self.decision_time_ms,
            "entry_reference": self.entry_reference,
            "structural_stop": self.structural_stop,
            "horizon_minutes": self.horizon_minutes,
            "expected_gross_edge_bps": round(self.expected_gross_edge_bps, 8),
            "expected_cost_bps": round(self.expected_cost_bps, 8),
            "expected_net_edge_bps": round(self.expected_net_edge_bps, 8),
            "cost": self.cost.to_dict(),
            "edge_evidence": self.edge_evidence.to_dict(),
            "admission_status": self.admission_status.value,
            "regime": self.regime,
            "confidence": round(self.confidence, 6),
            "evidence": list(self.evidence),
            "counter_evidence": list(self.counter_evidence),
            "context_fingerprint": self.context_fingerprint,
            "contract_version": self.contract_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TradeProposal:
        """Rebuild a proposal from ``to_dict`` output (replay contract)."""
        data = dict(payload)
        data["cost"] = CostBreakdown.from_dict(data["cost"])
        data["edge_evidence"] = EdgeEvidence(**data["edge_evidence"])
        data["admission_status"] = AdmissionStatus(data["admission_status"])
        data["evidence"] = tuple(data.get("evidence") or ())
        data["counter_evidence"] = tuple(data.get("counter_evidence") or ())
        return cls(**data)


# ---------------------------------------------------------------------------
# Verification / risk / decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Output of the IndependentVerifier (BUILDER != VERIFIER)."""

    decision_id: str
    verdict: VerifierVerdict
    checks: tuple[VerificationCheck, ...] = ()
    failures: tuple[str, ...] = ()
    verifier_version: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict is VerifierVerdict.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "failures": list(self.failures),
            "verifier_version": self.verifier_version,
        }


@dataclass(frozen=True, slots=True)
class RiskReview:
    """Deterministic risk review result recorded in the trace (§12).

    ``advisory=True`` marks a review the runtime ran on a decision that can NOT
    produce an order (SHADOW / NO_TRADE with a proposal): the SAME
    ``RiskManager.check_signal`` is consulted, so the trace says what risk would
    have said, but the verdict is informative only and can never authorise or
    block anything. The DecisionEngine refuses to accept an advisory review on an
    order-authorising packet, so an advisory verdict can never be mistaken for a
    gate.
    """

    verdict: RiskVerdict
    reason: str = ""
    notional_usdt: float | None = None
    source: str = "RiskManager.check_signal"
    advisory: bool = False
    #: True only when ``RiskManager.check_signal`` actually ran for this packet.
    #: A verdict that was never produced can never be reported as a pass.
    evaluated: bool = False
    #: The risk rule that decided the verdict (e.g. ``kill_switch``,
    #: ``position_sizing``, ``max_drawdown``). Empty when not evaluated.
    rule: str = ""
    #: The exact inputs handed to the engine, so the verdict is reproducible.
    inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evaluated:
            if self.verdict is RiskVerdict.NOT_APPLICABLE:
                raise ValueError("an evaluated risk review cannot be NOT_APPLICABLE")
            if not self.rule:
                raise ValueError("an evaluated risk review must name the rule it applied")
        if self.verdict is RiskVerdict.VETO and not self.reason:
            raise ValueError("a risk veto must state its reason")

    @property
    def state(self) -> RiskState:
        """The observable state — never a fake PASS (§12)."""
        if self.verdict is RiskVerdict.VETO:
            return RiskState.VETOED
        if not self.evaluated:
            return (
                RiskState.NOT_APPLICABLE
                if self.verdict is RiskVerdict.NOT_APPLICABLE
                else RiskState.NOT_EVALUATED
            )
        return RiskState.APPROVED  # PASS / ADJUST produced by a real run

    @property
    def binding(self) -> bool:
        """A binding review may gate an order; an advisory one cannot (§12)."""
        return not self.advisory

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "state": self.state.value,
            "risk_evaluated": self.evaluated,
            "risk_result": self.state.value,
            "risk_rule": self.rule,
            "risk_reason": self.reason,
            "risk_inputs": self.inputs,
            "reason": self.reason,
            "notional_usdt": self.notional_usdt,
            "source": self.source,
            "advisory": self.advisory,
            "binding": self.binding,
        }


@dataclass(frozen=True, slots=True)
class ShadowTradeDecision:
    """Explicit shadow decision contract (§4).

    A SHADOW_TRADE creates no order, changes no portfolio and consumes no
    capital. It exists so the system can observe and learn from research
    candidates that are not admitted to paper execution.
    """

    run_id: str
    decision_id: str
    timestamp_ms: int
    asset: str
    strategy_id: str
    strategy_version: str
    direction: str
    hypothetical_entry: float
    expected_edge_bps: float
    expected_cost_bps: float
    expected_net_edge_bps: float
    regime: str | None
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    confidence: float
    rejection_reason: str
    admission_status: AdmissionStatus
    decision_time_ms: int
    marked_shadow: bool = True

    def __post_init__(self) -> None:
        if not self.marked_shadow:
            raise ValueError("a ShadowTradeDecision must be explicitly marked SHADOW (§4)")
        if self.decision_time_ms > self.timestamp_ms:
            raise ValueError("point-in-time violation: decision_time_ms > timestamp_ms")

    @property
    def is_shadow(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "timestamp_ms": self.timestamp_ms,
            "asset": self.asset,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "direction": self.direction,
            "hypothetical_entry": self.hypothetical_entry,
            "expected_edge_bps": round(self.expected_edge_bps, 8),
            "expected_cost_bps": round(self.expected_cost_bps, 8),
            "expected_net_edge_bps": round(self.expected_net_edge_bps, 8),
            "regime": self.regime,
            "evidence": list(self.evidence),
            "counter_evidence": list(self.counter_evidence),
            "confidence": round(self.confidence, 6),
            "rejection_reason": self.rejection_reason,
            "admission_status": self.admission_status.value,
            "decision_time_ms": self.decision_time_ms,
            "marked_shadow": self.marked_shadow,
            "mode": DecisionMode.SHADOW_TRADE.value,
        }


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """Persistent, replayable record of one decision (§5)."""

    run_id: str
    decision_id: str
    asset: str
    symbol: str
    market_time_ms: int
    decision_time_ms: int
    mode: DecisionMode
    reason: str
    classification: str
    regime: str | None
    strategies_considered: tuple[dict[str, Any], ...]
    market_context: dict[str, Any]
    asset_context: dict[str, Any]
    proposal: dict[str, Any] | None
    agent_messages: tuple[dict[str, Any], ...]
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    verification: dict[str, Any]
    risk: dict[str, Any]
    shadow: dict[str, Any] | None
    cost_model_version: str
    order_created: bool
    orders_created: int
    #: One of ``NoTradeKind`` when the decision was a NO_TRADE. ``None`` for
    #: TRADE_PAPER / SHADOW_TRADE. An operational failure is NOT a NO_TRADE
    #: and is reported through ``errors`` instead (§4).
    no_trade_kind: str | None = None
    errors: tuple[str, ...] = ()
    sequence: int = 0
    prev_hash: str = ""
    trace_hash: str = ""
    schema_version: str = TRACE_SCHEMA_VERSION
    created_at_ms: int = 0

    def __post_init__(self) -> None:
        if self.mode is DecisionMode.SHADOW_TRADE and self.order_created:
            raise ValueError("SHADOW_TRADE must never create an order (§4)")
        if self.mode is DecisionMode.NO_TRADE and self.order_created:
            raise ValueError("NO_TRADE must never create an order")
        if self.decision_time_ms < self.market_time_ms:
            raise ValueError("point-in-time violation: decision_time_ms < market_time_ms")
        if self.mode is DecisionMode.SHADOW_TRADE and not self.shadow:
            raise ValueError("SHADOW_TRADE trace must carry the shadow decision contract")
        if self.no_trade_kind is not None:
            if self.mode is not DecisionMode.NO_TRADE:
                raise ValueError("only a NO_TRADE trace may carry a no_trade_kind")
            if self.no_trade_kind not in {k.value for k in NoTradeKind}:
                raise ValueError(f"unknown no_trade_kind {self.no_trade_kind!r}")
            if self.no_trade_kind in {
                NoTradeKind.NO_TRADE_DATA.value,
                NoTradeKind.NO_TRADE_UNIVERSE.value,
            } and self.proposal is not None:
                # A DATA no-decision means there was nothing usable to reason
                # about, and a universe exclusion means the asset never reached
                # a strategy: neither can carry a trade proposal.
                raise ValueError(
                    f"a {self.no_trade_kind} decision cannot carry a trade proposal"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "asset": self.asset,
            "symbol": self.symbol,
            "market_time_ms": self.market_time_ms,
            "decision_time_ms": self.decision_time_ms,
            "mode": self.mode.value,
            "reason": self.reason,
            "classification": self.classification,
            "regime": self.regime,
            "strategies_considered": [dict(s) for s in self.strategies_considered],
            "market_context": self.market_context,
            "asset_context": self.asset_context,
            "proposal": self.proposal,
            "agent_messages": [dict(m) for m in self.agent_messages],
            "evidence": list(self.evidence),
            "counter_evidence": list(self.counter_evidence),
            "verification": self.verification,
            "risk": self.risk,
            "shadow": self.shadow,
            "cost_model_version": self.cost_model_version,
            "order_created": self.order_created,
            "orders_created": self.orders_created,
            "no_trade_kind": self.no_trade_kind,
            "errors": list(self.errors),
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "trace_hash": self.trace_hash,
            "schema_version": self.schema_version,
            "created_at_ms": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DecisionTrace:
        data = dict(payload)
        data["mode"] = DecisionMode(data["mode"])
        data["strategies_considered"] = tuple(data.get("strategies_considered") or ())
        data["agent_messages"] = tuple(data.get("agent_messages") or ())
        data["evidence"] = tuple(data.get("evidence") or ())
        data["counter_evidence"] = tuple(data.get("counter_evidence") or ())
        data["errors"] = tuple(data.get("errors") or ())
        return cls(**data)


# ---------------------------------------------------------------------------
# Outcome / experience
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """Post-decision evaluation of one decision (§6).

    Temporal contract (hard, validated):

        reference_price_time_ms <= decision_time_ms < outcome_time_ms

    ``reference_price_time_ms`` is when the entry reference became OBSERVABLE
    (the close of the bar it was read from) and ``outcome_time_ms`` — also
    exposed as ``future_price_time_ms`` — is the close of the bar that carries
    the horizon's outcome. A bar is never used before it closes, so the
    outcome can never contain information the decision could already see.

    ``outcome_key`` (``<decision_id>@<horizon>``) is the stable identity used
    to make PENDING → RESOLVED idempotent: the same decision and horizon can
    only ever produce one outcome.
    """

    run_id: str
    decision_id: str
    asset: str
    symbol: str
    strategy_id: str
    mode: DecisionMode
    direction: str
    decision_time_ms: int
    outcome_time_ms: int
    horizon_minutes: float
    entry_reference: float
    outcome_price: float
    gross_return_bps: float
    estimated_cost_bps: float
    net_hypothetical_bps: float
    mfe_bps: float
    mae_bps: float
    direction_correct: bool
    regime: str | None = None
    data_complete: bool = True
    status: OutcomeStatus = OutcomeStatus.RESOLVED
    bars_observed: int = 0
    market_time_ms: int = 0
    reference_price_time_ms: int = 0
    schema_version: str = OUTCOME_SCHEMA_VERSION
    created_at_ms: int = 0

    def __post_init__(self) -> None:
        if self.outcome_time_ms <= self.decision_time_ms:
            raise ValueError(
                "anti-lookahead: outcome_time_ms must be > decision_time_ms "
                f"({self.outcome_time_ms} <= {self.decision_time_ms})"
            )
        if self.reference_price_time_ms > self.decision_time_ms:
            raise ValueError(
                "anti-lookahead: reference_price_time_ms must be <= decision_time_ms "
                f"({self.reference_price_time_ms} > {self.decision_time_ms})"
            )
        if self.market_time_ms > self.decision_time_ms:
            raise ValueError(
                "anti-lookahead: market_time_ms must be <= decision_time_ms "
                f"({self.market_time_ms} > {self.decision_time_ms})"
            )
        if self.entry_reference <= 0 or self.outcome_price <= 0:
            raise ValueError("prices must be > 0")

    @property
    def is_paper_result(self) -> bool:
        return self.mode is DecisionMode.TRADE_PAPER

    @property
    def future_price_time_ms(self) -> int:
        """Alias of ``outcome_time_ms``: when the future price was observable."""
        return self.outcome_time_ms

    @property
    def outcome_key(self) -> str:
        """Stable idempotency key: one decision + one horizon ⇒ one outcome."""
        return f"{self.decision_id}@{self.horizon_minutes:g}m"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "outcome_key": self.outcome_key,
            "asset": self.asset,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "mode": self.mode.value,
            "direction": self.direction,
            "decision_time_ms": self.decision_time_ms,
            "market_time_ms": self.market_time_ms,
            "outcome_time_ms": self.outcome_time_ms,
            "future_price_time_ms": self.future_price_time_ms,
            "reference_price_time_ms": self.reference_price_time_ms,
            "horizon_minutes": self.horizon_minutes,
            "entry_reference": self.entry_reference,
            "outcome_price": self.outcome_price,
            "gross_return_bps": round(self.gross_return_bps, 8),
            "estimated_cost_bps": round(self.estimated_cost_bps, 8),
            "net_hypothetical_bps": round(self.net_hypothetical_bps, 8),
            "mfe_bps": round(self.mfe_bps, 8),
            "mae_bps": round(self.mae_bps, 8),
            "direction_correct": self.direction_correct,
            "regime": self.regime,
            "data_complete": self.data_complete,
            "status": self.status.value,
            "bars_observed": self.bars_observed,
            "schema_version": self.schema_version,
            "created_at_ms": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OutcomeRecord:
        data = dict(payload)
        data["mode"] = DecisionMode(data["mode"])
        data["status"] = OutcomeStatus(data["status"])
        # Derived on read: never trusted from the persisted payload.
        data.pop("outcome_key", None)
        data.pop("future_price_time_ms", None)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class StrategyPerformance:
    """Evidence-based track record for one (strategy, asset, regime) cell (§7).

    This record may influence router SELECTION only. It can never modify
    risk limits, sizing, capital, accounting or admission thresholds.
    """

    strategy_id: str
    asset: str
    regime: str
    timeframe: str
    sample_size: int
    shadow_sample_size: int
    paper_sample_size: int
    no_trade_sample_size: int
    gross_expectancy_bps: float
    net_expectancy_bps: float
    hit_rate: float
    profit_factor: float | None
    max_drawdown_bps: float
    recent_net_expectancy_bps: float
    historical_net_expectancy_bps: float
    confidence: float
    last_updated_ms: int
    schema_version: str = PERFORMANCE_SCHEMA_VERSION

    @property
    def key(self) -> str:
        return f"{self.strategy_id}|{self.asset}|{self.regime}|{self.timeframe}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "asset": self.asset,
            "regime": self.regime,
            "timeframe": self.timeframe,
            "sample_size": self.sample_size,
            "shadow_sample_size": self.shadow_sample_size,
            "paper_sample_size": self.paper_sample_size,
            "no_trade_sample_size": self.no_trade_sample_size,
            "gross_expectancy_bps": round(self.gross_expectancy_bps, 8),
            "net_expectancy_bps": round(self.net_expectancy_bps, 8),
            "hit_rate": round(self.hit_rate, 8),
            "profit_factor": None if self.profit_factor is None else round(self.profit_factor, 8),
            "max_drawdown_bps": round(self.max_drawdown_bps, 8),
            "recent_net_expectancy_bps": round(self.recent_net_expectancy_bps, 8),
            "historical_net_expectancy_bps": round(self.historical_net_expectancy_bps, 8),
            "confidence": round(self.confidence, 8),
            "last_updated_ms": self.last_updated_ms,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StrategyPerformance:
        return cls(**payload)
