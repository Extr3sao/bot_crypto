"""AGGTRADES histogram experiments — Filter 0..5 with COST_MODEL_V3 (§PHASE 5).

Read-only, offline, deterministic. Consumes the per-minute tick aggregates
produced by ``scripts/fetch_aggtrades_microstructure.py`` and the
PRE-REGISTERED rules frozen in ``docs/AGGTRADES_HYPOTHESES_V1.md``.

Window discipline: the day sample is DISCONTINUOUS, so every rolling window is
computed strictly WITHIN one calendar day. No statistic ever crosses a day
boundary, which also removes the most common source of accidental look-ahead.

Outputs:
  reports/microstructure-v1/AGGTRADES_INFO_CONTENT.json   (Filter 0)
  reports/microstructure-v1/AGGTRADES_RESULTS.json        (Filter 1..5)

No network, no credentials, no execution. ZERO_COST is never used.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Sequence
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from trading_bot.research.microstructure.cost_model_v3 import (
    VENUE_SPECS,
    cost_model_v3_all_in,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "reports", "microstructure-v1", "aggtrades"))
OUT = os.path.abspath(os.path.join(HERE, "..", "reports", "microstructure-v1"))

ASSETS = ["BTC", "ETH", "SOL"]
MINUTE_MS = 60_000
BAR_MINUTES = 5
BARS_PER_DAY = 24 * 60 // BAR_MINUTES  # 288
HORIZONS = [1, 5, 15, 30, 60]
ROLLING_WINDOW = 20

SPLIT_OF_DAY_PREFIX = {
    "2026-03": "DEV",
    "2026-04": "DEV",
    "2026-05": "DEV",
    "2026-06": "DEV",
    "2026-07": "VAL",
    "2026-08": "VAL",
    "2026-09": "OOS",
}

# PRE-REGISTERED cost models (admission + venue-context only).


def _admission_cost() -> Any:
    return cost_model_v3_all_in(
        VENUE_SPECS["BINANCE_SPOT_STANDARD_TAKER"],
        size_usd=1_000.0,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type="market",
        exit_order_type="market",
    )


def _context_cost() -> Any:
    return cost_model_v3_all_in(
        VENUE_SPECS["MEXC_SPOT_TAKER"],
        size_usd=1_000.0,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type="market",
        exit_order_type="market",
    )


# ---------------------------------------------------------------------------
# loading / bars
# ---------------------------------------------------------------------------


def _load_minutes(symbol: str, day: str) -> list[dict[str, Any]] | None:
    path = os.path.join(DATA, f"AGG_{symbol}USDT_{day}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        obj: dict[str, Any] = json.load(fh)
    rows: list[dict[str, Any]] = obj["rows"]
    return rows


def _bars_from_minutes(rows: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """Group minute rows into aligned 5-minute bars.

    Only complete 5-minute groups are emitted, so the last incomplete group of a
    (possibly truncated) day is dropped rather than partially aggregated.
    """
    by_minute: dict[int, dict[str, Any]] = {int(r["minute_ms"]): r for r in rows}
    day_start = min(by_minute) if by_minute else 0
    bars: list[dict[str, Any]] = []
    for b in range(BARS_PER_DAY):
        bucket: list[dict[str, Any]] = []
        for k in range(BAR_MINUTES):
            m = day_start + (b * BAR_MINUTES + k) * MINUTE_MS
            row = by_minute.get(m)
            if row is None:
                bucket = []
                break
            bucket.append(row)
        if not bucket:
            continue
        g: dict[str, Any] = {
            "day": day,
            "symbol": None,
            "open_time": day_start + b * BAR_MINUTES * MINUTE_MS,
            "n_trades": 0,
            "buy_vol": 0.0,
            "sell_vol": 0.0,
            "buy_count": 0,
            "sell_count": 0,
            "sum_qty_sq": 0.0,
            "large_buy_vol": 0.0,
            "large_sell_vol": 0.0,
            "buy_quote": 0.0,
            "sell_quote": 0.0,
            "first_price": None,
            "last_price": None,
            "high": None,
            "low": None,
            "max_trade_qty": 0.0,
            "min_interarrival_ms": None,
        }
        for r in bucket:
            g["n_trades"] += int(r["n_trades"])
            g["buy_vol"] += float(r["buy_vol"])
            g["sell_vol"] += float(r["sell_vol"])
            g["buy_count"] += int(r["buy_count"])
            g["sell_count"] += int(r["sell_count"])
            g["sum_qty_sq"] += float(r["sum_qty_sq"])
            g["large_buy_vol"] += float(r["large_buy_vol"])
            g["large_sell_vol"] += float(r["large_sell_vol"])
            g["buy_quote"] += float(r["buy_quote"])
            g["sell_quote"] += float(r["sell_quote"])
            g["max_trade_qty"] = max(g["max_trade_qty"], float(r["max_trade_qty"]))
            if g["first_price"] is None:
                g["first_price"] = r["first_price"]
            g["last_price"] = r["last_price"]
            hi = r["high"]
            lo = r["low"]
            if hi is not None:
                g["high"] = hi if g["high"] is None else max(g["high"], hi)
            if lo is not None:
                g["low"] = lo if g["low"] is None else min(g["low"], lo)
            mia = r["min_interarrival_ms"]
            if mia is not None:
                g["min_interarrival_ms"] = (
                    mia if g["min_interarrival_ms"] is None else min(g["min_interarrival_ms"], mia)
                )
        total_vol = g["buy_vol"] + g["sell_vol"]
        g["total_vol"] = total_vol
        g["vwap"] = (g["buy_quote"] + g["sell_quote"]) / total_vol if total_vol > 0 else None
        g["available_at"] = g["open_time"] + BAR_MINUTES * MINUTE_MS + 1
        bars.append(g)
    return bars


# ---------------------------------------------------------------------------
# features (all rolling stats are WITHIN a single day)
# ---------------------------------------------------------------------------


def _rolling(series: list[float | None], window: int, fn: Any) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(series)):
        if i + 1 < window:
            out.append(None)
            continue
        w = [v for v in series[i + 1 - window : i + 1] if v is not None]
        out.append(fn(w) if len(w) >= 2 else None)
    return out


def _median(w: list[float]) -> float:
    s = sorted(w)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _zscore(series: Sequence[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(series)):
        if i + 1 < window:
            out.append(None)
            continue
        w = [v for v in series[i + 1 - window : i + 1] if v is not None]
        cur = series[i]
        if len(w) < 2 or cur is None:
            out.append(None)
            continue
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / len(w)
        sd = math.sqrt(var)
        out.append(0.0 if sd == 0 else (cur - mu) / sd)
    return out


def compute_features(bars: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    n = len(bars)

    def imbal(a: float, b: float) -> float | None:
        t = a + b
        return (a - b) / t if t > 0 else None

    f1 = [imbal(b["buy_vol"], b["sell_vol"]) for b in bars]
    f2 = [imbal(float(b["buy_count"]), float(b["sell_count"])) for b in bars]
    f3 = [imbal(b["large_buy_vol"], b["large_sell_vol"]) for b in bars]
    ntr = [float(b["n_trades"]) for b in bars]
    f4 = _zscore(ntr, ROLLING_WINDOW)
    mia = [float(b["min_interarrival_ms"]) if b["min_interarrival_ms"] is not None else None for b in bars]
    med = _rolling(mia, ROLLING_WINDOW, _median)
    f5: list[float | None] = []
    for i in range(n):
        cur, base = mia[i], med[i]
        if cur is not None and base is not None and base != 0.0:
            f5.append(cur / base)
        else:
            f5.append(None)
    absf1 = [abs(v) if v is not None else None for v in f1]
    f6 = _zscore(absf1, ROLLING_WINDOW)
    f7: list[float | None] = []
    for b in bars:
        vwap = b["vwap"]
        last = b["last_price"]
        if vwap and vwap > 0 and last:
            f7.append((last / vwap - 1.0) * 10_000.0)
        else:
            f7.append(None)
    ret_mom: list[float | None] = []
    for i in range(n):
        if i < 12 or not bars[i]["last_price"] or not bars[i - 12]["last_price"]:
            ret_mom.append(None)
        else:
            ret_mom.append((bars[i]["last_price"] / bars[i - 12]["last_price"] - 1.0) * 10_000.0)
    return {
        "F1_signed_flow_imbalance": f1,
        "F2_trade_imbalance": f2,
        "F3_large_trade_imbalance": f3,
        "F4_trade_intensity_z": f4,
        "F5_interarrival_accel": f5,
        "F6_abs_flow_z": f6,
        "F7_vwap_dislocation_bps": f7,
        "ret_mom_bps": ret_mom,
    }


def forward_returns(bars: list[dict[str, Any]]) -> dict[int, list[float | None]]:
    closes = [b["last_price"] for b in bars]
    n = len(closes)
    out: dict[int, list[float | None]] = {}
    for h in HORIZONS:
        series: list[float | None] = []
        for i in range(n):
            j = i + h
            if j >= n or not closes[i] or not closes[j] or closes[i] <= 0:
                series.append(None)
            else:
                series.append((closes[j] / closes[i] - 1.0) * 10_000.0)
        out[h] = series
    return out


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def trade_stats(pnl: list[float]) -> dict[str, Any]:
    if not pnl:
        return {"n": 0}
    n = len(pnl)
    mean = sum(pnl) / n
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    gross_pos = sum(wins)
    gross_neg = abs(sum(losses))
    var = sum((p - mean) ** 2 for p in pnl) / n if n > 1 else 0.0
    sd = math.sqrt(var)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnl:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "n": n,
        "mean_bps": round(mean, 4),
        "total_bps": round(sum(pnl), 2),
        "win_rate": round(len(wins) / n, 4),
        "pf": round(gross_pos / gross_neg, 4) if gross_neg > 0 else None,
        "sharpe_per_trade": round(mean / sd, 4) if sd > 0 else None,
        "max_dd_bps": round(max_dd, 2),
    }


def spearman(xs: list[float], ys: list[float]) -> float:
    def rank(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, idx in enumerate(order):
            r[idx] = float(pos)
        return r

    if len(xs) < 3:
        return 0.0
    rx, ry = rank(xs), rank(ys)
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(rx)))
    dx = math.sqrt(sum((v - mx) ** 2 for v in rx))
    dy = math.sqrt(sum((v - my) ** 2 for v in ry))
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0


# ---------------------------------------------------------------------------
# main experiment
# ---------------------------------------------------------------------------


def build_dataset() -> dict[str, Any]:
    with open(os.path.join(DATA, "MANIFEST_AGGTRADES.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    days_by_split: dict[str, list[str]] = {}
    for f in manifest["files"]:
        days_by_split.setdefault(f["split"], [])
        if f["day"] not in days_by_split[f["split"]]:
            days_by_split[f["split"]].append(f["day"])
    for k in days_by_split:
        days_by_split[k] = sorted(days_by_split[k])

    bars_by_asset_day: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for asset in ASSETS:
        sym = f"{asset}USDT"
        for days in days_by_split.values():
            for day in days:
                rows = _load_minutes(asset, day)
                if rows is None:
                    continue
                bars = _bars_from_minutes(rows, day)
                for b in bars:
                    b["symbol"] = sym
                bars_by_asset_day[(asset, day)] = bars
    return {"manifest": manifest, "days_by_split": days_by_split, "bars": bars_by_asset_day}


def run_information_content(ds: dict[str, Any]) -> dict[str, Any]:
    """Filter 0 — quintile monotonicity of forward return by feature (DEV only)."""
    out: dict[str, Any] = {}
    for asset in ASSETS:
        for day in ds["days_by_split"].get("DEV", []):
            bars = ds["bars"].get((asset, day))
            if not bars:
                continue
            feats = compute_features(bars)
            fwd = forward_returns(bars)
            for fname, series in feats.items():
                h = 5
                xs: list[float] = []
                ys: list[float] = []
                for i in range(len(series)):
                    x, y = series[i], fwd[h][i]
                    if x is not None and y is not None:
                        xs.append(x)
                        ys.append(y)
                if len(xs) < 30:
                    continue
                rec = out.setdefault(fname, {"quintiles": [], "observations": 0, "rhos": []})
                rec["observations"] += len(xs)
                rec["rhos"].append(round(spearman(xs, ys), 4))
    for rec in out.values():
        rec["mean_rho_dev"] = round(sum(rec["rhos"]) / len(rec["rhos"]), 4) if rec["rhos"] else 0.0
        rec["informative"] = abs(rec["mean_rho_dev"]) >= 0.01
    return out


def _sign(x: float | None) -> float:
    if x is None or x == 0.0:
        return 0.0
    return 1.0 if x > 0 else -1.0


def signal_series(name: str, feats: dict[str, list[float | None]], btc_f1: list[float | None] | None) -> list[float]:
    n = len(feats["F1_signed_flow_imbalance"])
    sig = [0.0] * n
    if name == "A-01":
        for i in range(n):
            v = feats["F1_signed_flow_imbalance"][i]
            sig[i] = _sign(v) if v is not None and abs(v) >= 0.3 else 0.0
    elif name == "A-02":
        for i in range(n):
            v = feats["F3_large_trade_imbalance"][i]
            sig[i] = _sign(v) if v is not None and abs(v) >= 0.3 else 0.0
    elif name == "A-03":
        for i in range(n):
            f1 = feats["F1_signed_flow_imbalance"][i]
            rm = feats["ret_mom_bps"][i]
            if f1 is None or rm is None:
                continue
            if rm > 0 and f1 >= 0.3:
                sig[i] = 1.0
            elif rm < 0 and f1 <= -0.3:
                sig[i] = -1.0
    elif name == "A-04":
        for i in range(n):
            acc = feats["F5_interarrival_accel"][i]
            f1 = feats["F1_signed_flow_imbalance"][i]
            if acc is not None and f1 is not None and acc < 0.5:
                sig[i] = -_sign(f1)
    elif name == "A-05":
        for i in range(n):
            v = feats["F7_vwap_dislocation_bps"][i]
            if v is None:
                continue
            if v > 20.0:
                sig[i] = -1.0
            elif v < -20.0:
                sig[i] = 1.0
    elif name == "A-06":
        if btc_f1 is None:
            return sig
        for i in range(n):
            if i == 0:
                continue
            prev = btc_f1[i - 1]
            sig[i] = _sign(prev)
    return sig


def run_signal(
    name: str,
    ds: dict[str, Any],
    horizon: int,
    dir_from_dev: bool,
) -> dict[str, Any]:
    admission = _admission_cost()
    context = _context_cost()
    cost_bps = admission.round_trip_bps

    by_split_pnl: dict[str, list[float]] = {"DEV": [], "VAL": [], "OOS": []}
    by_asset_dev: dict[str, list[float]] = {a: [] for a in ASSETS}
    raw_by_split: dict[str, list[float]] = {"DEV": [], "VAL": [], "OOS": []}

    # --- pass 1: collect DEV signal/label pairs to freeze the direction ----
    dev_pairs: list[tuple[float, float]] = []
    for asset in ASSETS:
        for day in ds["days_by_split"].get("DEV", []):
            bars = ds["bars"].get((asset, day))
            if not bars:
                continue
            feats = compute_features(bars)
            fwd = forward_returns(bars)
            btc = _btc_flow_for_day(ds, day)
            sig = signal_series(name, feats, btc)
            for i in range(len(bars)):
                r = fwd[horizon][i]
                if sig[i] != 0.0 and r is not None:
                    dev_pairs.append((sig[i], r))
    direction = 1.0
    if dir_from_dev and dev_pairs:
        total = sum(s * r for s, r in dev_pairs)
        direction = 1.0 if total >= 0 else -1.0

    # --- pass 2: evaluate the frozen rule on every split ------------------
    for split, days in ds["days_by_split"].items():
        for asset in ASSETS:
            for day in days:
                bars = ds["bars"].get((asset, day))
                if not bars:
                    continue
                feats = compute_features(bars)
                fwd = forward_returns(bars)
                btc = _btc_flow_for_day(ds, day)
                sig = signal_series(name, feats, btc)
                for i in range(len(bars)):
                    r = fwd[horizon][i]
                    if sig[i] == 0.0 or r is None:
                        continue
                    gross = direction * sig[i] * r
                    raw_by_split[split].append(gross)
                    by_split_pnl[split].append(gross - cost_bps)
                    if split == "DEV":
                        by_asset_dev[asset].append(gross - cost_bps)

    stats = {k: trade_stats(v) for k, v in by_split_pnl.items()}
    all_pnl = by_split_pnl["DEV"] + by_split_pnl["VAL"] + by_split_pnl["OOS"]
    overall = trade_stats(all_pnl)
    gross_stats = {k: trade_stats(v) for k, v in raw_by_split.items()}

    gross_mean = gross_stats["DEV"].get("mean_bps", 0.0)
    net_mean = stats["DEV"].get("mean_bps", 0.0)

    classification, reason = _classify(name, stats, gross_stats, overall, cost_bps)

    # Descriptive only — never used to promote anything. A gross expectancy that
    # changes SIGN between DEV and a later split is the classic way an unstable
    # edge gets promoted by choosing the evaluation period after the fact, so it
    # is reported explicitly instead of being left for the reader to notice.
    gross_sign = {
        s: (0 if gross_stats[s].get("n", 0) == 0 else (1 if gross_stats[s].get("mean_bps", 0.0) > 0 else -1))
        for s in ("DEV", "VAL", "OOS")
    }
    nonzero = [v for v in gross_sign.values() if v != 0]
    sign_flip = len(set(nonzero)) > 1

    return {
        "gross_sign_by_split": gross_sign,
        "sign_flip_across_splits": sign_flip,
        "candidate_id": name,
        "horizon_bars": horizon,
        "horizon_minutes": horizon * BAR_MINUTES,
        "direction_frozen_from_dev": direction if dir_from_dev else "pre_registered",
        "cost_model": "COST_MODEL_V3/BINANCE_SPOT_STANDARD_TAKER",
        "cost_bps": round(cost_bps, 4),
        "context_cost_mexc_bps": round(context.round_trip_bps, 4),
        "overall": overall,
        "splits_net": stats,
        "splits_gross": gross_stats,
        "gross_mean_bps": round(gross_mean, 4),
        "net_mean_bps": round(net_mean, 4),
        "asset_stability_dev_net_mean_bps": {
            a: (round(sum(v) / len(v), 4) if v else None) for a, v in by_asset_dev.items()
        },
        "classification": classification,
        "classification_reason": reason,
        "filters": {
            "filter1_gross_positive_dev": gross_mean > 0,
            "filter2_cost_survival": net_mean > 0,
            "filter3_all_splits_positive": all(
                stats[s].get("mean_bps", 0.0) > 0 for s in ("DEV", "VAL", "OOS")
            ),
            "filter4_stress_1p25x": (gross_mean - cost_bps * 1.25) > 0,
            "filter4_stress_1p5x": (gross_mean - cost_bps * 1.5) > 0,
        },
    }


def _btc_flow_for_day(ds: dict[str, Any], day: str) -> list[float | None] | None:
    bars = ds["bars"].get(("BTC", day))
    if not bars:
        return None
    return compute_features(bars)["F1_signed_flow_imbalance"]


def _classify(
    name: str,
    stats: dict[str, dict[str, Any]],
    gross: dict[str, dict[str, Any]],
    overall: dict[str, Any],
    cost_bps: float,
) -> tuple[str, str]:
    if overall.get("n", 0) < 100:
        return "INSUFFICIENT_DATA", f"only {overall.get('n', 0)} trades"
    g = gross["DEV"].get("mean_bps", 0.0)
    if g <= 0.0:
        return "NO_GROSS_EDGE", f"gross DEV expectancy {g:.4f} bps <= 0"
    n = stats["DEV"].get("mean_bps", 0.0)
    if n <= 0.0:
        return "COST_KILLED", f"gross {g:.4f} < cost {cost_bps:.4f} bps"
    if not all(stats[s].get("mean_bps", 0.0) > 0 for s in ("DEV", "VAL", "OOS")):
        return "OOS_FAILED", "at least one split has non-positive net expectancy"
    if not (g - cost_bps * 1.25) > 0:
        return "COST_KILLED", "does not survive 1.25x cost stress"
    return "RESEARCH_CANDIDATE", "survived all pre-registered filters; requires verification"


HYPOTHESES = [
    ("A-01", 5, True),
    ("A-02", 5, True),
    ("A-03", 5, True),
    ("A-04", 5, False),
    ("A-05", 5, False),
    ("A-06", 1, True),
]


def main() -> None:
    ds = build_dataset()
    info = run_information_content(ds)
    results = [run_signal(name, ds, h, d) for name, h, d in HYPOTHESES]

    admission = _admission_cost()
    context = _context_cost()
    payload = {
        "generated_by": "scripts/aggtrades_experiments.py",
        "hypotheses_doc": "docs/AGGTRADES_HYPOTHESES_V1.md",
        "dataset": {
            "manifest": "reports/microstructure-v1/aggtrades/MANIFEST_AGGTRADES.json",
            "files": ds["manifest"]["total_files"],
            "minute_rows": ds["manifest"]["total_minute_rows"],
            "days_per_split": {k: len(v) for k, v in ds["days_by_split"].items()},
            "bars_per_day": BARS_PER_DAY,
            "rolling_window": ROLLING_WINDOW,
            "rolling_scope": "within-day only (discontinuous sample)",
        },
        "cost_model": {
            "admission_scenario": "BINANCE_SPOT_STANDARD_TAKER",
            "admission_rt_cost_bps": round(admission.round_trip_bps, 4),
            "context_scenario": "MEXC_SPOT_TAKER",
            "context_rt_cost_bps": round(context.round_trip_bps, 4),
        },
        "results": results,
    }

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "AGGTRADES_INFO_CONTENT.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(info, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(OUT, "AGGTRADES_RESULTS.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    print(f"admission RT cost = {admission.round_trip_bps:.3f} bps (BINANCE_SPOT_STANDARD_TAKER)")
    print(f"context   RT cost = {context.round_trip_bps:.3f} bps (MEXC_SPOT_TAKER)")
    for r in results:
        print(
            f"{r['candidate_id']:<6} h={r['horizon_bars']:<2} n={r['overall'].get('n', 0):>6} "
            f"gross={r['gross_mean_bps']:>8.3f} net={r['net_mean_bps']:>9.3f} "
            f"-> {r['classification']}"
        )
    print("-> AGGTRADES_INFO_CONTENT.json, AGGTRADES_RESULTS.json")


if __name__ == "__main__":
    main()
