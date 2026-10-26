"""RFC-025 Part B — information audit BEFORE any trading (§25-31).

Measures whether the orthogonal features carry DIRECTIONAL information about
future signed spot return at frozen horizons (30m/1h/2h/4h/8h), pooled across
BTC/ETH/SOL, on the certified price corpus.

Two conditions per feature/horizon:
    ALL MARKET                 — every bar
    VOLATILITY EVENT ONLY      — bars where the certified RFC-023 vol shock fires

Read-only; never reads HOLDOUT.
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np

sys.path.insert(0, "scripts")
import sprint002_lib as L
import sprint025_lib as OL

OUT = OL.SPRINT_OUT
SPLITS = ("DISCOVERY", "VALIDATION")
FEATURES = OL.FEATURE_NAMES
HORIZONS = OL.HORIZON_BARS


def _collect(split: str) -> dict[str, Any]:
    """Pool feature/forward pairs across assets and windows for one split."""
    windows = L.SPLITS[split]
    # per feature, per horizon: pooled arrays for ALL and VOL
    pool: dict[str, Any] = {
        f: {h: {"xs": [], "ys": [], "xs_vol": [], "ys_vol": [], "n_vol": 0} for h in HORIZONS}
        for f in FEATURES
    }
    per_asset: dict[str, Any] = {
        a: {f: {h: {"xs": [], "ys": []} for h in HORIZONS} for f in FEATURES} for a in OL.ASSETS
    }
    vol_bars = 0
    total_bars = 0
    for asset in OL.ASSETS:
        for window in windows:
            b = OL.bundle_for(asset, window, "5m")
            feats = OL.ortho_on_bundle(asset, b)
            shock = OL.vol_shock_of(b)
            close = b.bars.c
            total_bars += len(b)
            vol_bars += int(shock.sum())
            for h in HORIZONS:
                fwd = OL.forward_return_bps(close, h)
                finite_fwd = np.isfinite(fwd)
                for f in FEATURES:
                    x = np.asarray(feats[f], dtype=np.float64)
                    m = finite_fwd & np.isfinite(x)
                    pool[f][h]["xs"].extend(x[m].tolist())
                    pool[f][h]["ys"].extend(fwd[m].tolist())
                    mv = m & shock
                    pool[f][h]["xs_vol"].extend(x[mv].tolist())
                    pool[f][h]["ys_vol"].extend(fwd[mv].tolist())
                    per_asset[asset][f][h]["xs"].extend(x[m].tolist())
                    per_asset[asset][f][h]["ys"].extend(fwd[m].tolist())
    return {
        "pool": pool,
        "per_asset": per_asset,
        "total_bars": total_bars,
        "vol_bars": vol_bars,
        "vol_event_rate": round(vol_bars / total_bars, 5) if total_bars else None,
    }


def _stats(x: list[float], y: list[float]) -> dict[str, Any]:
    xs = np.array(x, dtype=np.float64)
    ys = np.array(y, dtype=np.float64)
    if xs.shape[0] < 50:
        return {"status": "N/A", "n": int(xs.shape[0])}
    ic = OL.spearman_ic(xs, ys)
    pe = OL.pearson(xs, ys)
    qs = OL.quantile_spread(xs, ys, 5)
    return {
        "status": "OK",
        "n": int(xs.shape[0]),
        "pearson": round(pe, 5) if pe is not None else None,
        "ic_spearman": round(ic, 5) if ic is not None else None,
        "top_minus_bottom_bps": qs.get("top_minus_bottom_bps"),
        "monotonicity": qs.get("monotonicity"),
        "quantile_means_bps": qs.get("quantile_means_bps"),
    }


def audit() -> dict[str, Any]:
    out: dict[str, Any] = {"splits": {}}
    for split in SPLITS:
        c = _collect(split)
        fout: dict[str, Any] = {}
        for f in FEATURES:
            hout: dict[str, Any] = {}
            for h in HORIZONS:
                allst = _stats(c["pool"][f][h]["xs"], c["pool"][f][h]["ys"])
                volst = _stats(c["pool"][f][h]["xs_vol"], c["pool"][f][h]["ys_vol"])
                hout[OL.HORIZON_LABEL[h]] = {"ALL": allst, "VOL": volst}
            fout[f] = hout
        # strongest feature by |IC| at 1h, ALL
        strongest = _strongest(fout)
        out["splits"][split] = {
            "total_bars": c["total_bars"],
            "vol_bars": c["vol_bars"],
            "vol_event_rate": c["vol_event_rate"],
            "features": fout,
            "strongest_1h_all": strongest,
            "per_asset_1h": {
                a: {
                    f: _stats(c["per_asset"][a][f][12]["xs"], c["per_asset"][a][f][12]["ys"])
                    for f in FEATURES
                }
                for a in OL.ASSETS
            },
        }
    return out


def _strongest(fout: dict[str, Any]) -> dict[str, Any]:
    best_f, best_ic = None, 0.0
    for f, hs in fout.items():
        ic = hs["1h"]["ALL"].get("ic_spearman")
        if ic is not None and abs(ic) > abs(best_ic):
            best_ic, best_f = ic, f
    return {"feature": best_f, "ic_1h_all": round(best_ic, 5) if best_f else None}


def gate(audit_res: dict[str, Any]) -> dict[str, Any]:
    """G_ORTHO_INFO_1: >=1 feature shows directional info in DISCOVERY with the
    SAME sign in VALIDATION (§31). Directional info = |Spearman IC| >= 0.02 and
    |top-minus-bottom| CI-ish threshold, evaluated at the 1h horizon (primary),
    ALL MARKET and VOL conditions reported."""
    disc = audit_res["splits"]["DISCOVERY"]["features"]
    val = audit_res["splits"]["VALIDATION"]["features"]
    ic_thr = 0.02
    tmb_thr = 5.0  # bps, informational scale (profitability not required yet)
    passing: list[dict[str, Any]] = []
    for f in FEATURES:
        rows: dict[str, Any] = {}
        for cond in ("ALL", "VOL"):
            d = disc[f]["1h"][cond]
            v = val[f]["1h"][cond]
            dic = d.get("ic_spearman")
            vic = v.get("ic_spearman")
            dtb = d.get("top_minus_bottom_bps")
            vtb = v.get("top_minus_bottom_bps")
            if dic is None or vic is None:
                rows[cond] = {"status": "N/A"}
                continue
            sign_ok = (dic == 0) or (vic == 0) or (np.sign(dic) == np.sign(vic))
            ic_pass = abs(dic) >= ic_thr and abs(vic) >= ic_thr * 0.5
            tmb_pass = (
                dtb is not None
                and vtb is not None
                and abs(dtb) >= tmb_thr
                and np.sign(dtb) == np.sign(vtb)
            )
            rows[cond] = {
                "discovery_ic": dic,
                "validation_ic": vic,
                "sign_consistent": bool(sign_ok),
                "discovery_tmb_bps": dtb,
                "validation_tmb_bps": vtb,
                "ic_pass": bool(ic_pass and sign_ok),
                "tmb_pass": bool(tmb_pass),
                "pass": bool(sign_ok and (ic_pass or tmb_pass)),
            }
            if rows[cond]["pass"]:
                passing.append({"feature": f, "condition": cond, **rows[cond]})
        # store for reporting
    return {
        "gate": "G_ORTHO_INFO_1",
        "pass": bool(passing),
        "n_passing": len(passing),
        "passing": passing,
        "ic_threshold": ic_thr,
        "tmb_threshold_bps": tmb_thr,
        "horizon": "1h",
        "definition": "same-sign directional info in DISCOVERY and VALIDATION",
    }


def main() -> None:
    OL.SPRINT_OUT.mkdir(parents=True, exist_ok=True)
    res = audit()
    g = gate(res)
    res["G_ORTHO_INFO_1"] = g
    OL.write_json(OUT / "INFORMATION_AUDIT.json", res)
    _write_md(res, g)
    print("vol event rate DISCOVERY:", res["splits"]["DISCOVERY"]["vol_event_rate"])
    print("strongest 1h ALL DISCOVERY:", res["splits"]["DISCOVERY"]["strongest_1h_all"])
    print("G_ORTHO_INFO_1:", g["pass"], "n_passing:", g["n_passing"])
    for p in g["passing"]:
        print("  PASS", p["feature"], p["condition"], p["discovery_ic"], p["validation_ic"])


def _fmt_ic(hs: dict[str, Any], h: str, c: str) -> str:
    v = hs[h][c].get("ic_spearman")
    return f"{v:+.4f}" if v is not None else "n/a"


def _fmt_tmb(hs: dict[str, Any], h: str, c: str) -> str:
    v = hs[h][c].get("top_minus_bottom_bps")
    return f"{v:+.2f}" if v is not None else "n/a"


def _write_md(res: dict[str, Any], g: dict[str, Any]) -> None:
    lines = [
        "# INFORMATION_AUDIT — RFC-025 Part B",
        "",
        "Información DIRECCIONAL de cada feature ortogonal frente al retorno",
        "futuro con signo de spot, a horizontes congelados 30m/1h/2h/4h/8h,",
        "pooled BTC/ETH/SOL, en DISCOVERY (W1-W4) y VALIDATION (W5).",
        "Two conditions: **ALL MARKET** y **VOLATILITY EVENT ONLY** (vol shock certificado).",
        "",
    ]
    for split in SPLITS:
        d = res["splits"][split]
        lines += [
            f"## {split} (bars={d['total_bars']}, vol-event rate={d['vol_event_rate']})",
            "",
            "IC Spearman (1h, ALL / VOL) y top-bottom (bps):",
            "",
            "| feature | IC 1h ALL | IC 1h VOL | t-b 1h ALL | t-b 1h VOL | IC 30m ALL | IC 8h ALL |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for f in FEATURES:
            hs = d["features"][f]
            lines.append(
                f"| {f} | {_fmt_ic(hs, '1h', 'ALL')} | {_fmt_ic(hs, '1h', 'VOL')} | "
                f"{_fmt_tmb(hs, '1h', 'ALL')} | {_fmt_tmb(hs, '1h', 'VOL')} | "
                f"{_fmt_ic(hs, '30m', 'ALL')} | {_fmt_ic(hs, '8h', 'ALL')} |"
            )
        lines.append("")
    lines += [
        "## G_ORTHO_INFO_1",
        "",
        f"**PASS = {g['pass']}** (umbral |IC|>={g['ic_threshold']} o |t-b|>={g['tmb_threshold_bps']} bps,",
        "mismo signo en DISCOVERY y VALIDATION, horizonte 1h).",
        "",
    ]
    if g["passing"]:
        for p in g["passing"]:
            lines.append(
                f"- {p['feature']} [{p['condition']}]: IC D={p['discovery_ic']:+.4f} "
                f"V={p['validation_ic']:+.4f}; t-b D={p['discovery_tmb_bps']} V={p['validation_tmb_bps']}."
            )
    else:
        lines.append("Ninguna feature demuestra información direccional reproducible.")
    lines.append("")
    OL.write_md(OUT / "INFORMATION_AUDIT.md", "\n".join(lines))


if __name__ == "__main__":
    main()
