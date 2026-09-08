"""Statistical evidence for the admission path — Track E2.

STAT-VALIDATION-01 (checkpoint INTELLIGENCE-AND-EXECUTION-HARDENING-01).
Bridges the Track E estimators into the runtime admission path
(``research/admission.py::AdmissionController``) as EVIDENCE, not as a
promotion oracle:

- A single p-value can NEVER promote a strategy (multi-gate remains
  mandatory; this module only *reports* evidence and computes a gate
  contribution).
- The existing strategy-level gates (``config/strategies.py::
  require_walk_forward_validation``) are untouched.
- No POC01 behavior change: nothing here is wired into the frozen runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_bot.backtesting.stat_validation import (
    SharpeCI,
    bootstrap_sharpe_ci,
    permutation_significance,
)


@dataclass(frozen=True, slots=True)
class StatEvidenceGates:
    """Configurable thresholds for the statistical evidence gates."""

    min_prob_sharpe_positive: float = 0.90
    max_permutation_p_value: float = 0.10
    require_ci_excludes_zero: bool = True


@dataclass(frozen=True, slots=True)
class StatEvidence:
    """Immutable statistical evidence record for one strategy sample."""

    n: int
    sharpe_estimate: float
    ci_lower: float
    ci_upper: float
    prob_sharpe_positive: float
    permutation_p_value: float
    gates_passed: bool
    failed_gates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "n": self.n,
            "sharpe_estimate": self.sharpe_estimate,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "prob_sharpe_positive": self.prob_sharpe_positive,
            "permutation_p_value": self.permutation_p_value,
            "gates_passed": self.gates_passed,
            "failed_gates": list(self.failed_gates),
        }


def compute_stat_evidence(
    returns: tuple[float, ...],
    *,
    gates: StatEvidenceGates | None = None,
    seed: int = 42,
    resamples: int = 1_000,
    permutations: int = 1_000,
) -> StatEvidence:
    """Compute statistical evidence for admission; multi-gate, never solo.

    Fails closed: insufficient sample or zero variance raise ``ValueError``
    from the underlying estimators and the caller must treat the strategy as
    NOT evidenced (no promotion path through exceptions).
    """
    g = gates or StatEvidenceGates()
    ci: SharpeCI = bootstrap_sharpe_ci(returns, resamples=resamples, seed=seed)
    perm = permutation_significance(returns, permutations=permutations, seed=seed)
    failed: list[str] = []
    if g.require_ci_excludes_zero and not (ci.ci_lower > 0.0 or ci.ci_upper < 0.0):
        failed.append("ci_includes_zero")
    if ci.prob_sharpe_positive < g.min_prob_sharpe_positive:
        failed.append("prob_sharpe_positive_below_gate")
    if perm.p_value > g.max_permutation_p_value:
        failed.append("permutation_p_value_above_gate")
    return StatEvidence(
        n=ci.n,
        sharpe_estimate=ci.estimate,
        ci_lower=ci.ci_lower,
        ci_upper=ci.ci_upper,
        prob_sharpe_positive=ci.prob_sharpe_positive,
        permutation_p_value=perm.p_value,
        gates_passed=not failed,
        failed_gates=tuple(failed),
    )
