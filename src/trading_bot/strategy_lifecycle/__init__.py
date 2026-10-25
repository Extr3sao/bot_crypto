"""Dynamic strategy ecosystem — Strategy Pods + lifecycle + champion/challenger.

This package is the RESEARCH/DISCOVERY plane of the dynamic strategy
architecture (RFC-STRAT-013 / RFC-STRAT-014). It answers a question the
existing admission ledger does not: *given a set of strategies and the evidence
each has accumulated, which are worth routing, and how does that change over
time?*

Hard boundaries (structurally enforced, not by convention):

* Nothing here executes. A :class:`~trading_bot.strategy_lifecycle.pods.StrategyPod`
  produces a signal; PAPER execution stays behind the admission ledger,
  IndependentVerifier and the deterministic RiskManager.
* Nothing here decides risk. No lifecycle or portfolio decision may touch
  leverage, sizing, capital, accounting or risk limits.
* An LLM (or any advisory ``proposed_state``) can never change a state: the
  :class:`~trading_bot.strategy_lifecycle.lifecycle.StrategyLifecycleController`
  only acts on deterministic policy evidence.
* ``LIVE`` is not reachable. The lifecycle vocabulary has no live state and the
  execution-mode vocabulary refuses it at construction.
"""

from __future__ import annotations

from .champion import ChampionChallenger, ComparisonOutcome, ComparisonResult
from .config import DEFAULT_HEALTH_POLICY, DEFAULT_LIFECYCLE_POLICY, HealthPolicy, LifecyclePolicy
from .contracts import (
    EVIDENCE_REQUIRED_EDGES,
    STATE_TRANSITIONS,
    ContextKey,
    ExecutionMode,
    HealthReport,
    HealthState,
    LifecycleDecision,
    LifecycleState,
    LifecycleStateError,
    PortfolioDecision,
    PromotionRecord,
    RationaleCode,
    StrategyDescriptor,
    StrategyEvent,
    assert_transition,
    can_transition,
    describe_transition,
)
from .ecosystem import DynamicStrategyEcosystem
from .health import StrategyHealthMonitor
from .lifecycle import ControllerInputs, StrategyLifecycleController
from .performance import ContextualPerformanceStore, PerformanceObservation, PerformanceWindow
from .pods import ParallelShadowRuntime, PodResult, PodSignal, StrategyPod
from .portfolio import PortfolioProposal, StrategyPortfolioManager
from .registry import ChurnMetrics, DynamicStrategyRegistry

__all__ = [
    "DEFAULT_HEALTH_POLICY",
    "DEFAULT_LIFECYCLE_POLICY",
    "EVIDENCE_REQUIRED_EDGES",
    "STATE_TRANSITIONS",
    "ChampionChallenger",
    "ChurnMetrics",
    "ComparisonOutcome",
    "ComparisonResult",
    "ContextKey",
    "ContextualPerformanceStore",
    "ControllerInputs",
    "DynamicStrategyEcosystem",
    "DynamicStrategyRegistry",
    "ExecutionMode",
    "HealthPolicy",
    "HealthReport",
    "HealthState",
    "LifecycleDecision",
    "LifecyclePolicy",
    "LifecycleState",
    "LifecycleStateError",
    "ParallelShadowRuntime",
    "PerformanceObservation",
    "PerformanceWindow",
    "PodResult",
    "PodSignal",
    "PortfolioDecision",
    "PortfolioProposal",
    "PromotionRecord",
    "RationaleCode",
    "StrategyDescriptor",
    "StrategyEvent",
    "StrategyHealthMonitor",
    "StrategyLifecycleController",
    "StrategyPod",
    "StrategyPortfolioManager",
    "assert_transition",
    "can_transition",
    "describe_transition",
]
