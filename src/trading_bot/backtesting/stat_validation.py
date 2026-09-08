"""Statistical validation for strategy evidence — Track E.

STAT-VALIDATION-01 (checkpoint INTELLIGENCE-AND-EXECUTION-HARDENING-01).
Implements ONLY the confirmed gaps from the earlier audit (no duplication of
Monte Carlo / walk-forward / existing bootstrap infrastructure):

- Bootstrap Sharpe confidence interval (percentile method).
- Probability that Sharpe > 0 (bootstrap estimate).
- Permutation (sign-flip) significance test.

All estimators are reproducible with an explicit seed, fail closed on
degenerate inputs (tiny N, zero variance -> INSUFFICIENT_EVIDENCE, not
fabricated numbers), and consume only PAST returns (no future leakage by
construction: each resample draws from the provided series alone).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["SIGNIFICANT", "NOT_SIGNIFICANT", "INSUFFICIENT_EVIDENCE"]


def _sharpe(returns: tuple[float, ...], *, periods_per_year: int = 365) -> float:
    """Annualized Sharpe from a return sample (0.0 on zero variance)."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    if std == 0.0:
        return 0.0
    return mean / std * math.sqrt(periods_per_year)


@dataclass(frozen=True, slots=True)
class SharpeCI:
    """Bootstrap Sharpe confidence interval."""

    estimate: float
    ci_lower: float
    ci_upper: float
    prob_sharpe_positive: float
    n: int
    resamples: int
    seed: int


@dataclass(frozen=True, slots=True)
class PermutationResult:
    """Sign-flip permutation test against a zero-mean null."""

    observed_sharpe: float
    null_mean_sharpe: float
    p_value: float
    verdict: Verdict
    n: int
    permutations: int
    seed: int


MIN_SAMPLE = 5


def bootstrap_sharpe_ci(
    returns: tuple[float, ...],
    *,
    resamples: int = 2_000,
    confidence: float = 0.95,
    seed: int = 42,
    periods_per_year: int = 365,
) -> SharpeCI:
    """Percentile bootstrap CI for annualized Sharpe (seeded, deterministic)."""
    n = len(returns)
    if n < MIN_SAMPLE:
        raise ValueError(f"insufficient sample: {n} < {MIN_SAMPLE}")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if len(set(returns)) == 1:
        # Zero-variance series: Sharpe is degenerate (float noise can make
        # std tiny-but-nonzero and Sharpe astronomic). Fail closed: no
        # statistical evidence without variance.
        return SharpeCI(
            estimate=0.0,
            ci_lower=0.0,
            ci_upper=0.0,
            prob_sharpe_positive=0.0,
            n=n,
            resamples=resamples,
            seed=seed,
        )
    estimate = _sharpe(returns, periods_per_year=periods_per_year)
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(resamples):
        sample = tuple(returns[rng.randrange(n)] for _ in range(n))
        stats.append(_sharpe(sample, periods_per_year=periods_per_year))
    stats.sort()
    alpha = (1.0 - confidence) / 2.0
    lower_idx = max(0, math.floor(alpha * len(stats)))
    upper_idx = min(len(stats) - 1, math.ceil((1.0 - alpha) * len(stats)) - 1)
    positive = sum(1 for s in stats if s > 0.0)
    return SharpeCI(
        estimate=estimate,
        ci_lower=stats[lower_idx],
        ci_upper=stats[upper_idx],
        prob_sharpe_positive=positive / len(stats),
        n=n,
        resamples=resamples,
        seed=seed,
    )


def permutation_significance(
    returns: tuple[float, ...],
    *,
    permutations: int = 2_000,
    alpha: float = 0.05,
    seed: int = 42,
    periods_per_year: int = 365,
) -> PermutationResult:
    """Sign-flip permutation test: H0 = symmetric zero-mean returns.

    The observed Sharpe is compared against the null distribution of Sharpe
    values from random sign flips (which preserves the return magnitudes
    while destroying any directional edge). Deterministic under ``seed``.
    """
    n = len(returns)
    if n < MIN_SAMPLE:
        raise ValueError(f"insufficient sample: {n} < {MIN_SAMPLE}")
    if len(set(returns)) == 1:
        return PermutationResult(
            observed_sharpe=0.0,
            null_mean_sharpe=0.0,
            p_value=1.0,
            verdict="INSUFFICIENT_EVIDENCE",
            n=n,
            permutations=permutations,
            seed=seed,
        )
    observed = _sharpe(returns, periods_per_year=periods_per_year)
    rng = random.Random(seed)
    exceed = 0
    null_sum = 0.0
    for _ in range(permutations):
        flipped = tuple(r * (1 if rng.random() < 0.5 else -1) for r in returns)
        s = _sharpe(flipped, periods_per_year=periods_per_year)
        null_sum += s
        if s >= observed:
            exceed += 1
    p_value = exceed / permutations
    verdict: Verdict = "SIGNIFICANT" if p_value < alpha else "NOT_SIGNIFICANT"
    return PermutationResult(
        observed_sharpe=observed,
        null_mean_sharpe=null_sum / permutations,
        p_value=p_value,
        verdict=verdict,
        n=n,
        permutations=permutations,
        seed=seed,
    )
