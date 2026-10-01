"""Typed contracts for the dynamic strategy ecosystem (RFC-STRAT-013/014).

One vocabulary for the whole plane:

    descriptor → performance (context-keyed) → health → lifecycle decision
    → router eligibility → portfolio arbitration → champion/challenger

Design rules:

* Every state change is a closed-graph edge. An edge that is not in
  :data:`STATE_TRANSITIONS` does not exist.
* ``PAUSED → ACTIVE`` and ``CANDIDATE → ACTIVE`` are impossible by construction.
* ``LIVE`` is not in :class:`ExecutionMode`'s *reachable* subset and the
  lifecycle has no live state; the module refuses at import time to build a
  graph that would reach one.
* Every record is JSON-serialisable and carries its schema version, so a
  replay can rebuild it exactly and a report can cite it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

__all__ = [
    "CONTRACTS_SCHEMA_VERSION",
    "EVIDENCE_REQUIRED_EDGES",
    "FORBIDDEN_EXECUTION_MODES",
    "STATE_TRANSITIONS",
    "ContextKey",
    "ExecutionMode",
    "HealthReport",
    "HealthState",
    "LifecycleDecision",
    "LifecycleState",
    "LifecycleStateError",
    "PerformanceCell",
    "PortfolioDecision",
    "PromotionRecord",
    "RationaleCode",
    "StrategyDescriptor",
    "StrategyEvent",
    "assert_no_future_data",
    "assert_transition",
    "can_transition",
    "describe_transition",
]

CONTRACTS_SCHEMA_VERSION: Final[str] = "strategy-lifecycle-contracts-v1"


class LifecycleStateError(RuntimeError):
    """Raised when a lifecycle transition is not authorised."""


class ExecutionMode(StrEnum):
    """Provenance tag for where a result came from (§12).

    ``LIVE`` exists only so the provenance vocabulary is complete; it is in
    :data:`FORBIDDEN_EXECUTION_MODES` and no component in this package may
    emit it. A SHADOW result can therefore never be mistaken for a PAPER one,
    which is what makes "shadow leaked into execution" a test, not a hope.
    """

    LIVE = "LIVE"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"


#: Modes this package must never produce. Constructing a result with one of
#: these raises — there is no code path that legitimately reaches them here.
FORBIDDEN_EXECUTION_MODES: Final[frozenset[ExecutionMode]] = frozenset(
    {ExecutionMode.LIVE}
)


class LifecycleState(StrEnum):
    """The dynamic lifecycle (§5). A superset of the ledger's ``AdmissionStatus``.

    This state governs routing eligibility and shadow/observation. It does NOT
    grant execution authority: only the admission ledger (``PAPER_ACTIVE``)
    plus IndependentVerifier plus the RiskManager can authorise an order.
    """

    DISCOVERED = "DISCOVERED"
    CANDIDATE = "CANDIDATE"
    VALIDATING = "VALIDATING"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    ELIGIBLE = "ELIGIBLE"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    THROTTLED = "THROTTLED"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


#: The complete transition graph (§5). ``{x}`` self-edges mean "stay put".
STATE_TRANSITIONS: Final[dict[LifecycleState, frozenset[LifecycleState]]] = {
    LifecycleState.DISCOVERED: frozenset(
        {LifecycleState.DISCOVERED, LifecycleState.CANDIDATE, LifecycleState.RETIRED}
    ),
    LifecycleState.CANDIDATE: frozenset(
        {LifecycleState.CANDIDATE, LifecycleState.VALIDATING, LifecycleState.RETIRED}
    ),
    LifecycleState.VALIDATING: frozenset(
        {
            LifecycleState.VALIDATING,
            LifecycleState.PAPER,
            LifecycleState.SHADOW,
            LifecycleState.CANDIDATE,
            LifecycleState.RETIRED,
        }
    ),
    LifecycleState.PAPER: frozenset(
        {LifecycleState.PAPER, LifecycleState.SHADOW, LifecycleState.RETIRED}
    ),
    # SHADOW is where challengers live. It may become ELIGIBLE (earned), go back
    # to PAPER (a validated promotion path) or be paused.
    LifecycleState.SHADOW: frozenset(
        {
            LifecycleState.SHADOW,
            LifecycleState.ELIGIBLE,
            LifecycleState.PAPER,
            LifecycleState.PAUSED,
            LifecycleState.RETIRED,
        }
    ),
    # ELIGIBLE is the one pre-ACTIVE state. From here a policy decision may
    # activate, or send the strategy back to SHADOW/PAUSED.
    LifecycleState.ELIGIBLE: frozenset(
        {
            LifecycleState.ELIGIBLE,
            LifecycleState.ACTIVE,
            LifecycleState.SHADOW,
            LifecycleState.PAUSED,
            LifecycleState.RETIRED,
        }
    ),
    # ACTIVE degrades or pauses; it never jumps to ELIGIBLE without evidence.
    LifecycleState.ACTIVE: frozenset(
        {
            LifecycleState.ACTIVE,
            LifecycleState.DEGRADED,
            LifecycleState.PAUSED,
            LifecycleState.RETIRED,
        }
    ),
    # {ACTIVE, DEGRADED, THROTTLED} form one "active lineage": a strategy that
    # never left ACTIVE may recover within it once the health returns. Leaving
    # the lineage (-> SHADOW / PAUSED) always requires re-earning evidence.
    LifecycleState.DEGRADED: frozenset(
        {
            LifecycleState.DEGRADED,
            LifecycleState.ACTIVE,
            LifecycleState.THROTTLED,
            LifecycleState.PAUSED,
            LifecycleState.SHADOW,
            LifecycleState.RETIRED,
        }
    ),
    LifecycleState.THROTTLED: frozenset(
        {
            LifecycleState.THROTTLED,
            LifecycleState.ACTIVE,
            LifecycleState.DEGRADED,
            LifecycleState.PAUSED,
            LifecycleState.SHADOW,
            LifecycleState.RETIRED,
        }
    ),
    # PAUSED may only recover through SHADOW (or be retired). PAUSED → ACTIVE
    # does not exist: reactivation must re-earn evidence.
    LifecycleState.PAUSED: frozenset(
        {LifecycleState.PAUSED, LifecycleState.SHADOW, LifecycleState.RETIRED}
    ),
    LifecycleState.RETIRED: frozenset({LifecycleState.RETIRED}),
}

#: Edges that additionally require a :class:`PromotionRecord` naming evidence.
EVIDENCE_REQUIRED_EDGES: Final[frozenset[tuple[LifecycleState, LifecycleState]]] = (
    frozenset(
        {
            (LifecycleState.SHADOW, LifecycleState.ELIGIBLE),
            (LifecycleState.ELIGIBLE, LifecycleState.ACTIVE),
        }
    )
)


def _assert_no_live_reachable() -> None:
    """Fail closed at import time if a state named LIVE ever appears (§21)."""
    offenders = [s.value for s in LifecycleState if "LIVE" in s.value.upper()]
    if offenders:
        raise LifecycleStateError(f"LIVE must not be a lifecycle state: {offenders}")


_assert_no_live_reachable()


def assert_no_future_data(
    *, data_time_ms: int, decision_time_ms: int, label: str = "data"
) -> None:
    """Anti-lookahead guard (§25): a decision may never read data from its future.

    Applies to regime labels, health metrics, performance windows and shadow /
    challenger evaluation: ``data_time <= decision_time`` is a hard invariant.
    """
    if data_time_ms > decision_time_ms:
        raise LifecycleStateError(
            f"point-in-time violation: {label} at {data_time_ms} is after the decision "
            f"at {decision_time_ms}"
        )


def allowed_transitions(state: LifecycleState) -> frozenset[LifecycleState]:
    return STATE_TRANSITIONS.get(state, frozenset({state}))


def can_transition(source: LifecycleState, target: LifecycleState) -> bool:
    return target in allowed_transitions(source)


def describe_transition(source: LifecycleState, target: LifecycleState) -> str:
    return f"{source.value} -> {target.value}"


def assert_transition(
    strategy_id: str,
    source: LifecycleState,
    target: LifecycleState,
    *,
    promotion: PromotionRecord | None = None,
) -> None:
    """Authorise (or refuse) one lifecycle move, loudly."""
    if not can_transition(source, target):
        raise LifecycleStateError(
            f"{strategy_id}: transition {describe_transition(source, target)} is not "
            f"authorised (allowed: {sorted(s.value for s in allowed_transitions(source))})"
        )
    if (source, target) in EVIDENCE_REQUIRED_EDGES:
        if promotion is None:
            raise LifecycleStateError(
                f"{strategy_id}: {describe_transition(source, target)} requires a "
                "PromotionRecord naming the evidence"
            )
        if promotion.strategy_id != strategy_id:
            raise LifecycleStateError(
                f"{strategy_id}: promotion record belongs to {promotion.strategy_id}"
            )
        if not promotion.evidence:
            raise LifecycleStateError(
                f"{strategy_id}: promotion record carries no evidence"
            )


# --------------------------------------------------------------------------- #
# Context key — the (strategy, asset, timeframe, regime) cell (§6/§14)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ContextKey:
    """The unit of contextual performance: strategy x asset x timeframe x regime."""

    strategy_id: str
    asset: str
    timeframe: str
    regime: str

    def __str__(self) -> str:
        return f"{self.strategy_id}|{self.asset}|{self.timeframe}|{self.regime}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "regime": self.regime,
        }

    @staticmethod
    def cell_prefix(strategy_id: str, asset: str) -> tuple[str, str]:
        return (strategy_id, asset)


# --------------------------------------------------------------------------- #
# Rationale codes — machine-readable reasons on every decision (§9/§13)
# --------------------------------------------------------------------------- #


class RationaleCode(StrEnum):
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    THROTTLED = "THROTTLED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REGIME_MISMATCH = "REGIME_MISMATCH"
    RISK_CONFLICT = "RISK_CONFLICT"
    PORTFOLIO_CONFLICT = "PORTFOLIO_CONFLICT"
    CORRELATION_CONFLICT = "CORRELATION_CONFLICT"
    CONCENTRATION_CONFLICT = "CONCENTRATION_CONFLICT"
    STALE_DATA = "STALE_DATA"
    UNKNOWN_STRATEGY = "UNKNOWN_STRATEGY"
    # lifecycle-controller reasons
    PROMOTION_EARNED = "PROMOTION_EARNED"
    DEMOTION_EARNED = "DEMOTION_EARNED"
    HEALTH_DEGRADED = "HEALTH_DEGRADED"
    DRAWDOWN_BREACH = "DRAWDOWN_BREACH"
    EXPECTANCY_DECAY = "EXPECTANCY_DECAY"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    RECOVERY_EARNED = "RECOVERY_EARNED"
    RETIREMENT_EARNED = "RETIREMENT_EARNED"
    CHALLENGER_WIN = "CHALLENGER_WIN"
    CHAMPION_RETAINED = "CHAMPION_RETAINED"
    POLICY_INERT = "POLICY_INERT"


# --------------------------------------------------------------------------- #
# Events — append-only observability (§16)
# --------------------------------------------------------------------------- #


class StrategyEventType(StrEnum):
    STRATEGY_REGISTERED = "STRATEGY_REGISTERED"
    STRATEGY_VALIDATION_STARTED = "STRATEGY_VALIDATION_STARTED"
    STRATEGY_SHADOW_STARTED = "STRATEGY_SHADOW_STARTED"
    STRATEGY_ELIGIBLE = "STRATEGY_ELIGIBLE"
    STRATEGY_ACTIVATED = "STRATEGY_ACTIVATED"
    STRATEGY_DEGRADED = "STRATEGY_DEGRADED"
    STRATEGY_THROTTLED = "STRATEGY_THROTTLED"
    STRATEGY_PAUSED = "STRATEGY_PAUSED"
    STRATEGY_REACTIVATED = "STRATEGY_REACTIVATED"
    STRATEGY_RETIRED = "STRATEGY_RETIRED"
    STRATEGY_PROMOTION_REJECTED = "STRATEGY_PROMOTION_REJECTED"
    STRATEGY_CHALLENGER_WIN = "STRATEGY_CHALLENGER_WIN"
    STRATEGY_CHAMPION_RETAINED = "STRATEGY_CHAMPION_RETAINED"


_EVENT_FOR_STATE: Final[dict[LifecycleState, StrategyEventType]] = {
    LifecycleState.SHADOW: StrategyEventType.STRATEGY_SHADOW_STARTED,
    LifecycleState.ELIGIBLE: StrategyEventType.STRATEGY_ELIGIBLE,
    LifecycleState.ACTIVE: StrategyEventType.STRATEGY_ACTIVATED,
    LifecycleState.DEGRADED: StrategyEventType.STRATEGY_DEGRADED,
    LifecycleState.THROTTLED: StrategyEventType.STRATEGY_THROTTLED,
    LifecycleState.PAUSED: StrategyEventType.STRATEGY_PAUSED,
    LifecycleState.RETIRED: StrategyEventType.STRATEGY_RETIRED,
}


def event_for_state(state: LifecycleState) -> StrategyEventType | None:
    return _EVENT_FOR_STATE.get(state)


@dataclass(frozen=True, slots=True)
class StrategyEvent:
    """One append-only lifecycle event (§16)."""

    event_type: StrategyEventType
    strategy_id: str
    timestamp_ms: int
    from_state: LifecycleState | None = None
    to_state: LifecycleState | None = None
    reason_codes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACTS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "strategy_id": self.strategy_id,
            "timestamp_ms": self.timestamp_ms,
            "from_state": None if self.from_state is None else self.from_state.value,
            "to_state": None if self.to_state is None else self.to_state.value,
            "reason_codes": list(self.reason_codes),
            "evidence": list(self.evidence),
            "details": self.details,
            "schema_version": self.schema_version,
        }


# --------------------------------------------------------------------------- #
# Descriptor (§4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    """Everything the ecosystem must be able to state about a strategy (§4)."""

    strategy_id: str
    strategy_version: str
    family: str
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    supported_regimes: tuple[str, ...]
    runtime_implementation: str
    deterministic: bool = True
    lifecycle_state: LifecycleState = LifecycleState.DISCOVERED
    permissions: tuple[str, ...] = ()
    validation_status: str = "UNVALIDATED"
    validation_evidence: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    schema_version: str = CONTRACTS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id is required")
        if not self.deterministic:
            raise ValueError(
                "the runtime plane only admits deterministic strategies (§3): a "
                "non-deterministic strategy cannot receive a lifecycle"
            )

    @property
    def key(self) -> str:
        return f"{self.strategy_id}@{self.strategy_version}"

    def supports(self, asset: str, timeframe: str, regime: str | None) -> bool:
        if asset.upper() not in {a.upper() for a in self.assets}:
            return False
        if timeframe not in self.timeframes:
            return False
        if regime is not None and self.supported_regimes:
            return regime in self.supported_regimes
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "family": self.family,
            "assets": list(self.assets),
            "timeframes": list(self.timeframes),
            "supported_regimes": list(self.supported_regimes),
            "runtime_implementation": self.runtime_implementation,
            "deterministic": self.deterministic,
            "lifecycle_state": self.lifecycle_state.value,
            "permissions": list(self.permissions),
            "validation_status": self.validation_status,
            "validation_evidence": list(self.validation_evidence),
            "provenance": self.provenance,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "schema_version": self.schema_version,
        }


# --------------------------------------------------------------------------- #
# Performance cell (§6/§7)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PerformanceCell:
    """Aggregated, context-keyed performance for one rolling window (§7).

    Pure numbers with full provenance: no cell may exist without the window
    and the sample count that produced it.
    """

    context: ContextKey
    window: str
    sample_count: int
    trade_count: int
    gross_pnl_usdt: float
    net_pnl_usdt: float
    gross_expectancy_bps: float
    net_expectancy_bps: float
    profit_factor: float | None
    hit_rate: float
    avg_win_bps: float
    avg_loss_bps: float
    max_drawdown_bps: float
    exposure_usdt: float
    turnover_usdt: float
    cost_bps: float
    slippage_bps: float | None
    positive_windows: int
    window_count: int
    last_updated_ms: int
    execution_mode: ExecutionMode = ExecutionMode.SHADOW
    schema_version: str = CONTRACTS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_mode is ExecutionMode.LIVE:
            raise ValueError("a PerformanceCell can never be built on LIVE data here")

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "window": self.window,
            "sample_count": self.sample_count,
            "trade_count": self.trade_count,
            "gross_pnl_usdt": round(self.gross_pnl_usdt, 8),
            "net_pnl_usdt": round(self.net_pnl_usdt, 8),
            "gross_expectancy_bps": round(self.gross_expectancy_bps, 8),
            "net_expectancy_bps": round(self.net_expectancy_bps, 8),
            "profit_factor": None if self.profit_factor is None else round(self.profit_factor, 8),
            "hit_rate": round(self.hit_rate, 8),
            "avg_win_bps": round(self.avg_win_bps, 8),
            "avg_loss_bps": round(self.avg_loss_bps, 8),
            "max_drawdown_bps": round(self.max_drawdown_bps, 8),
            "exposure_usdt": round(self.exposure_usdt, 8),
            "turnover_usdt": round(self.turnover_usdt, 8),
            "cost_bps": round(self.cost_bps, 8),
            "slippage_bps": None if self.slippage_bps is None else round(self.slippage_bps, 8),
            "positive_windows": self.positive_windows,
            "window_count": self.window_count,
            "last_updated_ms": self.last_updated_ms,
            "execution_mode": self.execution_mode.value,
            "schema_version": self.schema_version,
        }


# --------------------------------------------------------------------------- #
# Health (§8)
# --------------------------------------------------------------------------- #


class HealthState(StrEnum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Structured health verdict with the flags and evidence behind it (§8)."""

    strategy_id: str
    context: ContextKey
    health_state: HealthState
    score: float
    metrics: dict[str, float]
    baseline: dict[str, float]
    current: dict[str, float]
    degradation_flags: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    window: str = "medium"
    timestamp_ms: int = 0
    schema_version: str = CONTRACTS_SCHEMA_VERSION

    @property
    def degraded(self) -> bool:
        return self.health_state in (HealthState.DEGRADED, HealthState.CRITICAL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "context": self.context.to_dict(),
            "health_state": self.health_state.value,
            "score": round(self.score, 8),
            "metrics": {k: round(v, 8) for k, v in self.metrics.items()},
            "baseline": {k: round(v, 8) for k, v in self.baseline.items()},
            "current": {k: round(v, 8) for k, v in self.current.items()},
            "degradation_flags": list(self.degradation_flags),
            "evidence": list(self.evidence),
            "window": self.window,
            "timestamp_ms": self.timestamp_ms,
            "schema_version": self.schema_version,
        }


# --------------------------------------------------------------------------- #
# Lifecycle decision + promotion record (§9)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """The audit trail for a transition that consumes evidence (§9/§41)."""

    promotion_id: str
    strategy_id: str
    from_state: LifecycleState
    to_state: LifecycleState
    evidence: tuple[str, ...]
    policy_version: str
    metrics_snapshot: dict[str, float] = field(default_factory=dict)
    dataset: str = ""
    commit: str = ""
    decided_at_ms: int = 0

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("a promotion record without evidence is not evidence")
        if (self.from_state, self.to_state) not in EVIDENCE_REQUIRED_EDGES:
            # Not an error (some callers record every decision), but the record
            # exists precisely to gate the evidence-required edges.
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "strategy_id": self.strategy_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "evidence": list(self.evidence),
            "policy_version": self.policy_version,
            "metrics_snapshot": {k: round(v, 8) for k, v in self.metrics_snapshot.items()},
            "dataset": self.dataset,
            "commit": self.commit,
            "decided_at_ms": self.decided_at_ms,
        }


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    """One auditable lifecycle verdict (§9). No side effects — the registry applies it."""

    strategy_id: str
    context: ContextKey
    from_state: LifecycleState
    to_state: LifecycleState
    reason_codes: tuple[str, ...]
    metrics_snapshot: dict[str, float]
    evidence: tuple[str, ...]
    policy_version: str
    promotion: PromotionRecord | None = None
    timestamp_ms: int = 0
    schema_version: str = CONTRACTS_SCHEMA_VERSION

    @property
    def changed(self) -> bool:
        return self.from_state is not self.to_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "context": self.context.to_dict(),
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "changed": self.changed,
            "reason_codes": list(self.reason_codes),
            "metrics_snapshot": {k: round(v, 8) for k, v in self.metrics_snapshot.items()},
            "evidence": list(self.evidence),
            "policy_version": self.policy_version,
            "promotion": None if self.promotion is None else self.promotion.to_dict(),
            "timestamp_ms": self.timestamp_ms,
            "schema_version": self.schema_version,
        }


# --------------------------------------------------------------------------- #
# Portfolio decision (§10)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PortfolioDecision:
    """Output of the StrategyPortfolioManager (§10). Risk still holds the veto."""

    accepted_proposals: tuple[str, ...] = ()
    rejected_proposals: tuple[str, ...] = ()
    merged_exposure: dict[str, float] = field(default_factory=dict)
    correlation_flags: tuple[str, ...] = ()
    concentration_flags: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    timestamp_ms: int = 0
    schema_version: str = CONTRACTS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_proposals": list(self.accepted_proposals),
            "rejected_proposals": list(self.rejected_proposals),
            "merged_exposure": {k: round(v, 8) for k, v in self.merged_exposure.items()},
            "correlation_flags": list(self.correlation_flags),
            "concentration_flags": list(self.concentration_flags),
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
            "timestamp_ms": self.timestamp_ms,
            "schema_version": self.schema_version,
        }
