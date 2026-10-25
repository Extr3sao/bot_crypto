"""ALPHA-001 — statistical core and the preregistered hypothesis registry.

This module is the *falsification* toolkit for the economic alpha discovery
campaign: it holds no strategy logic and no data access, only the statistics the
campaign is allowed to use, plus the frozen hypothesis registry whose hash is
computed before any PnL is observed.

Design rules it encodes:

* **Preregistration first.**  ``HYPOTHESES`` is frozen; the registry hash is taken
  before discovery and may not change afterwards (no adding, no removing losers).
* **Economic, not statistical, admission.**  A hypothesis must clear
  ``min_gross_hurdle_bps`` — cost + execution uncertainty + winner's-curse buffer +
  statistical uncertainty — not merely a p-value.
* **Multiplicity is mandatory.**  Raw p-values are always reported with BH-FDR and
  Holm, and the best observed statistic is compared against a best-of-N null.
* **Underpowered is not negative.**  A small sample yields ``INCONCLUSIVE``, never
  "no alpha".
* **Concentration is a gate.**  An edge carried by one trade is not an edge.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "COST_BPS_V3",
    "EXECUTION_UNCERTAINTY_FRACTION",
    "FAMILIES",
    "HYPOTHESES",
    "WINNERS_CURSE_BUFFER_BPS",
    "benjamini_hochberg",
    "best_of_n_null",
    "concentration",
    "cost_frontier",
    "holm",
    "hypothesis_registry_hash",
    "mde_bps",
    "mean",
    "min_gross_hurdle_bps",
    "normal_two_sided_p",
    "pearson",
    "power_class",
    "sign_concentration",
    "spearman",
    "stability_by_window",
    "winners_curse_shrinkage",
]

# --------------------------------------------------------------------------- #
# §0 — economics
# --------------------------------------------------------------------------- #

#: The certified all-in cost (COST_MODEL_V3, RFC-023/026), in basis points per
#: round trip.  Frozen: execution optimisation cannot rescue weak alpha.
COST_BPS_V3 = 23.790569

#: Execution slippage on top of the modelled cost, as a fraction of it.
EXECUTION_UNCERTAINTY_FRACTION = 0.25

#: Expected selection inflation measured by RFC-023 (observed D→V drop ~ +8-9 bps).
WINNERS_CURSE_BUFFER_BPS = 8.121


def min_gross_hurdle_bps(
    *,
    n_effective: int,
    sigma_trade_bps: float,
    cost_bps: float = COST_BPS_V3,
    execution_fraction: float = EXECUTION_UNCERTAINTY_FRACTION,
    winners_curse_bps: float = WINNERS_CURSE_BUFFER_BPS,
    z: float = 1.959963985,
) -> dict[str, Any]:
    """The gross-alpha floor, derived before any result is observed.

    ``cost + execution uncertainty + winner's curse + statistical uncertainty``,
    where the statistical term is the standard error of a per-trade mean at the
    design sample size.  It answers: "what gross edge would we need to be able to
    *detect and keep* after costs?"
    """
    if n_effective <= 0:
        raise ValueError("n_effective must be > 0")
    if sigma_trade_bps <= 0:
        raise ValueError("sigma_trade_bps must be > 0")
    execution = cost_bps * execution_fraction
    statistical = z * sigma_trade_bps / math.sqrt(n_effective)
    total = cost_bps + execution + winners_curse_bps + statistical
    return {
        "cost_bps": round(cost_bps, 6),
        "execution_uncertainty_bps": round(execution, 6),
        "winners_curse_buffer_bps": round(winners_curse_bps, 6),
        "statistical_uncertainty_bps": round(statistical, 6),
        "min_gross_alpha_hurdle_bps": round(total, 6),
        "n_effective": int(n_effective),
        "sigma_trade_bps": round(sigma_trade_bps, 6),
        "z": z,
        "derivation": (
            "cost (COST_MODEL_V3 23.790569 bps) + 25% execution uncertainty + "
            "RFC-023 winner's-curse buffer (8.121 bps) + z_{0.975} * sigma_trade / sqrt(n_eff)"
        ),
    }


def cost_frontier(
    *,
    gross_bps: float,
    statistical_bps: float,
    cost_bps: float = COST_BPS_V3,
    execution_fraction: float = EXECUTION_UNCERTAINTY_FRACTION,
    winners_curse_bps: float = WINNERS_CURSE_BUFFER_BPS,
) -> dict[str, Any]:
    """How far the certified cost must fall before an observed edge becomes tradeable.

    The question this answers is not "is the alpha significant" but "is the cost the
    binding constraint".  Two frontiers are reported because they are the two honest
    readings of the same data:

    * ``net_break_even_cost_bps`` — the cost at which the *raw* average net PnL is
      zero (``gross - cost``).  Every safety margin is dropped: the most charitable
      reading available.
    * ``admission_break_even_cost_bps`` — the cost at which the *frozen admission
      rule* is exactly met, i.e. ``gross == cost * (1 + f) + w + s``.  Solving for
      the cost gives ``(gross - w - s) / (1 + f)``.  A **negative** value means no
      cost level whatsoever admits the cell: the venue would have to *pay* the
      strategy ``required_rebate_bps`` per round trip.

    ``path_to_viability`` names what could still admit the cell:

    * ``ADMISSIBLE`` — already clears the frozen rule.
    * ``COST_LIMITED`` — a cost cut alone would suffice; the required cut is
      ``cost_reduction_needed_fraction``.
    * ``SAMPLE_TOO_SMALL`` — the cost is *not* the binding constraint; the cell needs
      a smaller statistical term (more effective observations) because the point
      estimate does not even cover the non-cost part of the bar.
    * ``BELOW_SELECTION_BUFFER`` — the point estimate does not clear the winner's
      curse buffer on its own, so neither cheaper execution nor more data helps.

    The classification is arithmetic and conditional on the point estimate being the
    true effect.  A cell whose p-value does not survive multiplicity has no true
    effect to project, and the caller is expected to say so rather than read
    ``SAMPLE_TOO_SMALL`` as "collect more data".
    """
    if cost_bps < 0.0:
        raise ValueError("cost_bps must be >= 0")
    if statistical_bps < 0.0:
        raise ValueError("statistical_bps must be >= 0")
    if execution_fraction < 0.0:
        raise ValueError("execution_fraction must be >= 0")

    non_cost = winners_curse_bps + statistical_bps
    hurdle = cost_bps * (1.0 + execution_fraction) + non_cost
    break_even = (gross_bps - non_cost) / (1.0 + execution_fraction)
    required_rebate = max(0.0, -break_even)

    if cost_bps > 0.0:
        reduction: float | None = 1.0 - break_even / cost_bps
        net_reduction: float | None = 1.0 - gross_bps / cost_bps
    else:
        reduction = None
        net_reduction = None

    if gross_bps >= hurdle:
        path = "ADMISSIBLE"
    elif break_even >= 0.0:
        path = "COST_LIMITED"
    elif gross_bps > winners_curse_bps:
        path = "SAMPLE_TOO_SMALL"
    else:
        path = "BELOW_SELECTION_BUFFER"

    return {
        "gross_bps": round(gross_bps, 6),
        "cost_bps": round(cost_bps, 6),
        "execution_fraction": execution_fraction,
        "winners_curse_buffer_bps": round(winners_curse_bps, 6),
        "statistical_uncertainty_bps": round(statistical_bps, 6),
        "hurdle_bps": round(hurdle, 6),
        "admission_gap_bps": round(gross_bps - hurdle, 6),
        "admission_break_even_cost_bps": round(break_even, 6),
        "required_rebate_bps": round(required_rebate, 6),
        "cost_reduction_needed_fraction": (
            None if reduction is None else round(reduction, 6)
        ),
        "net_break_even_cost_bps": round(gross_bps, 6),
        "net_cost_reduction_needed_fraction": (
            None if net_reduction is None else round(net_reduction, 6)
        ),
        "admissible_at_zero_cost": gross_bps >= non_cost,
        "net_positive_at_zero_cost": gross_bps > 0.0,
        "path_to_viability": path,
    }


# --------------------------------------------------------------------------- #
# §1 — basic statistics
# --------------------------------------------------------------------------- #


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            ranks[order[position]] = average
        index = end + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx, my = mean(x), mean(y)
    dx = [value - mx for value in x]
    dy = [value - my for value in y]
    denom = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denom == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denom


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Rank IC, the standard information-coefficient measure."""
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    return pearson(_ranks(x), _ranks(y))


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def mde_bps(
    *, sigma_bps: float, n: int, alpha: float = 0.05, power: float = 0.8
) -> float:
    """Minimum detectable effect (bps) for a one-sided mean test at ``power``."""
    if n <= 0 or sigma_bps <= 0:
        return float("inf")
    z_alpha = 1.6448536269514722 if alpha == 0.05 else _probit(1.0 - alpha)
    z_beta = _probit(power)
    return (z_alpha + z_beta) * sigma_bps / math.sqrt(n)


def _probit(p: float) -> float:
    """Adequate inverse normal CDF (Acklam-style rational approximation)."""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    low, high = 0.02425, 1.0 - 0.02425
    if p < low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > high:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = p - 0.5
    r = q * q
    numerator = ((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]
    denominator = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
    return numerator * q / denominator


def effective_sample_size(series: Sequence[float]) -> float:
    """Autocorrelation-adjusted sample size (>0, ≤ n) for overlapping horizons."""
    n = len(series)
    if n < 3:
        return float(max(n, 1))
    mu = mean(series)
    var = sum((value - mu) ** 2 for value in series) / n
    if var <= 0.0:
        return float(n)
    factor = 1.0
    for lag in range(1, min(10, n - 1) + 1):
        cov = sum(
            (series[index] - mu) * (series[index - lag] - mu) for index in range(lag, n)
        ) / n
        rho = cov / var
        if rho <= 0.0:
            break
        factor += 2.0 * rho
    return max(1.0, n / factor)


def power_class(*, n_effective: float, sigma_bps: float, hurdle_bps: float) -> dict[str, float | str]:
    detectable = mde_bps(sigma_bps=sigma_bps, n=int(max(1, round(n_effective))))
    return {
        "n_effective": round(n_effective, 3),
        "mde_bps": round(detectable, 6),
        "hurdle_bps": round(hurdle_bps, 6),
        "class": "POWERED" if detectable <= hurdle_bps else "UNDERPOWERED",
    }


# --------------------------------------------------------------------------- #
# §2 — multiple testing and selection
# --------------------------------------------------------------------------- #


def benjamini_hochberg(pvalues: Sequence[float], q: float = 0.10) -> list[bool]:
    """BH-FDR step-up.  Returns a pass mask aligned with ``pvalues``."""
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda index: pvalues[index])
    passes = [False] * n
    threshold_rank = 0
    for rank, index in enumerate(order, start=1):
        if pvalues[index] <= q * rank / n:
            threshold_rank = rank
    for rank, index in enumerate(order, start=1):
        if rank <= threshold_rank:
            passes[index] = True
    return passes


def holm(pvalues: Sequence[float], alpha: float = 0.10) -> list[bool]:
    """Holm-Bonferroni step-down (FWER)."""
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda index: pvalues[index])
    passes = [False] * n
    for rank, index in enumerate(order, start=1):
        if pvalues[index] <= alpha / (n - rank + 1):
            passes[index] = True
        else:
            break
    return passes


def best_of_n_null(observed_best: float, null_best: Sequence[float]) -> dict[str, float]:
    """Compare the best observed statistic with the best-of-N under no alpha."""
    draws = sorted(null_best)
    n = len(draws)
    if n == 0:
        return {"draws": 0}
    def quantile(level: float) -> float:
        position = min(n - 1, max(0, math.ceil(level * n) - 1))
        return draws[position]
    at_least = sum(1 for value in draws if value >= observed_best)
    return {
        "draws": n,
        "null_median": round(quantile(0.50), 6),
        "null_p95": round(quantile(0.95), 6),
        "null_p99": round(quantile(0.99), 6),
        "null_max": round(draws[-1], 6),
        "observed_best": round(observed_best, 6),
        "p_null_best_ge_observed": round(at_least / n, 6),
        "significant_at_0_05": (at_least / n) < 0.05,
    }


def winners_curse_shrinkage(*, observed_best: float, null_best_median: float) -> dict[str, float]:
    """Selection-inflation shrinkage: never use the raw winner as an expectation."""
    inflation = max(0.0, null_best_median)
    shrunken = observed_best - inflation
    return {
        "observed_best_bps": round(observed_best, 6),
        "selection_inflation_bps": round(inflation, 6),
        "shrunken_edge_bps": round(shrunken, 6),
        "shrinkage_fraction": round(inflation / observed_best, 6) if observed_best else 0.0,
    }


# --------------------------------------------------------------------------- #
# §3 — concentration and stability
# --------------------------------------------------------------------------- #


def concentration(contributions: Sequence[float]) -> dict[str, Any]:
    """Trade-contribution concentration.  A single-trade edge is not an edge."""
    total = sum(contributions)
    ranked = sorted(contributions, reverse=True)
    def share(k: int) -> float:
        return sum(ranked[:k]) / total if total else 0.0
    top1 = share(1)
    top3 = share(3)
    top5 = share(5)
    net_ex_best = total - (ranked[0] if ranked else 0.0)
    classification = (
        "ROBUST"
        if (top1 <= 0.25 and top3 <= 0.60 and top5 <= 0.85 and net_ex_best > 0)
        else "FRAGILE"
    )
    return {
        "n_trades": len(contributions),
        "total": round(total, 6),
        "top1_share": round(top1, 6),
        "top3_share": round(top3, 6),
        "top5_share": round(top5, 6),
        "net_ex_best": round(net_ex_best, 6),
        "net_ex_top3": round(total - sum(ranked[:3]), 6),
        "classification": classification,
    }


def sign_concentration(contributions: Sequence[float]) -> dict[str, Any]:
    positive = [value for value in contributions if value > 0]
    negative = [value for value in contributions if value < 0]
    gross = sum(abs(value) for value in contributions)
    return {
        "positive_share": round(sum(positive) / gross, 6) if gross else 0.0,
        "negative_share": round(sum(abs(value) for value in negative) / gross, 6) if gross else 0.0,
        "hit_rate": round(len(positive) / len(contributions), 6) if contributions else 0.0,
    }


def stability_by_window(
    contributions: Sequence[float], *, windows: int = 4
) -> dict[str, Any]:
    """Per-sub-window gross mean.  Reported as-is: no retroactive filtering."""
    if windows <= 0 or not contributions:
        return {"windows": [], "n_positive": 0, "n_negative": 0, "consistent": False}
    size = math.ceil(len(contributions) / windows)
    chunks = [contributions[index : index + size] for index in range(0, len(contributions), size)]
    means = [mean(chunk) for chunk in chunks]
    positive = sum(1 for value in means if value > 0)
    negative = sum(1 for value in means if value < 0)
    return {
        "window_size": size,
        "windows": [round(value, 6) for value in means],
        "n_positive": positive,
        "n_negative": negative,
        "consistent": positive == len(means) or negative == len(means),
    }


# --------------------------------------------------------------------------- #
# §4 — the preregistered registry (frozen before discovery)
# --------------------------------------------------------------------------- #

FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "family_id": "F1_XSEC_DISPERSION",
        "mechanism": "cross-sectional dispersion of daily returns times the market",
        "orthogonality": "dispersion is a second-moment cross-sectional statistic, not return-ranked",
    },
    {
        "family_id": "F2_CROSS_ASSET_LEAD_LAG",
        "mechanism": "BTC's lagged return predicts the alt basket (leader-follower)",
        "orthogonality": "uses cross-asset timing, not the asset's own history",
    },
    {
        "family_id": "F3_MARKET_BREADTH",
        "mechanism": "breadth (share of universe above its own MA) times the market",
        "orthogonality": "aggregate participation, not a price pattern",
    },
    {
        "family_id": "F4_RELATIVE_VOLATILITY",
        "mechanism": "short/long realised-vol ratio as a cross-sectional and time-series conditioner",
        "orthogonality": "vol-of-vol; magnitudes only, tested here for direction too",
    },
    {
        "family_id": "F5_VOL_SHOCK_ASYMMETRY",
        "mechanism": "post volatility-shock directional asymmetry (up-shocks vs down-shocks)",
        "orthogonality": "conditions on the sign of a shock, not its magnitude",
    },
    {
        "family_id": "F6_SESSION_STRUCTURE",
        "mechanism": "intraday session structure in 24/7 crypto (bar-of-day effects)",
        "orthogonality": "clock-based conditioning, no price pattern",
    },
)

#: Frozen before discovery.  The hash below is computed from this exact tuple.
HYPOTHESES: tuple[dict[str, Any], ...] = (
    {
        "hypothesis_id": "A1-H01",
        "family_id": "F1_XSEC_DISPERSION",
        "mechanism": "high cross-sectional dispersion precedes negative market returns",
        "inputs": ["daily close panel"],
        "signal": "cross-sectional std of 1d returns across the universe",
        "direction": "SHORT_MARKET_WHEN_DISPERSION_HIGH",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"lookback_days": 1},
        "expected_turnover_per_day": 0.5,
        "invalidation": "signal has no monotone relation to the forward market return",
        "expected_failure_mode": "dispersion is a volatility proxy already known to carry magnitude only",
    },
    {
        "hypothesis_id": "A1-H02",
        "family_id": "F1_XSEC_DISPERSION",
        "mechanism": "rising dispersion precedes basket weakness",
        "inputs": ["daily close panel"],
        "signal": "1d change in cross-sectional dispersion",
        "direction": "SHORT_BASKET_WHEN_DISPERSION_RISES",
        "assets": "EQUAL_WEIGHT_BASKET",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"lookback_days": 1},
        "expected_turnover_per_day": 0.5,
        "invalidation": "no relation between dispersion change and basket forward return",
        "expected_failure_mode": "too small relative to cost",
    },
    {
        "hypothesis_id": "A1-H03",
        "family_id": "F2_CROSS_ASSET_LEAD_LAG",
        "mechanism": "BTC leads the alt basket by one day",
        "inputs": ["daily close panel"],
        "signal": "BTC 1d return at t",
        "direction": "LONG_ALT_BASKET_WHEN_BTC_UP",
        "assets": "ALT_EQUAL_WEIGHT_BASKET",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"lag_days": 1},
        "expected_turnover_per_day": 0.7,
        "invalidation": "no positive relation between BTC lagged return and alt forward return",
        "expected_failure_mode": "contemporaneous correlation rather than tradable lead",
    },
    {
        "hypothesis_id": "A1-H04",
        "family_id": "F2_CROSS_ASSET_LEAD_LAG",
        "mechanism": "BTC leads the alt basket by two to three days",
        "inputs": ["daily close panel"],
        "signal": "BTC 3d cumulative return at t",
        "direction": "LONG_ALT_BASKET_WHEN_BTC_3D_UP",
        "assets": "ALT_EQUAL_WEIGHT_BASKET",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"lag_days": 3},
        "expected_turnover_per_day": 0.4,
        "invalidation": "no relation between BTC 3d return and alt forward return",
        "expected_failure_mode": "alt moves are simultaneous, not lagged",
    },
    {
        "hypothesis_id": "A1-H05",
        "family_id": "F3_MARKET_BREADTH",
        "mechanism": "breadth above its midline precedes market strength",
        "inputs": ["daily close panel"],
        "signal": "share of universe trading above its own 20d MA",
        "direction": "LONG_MARKET_WHEN_BREADTH_HIGH",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "holding_horizon_days": 3,
        "parameters": {"ma_days": 20},
        "expected_turnover_per_day": 0.2,
        "invalidation": "breadth carries no information about the forward market return",
        "expected_failure_mode": "breadth is a lagging aggregate of price",
    },
    {
        "hypothesis_id": "A1-H06",
        "family_id": "F3_MARKET_BREADTH",
        "mechanism": "breadth thrust precedes basket strength",
        "inputs": ["daily close panel"],
        "signal": "5d change in breadth",
        "direction": "LONG_BASKET_WHEN_BREADTH_RISES",
        "assets": "EQUAL_WEIGHT_BASKET",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"change_days": 5},
        "expected_turnover_per_day": 0.4,
        "invalidation": "no relation between breadth change and basket forward return",
        "expected_failure_mode": "too small relative to cost",
    },
    {
        "hypothesis_id": "A1-H07",
        "family_id": "F4_RELATIVE_VOLATILITY",
        "mechanism": "cross-sectional low relative volatility outperforms",
        "inputs": ["daily close panel"],
        "signal": "rank of 5d/20d realised-vol ratio across the universe",
        "direction": "LONG_LOW_VOL_RATIO / SHORT_HIGH_VOL_RATIO",
        "assets": "UNIVERSE_CROSS_SECTION",
        "timeframe": "1D",
        "holding_horizon_days": 5,
        "parameters": {"short_window": 5, "long_window": 20},
        "expected_turnover_per_day": 0.2,
        "invalidation": "no monotone relation between the vol ratio and forward return",
        "expected_failure_mode": "vol ratio is magnitude-only (RFC-023)",
    },
    {
        "hypothesis_id": "A1-H08",
        "family_id": "F4_RELATIVE_VOLATILITY",
        "mechanism": "a vol spike above its own norm precedes negative drift",
        "inputs": ["daily close panel"],
        "signal": "BTC 5d/20d realised-vol ratio",
        "direction": "SHORT_BTC_WHEN_VOL_RATIO_HIGH",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"short_window": 5, "long_window": 20},
        "expected_turnover_per_day": 0.3,
        "invalidation": "no relation between the vol ratio and forward BTC return",
        "expected_failure_mode": "magnitude-only, already falsified directionally",
    },
    {
        "hypothesis_id": "A1-H09",
        "family_id": "F5_VOL_SHOCK_ASYMMETRY",
        "mechanism": "up-shocks continue, down-shocks continue (positive asymmetry)",
        "inputs": ["daily close panel"],
        "signal": "sign of the daily return on a >2 sigma volatility-shock day",
        "direction": "LONG_AFTER_UP_SHOCK / SHORT_AFTER_DOWN_SHOCK",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"shock_z": 2.0, "vol_window": 20},
        "expected_turnover_per_day": 0.1,
        "invalidation": "shock sign carries no forward directional information",
        "expected_failure_mode": "shock days are rare, so the sample is small",
    },
    {
        "hypothesis_id": "A1-H10",
        "family_id": "F5_VOL_SHOCK_ASYMMETRY",
        "mechanism": "down-shocks reverse, up-shocks continue (asymmetric reversal)",
        "inputs": ["daily close panel"],
        "signal": "sign of the daily return on a >2 sigma volatility-shock day",
        "direction": "LONG_AFTER_DOWN_SHOCK / SHORT_AFTER_UP_SHOCK",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "holding_horizon_days": 1,
        "parameters": {"shock_z": 2.0, "vol_window": 20},
        "expected_turnover_per_day": 0.1,
        "invalidation": "shock sign carries no forward directional information",
        "expected_failure_mode": "shock days are rare, so the sample is small",
    },
    {
        "hypothesis_id": "A1-H11",
        "family_id": "F6_SESSION_STRUCTURE",
        "mechanism": "the first 4h bar of the UTC day predicts the next 4h bar",
        "inputs": ["4h close panel"],
        "signal": "BTC 00:00-04:00 UTC 4h return",
        "direction": "TRADE_IN_THE_DIRECTION_OF_THE_FIRST_BAR",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "4h",
        "holding_horizon_days": 0.167,
        "parameters": {"session_hours": [0, 4]},
        "expected_turnover_per_day": 6.0,
        "invalidation": "no relation between the first bar and the next bar",
        "expected_failure_mode": "6x daily turnover ⇒ cost dominates by construction",
    },
    {
        "hypothesis_id": "A1-H12",
        "family_id": "F6_SESSION_STRUCTURE",
        "mechanism": "the 12:00-16:00 UTC bar reverses in the next 4h bar",
        "inputs": ["4h close panel"],
        "signal": "BTC 12:00-16:00 UTC 4h return",
        "direction": "FADE_THE_EUROPEAN_AFTERNOON_BAR",
        "assets": "BINANCE:BTCUSDT",
        "timeframe": "4h",
        "holding_horizon_days": 0.167,
        "parameters": {"session_hours": [12, 16]},
        "expected_turnover_per_day": 6.0,
        "invalidation": "no relation between the afternoon bar and the next bar",
        "expected_failure_mode": "6x daily turnover ⇒ cost dominates by construction",
    },
)


def hypothesis_registry_hash(
    *, hypotheses: Sequence[Mapping[str, Any]] = HYPOTHESES, families: Sequence[Mapping[str, Any]] = FAMILIES
) -> str:
    """Stable hash of the registry (adding or removing a hypothesis changes it)."""
    import hashlib
    import json

    payload = json.dumps(
        {"families": list(families), "hypotheses": list(hypotheses)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
