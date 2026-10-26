"""MICROSTRUCTURE-EDGE-V1 experiments — Filter 0 + signal tests (§32-43).

Read-only, offline. Consumes the raw public data fetched by
``scripts/fetch_microstructure_data.py`` and the pre-registered rules in
``docs/MICROSTRUCTURE_HYPOTHESES_V1.md``. Produces:

  reports/microstructure-v1/INFORMATION_CONTENT.json   (Filter 0)
  reports/microstructure-v1/RESULTS.json               (signal tests)
  reports/microstructure-v1/RESULTS.md                 (human summary)

No network, no execution, no credentials. ZERO_COST never appears in
admission.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import sys
from statistics import mean
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from trading_bot.research.microstructure.cost_model import ADMISSION_COST_MODEL
from trading_bot.research.microstructure.features import (
    flow_features,
    forward_return_bps,
)
from trading_bot.research.microstructure.integrity import (
    check_ordering_and_duplicates,
    classify_gaps,
)
from trading_bot.research.microstructure.types import MicroBar

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "microstructure-v1", "data")
OUT = os.path.join(HERE, "..", "reports", "microstructure-v1")

ASSETS = ["BTC", "ETH", "SOL"]
HORIZONS = [1, 5, 15, 30, 60]
INTERVAL_MS = 5 * 60 * 1000

# Window boundaries (UTC), mirrors STRATEGY-DISCOVERY-V3 splits.
WINDOWS = [
    ("W1_2026-03", "2026-03", "DEV"),
    ("W2_2026-04", "2026-04", "DEV"),
    ("W3_2026-05", "2026-05", "DEV"),
    ("W4_2026-06", "2026-06", "DEV"),
    ("W5_2026-07", "2026-07", "VAL"),
    ("W6_2026-08", "2026-08", "VAL"),
    ("W7_2026-09", "2026-09", "OOS"),
]
RT_COST_BPS = ADMISSION_COST_MODEL.round_trip_bps()  # 23.5
COST_STRESS = {"BASE": 1.0, "1.5X": 1.5, "2X": 2.0}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_bars(symbol: str) -> list[MicroBar]:
    path = os.path.join(DATA, f"KLINES_{symbol}USDT_5m.json")
    raw = _load_json(path)
    bars: list[MicroBar] = []
    for r in raw:
        event_time = int(r[0])
        bars.append(
            MicroBar(
                event_time=event_time,
                available_at=int(r[6]) + 1,  # close time + 1
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
                quote_volume=float(r[7]),
                trades=int(r[8]),
                taker_buy_base=float(r[9]),
                taker_buy_quote=float(r[10]),
            )
        )
    check_ordering_and_duplicates([b.event_time for b in bars], f"{symbol}.event_time")
    return bars


def load_premium(symbol: str) -> list[tuple[int, int, float]]:
    """Return (available_at, event_time, premium_close)."""
    raw = _load_json(os.path.join(DATA, f"PREMIUM_{symbol}USDT_5m.json"))
    out: list[tuple[int, int, float]] = []
    for r in raw:
        event_time = int(r[0])
        close_time = int(r[6])
        out.append((close_time + 1, event_time, float(r[4])))  # close of premium kline
    out.sort()
    return out


def load_funding(symbol: str) -> list[tuple[int, int, float]]:
    raw = _load_json(os.path.join(DATA, f"FUNDING_{symbol}USDT.json"))
    out = [(int(r["fundingTime"]), int(r["fundingTime"]), float(r["fundingRate"])) for r in raw]
    out.sort()
    return out


def load_oi(symbol: str) -> list[tuple[int, int, float]]:
    raw = _load_json(os.path.join(DATA, f"OPENINTEREST_{symbol}USDT.json"))
    # dedupe by timestamp (backwards paging can overlap)
    seen: dict[int, float] = {}
    for r in raw:
        t = int(r["timestamp"])
        seen[t] = float(r["sumOpenInterest"])
    out = [(t + INTERVAL_MS, t, v) for t, v in sorted(seen.items())]
    return out


def asof_align(samples: list[tuple[int, int, float]], decision_time: int) -> float | None:
    """Latest sample value with available_at <= decision_time (PIT-safe)."""
    if not samples:
        return None
    times = [s[0] for s in samples]
    i = bisect.bisect_right(times, decision_time) - 1
    return samples[i][2] if i >= 0 else None


def align_series(samples: list[tuple[int, int, float]], decisions: list[int]) -> list[float | None]:
    times = [s[0] for s in samples]
    vals = [s[2] for s in samples]
    out: list[float | None] = []
    for d in decisions:
        i = bisect.bisect_right(times, d) - 1
        out.append(vals[i] if i >= 0 else None)
    return out


def window_of(event_time: int) -> tuple[str, str]:
    dt = _utc(event_time)
    ym = dt[:7]
    for wid, month, split in WINDOWS:
        if month == ym:
            return split, wid
    return ("UNKNOWN", "UNKNOWN")


def _utc(ms: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.UTC).strftime("%Y-%m-%dT%H:%M")


# --------------------------------------------------------------------------
# feature matrix
# --------------------------------------------------------------------------


def build_matrix(bars: list[MicroBar], symbol: str) -> dict[str, Any]:
    closes = [b.close for b in bars]
    decisions = [b.available_at for b in bars]

    ff = flow_features(bars, lookback=20)

    premium = align_series(load_premium(symbol), decisions)
    premium_z = _z_of(premium, 21)
    funding = align_series(load_funding(symbol), decisions)
    funding_z = _z_of(funding, 21)
    oi = align_series(load_oi(symbol), decisions)
    oi_change = _pct_change(oi)
    oi_change_z = _z_of(oi_change, 21)

    features: dict[str, list[float | None]] = {
        "flow_imbalance": ff["flow_imbalance"],
        "flow_imbalance_z": ff["flow_imbalance_z"],
        "avg_trade_size": ff["avg_trade_size"],
        "ret_mom_bps": ff["ret_mom_bps"],
        "realized_vol_bps": ff["realized_vol_bps"],
        "range_bps": ff["range_bps"],
        "funding_rate": funding,
        "funding_z": funding_z,
        "premium": premium,
        "premium_z": premium_z,
        "oi_change_z": oi_change_z,
    }
    anchors = {
        "flow_imbalance": 20,
        "flow_imbalance_z": 20,
        "funding_z": 21,
        "premium_z": 21,
        "oi_change_z": 21,
    }
    return {
        "bars": bars,
        "closes": closes,
        "decisions": decisions,
        "features": features,
        "anchors": anchors,
    }


def _z_of(series: list[float | None], window: int) -> list[float | None]:
    # rolling z over the non-None subsequence, then map back
    vals: list[float] = []
    idx: list[int] = []
    for i, v in enumerate(series):
        if v is not None:
            vals.append(v)
            idx.append(i)
    out: list[float | None] = [None] * len(series)
    for k, i in enumerate(idx):
        if k + 1 < window:
            continue
        w = vals[k + 1 - window : k + 1]
        mu = sum(w) / window
        sd = math.sqrt(sum((x - mu) ** 2 for x in w) / window)
        out[i] = (vals[k] - mu) / sd if sd > 0 else 0.0
    return out


def _pct_change(series: list[float | None]) -> list[float | None]:
    out: list[float | None] = []
    prev: float | None = None
    for v in series:
        if v is None or prev is None or prev == 0:
            out.append(None)
        else:
            out.append((v / prev - 1.0) * 10_000.0)
        if v is not None:
            prev = v
    return out


# --------------------------------------------------------------------------
# Filter 0 — information content seedlings
# --------------------------------------------------------------------------


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    for rank, i in enumerate(order):
        ranks[i] = float(rank)
    return ranks


def _spearman(x: list[float], y: list[float]) -> float:
    rx, ry = _rank(x), _rank(y)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0


def filter0(matrix: dict[str, Any]) -> dict[str, Any]:
    closes = matrix["closes"]
    features = matrix["features"]
    out: dict[str, Any] = {}
    n = len(closes)
    for fname, fseries in features.items():
        per_h: dict[str, Any] = {}
        for h in HORIZONS:
            xs: list[float] = []
            ys: list[float] = []
            for i in range(n):
                v = fseries[i]
                if v is None:
                    continue
                fr = forward_return_bps(closes, i, h)
                if fr is None:
                    continue
                xs.append(v)
                ys.append(fr)
            if len(xs) < 500:
                per_h[str(h)] = {"n": len(xs), "status": "INSUFFICIENT"}
                continue
            ic = _spearman(xs, ys)
            # deciles
            order = sorted(range(len(xs)), key=lambda i: xs[i])
            deciles = 10
            size = len(order) // deciles
            dmeans = []
            for d in range(deciles):
                sl = order[d * size : (d + 1) * size]
                dmeans.append(mean(ys[i] for i in sl))
            spread = dmeans[-1] - dmeans[0]
            steps = sum(1 for k in range(len(dmeans) - 1) if dmeans[k + 1] >= dmeans[k]) / (
                len(dmeans) - 1
            )
            monotone = steps if steps >= 0.5 else steps - 1.0  # signed
            per_h[str(h)] = {
                "n": len(xs),
                "ic_spearman": round(ic, 5),
                "decile_top_minus_bottom_bps": round(spread, 3),
                "top_decile_mean_bps": round(dmeans[-1], 3),
                "bottom_decile_mean_bps": round(dmeans[0], 3),
                "monotone_score": round(monotone, 3),
                "status": "NO_INFORMATION"
                if abs(ic) < 0.01 and abs(spread) < RT_COST_BPS
                else "HAS_SIGNAL",
            }
        out[fname] = per_h
    return out


# --------------------------------------------------------------------------
# signal simulation
# --------------------------------------------------------------------------


def simulate(
    positions: list[int],
    closes: list[float],
    decisions: list[int],
    horizon: int,
    cost_bps: float,
) -> dict[str, Any]:
    """Trade every non-zero position, hold ``horizon`` bars, one RT cost."""
    trades: list[dict[str, Any]] = []
    n = len(closes)
    for i in range(n):
        pos = positions[i]
        if pos == 0:
            continue
        fr = forward_return_bps(closes, i, horizon)
        if fr is None:
            continue
        gross = pos * fr
        net = gross - cost_bps
        split, _ = window_of(decisions[i])
        trades.append({"i": i, "gross": gross, "net": net, "split": split})
    return summarize(trades)


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "gross_bps": 0.0,
            "net_bps": 0.0,
            "pf": 0.0,
            "win_rate": 0.0,
            "max_dd_bps": 0.0,
            "splits": {},
        }
    gross = [t["gross"] for t in trades]
    net = [t["net"] for t in trades]
    wins = [x for x in net if x > 0]
    losses = [-x for x in net if x < 0]
    pf = (sum(wins) / sum(losses)) if losses else float("inf")
    # equity DD in bps
    eq = 0.0
    peak = 0.0
    dd = 0.0
    for x in net:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    splits: dict[str, Any] = {}
    for s in ("DEV", "VAL", "OOS"):
        st = [t for t in trades if t["split"] == s]
        if st:
            splits[s] = {
                "n": len(st),
                "gross_bps": round(mean(t["gross"] for t in st), 3),
                "net_bps": round(mean(t["net"] for t in st), 3),
            }
    return {
        "n": len(trades),
        "gross_bps": round(mean(gross), 3),
        "net_bps": round(mean(net), 3),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "pf": round(pf, 4) if pf != float("inf") else 999.0,
        "max_dd_bps": round(dd, 1),
        "splits": splits,
    }


def positions_from_threshold(series: list[float | None], thr: float, direction: int) -> list[int]:
    out = [0] * len(series)
    for i, v in enumerate(series):
        if v is None:
            continue
        if v > thr:
            out[i] = direction
        elif v < -thr:
            out[i] = -direction
    return out


def positions_breakout_flow(
    ret_mom: list[float | None], flow_z: list[float | None], thr: float
) -> list[int]:
    out = [0] * len(ret_mom)
    for i in range(len(ret_mom)):
        r, f = ret_mom[i], flow_z[i]
        if r is None or f is None:
            continue
        if r > 0 and f > thr:
            out[i] = 1
        elif r < 0 and f < -thr:
            out[i] = -1
    return out


def _dev_direction(pos: list[int], closes: list[float], decisions: list[int], h: int) -> int:
    """Determine signal sign from DEV only, then apply to all splits (§5)."""
    dev = simulate(pos, closes, decisions, h, 0.0)
    return 1 if dev["gross_bps"] >= 0 else -1


def run_signals(mats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    closes_all: list[float] = []
    dec_all: list[int] = []
    pos_long: list[int] = []
    pos_break: list[int] = []
    for _sym, m in mats.items():
        closes_all.extend(m["closes"])
        dec_all.extend(m["decisions"])
        fz = m["features"]["flow_imbalance_z"]
        rm = m["features"]["ret_mom_bps"]
        pos_long.extend(positions_from_threshold(fz, 2.0, 1))
        pos_break.extend(positions_breakout_flow(rm, fz, 1.0))
    # direction from DEV
    d1 = _dev_direction(pos_long, closes_all, dec_all, 5)
    d3 = _dev_direction(pos_break, closes_all, dec_all, 5)
    results["S-01_flow_imbalance_z"] = {
        "hypothesis": "M-01",
        "horizon_bars": 5,
        "dev_direction": "long_on_positive" if d1 == 1 else "short_on_positive",
        "scenarios": {
            k: simulate([p * d1 for p in pos_long], closes_all, dec_all, 5, RT_COST_BPS * mlt)
            for k, mlt in COST_STRESS.items()
        },
    }
    results["S-03_flow_breakout"] = {
        "hypothesis": "M-03",
        "horizon_bars": 5,
        "dev_direction": "long_on_positive" if d3 == 1 else "short_on_positive",
        "scenarios": {
            k: simulate([p * d3 for p in pos_break], closes_all, dec_all, 5, RT_COST_BPS * mlt)
            for k, mlt in COST_STRESS.items()
        },
    }
    # M-04 funding, M-05 premium: contrarian (pre-registered -1 on positive z)
    for sid, fname, h in (("S-04_funding", "funding_z", 30), ("S-05_premium", "premium_z", 15)):
        cl, dc, pos = [], [], []
        for _sym, m in mats.items():
            cl.extend(m["closes"])
            dc.extend(m["decisions"])
            pos.extend(positions_from_threshold(m["features"][fname], 2.0, -1))
        results[sid] = {
            "hypothesis": "M-04" if "funding" in fname else "M-05",
            "horizon_bars": h,
            "direction": "contrarian_pre_registered",
            "scenarios": {
                k: simulate(pos, cl, dc, h, RT_COST_BPS * mlt) for k, mlt in COST_STRESS.items()
            },
        }
    # M-06 OI+price, M-07 funding+OI+price (per asset; OI only recent 30d)
    oi_res: dict[str, Any] = {}
    for sym, m in mats.items():
        closes = m["closes"]
        dec = m["decisions"]
        rm = m["features"]["ret_mom_bps"]
        oz = m["features"]["oi_change_z"]
        fz = m["features"]["funding_z"]
        cells: dict[str, list[int]] = {
            "up_oi_up": [],
            "up_oi_dn": [],
            "dn_oi_up": [],
            "dn_oi_dn": [],
        }
        pos6 = [0] * len(closes)
        pos7 = [0] * len(closes)
        for i in range(len(closes)):
            if rm[i] is None or oz[i] is None:
                continue
            up = rm[i] > 0
            oiu = oz[i] > 0
            key = ("up" if up else "dn") + "_" + ("oi_up" if oiu else "oi_dn")
            cells[key].append(i)
            pos6[i] = 1 if up else -1  # M-06 cell membership; direction from DEV below
            if (
                fz[i] is not None
                and abs(fz[i]) > 2
                and (fz[i] > 0) == (not up)
                and (oz[i] > 0) == (not up)
            ):
                pos7[i] = -1 if fz[i] > 0 else 1
        oi_res[sym] = {
            "S-06_oi_price": {
                "cells": {k: len(v) for k, v in cells.items()},
                "scenarios": {
                    k: simulate(pos6, closes, dec, 15, RT_COST_BPS * mlt)
                    for k, mlt in COST_STRESS.items()
                },
            },
            "S-07_funding_oi_price": {
                "scenarios": {
                    k: simulate(pos7, closes, dec, 30, RT_COST_BPS * mlt)
                    for k, mlt in COST_STRESS.items()
                },
            },
        }
    results["S-06_S-07_oi"] = oi_res

    # M-08 BTC lead/lag: BTC previous-bar return sign -> ETH/SOL next bar
    if "BTC" in mats:
        btc = mats["BTC"]
        bt_ret: dict[int, float] = {}
        for i in range(1, len(btc["closes"])):
            bt_ret[btc["bars"][i].event_time] = (
                btc["closes"][i] / btc["closes"][i - 1] - 1.0
            ) * 10_000.0
        cl, dc, pos = [], [], []
        for sym in ("ETH", "SOL"):
            m = mats[sym]
            for i in range(1, len(m["closes"])):
                prev_t = m["bars"][i - 1].event_time
                r = bt_ret.get(prev_t)
                if r is None:
                    continue
                cl.append(m["closes"][i])
                dc.append(m["decisions"][i])
                pos.append(1 if r > 0 else (-1 if r < 0 else 0))
        results["S-08_btc_lead_lag"] = {
            "hypothesis": "M-08",
            "horizon_bars": 1,
            "direction": "momentum_prev_btc_bar",
            "scenarios": {
                k: simulate(pos, cl, dc, 1, RT_COST_BPS * mlt) for k, mlt in COST_STRESS.items()
            },
        }
    return results


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    mats: dict[str, dict[str, Any]] = {}
    gap_report: dict[str, Any] = {}
    for sym in ASSETS:
        bars = load_bars(sym)
        mats[sym] = build_matrix(bars, sym)
        g = classify_gaps([b.event_time for b in bars], INTERVAL_MS)
        gap_report[sym] = {"n": g.n, "gaps": g.gaps, "worst_gap_ms": g.worst_gap_ms}
        print(f"[{sym}] bars={len(bars)} gaps={g.gaps} worst={g.worst_gap_ms}ms", flush=True)

    print("Filter 0 ...", flush=True)
    f0: dict[str, Any] = {}
    for sym in ASSETS:
        f0[sym] = filter0(mats[sym])
    with open(os.path.join(OUT, "INFORMATION_CONTENT.json"), "w", encoding="utf-8") as fh:
        json.dump({"gaps": gap_report, "assets": f0}, fh, indent=2)

    print("Signal tests ...", flush=True)
    sig = run_signals(mats)
    with open(os.path.join(OUT, "RESULTS.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "cost_bps_rt": RT_COST_BPS,
                "cost_model": ADMISSION_COST_MODEL.name,
                "stress": COST_STRESS,
                "signals": sig,
            },
            fh,
            indent=2,
        )

    # console summary
    print(f"RT cost = {RT_COST_BPS} bps ({ADMISSION_COST_MODEL.name})", flush=True)
    for sid, r in sig.items():
        if sid == "S-06_S-07_oi":
            continue
        base = r["scenarios"]["BASE"]
        print(
            f"{sid:26s} n={base['n']:6d} gross={base['gross_bps']:8.3f} "
            f"net={base['net_bps']:8.3f} PF={base['pf']} splits={base['splits']}",
            flush=True,
        )
    print("-> INFORMATION_CONTENT.json, RESULTS.json", flush=True)


if __name__ == "__main__":
    main()
