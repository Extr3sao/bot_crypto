"""ARC-03 frozen statistical gate calculators (EXECUTION implementation).

Every function in this module is a direct transcription of the conventions frozen in
``docs/arc03-prereg-01/ARC03_STATISTICAL_GATES.json`` (commit 8ebf8a181a3cfaf03737ef585f8906d28f8d419f,
re-verified at 2dfe96c88fd66953d3fee148415e2e837c1bd2c7). No runtime defaults, no
alternative estimators. Each gate is a pure function of its inputs plus the frozen
constants below.

Conventions implemented (frozen):

* sample std with ddof=1
* Sharpe: mean/std(ddof=1) * sqrt(trades_per_year); trades_per_year = N / (window_span_days / 365.0);
  window_span_days is the FROZEN CONSTANT (end - start + 300000) / 86400000, not trade-derived;
  zero variance or N < 2 => Sharpe 0.0 and G5 FAILS
* profit factor: sum(positive nets) / -sum(negative nets); gross_loss == 0 and gross_profit > 0
  => +inf (PASS); both zero => FAIL; threshold >= 1.15
* bootstrap: i.i.d. trade resampling with replacement, R = 10000, seed 20260915,
  random.Random.randrange(N) in sequence per resample, percentile CI with
  lower_idx = max(0, floor(0.025 * R)); gate: ci_lower > 0
* permutation: one-sided upper tail sign-flip null, draws = 10000, seed 20260915,
  p = #{null mean >= observed mean} / draws (no +1 correction); gate: p <= 0.05
* temporal stability: equal-count chronological halves [0, N//2) / [N//2, N) both means > 0,
  and >= 3 of 4 equal-count chronological quartiles with means > 0; N < 4 or empty group => FAIL
* asset stability: >= 2 of 3 per-asset mean net returns > 0
* concentration: shares of total net (must be > 0) by asset, by UTC entry month, and by
  single trade; thresholds 0.60 / 0.40 / 0.25
* cost sensitivity: mean net @20bps > 0 AND mean net @40bps >= 0 on the identical trade set
* G1 sample: N >= 120 AND min per-asset N >= 40
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

#: Frozen constants (ARC03_STATISTICAL_GATES.json / ARC03_SPEC_V1.json).
BOOTSTRAP_SEED = 20260915
BOOTSTRAP_RESAMPLES = 10_000
PERMUTATION_SEED = 20260915
PERMUTATION_DRAWS = 10_000
BOOTSTRAP_CONFIDENCE = 0.95
PRIMARY_COST_BPS = 10
G1_MIN_TOTAL_TRADES = 120
G1_MIN_TRADES_PER_ASSET = 40
G4_MIN_PROFIT_FACTOR = 1.15
G5_MIN_SHARPE = 0.50
PERMUTATION_MAX_P = 0.05
MAX_ASSET_SHARE = 0.60
MAX_MONTH_SHARE = 0.40
MAX_SINGLE_TRADE_SHARE = 0.25
BAR_MS = 300_000
DAY_MS = 86_400_000

#: Frozen common window (prereg): start 2020-09-14T07:00:00Z, end 2026-08-31T23:55:00Z.
WINDOW_START_MS = 1_600_066_800_000
WINDOW_END_MS = 1_788_220_500_000
WINDOW_SPAN_DAYS = (WINDOW_END_MS - WINDOW_START_MS + BAR_MS) / DAY_MS  # 2177.7083333333335

ASSET_ORDER: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


# ----------------------------------------------------------------------------- helpers
def sample_std(xs: Sequence[float]) -> float:
    """sqrt(sum((x - mean)^2) / (n - 1)) — ddof=1, frozen."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = math.fsum(xs) / n
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (n - 1))


def annualized_sharpe(net_returns: Sequence[float]) -> tuple[float, bool]:
    """Frozen annualized Sharpe. Returns (sharpe, evaluable).

    ``evaluable`` is False (and sharpe 0.0) when N < 2 or sample_std == 0 — G5 FAILS.
    """
    n = len(net_returns)
    if n < 2:
        return 0.0, False
    std = sample_std(net_returns)
    if std == 0.0:
        return 0.0, False
    mean = math.fsum(net_returns) / n
    trades_per_year = n / (WINDOW_SPAN_DAYS / 365.0)
    return mean / std * math.sqrt(trades_per_year), True


def profit_factor(net_returns: Sequence[float]) -> tuple[float, bool]:
    """Frozen profit factor. Returns (pf, evaluable).

    gross_loss == 0 and gross_profit > 0 => (+inf, True); gross_profit == 0 too => (inf, False).
    """
    gross_profit = math.fsum(r for r in net_returns if r > 0.0)
    gross_loss = -math.fsum(r for r in net_returns if r < 0.0)
    if gross_loss == 0.0:
        if gross_profit > 0.0:
            return math.inf, True
        return math.inf, False
    return gross_profit / gross_loss, True


def bootstrap_ci_lower(net_returns: Sequence[float]) -> tuple[float, float, bool]:
    """Frozen bootstrap. Returns (ci_lower, p_bootstrap_mean_positive, evaluable).

    Degenerate (all returns identical) => (0.0, ..., False) — G6 FAILS fail-closed.
    """
    n = len(net_returns)
    if n == 0:
        return 0.0, 0.0, False
    lo = min(net_returns)
    hi = max(net_returns)
    if lo == hi:
        return 0.0, (1.0 if lo > 0 else 0.0), False
    rng = random.Random(BOOTSTRAP_SEED)
    stats: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        acc = 0.0
        for _ in range(n):
            acc += net_returns[rng.randrange(n)]
        stats.append(acc / n)
    stats.sort()
    lower_idx = max(0, math.floor((1.0 - BOOTSTRAP_CONFIDENCE) / 2.0 * BOOTSTRAP_RESAMPLES))
    ci_lower = stats[lower_idx]
    p_positive = sum(1 for s in stats if s > 0.0) / BOOTSTRAP_RESAMPLES
    return ci_lower, p_positive, True


def permutation_p(net_returns: Sequence[float]) -> tuple[float, bool]:
    """Frozen one-sided sign-flip permutation p-value. Returns (p, evaluable).

    Degenerate (all returns identical) => (1.0, False) — G7 FAILS fail-closed.
    """
    n = len(net_returns)
    if n == 0:
        return 1.0, False
    lo = min(net_returns)
    hi = max(net_returns)
    if lo == hi:
        return 1.0, False
    observed = math.fsum(net_returns) / n
    rng = random.Random(PERMUTATION_SEED)
    exceed = 0
    for _ in range(PERMUTATION_DRAWS):
        acc = 0.0
        for r in net_returns:
            acc += r * (1.0 if rng.random() < 0.5 else -1.0)
        if acc / n >= observed:
            exceed += 1
    return exceed / PERMUTATION_DRAWS, True


# ----------------------------------------------------------------------------- gates
@dataclass(frozen=True)
class TradeRecord:
    """Minimal per-trade record the gate evaluators need (frozen emission order)."""

    trade_id: str
    asset: str
    entry_time_ms: int
    net_return: float
    net_return_ex_funding: float


@dataclass
class GateResult:
    gate_id: str
    metric: Any
    threshold: str
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)


def _temporal_stability(ordered_returns: Sequence[float]) -> GateResult:
    n = len(ordered_returns)
    halves_ok = False
    quartiles_ok = False
    halves: list[float | None] = [None, None]
    quartiles: list[float | None] = [None, None, None, None]
    detail: dict[str, Any] = {"n": n}
    if n >= 2:
        h = n // 2
        if h > 0 and (n - h) > 0:
            first = math.fsum(ordered_returns[:h]) / h
            second = math.fsum(ordered_returns[h:]) / (n - h)
            halves = [first, second]
            halves_ok = first > 0.0 and second > 0.0
    if n >= 4:
        bounds = [math.floor(k * n / 4) for k in range(5)]
        means: list[float] = []
        for k in range(4):
            seg = ordered_returns[bounds[k] : bounds[k + 1]]
            if not seg:
                means = []
                break
            means.append(math.fsum(seg) / len(seg))
        if means:
            quartiles = means  # type: ignore[assignment]
            quartiles_ok = sum(1 for m in means if m > 0.0) >= 3
    detail.update(halves=halves, quartiles=quartiles)
    return GateResult(
        "G8_TEMPORAL_STABILITY",
        {"halves": halves, "quartiles": quartiles},
        "both halves > 0 AND >= 3 of 4 quartiles > 0",
        halves_ok and quartiles_ok,
        detail,
    )


def _asset_stability(records: Sequence[TradeRecord]) -> GateResult:
    per_asset: dict[str, list[float]] = {a: [] for a in ASSET_ORDER}
    for r in records:
        per_asset.setdefault(r.asset, []).append(r.net_return)
    means = {a: (math.fsum(v) / len(v) if v else None) for a, v in per_asset.items()}
    positive = sum(1 for m in means.values() if m is not None and m > 0.0)
    return GateResult(
        "G9_ASSET_STABILITY",
        means,
        ">= 2 of 3 assets mean net > 0",
        positive >= 2,
        {"positive_assets": positive},
    )


def _utc_month(entry_time_ms: int) -> str:
    secs = entry_time_ms // 1000
    days = secs // 86400
    # civil-from-days (Howard Hinnant's algorithm), UTC only.
    z = days + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    m = mp + (3 if mp < 10 else -9)
    return f"{y + (1 if m <= 2 else 0):04d}-{m:02d}"


def _concentration(records: Sequence[TradeRecord]) -> GateResult:
    total_net = math.fsum(r.net_return for r in records)
    if total_net <= 0.0:
        return GateResult(
            "G10_CONCENTRATION",
            {"total_net": total_net},
            "asset <= 0.60 AND month <= 0.40 AND single trade <= 0.25",
            False,
            {"reason": "TOTAL_NET_NOT_POSITIVE"},
        )
    by_asset: dict[str, float] = {}
    by_month: dict[str, float] = {}
    for r in records:
        by_asset[r.asset] = by_asset.get(r.asset, 0.0) + r.net_return
        by_month[_utc_month(r.entry_time_ms)] = by_month.get(_utc_month(r.entry_time_ms), 0.0) + r.net_return
    max_asset_share = max(by_asset.values()) / total_net
    max_month_share = max(by_month.values()) / total_net
    max_single_share = max(r.net_return for r in records) / total_net
    passed = (
        max_asset_share <= MAX_ASSET_SHARE
        and max_month_share <= MAX_MONTH_SHARE
        and max_single_share <= MAX_SINGLE_TRADE_SHARE
    )
    return GateResult(
        "G10_CONCENTRATION",
        {
            "max_asset_share": max_asset_share,
            "max_calendar_month_share": max_month_share,
            "max_single_trade_share": max_single_share,
        },
        "asset <= 0.60 AND month <= 0.40 AND single trade <= 0.25",
        passed,
        {"total_net": total_net, "by_asset": by_asset, "by_month": by_month},
    )


def _cost_sensitivity(mean_20: float, mean_40: float) -> GateResult:
    passed = mean_20 > 0.0 and mean_40 >= 0.0
    return GateResult(
        "G11_COST_SENSITIVITY",
        {"mean_net_20bps": mean_20, "mean_net_40bps": mean_40},
        "mean_20bps > 0 AND mean_40bps >= 0",
        passed,
    )


def evaluate_gates(
    records: Sequence[TradeRecord],
    *,
    net_returns_20bps: Sequence[float] | None = None,
    net_returns_40bps: Sequence[float] | None = None,
) -> list[GateResult]:
    """Evaluate ALL critical gates G1..G11 on one trade set (frozen emission order).

    ``net_returns_20bps`` / ``net_returns_40bps`` must be the SAME trade set re-priced;
    they default to ``records``' net returns (only valid when the caller passes them
    explicitly for the primary experiment).
    """
    n = len(records)
    nets = [r.net_return for r in records]
    nets_ex = [r.net_return_ex_funding for r in records]

    per_asset_counts: dict[str, int] = {a: 0 for a in ASSET_ORDER}
    for r in records:
        per_asset_counts[r.asset] = per_asset_counts.get(r.asset, 0) + 1
    min_asset = min(per_asset_counts.values()) if per_asset_counts else 0
    g1 = GateResult(
        "G1_SAMPLE",
        {"n_total": n, "per_asset": per_asset_counts},
        f"N >= {G1_MIN_TOTAL_TRADES} AND min per-asset >= {G1_MIN_TRADES_PER_ASSET}",
        n >= G1_MIN_TOTAL_TRADES and min_asset >= G1_MIN_TRADES_PER_ASSET,
        {"min_per_asset": min_asset},
    )

    mean_net = math.fsum(nets) / n if n else 0.0
    g2 = GateResult("G2_NET_EXPECTANCY", mean_net, "> 0.0", n > 0 and mean_net > 0.0)

    mean_ex = math.fsum(nets_ex) / n if n else 0.0
    g3 = GateResult("G3_NET_EXPECTANCY_EX_FUNDING", mean_ex, "> 0.0", n > 0 and mean_ex > 0.0)

    pf, pf_evaluable = profit_factor(nets)
    g4 = GateResult(
        "G4_PROFIT_FACTOR",
        pf if math.isfinite(pf) else "Infinity",
        ">= 1.15",
        pf_evaluable and pf >= G4_MIN_PROFIT_FACTOR,
    )

    sharpe, sharpe_evaluable = annualized_sharpe(nets)
    g5 = GateResult(
        "G5_SHARPE",
        sharpe,
        ">= 0.50",
        sharpe_evaluable and sharpe >= G5_MIN_SHARPE,
        {"window_span_days": WINDOW_SPAN_DAYS, "n": n},
    )

    ci_lower, p_boot, boot_evaluable = bootstrap_ci_lower(nets)
    g6 = GateResult(
        "G6_BOOTSTRAP",
        ci_lower,
        "ci_lower > 0.0",
        boot_evaluable and ci_lower > 0.0,
        {"p_bootstrap_mean_positive": p_boot, "resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED},
    )

    p_perm, perm_evaluable = permutation_p(nets)
    g7 = GateResult(
        "G7_PERMUTATION",
        p_perm,
        "p <= 0.05",
        perm_evaluable and p_perm <= PERMUTATION_MAX_P,
        {"draws": PERMUTATION_DRAWS, "seed": PERMUTATION_SEED, "statistic": "MEAN net (not Sharpe)"},
    )

    g8 = _temporal_stability(nets)
    g9 = _asset_stability(records)
    g10 = _concentration(records)

    nets20 = list(net_returns_20bps) if net_returns_20bps is not None else nets
    nets40 = list(net_returns_40bps) if net_returns_40bps is not None else nets
    mean20 = math.fsum(nets20) / len(nets20) if nets20 else 0.0
    mean40 = math.fsum(nets40) / len(nets40) if nets40 else 0.0
    g11 = _cost_sensitivity(mean20, mean40)

    return [g1, g2, g3, g4, g5, g6, g7, g8, g9, g10, g11]


def all_critical_gates_pass(results: Sequence[GateResult]) -> bool:
    return bool(results) and all(g.passed for g in results)
