"""Robustness neighborhood + regime attribution for the ema_crossover baseline.

Variants (§20 — neighborhood only, NO optimization):
  BASE        EMA 9/21, TP 0.75%, SL 1.5*ATR   (runtime contract)
  TP1.5       EMA 9/21, TP 1.50%, SL 1.5*ATR
  SL2.0       EMA 9/21, TP 0.75%, SL 2.0*ATR
  EMA12/26    EMA 12/26, TP 0.75%, SL 1.5*ATR

Regime attribution (§22): each window is classified by BTC 5m-window return
(up/down) and realized vol tercile -> PnL/trades aggregated per regime class.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from statistics import mean
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_baseline_backtest as bt  # type: ignore[import-not-found]

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")

VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("BASE_9_21_TP075_SL15", {}),
    ("TP150", {"TP_PCT": 1.5}),
    ("SL20_ATR", {"STOP_ATR_MULT": 2.0}),
    ("EMA_12_26", {"FAST": 12, "SLOW": 26}),
]


def run_variant(name: str, overrides: dict[str, Any]) -> dict[str, Any]:
    fast = int(overrides.get("FAST", 9))
    slow = int(overrides.get("SLOW", 21))
    old = (bt.TP_PCT, bt.STOP_ATR_MULT)
    bt.TP_PCT = float(overrides.get("TP_PCT", old[0]))
    bt.STOP_ATR_MULT = float(overrides.get("STOP_ATR_MULT", old[1]))
    all_trades: list[dict[str, Any]] = []
    per_window: dict[str, float] = {}
    equity = bt.START_EQUITY
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        base = os.path.basename(f)[:-5]
        sym, window = base.split("_", 1)
        with open(f, encoding="utf-8") as fh:
            bars = json.load(fh)
        res, equity = _simulate_with(fast, slow, sym.replace("USDT", "/USDT"), bars, equity)
        per_window[window] = per_window.get(window, 0.0) + sum(t["net"] for t in res["trades"])
        all_trades.extend(res["trades"])
    bt.TP_PCT, bt.STOP_ATR_MULT = old
    return {"totals": bt.aggregate(all_trades), "per_window_net": per_window,
            "final_equity": round(equity, 2)}


def _simulate_with(fast: int, slow: int, symbol: str, bars: list[dict[str, Any]], equity: float) -> tuple[dict[str, Any], float]:
    """Re-implements bt.simulate but with configurable EMA windows (minimal
    duplication; the rest of the contract is shared via bt constants)."""
    closes = [b["close"] for b in bars]
    e9 = bt.ema_series(closes, fast)
    e21 = bt.ema_series(closes, slow)
    rsi = bt.rsi_series(closes)
    atr = bt.atr_series(bars)
    eq = equity
    peak = eq
    max_dd_pct = 0.0
    trades: list[dict[str, Any]] = []
    pos: dict[str, Any] | None = None
    consec_losses = 0
    cooldown_until_day = -1
    trades_today = 0
    cur_day = -1
    daily_start = eq
    daily_locked = False

    def close_pos(price: float, ts: int, reason: str) -> None:
        nonlocal eq, pos, consec_losses
        pp = pos
        assert pp is not None
        exit_fill = price * (1 - bt.SLIP) if pp["side"] == "buy" else price * (1 + bt.SLIP)
        gross = (exit_fill - pp["entry"]) * pp["qty"] * (1 if pp["side"] == "buy" else -1)
        fees = pp["notional"] * bt.FEES + abs(exit_fill * pp["qty"]) * bt.FEES
        net = gross - fees
        eq += net
        consec_losses = 0 if net > 0 else consec_losses + 1
        trades.append({"asset": symbol, "window": bars[0]["ts"], "entry_ts": pp["entry_ts"],
                       "exit_ts": ts, "net": round(net, 4), "gross": round(gross, 4),
                       "fees": round(fees, 4), "reason": reason,
                       "duration_min": round((ts - pp["entry_ts"]) / 60_000, 1)})
        pos = None

    for i in range(bt.WARMUP, len(bars)):
        b = bars[i]
        ts, h, low_, cl = b["ts"], b["high"], b["low"], b["close"]
        d = bt.day_key(ts)
        if d != cur_day:
            cur_day, trades_today, daily_start, daily_locked = d, 0, eq, False
        if pos is not None:
            sl_hit = low_ <= pos["sl"] if pos["side"] == "buy" else h >= pos["sl"]
            tp_hit = h >= pos["tp"] if pos["side"] == "buy" else low_ <= pos["tp"]
            if (sl_hit and tp_hit) or sl_hit:
                close_pos(pos["sl"], ts, "stop_loss")
            elif tp_hit:
                close_pos(pos["tp"], ts, "take_profit")
        if not daily_locked and (daily_start - eq) / daily_start * 100.0 >= bt.DAILY_LOSS_PCT:
            daily_locked = True
        if pos is None and not daily_locked and trades_today < bt.MAX_TRADES_DAY and not (
            consec_losses >= bt.COOLDOWN_LOSSES and d <= cooldown_until_day
        ):
            f9, f21, fr, fa = e9[i], e21[i], rsi[i], atr[i]
            if f9 is not None and f21 is not None and fr is not None and fa and fa > 0:
                side = "buy" if (f9 > f21 and fr > 50) else ("sell" if (f9 < f21 and fr < 50) else None)
                if side is not None:
                    stop_dist = fa * bt.STOP_ATR_MULT
                    stop_dist_pct = stop_dist / cl * 100.0
                    notional = min(bt.MAX_NOTIONAL, max(bt.MIN_NOTIONAL, eq * (bt.RISK_PCT / 100.0) / (stop_dist_pct / 100.0)))
                    fill = cl * (1 + bt.SLIP) if side == "buy" else cl * (1 - bt.SLIP)
                    pos = {"side": side, "entry": fill, "qty": notional / fill, "notional": notional,
                           "sl": fill - stop_dist if side == "buy" else fill + stop_dist,
                           "tp": fill * (1 + bt.TP_PCT / 100.0) if side == "buy" else fill * (1 - bt.TP_PCT / 100.0),
                           "entry_ts": ts}
                    trades_today += 1
                    if consec_losses >= bt.COOLDOWN_LOSSES:
                        cooldown_until_day = d
        peak = max(peak, eq)
        max_dd_pct = max(max_dd_pct, (peak - eq) / peak * 100.0 if peak else 0.0)
    return {"trades": trades, "final_equity": eq, "max_dd_pct": max_dd_pct}, eq


def regime_attribution() -> dict[str, Any]:
    """Classify each window by BTC return/vol; aggregate trades per regime."""
    btc_files = {os.path.basename(f)[:-5].split("_", 1)[1]: f
                 for f in glob.glob(os.path.join(DATA, "BTCUSDT_*.json"))}
    with open(os.path.join(OUTDIR, "BASELINE_RESULTS.json"), encoding="utf-8") as fh:
        base = json.load(fh)
    regimes: dict[str, dict[str, Any]] = {}
    for window, f in sorted(btc_files.items()):
        with open(f, encoding="utf-8") as fh:
            bars = json.load(fh)
        ret = (bars[-1]["close"] / bars[0]["close"] - 1) * 100.0
        atr = [v for v in bt.atr_series(bars) if v is not None]
        vol = mean([a / b["close"] * 100.0 for a, b in zip(atr, bars[15:], strict=False)]) if atr else 0.0
        direction = "UP" if ret > 2 else ("DOWN" if ret < -2 else "RANGE")
        vol_class = "HIGHVOL" if vol > 0.25 else ("LOWVOL" if vol < 0.15 else "MIDVOL")
        # aggregate the three assets' trades for this window from per-window stats
        wins = base["per_window_asset"]
        wkeys = [k for k in wins if k.endswith(window)]
        net = sum(wins[k]["net"] for k in wkeys)
        trades = sum(wins[k]["trades"] for k in wkeys)
        key = f"{direction}_{vol_class}"
        r = regimes.setdefault(key, {"windows": [], "net": 0.0, "trades": 0})
        r["windows"].append(window)
        r["net"] = round(r["net"] + net, 2)
        r["trades"] += trades
        print(f"{window}: BTC ret={ret:+.1f}% vol={vol:.3f}% -> {key} | net={net:+.2f} trades={trades}")
    return regimes


def main() -> None:
    variants = {}
    for name, ov in VARIANTS:
        variants[name] = run_variant(name, ov)
        t = variants[name]["totals"]
        print(f"{name}: trades={t['trades']} net={t['net']} PF={t['profit_factor']} "
              f"WR={t['win_rate']} exit={t['exit_mix']}", flush=True)
    regimes = regime_attribution()
    out = {"variants": variants, "regimes": regimes}
    with open(os.path.join(OUTDIR, "ROBUSTNESS_VARIANTS.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print("-> ROBUSTNESS_VARIANTS.json")


if __name__ == "__main__":
    main()
