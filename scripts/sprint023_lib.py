"""RFC-023 — generalization diagnosis statistical primitives.

Read-only analysis of the frozen Sprint 002 outputs. NO new strategy, NO
tuning, NO holdout access (W6-W7 is never loaded here). Everything is computed
from the certified dataset (W1-W4 DISCOVERY, W5 VALIDATION) and the Sprint 002
signal functions and event engine, which are imported, not modified.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_pipeline as P  # noqa: E402
import sprint002_signals as S  # noqa: E402

OUT = REPO / "reports" / "generalization"
SEED = 20261023
N_PERM = 200
N_BOOT = 2000
HORIZONS = (1, 2, 4, 8, 16)
HORIZON_LABEL = {1: "30m", 2: "1h", 4: "2h", 8: "4h", 16: "8h"}
MIN_TRADES = L.MIN_TRADES
COST = L.CERTIFIED_ROUND_TRIP_BPS

# ---------------------------------------------------------------------------
# frozen Sprint 002 outputs (regenerated deterministically, never tuned)
# ---------------------------------------------------------------------------

_DISC: list[dict[str, Any]] | None = None


def discovery() -> list[dict[str, Any]]:
    global _DISC
    if _DISC is None:
        _DISC = P.stage_discovery()
    return _DISC


def net_of(trades: list[L.Trade]) -> NDArray[Any]:
    return np.array([t.net_bps for t in trades], dtype=np.float64)


def gross_of(trades: list[L.Trade]) -> NDArray[Any]:
    return np.array([t.gross_bps for t in trades], dtype=np.float64)


# ---------------------------------------------------------------------------
# basic statistics (no scipy in this environment)
# ---------------------------------------------------------------------------


def rankdata(x: NDArray[Any]) -> NDArray[Any]:
    v = np.asarray(x, dtype=np.float64)
    n = int(v.shape[0])
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1, dtype=np.float64)
    sx = v[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sx[j + 1] == sx[i]:
            j += 1
        if j > i:
            avg = float((ranks[order[i]] + ranks[order[j]]) / 2.0)
            for k in range(i, j + 1):
                ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(a: NDArray[Any], b: NDArray[Any]) -> float | None:
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 3:
        return None
    x, y = x[m], y[m]
    xs = float(np.std(x))
    ys = float(np.std(y))
    if xs == 0.0 or ys == 0.0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman_ic(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 5:
        return None
    return pearson(rankdata(x[m]), rankdata(y[m]))


def trimmed_mean(x: NDArray[Any], frac: float = 0.10) -> float | None:
    v = np.asarray(x, dtype=np.float64)
    v = v[np.isfinite(v)]
    n = int(v.shape[0])
    if n < 5:
        return None
    s = np.sort(v)
    k = int(n * frac)
    core = s[k : n - k] if n - 2 * k > 0 else s
    return float(np.mean(core))


def winsorized_mean(x: NDArray[Any], frac: float = 0.05) -> float | None:
    v = np.asarray(x, dtype=np.float64)
    v = v[np.isfinite(v)]
    n = int(v.shape[0])
    if n < 5:
        return None
    s = np.sort(v)
    k = max(1, int(n * frac))
    lo, hi = s[k - 1], s[n - k]
    w = np.clip(v, lo, hi)
    return float(np.mean(w))


def bootstrap_ci(
    x: NDArray[Any],
    stat: str = "mean",
    n: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, Any]:
    v = np.asarray(x, dtype=np.float64)
    v = v[np.isfinite(v)]
    if int(v.shape[0]) < 10:
        return {"status": "N/A", "reason": "fewer than 10 samples"}
    rng = np.random.default_rng(seed)
    nb = int(v.shape[0])
    draws = np.empty(n, dtype=np.float64)
    for i in range(n):
        s = v[rng.integers(0, nb, size=nb)]
        draws[i] = float(np.mean(s)) if stat == "mean" else float(np.median(s))
    return {
        "status": "OK",
        "n_resamples": n,
        "point": round(float(np.mean(v)) if stat == "mean" else float(np.median(v)), 4),
        "ci95": [
            round(float(np.percentile(draws, 2.5)), 4),
            round(float(np.percentile(draws, 97.5)), 4),
        ],
        "p_le_0": round(float(np.mean(draws <= 0.0)), 4),
    }


def z_two_sided(conf: float = 0.95) -> float:
    # 0.95 -> 1.959964 ; 0.90 -> 1.644854
    table = {0.90: 1.644854, 0.95: 1.959964, 0.99: 2.575829}
    return table.get(round(conf, 2), 1.959964)


def z_power(power: float = 0.80) -> float:
    table = {0.80: 0.841621, 0.90: 1.281552, 0.95: 1.644854}
    return table.get(round(power, 2), 0.841621)


# ---------------------------------------------------------------------------
# bundle access by split
# ---------------------------------------------------------------------------


def split_bundles(
    split: str, tf: str, assets: tuple[str, ...] = L.ASSETS
) -> list[tuple[str, str, L.Bundle]]:
    windows = L.SPLITS[split]
    out: list[tuple[str, str, L.Bundle]] = []
    for asset in assets:
        for window in windows:
            out.append((asset, window, P.B.get(asset, window, tf)))
    return out


# ---------------------------------------------------------------------------
# best-of-N null: signal-timestamp permutation preserving count + directions
# ---------------------------------------------------------------------------


def _permute_signal(sig: NDArray[Any], rng: np.random.Generator) -> NDArray[Any]:
    v = np.asarray(sig)
    n = int(v.shape[0])
    idx = np.flatnonzero(v)
    out = np.zeros(n, dtype=v.dtype)
    if idx.shape[0] == 0:
        return out
    target = rng.choice(n, size=idx.shape[0], replace=False)
    out[target] = v[idx]
    return out


def _permuted_experiment(exp: dict[str, Any], rng: np.random.Generator) -> list[L.Trade]:
    """Re-run one experiment on DISCOVERY with its signal timestamps permuted."""
    windows = L.SPLITS["DISCOVERY"]
    sig_name = exp["sig"]
    if sig_name == "lead_lag":
        trades: list[L.Trade] = []
        for tf in ("15m", "30m"):
            lag = int(exp["params"][4])
            for window in windows:
                leader = P.B.get("BTCUSDT", window, tf)
                for follower in ("ETHUSDT", "SOLUSDT"):
                    fb = P.B.get(follower, window, tf)
                    sig = _permute_signal(S.sig_lead_lag(leader, fb, lag), rng)
                    spec = L.Spec(
                        candidate_id=exp["candidate_id"],
                        hypothesis_id="H-P1-06",
                        family="lead_lag",
                        timeframe=tf,
                        signals=P._const_signal(sig),
                        warmup=P.WARM,
                        atr_target_mult=exp["params"][0],
                        atr_target_is_atr=True,
                        atr_stop_mult=exp["params"][2],
                        hold_bars=int(exp["params"][3]),
                    )
                    trades.extend(L.run_spec(spec, fb, follower, window))
        return trades
    if sig_name == "cross_sectional_rs":
        trades = []
        hold = int(exp["params"][3])
        for tf in ("1h", "2h"):
            for window in windows:
                for asset in L.ASSETS:
                    b = P.B.get(asset, window, tf)
                    base = np.zeros(len(b), dtype=np.int8)
                    base[:] = 0
                    # random half long / half short at random timestamps (count preserved later by permute of combined)
                    sig = _permute_signal(
                        np.where(np.arange(len(b)) % 2 == 0, 1, -1).astype(np.int8), rng
                    )
                    spec = L.Spec(
                        candidate_id=exp["candidate_id"],
                        hypothesis_id="H-P1-05",
                        family="cross_sectional_rs",
                        timeframe=tf,
                        signals=P._const_signal(sig),
                        warmup=P.WARM,
                        atr_target_mult=0.0,
                        atr_target_is_atr=False,
                        atr_stop_mult=0.0,
                        hold_bars=hold,
                    )
                    trades.extend(L.run_spec(spec, b, asset, window))
        return trades
    fn = P.SIG_FN[sig_name]
    tf = exp["timeframe"]
    trades = []
    for asset, window, b in split_bundles("DISCOVERY", tf, exp.get("asset_scope", L.ASSETS)):
        sig = _permute_signal(fn(b), rng)
        spec = L.Spec(
            candidate_id=exp["candidate_id"],
            hypothesis_id=exp["hypothesis_id"],
            family=exp["family"],
            timeframe=tf,
            signals=P._const_signal(sig),
            warmup=P.WARM,
            atr_target_mult=exp["params"][0],
            atr_target_is_atr=exp["params"][1],
            atr_stop_mult=exp["params"][2],
            hold_bars=int(exp["params"][3]),
        )
        trades.extend(L.run_spec(spec, b, asset, window))
    return trades


def null_draws(n_draws: int, seed: int) -> list[dict[str, Any]]:
    """One chunk of best-of-106 null draws (resumable across processes)."""
    disc = discovery()
    rng = np.random.default_rng(seed)
    out: list[dict[str, Any]] = []
    for _ in range(n_draws):
        nets: list[float] = []
        sharpes: list[float] = []
        pnls: list[float] = []
        for exp in disc:
            tr = _permuted_experiment(exp, rng)
            if len(tr) < MIN_TRADES:
                continue
            net = net_of(tr)
            nets.append(float(np.mean(net)))
            pnls.append(float(np.sum(net)) / 1e4 * L.ROOT_NOTIONAL)
            tf = str(exp["timeframe"]).split("+")[0]
            m = L.metrics(tr, 1, L.TF_MIN.get(tf, 30.0))
            s = m.get("sharpe")
            sharpes.append(float(s) if s is not None else 0.0)
        if nets:
            out.append(
                {
                    "best_net_bps": max(nets),
                    "best_sharpe": max(sharpes),
                    "best_pnl_usdt": max(pnls),
                    "n_valid": len(nets),
                }
            )
    return out


def summarise_null(draws: list[dict[str, Any]]) -> dict[str, Any]:
    if not draws:
        return {"status": "N/A", "reason": "no draws"}
    bn = np.array([d["best_net_bps"] for d in draws], dtype=np.float64)
    bs = np.array([d["best_sharpe"] for d in draws], dtype=np.float64)
    bp = np.array([d["best_pnl_usdt"] for d in draws], dtype=np.float64)
    return {
        "status": "OK",
        "n_draws": len(draws),
        "median_best_net_bps": round(float(np.median(bn)), 4),
        "mean_best_net_bps": round(float(np.mean(bn)), 4),
        "p95_best_net_bps": round(float(np.percentile(bn, 95)), 4),
        "p99_best_net_bps": round(float(np.percentile(bn, 99)), 4),
        "max_best_net_bps": round(float(np.max(bn)), 4),
        "median_best_sharpe": round(float(np.median(bs)), 4),
        "p95_best_sharpe": round(float(np.percentile(bs, 95)), 4),
        "median_best_pnl_usdt": round(float(np.median(bp)), 2),
        "median_valid_experiments": int(np.median([d["n_valid"] for d in draws])),
    }


def p_best_ge_observed(draws: list[dict[str, Any]], observed_best: float) -> dict[str, Any]:
    """Empirical P(null best-of-106 >= observed) with a Wilson 95% interval."""
    n = len(draws)
    if n == 0:
        return {"status": "N/A"}
    k = sum(1 for d in draws if float(d["best_net_bps"]) >= observed_best)
    p = k / n
    z = z_two_sided(0.95)
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = max(0.0, centre - half)
    hi = min(1.0, centre + half)
    return {
        "status": "OK",
        "n_draws": n,
        "n_ge_observed": k,
        "p_value": round(p, 4),
        "p_ci95_wilson": [round(lo, 4), round(hi, 4)],
        "mc_resolution": round(1.0 / (n + 1), 5),
        "reject_alpha_005": bool(hi < 0.05),
    }


# ---------------------------------------------------------------------------
# family-level evidence
# ---------------------------------------------------------------------------


def family_level() -> dict[str, Any]:
    disc = discovery()
    fams: dict[str, dict[str, Any]] = {}
    for r in disc:
        fams.setdefault(
            r["hypothesis_id"], {"family": r["family"], "nets": [], "grosses": [], "tools": []}
        )
        fams[r["hypothesis_id"]]["nets"].append(r["metrics"].get("net_bps"))
        fams[r["hypothesis_id"]]["grosses"].append(r["metrics"].get("gross_bps"))
    out: dict[str, Any] = {}
    for hyp, d in sorted(fams.items()):
        nets = np.array([x for x in d["nets"] if x is not None], dtype=np.float64)
        gros = np.array([x for x in d["grosses"] if x is not None], dtype=np.float64)
        out[hyp] = {
            "family": d["family"],
            "experiments": int(nets.shape[0]),
            "positive_gross": int(np.count_nonzero(gros > 0)),
            "positive_net": int(np.count_nonzero(nets > 0)),
            "median_net_bps": round(float(np.median(nets)), 4),
            "mean_net_bps": round(float(np.mean(nets)), 4),
            "p25": round(float(np.percentile(nets, 25)), 4),
            "p50": round(float(np.percentile(nets, 50)), 4),
            "p75": round(float(np.percentile(nets, 75)), 4),
            "p90": round(float(np.percentile(nets, 90)), 4),
            "best": round(float(np.max(nets)), 4),
            "worst": round(float(np.min(nets)), 4),
        }
    shifted = [h for h, v in out.items() if v["median_net_bps"] > 0]
    return {
        "status": "OK",
        "hypotheses": out,
        "families_with_positive_median": shifted,
        "n_families_positive_median": len(shifted),
    }


# ---------------------------------------------------------------------------
# multiple testing
# ---------------------------------------------------------------------------


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def multiple_testing() -> dict[str, Any]:
    disc = discovery()
    rows: list[tuple[str, float, float, int]] = []
    for r in disc:
        m = r["metrics"]
        n = int(m.get("trades", 0) or 0)
        t = m.get("t_stat")
        if n < MIN_TRADES or t is None:
            continue
        rows.append((r["experiment_id"], float(t), _norm_sf(float(t)), n))
    pvals = np.array([x[2] for x in rows], dtype=np.float64)
    order = np.argsort(pvals)
    m = int(pvals.shape[0])
    alpha = 0.10
    # Benjamini-Hochberg
    bh_pass: list[str] = []
    kmax = 0
    for k in range(1, m + 1):
        i = order[k - 1]
        if pvals[i] <= alpha * k / m:
            kmax = k
    for k in range(kmax):
        bh_pass.append(rows[order[k]][0])
    # Holm
    holm_pass: list[str] = []
    for k in range(m):
        i = order[k]
        if pvals[i] <= alpha / (m - k):
            holm_pass.append(rows[i][0])
        else:
            break
    raw_sig = [x[0] for x in rows if x[2] < 0.05]
    return {
        "status": "OK",
        "n_tested": m,
        "n_raw_p_lt_005": len(raw_sig),
        "raw_p_lt_005": raw_sig,
        "bh_fdr_q": alpha,
        "bh_pass": bh_pass,
        "n_bh_pass": len(bh_pass),
        "holm_alpha": alpha,
        "holm_pass": holm_pass,
        "n_holm_pass": len(holm_pass),
        "p_value_method": "one-sided normal approximation on the reported t-statistic",
    }


# ---------------------------------------------------------------------------
# trade concentration + outlier influence
# ---------------------------------------------------------------------------


def concentration(trades: list[L.Trade]) -> dict[str, Any]:
    net = net_of(trades)
    n = int(net.shape[0])
    if n == 0:
        return {"status": "N/A"}
    total = float(np.sum(net))
    s = np.sort(net)[::-1]

    def share(k: int) -> float | None:
        if total == 0:
            return None
        return round(float(np.sum(s[:k])) / total, 4)

    pf = None
    w = float(net[net > 0].sum())
    lo = abs(float(net[net < 0].sum()))
    pf = round(w / lo, 4) if lo > 0 else None
    ex_best = float(np.mean(s[1:])) if n > 1 else None
    ex_top3 = float(np.mean(s[3:])) if n > 3 else None
    if total > 0 and ex_best is not None and ex_best <= 0:
        verdict = "SINGLE_TRADE_DEPENDENCY"
    elif total > 0 and (share(1) or 0) >= 0.5:
        verdict = "CONCENTRATED_EDGE"
    elif total > 0:
        verdict = "DIVERSIFIED_EDGE"
    else:
        verdict = "NO_EDGE"
    return {
        "status": "OK",
        "trades": n,
        "total_net_bps": round(total, 4),
        "total_net_pnl_usdt": round(total / 1e4 * L.ROOT_NOTIONAL, 2),
        "pct_top1": share(1),
        "pct_top3": share(3),
        "pct_top5": share(5),
        "net_bps_ex_best": round(ex_best, 4) if ex_best is not None else None,
        "net_bps_ex_top3": round(ex_top3, 4) if ex_top3 is not None else None,
        "pf_with_best": pf,
        "pf_ex_best": (
            lambda: (lambda w2: round(w2 / lo, 4) if lo > 0 else None)(
                float(s[1:][s[1:] > 0].sum())
            )
        )()
        if n > 1
        else None,
        "verdict": verdict,
    }


def outlier_influence(trades: list[L.Trade]) -> dict[str, Any]:
    net = net_of(trades)
    if int(net.shape[0]) < 5:
        return {"status": "N/A"}
    mean = float(np.mean(net))
    median = float(np.median(net))
    return {
        "status": "OK",
        "trades": int(net.shape[0]),
        "mean_bps": round(mean, 4),
        "median_bps": round(median, 4),
        "trimmed_mean_10_bps": round(trimmed_mean(net, 0.10) or 0.0, 4),
        "winsorized_mean_5_bps": round(winsorized_mean(net, 0.05) or 0.0, 4),
        "tail_dependent": bool(mean > 0 and median < 0),
    }


# ---------------------------------------------------------------------------
# signal information audit + direction vs magnitude
# ---------------------------------------------------------------------------


def _forward_return(c: NDArray[Any], h: int) -> NDArray[Any]:
    n = int(c.shape[0])
    out = np.full(n, np.nan, dtype=np.float64)
    if n > h:
        out[: n - h] = c[h:] / c[: n - h] - 1.0
    return out * 1e4  # bps


def info_for_signals(
    sig_names: list[str],
    split: str,
    tf: str,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[str, Any]:
    """Pooled signal -> forward-return statistics per (signal, horizon)."""
    bundles = split_bundles(split, tf)
    result: dict[str, Any] = {}
    for name in sig_names:
        fn = P.SIG_FN[name]
        rows: dict[int, dict[str, list[float]]] = {
            h: {"sig": [], "fwd": [], "abs_sig": [], "abs_nosig": []} for h in horizons
        }
        for _asset, _window, b in bundles:
            sig = np.asarray(fn(b), dtype=np.float64)
            c = b.bars.c
            for h in horizons:
                fwd = _forward_return(c, h)
                m = np.isfinite(fwd)
                if int(m.sum()) < 20:
                    continue
                rows[h]["sig"].extend(sig[m].tolist())
                rows[h]["fwd"].extend(fwd[m].tolist())
                nz = np.abs(sig[m]) > 0
                rows[h]["abs_sig"].extend(np.abs(fwd[m][nz]).tolist())
                rows[h]["abs_nosig"].extend(np.abs(fwd[m][~nz]).tolist())
        per_h: dict[str, Any] = {}
        for h in horizons:
            sig = np.array(rows[h]["sig"], dtype=np.float64)
            fwd = np.array(rows[h]["fwd"], dtype=np.float64)
            nz = np.abs(sig) > 0
            if int(nz.sum()) < 10:
                per_h[HORIZON_LABEL[h]] = {"status": "N/A", "events": int(nz.sum())}
                continue
            sgn = np.sign(sig) * np.sign(fwd)
            hit = float(np.mean(sgn[nz] > 0))
            e_sig = float(np.mean(fwd[nz]))
            e_no = float(np.mean(fwd[~nz])) if int((~nz).sum()) > 0 else None
            abs_sig = float(np.mean(np.abs(fwd[nz])))
            abs_no = float(np.mean(np.abs(fwd[~nz]))) if int((~nz).sum()) > 0 else None
            ci = bootstrap_ci((sgn[nz] > 0).astype(np.float64))
            per_h[HORIZON_LABEL[h]] = {
                "status": "OK",
                "events": int(nz.sum()),
                "bars": int(sig.shape[0]),
                "ic_spearman": spearman_ic(sig, fwd),
                "direction_hit_rate": round(hit, 4),
                "hit_rate_ci95": ci.get("ci95"),
                "e_fwd_signal_bps": round(e_sig, 4),
                "e_fwd_nosignal_bps": round(e_no, 4) if e_no is not None else None,
                "abs_move_signal_bps": round(abs_sig, 4),
                "abs_move_nosignal_bps": round(abs_no, 4) if abs_no is not None else None,
                "abs_move_lift": round(abs_sig / abs_no, 4) if abs_no else None,
            }
        result[name] = {"timeframe": tf, "split": split, "horizons": per_h}
    return result


def classify_direction_magnitude(info: dict[str, Any]) -> str:
    """Aggregate a signal's horizons into a §15 class.

    Directional alpha requires a direction hit rate whose bootstrap CI lies above
    0.5 (a rate below 0.5 is adverse, not alpha). Magnitude alpha requires an
    absolute-move lift >= 1.20 against non-signal bars.
    """
    ok = [v for v in info["horizons"].values() if v.get("status") == "OK"]
    if not ok:
        return "UNCERTAIN"
    ci_lows = [v["hit_rate_ci95"][0] for v in ok if v.get("hit_rate_ci95")]
    lifts = [v.get("abs_move_lift") for v in ok if v.get("abs_move_lift") is not None]
    directional = bool(ci_lows and float(np.mean(ci_lows)) > 0.50)
    volatility = bool(lifts and float(np.mean(lifts)) >= 1.20)
    if directional and volatility:
        return "BOTH"
    if directional:
        return "DIRECTIONAL_ALPHA"
    if volatility:
        return "VOLATILITY_ALPHA_ONLY"
    return "NO_INFORMATION"


# ---------------------------------------------------------------------------
# MDE / sample size
# ---------------------------------------------------------------------------


def mde_table(sigma: float, ns: tuple[int, ...] = (20, 50, 100, 250, 500, 1000)) -> dict[str, Any]:
    factor = z_two_sided(0.95) + z_power(0.80)  # 80% power, 95% two-sided
    out: dict[str, Any] = {}
    for n in ns:
        out[str(n)] = round(factor * sigma / math.sqrt(n), 4)
    return out


def required_n(
    sigma: float, edges: tuple[float, ...] = (5.0, 10.0, 20.0), power: float = 0.80
) -> dict[str, Any]:
    factor = z_two_sided(0.95) + z_power(power)
    return {f"{e:g}bps": math.ceil((factor * sigma / e) ** 2) for e in edges}


# ---------------------------------------------------------------------------
# effective sample size
# ---------------------------------------------------------------------------


def effective_sample(split: str = "DISCOVERY", tf: str = "30m") -> dict[str, Any]:
    bundles = {a: P.B.get(a, L.SPLITS[split][0], tf) for a in L.ASSETS}
    ts = [{int(t) for t in b.bars.ts} for b in bundles.values()]
    common = sorted(set.intersection(*ts))
    idx = {a: {int(t): k for k, t in enumerate(b.bars.ts)} for a, b in bundles.items()}
    rets: dict[str, list[float]] = {a: [] for a in L.ASSETS}
    for t in common:
        for a, b in bundles.items():
            k = idx[a][t]
            r = float(b.ret1[k])
            rets[a].append(r if np.isfinite(r) else 0.0)
    arrs = {a: np.array(v, dtype=np.float64) for a, v in rets.items()}
    corrs: list[float] = []
    names = list(L.ASSETS)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = pearson(arrs[names[i]], arrs[names[j]])
            if c is not None:
                corrs.append(c)
    rho = float(np.mean(corrs)) if corrs else 0.0
    k = len(names)
    n_total = int(len(common) * k)
    n_eff = n_total / (1.0 + (k - 1) * max(0.0, rho))
    return {
        "status": "OK",
        "split": split,
        "timeframe": tf,
        "bars_common": len(common),
        "return_corr": {
            f"{names[i]}_{names[j]}": round(corrs[c], 4)
            for c, (i, j) in enumerate(
                [(i, j) for i in range(len(names)) for j in range(i + 1, len(names))]
            )
        },
        "rho_bar": round(rho, 4),
        "n_bars_total": n_total,
        "effective_sample_size": round(n_eff, 1),
        "independence_ratio": round(n_eff / n_total, 4),
    }


def trade_outcome_correlation(
    windows: tuple[str, ...] = L.SPLITS["DISCOVERY"], tf: str = "30m"
) -> dict[str, Any]:
    """Correlation of per-day pooled trade outcomes across assets (coarse)."""
    # Use 30m bars' returns on the common axis as a proxy for co-movement of PnL.
    return effective_sample("DISCOVERY", tf)


# ---------------------------------------------------------------------------
# distribution shift + regime
# ---------------------------------------------------------------------------


def _bar_features(tf: str, split: str) -> dict[str, Any]:
    vals: dict[str, list[float]] = {
        k: [] for k in ("ret", "absret", "atr_pct", "rv20", "volume", "trend")
    }
    for _a, _w, b in split_bundles(split, tf):
        r = b.ret1
        e50 = b.ema50
        m = np.isfinite(r)
        vals["ret"].extend(r[m].tolist())
        vals["absret"].extend(np.abs(r[m]).tolist())
        ap = b.atr_pct
        ma = np.isfinite(ap)
        vals["atr_pct"].extend(ap[ma].tolist())
        rv = b.rv20
        mr = np.isfinite(rv)
        vals["rv20"].extend(rv[mr].tolist())
        v = b.bars.v
        vals["volume"].extend(v.tolist())
        tr = np.full(e50.shape, np.nan, dtype=np.float64)
        tr[1:] = np.abs(np.diff(e50) / e50[:-1])
        mt = np.isfinite(tr)
        vals["trend"].extend(tr[mt].tolist())
    return vals


def distribution_shift(tf: str = "30m") -> dict[str, Any]:
    d = _bar_features(tf, "DISCOVERY")
    v = _bar_features(tf, "VALIDATION")
    out: dict[str, Any] = {}
    material = 0
    for key in d:
        da = np.array(d[key], dtype=np.float64)
        va = np.array(v[key], dtype=np.float64)
        dm = float(np.mean(da)) if da.shape[0] else None
        vm = float(np.mean(va)) if va.shape[0] else None
        dsd = float(np.std(da)) if da.shape[0] else 0.0
        z = (vm - dm) / dsd if (dm is not None and vm is not None and dsd > 0) else None
        if z is not None and abs(z) >= 0.20:
            material += 1
        out[key] = {
            "discovery_mean": round(dm, 6) if dm is not None else None,
            "validation_mean": round(vm, 6) if vm is not None else None,
            "std_shift_z": round(z, 4) if z is not None else None,
            "material": bool(z is not None and abs(z) >= 0.20),
        }
    verdict = (
        "NO_MATERIAL_SHIFT"
        if material == 0
        else ("COVARIATE_SHIFT" if material >= 2 else "COVARIATE_SHIFT_WEAK")
    )
    return {
        "status": "OK",
        "timeframe": tf,
        "features": out,
        "n_material": material,
        "verdict": verdict,
    }


def regime_composition(tf: str = "30m") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for split in ("DISCOVERY", "VALIDATION"):
        counts: dict[str, int] = {}
        for _a, _w, b in split_bundles(split, tf):
            labels = L.regime_labels(b)
            for code in labels:
                name = L.REGIME_NAMES.get(int(code), "UNKNOWN")
                counts[name] = counts.get(name, 0) + 1
        total = sum(counts.values()) or 1
        out[split] = {
            "bars": total,
            "composition": {k: round(v / total, 4) for k, v in sorted(counts.items())},
            "counts": dict(sorted(counts.items())),
        }
    return {"status": "OK", "timeframe": tf, "by_split": out}


# ---------------------------------------------------------------------------
# dataset adequacy
# ---------------------------------------------------------------------------


def dataset_adequacy() -> dict[str, Any]:
    tf_stats = [
        ("5m", "5m"),
        ("15m", "15m"),
        ("30m", "30m"),
        ("1h", "1h"),
        ("2h", "2h"),
    ]
    out: dict[str, Any] = {}
    for label, tf in tf_stats:
        nbars = 0
        for _a, _w, b in split_bundles("DISCOVERY", tf):
            nbars += len(b)
        out[label] = {"discovery_bars": nbars}
    return {"status": "OK", "timeframes": out}


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# winners' curse
# ---------------------------------------------------------------------------


def winners_curse(
    null_summary: dict[str, Any], observed_best: float, validation_net: float
) -> dict[str, Any]:
    med = null_summary.get("median_best_net_bps")
    return {
        "status": "OK" if med is not None else "N/A",
        "observed_discovery_best_bps": round(observed_best, 4),
        "null_median_best_bps": med,
        "expected_winner_inflation_bps": round(observed_best - med, 4) if med is not None else None,
        "validation_net_bps": round(validation_net, 4),
        "discovery_to_validation_drop_bps": round(observed_best - validation_net, 4),
        "drop_consistent_with_regression_to_mean": (
            bool(
                med is not None
                and abs((observed_best - validation_net) - (observed_best - med)) <= 12.0
            )
            if med is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# null baselines for one candidate (§17)
# ---------------------------------------------------------------------------


def _spec_net(
    basename: str,
    hyp: str,
    family: str,
    tf: str,
    sig_by_key: dict[str, NDArray[Any]],
    params: tuple[Any, ...],
) -> list[L.Trade]:
    trades: list[L.Trade] = []
    for asset, window, b in split_bundles("DISCOVERY", tf):
        sig = sig_by_key.get(f"{asset}|{window}")
        if sig is None:
            continue
        spec = L.Spec(
            candidate_id=basename,
            hypothesis_id=hyp,
            family=family,
            timeframe=tf,
            signals=P._const_signal(sig),
            warmup=P.WARM,
            atr_target_mult=params[0],
            atr_target_is_atr=bool(params[1]),
            atr_stop_mult=params[2],
            hold_bars=int(params[3]),
        )
        trades.extend(L.run_spec(spec, b, asset, window))
    return trades


def null_baselines(
    tf: str = "30m",
    params: tuple[Any, ...] = (4.0, True, 2.0, 32),
    resamples: int = 200,
    seed: int = SEED,
) -> dict[str, Any]:
    fn = P.SIG_FN["squeeze_magnitude"]
    real_sig: dict[str, NDArray[Any]] = {}
    for asset, window, b in split_bundles("DISCOVERY", tf):
        real_sig[f"{asset}|{window}"] = fn(b)
    real = _spec_net("REAL", "H-P0-02", "squeeze_magnitude", tf, real_sig, params)
    always_long = {k: np.ones_like(v) for k, v in real_sig.items()}
    al = _spec_net("ALWAYS_LONG", "H-P0-02", "squeeze_magnitude", tf, always_long, params)
    rng = np.random.default_rng(seed)
    rand_dir_nets: list[float] = []
    rand_ts_nets: list[float] = []
    for _ in range(resamples):
        sd: dict[str, NDArray[Any]] = {}
        st: dict[str, NDArray[Any]] = {}
        for k, v in real_sig.items():
            nz = np.flatnonzero(v)
            d = np.zeros_like(v)
            if nz.shape[0]:
                d[nz] = rng.choice(np.array([-1, 1]), size=nz.shape[0])
            sd[k] = d
            r = rng.permutation(v.shape[0])[: nz.shape[0]]
            rr = np.zeros_like(v)
            rr[r] = rng.choice(np.array([-1, 1]), size=nz.shape[0]) if nz.shape[0] else 0
            st[k] = rr
        rd = net_of(_spec_net("RD", "H-P0-02", "squeeze_magnitude", tf, sd, params))
        rt = net_of(_spec_net("RT", "H-P0-02", "squeeze_magnitude", tf, st, params))
        rand_dir_nets.append(float(np.mean(rd)) if rd.shape[0] else float("nan"))
        rand_ts_nets.append(float(np.mean(rt)) if rt.shape[0] else float("nan"))
    return {
        "status": "OK",
        "timeframe": tf,
        "real_net_bps": round(float(np.mean(net_of(real))), 4) if real else None,
        "real_trades": len(real),
        "always_long_net_bps": round(float(np.mean(net_of(al))), 4) if al else None,
        "always_long_trades": len(al),
        "random_direction_same_ts": {
            "median_net_bps": round(float(np.nanmedian(rand_dir_nets)), 4),
            "p95_net_bps": round(float(np.nanpercentile(rand_dir_nets, 95)), 4),
            "p99_net_bps": round(float(np.nanpercentile(rand_dir_nets, 99)), 4),
            "p_real_exceeds_p95": bool(
                real and float(np.mean(net_of(real))) > float(np.nanpercentile(rand_dir_nets, 95))
            ),
        },
        "random_timestamp_same_count": {
            "median_net_bps": round(float(np.nanmedian(rand_ts_nets)), 4),
            "p95_net_bps": round(float(np.nanpercentile(rand_ts_nets, 95)), 4),
            "p99_net_bps": round(float(np.nanpercentile(rand_ts_nets, 99)), 4),
            "p_real_exceeds_p95": bool(
                real and float(np.mean(net_of(real))) > float(np.nanpercentile(rand_ts_nets, 95))
            ),
        },
        "n_resamples": resamples,
    }


# ---------------------------------------------------------------------------
# event study (§18)
# ---------------------------------------------------------------------------


def hyp_tf_map() -> dict[str, tuple[str, ...]]:
    return {sd["sig"]: tuple(sd["tfs"]) for sd in P.SINGLE_ASSET_SPECS}


def event_study(split: str = "DISCOVERY", horizons: tuple[int, ...] = HORIZONS) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sig_name, tfs in hyp_tf_map().items():
        tf = tfs[0]
        fn = P.SIG_FN[sig_name]
        per_h: dict[int, dict[str, list[float]]] = {
            h: {"ret": [], "mfe": [], "mae": []} for h in horizons
        }
        for _a, _w, b in split_bundles(split, tf):
            sig = np.asarray(fn(b))
            c, hh, lo, op = b.bars.c, b.bars.h, b.bars.lo, b.bars.o
            n = int(c.shape[0])
            for i in np.flatnonzero(sig):
                ei = i + 1
                for h in horizons:
                    if ei + h >= n:
                        continue
                    sgn = 1.0 if sig[i] > 0 else -1.0
                    entry = float(op[ei])
                    if entry <= 0:
                        continue
                    ret = sgn * (float(c[ei + h]) / entry - 1.0) * 1e4
                    window_hi = float(np.max(hh[ei : ei + h + 1]))
                    window_lo = float(np.min(lo[ei : ei + h + 1]))
                    mfe = (
                        (window_hi / entry - 1.0) * 1e4
                        if sgn > 0
                        else (entry / window_lo - 1.0) * 1e4
                    )
                    mae = (
                        (entry / window_lo - 1.0) * 1e4
                        if sgn > 0
                        else (window_hi / entry - 1.0) * 1e4
                    )
                    per_h[h]["ret"].append(ret)
                    per_h[h]["mfe"].append(mfe)
                    per_h[h]["mae"].append(mae)
        rows: dict[str, Any] = {}
        for h in horizons:
            r = np.array(per_h[h]["ret"], dtype=np.float64)
            if r.shape[0] < 10:
                rows[HORIZON_LABEL[h]] = {"status": "N/A", "events": int(r.shape[0])}
                continue
            ci = bootstrap_ci(r)
            rows[HORIZON_LABEL[h]] = {
                "status": "OK",
                "events": int(r.shape[0]),
                "mean_fwd_ret_bps": round(float(np.mean(r)), 4),
                "median_fwd_ret_bps": round(float(np.median(r)), 4),
                "positive_rate": round(float(np.count_nonzero(r > 0)) / r.shape[0], 4),
                "mean_mfe_bps": round(float(np.mean(per_h[h]["mfe"])), 4),
                "mean_mae_bps": round(float(np.mean(per_h[h]["mae"])), 4),
                "ci95_mean_ret": ci.get("ci95"),
            }
        out[sig_name] = {"timeframe": tf, "split": split, "horizons": rows}
    return {"status": "OK", "signals": out}


# ---------------------------------------------------------------------------
# sample size / MDE from empirical variance (§23/§24)
# ---------------------------------------------------------------------------


def sample_size_analysis(tf: str = "30m") -> dict[str, Any]:
    # Empirical per-trade variance of the two frozen winners (DISCOVERY+VALIDATION).
    winners = [r for r in discovery() if r["experiment_id"] in ("EXP-S002-0023", "EXP-S002-0022")]
    pool: list[float] = []
    per_cand: dict[str, Any] = {}
    for w in winners:
        tr = list(w["trades"])
        tr.extend(P.rerun(w, L.SPLITS["VALIDATION"])[0])
        net = net_of(tr)
        pool.extend(net.tolist())
        per_cand[w["experiment_id"]] = {
            "trades": int(net.shape[0]),
            "mean_bps": round(float(np.mean(net)), 4),
            "std_bps": round(float(np.std(net, ddof=1)), 4),
        }
    sigma = float(np.std(np.array(pool, dtype=np.float64), ddof=1)) if len(pool) >= 2 else 0.0
    return {
        "status": "OK",
        "per_candidate": per_cand,
        "pooled_trades": len(pool),
        "pooled_std_bps": round(sigma, 4),
        "mde_bps_by_n": mde_table(sigma),
        "required_n_for_edge": required_n(sigma),
        "assumptions": "two-sided 95% confidence, 80% power, z-approximation, i.i.d. trades",
    }


# ---------------------------------------------------------------------------
# dataset adequacy (§32)
# ---------------------------------------------------------------------------


def dataset_adequacy_detailed() -> dict[str, Any]:
    disc = discovery()
    out: dict[str, Any] = {}
    for tf in ("15m", "30m", "1h", "2h"):
        bars = 0
        for _a, _w, b in split_bundles("DISCOVERY", tf):
            bars += len(b)
        exps = [r for r in disc if r["timeframe"] == tf or r["timeframe"].startswith(tf + "+")]
        nets: list[float] = []
        for e in exps:
            nets.extend(net_of(e["trades"]).tolist())
        arr = np.array(nets, dtype=np.float64)
        sigma = float(np.std(arr, ddof=1)) if arr.shape[0] >= 2 else 0.0
        mde100 = (z_two_sided(0.95) + z_power(0.80)) * sigma / math.sqrt(100) if sigma else None
        if mde100 is None:
            cls = "UNDERPOWERED"
        elif mde100 <= 15.0:
            cls = "ADEQUATE"
        elif mde100 <= 35.0:
            cls = "MARGINALLY_ADEQUATE"
        else:
            cls = "UNDERPOWERED"
        out[tf] = {
            "discovery_bars": bars,
            "experiments": len(exps),
            "pooled_trades": int(arr.shape[0]),
            "pooled_std_bps": round(sigma, 4),
            "mde_100_trades_bps": round(mde100, 4) if mde100 is not None else None,
            "classification": cls,
        }
    return {"status": "OK", "timeframes": out}


def write_json(path: Path, payload: Any) -> None:
    L.write_json(path, payload)
