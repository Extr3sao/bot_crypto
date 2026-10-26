"""RFC-037 §25-§41 -- adversarial nulls + practical capital feasibility (vectorized).

Frozen strategy, no changes.  Question: is the observed performance distinguishable
from what this pipeline can create WITHOUT real trend information?
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc036_verify as V  # noqa: E402
from rfc036_data import load_all_markets  # noqa: E402

from trading_bot.research import managed_futures_v1 as mf  # noqa: E402

OUT = REPO / "reports" / "managed-futures-refutation"
OUT.mkdir(parents=True, exist_ok=True)
CAP = 10_000_000.0
WINDOWS = {"DISCOVERY": ("1985-01-01", "1993-12-31"), "VALIDATION": ("1994-01-01", "2000-03-31")}
N_SIMS = 1000
SEED = 20261005


def d2o(s: str) -> int:
    return date.fromisoformat(s).toordinal()


class MarketData:
    def __init__(self) -> None:
        self.roots = sorted(V.SPECS)
        self.rets: dict[str, dict[int, float]] = {}
        self.ords: dict[str, list[int]] = {}
        self.cum: dict[str, NDArray[Any]] = {}
        cal: set[int] = set()
        for r in self.roots:
            hs = V.held_series(V.build_market(r), d2o("1970-01-01"), d2o("2000-12-31"))
            self.rets[r] = hs["interval_r"]
            o = sorted(hs["interval_r"])
            self.ords[r] = o
            logr = np.log1p(np.asarray([hs["interval_r"][x] for x in o]))
            self.cum[r] = np.concatenate([[0.0], np.cumsum(logr)])
            cal.update(o)
        self.cal = sorted(cal)

    def last(self, r: str, od: int) -> int:
        import bisect

        return bisect.bisect_right(self.ords[r], od) - 1

    def signal_vol(self, r: str, k: int) -> tuple[float, float]:
        if k - mf.LOOKBACK_DAYS < 0:
            return 0.0, float("nan")
        cum = self.cum[r]
        prod = float(np.exp(cum[k + 1] - cum[k + 1 - mf.LOOKBACK_DAYS]))
        sig = float(np.sign(prod - 1.0))
        lo = max(0, k - mf.VOL_LOOKBACK_DAYS + 1)
        arr = np.asarray([self.rets[r][self.ords[r][j]] for j in range(lo, k + 1)])
        vol = float(np.std(arr, ddof=1) * math.sqrt(252.0)) if arr.size >= 3 else float("nan")
        return sig, vol


def weight_matrix(md: MarketData, lo: int, hi: int) -> tuple[NDArray[Any], NDArray[Any], list[int]]:
    dates = [o for o in md.cal if lo <= o <= hi]
    M = len(md.roots)
    R = np.zeros((len(dates), M))
    idx = {o: i for i, o in enumerate(dates)}
    for j, r in enumerate(md.roots):
        for o, v in md.rets[r].items():
            if o in idx:
                R[idx[o], j] = v
    rebal, seen = [], set()
    for i, o in enumerate(dates):
        mk = (date.fromordinal(o).year, date.fromordinal(o).month)
        if mk not in seen:
            seen.add(mk)
            rebal.append(i)
    W = np.zeros((len(dates), M))
    cur_w = np.zeros(M)
    prev_i: int | None = None
    rset = set(rebal)
    for i, o in enumerate(dates):
        if i in rset:
            sig_od = dates[prev_i] if prev_i is not None else o
            raw = np.zeros(M)
            for j, r in enumerate(md.roots):
                k = md.last(r, sig_od)
                if k < 0:
                    continue
                sig, vol = md.signal_vol(r, k)
                if sig != 0.0 and math.isfinite(vol) and vol > 0:
                    raw[j] = sig * (mf.TARGET_POSITION_VOL / vol)
            nz = np.nonzero(raw)[0]
            n = len(nz)
            if n == 0:
                cur_w = np.zeros(M)
            else:
                scale = _scale(md, raw, nz, dates, i)
                cur_w = raw / n * scale
                g = float(np.abs(cur_w).sum())
                if g > mf.MAX_GROSS_LEVERAGE:
                    cur_w = cur_w * (mf.MAX_GROSS_LEVERAGE / g)
        W[i] = cur_w
        prev_i = i
    return R, W, dates


def _scale(md: MarketData, raw: NDArray[Any], nz: NDArray[Any], dates: list[int], oi: int) -> float:
    if len(nz) < 2:
        return 1.0
    lo = max(0, oi - 1 - mf.VOL_LOOKBACK_DAYS)
    win = dates[lo : oi + 1]
    if len(win) < 10:
        return 1.0
    mat = np.zeros((len(win), len(nz)))
    for jj, j in enumerate(nz):
        r = md.roots[j]
        for t, o in enumerate(win):
            mat[t, jj] = md.rets[r].get(o, 0.0)
    wraw = raw[nz] / len(nz)
    cov = np.atleast_2d(np.cov(mat, rowvar=False, ddof=1))
    var = float(wraw @ cov @ wraw) * 252.0
    return mf.TARGET_PORTFOLIO_VOL / math.sqrt(var) if var > 0 else 1.0


def run_nulls(md: MarketData) -> dict[str, object]:
    M = len(md.roots)
    out: dict[str, object] = {}
    for name, (lo_s, hi_s) in WINDOWS.items():
        R, W, _ = weight_matrix(md, d2o(lo_s), d2o(hi_s))
        obs = float((W * R).sum()) * CAP
        rng = np.random.default_rng(SEED)
        perm = np.empty(N_SIMS)
        for s in range(N_SIMS):
            p = rng.permutation(M)
            perm[s] = float((W * R[:, p]).sum()) * CAP
        rng2 = np.random.default_rng(SEED)
        sgn = np.empty(N_SIMS)
        for s in range(N_SIMS):
            g = np.where(rng2.random(M) < 0.5, 1.0, -1.0)
            sgn[s] = float((W * g * R).sum()) * CAP
        out[name] = {
            "observed_net": obs,
            "perm_median": float(np.median(perm)),
            "perm_p95": float(np.quantile(perm, 0.95)),
            "perm_p99": float(np.quantile(perm, 0.99)),
            "perm_p_null_ge_observed": float(np.mean(perm >= obs)),
            "sign_median": float(np.median(sgn)),
            "sign_p95": float(np.quantile(sgn, 0.95)),
            "sign_p_null_ge_observed": float(np.mean(sgn >= obs)),
            "n_sims": N_SIMS,
        }
    return out


def run_capital() -> dict[str, object]:
    roots = sorted(V.SPECS)
    bm = load_all_markets(roots)
    panels = []
    for r in roots:
        md = bm[r]
        if len(md.series) == 0:
            continue
        ts = mf.build_tradable_series(md, d2o("1970-01-01"), d2o("2000-12-31"))
        if ts.held:
            panels.append(mf.build_panel(md, ts, sorted(ts.held)))
    cal = sorted({o for p in panels for o in p.ts.held})
    lo, hi = d2o("1994-01-01"), d2o("2000-03-31")
    frac = float(
        mf.simulate_portfolio(panels, cal, (lo, hi), mf.default_config(), CAP)["net_pnl"].sum()
    )
    levels = [
        250_000,
        500_000,
        1_000_000,
        2_000_000,
        5_000_000,
        10_000_000,
        25_000_000,
        50_000_000,
        100_000_000,
    ]
    grid = []
    n_markets = len(panels)
    for cap in levels:
        run = mf.simulate_portfolio(
            panels, cal, (lo, hi), mf.default_config(integer_contracts=True), cap
        )
        active = float(np.mean(run["n_long"] + run["n_short"]))
        net = float(run["net_pnl"].sum())
        grid.append(
            {
                "capital": cap,
                "net": net,
                "active_markets": active,
                "lost_markets": max(0.0, n_markets - active),
                "tracking_error": (net - frac) / abs(frac),
            }
        )
    viable = [g for g in grid if g["active_markets"] >= 20.0 and abs(g["tracking_error"]) <= 0.15]
    preferred = [
        g for g in grid if g["active_markets"] >= 24.0 and abs(g["tracking_error"]) <= 0.10
    ]
    return {
        "n_markets": n_markets,
        "fractional_net": frac,
        "grid": grid,
        "preregistered_rule": {
            "min_viable": "active_markets>=20 and |tracking_error|<=15%",
            "min_preferred": "active_markets>=24 and |tracking_error|<=10%",
        },
        "minimum_viable_capital": (viable[0]["capital"] if viable else None),
        "minimum_preferred_capital": (preferred[0]["capital"] if preferred else None),
    }


def main() -> int:
    md = MarketData()
    nulls = run_nulls(md)
    capital = run_capital()
    (OUT / "ADVERSARIAL_NULLS_RAW.json").write_text(
        json.dumps(nulls, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "CAPITAL_FEASIBILITY_RAW.json").write_text(
        json.dumps(capital, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"nulls": nulls, "capital": capital}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
