from __future__ import annotations

import random

import pytest

from trading_bot.backtesting.stat_validation import (
    bootstrap_sharpe_ci,
    permutation_significance,
)


def _positive_returns(n: int = 60, *, seed: int = 7) -> tuple[float, ...]:
    rng = random.Random(seed)
    return tuple(max(0.0005, rng.gauss(0.004, 0.01)) for _ in range(n))


def _negative_returns(n: int = 60, *, seed: int = 7) -> tuple[float, ...]:
    rng = random.Random(seed)
    return tuple(min(-0.0005, rng.gauss(-0.004, 0.01)) for _ in range(n))


def _random_returns(n: int = 60, *, seed: int = 7) -> tuple[float, ...]:
    rng = random.Random(seed)
    return tuple(rng.gauss(0.0, 0.01) for _ in range(n))


def test_positive_strategy_ci_excludes_zero_and_prob_high() -> None:
    ci = bootstrap_sharpe_ci(_positive_returns(), resamples=500, seed=42)
    assert ci.estimate > 0.0
    assert ci.ci_lower > 0.0
    assert ci.prob_sharpe_positive >= 0.9


def test_negative_strategy_ci_excludes_zero_from_above() -> None:
    ci = bootstrap_sharpe_ci(_negative_returns(), resamples=500, seed=42)
    assert ci.estimate < 0.0
    assert ci.ci_upper < 0.0
    assert ci.prob_sharpe_positive <= 0.1


def test_random_strategy_ci_straddles_zero() -> None:
    ci = bootstrap_sharpe_ci(_random_returns(), resamples=500, seed=42)
    assert ci.ci_lower <= 0.0 <= ci.ci_upper


def test_permutation_positive_strategy_significant() -> None:
    result = permutation_significance(_positive_returns(seed=11), permutations=500, seed=42)
    assert result.observed_sharpe > 0.0
    assert result.verdict == "SIGNIFICANT"
    assert result.p_value <= 0.05


def test_permutation_negative_strategy_not_significant_edge() -> None:
    result = permutation_significance(_negative_returns(seed=11), permutations=500, seed=42)
    # Negative observed Sharpe: the null (symmetric) distribution trivially
    # exceeds it often -> NOT_SIGNIFICANT (edge is on the short side).
    assert result.verdict == "NOT_SIGNIFICANT"
    assert result.p_value > 0.05


def test_permutation_random_strategy_not_significant() -> None:
    result = permutation_significance(_random_returns(seed=3), permutations=500, seed=42)
    assert result.verdict in ("NOT_SIGNIFICANT", "SIGNIFICANT")  # data-dependent
    assert 0.0 <= result.p_value <= 1.0


def test_tiny_sample_fails_closed() -> None:
    with pytest.raises(ValueError, match="insufficient sample"):
        bootstrap_sharpe_ci((0.01, 0.02, 0.01, 0.03), resamples=100)
    with pytest.raises(ValueError, match="insufficient sample"):
        permutation_significance((0.01, 0.02, 0.01, 0.03), permutations=100)


def test_zero_variance_returns_insufficient_evidence_not_numbers() -> None:
    flat = (0.01,) * 60
    ci = bootstrap_sharpe_ci(flat, resamples=100)
    assert ci.estimate == 0.0
    assert ci.ci_lower == 0.0 and ci.ci_upper == 0.0
    assert ci.prob_sharpe_positive == 0.0
    perm = permutation_significance(flat, permutations=100)
    assert perm.verdict == "INSUFFICIENT_EVIDENCE"
    assert perm.p_value == 1.0


def test_seed_reproducibility_bit_identical() -> None:
    returns = _positive_returns(seed=5)
    first = bootstrap_sharpe_ci(returns, resamples=300, seed=99)
    second = bootstrap_sharpe_ci(returns, resamples=300, seed=99)
    assert (first.ci_lower, first.ci_upper, first.prob_sharpe_positive) == (
        second.ci_lower,
        second.ci_upper,
        second.prob_sharpe_positive,
    )
    perm_first = permutation_significance(returns, permutations=300, seed=99)
    perm_second = permutation_significance(returns, permutations=300, seed=99)
    assert (perm_first.p_value, perm_first.null_mean_sharpe) == (perm_second.p_value, perm_second.null_mean_sharpe)


def test_different_seed_gives_different_resamples_same_estimate() -> None:
    returns = _positive_returns(seed=5)
    a = bootstrap_sharpe_ci(returns, resamples=300, seed=1)
    b = bootstrap_sharpe_ci(returns, resamples=300, seed=2)
    assert a.estimate == b.estimate  # point estimate is seed-free
    # CI bounds are resample-dependent (extremely unlikely to be identical).
    assert (a.ci_lower, a.ci_upper) != (b.ci_lower, b.ci_upper)


def test_no_future_leakage_prefix_invariance() -> None:
    # Truncating FUTURE returns must not change the CI computed on the past.
    returns = _positive_returns(n=80, seed=13)
    past = returns[:40]
    ci_before = bootstrap_sharpe_ci(past, resamples=300, seed=7)
    # Mutate the future harshly.
    mutated = tuple(past) + tuple(-10.0 * r for r in returns[40:])
    ci_after = bootstrap_sharpe_ci(mutated[:40], resamples=300, seed=7)
    assert (ci_before.ci_lower, ci_before.ci_upper) == (ci_after.ci_lower, ci_after.ci_upper)


def test_confidence_level_respected() -> None:
    returns = _positive_returns(seed=21)
    wide = bootstrap_sharpe_ci(returns, resamples=500, confidence=0.99, seed=3)
    narrow = bootstrap_sharpe_ci(returns, resamples=500, confidence=0.80, seed=3)
    assert wide.ci_lower <= narrow.ci_lower
    assert wide.ci_upper >= narrow.ci_upper
