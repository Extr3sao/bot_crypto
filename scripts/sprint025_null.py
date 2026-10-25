"""RFC-025 §30 — empirical null for the information gate.

Circularly shift the forward-return series (preserves its autocorrelation,
destroys any feature->return alignment) and recompute the pooled Spearman IC
for every feature at the 1h horizon, in ALL and VOL conditions. Report
per-feature p-values and a best-of-N family-wise p-value so a gate that "passes"
several weakly-correlated features is judged against how easily the maximum
|IC| arises by chance.
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, "scripts")
import sprint002_lib as L
import sprint025_lib as OL

OUT = OL.SPRINT_OUT
FEATURES = OL.FEATURE_NAMES
H = 12  # 1h on the 5m grid
N_DRAWS = 500
SEED = 20261025


def _pooled(split: str) -> dict[str, Any]:
    windows = L.SPLITS[split]
    xs: dict[str, list[float]] = {f: [] for f in FEATURES}
    ys: list[float] = []
    shock: list[bool] = []
    for asset in OL.ASSETS:
        for window in windows:
            b = OL.bundle_for(asset, window, "5m")
            feats = OL.ortho_on_bundle(asset, b)
            sh = OL.vol_shock_of(b)
            fwd = OL.forward_return_bps(b.bars.c, H)
            for i in range(len(b)):
                if not np.isfinite(fwd[i]):
                    continue
                ys.append(float(fwd[i]))
                shock.append(bool(sh[i]))
                for f in FEATURES:
                    xs[f].append(float(feats[f][i]))
    return {
        "xs": {f: np.array(v, dtype=np.float64) for f, v in xs.items()},
        "y": np.array(ys, dtype=np.float64),
        "shock": np.array(shock, dtype=bool),
    }


def _corr(xr: NDArray[Any], yr: NDArray[Any], mask: NDArray[Any]) -> float | None:
    a = xr[mask]
    b = yr[mask]
    if a.shape[0] < 50:
        return None
    sa, sb = float(np.std(a)), float(np.std(b))
    if sa == 0 or sb == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main() -> None:
    OL.SPRINT_OUT.mkdir(parents=True, exist_ok=True)
    data = _pooled("DISCOVERY")
    y = data["y"]
    shock = data["shock"]
    n = y.shape[0]
    # precompute feature ranks (over finite feature values, feature is fixed)
    fr: dict[str, NDArray[Any]] = {}
    fmask: dict[str, NDArray[Any]] = {}
    for f in FEATURES:
        x = data["xs"][f]
        fmask[f] = np.isfinite(x)
        xr = np.full(n, np.nan)
        xr[fmask[f]] = OL._rank(x[fmask[f]])
        fr[f] = xr

    yr_obs = OL._rank(y)
    observed: dict[str, dict[str, float | None]] = {}
    for f in FEATURES:
        m_all = fmask[f]
        m_vol = fmask[f] & shock
        observed[f] = {
            "ALL": _corr(fr[f], yr_obs, m_all),
            "VOL": _corr(fr[f], yr_obs, m_vol),
        }

    rng = np.random.default_rng(SEED)
    null: dict[str, dict[str, list[float]]] = {f: {"ALL": [], "VOL": []} for f in FEATURES}
    null_max_all: list[float] = []
    null_max_vol: list[float] = []
    for _ in range(N_DRAWS):
        off = int(rng.integers(1, n))
        yr = OL._rank(np.roll(y, off))
        draw_abs: list[float] = []
        draw_abs_vol: list[float] = []
        for f in FEATURES:
            m_all = fmask[f]
            m_vol = fmask[f] & shock
            c_all = _corr(fr[f], yr, m_all)
            c_vol = _corr(fr[f], yr, m_vol)
            null[f]["ALL"].append(c_all if c_all is not None else 0.0)
            null[f]["VOL"].append(c_vol if c_vol is not None else 0.0)
            draw_abs.append(abs(c_all or 0.0))
            draw_abs_vol.append(abs(c_vol or 0.0))
        null_max_all.append(max(draw_abs))
        null_max_vol.append(max(draw_abs_vol))

    out: dict[str, Any] = {
        "method": "circular shift of forward returns; feature ranks fixed",
        "n_draws": N_DRAWS,
        "horizon": "1h",
        "split": "DISCOVERY",
        "n_bars": int(n),
        "features": {},
    }
    for f in FEATURES:
        row: dict[str, Any] = {}
        for cond in ("ALL", "VOL"):
            obs = observed[f][cond]
            arr = np.array(null[f][cond], dtype=np.float64)
            p = float(np.mean(np.abs(arr) >= abs(obs))) if obs is not None else None
            row[cond] = {
                "observed_ic": round(obs, 5) if obs is not None else None,
                "null_median_abs": round(float(np.median(np.abs(arr))), 5),
                "null_p95_abs": round(float(np.percentile(np.abs(arr), 95)), 5),
                "p_two_sided": round(p, 4) if p is not None else None,
            }
        out["features"][f] = row
    nm = np.array(null_max_all, dtype=np.float64)
    nmv = np.array(null_max_vol, dtype=np.float64)
    out["family_wise_null"] = {
        "n_features": len(FEATURES),
        "null_max_abs_ic_median": round(float(np.median(nm)), 5),
        "null_max_abs_ic_p95": round(float(np.percentile(nm, 95)), 5),
        "note": "max |IC| over the 9 features under the null",
    }
    # best-of-N: is the observed max |IC| beyond the null max? (ALL and VOL)
    obs_max = max(abs(v["ALL"]) for v in observed.values() if v["ALL"] is not None)
    obs_max_vol = max(abs(v["VOL"]) for v in observed.values() if v["VOL"] is not None)
    out["family_wise_null"]["observed_max_abs_ic_all"] = round(float(obs_max), 5)
    out["family_wise_null"]["p_family_wise_all"] = round(float(np.mean(nm >= obs_max)), 4)
    out["family_wise_null"]["observed_max_abs_ic_vol"] = round(float(obs_max_vol), 5)
    out["family_wise_null"]["null_max_abs_ic_vol_p95"] = round(float(np.percentile(nmv, 95)), 5)
    out["family_wise_null"]["p_family_wise_vol"] = round(float(np.mean(nmv >= obs_max_vol)), 4)
    OL.write_json(OUT / "EMPIRICAL_NULL.json", out)
    _md(out)
    for f in FEATURES:
        print(
            f"{f:16s} ALL obs={out['features'][f]['ALL']['observed_ic']} p={out['features'][f]['ALL']['p_two_sided']}"
            f" | VOL obs={out['features'][f]['VOL']['observed_ic']} p={out['features'][f]['VOL']['p_two_sided']}"
        )
    fw = out["family_wise_null"]
    print("family-wise ALL p:", fw["p_family_wise_all"], "obs_max:", fw["observed_max_abs_ic_all"], "null p95:", fw["null_max_abs_ic_p95"])
    print("family-wise VOL p:", fw["p_family_wise_vol"], "obs_max:", fw["observed_max_abs_ic_vol"], "null p95:", fw["null_max_abs_ic_vol_p95"])


def _md(out: dict[str, Any]) -> None:
    lines = [
        "# EMPIRICAL_NULL — RFC-025 §30",
        "",
        f"{out['method']}; {out['n_draws']} draws; horizon {out['horizon']}; split {out['split']} (n={out['n_bars']}).",
        "",
        "| feature | IC ALL | p ALL | IC VOL | p VOL |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for f, row in out["features"].items():
        lines.append(
            f"| {f} | {row['ALL']['observed_ic']} | {row['ALL']['p_two_sided']} | "
            f"{row['VOL']['observed_ic']} | {row['VOL']['p_two_sided']} |"
        )
    fw = out["family_wise_null"]
    lines += [
        "",
        f"Family-wise ALL (max |IC| over 9 features): observed {fw['observed_max_abs_ic_all']}, "
        f"null median {fw['null_max_abs_ic_median']}, null p95 {fw['null_max_abs_ic_p95']}, "
        f"**p_family_wise_ALL = {fw['p_family_wise_all']}**.",
        "",
        f"Family-wise VOL (max |IC| over 9 features): observed {fw['observed_max_abs_ic_vol']}, "
        f"null p95 {fw['null_max_abs_ic_vol_p95']}, **p_family_wise_VOL = {fw['p_family_wise_vol']}**.",
        "",
    ]
    OL.write_md(OUT / "EMPIRICAL_NULL.md", "\n".join(lines))


if __name__ == "__main__":
    main()
