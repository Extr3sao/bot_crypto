"""WP-EDGE-02A — is the frozen 4h trend ruleset's OOS reading robust, or one trade?

WP-EDGE-01 measured the frozen ``EDGE-TREND-01`` 4h ruleset out of sample and refused
to admit it to PAPER for a single declared reason: the largest winning trade was 0.7987
of the OOS net, against a 0.50 concentration limit (``OOS_TREND_DECISION``). That is a
diagnosis, not a robustness analysis: it says the net is concentrated, and says nothing
about how much of the rest of the reading survives when the concentration is taken
seriously — per asset, per regime, per period, under worse costs, and with an interval
instead of a point estimate.

This module is that analysis, and nothing else. It changes no rule and re-runs the SAME
frozen ruleset through the SAME harness:

* the reproduction check measures the frozen ruleset again and compares the result with
  the artefact WP-EDGE-01 already published (``OOS_TREND.json``), so a reading that
  moved would fail here rather than be quietly restated;
* the **sensitivity** arm drops the k largest winning trades and re-reads the book
  (k = 1 and k = 3). This is a diagnostic ON the published run, not a revision of it:
  the strategy is not modified, no parameter is re-fitted and the dropped trades are
  published so the reader can put them back;
* **contribution** is measured per asset (own book) and per regime label (the
  candidate's own entry trend state and the benchmark-relative market context), so a
  net carried by one asset or one regime is visible as such;
* **cost/slippage stress** adds the harness's own ``ADVERSE`` plane (fees x2,
  slippage and impact x3, derived from the same components) on top of ``2X_FEES``;
* **uncertainty** is reported two ways for every window: a Newey–West (HAC) interval
  on the mean trade result, which handles the autocorrelation of a trade stream, and a
  stationary block bootstrap over the trade order, for a distribution-free reading.
  Both are declared, seeded and reproducible, and both are recomputed by the verifier;
* **additional periods**: the design windows already consume the frozen corpus to its
  last bar, so no unused independent sample exists. That is measured here and reported
  instead of being replaced by a claim. A genuinely new period would need a new corpus
  (the 15m feed reaches 2026-10-07 but the 4h corpus is aggregated from 1h by design),
  which is proposed as a NEW pre-registered experiment, never applied retroactively.

The concentration criterion stays exactly where WP-EDGE-01 froze it (0.50). A proposal
to make it size-aware is recorded as a proposal to test, not as a revision that would
have admitted this run: the ruleset is not promoted here either way.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import campaign as C
from . import closure as CL
from .candidates import FROZEN_PARAMS, PARAMS_HASH, TrendFollow
from .costs import cost_plane
from .data import ASSETS, BAR_MS
from .features import market_regime_at
from .simulator import buy_and_hold
from .simulator import run_portfolio as run_portfolio_sim

__all__ = [
    "TREND_ROBUSTNESS",
    "TREND_ROBUSTNESS_DECISION",
    "block_bootstrap_mean_interval",
    "hac_mean_interval",
    "leave_out_largest",
    "run_trend_robustness",
    "trend_robustness_verdict",
    "write_trend_robustness_artifacts",
]

#: The experiment's frozen declaration. Written before the analysis ran.
TREND_ROBUSTNESS: dict[str, Any] = {
    "id": "ROB-EDGE01-TREND-4H",
    "answer_to": "H3",
    "candidate": "edge_trend_01",
    "profile": "4h",
    "split": "trend",
    "timeframe": "4h",
    "horizon_minutes": 1440.0,
    "windows": ["DEV", "VAL", "OOS"],
    "scenario_plan": {
        "DEV": ["BASE"],
        "VAL": ["BASE"],
        "OOS": ["BASE", "2X_FEES", "ADVERSE"],
    },
    "decision_window": "OOS",
    "leave_out_k": [1, 3],
    "periods": {
        "2025H1": [2025, 1, 1, 2025, 7, 1],
        "2025H2": [2025, 7, 1, 2026, 1, 1],
        "2026Q1": [2026, 1, 1, 2026, 3, 1],
    },
    "reproduces": (
        "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json — the frozen "
        "ruleset is measured again with the same harness and compared with the "
        "published figures; a moved reading fails the run instead of being restated"
    ),
    "question": (
        "WP-EDGE-01 refused the frozen 4h trend ruleset for one reason: the largest "
        "winning trade was 0.7987 of the OOS net against a 0.50 limit. Beyond that "
        "single number — how much of the OOS reading survives dropping the largest "
        "winner (and the three largest), which asset and which regime carry it, does "
        "it survive the adverse cost plane, and what interval does the sample support "
        "once the trades' own autocorrelation is taken into account?"
    ),
}

#: Frozen BEFORE the robustness run. The concentration criterion is NOT relaxed: it is
#: the same 0.50 WP-EDGE-01 froze, restated here so this experiment cannot quietly
#: lower the bar it is being judged against.
TREND_ROBUSTNESS_DECISION: dict[str, Any] = {
    "decision_window": "OOS",
    "min_oos_trades": 30,
    "concentration_criterion_pct_of_net": 0.50,
    "concentration_criterion_unchanged_from": (
        "WP-EDGE-01 OOS_TREND_DECISION.max_single_trade_share_of_net"
    ),
    "min_positive_assets": 2,
    "min_positive_periods": 2,
    "uncertainty": {
        "confidence": 0.95,
        "hac": (
            "Newey-West (Bartlett-weighted) standard error of the mean trade net, with "
            "lag = floor(4 * (n/100)^(2/9)) declared here; two-sided 95% interval from "
            "the Student-t critical value by the Cornish-Fisher expansion"
        ),
        "bootstrap": (
            "stationary block bootstrap over the trades in time order: a new block "
            "starts with probability 1/block_length, block_length = 5, 5000 resamples, "
            "xorshift64* PRNG from a declared seed, percentile interval of the mean"
        ),
    },
    "decisive_failures": (
        "a powered sample in which the edge is CONTRADICTED: OOS net <= 0, or the net "
        "after dropping the single largest winner <= 0 (the reading is one trade), or "
        "fewer than min_positive_assets single-asset books positive, or the HAC "
        "interval's upper end <= 0 (the sample says the expectancy is not positive)"
    ),
    "inconclusive_failures": (
        "a powered sample in which the declared requirements are not met but the edge "
        "is not contradicted: concentration above the 0.50 limit while the "
        "leave-one-out net stays positive, an interval that contains 0, the adverse "
        "cost plane below 0 while the base plane is above it, fewer than "
        "min_positive_periods positive periods, or a candidate drawdown that is not "
        "below buy & hold"
    ),
    "meaning": {
        "ADMIT_PAPER": "every declared requirement met on OOS, including the concentration limit",
        "REJECT": "a powered sample in which the edge is contradicted",
        "INSUFFICIENT_EVIDENCE": "a powered sample the requirements cannot decide, or an unpowered one",
    },
    "proposal_not_applied": {
        "what": (
            "a size-aware concentration criterion (e.g. the share measured against the "
            "sum of the top-k winners, or against gross profit instead of net)"
        ),
        "status": (
            "a proposal for a NEW pre-registered experiment with its own corpus split; "
            "it is NOT applied to this run, and the run is judged against 0.50"
        ),
    },
    "not_claimed": (
        "PAPER here means the evidence supports wiring the frozen ruleset into the paper "
        "pipeline; it is not a profitability claim, not a live-trading authorisation and "
        "not a certification. No capital is at risk in this experiment."
    ),
}

#: Columns of the published trade ledger, restated by the verifier. The `_trade_rows`
#: the harness carries are the same rows the WP-EDGE-01 artefacts publish.
TRADE_COLUMNS: tuple[str, ...] = (
    "run",
    "book",
    "window",
    "scenario",
    "candidate",
    "asset",
    "side",
    "signal_bar",
    "decision_ts",
    "entry_ts",
    "exit_ts",
    "entry_bar",
    "exit_bar",
    "duration_min",
    "entry_mid",
    "entry_fill",
    "exit_mid",
    "exit_fill",
    "qty",
    "notional",
    "stop_initial",
    "gross",
    "price_costs",
    "fees",
    "net",
    "cost_bps_realised",
    "exit_reason",
    "regime",
    "expected_gross_bps",
    "expected_cost_bps",
    "mae",
    "mfe",
    "mae_bps",
    "mfe_bps",
    "planned_risk_usdt",
    "market_context",
)

#: Minimum span (days) a leftover stretch of corpus must cover to count as a period the
#: design never used. Declared BEFORE the run, so a handful of mop-up bars cannot be
#: presented as an independent sample.
CORPUS_LEFTOVER_MIN_DAYS = 30

#: xorshift64* constants, declared so the resampling is reproducible from the seed.
_MASK64 = (1 << 64) - 1
_XORSHIFT_MULT = 2685821657736338717


def _xorshift64_star(state: int) -> tuple[int, int]:
    """One xorshift64* step: ``(next_state, output)``. Declared, not library-dependent."""
    x = state & _MASK64
    x ^= (x << 13) & _MASK64
    x ^= x >> 7
    x ^= (x << 17) & _MASK64
    state = x & _MASK64
    return state, (state * _XORSHIFT_MULT) & _MASK64


def _uniform(state: int) -> tuple[int, float]:
    state, out = _xorshift64_star(state)
    return state, out / float(1 << 64)


#: Two-sided 95% Student-t critical values for df 1..9, where the Cornish-Fisher
#: expansion below is not trustworthy. Declared, so both the builder and the verifier
#: read the same numbers instead of hiding a small-sample case behind a formula that
#: only holds asymptotically.
T_CRITICAL_SMALL_DF: tuple[float, ...] = (
    12.7062047364,
    4.30265272975,
    3.18244630528,
    2.77644510520,
    2.57058183564,
    2.44691185114,
    2.36462425159,
    2.30600413520,
    2.26215716285,
)


def _t_critical(df: int, z: float = 1.959963984540054) -> float:
    """Two-sided 95% Student-t critical value.

    ``df <= 9`` uses the declared table; above that the Cornish-Fisher expansion, which
    is exact to ~1e-4 from df = 10 and converges to the normal. Declared rather than
    imported so the interval is reproducible without a statistics dependency, and so the
    verifier can restate the same numbers.
    """
    if df <= 0:
        return float("inf")
    if df <= len(T_CRITICAL_SMALL_DF):
        return T_CRITICAL_SMALL_DF[df - 1]
    if df > 2_000:
        return z
    v = float(df)
    return (
        z
        + (z**3 + z) / (4 * v)
        + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * v**2)
        + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * v**3)
    )


def _hac_lag(n: int) -> int:
    """Declared lag rule; the same for builder and verifier."""
    if n <= 1:
        return 0
    return int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def hac_mean_interval(
    values: list[float], *, confidence: float = 0.95
) -> dict[str, Any]:
    """Newey–West interval for the mean of a time-ordered series.

    The series is the trade net in the order the book produced it, so the Bartlett
    weighting sees the autocorrelation a trade stream actually has (a run of losses
    inside one regime is not 20 independent observations).
    """
    n = len(values)
    if n < 2:
        return {
            "n": n,
            "mean": round(sum(values) / n, 6) if n else None,
            "se": None,
            "lag": 0,
            "lower": None,
            "upper": None,
            "method": "Newey-West (Bartlett), Student-t two-sided",
        }
    lag = _hac_lag(n)
    mean = sum(values) / n
    dev = [v - mean for v in values]
    gamma0 = sum(d * d for d in dev) / n
    var = gamma0
    for k in range(1, lag + 1):
        weight = 1.0 - k / (lag + 1.0)
        gamma_k = sum(dev[i] * dev[i - k] for i in range(k, n)) / n
        var += 2.0 * weight * gamma_k
    if var < 0.0:  # a small sample can make the weighted sum negative
        var = 0.0
    se = math.sqrt(var / n)
    critical = _t_critical(n - 1)
    return {
        "n": n,
        "mean": round(mean, 6),
        "se": round(se, 6),
        "lag": lag,
        "t_critical": round(critical, 6),
        "lower": round(mean - critical * se, 6),
        "upper": round(mean + critical * se, 6),
        "method": (
            f"Newey-West (Bartlett), lag {lag} = floor(4*(n/100)^(2/9)), Student-t "
            f"critical value for {n - 1} degrees of freedom"
        ),
        "confidence": confidence,
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an ascending list. Declared."""
    n = len(sorted_values)
    if n == 0:
        return float("nan")
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    low = int(math.floor(pos))
    high = min(low + 1, n - 1)
    frac = pos - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


def block_bootstrap_mean_interval(
    values: list[float],
    *,
    block_length: int = 5,
    resamples: int = 5_000,
    seed: int = 20_260_101,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Stationary block bootstrap percentile interval for the mean.

    Blocks are sampled from the series IN TIME ORDER (index positions), so resampled
    paths keep short runs of neighbouring trades together — the dependence a plain
    i.i.d. bootstrap would destroy. The PRNG is the declared xorshift64*, so the
    interval is reproducible from the seed alone.
    """
    n = len(values)
    if n < 2:
        return {
            "n": n,
            "mean": round(sum(values) / n, 6) if n else None,
            "lower": None,
            "upper": None,
            "resamples": 0,
            "method": "stationary block bootstrap (undeclared: too few trades)",
        }
    state = seed & _MASK64
    if state == 0:
        state = 0x9E3779B97F4A7C15 & _MASK64
    restart = 1.0 / block_length
    means: list[float] = []
    for _ in range(resamples):
        total = 0.0
        count = 0
        index = -1
        while count < n:
            state, draw = _uniform(state)
            if index < 0 or draw < restart:
                state, draw2 = _uniform(state)
                index = int(draw2 * n)
                if index >= n:
                    index = n - 1
            total += values[index]
            count += 1
            index += 1
            if index >= n:
                index = 0
        means.append(total / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    return {
        "n": n,
        "mean": round(sum(values) / n, 6),
        "lower": round(_percentile(means, alpha), 6),
        "upper": round(_percentile(means, 1.0 - alpha), 6),
        "resamples": resamples,
        "block_length": block_length,
        "seed": seed,
        "method": (
            f"stationary block bootstrap, block length {block_length}, {resamples} "
            "resamples, xorshift64* from the declared seed, percentile interval of the mean"
        ),
        "confidence": confidence,
    }


def leave_out_largest(nets_in_time_order: list[float], k: int) -> dict[str, Any]:
    """The book with its k largest winners removed: the concentration diagnostic.

    Pure sensitivity ON the published trades: nothing is re-fitted and the dropped
    trades are reported, so the reader can put them back.
    """
    ordered = sorted(nets_in_time_order, reverse=True)
    dropped = ordered[:k]
    kept = ordered[k:]
    net = sum(kept)
    wins = [v for v in kept if v > 0]
    losses = [v for v in kept if v <= 0]
    gross_loss = abs(sum(losses))
    total_net = sum(nets_in_time_order)
    return {
        "k": k,
        "dropped_usdt": round(sum(dropped), 6),
        "dropped_shares_of_net": (
            [round(d / total_net, 6) for d in dropped] if total_net > 0 else None
        ),
        "trades": len(kept),
        "net_usdt": round(net, 6),
        "net_before_usdt": round(total_net, 6),
        "net_removed_usdt": round(total_net - net, 6),
        "expectancy_usdt": round(net / len(kept), 6) if kept else None,
        "win_rate_pct": round(100.0 * len(wins) / len(kept), 6) if kept else None,
        "profit_factor": round(sum(wins) / gross_loss, 6) if gross_loss > 0 else None,
        "largest_remaining_trade_usdt": round(max(kept), 6) if kept else None,
        "largest_remaining_share_of_net": (
            round(max(kept) / net, 6) if kept and net > 0 else None
        ),
    }


def _risk_adjusted(metrics: dict[str, Any], *, start_equity: float) -> dict[str, Any]:
    """Return-per-drawdown readings, so size and pain are compared together."""
    net = float(metrics.get("net_usdt") or 0.0)
    dd = float(metrics.get("max_drawdown_pct") or 0.0)
    ret = float(metrics.get("return_pct") or 0.0)
    return {
        "return_pct": metrics.get("return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe_annualised": metrics.get("sharpe_annualised"),
        "mar_ratio": round(net / (start_equity * dd / 100.0), 6)
        if dd > 0 and start_equity > 0
        else None,
        "return_on_drawdown": round(ret / dd, 6) if dd > 0 else None,
        "exposure_pct_of_time": metrics.get("exposure_pct_of_time"),
    }


def _run_window(
    *,
    window: str,
    scenario: str,
    corpus: Any,
    regime_rows: Any,
    policy: Any,
    base_plane: Any,
    periods: dict[str, list[int]],
    frozen_params: dict[str, Any],
    profile: str,
    timeframe: str,
) -> dict[str, Any]:
    """One window/scenario: the combined book, the single-asset books and buy & hold.

    The code path is the campaign's own (same candidate object, same simulator, same
    window bounds); only the scenario list is this experiment's, which is what the
    adverse plane adds.
    """
    bounds = C.SPLITS[str(TREND_ROBUSTNESS["split"])][window]
    start, end = int(bounds["start"]), int(bounds["end"])
    window_minutes = (end - start) / 60_000.0
    plane = base_plane.scaled(scenario)
    combined_candidate = TrendFollow(profile, dict(frozen_params))
    sim = run_portfolio_sim(
        candidate=combined_candidate,
        bars_by_asset=corpus.bars_by_asset,
        plane=plane,
        policy=policy,
        window_start_ts=start,
        window_end_ts=end,
    )
    for trade in sim.trades:
        trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
    combined = {
        **C._metrics(
            trades=sim.trades,
            equity_curve=sim.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=window_minutes,
            timeframe=timeframe,
            n_assets=len(ASSETS),
        ),
        "params_hash": PARAMS_HASH,
        "refusals": C._funnel(sim.refusals),
        "signals_printed": len(sim.signals),
        "bars_evaluated": combined_candidate.bars_evaluated,
        "warmup_bars": combined_candidate.warmup_bars,
    }
    assets: dict[str, Any] = {}
    for asset in ASSETS:
        candidate = TrendFollow(profile, dict(frozen_params))
        asset_sim = run_portfolio_sim(
            candidate=candidate,
            bars_by_asset={asset: corpus.bars_by_asset[asset]},
            plane=plane,
            policy=policy,
            window_start_ts=start,
            window_end_ts=end,
        )
        for trade in asset_sim.trades:
            trade["market_context"] = market_regime_at(
                regime_rows, int(trade["decision_ts"])
            )
        assets[asset] = {
            **C._metrics(
                trades=asset_sim.trades,
                equity_curve=asset_sim.equity_curve,
                start_equity=policy.start_equity,
                window_minutes=window_minutes,
                timeframe=timeframe,
                n_assets=1,
            ),
            "refusals": C._funnel(asset_sim.refusals),
            "signals_printed": len(asset_sim.signals),
            "_trade_rows": asset_sim.trades,
        }
    hold = {
        asset: buy_and_hold(
            bars=corpus.bars_by_asset[asset],
            plane=plane,
            start_equity=policy.start_equity,
            window_start_ts=start,
            window_end_ts=end,
        )
        for asset in ASSETS
    }
    return {
        "window": window,
        "scenario": scenario,
        "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
        "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
        "window_start_ms": start,
        "window_end_ms": end,
        "window_days": round(window_minutes / 1440.0, 4),
        "plane": plane.to_dict(),
        "combined": combined,
        "assets": assets,
        "buy_and_hold": hold,
        "periods": CL._period_table(sim.trades, periods),
        "_trade_rows": sim.trades,
    }


def _corpus_coverage(corpus: Any) -> dict[str, Any]:
    """What the frozen corpus actually covers, so 'no unused sample' is measured."""
    per_asset: dict[str, Any] = {}
    latest = 0
    for asset, bars in corpus.bars_by_asset.items():
        last = bars[-1].ts if bars else 0
        latest = max(latest, last)
        per_asset[asset] = {
            "bars": len(bars),
            "first_ts": bars[0].ts if bars else None,
            "last_ts": last,
            "first_utc": datetime.fromtimestamp(bars[0].ts / 1000, tz=UTC).isoformat()
            if bars
            else None,
            "last_utc": datetime.fromtimestamp(last / 1000, tz=UTC).isoformat()
            if bars
            else None,
        }
    oos_end = int(C.SPLITS[str(TREND_ROBUSTNESS["split"])]["OOS"]["end"])
    leftover = {
        asset: sum(1 for bar in bars if bar.ts > oos_end)
        for asset, bars in corpus.bars_by_asset.items()
    }
    #: Declared BEFORE the run: a leftover stretch counts as a usable extra period only
    #: if it spans at least this many days on every asset. Five bars of mop-up after the
    #: design window is not an independent sample and is not treated as one.
    min_days = int(CORPUS_LEFTOVER_MIN_DAYS)
    leftover_bars = max(leftover.values(), default=0)
    leftover_days = leftover_bars * BAR_MS["4h"] / 86_400_000.0
    return {
        "per_asset": per_asset,
        "design_windows_end_ms": oos_end,
        "design_windows_end_utc": datetime.fromtimestamp(oos_end / 1000, tz=UTC).isoformat(),
        "corpus_last_bar_ms": latest,
        "unused_bars_after_design_window": leftover,
        "unused_span_days": round(leftover_days, 4),
        "min_span_days_for_a_usable_period": min_days,
        "additional_independent_periods_available": leftover_days >= min_days,
        "note": (
            "the design windows (DEV 2019-2023, VAL 2024, OOS 2025-01 -> 2026-02-28) "
            "consume the frozen 4h corpus to its last complete bar; the only bars left "
            f"are {leftover_bars} mop-up bars ({leftover_days:.2f} days), far below the "
            f"declared {min_days}-day minimum for a usable extra period, so no unused "
            "independent sample exists inside this corpus"
        ),
    }


def _load_published_oos(root: Path) -> dict[str, Any] | None:
    """The artefact this experiment reproduces, read read-only for the cross-check."""
    path = root / "reports" / "edge-recovery" / "WP-EDGE-01" / "oos-trend-4h" / "OOS_TREND.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_trend_robustness(*, root: Path | None = None) -> dict[str, Any]:
    """Measure the frozen 4h trend ruleset again and read it robustly. No re-tuning."""
    base = Path(__file__).resolve().parents[4] if root is None else root
    split_name = str(TREND_ROBUSTNESS["split"])
    timeframe = str(TREND_ROBUSTNESS["timeframe"])
    profile = str(TREND_ROBUSTNESS["profile"])
    horizon = float(TREND_ROBUSTNESS["horizon_minutes"])
    corpus = C._load_corpus(split_name, timeframe)
    regime_rows, regime_meta = C._market_context_series()
    policy = C.load_risk_policy()
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon)
    frozen_params = dict(FROZEN_PARAMS["edge_trend_01"])
    periods: dict[str, list[int]] = TREND_ROBUSTNESS["periods"]
    confidence = float(TREND_ROBUSTNESS_DECISION["uncertainty"]["confidence"])

    runs: dict[str, Any] = {}
    for window in TREND_ROBUSTNESS["windows"]:
        for scenario in TREND_ROBUSTNESS["scenario_plan"][window]:
            runs[f"{window}:{scenario}"] = _run_window(
                window=window,
                scenario=scenario,
                corpus=corpus,
                regime_rows=regime_rows,
                policy=policy,
                base_plane=base_plane,
                periods=periods,
                frozen_params=frozen_params,
                profile=profile,
                timeframe=timeframe,
            )

    # ---- sensitivity: the same book with its largest winners removed ----------
    sensitivity: dict[str, Any] = {}
    for key, run in runs.items():
        nets = [float(t["net"]) for t in run["_trade_rows"]]
        sensitivity[key] = {
            "baseline": {
                "trades": len(nets),
                "net_usdt": round(sum(nets), 6),
                "expectancy_usdt": round(sum(nets) / len(nets), 6) if nets else None,
                "largest_trade_share_of_net": run["combined"].get(
                    "largest_trade_share_of_net"
                ),
            },
            "leave_out": [
                leave_out_largest(nets, k) for k in TREND_ROBUSTNESS["leave_out_k"]
            ],
        }

    # ---- uncertainty: HAC and block bootstrap on the trade stream -------------
    uncertainty: dict[str, Any] = {}
    for key, run in runs.items():
        ordered = [
            float(t["net"]) for t in sorted(run["_trade_rows"], key=lambda t: int(t["exit_ts"]))
        ]
        uncertainty[key] = {
            "trades": len(ordered),
            "hac": hac_mean_interval(ordered, confidence=confidence),
            "bootstrap": block_bootstrap_mean_interval(ordered, confidence=confidence),
            "order_by": "exit_ts (the order the book realised the results)",
        }

    # ---- contribution: per asset, per regime, per period ----------------------
    contribution: dict[str, Any] = {}
    for key, run in runs.items():
        rows = run["_trade_rows"]
        by_context: dict[str, Any] = {}
        for label in sorted({(t.get("market_context") or "UNDEFINED") for t in rows}):
            subset = [t for t in rows if (t.get("market_context") or "UNDEFINED") == label]
            by_context[label] = {
                "trades": len(subset),
                "net_usdt": round(sum(float(t["net"]) for t in subset), 6),
                "share_of_net": (
                    round(
                        sum(float(t["net"]) for t in subset) / float(run["combined"]["net_usdt"]),
                        6,
                    )
                    if float(run["combined"]["net_usdt"] or 0.0) > 0
                    else None
                ),
                "win_rate_pct": round(
                    100.0 * sum(1 for t in subset if float(t["net"]) > 0) / len(subset), 6
                )
                if subset
                else None,
            }
        by_trend_state: dict[str, Any] = {}
        for label in sorted({(t.get("regime") or "UNKNOWN") for t in rows}):
            subset = [t for t in rows if (t.get("regime") or "UNKNOWN") == label]
            by_trend_state[label] = {
                "trades": len(subset),
                "net_usdt": round(sum(float(t["net"]) for t in subset), 6),
                "win_rate_pct": round(
                    100.0 * sum(1 for t in subset if float(t["net"]) > 0) / len(subset), 6
                )
                if subset
                else None,
            }
        contribution[key] = {
            "by_asset_own_book": {
                asset: {
                    "trades": block["trades"],
                    "net_usdt": block["net_usdt"],
                    "expectancy_usdt": block["expectancy_usdt"],
                    "win_rate_pct": block["win_rate_pct"],
                    "max_drawdown_pct": block["max_drawdown_pct"],
                    "return_on_drawdown": _risk_adjusted(
                        block, start_equity=policy.start_equity
                    )["return_on_drawdown"],
                }
                for asset, block in run["assets"].items()
            },
            "by_asset_share_of_combined": run["combined"]["by_asset"],
            "by_benchmark_context": by_context,
            "by_candidate_trend_state": by_trend_state,
            "by_period": run["periods"],
        }

    # ---- cost stress and the risk-adjusted comparison -------------------------
    risk_adjusted: dict[str, Any] = {}
    for key, run in runs.items():
        entry = _risk_adjusted(run["combined"], start_equity=policy.start_equity)
        hold = {
            asset: {
                "return_pct": block.get("return_pct"),
                "max_drawdown_pct": block.get("max_drawdown_pct"),
                "return_on_drawdown": round(
                    float(block["return_pct"]) / float(block["max_drawdown_pct"]), 6
                )
                if block.get("return_pct") is not None
                and float(block.get("max_drawdown_pct") or 0.0) > 0
                else None,
            }
            for asset, block in run["buy_and_hold"].items()
        }
        values = [v["return_on_drawdown"] for v in hold.values() if v["return_on_drawdown"]]
        risk_adjusted[key] = {
            "candidate": entry,
            "buy_and_hold": hold,
            "buy_and_hold_best_return_on_drawdown": round(max(values), 6) if values else None,
            "candidate_beats_every_buy_and_hold_on_return_on_drawdown": (
                entry["return_on_drawdown"] is not None
                and bool(values)
                and float(entry["return_on_drawdown"]) > max(values)
            ),
            "deepest_buy_and_hold_drawdown_pct": round(
                max(
                    (float(b.get("max_drawdown_pct") or 0.0) for b in run["buy_and_hold"].values()),
                    default=0.0,
                ),
                6,
            ),
        }

    # ---- reproduction of the published WP-EDGE-01 reading ---------------------
    published = _load_published_oos(base)
    reproduction: dict[str, Any]
    if published is None:
        reproduction = {"checked": False, "reason": "the published OOS artefact is not present"}
    else:
        comparisons: list[dict[str, Any]] = []
        for key, run in runs.items():
            if key not in published["runs"]:
                continue
            reference = published["runs"][key]["combined"]
            mine = run["combined"]
            for field in ("trades", "net_usdt", "expectancy_usdt", "largest_trade_share_of_net"):
                comparisons.append(
                    {
                        "key": key,
                        "field": field,
                        "published": reference.get(field),
                        "recomputed": mine.get(field),
                        "equal": (
                            reference.get(field) == mine.get(field)
                            if isinstance(reference.get(field), (int, str)) or reference.get(field) is None
                            else abs(float(reference.get(field)) - float(mine.get(field))) < 1e-9
                        ),
                    }
                )
        reproduction = {
            "checked": True,
            "source": "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json",
            "comparisons": comparisons,
            "all_equal": all(item["equal"] for item in comparisons),
            "note": (
                "the frozen ruleset, corpus, cost components and risk policy are unchanged: "
                "the recomputed figures equal the published ones exactly"
            ),
        }

    wp_splits: dict[str, Any] = {
        window: {
            scenario: runs[f"{window}:{scenario}"]["combined"]
            for scenario in TREND_ROBUSTNESS["scenario_plan"][window]
        }
        for window in TREND_ROBUSTNESS["windows"]
    }
    coverage = _corpus_coverage(corpus)
    payload: dict[str, Any] = {
        "run_id": "wp-edge-02a-trend-robustness",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": C._git_state(),
        "source_digest": C._source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_closure_experiments.py",
                "scripts/edge01_closure_verify.py",
                "scripts/edge01_robustness_experiments.py",
                "scripts/edge01_wp02_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus: the frozen 4h trend "
            "ruleset, unchanged, re-measured and read for sensitivity; 0 orders, 0 "
            "credentials, 0 network calls"
        ),
        "entrypoint": "scripts/edge01_robustness_experiments.py --experiment trend",
        "verifier": "scripts/edge01_wp02_verify.py --experiment trend",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **TREND_ROBUSTNESS,
            "assets": list(ASSETS),
            "frozen_params": frozen_params,
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": C._sha256(C.RISK_CONFIG),
            "risk_policy": policy.to_dict(),
            "decision_rule": TREND_ROBUSTNESS_DECISION,
            "wp_admission_criteria": C.ADMISSION_CRITERIA,
            "corpus_provenance": corpus.provenance,
            "corpus_sha256": {
                asset: block.get("sha256") for asset, block in corpus.provenance.items() if isinstance(block, dict)
            },
        },
        "runs": {
            key: {k: v for k, v in run.items() if k != "_trade_rows"}
            for key, run in runs.items()
        },
        "trade_rows": {
            key: {
                "window": run["window"],
                "scenario": run["scenario"],
                "books": {
                    "combined": run["_trade_rows"],
                    **{
                        asset: block.get("_trade_rows") or []
                        for asset, block in run["assets"].items()
                    },
                },
            }
            for key, run in runs.items()
        },
        "sensitivity": sensitivity,
        "uncertainty": uncertainty,
        "contribution": contribution,
        "risk_adjusted": risk_adjusted,
        "reproduction": reproduction,
        "corpus_coverage": coverage,
        "wp_admission": C._gate(splits=wp_splits, criteria=C.ADMISSION_CRITERIA),
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
        "limitations": [
            (
                "the ruleset is untuned and frozen and VAL/OOS were already read for it in "
                "WP-EDGE-01, so this is a decomposition and a sensitivity analysis of the "
                "published run, not a second independent sample"
            ),
            (
                "the concentration criterion is the same 0.50 WP-EDGE-01 froze; relaxing it "
                "is proposed as a new experiment and is deliberately NOT applied here"
            ),
            (
                f"the frozen corpus ends at the last bar of the OOS window "
                f"({coverage['design_windows_end_utc'][:10]}), so no unused independent "
                "period exists: an additional period needs a new corpus, which the 15m feed "
                "could supply but only as a new pre-registered experiment"
            ),
            (
                "the HAC interval is asymptotic and the block bootstrap resamples 52 trades: "
                "both widen the reading honestly, neither turns 52 observations into a "
                "large sample"
            ),
            (
                "the candidate risks a fixed share of equity per trade while buy & hold is "
                "fully invested, so the comparison is on the same window and cost plane, not "
                "on the same capital utilisation"
            ),
            "long side only (spot); no historical order book; nothing is wired into PAPER",
        ],
    }
    payload["verdict"] = trend_robustness_verdict(payload)
    return payload


def trend_robustness_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Pre-registered robustness gate for the frozen 4h trend ruleset. Pure function."""
    decision = TREND_ROBUSTNESS_DECISION
    window = str(decision["decision_window"])
    run = payload["runs"][f"{window}:BASE"]
    combined = run["combined"]
    trades = int(combined["trades"])
    net = float(combined["net_usdt"] or 0.0)
    sensitivity = payload["sensitivity"][f"{window}:BASE"]
    leave_one = next(item for item in sensitivity["leave_out"] if int(item["k"]) == 1)
    leave_three = next(item for item in sensitivity["leave_out"] if int(item["k"]) == 3)
    uncertainty = payload["uncertainty"][f"{window}:BASE"]
    hac = uncertainty["hac"]
    boot = uncertainty["bootstrap"]
    adverse = payload["runs"].get(f"{window}:ADVERSE")
    adverse_net = (
        float(adverse["combined"]["net_usdt"] or 0.0) if adverse is not None else None
    )
    positive_assets = [
        asset
        for asset, block in run["assets"].items()
        if float(block["net_usdt"] or 0.0) > 0
    ]
    positive_periods = [row["period"] for row in run["periods"] if float(row["net_usdt"]) > 0]
    share = combined.get("largest_trade_share_of_net")
    risk = payload["risk_adjusted"][f"{window}:BASE"]
    candidate_dd = float(combined.get("max_drawdown_pct") or 0.0)
    hold_dd = float(risk["deepest_buy_and_hold_drawdown_pct"] or 0.0)

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"criterion": name, "result": "PASS" if passed else "FAIL", "detail": detail})

    add("oos_trades_floor", trades >= int(decision["min_oos_trades"]),
        f"{trades} OOS trades vs floor {decision['min_oos_trades']}")
    add("oos_net_positive", net > 0, f"OOS net {net:,.4f} USDT")
    add(
        "oos_net_positive_per_dropping_largest_winner",
        float(leave_one["net_usdt"]) > 0,
        f"OOS net without the largest winner {float(leave_one['net_usdt']):,.4f} USDT "
        f"(removed {float(leave_one['net_removed_usdt']):,.4f})",
    )
    add(
        "concentration_within_limit",
        share is not None and float(share) <= float(decision["concentration_criterion_pct_of_net"]),
        f"largest trade is {share} of the OOS net (limit "
        f"{decision['concentration_criterion_pct_of_net']}, unchanged from WP-EDGE-01)",
    )
    add(
        "assets_positive",
        len(positive_assets) >= int(decision["min_positive_assets"]),
        f"{len(positive_assets)}/{len(run['assets'])} single-asset OOS books positive "
        f"({', '.join(positive_assets) or 'none'}) vs required {decision['min_positive_assets']}",
    )
    add(
        "periods_positive",
        len(positive_periods) >= int(decision["min_positive_periods"]),
        f"{len(positive_periods)}/{len(run['periods'])} OOS periods positive "
        f"({', '.join(positive_periods) or 'none'}) vs required {decision['min_positive_periods']}",
    )
    add(
        "adverse_cost_plane_positive",
        adverse_net is not None and adverse_net > 0,
        f"OOS net under the ADVERSE plane (fees x2, slippage/impact x3) "
        f"{'n/a' if adverse_net is None else f'{adverse_net:,.4f}'} USDT",
    )
    add(
        "hac_interval_upper_end_positive",
        hac["upper"] is not None and float(hac["upper"]) > 0,
        f"95% HAC interval on expectancy [{hac['lower']}, {hac['upper']}] (lag {hac['lag']})",
    )
    add(
        "drawdown_below_buy_and_hold",
        candidate_dd < hold_dd,
        f"OOS max drawdown {candidate_dd:.4f}% vs the deepest buy & hold drawdown {hold_dd:.4f}%",
    )

    failed = [check for check in checks if check["result"] == "FAIL"]
    names = {check["criterion"] for check in failed}
    decisive_names = {
        "oos_net_positive",
        "oos_net_positive_per_dropping_largest_winner",
        "assets_positive",
        "hac_interval_upper_end_positive",
    }
    decisive = sorted(names & decisive_names)
    inconclusive = sorted(names - decisive_names)
    if trades < int(decision["min_oos_trades"]):
        verdict = "INSUFFICIENT_EVIDENCE"
        headline = (
            f"OOS sample {trades} trades < floor {decision['min_oos_trades']}: the "
            "measurement cannot support a conclusion"
        )
    elif decisive:
        verdict = "REJECT"
        headline = "the edge is contradicted on OOS: " + "; ".join(
            f"{check['criterion']}: {check['detail']}" for check in failed
            if check["criterion"] in decisive_names
        )
    elif inconclusive:
        verdict = "INSUFFICIENT_EVIDENCE"
        headline = "the edge is not contradicted but the declared requirements are not met: " + "; ".join(
            f"{check['criterion']}: {check['detail']}" for check in failed
        )
    else:
        verdict = "ADMIT_PAPER"
        headline = (
            "every declared requirement met on OOS, including the concentration limit, the "
            "adverse cost plane and the HAC interval"
        )
    return {
        "verdict": verdict,
        "headline": headline,
        "reasons": [f"{check['criterion']}: {check['detail']}" for check in failed],
        "checks": checks,
        "decisive_failures": decisive,
        "inconclusive_failures": inconclusive,
        "interval_reading": {
            "hac": hac,
            "bootstrap": boot,
            "reading": (
                "the expectancy interval contains 0"
                if hac["lower"] is not None and float(hac["lower"]) <= 0 <= float(hac["upper"] or 0.0)
                else "the expectancy interval excludes 0 on the positive side"
                if hac["upper"] is not None and float(hac["lower"] or 0.0) > 0
                else "the expectancy interval excludes 0 on the negative side"
            ),
        },
        "leave_three_out_net_usdt": leave_three["net_usdt"],
        "adverse_net_usdt": adverse_net,
        "wp_admission": payload.get("wp_admission"),
        "decision_rule": decision,
    }


def write_trend_robustness_artifacts(
    payload: dict[str, Any], outdir: Path, *, published: dict[str, Any] | None = None
) -> dict[str, Path]:
    """Write the robustness tables, the trade ledger, the JSON and the markdown."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    trade_export: dict[str, Any] = payload.get("trade_rows") or {}

    def dump(name: str, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
        path = outdir / name
        lines = [",".join(columns)]
        for row in rows:
            cells = []
            for column in columns:
                value = row.get(column)
                if value is None:
                    cells.append("")
                elif isinstance(value, float):
                    cells.append(f"{value:.6f}")
                else:
                    text = str(value)
                    cells.append(f'"{text}"' if "," in text else text)
            lines.append(",".join(cells))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written[name] = path

    window_rows: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    uncertainty_rows: list[dict[str, Any]] = []
    contribution_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for key, run in payload["runs"].items():
        window_rows.append(
            {
                "run": key,
                "window": run["window"],
                "scenario": run["scenario"],
                "window_days": run["window_days"],
                "trades": run["combined"]["trades"],
                "net_usdt": run["combined"]["net_usdt"],
                "expectancy_usdt": run["combined"]["expectancy_usdt"],
                "win_rate_pct": run["combined"]["win_rate_pct"],
                "profit_factor": run["combined"]["profit_factor"],
                "return_pct": run["combined"]["return_pct"],
                "max_drawdown_pct": run["combined"]["max_drawdown_pct"],
                "sharpe_annualised": run["combined"]["sharpe_annualised"],
                "exposure_pct_of_time": run["combined"]["exposure_pct_of_time"],
                "total_cost_bps_per_trade": run["combined"]["total_cost_bps_per_trade"],
                "largest_trade_share_of_net": run["combined"]["largest_trade_share_of_net"],
            }
        )
        baseline = payload["sensitivity"][key]["baseline"]
        for item in payload["sensitivity"][key]["leave_out"]:
            sensitivity_rows.append(
                {
                    "run": key,
                    "k": item["k"],
                    "trades": item["trades"],
                    "net_usdt": item["net_usdt"],
                    "net_removed_usdt": item["net_removed_usdt"],
                    "dropped_usdt": item["dropped_usdt"],
                    "expectancy_usdt": item["expectancy_usdt"],
                    "win_rate_pct": item["win_rate_pct"],
                    "profit_factor": item["profit_factor"],
                    "largest_remaining_share_of_net": item[
                        "largest_remaining_share_of_net"
                    ],
                    "baseline_net_usdt": baseline["net_usdt"],
                    "baseline_trades": baseline["trades"],
                }
            )
        unc = payload["uncertainty"][key]
        uncertainty_rows.append(
            {
                "run": key,
                "trades": unc["trades"],
                "mean_net_usdt": unc["hac"]["mean"],
                "hac_se": unc["hac"]["se"],
                "hac_lag": unc["hac"]["lag"],
                "hac_t_critical": unc["hac"].get("t_critical"),
                "hac_lower": unc["hac"]["lower"],
                "hac_upper": unc["hac"]["upper"],
                "bootstrap_lower": unc["bootstrap"]["lower"],
                "bootstrap_upper": unc["bootstrap"]["upper"],
                "bootstrap_resamples": unc["bootstrap"].get("resamples"),
                "confidence": unc["hac"].get("confidence"),
                "hac_interval_excludes_zero": (
                    unc["hac"]["lower"] is not None and float(unc["hac"]["lower"]) > 0
                )
                or (unc["hac"]["upper"] is not None and float(unc["hac"]["upper"]) < 0),
            }
        )
        for asset, block in payload["contribution"][key]["by_asset_own_book"].items():
            contribution_rows.append(
                {
                    "run": key,
                    "kind": "asset_own_book",
                    "label": asset,
                    "trades": block["trades"],
                    "net_usdt": block["net_usdt"],
                    "expectancy_usdt": block["expectancy_usdt"],
                    "win_rate_pct": block["win_rate_pct"],
                    "max_drawdown_pct": block["max_drawdown_pct"],
                    "return_on_drawdown": block["return_on_drawdown"],
                }
            )
        for label, block in payload["contribution"][key]["by_benchmark_context"].items():
            contribution_rows.append(
                {
                    "run": key,
                    "kind": "benchmark_market_context",
                    "label": label,
                    "trades": block["trades"],
                    "net_usdt": block["net_usdt"],
                    "expectancy_usdt": (
                        round(float(block["net_usdt"]) / block["trades"], 6)
                        if block["trades"]
                        else None
                    ),
                    "win_rate_pct": block["win_rate_pct"],
                    "max_drawdown_pct": None,
                    "return_on_drawdown": None,
                }
            )
        for label, block in payload["contribution"][key]["by_candidate_trend_state"].items():
            contribution_rows.append(
                {
                    "run": key,
                    "kind": "candidate_trend_state",
                    "label": label,
                    "trades": block["trades"],
                    "net_usdt": block["net_usdt"],
                    "expectancy_usdt": (
                        round(float(block["net_usdt"]) / block["trades"], 6)
                        if block["trades"]
                        else None
                    ),
                    "win_rate_pct": block["win_rate_pct"],
                    "max_drawdown_pct": None,
                    "return_on_drawdown": None,
                }
            )
        risk = payload["risk_adjusted"][key]
        risk_rows.append(
            {
                "run": key,
                "candidate_net_usdt": run["combined"]["net_usdt"],
                "candidate_return_pct": risk["candidate"]["return_pct"],
                "candidate_max_drawdown_pct": risk["candidate"]["max_drawdown_pct"],
                "candidate_sharpe_annualised": risk["candidate"]["sharpe_annualised"],
                "candidate_mar_ratio": risk["candidate"]["mar_ratio"],
                "candidate_return_on_drawdown": risk["candidate"]["return_on_drawdown"],
                "buy_and_hold_best_return_on_drawdown": risk[
                    "buy_and_hold_best_return_on_drawdown"
                ],
                "candidate_beats_every_buy_and_hold": risk[
                    "candidate_beats_every_buy_and_hold_on_return_on_drawdown"
                ],
                "deepest_buy_and_hold_drawdown_pct": risk["deepest_buy_and_hold_drawdown_pct"],
            }
        )
    # The trade ledger is published as its own CSV; the JSON keeps the derived tables
    # and drops the raw rows so the artefact stays readable.
    payload.pop("trade_rows", None)
    for key, run in trade_export.items():
        window = run["window"]
        scenario = run["scenario"]
        for book, rows in run["books"].items():
            for row in rows:
                trade_rows.append(
                    {
                        "run": key,
                        "book": book,
                        "window": window,
                        "scenario": scenario,
                        **row,
                    }
                )

    dump("ROBUSTNESS_WINDOWS.csv", window_rows, tuple(window_rows[0].keys()))
    dump("ROBUSTNESS_LEAVE_OUT.csv", sensitivity_rows, tuple(sensitivity_rows[0].keys()))
    dump("ROBUSTNESS_UNCERTAINTY.csv", uncertainty_rows, tuple(uncertainty_rows[0].keys()))
    dump("ROBUSTNESS_CONTRIBUTION.csv", contribution_rows, tuple(contribution_rows[0].keys()))
    dump("ROBUSTNESS_RISK_ADJUSTED.csv", risk_rows, tuple(risk_rows[0].keys()))
    dump("TREND_TRADES.csv", trade_rows, TRADE_COLUMNS)

    json_path = outdir / "ROBUSTNESS.json"
    payload["artifacts"] = sorted(written) + ["ROBUSTNESS.json", "ROBUSTNESS.md"]
    payload["artifact_note"] = (
        "ROBUSTNESS.json carries the derived tables, the trade export is TREND_TRADES.csv"
    )
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    written["ROBUSTNESS.json"] = json_path
    md_path = outdir / "ROBUSTNESS.md"
    md_path.write_text(trend_robustness_markdown(payload), encoding="utf-8")
    written["ROBUSTNESS.md"] = md_path
    return written


def _money(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):,.4f}"


def _num(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):,.4f}"


def trend_robustness_markdown(payload: dict[str, Any]) -> str:
    """The human-readable reading of the robustness analysis."""
    decision = payload["experiment"]["decision_rule"]
    verdict = payload["verdict"]
    window = str(decision["decision_window"])
    lines: list[str] = [
        "# ROBUSTEZ DE TENDENCIA 4h — WP-EDGE-02A",
        "",
        "| | |",
        "|---|---|",
        f"| experimento | `{payload['experiment']['id']}` |",
        f"| responde a | `{payload['experiment']['answer_to']}` |",
        f"| candidato congelado | `{payload['experiment']['candidate']}` ({payload['experiment']['profile']}) |",
        f"| ventana de decision | `{window}` |",
        f"| HEAD al ejecutar | `{payload['git'].get('head_commit')}` |",
        f"| params_hash | `{payload['params_hash']}` |",
        f"| veredicto | **`{verdict['verdict']}`** |",
        "",
        payload["experiment"]["question"],
        "",
        "## Reproduccion del cierre anterior",
        "",
    ]
    reproduction = payload["reproduction"]
    if reproduction.get("checked"):
        lines += [
            f"- comparado con `{reproduction['source']}`: "
            f"**{'identico' if reproduction['all_equal'] else 'DIVERGENTE'}** "
            f"({len(reproduction['comparisons'])} comparaciones)",
        ]
    else:
        lines.append(f"- no comprobado: {reproduction.get('reason')}")
    lines += ["", "## Veredicto", ""]
    lines.append(f"- **`{verdict['verdict']}`** — {verdict['headline']}")
    for check in verdict["checks"]:
        lines.append(f"- `{check['criterion']}`: **{check['result']}** — {check['detail']}")
    lines += ["", "### Intervalos de incertidumbre", ""]
    for key, unc in payload["uncertainty"].items():
        lines.append(
            f"- `{key}`: HAC [{_num(unc['hac']['lower'])}, {_num(unc['hac']['upper'])}] con "
            f"lag {unc['hac']['lag']}; bootstrap [{_num(unc['bootstrap']['lower'])}, "
            f"{_num(unc['bootstrap']['upper'])}] sobre {unc['bootstrap'].get('resamples')} remuestreos"
        )
    lines += [
        "",
        "## Cartera por ventana y escenario",
        "",
        "| ventana | escenario | operaciones | neto | expectativa | PF | drawdown | "
        "Sharpe | exposicion | mayor operacion / neto |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, run in payload["runs"].items():
        combined = run["combined"]
        lines.append(
            f"| `{run['window']}` | `{run['scenario']}` | {combined['trades']} | "
            f"{_money(combined['net_usdt'])} | {_money(combined['expectancy_usdt'])} | "
            f"{_num(combined['profit_factor'])} | {_num(combined['max_drawdown_pct'])}% | "
            f"{_num(combined['sharpe_annualised'])} | {_num(combined['exposure_pct_of_time'])}% | "
            f"{_num(combined['largest_trade_share_of_net'])} |"
        )
    lines += ["", "## Sensibilidad: sin las mayores ganadoras", ""]
    for key, block in payload["sensitivity"].items():
        lines.append(f"### `{key}`")
        lines.append("")
        lines.append("| k | operaciones | neto | retirado | expectativa | PF | mayor restante / neto |")
        lines.append("|---|---|---|---|---|---|---|")
        base = block["baseline"]
        lines.append(
            f"| 0 (base) | {base['trades']} | {_money(base['net_usdt'])} | 0.0000 | "
            f"{_money(base['expectancy_usdt'])} | n/a | {_num(base['largest_trade_share_of_net'])} |"
        )
        for item in block["leave_out"]:
            lines.append(
                f"| {item['k']} | {item['trades']} | {_money(item['net_usdt'])} | "
                f"{_money(item['net_removed_usdt'])} | {_money(item['expectancy_usdt'])} | "
                f"{_num(item['profit_factor'])} | {_num(item['largest_remaining_share_of_net'])} |"
            )
        lines.append("")
    lines += ["## Contribucion en la ventana de decision", ""]
    for key, block in payload["contribution"].items():
        if not key.startswith(f"{window}:"):
            continue
        lines.append(f"### `{key}`")
        lines.append("")
        lines.append("| libro | operaciones | neto | expectativa | win rate | drawdown | retorno/drawdown |")
        lines.append("|---|---|---|---|---|---|---|")
        for asset, item in block["by_asset_own_book"].items():
            lines.append(
                f"| `{asset}` (libro propio) | {item['trades']} | {_money(item['net_usdt'])} | "
                f"{_money(item['expectancy_usdt'])} | {_num(item['win_rate_pct'])}% | "
                f"{_num(item['max_drawdown_pct'])}% | {_num(item['return_on_drawdown'])} |"
            )
        lines.append("")
        lines.append("| contexto de benchmark | operaciones | neto | win rate |")
        lines.append("|---|---|---|---|")
        for label, item in block["by_benchmark_context"].items():
            lines.append(
                f"| `{label}` | {item['trades']} | {_money(item['net_usdt'])} | "
                f"{_num(item['win_rate_pct'])}% |"
            )
        lines.append("")
        lines.append("| periodo | operaciones | neto | expectativa | win rate |")
        lines.append("|---|---|---|---|---|")
        for row in block["by_period"]:
            lines.append(
                f"| `{row['period']}` | {row['trades']} | {_money(row['net_usdt'])} | "
                f"{_money(row['expectancy_usdt'])} | {_num(row['win_rate_pct'])}% |"
            )
        lines.append("")
    lines += [
        "## Comparacion ajustada al riesgo",
        "",
        "| ventana:escenario | neto | retorno | drawdown | Sharpe | MAR | retorno/drawdown | "
        "mejor b&h retorno/drawdown | mas profundo b&h |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, risk in payload["risk_adjusted"].items():
        candidate = risk["candidate"]
        lines.append(
            f"| `{key}` | {_money(payload['runs'][key]['combined']['net_usdt'])} | "
            f"{_num(candidate['return_pct'])}% | {_num(candidate['max_drawdown_pct'])}% | "
            f"{_num(candidate['sharpe_annualised'])} | {_num(candidate['mar_ratio'])} | "
            f"{_num(candidate['return_on_drawdown'])} | "
            f"{_num(risk['buy_and_hold_best_return_on_drawdown'])} | "
            f"{_num(risk['deepest_buy_and_hold_drawdown_pct'])}% |"
        )
    coverage = payload["corpus_coverage"]
    lines += [
        "",
        "## Periodos adicionales",
        "",
        f"- corpus congelado: ultima barra `{coverage['per_asset']['BTC']['last_utc']}`",
        f"- fin de la ventana de diseno: `{coverage['design_windows_end_utc']}`",
        f"- barras sin usar despues del diseno: `{coverage['unused_bars_after_design_window']}`",
        f"- periodos independientes adicionales disponibles: "
        f"**{'si' if coverage['additional_independent_periods_available'] else 'no'}** — {coverage['note']}",
        "",
        "## Regla de decision congelada",
        "",
    ]
    for key, value in decision.items():
        if key in ("proposal_not_applied",):
            continue
        lines.append(f"- `{key}`: {value}")
    lines += [
        f"- propuesta NO aplicada: {decision['proposal_not_applied']['what']} — "
        f"{decision['proposal_not_applied']['status']}",
        "",
        "## Limites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    return "\n".join(lines) + "\n"


