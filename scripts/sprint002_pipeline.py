"""RFC-022 Sprint 002 - full edge discovery pipeline.

Frozen order:
    DISCOVERY -> freeze survivors -> VALIDATION -> WALK-FORWARD -> ROBUSTNESS
    (cost/slippage stress, parameter neighbourhood, asset/regime/temporal, block
    bootstrap) -> HOLDOUT (finalists only) -> INDEPENDENT VERIFICATION.

The holdout (W6-W7) is read ONLY by finalists that clear discovery + validation
+ robustness, and never used for selection or tuning.

Outputs go to reports/edge-discovery/sprint002/.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint002_lib as L
import sprint002_signals as S


def _const_signal(sig: NDArray[Any]) -> L.SignalFn:
    """Wrap a precomputed signal array as a SignalFn (avoids untyped lambdas)."""

    def fn(_b: L.Bundle) -> NDArray[Any]:
        return sig

    return fn


WARM = 262
COST = L.CERTIFIED_ROUND_TRIP_BPS
OUT = L.OUT_DIR
BOOTSTRAP_N = 2000
RNG_SEED = 20261004

GRID_SWING = [(3.0, True, 1.5, 16), (3.0, True, 1.5, 32), (4.0, True, 2.0, 32), (2.0, True, 1.5, 32)]
GRID_FAST = [(2.0, True, 1.0, 16), (3.0, True, 1.5, 16), (3.0, True, 2.0, 32)]
GRID_NEAR = [(2.0, True, 1.0, 8), (2.5, True, 1.0, 16), (3.0, True, 1.5, 16)]

SINGLE_ASSET_SPECS: list[dict[str, Any]] = [
    {"hyp": "H-P0-01", "family": "compression_breakout", "sig": "compression_breakout", "tfs": ("15m", "30m", "1h", "2h"), "grid": GRID_SWING},
    {"hyp": "H-P0-02", "family": "squeeze_magnitude", "sig": "squeeze_magnitude", "tfs": ("15m", "30m", "1h"), "grid": GRID_SWING},
    {"hyp": "H-P0-03", "family": "vol_contraction_expansion", "sig": "vol_contraction_expansion", "tfs": ("30m", "1h", "2h"), "grid": GRID_SWING},
    {"hyp": "H-P1-01", "family": "pullback_continuation", "sig": "pullback_continuation", "tfs": ("15m", "30m", "1h", "2h"), "grid": GRID_SWING},
    {"hyp": "H-P1-02", "family": "breakout_retest", "sig": "breakout_retest", "tfs": ("30m", "1h", "2h"), "grid": GRID_NEAR},
    {"hyp": "H-P1-03", "family": "regime_momentum", "sig": "regime_momentum", "tfs": ("30m", "1h", "2h"), "grid": GRID_FAST},
    {"hyp": "H-P1-04", "family": "vol_shock_followthrough", "sig": "vol_shock_continuation", "tfs": ("30m", "1h"), "grid": GRID_NEAR},
    {"hyp": "H-P1-04R", "family": "vol_shock_followthrough", "sig": "vol_shock_reversion", "tfs": ("30m", "1h"), "grid": GRID_NEAR},
    {"hyp": "H-P2-02", "family": "volume_expansion", "sig": "volume_expansion", "tfs": ("30m", "1h"), "grid": GRID_NEAR},
    {"hyp": "H-P2-03", "family": "session_conditioning", "sig": "session_conditioning", "tfs": ("30m", "1h"), "grid": GRID_NEAR},
]

SIG_FN: dict[str, Any] = {
    "compression_breakout": S.sig_compression_breakout,
    "squeeze_magnitude": S.sig_squeeze_magnitude,
    "vol_contraction_expansion": S.sig_vol_contraction_expansion,
    "pullback_continuation": S.sig_pullback_continuation,
    "breakout_retest": S.sig_breakout_retest,
    "regime_momentum": S.sig_regime_momentum,
    "vol_shock_continuation": S.sig_vol_shock_continuation,
    "vol_shock_reversion": S.sig_vol_shock_reversion,
    "volume_expansion": S.sig_volume_expansion,
    "session_conditioning": S.sig_session_conditioning,
}


class Bundles:
    def __init__(self) -> None:
        self._files = L.dataset_files()
        self._cache: dict[str, L.Bundle] = {}

    def get(self, asset: str, window: str, tf: str) -> L.Bundle:
        key = f"{asset}|{window}|{tf}"
        if key not in self._cache:
            if tf in ("2h", "4h"):
                src = next(
                    x for x in self._files
                    if x.asset == asset and x.window == window and x.timeframe == "5m"
                )
                bars = L.resample(L.load_bars(src.path), int(L.TF_MIN[tf]))
            else:
                f = next(
                    x for x in self._files
                    if x.asset == asset and x.window == window and x.timeframe == tf
                )
                bars = L.load_bars(f.path)
            self._cache[key] = L.build_bundle(bars, tf)
        return self._cache[key]


B = Bundles()


def run_single(
    exp: dict[str, Any],
    windows: tuple[str, ...],
    assets: tuple[str, ...] = L.ASSETS,
    cost_bps: float = COST,
    slip_mult: float = 1.0,
) -> tuple[list[L.Trade], int]:
    """Re-run one single-asset experiment on a given split."""
    target, is_atr, stop, hold = exp["params"]
    fn = SIG_FN[exp["sig"]]
    trades: list[L.Trade] = []
    eval_bars = 0
    for asset in assets:
        for window in windows:
            b = B.get(asset, window, exp["timeframe"])
            sig = fn(b)
            spec = L.Spec(
                candidate_id=exp["candidate_id"],
                hypothesis_id=exp["hypothesis_id"],
                family=exp["family"],
                timeframe=exp["timeframe"],
                signals=_const_signal(sig),
                warmup=WARM,
                atr_target_mult=target,
                atr_target_is_atr=is_atr,
                atr_stop_mult=stop,
                hold_bars=hold,
            )
            trades.extend(L.run_spec(spec, b, asset, window, cost_bps=cost_bps, slip_mult=slip_mult))
            eval_bars += max(0, len(b) - WARM)
    return trades, eval_bars


def run_lead_lag(
    exp: dict[str, Any],
    windows: tuple[str, ...],
    cost_bps: float = COST,
    slip_mult: float = 1.0,
) -> tuple[list[L.Trade], int]:
    target, _is_atr, stop, hold, lag = exp["params"]
    trades: list[L.Trade] = []
    eval_bars = 0
    for tf in ("15m", "30m"):
        for window in windows:
            leader = B.get("BTCUSDT", window, tf)
            for follower in ("ETHUSDT", "SOLUSDT"):
                fb = B.get(follower, window, tf)
                sig = S.sig_lead_lag(leader, fb, int(lag))
                spec = L.Spec(
                    candidate_id=exp["candidate_id"], hypothesis_id="H-P1-06", family="lead_lag",
                    timeframe=tf, signals=_const_signal(sig), warmup=WARM,
                    atr_target_mult=target, atr_target_is_atr=True, atr_stop_mult=stop,
                    hold_bars=int(hold),
                )
                trades.extend(L.run_spec(spec, fb, follower, window, cost_bps=cost_bps, slip_mult=slip_mult))
                eval_bars += max(0, len(fb) - WARM)
    return trades, eval_bars


def run_xsec(
    exp: dict[str, Any],
    windows: tuple[str, ...],
    cost_bps: float = COST,
    slip_mult: float = 1.0,
) -> tuple[list[L.Trade], int]:
    """Two-leg relative strength; both legs pay the full certified round trip."""
    hold = int(exp["params"][3])
    trades: list[L.Trade] = []
    eval_bars = 0
    for tf in ("1h", "2h"):
        for window in windows:
            bundles = {a: B.get(a, window, tf) for a in L.ASSETS}
            ranks = S.cross_sectional_ranks(bundles)
            for asset, b in bundles.items():
                r = ranks[asset]
                sig = np.zeros(len(b), dtype=np.int8)
                sig[np.isfinite(r) & (r == 1.0)] = 1
                sig[np.isfinite(r) & (r == 3.0)] = -1
                spec = L.Spec(
                    candidate_id=exp["candidate_id"], hypothesis_id="H-P1-05",
                    family="cross_sectional_rs", timeframe=tf, signals=_const_signal(sig),
                    warmup=WARM, atr_target_mult=0.0, atr_target_is_atr=False,
                    atr_stop_mult=0.0, hold_bars=hold,
                )
                trades.extend(L.run_spec(spec, b, asset, window, cost_bps=cost_bps, slip_mult=slip_mult))
                eval_bars += max(0, len(b) - WARM)
    return trades, eval_bars


def rerun(
    exp: dict[str, Any],
    windows: tuple[str, ...],
    cost_bps: float = COST,
    slip_mult: float = 1.0,
    assets: tuple[str, ...] = L.ASSETS,
) -> tuple[list[L.Trade], int]:
    if exp["sig"] == "lead_lag":
        return run_lead_lag(exp, windows, cost_bps, slip_mult)
    if exp["sig"] == "cross_sectional_rs":
        return run_xsec(exp, windows, cost_bps, slip_mult)
    return run_single(exp, windows, assets, cost_bps, slip_mult)


def mm(trades: list[L.Trade], eval_bars: int, tf: str) -> dict[str, Any]:
    return L.metrics(trades, eval_bars, L.TF_MIN[tf])


def params_of(p: tuple[Any, ...]) -> dict[str, Any]:
    if len(p) == 5:
        return {"target_mult": p[0], "target_is_atr": p[1], "stop_mult": p[2], "hold_bars": p[3], "lag_bars": p[4]}
    return {"target_mult": p[0], "target_is_atr": p[1], "stop_mult": p[2], "hold_bars": p[3]}


def stage_discovery() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    exp_no = 0
    for sd in SINGLE_ASSET_SPECS:
        for tf in sd["tfs"]:
            for p in sd["grid"]:
                exp_no += 1
                exp = {
                    "experiment_id": f"EXP-S002-{exp_no:04d}",
                    "candidate_id": f"{sd['sig']}@{tf}",
                    "hypothesis_id": sd["hyp"],
                    "family": sd["family"],
                    "sig": sd["sig"],
                    "timeframe": tf,
                    "params": p,
                }
                trades, eval_bars = run_single(exp, L.SPLITS["DISCOVERY"])
                rows.append({**exp, "parameters": params_of(p), "trades": trades,
                             "eval_bars": eval_bars, "metrics": mm(trades, eval_bars, tf)})
    for lag in (1, 3):
        for p in GRID_NEAR:
            exp_no += 1
            exp = {
                "experiment_id": f"EXP-S002-{exp_no:04d}",
                "candidate_id": f"lead_lag@{lag}bar",
                "hypothesis_id": "H-P1-06",
                "family": "lead_lag",
                "sig": "lead_lag",
                "timeframe": "15m+30m",
                "params": (p[0], True, p[2], p[3], lag),
            }
            trades, eval_bars = run_lead_lag(exp, L.SPLITS["DISCOVERY"])
            rows.append({**exp, "parameters": params_of(exp["params"]), "trades": trades,
                         "eval_bars": eval_bars, "metrics": mm(trades, eval_bars, "15m")})
    for hold in (32, 96):
        exp_no += 1
        exp = {
            "experiment_id": f"EXP-S002-{exp_no:04d}",
            "candidate_id": f"cross_sectional_rs@{hold}bar",
            "hypothesis_id": "H-P1-05",
            "family": "cross_sectional_rs",
            "sig": "cross_sectional_rs",
            "timeframe": "1h+2h",
            "params": (0.0, False, 0.0, hold),
        }
        trades, eval_bars = run_xsec(exp, L.SPLITS["DISCOVERY"])
        rows.append({**exp, "parameters": {**params_of(exp["params"]), "legs": 2},
                     "trades": trades, "eval_bars": eval_bars, "metrics": mm(trades, eval_bars, "1h")})
    return rows


# ---------------------------------------------------------------------------
# robustness helpers
# ---------------------------------------------------------------------------


def block_bootstrap(trades: list[L.Trade], n: int = BOOTSTRAP_N, block: int = 10) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: t.entry_ts)
    net = np.array([t.net_bps for t in ordered], dtype=np.float64)
    if net.shape[0] < 20:
        return {"status": "N/A", "reason": "fewer than 20 trades"}
    rng = random.Random(RNG_SEED)
    nb = int(net.shape[0])
    nblocks = max(1, nb // block) + 1
    means = np.empty(n, dtype=np.float64)
    pfs = np.empty(n, dtype=np.float64)
    for i in range(n):
        idx: list[int] = []
        for _ in range(nblocks):
            s = rng.randrange(0, nb)
            idx.extend(range(s, min(s + block, nb)))
        sample = net[np.array(idx[:nb], dtype=np.int64)]
        means[i] = float(np.mean(sample))
        w = float(sample[sample > 0].sum())
        lo = abs(float(sample[sample < 0].sum()))
        pfs[i] = w / lo if lo > 0 else float("inf")
    return {
        "status": "OK",
        "n_resamples": n,
        "block_size": block,
        "mean_net_bps": round(float(np.mean(net)), 4),
        "ci95_net_bps": [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)],
        "p_net_le_0": round(float(np.mean(means <= 0.0)), 4),
        "pf_median": round(float(np.median(pfs)), 4) if np.isfinite(np.median(pfs)) else None,
    }


def group_metrics(trades: list[L.Trade], key: str) -> dict[str, Any]:
    groups: dict[str, list[L.Trade]] = {}
    for t in trades:
        groups.setdefault(str(getattr(t, key)), []).append(t)
    out: dict[str, Any] = {}
    for g, ts in sorted(groups.items()):
        net = np.array([t.net_bps for t in ts], dtype=np.float64)
        out[g] = {
            "trades": int(net.shape[0]),
            "net_bps": round(float(np.mean(net)), 4),
            "net_pnl_usdt": round(float(net.sum()) / 1e4 * L.ROOT_NOTIONAL, 2),
            "win_rate": round(float(np.count_nonzero(net > 0)) / net.shape[0], 4),
            "verdict": (
                "WORKS" if float(np.mean(net)) > 0 and net.shape[0] >= 10
                else ("INSUFFICIENT_SAMPLE" if net.shape[0] < 10 else "FAILS")
            ),
        }
    return out


def temporal_breakdown(trades: list[L.Trade]) -> dict[str, Any]:
    return group_metrics(trades, "window")


def param_neighbourhood(exp: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a small neighbourhood around the frozen parameters on DISCOVERY."""
    target, is_atr, stop, hold = exp["params"][:4]
    if exp["sig"] in ("lead_lag", "cross_sectional_rs"):
        return {"status": "N/A", "reason": "cross-asset candidate"}
    out: dict[str, Any] = {}
    for dt in (-1.0, 0.0, 1.0):
        for ds in (-0.5, 0.0, 0.5):
            for dh in (0, 16):
                p = (max(0.5, target + dt), is_atr, max(0.5, stop + ds), max(1, hold + dh))
                e = {**exp, "params": p}
                trades, eval_bars = run_single(e, L.SPLITS["DISCOVERY"])
                m = mm(trades, eval_bars, exp["timeframe"])
                out[f"tgt={p[0]}|stop={p[2]}|hold={p[3]}"] = {
                    "trades": m.get("trades", 0),
                    "net_bps": m.get("net_bps"),
                    "edge_cost_ratio": m.get("edge_cost_ratio"),
                }
    nets = [v["net_bps"] for v in out.values() if v["net_bps"] is not None]
    positive = sum(1 for x in nets if x > 0)
    return {
        "status": "OK",
        "neighbourhood": out,
        "positive_cells": positive,
        "total_cells": len(nets),
        "plateau_fraction": round(positive / len(nets), 4) if nets else None,
        "verdict": (
            "PLATEAU" if nets and positive / len(nets) >= 0.6
            else ("PARTIAL" if nets and positive / len(nets) >= 0.3 else "ISOLATED_SPIKE")
        ),
    }


# ---------------------------------------------------------------------------
# artifact writers
# ---------------------------------------------------------------------------


def write_registry_and_matrix(disc: list[dict[str, Any]], survivors: list[dict[str, Any]]) -> None:
    with (OUT / "EXPERIMENT_REGISTRY.jsonl").open("w", encoding="utf-8") as fh:
        for r in disc:
            fh.write(
                json.dumps(
                    {
                        "experiment_id": r["experiment_id"],
                        "candidate_id": r["candidate_id"],
                        "hypothesis_id": r["hypothesis_id"],
                        "family": r["family"],
                        "timeframe": r["timeframe"],
                        "parameters": r["parameters"],
                        "dataset": "strategy-baseline W1-W7 certified (102eac98...)",
                        "split": "DISCOVERY W1-W4",
                        "metrics": r["metrics"],
                        "cost_bps": COST,
                        "code_hash": L.sha256_obj({"sig": r["sig"], "params": r["params"]}),
                        "config_hash": L.config_hash(),
                        "status": (
                            "INSUFFICIENT_SAMPLE" if r["metrics"].get("trades", 0) < L.MIN_TRADES
                            else ("POSITIVE_NET" if r["metrics"].get("net_bps", -1) > 0 else "REJECTED")
                        ),
                    },
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
    cols = [
        "experiment_id", "candidate_id", "hypothesis", "family", "timeframe", "parameters",
        "trades", "gross_expectancy", "net_expectancy", "edge_cost_ratio", "PF", "Sharpe", "MaxDD",
        "discovery_status", "rejection_reason",
    ]
    with (OUT / "EXPERIMENT_MATRIX.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in disc:
            m = r["metrics"]
            status, reason = classify(m)
            w.writerow(
                {
                    "experiment_id": r["experiment_id"], "candidate_id": r["candidate_id"],
                    "hypothesis": r["hypothesis_id"], "family": r["family"],
                    "timeframe": r["timeframe"], "parameters": json.dumps(r["parameters"]),
                    "trades": m.get("trades"), "gross_expectancy": m.get("gross_bps"),
                    "net_expectancy": m.get("net_bps"), "edge_cost_ratio": m.get("edge_cost_ratio"),
                    "PF": m.get("profit_factor"), "Sharpe": m.get("sharpe"),
                    "MaxDD": m.get("max_dd_bps"), "discovery_status": status,
                    "rejection_reason": reason,
                }
            )


def classify(m: dict[str, Any]) -> tuple[str, str]:
    if m.get("trades", 0) < L.MIN_TRADES:
        return "REJECTED_DISCOVERY", "INSUFFICIENT_SAMPLE"
    if m.get("gross_bps", 0) <= 0:
        return "REJECTED_DISCOVERY", "NO_GROSS_EDGE"
    if m.get("net_bps", 0) <= 0:
        return "REJECTED_DISCOVERY", "COST_KILLED"
    if m.get("single_trade_dependency"):
        return "REJECTED_DISCOVERY", "SINGLE_TRADE_DEPENDENCY"
    return "PASSED_DISCOVERY", ""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== STAGE 1 DISCOVERY (W1-W4) ===", flush=True)
    disc = stage_discovery()
    pos = [
        r for r in disc
        if r["metrics"].get("trades", 0) >= L.MIN_TRADES
        and r["metrics"].get("net_bps", -1) > 0
        and not r["metrics"].get("single_trade_dependency")
    ]
    print(f"experiments={len(disc)} positive_net={len(pos)}", flush=True)
    for r in sorted(disc, key=lambda x: -float(x["metrics"].get("net_bps", -99)))[:10]:
        m = r["metrics"]
        print(
            f"  {r['experiment_id']} {r['candidate_id']:30s} {r['parameters']} n={m.get('trades')} "
            f"gross={m.get('gross_bps')} net={m.get('net_bps')} ratio={m.get('edge_cost_ratio')} "
            f"PF={m.get('profit_factor')} t={m.get('t_stat')} exbest={m.get('net_bps_ex_best_trade')}"
        )
    write_registry_and_matrix(disc, pos)
    L.write_json(
        OUT / "DISCOVERY_RAW.json",
        {
            "schema": "rfc022.discovery_raw.v1",
            "experiments": [{k: v for k, v in r.items() if k != "trades"} for r in disc],
        },
    )
    L.write_json(
        OUT / "DISCOVERY_SURVIVOR_SET.json",
        {
            "schema": "rfc022.discovery_survivor_set.v1",
            "split": "DISCOVERY",
            "cost_bps": COST,
            "min_trades": L.MIN_TRADES,
            "survivors": [
                {k: v for k, v in r.items() if k != "trades"}
                for r in sorted(pos, key=lambda x: -float(x["metrics"]["net_bps"]))
            ],
        },
    )
    print("artifacts written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
