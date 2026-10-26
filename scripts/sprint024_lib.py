"""RFC-024 — directional signal discovery on reproducible volatility events.

Read-only research over the certified dataset (W1-W4 DISCOVERY, W5 VALIDATION).
It NEVER loads W6-W7 (the holdout) and never modifies the frozen Sprint 002
signal/event engine, which it imports.

Design rules (RFC-024 §4/§5/§51):
    * a SMALL pre-registered hypothesis set (6), one mechanism each;
    * NO parameter / timeframe / indicator grid — the exit configuration is a
      single frozen constant shared by every hypothesis, so it cannot act as a
      per-hypothesis tuning lever;
    * the directional question is the only thing that varies;
    * multiple-testing control (raw p, BH-FDR, Holm) over the registered family;
    * a best-of-N null with N = exact hypothesis count (6), >=1000 draws;
    * power / effective-sample analysis so an underpowered null is reported as
      INCONCLUSIVE, never as NO_SIGNAL.
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
import sprint023_lib as G  # noqa: E402
import sprint024_signals as D  # noqa: E402

OUT = REPO / "reports" / "directional"
SEED = 20261024
N_NULL_TARGET = 1000
COST = L.CERTIFIED_ROUND_TRIP_BPS
MIN_TRADES = L.MIN_TRADES
HORIZONS = (1, 2, 4, 8)
HORIZON_LABEL = {1: "30m", 2: "1h", 4: "2h", 8: "4h"}

# Frozen, shared exit configuration. NOT swept, NOT per-hypothesis (§4).
EXIT: dict[str, Any] = {
    "target_mult": 2.0,
    "target_is_atr": True,
    "stop_mult": 1.5,
    "hold_bars": 16,
}

# Minimum economically meaningful edge for the power gate (RFC-024 §24).
MIN_ECONOMIC_EDGE_BPS = 10.0
# Assumed cross-asset independence ratio (RFC-023 measured ~0.356 at 30m).
INDEPENDENCE_RATIO = 0.356


# ---------------------------------------------------------------------------
# frozen hypothesis registry (§5/§11) — one mechanism per entry
# ---------------------------------------------------------------------------

REGISTRY: list[dict[str, Any]] = [
    {
        "hypothesis_id": "H-DIR-01",
        "family": "pre_event_trend",
        "signal": "shock_trend_continuation",
        "kind": "single",
        "timeframe": "30m",
        "conditioning_event": "vol_shock (RFC-023 reproducible magnitude event)",
        "mechanism": (
            "A volatility shock that agrees with the prevailing EMA trend is informed "
            "positioning rather than a liquidity sweep, so the next leg continues."
        ),
        "directional_prediction": "sign of the shock bar (continuation), gated on trend agreement",
        "features": ["vol_shock", "ret1", "ema9", "ema21"],
        "entry_timing": "OPEN of the bar after the shock bar",
        "exit_horizon": EXIT,
        "invalidation": "ATR stop, or time stop at the frozen hold",
        "economic_rationale": (
            "Trend-filtered shocks trade only with the flow; the shock itself is a move "
            "large enough to clear cost."
        ),
        "expected_failure_mode": "shock is noise and trend filter is late",
    },
    {
        "hypothesis_id": "H-DIR-02",
        "family": "pre_event_trend",
        "signal": "shock_trend_reversion",
        "kind": "single",
        "timeframe": "30m",
        "conditioning_event": "vol_shock (RFC-023 reproducible magnitude event)",
        "mechanism": (
            "A counter-trend shock inside an established trend is a liquidity grab; the "
            "trend resumes, so the trade goes WITH the trend, opposite to the shock bar."
        ),
        "directional_prediction": "opposite to the shock bar, aligned with the EMA trend (reversion)",
        "features": ["vol_shock", "ret1", "ema9", "ema21"],
        "entry_timing": "OPEN of the bar after the shock bar",
        "exit_horizon": EXIT,
        "invalidation": "ATR stop, or time stop at the frozen hold",
        "economic_rationale": (
            "Buying the dip (or selling the spike) in a trend improves the entry price "
            "while the trend runway is unchanged."
        ),
        "expected_failure_mode": "the counter-shock is a genuine reversal, not a grab",
    },
    {
        "hypothesis_id": "H-DIR-03",
        "family": "post_shock_response",
        "signal": "shock_confirm_followthrough",
        "kind": "single",
        "timeframe": "30m",
        "conditioning_event": "vol_shock + a confirming follow-through bar",
        "mechanism": (
            "A confirming bar that closes beyond the shock close filters absorbed, "
            "one-bar shocks; the trade joins the genuine continuation after confirmation."
        ),
        "directional_prediction": "sign of the shock, only when the next bar confirms it",
        "features": ["vol_shock", "ret1", "close"],
        "entry_timing": "OPEN of the bar after the confirming bar (i+2 from the shock)",
        "exit_horizon": EXIT,
        "invalidation": "ATR stop, or time stop at the frozen hold",
        "economic_rationale": (
            "Confirmation trades the response rather than the event, sacrificing some "
            "excursion to filter false shocks."
        ),
        "expected_failure_mode": "confirmation arrives too late and the move is already gone",
    },
    {
        "hypothesis_id": "H-DIR-04",
        "family": "market_relative_strength",
        "signal": "shock_xsec_relative_strength",
        "kind": "xsec",
        "timeframe": "1h",
        "conditioning_event": "vol_shock on the strongest / weakest major",
        "mechanism": (
            "Relative-strength persistence survives shocks: the strongest major keeps "
            "leading and the weakest keeps lagging through the event."
        ),
        "directional_prediction": "LONG the strongest, SHORT the weakest, at its own shock",
        "features": ["ret[20] cross-sectional rank", "vol_shock"],
        "entry_timing": "OPEN of the bar after the shock bar",
        "exit_horizon": EXIT,
        "invalidation": "ATR stop, or time stop at the frozen hold",
        "economic_rationale": (
            "The strongest-minus-weakest spread is less beta-driven than a single-asset "
            "position; each leg pays one full round trip."
        ),
        "expected_failure_mode": "shock is common to all three assets so the rank is uninformative",
    },
    {
        "hypothesis_id": "H-DIR-05",
        "family": "vol_liquidity_response",
        "signal": "shock_volume_continuation",
        "kind": "single",
        "timeframe": "1h",
        "conditioning_event": "vol_shock + abnormal volume percentile",
        "mechanism": (
            "A shock that also prints an unusually high volume percentile is real "
            "participation, not a thin-book print, so it continues."
        ),
        "directional_prediction": "sign of the shock bar, gated on a high volume rank",
        "features": ["vol_shock", "ret1", "vol_rank[120]"],
        "entry_timing": "OPEN of the bar after the shock bar",
        "exit_horizon": EXIT,
        "invalidation": "ATR stop, or time stop at the frozen hold",
        "economic_rationale": (
            "Participation is a different information set from price geometry and should "
            "raise the continuation hit rate."
        ),
        "expected_failure_mode": "exchange volume is noisy and correlated with the shock event",
    },
    {
        "hypothesis_id": "H-DIR-06",
        "family": "vol_range_location",
        "signal": "shock_range_location",
        "kind": "single",
        "timeframe": "30m",
        "conditioning_event": "vol_shock at an extreme of the trailing range",
        "mechanism": (
            "A shock arriving in the top/bottom quartile of the trailing range resolves "
            "range-bound liquidity and continues toward the extreme."
        ),
        "directional_prediction": "toward the range extreme the shock lands on",
        "features": ["vol_shock", "close", "hh[60]", "ll[60]"],
        "entry_timing": "OPEN of the bar after the shock bar",
        "exit_horizon": EXIT,
        "invalidation": "ATR stop, or time stop at the frozen hold",
        "economic_rationale": (
            "Range-extreme shocks are exactly the events that can break into new "
            "territory, which is where directional runway exists."
        ),
        "expected_failure_mode": "range location is a proxy for the shock direction itself",
    },
]

REGISTRY_HASH = L.sha256_obj(
    [
        {k: v for k, v in h.items() if k != "exit_horizon"} | {"exit_horizon": h["exit_horizon"]}
        for h in REGISTRY
    ]
)

_EXIT_OVERRIDE_KEYS = ("target_mult", "target_is_atr", "stop_mult", "hold_bars")


def hyp_exit(h: dict[str, Any]) -> dict[str, Any]:
    ex = h["exit_horizon"]
    return {k: ex[k] for k in _EXIT_OVERRIDE_KEYS}


# ---------------------------------------------------------------------------
# runners (§39 experiment record)
# ---------------------------------------------------------------------------


def _const_signal(sig: NDArray[Any]) -> L.SignalFn:
    def fn(_b: L.Bundle) -> NDArray[Any]:
        return sig

    return fn


def run_hypothesis(
    h: dict[str, Any],
    split: str,
    cost_bps: float = COST,
    slip_mult: float = 1.0,
) -> tuple[list[L.Trade], int]:
    """Run one frozen hypothesis over one split (W6-W7 never reachable here)."""
    if split == "HOLDOUT":  # refuse by construction (§44)
        raise ValueError("RFC-024 must never read the holdout")
    tf = h["timeframe"]
    ex = hyp_exit(h)
    windows = L.SPLITS[split]
    trades: list[L.Trade] = []
    eval_bars = 0
    if h["kind"] == "xsec":
        for window in windows:
            bundles = {a: P.B.get(a, window, tf) for a in L.ASSETS}
            sigs = D.xsec_shock_signal(bundles)
            for asset, b in bundles.items():
                spec = L.Spec(
                    candidate_id=f"{h['signal']}@{tf}",
                    hypothesis_id=h["hypothesis_id"],
                    family=h["family"],
                    timeframe=tf,
                    signals=_const_signal(sigs[asset]),
                    warmup=P.WARM,
                    atr_target_mult=float(ex["target_mult"]),
                    atr_target_is_atr=bool(ex["target_is_atr"]),
                    atr_stop_mult=float(ex["stop_mult"]),
                    hold_bars=int(ex["hold_bars"]),
                )
                trades.extend(
                    L.run_spec(spec, b, asset, window, cost_bps=cost_bps, slip_mult=slip_mult)
                )
                eval_bars += max(0, len(b) - P.WARM)
        return trades, eval_bars
    fn = D.SIG_FN[h["signal"]]
    for asset, window, b in G.split_bundles(split, tf):
        spec = L.Spec(
            candidate_id=f"{h['signal']}@{tf}",
            hypothesis_id=h["hypothesis_id"],
            family=h["family"],
            timeframe=tf,
            signals=_const_signal(fn(b)),
            warmup=P.WARM,
            atr_target_mult=float(ex["target_mult"]),
            atr_target_is_atr=bool(ex["target_is_atr"]),
            atr_stop_mult=float(ex["stop_mult"]),
            hold_bars=int(ex["hold_bars"]),
        )
        trades.extend(L.run_spec(spec, b, asset, window, cost_bps=cost_bps, slip_mult=slip_mult))
        eval_bars += max(0, len(b) - P.WARM)
    return trades, eval_bars


def metrics(h: dict[str, Any], trades: list[L.Trade], eval_bars: int) -> dict[str, Any]:
    tf = str(h["timeframe"]).split("+")[0]
    return L.metrics(trades, eval_bars, L.TF_MIN.get(tf, 30.0))


# ---------------------------------------------------------------------------
# signal arrays + funnel
# ---------------------------------------------------------------------------


def signal_maps(h: dict[str, Any], split: str) -> list[tuple[str, str, NDArray[Any], L.Bundle]]:
    """(asset, window, signal array, bundle) for every series of the split."""
    tf = h["timeframe"]
    out: list[tuple[str, str, NDArray[Any], L.Bundle]] = []
    if h["kind"] == "xsec":
        for window in L.SPLITS[split]:
            bundles = {a: P.B.get(a, window, tf) for a in L.ASSETS}
            sigs = D.xsec_shock_signal(bundles)
            for asset, b in bundles.items():
                out.append((asset, window, np.asarray(sigs[asset]), b))
        return out
    fn = D.SIG_FN[h["signal"]]
    for asset, window, b in G.split_bundles(split, tf):
        out.append((asset, window, np.asarray(fn(b)), b))
    return out


def signal_funnel(h: dict[str, Any], split: str) -> dict[str, Any]:
    tf = h["timeframe"]
    observations = 0
    vol_events = 0
    for _a, _w, b in G.split_bundles(split, tf):
        observations += len(b)
        vol_events += int(np.count_nonzero(D.shock_event(b)))
    mines = signal_maps(h, split)
    context_signals = int(sum(int(np.count_nonzero(s)) for _a, _w, s, _b in mines))
    trades, _eb = run_hypothesis(h, split)
    net = G.net_of(trades)
    gross = G.gross_of(trades)
    cost_viable = int(np.count_nonzero(gross > COST))
    return {
        "observations": observations,
        "volatility_events": vol_events,
        "context_signals": context_signals,
        "trades": len(trades),
        "context_conversion": round(context_signals / vol_events, 4) if vol_events else None,
        "trade_conversion": round(len(trades) / context_signals, 4) if context_signals else None,
        "cost_viable_trades": cost_viable,
        "mean_gross_bps": round(float(np.mean(gross)), 4) if gross.shape[0] else None,
        "mean_net_bps": round(float(np.mean(net)), 4) if net.shape[0] else None,
    }


# ---------------------------------------------------------------------------
# directional information audit (§19/§20)
# ---------------------------------------------------------------------------


def _forward_from_entry(b: L.Bundle, h_bars: int) -> NDArray[Any]:
    """Forward return in bps from OPEN[i+1] to CLOSE[i+h_bars], aligned at i."""
    n = len(b)
    op = b.bars.o
    c = b.bars.c
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        ei = i + 1
        xi = i + h_bars
        if ei >= n or xi >= n or op[ei] <= 0:
            continue
        out[i] = (float(c[xi]) / float(op[ei]) - 1.0) * 1e4
    return out


def directional_info(
    h: dict[str, Any], split: str, horizons: tuple[int, ...] = HORIZONS
) -> dict[str, Any]:
    rows: dict[int, dict[str, list[float]]] = {
        hz: {"sig": [], "ret": [], "signed": []} for hz in horizons
    }
    for _a, _w, sig, b in signal_maps(h, split):
        for hz in horizons:
            fwd = _forward_from_entry(b, hz)
            m = np.isfinite(fwd)
            rows[hz]["sig"].extend(sig[m].astype(np.float64).tolist())
            rows[hz]["ret"].extend(fwd[m].tolist())
    per_hz: dict[str, Any] = {}
    for hz in horizons:
        sig = np.array(rows[hz]["sig"], dtype=np.float64)
        ret = np.array(rows[hz]["ret"], dtype=np.float64)
        ev = np.abs(sig) > 0
        if int(ev.sum()) < 10:
            per_hz[HORIZON_LABEL[hz]] = {"status": "N/A", "events": int(ev.sum())}
            continue
        signed = np.sign(sig[ev]) * ret[ev]
        hit = float(np.mean(np.sign(sig[ev]) * np.sign(ret[ev]) > 0))
        ci = G.bootstrap_ci(signed)
        per_hz[HORIZON_LABEL[hz]] = {
            "status": "OK",
            "events": int(ev.sum()),
            "ic_spearman": G.spearman_ic(sig, ret),
            "mean_signed_bps": round(float(np.mean(signed)), 4),
            "median_signed_bps": round(float(np.median(signed)), 4),
            "direction_hit_rate": round(hit, 4),
            "hit_rate_ci95": ci.get("ci95"),
            "mean_signed_ci95": ci.get("ci95"),
            "p_signed_le_0": ci.get("p_le_0"),
        }
    return {"hypothesis_id": h["hypothesis_id"], "split": split, "horizons": per_hz}


def magnitude_info(split: str, tf: str = "30m", hz: int = 2) -> dict[str, Any]:
    """Absolute-move lift of the conditioning shock event vs non-shock bars.

    Reconfirms (independently of RFC-023) that the shock carries *volatility*
    information even though it carries no *direction* information.
    """
    shock_abs: list[float] = []
    base_abs: list[float] = []
    events = 0
    for _a, _w, b in G.split_bundles(split, tf):
        shock = D.shock_event(b)
        fwd = _forward_from_entry(b, hz)
        m = np.isfinite(fwd)
        shock_abs.extend(np.abs(fwd[m & shock]).tolist())
        base_abs.extend(np.abs(fwd[m & ~shock]).tolist())
        events += int(np.count_nonzero(shock & m))
    sa = np.array(shock_abs, dtype=np.float64)
    ba = np.array(base_abs, dtype=np.float64)
    ms = float(np.mean(sa)) if sa.shape[0] else 0.0
    mb = float(np.mean(ba)) if ba.shape[0] else 0.0
    return {
        "status": "OK",
        "split": split,
        "timeframe": tf,
        "horizon": HORIZON_LABEL.get(hz, str(hz)),
        "events": events,
        "abs_move_shock_bps": round(ms, 4),
        "abs_move_nonshock_bps": round(mb, 4),
        "abs_move_lift": round(ms / mb, 4) if mb > 0 else None,
        "volatility_information": bool(mb > 0 and ms / mb >= 1.20),
    }


def directional_class(info: dict[str, Any]) -> str:
    ok = [v for v in info["horizons"].values() if v.get("status") == "OK"]
    if not ok:
        return "UNCERTAIN"
    ci_lows = [v["mean_signed_ci95"][0] for v in ok if v.get("mean_signed_ci95")]
    directional = bool(ci_lows and float(np.mean(ci_lows)) > 0.0)
    if directional:
        return "DIRECTIONAL_ALPHA"
    return "NO_DIRECTIONAL_INFORMATION"


# ---------------------------------------------------------------------------
# multiple testing over the registered family (§16)
# ---------------------------------------------------------------------------


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def multiple_testing(rows: list[tuple[str, float, int]]) -> dict[str, Any]:
    """rows = [(hypothesis_id, t_stat, n)] -> raw p, BH-FDR and Holm at alpha=0.10."""
    clean = [(h, float(t), int(n)) for h, t, n in rows if n >= MIN_TRADES and math.isfinite(t)]
    pvals = np.array([_norm_sf(x[1]) for x in clean], dtype=np.float64)
    order = np.argsort(pvals)
    m = int(pvals.shape[0])
    alpha = 0.10
    bh_pass: list[str] = []
    kmax = 0
    for k in range(1, m + 1):
        idx = order[k - 1]
        if pvals[idx] <= alpha * k / m:
            kmax = k
    for k in range(kmax):
        bh_pass.append(clean[order[k]][0])
    holm_pass: list[str] = []
    for k in range(m):
        idx = order[k]
        if pvals[idx] <= alpha / (m - k):
            holm_pass.append(clean[idx][0])
        else:
            break
    raw_sig = [x[0] for x in clean if _norm_sf(x[1]) < 0.05]
    return {
        "status": "OK",
        "n_tested": m,
        "alpha": alpha,
        "p_value_method": "one-sided normal approximation on the net/expectancy t-statistic",
        "raw_p": {h: round(_norm_sf(t), 6) for h, t, _n in clean},
        "n_raw_p_lt_005": len(raw_sig),
        "raw_p_lt_005": raw_sig,
        "bh_fdr_q": alpha,
        "bh_pass": bh_pass,
        "n_bh_pass": len(bh_pass),
        "holm_alpha": alpha,
        "holm_pass": holm_pass,
        "n_holm_pass": len(holm_pass),
    }


# ---------------------------------------------------------------------------
# best-of-N null (N = exact hypothesis count, §31/§32)
# ---------------------------------------------------------------------------


def _permute_sig(sig: NDArray[Any], rng: np.random.Generator) -> NDArray[Any]:
    v = np.asarray(sig)
    n = int(v.shape[0])
    idx = np.flatnonzero(v)
    out = np.zeros(n, dtype=v.dtype)
    if idx.shape[0] == 0:
        return out
    target = rng.choice(n, size=idx.shape[0], replace=False)
    out[target] = v[idx]
    return out


def _permuted_trades(h: dict[str, Any], rng: np.random.Generator) -> list[L.Trade]:
    tf = h["timeframe"]
    ex = hyp_exit(h)
    trades: list[L.Trade] = []
    if h["kind"] == "xsec":
        for window in L.SPLITS["DISCOVERY"]:
            bundles = {a: P.B.get(a, window, tf) for a in L.ASSETS}
            sigs = D.xsec_shock_signal(bundles)
            for asset, b in bundles.items():
                spec = L.Spec(
                    candidate_id=f"{h['signal']}@{tf}",
                    hypothesis_id=h["hypothesis_id"],
                    family=h["family"],
                    timeframe=tf,
                    signals=_const_signal(_permute_sig(sigs[asset], rng)),
                    warmup=P.WARM,
                    atr_target_mult=float(ex["target_mult"]),
                    atr_target_is_atr=bool(ex["target_is_atr"]),
                    atr_stop_mult=float(ex["stop_mult"]),
                    hold_bars=int(ex["hold_bars"]),
                )
                trades.extend(L.run_spec(spec, b, asset, window))
        return trades
    fn = D.SIG_FN[h["signal"]]
    for asset, window, b in G.split_bundles("DISCOVERY", tf):
        spec = L.Spec(
            candidate_id=f"{h['signal']}@{tf}",
            hypothesis_id=h["hypothesis_id"],
            family=h["family"],
            timeframe=tf,
            signals=_const_signal(_permute_sig(fn(b), rng)),
            warmup=P.WARM,
            atr_target_mult=float(ex["target_mult"]),
            atr_target_is_atr=bool(ex["target_is_atr"]),
            atr_stop_mult=float(ex["stop_mult"]),
            hold_bars=int(ex["hold_bars"]),
        )
        trades.extend(L.run_spec(spec, b, asset, window))
    return trades


def null_draws(n_draws: int, seed: int) -> list[dict[str, Any]]:
    """One chunk of best-of-N null draws (N = hypothesis count). Resumable."""
    rng = np.random.default_rng(seed)
    out: list[dict[str, Any]] = []
    for _ in range(n_draws):
        nets: list[float] = []
        best_hyp = -1
        best_val = float("-inf")
        for j, h in enumerate(REGISTRY):
            tr = _permuted_trades(h, rng)
            if len(tr) < MIN_TRADES:
                continue
            net = G.net_of(tr)
            m = float(np.mean(net))
            nets.append(m)
            if m > best_val:
                best_val = m
                best_hyp = j
        if nets:
            out.append(
                {
                    "best_net_bps": best_val,
                    "best_hypothesis_index": best_hyp,
                    "best_hypothesis_id": REGISTRY[best_hyp]["hypothesis_id"]
                    if best_hyp >= 0
                    else None,
                    "n_valid": len(nets),
                }
            )
    return out


def summarise_null(draws: list[dict[str, Any]]) -> dict[str, Any]:
    if not draws:
        return {"status": "N/A", "reason": "no draws"}
    bn = np.array([d["best_net_bps"] for d in draws], dtype=np.float64)
    return {
        "status": "OK",
        "n_draws": len(draws),
        "n_hypotheses": len(REGISTRY),
        "median_best_net_bps": round(float(np.median(bn)), 4),
        "mean_best_net_bps": round(float(np.mean(bn)), 4),
        "p95_best_net_bps": round(float(np.percentile(bn, 95)), 4),
        "p99_best_net_bps": round(float(np.percentile(bn, 99)), 4),
        "max_best_net_bps": round(float(np.max(bn)), 4),
        "min_best_net_bps": round(float(np.min(bn)), 4),
    }


def p_best_ge_observed(draws: list[dict[str, Any]], observed_best: float) -> dict[str, Any]:
    n = len(draws)
    if n == 0:
        return {"status": "N/A"}
    k = sum(1 for d in draws if float(d["best_net_bps"]) >= observed_best)
    p = k / n
    z = G.z_two_sided(0.95)
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {
        "status": "OK",
        "n_draws": n,
        "n_ge_observed": k,
        "p_value": round(p, 4),
        "p_ci95_wilson": [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)],
        "mc_resolution": round(1.0 / (n + 1), 5),
        "reject_alpha_005": bool(min(1.0, centre + half) < 0.05),
    }


# ---------------------------------------------------------------------------
# power / sample size (§21-§24)
# ---------------------------------------------------------------------------


def mde(sigma: float, n: int) -> float:
    factor = G.z_two_sided(0.95) + G.z_power(0.80)
    return factor * sigma / math.sqrt(max(1, n))


def power_row(
    h: dict[str, Any], disc_trades: list[L.Trade], val_trades: list[L.Trade]
) -> dict[str, Any]:
    dn = G.net_of(disc_trades)
    vn = G.net_of(val_trades)
    sigma_d = float(np.std(dn, ddof=1)) if dn.shape[0] >= 2 else 0.0
    sigma_v = float(np.std(vn, ddof=1)) if vn.shape[0] >= 2 else 0.0
    n_val = int(vn.shape[0])
    # clamp floating-point residual variance (~1e-15) on degenerate series to 0
    eps = 1e-9
    sigma_v = 0.0 if sigma_v < eps else sigma_v
    sigma_d = 0.0 if sigma_d < eps else sigma_d
    sigma = sigma_v if sigma_v > 0.0 else sigma_d
    m = mde(sigma, n_val) if sigma > 0.0 and n_val > 0 else None
    eff_n = n_val * INDEPENDENCE_RATIO
    mde_eff = mde(sigma, round(eff_n)) if sigma > 0.0 and eff_n >= 1 else None
    testable = bool(m is not None and m <= MIN_ECONOMIC_EDGE_BPS)
    return {
        "hypothesis_id": h["hypothesis_id"],
        "discovery_trades": int(dn.shape[0]),
        "discovery_std_bps": round(sigma_d, 4),
        "validation_trades": n_val,
        "validation_std_bps": round(sigma_v, 4),
        "effective_validation_n": round(eff_n, 2),
        "mde_validation_bps": round(m, 4) if m is not None else None,
        "mde_effective_n_bps": round(mde_eff, 4) if mde_eff is not None else None,
        "min_economic_edge_bps": MIN_ECONOMIC_EDGE_BPS,
        "verdict": "TESTABLE" if testable else "UNDERPOWERED",
    }


# ---------------------------------------------------------------------------
# full evaluation (memoised)
# ---------------------------------------------------------------------------

_EVAL: dict[str, Any] | None = None


def evaluate() -> dict[str, Any]:
    global _EVAL
    if _EVAL is not None:
        return _EVAL
    result: dict[str, Any] = {"hypotheses": {}}
    mt_rows: list[tuple[str, float, int]] = []
    for h in REGISTRY:
        hid = h["hypothesis_id"]
        disc, dbars = run_hypothesis(h, "DISCOVERY")
        val, vbars = run_hypothesis(h, "VALIDATION")
        md = metrics(h, disc, dbars)
        mv = metrics(h, val, vbars)
        dn = G.net_of(disc)
        t_disc = (
            float(np.mean(dn)) / (float(np.std(dn)) / math.sqrt(dn.shape[0]))
            if dn.shape[0] > 1 and float(np.std(dn)) > 0
            else float("nan")
        )
        mt_rows.append((hid, t_disc, int(dn.shape[0])))
        result["hypotheses"][hid] = {
            "family": h["family"],
            "timeframe": h["timeframe"],
            "discovery": md,
            "validation": mv,
            "t_stat_discovery": round(t_disc, 4) if math.isfinite(t_disc) else None,
            "directional_discovery": directional_info(h, "DISCOVERY"),
            "directional_validation": directional_info(h, "VALIDATION"),
            "power": power_row(h, disc, val),
            "concentration_discovery": G.concentration(disc),
            "concentration_validation": G.concentration(val),
            "outliers_discovery": G.outlier_influence(disc),
            "asset_robustness_discovery": P.group_metrics(disc, "asset"),
            "asset_robustness_validation": P.group_metrics(val, "asset"),
            "regime_metrics_discovery": P.group_metrics(disc, "regime"),
            "regime_metrics_validation": P.group_metrics(val, "regime"),
            "funnel_discovery": signal_funnel(h, "DISCOVERY"),
            "funnel_validation": signal_funnel(h, "VALIDATION"),
            "exit_config": hyp_exit(h),
        }
    result["multiple_testing"] = multiple_testing(mt_rows)
    result["effective_sample"] = {
        "discovery": G.effective_sample("DISCOVERY", "30m"),
        "validation": G.effective_sample("VALIDATION", "30m"),
    }
    _EVAL = result
    return result


def best_discovery(result: dict[str, Any]) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for hid, v in result["hypotheses"].items():
        nb = v["discovery"].get("net_bps")
        if nb is None:
            continue
        if best is None or nb > best[1]:
            best = (hid, float(nb))
    return best


def write_json(path: Path, payload: Any) -> None:
    L.write_json(path, payload)


__all__ = [
    "COST",
    "EXIT",
    "HORIZONS",
    "HORIZON_LABEL",
    "MIN_ECONOMIC_EDGE_BPS",
    "N_NULL_TARGET",
    "OUT",
    "REGISTRY",
    "REGISTRY_HASH",
    "SEED",
    "best_discovery",
    "directional_class",
    "evaluate",
    "hyp_exit",
    "magnitude_info",
    "metrics",
    "multiple_testing",
    "null_draws",
    "p_best_ge_observed",
    "run_hypothesis",
    "signal_funnel",
    "signal_maps",
    "summarise_null",
    "write_json",
]
