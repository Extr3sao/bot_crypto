"""StrategyLifecycleController — deterministic promotion / demotion (§9/§24).

The controller reads a descriptor, its context-keyed performance cells and its
health report, and returns a :class:`LifecycleDecision`. It has NO side effects:
the registry applies the decision, which re-checks the transition graph.

Anti-false-success rules encoded here:

* No promotion from "last N trades were profitable". Promotion needs sample
  count, expectancy, profit factor, drawdown, stability, regime samples,
  cost-adjusted positivity AND independent verification.
* An advisory ``proposed_state`` (e.g. an LLM suggestion) is recorded and then
  IGNORED — it can never move the machine.
* ``PAUSED → ACTIVE`` and ``CANDIDATE → ACTIVE`` do not exist; recovery always
  routes through SHADOW → ELIGIBLE → ACTIVE.
* Activation has cooldown + dwell so the ecosystem cannot churn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .config import DEFAULT_LIFECYCLE_POLICY, LifecyclePolicy
from .contracts import (
    ContextKey,
    HealthReport,
    HealthState,
    LifecycleDecision,
    LifecycleState,
    PerformanceCell,
    PromotionRecord,
    RationaleCode,
    StrategyDescriptor,
)

__all__ = ["LIFECYCLE_CONTROLLER_VERSION", "StrategyLifecycleController"]

LIFECYCLE_CONTROLLER_VERSION: Final[str] = "strategy-lifecycle-controller-v1"


@dataclass(frozen=True, slots=True)
class ControllerInputs:
    descriptor: StrategyDescriptor
    context: ContextKey
    cells: dict[str, PerformanceCell]
    health: HealthReport
    now_ms: int
    regime_cell: PerformanceCell | None = None
    verification_passed: bool = False
    challenge_won: bool = False
    #: Consecutive evaluations the strategy has been in a degraded state.
    degraded_streak: int = 0
    #: Consecutive evaluations in a good state while PAUSED/THROTTLED.
    recovery_streak: int = 0
    last_activation_ms: int = 0
    eligible_since_ms: int = 0
    last_demotion_ms: int = 0
    #: Purely advisory. Recorded in evidence, never acted upon.
    advisory_proposed_state: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyLifecycleController:
    """Deterministic lifecycle evaluator (§9)."""

    policy: LifecyclePolicy = DEFAULT_LIFECYCLE_POLICY
    version: str = LIFECYCLE_CONTROLLER_VERSION

    def evaluate(self, inputs: ControllerInputs) -> LifecycleDecision:
        state = inputs.descriptor.lifecycle_state
        evidence: list[str] = []
        if inputs.advisory_proposed_state:
            evidence.append(
                f"advisory proposal {inputs.advisory_proposed_state!r} recorded and IGNORED "
                "(only deterministic policy may move a state)"
            )

        if state is LifecycleState.ACTIVE:
            target, reasons = self._from_active(inputs, evidence)
        elif state is LifecycleState.DEGRADED:
            target, reasons = self._from_degraded(inputs, evidence)
        elif state is LifecycleState.THROTTLED:
            target, reasons = self._from_throttled(inputs, evidence)
        elif state is LifecycleState.PAUSED:
            target, reasons = self._from_paused(inputs, evidence)
        elif state is LifecycleState.SHADOW:
            target, reasons = self._from_shadow(inputs, evidence)
        elif state is LifecycleState.ELIGIBLE:
            target, reasons = self._from_eligible(inputs, evidence)
        elif state in (LifecycleState.DISCOVERED, LifecycleState.CANDIDATE):
            target, reasons = self._from_early(inputs, evidence)
        else:  # VALIDATING / PAPER / RETIRED: no automatic move by this controller
            target, reasons = state, [RationaleCode.POLICY_INERT.value]

        promotion = None
        if (state, target) in {
            (LifecycleState.SHADOW, LifecycleState.ELIGIBLE),
            (LifecycleState.ELIGIBLE, LifecycleState.ACTIVE),
        }:
            promotion = self._promotion_record(inputs, state, target, evidence)

        metrics = self._metrics(inputs)
        return LifecycleDecision(
            strategy_id=inputs.descriptor.strategy_id,
            context=inputs.context,
            from_state=state,
            to_state=target,
            reason_codes=tuple(reasons),
            metrics_snapshot=metrics,
            evidence=tuple(evidence),
            policy_version=self.policy.version,
            promotion=promotion,
            timestamp_ms=inputs.now_ms,
        )

    # -- per-state machines -------------------------------------------------

    def _from_active(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        medium = inputs.cells.get("medium")
        if self._degraded(inputs, medium):
            evidence.append("active strategy met demotion criteria")
            return LifecycleState.DEGRADED, [
                RationaleCode.DEMOTION_EARNED.value,
                RationaleCode.HEALTH_DEGRADED.value,
            ]
        return LifecycleState.ACTIVE, [RationaleCode.SELECTED.value]

    def _from_degraded(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        if self._recovered(inputs):
            evidence.append("health recovered within the active lineage")
            return LifecycleState.ACTIVE, [RationaleCode.RECOVERY_EARNED.value]
        if inputs.degraded_streak + 1 >= self.policy.degrade_persistence + 1:
            evidence.append("degradation persisted; throttling")
            return LifecycleState.THROTTLED, [RationaleCode.HEALTH_DEGRADED.value]
        return LifecycleState.DEGRADED, [RationaleCode.DEGRADED.value]

    def _from_throttled(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        if self._recovered(inputs):
            evidence.append("health recovered; leaving throttle")
            return LifecycleState.ACTIVE, [RationaleCode.RECOVERY_EARNED.value]
        if inputs.degraded_streak + 1 >= 2 * (self.policy.degrade_persistence + 1):
            evidence.append("degradation persisted through the throttle; pausing")
            return LifecycleState.PAUSED, [RationaleCode.RETIREMENT_EARNED.value]
        return LifecycleState.THROTTLED, [RationaleCode.THROTTLED.value]

    def _from_paused(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        # PAUSED can only move to SHADOW (re-earn) — never straight to ACTIVE.
        if self._recovery_evidence(inputs):
            evidence.append("paused strategy showed recovery; re-entering SHADOW")
            return LifecycleState.SHADOW, [RationaleCode.RECOVERY_EARNED.value]
        return LifecycleState.PAUSED, [RationaleCode.PAUSED.value]

    def _from_shadow(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        ok, reasons = self._promotion_gate(inputs, evidence)
        if not ok:
            return LifecycleState.SHADOW, reasons
        if not self._quiet_period_ok(inputs):
            evidence.append("promotion blocked by post-demotion quiet period")
            return LifecycleState.SHADOW, [RationaleCode.COOLDOWN_ACTIVE.value]
        return LifecycleState.ELIGIBLE, [RationaleCode.PROMOTION_EARNED.value]

    def _from_eligible(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        ok, reasons = self._promotion_gate(inputs, evidence)
        if not ok:
            evidence.append("eligibility lapsed; returning to SHADOW")
            return LifecycleState.SHADOW, reasons
        # Activation dwell + cooldown (churn control §24).
        if (
            inputs.eligible_since_ms
            and inputs.now_ms - inputs.eligible_since_ms < self.policy.eligibility_dwell_ms
        ):
            evidence.append("activation blocked by eligibility dwell")
            return LifecycleState.ELIGIBLE, [RationaleCode.COOLDOWN_ACTIVE.value]
        if (
            inputs.last_activation_ms
            and inputs.now_ms - inputs.last_activation_ms < self.policy.activation_cooldown_ms
        ):
            evidence.append("activation blocked by activation cooldown")
            return LifecycleState.ELIGIBLE, [RationaleCode.COOLDOWN_ACTIVE.value]
        return LifecycleState.ACTIVE, [RationaleCode.PROMOTION_EARNED.value]

    def _from_early(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[LifecycleState, list[str]]:
        # DISCOVERED → CANDIDATE is a registration step, not a promotion.
        if inputs.descriptor.lifecycle_state is LifecycleState.DISCOVERED:
            return LifecycleState.CANDIDATE, [RationaleCode.SELECTED.value]
        return LifecycleState.CANDIDATE, [RationaleCode.POLICY_INERT.value]

    # -- gates --------------------------------------------------------------

    def _promotion_gate(
        self, inputs: ControllerInputs, evidence: list[str]
    ) -> tuple[bool, list[str]]:
        p = self.policy
        # Fail closed (DEF-VERIFY-002): a strategy the health monitor has called
        # DEGRADED/CRITICAL must not be promoted on a numeric cell alone. The
        # health verdict is a first-class refusal, checked before any metric.
        if inputs.health.health_state in (HealthState.DEGRADED, HealthState.CRITICAL):
            evidence.append(f"promotion refused: health is {inputs.health.health_state.value}")
            return False, [RationaleCode.HEALTH_DEGRADED.value]
        medium = inputs.cells.get("medium")
        if medium is None or medium.sample_count < p.minimum_samples:
            evidence.append(
                f"insufficient samples: {0 if medium is None else medium.sample_count} < {p.minimum_samples}"
            )
            return False, [RationaleCode.INSUFFICIENT_EVIDENCE.value]

        reasons: list[str] = []
        if medium.net_expectancy_bps < p.minimum_expectancy_bps:
            reasons.append(RationaleCode.INSUFFICIENT_EVIDENCE.value)
        if medium.profit_factor is None or medium.profit_factor < p.minimum_profit_factor:
            reasons.append(RationaleCode.INSUFFICIENT_EVIDENCE.value)
        if medium.max_drawdown_bps > p.maximum_drawdown_bps:
            reasons.append(RationaleCode.DRAWDOWN_BREACH.value)
        if (
            medium.window_count
            and (medium.positive_windows / medium.window_count) < p.minimum_stability
        ):
            reasons.append(RationaleCode.INSUFFICIENT_EVIDENCE.value)
        if medium.positive_windows < p.minimum_positive_windows:
            reasons.append(RationaleCode.INSUFFICIENT_EVIDENCE.value)
        if p.cost_adjusted_positive and medium.net_expectancy_bps <= 0:
            reasons.append(RationaleCode.INSUFFICIENT_EVIDENCE.value)
        if p.minimum_regime_samples > 0:
            rc = inputs.regime_cell
            if rc is None or rc.sample_count < p.minimum_regime_samples:
                reasons.append(RationaleCode.REGIME_MISMATCH.value)
        if p.independent_verification_required and not inputs.verification_passed:
            reasons.append(RationaleCode.INSUFFICIENT_EVIDENCE.value)
        if not inputs.descriptor.supports(
            inputs.context.asset, inputs.context.timeframe, inputs.context.regime
        ):
            reasons.append(RationaleCode.NOT_APPLICABLE.value)

        if reasons:
            evidence.append("promotion gate not satisfied: " + ", ".join(sorted(set(reasons))))
            return False, sorted(set(reasons))
        evidence.append("promotion gate satisfied")
        return True, [RationaleCode.PROMOTION_EARNED.value]

    def _degraded(self, inputs: ControllerInputs, medium: PerformanceCell | None) -> bool:
        if inputs.health.health_state in (HealthState.DEGRADED, HealthState.CRITICAL):
            return True
        if medium is None:
            return False
        if medium.sample_count < self.policy.demotion_minimum_samples:
            return False
        if medium.max_drawdown_bps >= self.policy.demotion_drawdown_bps:
            return True
        if medium.net_expectancy_bps <= self.policy.demotion_expectancy_bps:
            return True
        pf = medium.profit_factor
        return pf is not None and pf < self.policy.demotion_profit_factor

    def _recovered(self, inputs: ControllerInputs) -> bool:
        return (
            inputs.health.health_state is HealthState.HEALTHY
            and inputs.recovery_streak + 1 >= self.policy.degrade_persistence
        )

    def _recovery_evidence(self, inputs: ControllerInputs) -> bool:
        """PAUSED → SHADOW needs real, persistent recovery, not one good window."""
        medium = inputs.cells.get("medium")
        if medium is None:
            return False
        return (
            medium.sample_count >= self.policy.recovery_minimum_samples
            and medium.net_expectancy_bps >= self.policy.recovery_minimum_expectancy_bps
            and medium.profit_factor is not None
            and medium.profit_factor >= self.policy.minimum_profit_factor
            and inputs.recovery_streak + 1 >= self.policy.degrade_persistence
        )

    def _quiet_period_ok(self, inputs: ControllerInputs) -> bool:
        if not inputs.last_demotion_ms:
            return True
        return inputs.now_ms - inputs.last_demotion_ms >= self.policy.demotion_quiet_ms

    def _promotion_record(
        self,
        inputs: ControllerInputs,
        source: LifecycleState,
        target: LifecycleState,
        evidence: list[str],
    ) -> PromotionRecord:
        return PromotionRecord(
            promotion_id=f"{inputs.descriptor.strategy_id}:{source.value}->{target.value}:{inputs.now_ms}",
            strategy_id=inputs.descriptor.strategy_id,
            from_state=source,
            to_state=target,
            evidence=tuple(evidence) or ("policy gate satisfied",),
            policy_version=self.policy.version,
            metrics_snapshot=self._metrics(inputs),
            dataset=inputs.descriptor.provenance.get("dataset", ""),
            commit=inputs.descriptor.provenance.get("commit", ""),
            decided_at_ms=inputs.now_ms,
        )

    @staticmethod
    def _metrics(inputs: ControllerInputs) -> dict[str, float]:
        medium = inputs.cells.get("medium")
        if medium is None:
            return {}
        return {
            "sample_count": float(medium.sample_count),
            "net_expectancy_bps": medium.net_expectancy_bps,
            "profit_factor": medium.profit_factor or 0.0,
            "max_drawdown_bps": medium.max_drawdown_bps,
            "positive_windows": float(medium.positive_windows),
            "window_count": float(medium.window_count),
        }
