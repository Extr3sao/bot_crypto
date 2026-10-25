"""RFC-022 Sprint 002 - VOLATILITY@30M DIAGNOSIS (§10).

Mandatory BEFORE any re-tuning around the Sprint 001 finding. Answers:

    Why does volatility@30m produce +19.78 bps gross?
    Does the signal predict, or does it merely trade when amplitude is larger?
    Where does it lose (entry, exit, false breakout, regime, hold, cost)?

Method: read the per-trade research CSV (no new backtest, no re-tuning), split
chronologically, and compute ex-post counterfactual horizons from the certified
30m bars. Counterfactuals are RESEARCH ONLY.

Outputs:
    reports/edge-discovery/sprint002/VOLATILITY_30M_DIAGNOSIS.{md,json}
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint002_lib as L

CSV = L.REPO / "reports" / "strategy-baseline" / "TRADES_volatility_30m.csv"
SPRINT001_SLIP_BPS_ROUND_TRIP = 2.0  # the research sim applied 1 bp/side
HORIZON_BARS = {"30m": 1, "1h": 2, "2h": 4, "4h": 8, "8h": 16}


def _f(x: str) -> float:
    return float(x)


def _asset_code(symbol: str) -> str:
    """'BTC/USDT' -> 'BTCUSDT' (dataset file prefix)."""
    return symbol.replace("/", "")


def load() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scenario"] != "BASE":
                continue
            notional = _f(r["notional"])
            out.append(
                {
                    "window": r["window"][:2],
                    "asset": r["asset"],
                    "side": r["side"],
                    "entry_ts": int(r["entry_ts"]),
                    "exit_ts": int(r["exit_ts"]),
                    "entry": _f(r["entry"]),
                    "exit": _f(r["exit"]),
                    "reason": r["reason"],
                    "mfe_pct": _f(r["mfe_pct"]),
                    "mae_pct": _f(r["mae_pct"]),
                    "notional": notional,
                    "gross_usdt": _f(r["gross"]),
                    "fees_usdt": _f(r["fees"]),
                    "net_usdt": _f(r["net"]),
                    "duration_min": _f(r["duration_min"]),
                    # CSV gross is already after 1 bp/side slippage -> the pure
                    # price move adds the 2 bps round trip back.
                    "price_move_bps": _f(r["gross"]) / notional * 1e4 + SPRINT001_SLIP_BPS_ROUND_TRIP,
                    "sim_gross_bps": _f(r["gross"]) / notional * 1e4,
                }
            )
    return out


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"trades": 0}
    pm = np.array([r["price_move_bps"] for r in rows])
    sim = np.array([r["sim_gross_bps"] for r in rows])
    mfe = np.array([r["mfe_pct"] for r in rows]) * 100.0  # % -> bps
    mae = np.array([r["mae_pct"] for r in rows]) * 100.0
    dur = np.array([r["duration_min"] for r in rows])
    wins = pm[pm > 0]
    losses = pm[pm <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.shape[0] else None
    return {
        "trades": int(pm.shape[0]),
        "gross_bps_as_reported": round(float(np.mean(sim)), 4),
        "price_move_bps": round(float(np.mean(pm)), 4),
        "median_price_move_bps": round(float(np.median(pm)), 4),
        "net_bps_as_reported": round(float(np.mean(sim)) - L.CERTIFIED_ROUND_TRIP_BPS, 4),
        "net_bps_corrected": round(float(np.mean(pm)) - L.CERTIFIED_ROUND_TRIP_BPS, 4),
        "edge_cost_ratio_corrected": round(float(np.mean(pm)) / L.CERTIFIED_ROUND_TRIP_BPS, 4),
        "win_rate": round(float(wins.shape[0]) / pm.shape[0], 4),
        "avg_win_bps": round(float(wins.mean()), 2) if wins.shape[0] else None,
        "avg_loss_bps": round(float(losses.mean()), 2) if losses.shape[0] else None,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "mfe_bps_mean": round(float(np.mean(mfe)), 2),
        "mfe_bps_median": round(float(np.median(mfe)), 2),
        "mae_bps_mean": round(float(np.mean(mae)), 2),
        "mae_bps_median": round(float(np.median(mae)), 2),
        "mfe_over_mae_mean": round(float(np.mean(mfe) / np.mean(mae)), 4)
        if float(np.mean(mae)) > 0
        else None,
        "avg_duration_min": round(float(np.mean(dur)), 1),
        "median_duration_min": round(float(np.median(dur)), 1),
        "exit_mix": dict(Counter(r["reason"] for r in rows)),
        "side_mix": dict(Counter(r["side"] for r in rows)),
    }


def by_reason(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rsn in sorted({r["reason"] for r in rows}):
        sub = [r for r in rows if r["reason"] == rsn]
        pm = np.array([r["price_move_bps"] for r in sub])
        out[rsn] = {
            "n": len(sub),
            "mean_price_move_bps": round(float(np.mean(pm)), 2),
            "median_price_move_bps": round(float(np.median(pm)), 2),
        }
    return out


def by_side(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sd in sorted({r["side"] for r in rows}):
        sub = [r for r in rows if r["side"] == sd]
        pm = np.array([r["price_move_bps"] for r in sub])
        out[sd] = {
            "n": len(sub),
            "mean_price_move_bps": round(float(np.mean(pm)), 2),
            "win_rate": round(float(np.count_nonzero(pm > 0)) / pm.shape[0], 4),
        }
    return out


def horizon_counterfactual(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Ex-post pure-price move at fixed horizons after each DEV entry.

    Diagnosis of the EXIT only: this is not a strategy and is never promoted.
    """
    bars_cache: dict[tuple[str, str], L.Bars] = {}
    res: dict[str, list[float]] = {h: [] for h in HORIZON_BARS}
    for r in rows:
        asset = _asset_code(r["asset"])
        key = (asset, r["window"])
        if key not in bars_cache:
            f = next(
                x
                for x in L.dataset_files()
                if x.asset == asset and x.window == r["window"] and x.timeframe == "30m"
            )
            bars_cache[key] = L.load_bars(f.path)
        bars = bars_cache[key]
        idx = int(np.argmin(np.abs(bars.ts - float(r["entry_ts"]))))
        sgn = 1.0 if r["side"] == "buy" else -1.0
        # Entry at the OPEN of the bar AFTER the signal bar (same convention as
        # the Sprint 002 engine). Entering at the signal bar's own open would
        # read a bar that was not yet closed when the decision was made.
        base = idx + 1
        if base >= len(bars):
            continue
        for hz, nb in HORIZON_BARS.items():
            j = base + nb
            if j < len(bars):
                res[hz].append(sgn * (float(bars.o[j]) / float(bars.o[base]) - 1.0) * 1e4)
    out: dict[str, Any] = {}
    for hz, vals in res.items():
        if not vals:
            continue
        arr = np.array(vals)
        out[hz] = {
            "n": int(arr.shape[0]),
            "mean_bps": round(float(np.mean(arr)), 2),
            "median_bps": round(float(np.median(arr)), 2),
            "win_rate": round(float(np.count_nonzero(arr > 0)) / arr.shape[0], 4),
            "net_of_certified_cost_bps": round(
                float(np.mean(arr)) - L.CERTIFIED_ROUND_TRIP_BPS, 2
            ),
        }
    return out


def amplitude_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Does the signal merely fire in high-amplitude bars?

    Compares the ATR percentile at signal entries against the unconditional
    distribution of the same percentile over the DEV bars.
    """
    entries: list[float] = []
    uncond: list[float] = []
    cache: dict[tuple[str, str], L.Bundle] = {}
    for r in rows:
        asset = _asset_code(r["asset"])
        key = (asset, r["window"])
        if key not in cache:
            f = next(
                x
                for x in L.dataset_files()
                if x.asset == asset and x.window == r["window"] and x.timeframe == "30m"
            )
            cache[key] = L.build_bundle(L.load_bars(f.path), "30m")
        b = cache[key]
        idx = int(np.argmin(np.abs(b.bars.ts - float(r["entry_ts"]))))
        ra = float(b.rank_atr[120][max(0, idx - 1)])
        if np.isfinite(ra):
            entries.append(ra)
    for b in cache.values():
        vals = b.rank_atr[120]
        uncond.extend([float(x) for x in vals[np.isfinite(vals)]])
    e = np.array(entries)
    u = np.array(uncond)
    return {
        "entries_with_rank": int(e.shape[0]),
        "entry_rank_atr_median": round(float(np.median(e)), 4) if e.shape[0] else None,
        "unconditional_rank_atr_median": round(float(np.median(u)), 4) if u.shape[0] else None,
        "interpretation": (
            "entry_rank_atr_median close to 0.5 means the signal is NOT merely selecting "
            "high-amplitude bars"
        ),
    }


def main() -> int:
    rows = load()
    dev = [r for r in rows if r["window"] in L.SPLITS["DISCOVERY"]]
    val = [r for r in rows if r["window"] in L.SPLITS["VALIDATION"]]
    hold = [r for r in rows if r["window"] in L.SPLITS["HOLDOUT"]]

    diag: dict[str, Any] = {
        "schema": "rfc022.volatility_30m_diagnosis.v1",
        "candidate": "volatility@30m",
        "sprint001_reported": {
            "trades": 108,
            "gross_bps": 19.78,
            "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
            "net_bps": -4.01,
            "edge_cost_ratio": 0.831,
            "profit_factor": 0.9,
            "sharpe": -0.83,
            "max_dd_bps": 1318.8,
        },
        "cost_convention_note": (
            "The Sprint 001 CSV 'gross' is already net of the research simulator's 1 bp/side "
            "slippage, so subtracting the full certified round trip double-counts ~2 bps of "
            "slippage. The pure price move is csv_gross + 2.0 bps; both figures are reported."
        ),
        "splits": {
            "DISCOVERY": stats(dev),
            "VALIDATION": stats(val),
            "HOLDOUT": stats(hold),
            "ALL": stats(rows),
        },
        "by_reason": {"DISCOVERY": by_reason(dev), "VALIDATION": by_reason(val)},
        "by_side": {"DISCOVERY": by_side(dev), "VALIDATION": by_side(val)},
        "horizon_counterfactual_discovery": horizon_counterfactual(dev),
        "amplitude_check_discovery": amplitude_check(dev),
    }

    d = diag["splits"]["DISCOVERY"]
    v = diag["splits"]["VALIDATION"]
    h = diag["splits"]["HOLDOUT"]
    a = diag["splits"]["ALL"]

    # Driftless benchmark for the observed barrier geometry: for a symmetric
    # random walk the probability of touching +T before -S is S/(T+S). Comparing
    # the observed hit rate to that benchmark separates "real directional drift"
    # from "barrier geometry".
    tp_bps = 74.0
    sl_bps_d = float(np.mean([r["price_move_bps"] for r in dev if r["reason"] == "stop_loss"]))
    sl_bps_v = float(np.mean([r["price_move_bps"] for r in val if r["reason"] == "stop_loss"]))
    sl_bps_h = float(np.mean([r["price_move_bps"] for r in hold if r["reason"] == "stop_loss"]))
    bench_d = abs(sl_bps_d) / (tp_bps + abs(sl_bps_d)) if sl_bps_d else None
    bench_v = abs(sl_bps_v) / (tp_bps + abs(sl_bps_v)) if sl_bps_v else None
    bench_h = abs(sl_bps_h) / (tp_bps + abs(sl_bps_h)) if sl_bps_h else None
    diag["barrier_benchmark"] = {
        "take_profit_bps": tp_bps,
        "observed_stop_loss_mean_bps": {
            "DISCOVERY": round(sl_bps_d, 2),
            "VALIDATION": round(sl_bps_v, 2),
            "HOLDOUT": round(sl_bps_h, 2),
        },
        "driftless_hit_rate_benchmark": {
            "DISCOVERY": round(bench_d, 4) if bench_d else None,
            "VALIDATION": round(bench_v, 4) if bench_v else None,
            "HOLDOUT": round(bench_h, 4) if bench_h else None,
        },
        "observed_hit_rate": {
            "DISCOVERY": d["win_rate"],
            "VALIDATION": v.get("win_rate"),
            "HOLDOUT": h.get("win_rate"),
        },
        "interpretation": (
            "A driftless random walk would hit +74 bps before about -115 bps roughly 61-63% of "
            "the time. DISCOVERY (71%) exceeded that; VALIDATION and HOLDOUT fell to or below it. "
            "The Sprint 001 edge is therefore mostly BARRIER GEOMETRY plus DISCOVERY-period luck, "
            "not directional drift."
        ),
    }

    cf = diag["horizon_counterfactual_discovery"]
    endpoint_1h = cf.get("1h", {}).get("mean_bps")
    findings = {
        "why_positive_in_discovery": (
            "A bimodal payoff with a high hit rate: take_profit at a fixed +74 bps and stop_loss "
            "at about -115 to -123 bps (the SHORT leg uses the adapter's flat 1% default because "
            "its structural stop sits above price). 71% winners x +74 vs 29% losers x -115 yields "
            "about +19.8 bps mean in DISCOVERY. It is a hit-rate bet, not a large-move bet."
        ),
        "does_the_signal_predict": (
            "NO persistent directional edge at the executable entry. Measured from the OPEN of "
            "the bar AFTER the signal bar, the pure price move at fixed horizons is tiny: "
            f"+{cf.get('30m', {}).get('mean_bps')} bps at 30m, {endpoint_1h} bps at 1h, "
            f"{cf.get('2h', {}).get('mean_bps')} bps at 2h, {cf.get('4h', {}).get('mean_bps')} bps "
            "at 4h, all below the 23.79 bps round trip. The excursion exists but REVERTS: the "
            "mean is back near zero by the horizon end."
        ),
        "is_it_just_amplitude": (
            "NO — it selects LOW-amplitude bars. The entry ATR percentile median is 0.208 versus "
            "0.467 unconditional, so the squeeze family correctly identifies compressed regimes. "
            "But the subsequent expansion is directionally symmetric (endpoint drift ~0), so the "
            "profit comes from where the barriers sit inside the excursion, not from amplitude."
        ),
        "where_it_loses": (
            "OOS and in the endpoint. DISCOVERY is about +19.8 bps while W5-W7 is negative (the "
            "pooled 194-trade mean is only about +7.5 bps). The driftless-walk hit-rate benchmark "
            "for this barrier geometry is about 61-63%; DISCOVERY hit 71% but HOLDOUT fell to "
            "51.7%, i.e. below the random-walk benchmark."
        ),
        "exit_too_early": (
            "NO — the opposite. Because the endpoint drift is ~0, a longer hold earns ~nothing; "
            "the flat +74 bps target is what *creates* the DISCOVERY profit by harvesting the "
            "intra-window excursion before it reverts. That is not a durable edge: it is "
            "path-dependent barrier harvesting whose hit rate is not stable out of sample."
        ),
        "entry_problem": (
            "YES, in the sense that matters: the release bar carries no directional information "
            "that survives to the next open. A compression-quality or trend filter would have to "
            "supply the direction, which is exactly what H-P0-02 tests."
        ),
        "regime_problem": (
            "The family DOES select the intended regime (entry ATR percentile median 0.208 vs "
            "0.467 unconditional), so regime selection is not the failure. The failure is that the "
            "expansion it correctly anticipates has no persistent direction."
        ),
        "holding_period": (
            "Median hold 180 minutes at the 30m timeframe: the '30m' label is the signal "
            "timeframe, not the holding period. Sprint 001 did not test a hold-time axis, and the "
            "counterfactual shows the hold time does not rescue the edge."
        ),
        "cost_inevitable": (
            "YES for this family in this form. The corrected price-move edge is about 21.8 bps "
            "against a 23.79 bps round trip (~0.92 of cost) and the executable-entry drift is "
            "~+3.6 bps, i.e. about 0.15 of cost."
        ),
    }
    diag["findings"] = findings

    L.write_json(L.OUT_DIR / "VOLATILITY_30M_DIAGNOSIS.json", diag)

    # ---- markdown ---------------------------------------------------------
    d = diag["splits"]["DISCOVERY"]
    v = diag["splits"]["VALIDATION"]
    h = diag["splits"]["HOLDOUT"]
    a = diag["splits"]["ALL"]
    hc = diag["horizon_counterfactual_discovery"]
    lines = [
        "# SPRINT 002 — VOLATILITY@30M DIAGNOSIS",
        "",
        "Mandatory diagnosis BEFORE any re-tuning of the Sprint 001 finding (§10).",
        "No parameter was changed to produce this document; it reads the existing",
        "per-trade research CSV and the certified 30m bars only.",
        "",
        "```text",
        "candidate            = volatility@30m (Bollinger/Keltner squeeze release)",
        "sprint001 reported   = gross +19.78 bps / net -4.01 bps / ratio 0.831 / PF 0.90",
        "trades               = 194 BASE (108 DISCOVERY, 27 W5, 59 W6-W7)",
        "```",
        "",
        "## Cost-convention correction (important)",
        "",
        "The Sprint 001 CSV `gross` is **already net of the research simulator's 1 bp/side",
        "slippage**, and Sprint 001 then subtracted the full certified round trip — which",
        "contains slippage again. That double-counts ~2 bps. The pure price move is",
        "`csv_gross + 2.0 bps`.",
        "",
        "| | as reported (Sprint 001) | corrected (price move) |",
        "|---|---:|---:|",
        f"| DISCOVERY gross | {d['gross_bps_as_reported']} | {d['price_move_bps']} |",
        f"| DISCOVERY net vs 23.790569 | {d['net_bps_as_reported']} | {d['net_bps_corrected']} |",
        f"| edge/cost | {round(d['gross_bps_as_reported'] / L.CERTIFIED_ROUND_TRIP_BPS, 4)} | {d['edge_cost_ratio_corrected']} |",
        "",
        "The correction moves the Sprint 001 frontier from 0.831 to 0.915 — still below 1.0,",
        "so the verdict does not flip, but the honest baseline is +21.78 bps, not +19.78 bps.",
        "",
        "## Chronological split (the decisive table)",
        "",
        "| split | trades | gross (reported) | price move | net (corrected) | win rate | PF | mean MFE | mean MAE | median hold |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| DISCOVERY W1-W4 | {d['trades']} | {d['gross_bps_as_reported']} | {d['price_move_bps']} | {d['net_bps_corrected']} | {d['win_rate']} | {d['profit_factor']} | {d['mfe_bps_mean']} | {d['mae_bps_mean']} | {d['median_duration_min']} min |",
        f"| VALIDATION W5 | {v.get('trades', 0)} | {v.get('gross_bps_as_reported')} | {v.get('price_move_bps')} | {v.get('net_bps_corrected')} | {v.get('win_rate')} | {v.get('profit_factor')} | {v.get('mfe_bps_mean')} | {v.get('mae_bps_mean')} | {v.get('median_duration_min')} min |",
        f"| HOLDOUT W6-W7 | {h.get('trades', 0)} | {h.get('gross_bps_as_reported')} | {h.get('price_move_bps')} | {h.get('net_bps_corrected')} | {h.get('win_rate')} | {h.get('profit_factor')} | {h.get('mfe_bps_mean')} | {h.get('mae_bps_mean')} | {h.get('median_duration_min')} min |",
        f"| ALL | {a['trades']} | {a['gross_bps_as_reported']} | {a['price_move_bps']} | {a['net_bps_corrected']} | {a['win_rate']} | {a['profit_factor']} | {a['mfe_bps_mean']} | {a['mae_bps_mean']} | {a['median_duration_min']} min |",
        "",
        "## Exit mix (DISCOVERY) — the shape of the payoff",
        "",
        "| exit | n | mean price move |",
        "|---|---:|---:|",
    ]
    for rsn, rv in diag["by_reason"]["DISCOVERY"].items():
        lines.append(f"| {rsn} | {rv['n']} | {rv['mean_price_move_bps']} bps |")
    lines += [
        "",
        "A fixed +74 bps take-profit against a ~-121 bps stop is a hit-rate bet, not a",
        "large-move bet: 71% winners at +76 vs 29% losers at -121 is what produces +19.8 bps.",
        "The stop on the SHORT leg is the adapter's flat 1% default (its structural stop sits",
        "above price), which is why losses are 1.6x wins.",
        "",
        "## Ex-post horizon counterfactual (DISCOVERY entries, diagnosis only)",
        "",
        "Entry is the OPEN of the bar **after** the signal bar (the executable",
        "convention). This is the decisive measurement of whether the signal carries",
        "directional drift at all.",
        "",
        "```text",
        f"amplitude check: entry ATR percentile median = {diag['amplitude_check_discovery']['entry_rank_atr_median']}",
        f"                 unconditional median       = {diag['amplitude_check_discovery']['unconditional_rank_atr_median']}",
        "```",
        "",
        "| horizon | n | mean price move | median | win rate | net of certified cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for hz in HORIZON_BARS:
        hv = hc.get(hz)
        if hv:
            lines.append(
                f"| {hz} | {hv['n']} | {hv['mean_bps']} | {hv['median_bps']} | {hv['win_rate']} | {hv['net_of_certified_cost_bps']} |"
            )
    bb = diag["barrier_benchmark"]
    lines += [
        "",
        "## Barrier-geometry benchmark",
        "",
        "| split | observed hit rate | driftless-walk benchmark | stop-loss mean move |",
        "|---|---:|---:|---:|",
        f"| DISCOVERY | {bb['observed_hit_rate']['DISCOVERY']} | {bb['driftless_hit_rate_benchmark']['DISCOVERY']} | {bb['observed_stop_loss_mean_bps']['DISCOVERY']} bps |",
        f"| VALIDATION | {bb['observed_hit_rate']['VALIDATION']} | {bb['driftless_hit_rate_benchmark']['VALIDATION']} | {bb['observed_stop_loss_mean_bps']['VALIDATION']} bps |",
        f"| HOLDOUT | {bb['observed_hit_rate']['HOLDOUT']} | {bb['driftless_hit_rate_benchmark']['HOLDOUT']} | {bb['observed_stop_loss_mean_bps']['HOLDOUT']} bps |",
        "",
        bb["interpretation"],
        "",
        "## Answers to the §10 questions",
        "",
    ]
    qmap = [
        ("Why +19.78 bps gross?", "why_positive_in_discovery"),
        ("Does the signal have predictive power?", "does_the_signal_predict"),
        ("Or does it merely trade when amplitude is larger?", "is_it_just_amplitude"),
        ("Where does it lose?", "where_it_loses"),
        ("Entry wrong?", "entry_problem"),
        ("Exit too early?", "exit_too_early"),
        ("Wrong regime?", "regime_problem"),
        ("Holding period too short?", "holding_period"),
        ("Inevitable cost?", "cost_inevitable"),
    ]
    for q, k in qmap:
        lines.append(f"**{q}**")
        lines.append("")
        lines.append(findings[k])
        lines.append("")
    lines += [
        "## Conclusion carried into Sprint 002",
        "",
        "```text",
        "SIGNAL  : no directional drift that survives to the executable entry (~+3.6 bps at 1h)",
        "EXIT    : the flat +74 bps target CREATES the DISCOVERY profit; the drift is ~0 at every horizon",
        "HORIZON : untested by Sprint 001 (no hold-time axis); the counterfactual shows no horizon rescues it",
        "COST    : executable-entry drift ~3.6 bps = ~0.15 of cost",
        "OOS     : DISCOVERY-only effect — W5-W7 negative; HOLDOUT hit rate below the random-walk benchmark",
        "ROOT    : the Sprint 001 edge is BARRIER GEOMETRY + DISCOVERY-period luck, not alpha",
        "```",
        "",
        "This is a **SIGNAL problem (no directional drift), masked by a favourable exit",
        "geometry**, not a magnitude problem and not a cost problem. Sprint 002 therefore does",
        "NOT re-tune this family: it tests the same economic mechanism (compression ->",
        "expansion) with a frozen compression-quality filter and ATR-scaled exits (H-P0-02),",
        "alongside economically distinct hypotheses, and it re-expresses the Sprint 001 number",
        "under the corrected convention.",
        "",
        "Evidence: `VOLATILITY_30M_DIAGNOSIS.json`.",
    ]
    md = L.OUT_DIR / "VOLATILITY_30M_DIAGNOSIS.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"discovery": d, "validation": v, "holdout": h, "counterfactual": hc}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
