"""RFC-022 Sprint 002 - Stage 0 MAGNITUDE SCREEN + MFE/MAE ANALYSIS.

Cheap screening BEFORE any backtest. For every hypothesis the event bar set is
computed on DISCOVERY (W1-W4) only; forward excursions (MFE/MAE) are read from
bars after each event and are RESEARCH ONLY (they never feed a decision).

Outputs:
    reports/edge-discovery/sprint002/MAGNITUDE_SCREEN.{md,json}
    reports/edge-discovery/sprint002/MFE_MAE_ANALYSIS.{md,json}
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
from sprint002_hypotheses import HYPOTHESIS_META

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint002_lib as L
import sprint002_signals as S

DISCOVERY_TFS = ("15m", "30m", "1h", "2h", "4h")
HORIZONS = {
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "8h": 480,
    "12h": 720,
    "24h": 1440,
}

# hypothesis -> signal function (single-asset, PIT)
SIGNALS: dict[str, Any] = {
    "H-P0-01": S.sig_compression_breakout,
    "H-P0-02": S.sig_squeeze_magnitude,
    "H-P0-03": S.sig_vol_contraction_expansion,
    "H-P1-01": S.sig_pullback_continuation,
    "H-P1-02": S.sig_breakout_retest,
    "H-P1-03": S.sig_regime_momentum,
    "H-P1-04": S.sig_vol_shock_continuation,
    "H-P1-04R": S.sig_vol_shock_reversion,
    "H-P2-02": S.sig_volume_expansion,
    "H-P2-03": S.sig_session_conditioning,
}

MIN_EVENTS = 30  # below this the magnitude verdict is INSUFFICIENT_SAMPLE


def series(asset: str, window: str, tf: str) -> L.Bundle:
    files = L.dataset_files()
    if tf in ("2h", "4h"):
        src = next(
            x
            for x in files
            if x.asset == asset and x.window == window and x.timeframe == "5m"
        )
        bars = L.resample(L.load_bars(src.path), int(L.TF_MIN[tf]))
    else:
        f = next(
            x
            for x in files
            if x.asset == asset and x.window == window and x.timeframe == tf
        )
        bars = L.load_bars(f.path)
    return L.build_bundle(bars, tf)


def main() -> int:
    L.OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    mfe_rows: list[dict[str, Any]] = []

    for asset in L.ASSETS:
        for window in L.SPLITS["DISCOVERY"]:
            for tf in DISCOVERY_TFS:
                bundle = series(asset, window, tf)
                if len(bundle) < 260:
                    continue
                for hyp, fn in SIGNALS.items():
                    sig = fn(bundle)
                    idx = np.nonzero(sig != 0)[0]
                    n = int(idx.shape[0])
                    if n == 0:
                        continue
                    sides = sig[idx].astype(np.float64)
                    # Directional edge at a FIXED short horizon (first MFE), and
                    # the same-side forward excursion. Directional MFE answers
                    # "can a correctly-directed entry clear cost?"
                    for hz_name, hz_min in HORIZONS.items():
                        per = max(1, round(hz_min / bundle.tf_min))
                        mfe, mae = L.directional_excursions(bundle, idx, sides, per)
                        finite = np.isfinite(mfe)
                        if not finite.any():
                            continue
                        m = mfe[finite]
                        a = mae[finite]
                        n_mfe = np.nanmean(mfe)
                        mfe_med = L.pct(m, 50)
                        mae_med = L.pct(a, 50)
                        rows.append(
                            {
                                "directional_mfe_mean": round(float(n_mfe), 2)
                                if np.isfinite(n_mfe)
                                else None,
                                "directional_edge_vs_cost": round(
                                    float(n_mfe) - L.CERTIFIED_ROUND_TRIP_BPS, 2
                                )
                                if np.isfinite(n_mfe)
                                else None,
                                "asset": asset,
                                "window": window,
                                "timeframe": tf,
                                "hypothesis_id": hyp,
                                "horizon": hz_name,
                                "events": n,
                                "mfe_p25": L.pct(m, 25),
                                "mfe_median": L.pct(m, 50),
                                "mfe_p75": L.pct(m, 75),
                                "mfe_p90": L.pct(m, 90),
                                "mae_p25": L.pct(a, 25),
                                "mae_median": L.pct(a, 50),
                                "mae_p75": L.pct(a, 75),
                                "mfe_minus_cost_median": (
                                    round(mfe_med - L.CERTIFIED_ROUND_TRIP_BPS, 2)
                                    if mfe_med is not None
                                    else None
                                ),
                                "mfe_over_mae_median": (
                                    round(mfe_med / mae_med, 3)
                                    if mfe_med is not None and mae_med
                                    else None
                                ),
                            }
                        )
                        if hz_name in ("1h", "2h", "4h"):
                            mfe_rows.append(rows[-1])

    # ---- aggregate per hypothesis (pooled across assets/windows) -----------
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["hypothesis_id"]
        a = agg.setdefault(
            key,
            {
                "events": 0,
                "timeframes": set(),
                "by_horizon": {},
            },
        )
        a["events"] += r["events"]
        a["timeframes"].add(r["timeframe"])
        bh = a["by_horizon"].setdefault(
            r["horizon"],
            {
                "events": 0,
                "mfe_p75": [],
                "mfe_median": [],
                "mae_median": [],
                "mfe_p90": [],
                "dir_mfe": [],
            },
        )
        bh["events"] += r["events"]
        for f in ("mfe_p75", "mfe_median", "mae_median", "mfe_p90"):
            if r[f] is not None:
                bh[f].append(r[f])
        if r.get("directional_mfe_mean") is not None:
            bh["dir_mfe"].append(r["directional_mfe_mean"])

    screen: dict[str, Any] = {}
    for hyp, a in agg.items():
        meta = HYPOTHESIS_META.get(hyp, {"family": "", "tier": ""})
        best = None
        for hz, bh in a["by_horizon"].items():
            if not bh["mfe_p75"]:
                continue
            p75 = float(np.median(bh["mfe_p75"]))
            med = float(np.median(bh["mfe_median"]))
            if best is None or p75 > best["mfe_p75"]:
                best = {"horizon": hz, "mfe_p75": round(p75, 2), "mfe_median": round(med, 2)}

        # Directional edge at the SHORT short horizons that a real strategy can
        # actually hold (30m/1h/2h/4h): can a correctly-directed entry pay cost?
        dir_by_hz: dict[str, float | None] = {}
        for hz in ("30m", "1h", "2h", "4h"):
            bh = a["by_horizon"].get(hz)
            if bh and bh["dir_mfe"]:
                dir_by_hz[hz] = round(float(np.mean(bh["dir_mfe"])), 2)
            else:
                dir_by_hz[hz] = None
        dir_1h = dir_by_hz.get("1h")
        directional_edge = (
            round(dir_1h - L.CERTIFIED_ROUND_TRIP_BPS, 2) if dir_1h is not None else None
        )
        if directional_edge is None:
            direction_verdict = "INSUFFICIENT_SAMPLE"
        elif directional_edge > 0:
            direction_verdict = "DIRECTIONAL_EDGE"
        else:
            direction_verdict = "NO_DIRECTIONAL_EDGE"
        if a["events"] < MIN_EVENTS:
            verdict, reason = "INSUFFICIENT_SAMPLE", f"pooled events {a['events']} < {MIN_EVENTS}"
        elif best is None:
            verdict, reason = "INSUFFICIENT_SAMPLE", "no finite forward excursions"
        elif best["mfe_p75"] < L.CERTIFIED_ROUND_TRIP_BPS:
            verdict, reason = (
                "NO",
                f"P75 MFE {best['mfe_p75']} bps < cost {L.CERTIFIED_ROUND_TRIP_BPS}",
            )
        else:
            verdict, reason = (
                "YES",
                f"P75 MFE {best['mfe_p75']} bps >= cost at horizon {best['horizon']}",
            )
        screen[hyp] = {
            "hypothesis_id": hyp,
            "family": meta.get("family", ""),
            "tier": meta.get("tier", ""),
            "pooled_events": a["events"],
            "timeframes": sorted(a["timeframes"]),
            "best_horizon": best["horizon"] if best else None,
            "best_mfe_p75": best["mfe_p75"] if best else None,
            "best_mfe_median": best["mfe_median"] if best else None,
            "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
            "magnitude_sufficient": verdict,
            "verdict": verdict,
            "reason": reason,
            "directional_mfe_mean_by_horizon": dir_by_hz,
            "directional_edge_at_1h_bps": directional_edge,
            "direction_verdict": direction_verdict,
            "mfe_mae_symmetry": (
                "MFE~MAE: direction unknown at the event bar"
                if (best and best["mfe_p75"])
                else None
            ),
            "status": "DATA_BLOCKED" if meta.get("status") == "DATA_BLOCKED" else "SCREENED",
            "by_horizon": {
                hz: {
                    "events": bh["events"],
                    "mfe_median": round(float(np.median(bh["mfe_median"])), 2)
                    if bh["mfe_median"]
                    else None,
                    "mfe_p75": round(float(np.median(bh["mfe_p75"])), 2) if bh["mfe_p75"] else None,
                    "mfe_p90": round(float(np.median(bh["mfe_p90"])), 2) if bh["mfe_p90"] else None,
                    "mae_median": round(float(np.median(bh["mae_median"])), 2)
                    if bh["mae_median"]
                    else None,
                }
                for hz, bh in a["by_horizon"].items()
            },
        }

    screen["H-P1-05"] = {
        "hypothesis_id": "H-P1-05",
        "family": HYPOTHESIS_META["H-P1-05"]["family"],
        "tier": "P1",
        "pooled_events": None,
        "timeframes": ["1h", "2h"],
        "best_horizon": None,
        "best_mfe_p75": None,
        "best_mfe_median": None,
        "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
        "magnitude_sufficient": "N/A",
        "verdict": "N/A",
        "reason": "two-leg pair hypothesis; barrier is 2 x cost (47.58 bps); screened in the pair section",
        "directional_mfe_mean_by_horizon": {},
        "directional_edge_at_1h_bps": None,
        "direction_verdict": "N/A",
        "status": "SCREENED",
        "by_horizon": {},
    }
    screen["H-P2-01"] = {
        "hypothesis_id": "H-P2-01",
        "family": HYPOTHESIS_META["H-P2-01"]["family"],
        "tier": "P2",
        "pooled_events": 0,
        "timeframes": [],
        "best_horizon": None,
        "best_mfe_p75": None,
        "best_mfe_median": None,
        "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
        "magnitude_sufficient": "DATA_BLOCKED",
        "verdict": "DATA_BLOCKED",
        "reason": "no authoritative historical PIT funding/basis series (only a 2026-10-01 forward capture)",
        "directional_mfe_mean_by_horizon": {},
        "directional_edge_at_1h_bps": None,
        "direction_verdict": "DATA_BLOCKED",
        "status": "DATA_BLOCKED",
        "by_horizon": {},
    }

    payload = {
        "schema": "rfc022.magnitude_screen.v1",
        "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
        "min_events": MIN_EVENTS,
        "split": "DISCOVERY W1-W4",
        "timeframes": list(DISCOVERY_TFS),
        "assets": list(L.ASSETS),
        "note": (
            "Forward excursions are ex-post research only and never feed signal generation. "
            "The P75 MFE vs cost comparison is guidance, not an arbitrary pass threshold."
        ),
        "hypotheses": screen,
        "rows": rows,
    }
    L.write_json(L.OUT_DIR / "MAGNITUDE_SCREEN.json", payload)
    L.write_json(
        L.OUT_DIR / "MFE_MAE_ANALYSIS.json",
        {
            "schema": "rfc022.mfe_mae_analysis.v1",
            "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
            "horizons": list(HORIZONS),
            "note": "MFE/MAE by hypothesis/asset/timeframe/horizon, DISCOVERY only, ex-post.",
            "rows": mfe_rows,
        },
    )
    print("magnitude screen rows:", len(rows))
    for hyp, v in sorted(screen.items()):
        print(
            f"  {hyp}: mag={v['verdict']:18s} dir={v['direction_verdict']:20s} "
            f"events={v['pooled_events']} dir_edge_1h={v['directional_edge_at_1h_bps']} "
            f"dir_mfe={v['directional_mfe_mean_by_horizon']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
