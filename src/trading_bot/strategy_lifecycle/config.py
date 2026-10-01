"""Configurable policies for the lifecycle controller and health monitor (§7/§9).

Every threshold lives here and is overridable. The defaults are *preregistered
defaults*, not researched optima: the point of the controller is that its
behaviour is inspectable and adjustable, not that these exact numbers are right.
Every decision cites ``policy_version`` so a report can say which policy judged
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "DEFAULT_HEALTH_POLICY",
    "DEFAULT_LIFECYCLE_POLICY",
    "HealthPolicy",
    "LifecyclePolicy",
    "RollingWindows",
]

LIFECYCLE_POLICY_VERSION: Final[str] = "strategy-lifecycle-policy-v1"
HEALTH_POLICY_VERSION: Final[str] = "strategy-health-policy-v1"


@dataclass(frozen=True, slots=True)
class RollingWindows:
    """Rolling sample windows (§7). Sample counts, not wall-clock, so a quiet
    strategy is not judged on trades it never took."""

    short: int = 50
    medium: int = 100
    long: int = 250

    def __post_init__(self) -> None:
        if not (0 < self.short <= self.medium <= self.long):
            raise ValueError(
                "rolling windows must satisfy 0 < short <= medium <= long "
                f"(got {self.short}/{self.medium}/{self.long})"
            )

    def resolve(self, name: str) -> int:
        try:
            return {"short": self.short, "medium": self.medium, "long": self.long}[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"unknown window {name!r}") from exc


@dataclass(frozen=True, slots=True)
class HealthPolicy:
    """Thresholds for :class:`StrategyHealthMonitor` (§8)."""

    windows: RollingWindows = field(default_factory=RollingWindows)
    #: Below this many samples in the working window, health is INSUFFICIENT_DATA
    #: rather than HEALTHY — absence of evidence is never evidence of health.
    min_samples: int = 20
    #: Relative deterioration vs the long-window baseline that raises a flag.
    expectancy_decay_frac: float = 0.5
    profit_factor_decay_frac: float = 0.4
    hit_rate_drift_frac: float = 0.35
    #: Absolute profit-factor floor: below this is CRITICAL.
    min_profit_factor: float = 1.0
    #: Drawdown deterioration (bps) vs baseline that raises a flag.
    drawdown_worsen_bps: float = 75.0
    #: Cost sensitivity: cost as a fraction of gross edge above this is a flag.
    cost_sensitivity_frac: float = 0.6
    #: Slippage worsening (bps) vs baseline that raises a flag.
    slippage_worsen_bps: float = 2.0
    #: Loss clustering: this many consecutive losses within the window is a flag.
    loss_cluster_len: int = 4
    #: Signal-frequency drift: relative change in trades-per-sample beyond this.
    signal_frequency_drift_frac: float = 0.75
    #: Abnormal inactivity: zero trades in the window while >= min_samples bars.
    inactivity_samples: int = 60
    #: Abnormal signal explosion: trades-per-sample above this multiple of baseline.
    signal_explosion_multiple: float = 3.0
    #: Correlation increase (portfolio-level): flag when pairwise net-return
    #: correlation rises above this.
    correlation_flag_threshold: float = 0.7
    version: str = HEALTH_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    """Deterministic promotion / demotion policy (§9)."""

    # -- promotion gate (SHADOW/ELIGIBLE → ACTIVE) --------------------------
    minimum_samples: int = 100
    minimum_expectancy_bps: float = 0.0
    minimum_profit_factor: float = 1.1
    maximum_drawdown_bps: float = 200.0
    #: Fraction of rolling sub-windows that must be net-positive.
    minimum_stability: float = 0.6
    minimum_positive_windows: int = 3
    #: Samples required in the CURRENT regime cell specifically (§14).
    minimum_regime_samples: int = 30
    cost_adjusted_positive: bool = True
    independent_verification_required: bool = True

    # -- demotion gate (ACTIVE → DEGRADED) ----------------------------------
    demotion_minimum_samples: int = 30
    demotion_expectancy_bps: float = -10.0
    demotion_profit_factor: float = 0.9
    demotion_drawdown_bps: float = 250.0
    #: Consecutive degraded evaluations required before pausing (hysteresis).
    degrade_persistence: int = 2

    # -- recovery gate (PAUSED → SHADOW → ELIGIBLE → ACTIVE) ----------------
    #: ACTIVE → DEGRADED needs less evidence than ELIGIBLE → ACTIVE, so
    #: recovery is deliberately harder than demotion (§24 hysteresis).
    recovery_minimum_samples: int = 60
    recovery_minimum_expectancy_bps: float = 5.0

    # -- activation churn control (§24) -------------------------------------
    #: Minimum ms between two activations of the same strategy.
    activation_cooldown_ms: int = 6 * 60 * 60 * 1000
    #: Minimum ms a strategy must stay ELIGIBLE before it may activate.
    eligibility_dwell_ms: int = 30 * 60 * 1000
    #: Minimum ms before a demoted strategy may be reconsidered for promotion.
    demotion_quiet_ms: int = 2 * 60 * 60 * 1000

    version: str = LIFECYCLE_POLICY_VERSION


DEFAULT_HEALTH_POLICY: Final[HealthPolicy] = HealthPolicy()
DEFAULT_LIFECYCLE_POLICY: Final[LifecyclePolicy] = LifecyclePolicy()
