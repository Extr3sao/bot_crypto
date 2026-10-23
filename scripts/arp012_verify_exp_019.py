"""ARP-012 — EXP-ARP-019 INDEPENDENT ECONOMIC VERIFICATION driver.

Role: INDEPENDENT VERIFIER (BUILDER != VERIFIER). Rebuilds the DEV/VALIDATION/FULL
ledgers from raw bars using the *frozen* strategy, then recomputes every economic
metric with verifier-owned code (never the builder's aggregate parser:
``xsec_riskadj.summarize_positions`` is NOT used for any reported number here).

Writes ``reports/arp-012-exp-019-independent/``.

No OOS. No strategy/threshold/asset/universe/cost/split modification.

Run::

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp012_verify_exp_019.py
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_recovery.campaign import cost_model_v3_rt_bps  # noqa: E402
from trading_bot.research.diversified import analytics as A  # noqa: E402
from trading_bot.research.diversified import breadth as B  # noqa: E402
from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified.universe import (  # noqa: E402
    DynamicAssetUniverse,
    UniverseConfig,
)
from trading_bot.research.governance import (  # noqa: E402
    HoldoutRegistry,
    HoldoutStatus,
    SplitDefinition,
)

OUT = REPO / "reports" / "arp-012-exp-019-independent"
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-019"
POST_OOS = REPO / "reports" / "post-oos-recovery"
ARP011 = REPO / "reports" / "arp-011-exp-019"

EXPERIMENT_ID = "EXP-ARP-019"
STRATEGY_ID = "H-BREADTH-REGIME-001"
HOLDOUT_ID = "HOLDOUT-ARP-019-FORWARD"
BPS = 10_000.0
NOTIONAL = 500.0
DAY = 86_400_000
HORIZONS = (1, 5, 10, 20, 30)
SEEDS = tuple(range(1000, 1020))  # fixed recorded seeds for the random control

FROZEN_SPLIT = SplitDefinition(
    "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2026-03-01", "2027-03-01"
)

BUILDER_FILES = (
    "src/trading_bot/research/diversified/__init__.py",
    "src/trading_bot/research/diversified/data.py",
    "src/trading_bot/research/diversified/universe.py",
    "src/trading_bot/research/diversified/breadth.py",
    "src/trading_bot/research/alpha_expansion/strategies.py",
)


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "unknown"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hash() -> str:
    h = hashlib.sha256()
    for rel in BUILDER_FILES:
        p = REPO / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Verifier-owned metric functions (§4, §6, §7, §15)
# --------------------------------------------------------------------------- #
def episode_groups(trades: list[Any]) -> list[dict[str, Any]]:
    """Group per-constituent trades into basket episodes keyed by entry_ts."""
    by_entry: dict[int, list[Any]] = defaultdict(list)
    for t in trades:
        by_entry[t.entry_ts].append(t)
    groups: list[dict[str, Any]] = []
    for entry_ts in sorted(by_entry):
        ts = by_entry[entry_ts]
        exit_ts = max(t.exit_ts for t in ts)
        alloc_sum = sum(t.notional for t in ts)
        gross = sum(t.gross for t in ts)
        fees = sum(t.fees for t in ts)
        net = sum(t.net for t in ts)
        groups.append(
            {
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "n": len(ts),
                "alloc_sum": alloc_sum,
                "gross_usd": gross,
                "fees_usd": fees,
                "net_usd": net,
                "portfolio_bps": net / NOTIONAL * BPS,
                # basket return on the *deployed* capital (alloc_sum), the honest
                # per-episode return of the capital actually at work
                "deployed_bps": net / alloc_sum * BPS if alloc_sum else 0.0,
            }
        )
    return groups


def v_metrics(trades: list[Any]) -> dict[str, Any]:
    """Everything recomputed independently — no builder summariser."""
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    gross_usd = sum(t.gross for t in trades)
    fees_usd = sum(t.fees for t in trades)
    net_usd = sum(t.net for t in trades)
    net_bps = [t.net / t.notional * BPS for t in trades if t.notional]
    gross_bps = [t.gross / t.notional * BPS for t in trades if t.notional]
    pos = [t.net for t in trades if t.net > 0]
    neg = [t.net for t in trades if t.net < 0]
    positives_bps = [x for x in net_bps if x > 0]
    losses_bps = [x for x in net_bps if x <= 0]
    groups = episode_groups(trades)
    # drawdown reproduced: cumulative NON-compounding net sequence in emission order
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for t in trades:
        equity += t.net
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    pf = sum(pos) / abs(sum(neg)) if neg else None
    return {
        "trades": n,
        "episodes": len(groups),
        "total_gross_pnl_usd": round(gross_usd, 2),
        "total_net_pnl_usd": round(net_usd, 2),
        "total_fees_usd": round(fees_usd, 2),
        "avg_net_pnl_per_trade_usd": round(net_usd / n, 4),
        "avg_gross_pnl_per_trade_usd": round(gross_usd / n, 4),
        "avg_net_return_bps_per_trade": round(statistics.fmean(net_bps), 3),
        "median_net_return_bps_per_trade": round(statistics.median(net_bps), 3),
        "avg_gross_return_bps_per_trade": round(statistics.fmean(gross_bps), 3),
        "portfolio_return_bps": round(net_usd / NOTIONAL * BPS, 3),
        "gross_profit_usd": round(sum(pos), 2),
        "gross_loss_usd": round(sum(neg), 2),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "win_rate": round(len(positives_bps) / n, 4),
        "payoff": round(statistics.fmean(positives_bps) / abs(statistics.fmean(losses_bps)), 4)
        if positives_bps and losses_bps
        else None,
        "pnl_drawdown_bps_of_reference_notional": round(worst / NOTIONAL * BPS, 3),
        "avg_alloc_per_position": round(statistics.fmean([t.notional for t in trades]), 4),
    }


def equity_curve(trades: list[Any], calendar: list[int], corpus: dict[str, Any]) -> dict[str, Any]:
    """True daily mark-to-market equity curve for the fixed-500 non-compounding model.

    equity(d) = 500 + realised net of closed episodes + unrealised gross of open
    episodes (marked at close_d). Fees are recognised at episode exit (round-trip).
    """
    idx = {s: {b.timestamp: b for b in bars} for s, bars in corpus.items()}
    groups = episode_groups(trades)
    # episode lookups
    closed: list[dict[str, Any]] = groups
    days = list(calendar)
    realized = 0.0
    ci = 0
    curve: list[tuple[int, float]] = []
    closed_sorted = sorted(closed, key=lambda g: g["exit_ts"])
    for d in days:
        # realise any episode whose exit_ts <= d
        while ci < len(closed_sorted) and closed_sorted[ci]["exit_ts"] <= d:
            realized += closed_sorted[ci]["net_usd"]
            ci += 1
        unreal = 0.0
        for g in closed:
            if g["entry_ts"] <= d < g["exit_ts"]:
                for t in trades:
                    if t.entry_ts == g["entry_ts"] and t.symbol in idx:
                        bar = idx[t.symbol].get(d)
                        if bar is not None and t.entry > 0:
                            unreal += t.notional * (bar.close / t.entry - 1.0)
                        break
        eq = NOTIONAL + realized + unreal
        curve.append((d, eq))
    peak = -1e18
    trough_after_peak = 0.0
    maxdd = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        trough_after_peak = peak - eq
        maxdd = max(maxdd, trough_after_peak)
    final = curve[-1][1] if curve else NOTIONAL
    return {
        "start_equity_usd": NOTIONAL,
        "final_equity_usd": round(final, 4),
        "equity_return_bps": round((final - NOTIONAL) / NOTIONAL * BPS, 3),
        "equity_max_drawdown_usd": round(maxdd, 4),
        "equity_max_drawdown_bps": round(maxdd / NOTIONAL * BPS, 3),
        "capital_model": "fixed 500 USD per basket episode, non-compounding, 1x long-only",
    }


# --------------------------------------------------------------------------- #
# Beta / timing alpha (§18, §19)
# --------------------------------------------------------------------------- #
def beta_regression(trades: list[Any], btc_bars: list[Any]) -> dict[str, Any]:
    idx = {b.timestamp: b for b in btc_bars}
    xs: list[float] = []
    ys: list[float] = []
    ws: list[float] = []  # holding duration weight (days)
    entry_days: list[int] = []
    for t in trades:
        b0 = idx.get(t.entry_ts)
        b1 = idx.get(t.exit_ts)
        if b0 is None or b1 is None or b0.close <= 0 or not t.notional:
            continue
        xs.append(b1.close / b0.close - 1.0)
        ys.append(t.gross / t.notional)
        ws.append((t.exit_ts - t.entry_ts) / DAY)
        entry_days.append(t.entry_ts)
    n = len(xs)
    if n < 3:
        return {"observations": n, "market_beta": None}
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    beta = sxy / sxx if sxx > 0 else 0.0
    resid = [y - beta * x for x, y in zip(xs, ys, strict=True)]
    resid_mean = sum(resid) / n
    resid_sd = math.sqrt(sum(r * r for r in resid) / n)
    se_naive = resid_sd / math.sqrt(n)
    # intercept-included OLS for comparison
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx_c = sum((x - mx) ** 2 for x in xs)
    sxy_c = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    slope_c = sxy_c / sxx_c if sxx_c > 0 else 0.0
    intercept = my - slope_c * mx
    # t of intercept via residual variance of the with-intercept fit
    resid_c = [y - (slope_c * x + intercept) for x, y in zip(xs, ys, strict=True)]
    s2 = sum(r * r for r in resid_c) / max(1, n - 2)
    se_intercept = math.sqrt(s2 * (1.0 / n + mx * mx / sxx_c)) if sxx_c > 0 else float("nan")
    # cluster the residuals by entry day to respect basket dependence
    by_day: dict[int, list[float]] = defaultdict(list)
    for r, ed in zip(resid, entry_days, strict=True):
        by_day[ed].append(r)
    day_means = [statistics.fmean(v) for v in by_day.values()]
    n_days = len(day_means)
    se_cluster = statistics.pstdev(day_means) / math.sqrt(n_days) if n_days > 2 else float("nan")
    return {
        "observations": n,
        "dependent_variable": "per-position GROSS return = gross/notional over [entry_ts, exit_ts]",
        "independent_variable": "BTCUSDT close-to-close return over the SAME window",
        "frequency": "per asset-position episode (not per calendar period)",
        "intercept": "forced through origin (no intercept) in the builder's report",
        "sample": "all DEV+VALIDATION per-position episodes",
        "market_beta": round(beta, 4),
        "timing_alpha_residual_mean": round(resid_mean, 6),
        "residual_stdev": round(resid_sd, 6),
        "se_naive_per_position": round(se_naive, 6),
        "n_distinct_entry_days": n_days,
        "se_clustered_by_entry_day": round(se_cluster, 6) if se_cluster == se_cluster else None,
        "t_naive": round(resid_mean / se_naive, 3) if se_naive else None,
        "t_clustered": round(resid_mean / se_cluster, 3)
        if se_cluster == se_cluster and se_cluster
        else None,
        "ols_with_intercept_slope": round(slope_c, 4),
        "ols_with_intercept_intercept": round(intercept, 6),
        "ols_with_intercept_se_intercept": round(se_intercept, 6)
        if se_intercept == se_intercept
        else None,
        "ols_with_intercept_t": round(intercept / se_intercept, 3)
        if se_intercept == se_intercept and se_intercept
        else None,
    }


# --------------------------------------------------------------------------- #
# Regime (§20)
# --------------------------------------------------------------------------- #
def regime_analysis(trades: list[Any], btc_bars: list[Any]) -> dict[str, Any]:
    regimes = A.regime_by_day(
        [
            OHLCV(
                symbol=b.symbol,
                timestamp=b.timestamp,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
            )
            for b in btc_bars
        ]
    )
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"trades": 0, "net_usd": 0.0, "gross_usd": 0.0, "pos_usd": 0.0, "neg_usd": 0.0}
    )
    for t in trades:
        reg = regimes.get((t.entry_ts // DAY) * DAY, "UNKNOWN")
        b = buckets[reg]
        b["trades"] += 1
        b["net_usd"] += t.net
        b["gross_usd"] += t.gross
        if t.net > 0:
            b["pos_usd"] += t.net
        elif t.net < 0:
            b["neg_usd"] += t.net
    total_net = sum(v["net_usd"] for v in buckets.values())
    total_pos = sum(v["pos_usd"] for v in buckets.values())
    out: dict[str, Any] = {}
    for k in sorted(buckets):
        v = buckets[k]
        out[k] = {
            "trades": v["trades"],
            "net_usd": round(v["net_usd"], 2),
            "net_pct_of_total": round(v["net_usd"] / total_net * 100.0, 3) if total_net else None,
            "positive_net_usd": round(v["pos_usd"], 2),
            "share_of_all_positive_net": round(v["pos_usd"] / total_pos, 4) if total_pos else None,
        }
    return {
        "total_net_usd": round(total_net, 2),
        "total_positive_net_usd": round(total_pos, 2),
        "by_regime": out,
    }


# --------------------------------------------------------------------------- #
# Breadth predictive value (§23)
# --------------------------------------------------------------------------- #
def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def breadth_predictive(full_corpus: dict[str, Any]) -> dict[str, Any]:
    index_by_sym = {s: {b.timestamp: b for b in bars} for s, bars in full_corpus.items()}
    uverse = DynamicAssetUniverse(
        full_corpus, D.listing_times(), D.corpus_digest(), UniverseConfig()
    )
    calendar = sorted({ts for d in index_by_sym.values() for ts in d})
    xs: list[float] = []
    fwd: dict[int, list[float]] = {h: [] for h in HORIZONS}
    for day in calendar[: -max(HORIZONS)]:
        snap = uverse.snapshot(day + DAY)
        eligible = [s for s in snap.eligible_assets if s in index_by_sym]
        if len(eligible) < 5:
            continue
        pos, ev = B.breadth_of_day(index_by_sym, day, eligible, 50)
        if ev < 5:
            continue
        vals: dict[int, list[float]] = {h: [] for h in HORIZONS}
        for s in eligible:
            idx = index_by_sym[s]
            base = idx.get(day)
            if base is None or base.close <= 0:
                continue
            for h in HORIZONS:
                bar = idx.get(day + h * DAY)
                if bar is not None:
                    vals[h].append(bar.close / base.close - 1.0)
        if all(vals[h] for h in HORIZONS):
            xs.append(pos / ev)
            for h in HORIZONS:
                fwd[h].append(sum(vals[h]) / len(vals[h]))
    out: dict[str, Any] = {"observations": len(xs), "horizons": list(HORIZONS)}
    for h in HORIZONS:
        ys = fwd[h]
        r = _pearson(xs, ys)
        # block-bootstrap SE of the correlation (blocks of 20 days)
        se = _block_bootstrap_se(xs, ys, block=20, iters=300)
        out[f"h{h}"] = {
            "corr": round(r, 4) if r is not None else None,
            "corr_se_block20": round(se, 4) if se is not None else None,
            "mean_fwd": round(sum(ys) / len(ys), 6) if ys else None,
            "n": len(ys),
        }
    return out


def _block_bootstrap_se(
    xs: list[float], ys: list[float], *, block: int, iters: int
) -> float | None:
    n = len(xs)
    if n < block * 3:
        return None
    rng = random.Random(20261003)
    nb = n // block
    stats: list[float] = []
    for _ in range(iters):
        samp_x: list[float] = []
        samp_y: list[float] = []
        for _ in range(nb):
            start = rng.randrange(0, n - block + 1)
            samp_x.extend(xs[start : start + block])
            samp_y.extend(ys[start : start + block])
        r = _pearson(samp_x, samp_y)
        if r is not None:
            stats.append(r)
    if len(stats) < 3:
        return None
    return statistics.pstdev(stats)


# --------------------------------------------------------------------------- #
# Statistical uncertainty on VALIDATION (§24)
# --------------------------------------------------------------------------- #
def block_bootstrap_episodes(groups: list[dict[str, Any]], *, iters: int = 2000) -> dict[str, Any]:
    vals = [g["portfolio_bps"] for g in groups]
    n = len(vals)
    if n < 4:
        return {"episodes": n}
    mean = statistics.fmean(vals)
    total = sum(vals)
    rng = random.Random(20261003)
    means: list[float] = []
    totals: list[float] = []
    for _ in range(iters):
        # circular block bootstrap, block = ceil(sqrt(n)) episodes
        b = max(2, math.ceil(math.sqrt(n)))
        picks: list[float] = []
        while len(picks) < n:
            start = rng.randrange(0, n)
            for k in range(b):
                picks.append(vals[(start + k) % n])
        picks = picks[:n]
        means.append(statistics.fmean(picks))
        totals.append(sum(picks) * (n / len(picks)))
    means.sort()
    totals.sort()

    def pct(a: list[float], q: float) -> float:
        return a[min(len(a) - 1, max(0, int(q * (len(a) - 1))))]

    return {
        "episodes": n,
        "mean_portfolio_bps": round(mean, 3),
        "total_portfolio_bps": round(total, 3),
        "mean_ci95": [round(pct(means, 0.025), 3), round(pct(means, 0.975), 3)],
        "mean_bootstrap_se": round(statistics.pstdev(means), 3),
        "mean_p_leq_zero": round(sum(1 for m in means if m <= 0) / len(means), 4),
    }


# --------------------------------------------------------------------------- #
# Random-exposure control (§22)
# --------------------------------------------------------------------------- #
def market_daily_returns(full_corpus: dict[str, Any], calendar: list[int]) -> dict[int, float]:
    index_by_sym = {s: {b.timestamp: b for b in bars} for s, bars in full_corpus.items()}
    uverse = DynamicAssetUniverse(
        full_corpus, D.listing_times(), D.corpus_digest(), UniverseConfig()
    )
    out: dict[int, float] = {}
    for i, day in enumerate(calendar[:-1]):
        nxt = calendar[i + 1]
        snap = uverse.snapshot(day + DAY)
        eligible = [s for s in snap.eligible_assets if s in index_by_sym]
        rets: list[float] = []
        for s in eligible:
            b0 = index_by_sym[s].get(day)
            b1 = index_by_sym[s].get(nxt)
            if b0 is not None and b1 is not None and b0.close > 0:
                rets.append(b1.close / b0.close - 1.0)
        if rets:
            out[day] = sum(rets) / len(rets)
    return out


def random_timing_control(
    records: list[Any], mkt: dict[int, float], *, seeds: tuple[int, ...]
) -> dict[str, Any]:
    days = sorted(mkt)
    long_days = [r.decision_ts - DAY for r in records if r.state == "LONG"]
    long_days = [d for d in long_days if d in mkt]
    k = len(long_days)
    real = sum(mkt[d] for d in long_days)
    dist: list[float] = []
    nice = list(mkt.values())
    for seed in seeds:
        rng = random.Random(seed)
        sample = rng.sample(days, k) if k <= len(days) else list(days)
        dist.append(sum(mkt[d] for d in sample))
    dist.sort()
    worse = sum(1 for x in dist if x < real)
    return {
        "long_days": k,
        "real_exposure_sum_return": round(real, 6),
        "real_portfolio_bps": round(real * BPS, 3),
        "random_mean_portfolio_bps": round(statistics.fmean([x * BPS for x in dist]), 3),
        "random_p05": round(dist[min(len(dist) - 1, int(0.05 * len(dist)))] * BPS, 3),
        "random_p95": round(dist[min(len(dist) - 1, int(0.95 * len(dist)))] * BPS, 3),
        "real_percentile": round(worse / len(dist), 4),
        "seeds": list(seeds),
        "note": "diagnostic only; same exposure-days count, randomized timing, fixed seeds",
        "_unused": len(nice),
    }


# --------------------------------------------------------------------------- #
# Episode-ordered equity drawdown using true exit ordering
# --------------------------------------------------------------------------- #
def exit_ordered_drawdown(trades: list[Any]) -> dict[str, Any]:
    groups = sorted(episode_groups(trades), key=lambda g: g["exit_ts"])
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for g in groups:
        equity += g["net_usd"]
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return {
        "episode_ordered_drawdown_usd": round(worst, 4),
        "episode_ordered_drawdown_bps_of_500": round(worst / NOTIONAL * BPS, 3),
    }


# --------------------------------------------------------------------------- #
# Turnover & exposure (§10, §12)
# --------------------------------------------------------------------------- #
def turnover_exposure(groups: list[dict[str, Any]], audit: dict[str, Any]) -> dict[str, Any]:
    entry_notional = sum(g["alloc_sum"] for g in groups)
    exit_notional = sum(g["alloc_sum"] + g["gross_usd"] for g in groups)
    decisions = audit.get("decisions", 0)
    long_days = audit.get("long_days", 0)
    return {
        "episodes": len(groups),
        "entry_notional_usd": round(entry_notional, 2),
        "exit_notional_usd": round(exit_notional, 2),
        "gross_turnover_usd": round(entry_notional + exit_notional, 2),
        "net_turnover_usd": round(abs(exit_notional - entry_notional), 2),
        "avg_episode_size_names": round(statistics.fmean([g["n"] for g in groups]), 2)
        if groups
        else 0,
        "avg_deployed_capital_usd": round(statistics.fmean([g["alloc_sum"] for g in groups]), 2)
        if groups
        else 0,
        "time_in_market_fraction": round(long_days / decisions, 4) if decisions else None,
        "avg_gross_exposure_usd_when_long": round(
            statistics.fmean([g["alloc_sum"] for g in groups]), 2
        )
        if groups
        else 0,
        "one_round_trip_per_episode": True,
        "cost_charged_per_episode_usd": round(statistics.fmean([g["fees_usd"] for g in groups]), 4)
        if groups
        else 0,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cost = cost_model_v3_rt_bps()
    start_sha = git("rev-parse", "HEAD")
    spec_hash = sha256_file(EXP_DIR / "SPEC.md")
    manifest_hash = sha256_file(EXP_DIR / "MANIFEST.json")
    breadth_hash = sha256_file(REPO / "src/trading_bot/research/diversified/breadth.py")

    # holdout firewall
    reg = HoldoutRegistry.load(POST_OOS / "HOLDOUT_REGISTRY.json")
    fwd = reg.get(HOLDOUT_ID)
    holdout_status = fwd.status.value
    assert reg.status(HOLDOUT_ID) is HoldoutStatus.UNTOUCHED

    baseline = {
        "branch": git("branch", "--show-current"),
        "start_sha": start_sha,
        "code_hash": code_hash(),
        "spec_sha256": spec_hash,
        "manifest_sha256": manifest_hash,
        "breadth_sha256": breadth_hash,
        "dataset_fingerprint": D.corpus_digest(),
        "cost_model_v3_rt_bps": cost,
        "config_hash": sha256_file(REPO / "config/strategy_admission.json"),
        "split_hash": FROZEN_SPLIT.split_hash(),
        "split_definition": FROZEN_SPLIT.to_dict(),
        "holdout_id": HOLDOUT_ID,
        "holdout_status_before": holdout_status,
        "oos_opened": False,
        "dirty_worktree": git("status", "--short").splitlines(),
    }

    config = B.breadth_config()
    dev_corpus = D.load_corpus(split="DEV")
    val_corpus = D.load_corpus(split="VALIDATION")
    full_corpus = D.load_corpus_range(start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1])

    dev_tr, _dev_rec, dev_audit = B.simulate_breadth_regime(
        dev_corpus, D.listing_times(), D.corpus_digest(), config=config, cost_bps_rt=cost
    )
    val_tr, _val_rec, val_audit = B.simulate_breadth_regime(
        val_corpus, D.listing_times(), D.corpus_digest(), config=config, cost_bps_rt=cost
    )
    full_tr, full_rec, full_audit = B.simulate_breadth_regime(
        full_corpus, D.listing_times(), D.corpus_digest(), config=config, cost_bps_rt=cost
    )

    dev = v_metrics(dev_tr)
    val = v_metrics(val_tr)
    full = v_metrics(full_tr)

    # independent entry/exit price validation against raw bars (spot-check all)
    def validate_prices(trades: list[Any], corpus: dict[str, Any]) -> dict[str, Any]:
        idx = {s: {b.timestamp: b for b in bars} for s, bars in corpus.items()}
        ok = 0
        bad = 0
        for t in trades:
            b = idx.get(t.symbol, {}).get(t.entry_ts)
            if b is not None and abs(b.open - t.entry) < 1e-6:
                ok += 1
            else:
                bad += 1
        return {"entry_prices_verified": ok, "entry_prices_mismatch": bad, "total": len(trades)}

    price_check = {
        "DEV": validate_prices(dev_tr, dev_corpus),
        "VALIDATION": validate_prices(val_tr, val_corpus),
        "FULL": validate_prices(full_tr, full_corpus),
    }

    # calendar for equity curves
    def calendar_of(corpus: dict[str, Any]) -> list[int]:
        return sorted({b.timestamp for bars in corpus.values() for b in bars})

    dev_eq = equity_curve(dev_tr, calendar_of(dev_corpus), dev_corpus)
    val_eq = equity_curve(val_tr, calendar_of(val_corpus), val_corpus)
    full_eq = equity_curve(full_tr, calendar_of(full_corpus), full_corpus)

    dev_ord = exit_ordered_drawdown(dev_tr)
    val_ord = exit_ordered_drawdown(val_tr)
    full_ord = exit_ordered_drawdown(full_tr)

    dev_turn = turnover_exposure(episode_groups(dev_tr), dev_audit)
    val_turn = turnover_exposure(episode_groups(val_tr), val_audit)
    full_turn = turnover_exposure(episode_groups(full_tr), full_audit)

    # beta / timing alpha on the FULL window (builder's choice) and per split
    btc_full = D.load_corpus_range(
        ["BTCUSDT"], start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1]
    )["BTCUSDT"]
    btc_dev = D.load_corpus(["BTCUSDT"], split="DEV")["BTCUSDT"]
    btc_val = D.load_corpus(["BTCUSDT"], split="VALIDATION")["BTCUSDT"]
    beta_full = beta_regression(full_tr, btc_full)
    beta_dev = beta_regression(dev_tr, btc_dev)
    beta_val = beta_regression(val_tr, btc_val)

    regime = regime_analysis(full_tr, btc_full)

    # ALWAYS_LONG_SAME_BASKET control (§21)
    always_tr, _ar, _aa = B.simulate_breadth_regime(
        full_corpus,
        D.listing_times(),
        D.corpus_digest(),
        config=B.breadth_config(entry_breadth=0.0, exit_breadth=-1.0),
        cost_bps_rt=cost,
    )
    always = v_metrics(always_tr)
    always_group = episode_groups(always_tr)
    gate_value_add = {
        "window": "DEV+VALIDATION (2019-01-01..2025-07-01)",
        "always_long_same_basket": {
            "portfolio_return_bps": always.get("portfolio_return_bps"),
            "total_net_pnl_usd": always.get("total_net_pnl_usd"),
            "trades": always.get("trades"),
            "episodes": always.get("episodes"),
        },
        "breadth_gate": {
            "portfolio_return_bps": full.get("portfolio_return_bps"),
            "total_net_pnl_usd": full.get("total_net_pnl_usd"),
            "trades": full.get("trades"),
            "episodes": full.get("episodes"),
        },
        "breadth_value_add_bps": round(
            (full.get("portfolio_return_bps", 0) - always.get("portfolio_return_bps", 0)), 3
        ),
        "breadth_value_add_usd": round(
            (full.get("total_net_pnl_usd", 0) - always.get("total_net_pnl_usd", 0)), 2
        ),
        "note": "always-long uses the SAME universe/weighting/window/costs; only the gate differs",
        "_always_episodes": len(always_group),
    }

    # predictive value (§23)
    bpred = breadth_predictive(full_corpus)

    # random-exposure control (§22)
    mkt = market_daily_returns(full_corpus, calendar_of(full_corpus))
    rnd = random_timing_control(full_rec, mkt, seeds=SEEDS)

    # statistical uncertainty on the headline economics
    unc = {
        "DEV": block_bootstrap_episodes(episode_groups(dev_tr)),
        "VALIDATION": block_bootstrap_episodes(episode_groups(val_tr)),
        "FULL": block_bootstrap_episodes(episode_groups(full_tr)),
    }

    # effective sample size (§25)
    ess = {
        "asset_positions_DEV": dev.get("trades"),
        "asset_positions_VALIDATION": val.get("trades"),
        "asset_positions_FULL": full.get("trades"),
        "basket_episodes_DEV": dev.get("episodes"),
        "basket_episodes_VALIDATION": val.get("episodes"),
        "basket_episodes_FULL": full.get("episodes"),
        "daily_decisions_DEV": dev_audit.get("decisions"),
        "daily_decisions_FULL": full_audit.get("decisions"),
        "avg_constituents_per_episode": full_turn.get("avg_episode_size_names"),
        "effective_independent_evidence": "basket episodes (≈ the number of timer decisions)",
    }

    # robustness reproduction (§26) — the 8 pre-declared perturbations on VALIDATION
    specs: dict[str, dict[str, Any]] = {
        "entry_050_exit_040": {"entry_breadth": 0.50, "exit_breadth": 0.40},
        "entry_060_exit_050": {"entry_breadth": 0.60, "exit_breadth": 0.50},
        "lookback_40": {"lookback_days": 40},
        "lookback_60": {"lookback_days": 60},
        "entry_delay_1d": {"entry_delay_days": 1},
    }
    perturbations: dict[str, Any] = {}
    for name, ov in specs.items():
        tr, _r, _a = B.simulate_breadth_regime(
            val_corpus,
            D.listing_times(),
            D.corpus_digest(),
            config=B.breadth_config(**ov),
            cost_bps_rt=cost,
        )
        m = v_metrics(tr)
        perturbations[name] = {
            "expectancy_net_bps": m.get("avg_net_return_bps_per_trade"),
            "portfolio_return_bps": m.get("portfolio_return_bps"),
            "total_net_pnl_usd": m.get("total_net_pnl_usd"),
            "trades": m.get("trades"),
            "positive": (m.get("total_net_pnl_usd") or 0) > 0,
        }
    for mult in (1.25, 1.5, 2.0):
        tr, _r, _a = B.simulate_breadth_regime(
            val_corpus, D.listing_times(), D.corpus_digest(), config=config, cost_bps_rt=cost * mult
        )
        m = v_metrics(tr)
        perturbations[f"cost_{mult}x"] = {
            "expectancy_net_bps": m.get("avg_net_return_bps_per_trade"),
            "portfolio_return_bps": m.get("portfolio_return_bps"),
            "total_net_pnl_usd": m.get("total_net_pnl_usd"),
            "trades": m.get("trades"),
            "positive": (m.get("total_net_pnl_usd") or 0) > 0,
        }
    positive_count = sum(1 for v in perturbations.values() if v["positive"])
    robustness = {
        "reference_split": "VALIDATION",
        "perturbations": perturbations,
        "positive_count": positive_count,
        "total": len(perturbations),
        "positive_fraction": round(positive_count / len(perturbations), 4),
        "reproduced": positive_count == len(perturbations),
    }

    # concentration (§27) — TradeLike is an invariant protocol; the actual objects satisfy it
    concentration = A.concentration_by_asset_and_period(cast(Any, full_tr))
    conc = dict(concentration)

    # reconciliation (§5, §8)
    reconciliation = {
        "DEV_trades": dev.get("trades"),
        "VALIDATION_trades": val.get("trades"),
        "FULL_trades": full.get("trades"),
        "DEV_plus_VALIDATION": (dev.get("trades") or 0) + (val.get("trades") or 0),
        "FULL_minus_sum_delta": (full.get("trades") or 0)
        - ((dev.get("trades") or 0) + (val.get("trades") or 0)),
        "DEV_episodes": dev.get("episodes"),
        "VALIDATION_episodes": val.get("episodes"),
        "FULL_episodes": full.get("episodes"),
        "DEV_net_usd": dev.get("total_net_pnl_usd"),
        "VALIDATION_net_usd": val.get("total_net_pnl_usd"),
        "FULL_net_usd": full.get("total_net_pnl_usd"),
        "DEV_plus_VALIDATION_net_usd": round(
            (dev.get("total_net_pnl_usd") or 0) + (val.get("total_net_pnl_usd") or 0), 2
        ),
        "FULL_minus_sum_net_usd": round(
            (full.get("total_net_pnl_usd") or 0)
            - ((dev.get("total_net_pnl_usd") or 0) + (val.get("total_net_pnl_usd") or 0)),
            2,
        ),
        "builder_state_LONG_net_usd": 3018.29,
        "builder_state_LONG_trades": 4617,
        "explanation": (
            "DEV/VALIDATION/FULL are three INDEPENDENT simulations: DEV and VALIDATION "
            "are separate truncated corpora (each with its own end_of_sample exit and its "
            "own universe warm-up), while FULL is one continuous 2019-01..2025-07 run. "
            "The counts and USD totals therefore differ only by boundary effects; each "
            "number is internally consistent within its own run."
        ),
    }

    report = {
        "experiment_id": EXPERIMENT_ID,
        "strategy_id": STRATEGY_ID,
        "role": "INDEPENDENT_VERIFIER",
        "baseline": baseline,
        "cost_model_v3_rt_bps": cost,
        "price_check": price_check,
        "dev": dev,
        "validation": val,
        "full": full,
        "equity": {"DEV": dev_eq, "VALIDATION": val_eq, "FULL": full_eq},
        "exit_ordered_drawdown": {"DEV": dev_ord, "VALIDATION": val_ord, "FULL": full_ord},
        "turnover": {"DEV": dev_turn, "VALIDATION": val_turn, "FULL": full_turn},
        "beta": {"FULL": beta_full, "DEV": beta_dev, "VALIDATION": beta_val},
        "regime": regime,
        "gate_value_add": gate_value_add,
        "breadth_predictive": bpred,
        "random_timing": rnd,
        "uncertainty": unc,
        "effective_sample_size": ess,
        "robustness": robustness,
        "concentration": conc,
        "reconciliation": reconciliation,
        "oos_opened": False,
        "holdout_status_after": reg.status(HOLDOUT_ID).value,
    }

    (OUT / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    print(
        "DEV trades",
        dev.get("trades"),
        "net_usd",
        dev.get("total_net_pnl_usd"),
        "port_bps",
        dev.get("portfolio_return_bps"),
    )
    print(
        "VAL trades",
        val.get("trades"),
        "net_usd",
        val.get("total_net_pnl_usd"),
        "port_bps",
        val.get("portfolio_return_bps"),
    )
    print("FULL trades", full.get("trades"), "net_usd", full.get("total_net_pnl_usd"))
    print(
        "beta", beta_full.get("market_beta"), "alpha", beta_full.get("timing_alpha_residual_mean")
    )
    print("robust", robustness["positive_count"], "/", robustness["total"])
    print("value add bps", gate_value_add["breadth_value_add_bps"])
    print("wrote", OUT / "verification.json")


if __name__ == "__main__":
    main()
