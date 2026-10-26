"""Discovery candidates D-02..D-04 (STRATEGY-DISCOVERY-V3).

DISCOVERY ONLY (§10): none of this is a runtime family yet. Signal
generators are self-contained but drive an execution loop whose mechanics
mirror multi_family_backtest.simulate_family (same costs, sizing, intrabar
SL/TP stop_first, cooldown, daily lock, 20/day cap). Kept separate from
simulate_family because the family engine is bound to runtime classes whose
published V1 results must not move; any divergence of execution mechanics
between the two engines is a parity risk to audit before any promotion.

Pre-registered specs live in docs/STRATEGY_DISCOVERY_V3.md (§1, D-02..D-04).
No parameter grids: one variant per hypothesis (§23). Parameters below were
fixed in the pre-registration BEFORE any result was observed.

Candidates:
  D-02 vol_z_rev : SHORT/LONG after |z|>=2.0 adverse excursion, z = 20-bar
                   return / (ATR14 * sqrt(20)), TP 1.0 ATR, SL 1.5 ATR,
                   time-stop 24 bars, 15m only.
  D-03 squeeze_breakout : 12-bar range breakout with close confirmation
                   after compression (bar range < mean range/2), TP 1.5x
                   broken range, SL opposite side of range, 30m only.
  D-04 rel_momo : cross-sectional 24h momentum leader long (BTC/ETH/SOL),
                   z_rel > +1.0 gate, TP 1.0%, SL 1.0%, time-stop 24h, 1h.
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
from statistics import mean
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")

FEES = 0.0005
SLIP = 0.0001
RISK_PCT = 0.25
MIN_NOTIONAL, MAX_NOTIONAL = 25.0, 500.0
MAX_TRADES_DAY = 20
COOLDOWN_LOSSES = 3
DAILY_LOSS_PCT = 1.0
START_EQUITY = 10_000.0
START_EVAL = 60  # warmup bars before any evaluation (parity with V1 engine)

SCENARIOS: dict[str, tuple[float, float]] = {"BASE": (1.0, 1.0), "2X_COST": (2.0, 1.0),
                                             "STRESSED_SLIPPAGE": (1.0, 5.0), "ZERO_COST": (0.0, 0.0)}

# ----------------------------- signal generators ----------------------------


class VolZRev:
    """D-02: volatility-normalized short-term reversal (15m)."""

    candidate_id = "D-02_vol_z_rev"
    tf = "15m"
    min_bars = 35  # 20 lookback + ATR14 warmup
    time_stop_bars = 24

    def signal(self, bars: list[dict[str, Any]]) -> str | None:
        if len(bars) < self.min_bars + 1:
            return None
        w = bars[-21:]  # 20 returns
        ret = w[-1]["close"] / w[0]["close"] - 1.0
        trs = []
        for i in range(len(bars) - 14, len(bars)):
            trs.append(max(bars[i]["high"] - bars[i]["low"],
                           abs(bars[i]["high"] - bars[i - 1]["close"]),
                           abs(bars[i]["low"] - bars[i - 1]["close"])))
        atr = mean(trs)
        if atr <= 0:
            return None
        z = ret / (atr / bars[-1]["close"] * math.sqrt(20.0))
        if z <= -2.0:
            return "buy"
        if z >= 2.0:
            return "sell"
        return None


class SqueezeBreakout:
    """D-03: compression -> confirmed range breakout (30m)."""

    candidate_id = "D-03_squeeze_breakout"
    tf = "30m"
    min_bars = 40  # 12-bar range + 12-bar mean-range reference
    time_stop_bars = 36  # pre-registered: 18h on 30m bars
    range_len = 12

    def signal(self, bars: list[dict[str, Any]]) -> str | None:
        if len(bars) < self.min_bars + 1:
            return None
        rng = bars[-self.range_len:]
        hi = max(b["high"] for b in rng)
        lo = min(b["low"] for b in rng)
        prev_rng = bars[-self.range_len - 1: -1]
        widths = [b["high"] - b["low"] for b in prev_rng]
        if not widths or mean(widths) <= 0:
            return None
        cur = bars[-1]
        compressed = (cur["high"] - cur["low"]) < mean(widths) / 2.0
        # compression measured on the bar BEFORE the break bar (bars[-1] closed out of range)
        pre = bars[-2]
        if compressed and cur["close"] > hi and pre["close"] <= hi:
            return "buy"
        if compressed and cur["close"] < lo and pre["close"] >= lo:
            return "sell"
        return None


class RelMomentum:
    """D-04: cross-sectional 24h momentum leader, long-only (1h, 3 assets)."""

    candidate_id = "D-04_rel_momo"
    tf = "1h"
    min_bars = 60  # 24h lookback + buffer

    def __init__(self) -> None:
        self._prev_leader: str | None = None

    def leader(self, series: dict[str, list[dict[str, Any]]]) -> str | None:
        rets: dict[str, float] = {}
        vols: dict[str, float] = {}
        for sym, bars in series.items():
            if len(bars) < 25:
                return None
            w = bars[-25:]
            r = w[-1]["close"] / w[0]["close"] - 1.0
            rets[sym] = r
            vols[sym] = math.sqrt(sum((w[i]["close"] / w[i - 1]["close"] - 1.0) ** 2
                                      for i in range(1, len(w))) / 24.0) or 1e-12
        ranked = sorted(rets, key=lambda s: rets[s] / vols[s], reverse=True)
        lead = ranked[0]
        vals = sorted(rets[s] / vols[s] for s in rets)
        mid = vals[1]
        z_rel = (rets[lead] / vols[lead] - mid)
        if z_rel > 1.0:
            self._prev_leader = lead
            return lead
        self._prev_leader = None
        return None


# ------------------------------- execution ----------------------------------


def day_key(ts_ms: int) -> int:
    return ts_ms // 86_400_000


def atr14(bars: list[dict[str, Any]]) -> float:
    trs = [max(bars[i]["high"] - bars[i]["low"],
               abs(bars[i]["high"] - bars[i - 1]["close"]),
               abs(bars[i]["low"] - bars[i - 1]["close"])) for i in range(1, len(bars))]
    return mean(trs) if trs else 0.0


def simulate_single(candidate: VolZRev | SqueezeBreakout, symbol: str, bars: list[dict[str, Any]],
                    fees: float, slip: float, tf_min: float) -> dict[str, Any]:
    eq = START_EQUITY
    peak = eq
    max_dd = 0.0
    trades: list[dict[str, Any]] = []
    pos: dict[str, Any] | None = None
    consec = 0
    cooldown_day = -1
    trades_today = 0
    cur_day = -1
    daily_start = eq
    locked = False

    def close(price: float, ts: int, reason: str) -> None:
        nonlocal eq, pos, consec
        pp = pos
        assert pp is not None
        fill = price * (1 - slip) if pp["side"] == "buy" else price * (1 + slip)
        gross = (fill - pp["entry"]) * pp["qty"] * (1 if pp["side"] == "buy" else -1)
        f = pp["notional"] * fees + abs(fill * pp["qty"]) * fees
        net = gross - f
        eq += net
        consec = 0 if net > 0 else consec + 1
        trades.append({"window": bars[0]["ts"], "asset": symbol, "net": round(net, 4),
                       "gross": round(gross, 4), "fees": round(f, 4), "reason": reason,
                       "side": pp["side"], "mfe_pct": round(pp["mfe"] / pp["entry"] * 100.0, 4),
                       "mae_pct": round(pp["mae"] / pp["entry"] * 100.0, 4),
                       "entry_ts": pp["entry_ts"], "exit_ts": ts,
                       "duration_min": round((ts - pp["entry_ts"]) / 60_000, 1)})
        pos = None

    for i in range(START_EVAL, len(bars)):
        b = bars[i]
        ts, h, low_, cl = b["ts"], b["high"], b["low"], b["close"]
        d = day_key(ts)
        if d != cur_day:
            cur_day, trades_today, daily_start, locked = d, 0, eq, False
        if pos is not None:
            pos["age"] += 1
            if pos["side"] == "buy":
                pos["mfe"] = max(pos["mfe"], h - pos["entry"])
                pos["mae"] = max(pos["mae"], pos["entry"] - low_)
                sl_hit, tp_hit = low_ <= pos["sl"], h >= pos["tp"]
            else:
                pos["mfe"] = max(pos["mfe"], pos["entry"] - low_)
                pos["mae"] = max(pos["mae"], h - pos["entry"])
                sl_hit, tp_hit = h >= pos["sl"], low_ <= pos["tp"]
            if (sl_hit and tp_hit) or sl_hit:
                close(pos["sl"], ts, "stop_loss")
            elif tp_hit:
                close(pos["tp"], ts, "take_profit")
            elif pos["age"] >= candidate.time_stop_bars:
                close(cl, ts, "time_stop")
        if not locked and (daily_start - eq) / daily_start * 100.0 >= DAILY_LOSS_PCT:
            locked = True
        if pos is None and not locked and trades_today < MAX_TRADES_DAY \
                and not (consec >= COOLDOWN_LOSSES and d <= cooldown_day):
            side = candidate.signal(bars[: i + 1])
            if side is not None:
                entry_ref = cl
                atr = atr14(bars[max(0, i - 14): i + 1])
                if atr <= 0:
                    continue
                if candidate.candidate_id == "D-02_vol_z_rev":
                    tp_d, sl_d = 1.0 * atr, 1.5 * atr
                else:  # D-03: tp 1.5x broken range, sl opposite side
                    range_len = getattr(candidate, "range_len", 12)
                    rng = bars[max(0, i - range_len): i]
                    hi = max(x["high"] for x in rng)
                    lo = min(x["low"] for x in rng)
                    if side == "buy":
                        tp_d, sl_d = 1.5 * (hi - lo), max(entry_ref - lo, 1e-9)
                    else:
                        tp_d, sl_d = 1.5 * (hi - lo), max(hi - entry_ref, 1e-9)
                notional = min(MAX_NOTIONAL, max(MIN_NOTIONAL, eq * (RISK_PCT / 100.0) / (sl_d / entry_ref)))
                fill = cl * (1 + slip) if side == "buy" else cl * (1 - slip)
                pos = {"side": side, "entry": fill, "qty": notional / fill, "notional": notional,
                       "sl": fill - sl_d if side == "buy" else fill + sl_d,
                       "tp": fill + tp_d if side == "buy" else fill - tp_d,
                       "mfe": 0.0, "mae": 0.0, "age": 0, "entry_ts": ts}
                trades_today += 1
                if consec >= COOLDOWN_LOSSES:
                    cooldown_day = d
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100.0 if peak else 0.0)
    return {"trades": trades, "final_equity": round(eq, 2), "max_dd_pct": round(max_dd, 4)}


def simulate_rel_momo(candidate: RelMomentum, files_by_window: dict[str, dict[str, list[dict[str, Any]]]],
                      fees: float, slip: float, tf_min: float) -> dict[str, Any]:
    eq = START_EQUITY
    peak = eq
    max_dd = 0.0
    trades: list[dict[str, Any]] = []
    consec = 0
    cooldown_day = -1
    trades_today = 0
    cur_day = -1
    daily_start = eq
    locked = False
    window_names = sorted(files_by_window)
    for wname in window_names:
        series = files_by_window[wname]
        leader_seen: str | None = None
        entry: dict[str, Any] | None = None
        age = 0
        timestamps = sorted(series[next(iter(series))], key=lambda b: b["ts"])
        n_bars = len(series[next(iter(series))])
        for i in range(max(START_EVAL, candidate.min_bars), n_bars):
            d = day_key(timestamps[i]["ts"])
            if d != cur_day:
                cur_day, trades_today, daily_start, locked = d, 0, eq, False
            if entry is not None:
                age += 1
                b = series[leader_seen][i]  # type: ignore[index]
                h, low_, cl = b["high"], b["low"], b["close"]
                entry["mfe"] = max(entry["mfe"], h - entry["entry"])
                entry["mae"] = max(entry["mae"], entry["entry"] - low_)
                sl_hit, tp_hit = low_ <= entry["sl"], h >= entry["tp"]
                if (sl_hit and tp_hit) or sl_hit:
                    px = entry["sl"]
                elif tp_hit:
                    px = entry["tp"]
                elif age >= 24:
                    px = cl
                else:
                    px = None
                if px is not None:
                    fill = px * (1 - slip)
                    gross = (fill - entry["entry"]) * entry["qty"]
                    f = entry["notional"] * fees + abs(fill * entry["qty"]) * fees
                    net = gross - f
                    eq += net
                    consec = 0 if net > 0 else consec + 1
                    trades.append({"window": wname, "asset": leader_seen, "net": round(net, 4),
                                   "gross": round(gross, 4), "fees": round(f, 4),
                                   "reason": "stop_loss" if sl_hit and not tp_hit else
                                             ("take_profit" if tp_hit else "time_stop"),
                                   "side": "buy", "mfe_pct": round(entry["mfe"] / entry["entry"] * 100.0, 4),
                                   "mae_pct": round(entry["mae"] / entry["entry"] * 100.0, 4),
                                   "entry_ts": entry["entry_ts"], "exit_ts": timestamps[i]["ts"],
                                   "duration_min": round((timestamps[i]["ts"] - entry["entry_ts"]) / 60_000, 1)})
                    entry = None
            if not locked and (daily_start - eq) / daily_start * 100.0 >= DAILY_LOSS_PCT:
                locked = True
            if entry is None and not locked and trades_today < MAX_TRADES_DAY \
                    and not (consec >= COOLDOWN_LOSSES and d <= cooldown_day):
                sub = {s: bars[: i + 1] for s, bars in series.items()}
                lead = candidate.leader(sub)
                if lead is not None and lead != leader_seen:
                    cl = series[lead][i]["close"]
                    notional = min(MAX_NOTIONAL, max(MIN_NOTIONAL, eq * (RISK_PCT / 100.0) / 0.01))
                    fill = cl * (1 + slip)
                    entry = {"entry": fill, "qty": notional / fill, "notional": notional,
                             "sl": fill * 0.99, "tp": fill * 1.01, "mfe": 0.0, "mae": 0.0,
                             "entry_ts": series[lead][i]["ts"]}
                    leader_seen = lead
                    trades_today += 1
                    if consec >= COOLDOWN_LOSSES:
                        cooldown_day = d
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100.0 if peak else 0.0)
    return {"trades": trades, "final_equity": round(eq, 2), "max_dd_pct": round(max_dd, 4)}


def aggregate(trades: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    n = len(trades)
    return {"trades": n,
            "gross": round(sum(t["gross"] for t in trades), 2),
            "fees": round(sum(t["fees"] for t in trades), 2),
            "net": round(sum(nets), 2),
            "expectancy_gross": round(mean([t["gross"] for t in trades]), 4) if n else 0.0,
            "expectancy": round(mean(nets), 4) if n else 0.0,
            "avg_mfe_pct": round(mean([t["mfe_pct"] for t in trades]), 4) if n else 0.0,
            "avg_mae_pct": round(mean([t["mae_pct"] for t in trades]), 4) if n else 0.0,
            "avg_duration_min": round(mean([t["duration_min"] for t in trades]), 1) if n else 0.0,
            "win_rate": round(100.0 * len(wins) / n, 2) if n else 0.0,
            "profit_factor": round(gw / gl, 4) if gl else None,
            "max_dd_pct": None}


def main() -> None:
    tf_files: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for cand_tf in ("15m", "30m", "1h"):
        suffix = "" if cand_tf == "5m" else f"_5m_{cand_tf}"
        tf_files[cand_tf] = {}
        for f in sorted(glob.glob(os.path.join(DATA, f"*{suffix}.json"))):
            base = os.path.basename(f)[: -len(suffix) - 5] if suffix else os.path.basename(f)[:-5]
            sym, window = base.split("_", 1)
            tf_files[cand_tf].setdefault(window, []).append((sym, f))

    results: dict[str, Any] = {}
    dump_rows: list[dict[str, Any]] = []

    # D-02 (15m) and D-03 (30m): per-asset single-symbol simulators
    for cand_cls, tf in ((VolZRev, "15m"), (SqueezeBreakout, "30m")):
        cand = cand_cls()
        results[cand.candidate_id] = {}
        for sc, (cm, sm) in SCENARIOS.items():
            all_trades: list[dict[str, Any]] = []
            for window, entries in sorted(tf_files[tf].items()):
                for sym, f in entries:
                    with open(f, encoding="utf-8") as fh:
                        bars = json.load(fh)
                    res = simulate_single(cand, sym.replace("USDT", "/USDT"), bars, FEES * cm, SLIP * sm,
                                          {"15m": 15.0, "30m": 30.0}[tf])
                    for t in res["trades"]:
                        t["window"] = window
                    all_trades.extend(res["trades"])
            dev = [t for t in all_trades if str(t["window"]).startswith(("W1", "W2", "W3", "W4"))]
            val = [t for t in all_trades if str(t["window"]).startswith(("W5", "W6"))]
            oos = [t for t in all_trades if str(t["window"]).startswith("W7")]
            agg = aggregate(all_trades)
            agg["max_dd_pct"] = None
            results[cand.candidate_id][sc] = {"totals": agg, "DEV_W1_W4": aggregate(dev),
                                              "VAL_W5_W6": aggregate(val), "OOS_W7": aggregate(oos)}
            t = results[cand.candidate_id][sc]["totals"]
            print(f"{cand.candidate_id} [{sc}]: trades={t['trades']} gross={t['gross']} net={t['net']} "
                  f"PF={t['profit_factor']} WR={t['win_rate']} mfe={t['avg_mfe_pct']} mae={t['avg_mae_pct']}",
                  flush=True)
            if sc == "BASE":
                for tr in all_trades:
                    row = dict(tr)
                    row["scenario"] = sc
                    row["candidate"] = cand.candidate_id
                    dump_rows.append(row)

    # D-04 (1h): cross-sectional
    cand4 = RelMomentum()
    results[cand4.candidate_id] = {}
    for sc, (cm, sm) in SCENARIOS.items():
        series_by_window: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for window, entries in sorted(tf_files["1h"].items()):
            series_by_window[window] = {}
            for sym, f in entries:
                with open(f, encoding="utf-8") as fh:
                    series_by_window[window][sym] = json.load(fh)
        res = simulate_rel_momo(cand4, series_by_window, FEES * cm, SLIP * sm, 60.0)
        for t in res["trades"]:
            t["asset"] = str(t.get("asset"))
        dev = [t for t in res["trades"] if str(t["window"]).startswith(("W1", "W2", "W3", "W4"))]
        val = [t for t in res["trades"] if str(t["window"]).startswith(("W5", "W6"))]
        oos = [t for t in res["trades"] if str(t["window"]).startswith("W7")]
        results[cand4.candidate_id][sc] = {"totals": aggregate(res["trades"]),
                                           "DEV_W1_W4": aggregate(dev), "VAL_W5_W6": aggregate(val),
                                           "OOS_W7": aggregate(oos), "max_dd_pct": res["max_dd_pct"]}
        t = results[cand4.candidate_id][sc]["totals"]
        print(f"{cand4.candidate_id} [{sc}]: trades={t['trades']} gross={t['gross']} net={t['net']} "
              f"PF={t['profit_factor']} WR={t['win_rate']}", flush=True)
        if sc == "BASE":
            for tr in res["trades"]:
                row = dict(tr)
                row["scenario"] = sc
                row["candidate"] = cand4.candidate_id
                dump_rows.append(row)

    with open(os.path.join(OUTDIR, "DISCOVERY_CANDIDATES.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    if dump_rows:
        cols = ["scenario", "candidate", "window", "asset", "side", "entry_ts", "exit_ts",
                "duration_min", "reason", "mfe_pct", "mae_pct", "gross", "fees", "net"]
        with open(os.path.join(OUTDIR, "TRADES_DISCOVERY.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in dump_rows:
                w.writerow({k: r.get(k) for k in cols})
    print("-> DISCOVERY_CANDIDATES.json / TRADES_DISCOVERY.csv")


if __name__ == "__main__":
    main()
