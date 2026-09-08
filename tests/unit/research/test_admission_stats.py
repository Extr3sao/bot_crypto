from __future__ import annotations

import random

import pytest

from trading_bot.research.admission_stats import (
    StatEvidenceGates,
    compute_stat_evidence,
)


def _positive(n: int = 80, *, seed: int = 7) -> tuple[float, ...]:
    rng = random.Random(seed)
    return tuple(max(0.0005, rng.gauss(0.004, 0.01)) for _ in range(n))


def test_positive_strategy_passes_all_gates() -> None:
    evidence = compute_stat_evidence(_positive(seed=11), resamples=400, permutations=400)
    assert evidence.gates_passed, evidence.failed_gates
    assert evidence.ci_lower > 0.0
    payload = evidence.to_dict()
    assert payload["n"] == evidence.n


def test_single_p_value_cannot_promote() -> None:
    # A perfect permutation p-value (0.0) alone must NOT promote: with an
    # impossible prob-Sharpe gate (1.1 > max 1.0) the evidence fails even
    # though the p-value gate passes -> promotion is multi-gate.
    gates = StatEvidenceGates(require_ci_excludes_zero=False, min_prob_sharpe_positive=1.1)
    evidence = compute_stat_evidence(_positive(seed=11), gates=gates, resamples=400, permutations=400)
    assert evidence.permutation_p_value == 0.0  # p-value gate trivially passes
    assert not evidence.gates_passed
    assert "prob_sharpe_positive_below_gate" in evidence.failed_gates


def test_ci_excludes_zero_gate_fails_for_random_strategy() -> None:
    rng = random.Random(3)
    returns = tuple(rng.gauss(0.0, 0.01) for _ in range(80))
    evidence = compute_stat_evidence(returns, resamples=400, permutations=400)
    # A random strategy should fail at least one gate (usually CI + p-value).
    assert not evidence.gates_passed or evidence.prob_sharpe_positive < 0.9


def test_tiny_sample_fails_closed() -> None:
    with pytest.raises(ValueError, match="insufficient sample"):
        compute_stat_evidence((0.01, 0.02, 0.01), resamples=100, permutations=100)


def test_zero_variance_fails_closed_no_promotion() -> None:
    flat = (0.01,) * 80
    evidence = compute_stat_evidence(flat, resamples=100, permutations=100)
    assert not evidence.gates_passed
    assert "ci_includes_zero" in evidence.failed_gates


def test_gate_thresholds_configurable() -> None:
    gates = StatEvidenceGates(min_prob_sharpe_positive=0.5, max_permutation_p_value=0.9, require_ci_excludes_zero=False)
    evidence = compute_stat_evidence(_positive(seed=11), gates=gates, resamples=300, permutations=300)
    assert evidence.gates_passed
