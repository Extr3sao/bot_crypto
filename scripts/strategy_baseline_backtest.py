"""Strategy performance baseline — offline backtest of the ema_crossover
paper contract (PATH C, STRATEGY-PERFORMANCE-BASELINE-V1).

FIDELITY CONTRACT (mirrors src/trading_bot paper runtime):
  signal      : EMA9 > EMA21 and RSI14 > 50 -> LONG; inverse -> SHORT
                (evaluated on CLOSED 5m bars; one position per asset)
  stop        : 1.5 * ATR14 from entry (structural), intra-bar via H/L,
                ambiguous bar -> stop_first (conservative)
  take profit : +0.75% from entry (risk.yaml default_take_profit_pct)
  sizing      : 0.25% equity / stop_pct, clamped to [25, 500] USDT
  fees        : 5 bps per side; slippage 1 bp per side
  risk        : cooldown after 3 consecutive losses; daily loss limit -1%
                equity (stops new entries for the UTC day); max 20 trades/day

Trade loop mirrors the paper broker: position closes ONLY on SL/TP (or
opposite-signal close+flip), same as PaperBroker.execute_signal semantics.
"""

from __future__ import annotations

import glob
import json
import os
from statistics import mean
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")
WARMUP = 30  # bars of history before the first evaluated bar
FEES = 0.0005
SLIP = 0.0001
TP_PCT = 0.75
STOP_ATR_MULT = 1.5
RISK_PCT = 0.25
MIN_NOTIONAL, MAX_NOTIONAL = 25.0, 500.0
MAX_TRADES_DAY = 20
COOLDOWN_LOSSES = 3
DAILY_LOSS_PCT = 1.0
START_EQUITY = 10_000.0


def ema_series(vals: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if len(vals) < period:
        return out
    seed = sum(vals[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(vals)):
        prev = vals[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * ( period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def atr_series(c: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) < period + 1:
        return out
    trs = [
        max(
            c[i]["high"] - c[i]["low"],
            abs(c[i]["high"] - c[i - 1]["close"]),
            abs(c[i]["low"] - c[i - 1]["close"]),
        )
        for i in range(1, len(c))
    ]
    seed = sum(trs[:period]) / period
    out[period] = seed
    prev = seed
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i + 1] = prev
    return out


def day_key(ts_ms: int) -> int:
    return ts_ms // 86_400_000


def simulate(symbol: str, bars: list[dict[str, Any]], equity: float) -> tuple[dict[str, Any], float]:
    closes = [b["close"] for b in bars]
    e9 = ema_series(closes, 9)
    e21 = ema_series(closes, 21)
    rsi = rsi_series(closes)
    atr = atr_series(bars)
    eq = equity
    peak = eq
    max_dd_pct = 0.0
    trades: list[dict[str, Any]] = []
    pos = None  # {side, entry, sl, tp, qty, notional, entry_ts, stop_dist_pct}
    consec_losses = 0
    cooldown_until_day = -1
    trades_today = 0
    cur_day = -1
    daily_start = eq
    daily_locked = False
    daily_loss_veto_days = 0

    def close_pos(price: float, ts: int, reason: str) -> None:
        nonlocal eq, pos, consec_losses
        p = pos
        assert p is not None
        exit_fill = price * (1 - SLIP) if p["side"] == "buy" else price * (1 + SLIP)
        gross = (exit_fill - p["entry"]) * p["qty"] * (1 if p["side"] == "buy" else -1)
        fees = p["notional"] * FEES + abs(exit_fill * p["qty"]) * FEES
        net = gross - fees
        eq += net
        win = net > 0
        consec_losses = 0 if win else consec_losses + 1
        trades.append({
            "asset": symbol, "entry_ts": p["entry_ts"], "exit_ts": ts,
            "side": p["side"], "entry": p["entry"], "exit": exit_fill,
            "notional": p["notional"], "gross": round(gross, 4),
            "fees": round(fees, 4), "net": round(net, 4), "reason": reason,
            "duration_min": round((ts - p["entry_ts"]) / 60_000, 1),
            "ret_pct": round(gross / p["notional"] * 100.0, 4),
        })
        pos = None

    for i in range(WARMUP, len(bars)):
        b = bars[i]
        ts, _o, h, low_, cl = b["ts"], b["open"], b["high"], b["low"], b["close"]
        # ---- day rollover / risk reset
        d = day_key(ts)
        if d != cur_day:
            cur_day = d
            trades_today = 0
            daily_start = eq
            daily_locked = False
        # ---- intra-bar SL/TP on the OPEN position (uses current bar H/L)
        if pos is not None:
            sl_hit = low_ <= pos["sl"] if pos["side"] == "buy" else h >= pos["sl"]
            tp_hit = h >= pos["tp"] if pos["side"] == "buy" else low_ <= pos["tp"]
            if sl_hit and tp_hit:
                close_pos(pos["sl"], ts, "stop_loss")  # stop_first
            elif sl_hit:
                close_pos(pos["sl"], ts, "stop_loss")
            elif tp_hit:
                close_pos(pos["tp"], ts, "take_profit")
        # ---- daily loss gate on equity (realized)
        if not daily_locked and (daily_start - eq) / daily_start * 100.0 >= DAILY_LOSS_PCT:
            daily_locked = True
            daily_loss_veto_days += 1
        # ---- entries (closed-bar decision, next-bar fill semantics approximated
        #      by same-bar close like the paper runtime's snapshot close)
        if pos is None and not daily_locked and trades_today < MAX_TRADES_DAY and not (
            consec_losses >= COOLDOWN_LOSSES and d <= cooldown_until_day
        ):
            f9, f21, fr, fa = e9[i], e21[i], rsi[i], atr[i]
            if f9 is not None and f21 is not None and fr is not None and fa and fa > 0:
                side = None
                if f9 > f21 and fr > 50:
                    side = "buy"
                elif f9 < f21 and fr < 50:
                    side = "sell"
                if side is not None:
                    stop_dist = fa * STOP_ATR_MULT
                    stop_dist_pct = stop_dist / cl * 100.0
                    notional = min(MAX_NOTIONAL, max(MIN_NOTIONAL, eq * (RISK_PCT / 100.0) / (stop_dist_pct / 100.0)))
                    fill = cl * (1 + SLIP) if side == "buy" else cl * (1 - SLIP)
                    pos = {
                        "side": side, "entry": fill, "qty": notional / fill,
                        "notional": notional,
                        "sl": fill - stop_dist if side == "buy" else fill + stop_dist,
                        "tp": fill * (1 + TP_PCT / 100.0) if side == "buy" else fill * (1 - TP_PCT / 100.0),
                        "entry_ts": ts, "stop_dist_pct": stop_dist_pct,
                    }
                    trades_today += 1
                    if consec_losses >= COOLDOWN_LOSSES:
                        cooldown_until_day = d  # cooldown releases next day
        peak = max(peak, eq)
        max_dd_pct = max(max_dd_pct, (peak - eq) / peak * 100.0 if peak else 0.0)

    return {
        "symbol": symbol,
        "trades": trades,
        "final_equity": round(eq, 4),
        "max_dd_pct": round(max_dd_pct, 4),
        "daily_lock_days": daily_loss_veto_days,
    }, eq


def aggregate(trades: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gross = sum(t["gross"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    gw, gl = sum(wins), abs(sum(losses))
    return {
        "trades": len(trades),
        "gross": round(gross, 2), "fees": round(fees, 2), "net": round(sum(nets), 2),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(100.0 * len(wins) / len(nets), 2) if nets else 0.0,
        "avg_win": round(mean(wins), 4) if wins else 0.0,
        "avg_loss": round(mean(losses), 4) if losses else 0.0,
        "payoff": round(mean(wins) / abs(mean(losses)), 4) if wins and losses else None,
        "expectancy": round(mean(nets), 4) if nets else 0.0,
        "profit_factor": round(gw / gl, 4) if gl else None,
        "exit_mix": {
            "stop": sum(1 for t in trades if t["reason"] == "stop_loss"),
            "tp": sum(1 for t in trades if t["reason"] == "take_profit"),
        },
    }


def main() -> None:
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    if not files:
        raise SystemExit("no data files — run fetch_baseline_data.py first")
    results: dict[str, Any] = {}
    all_trades: list[dict[str, Any]] = []
    equity = START_EQUITY
    for f in files:
        base = os.path.basename(f)[:-5]
        sym, window = base.split("_", 1)
        with open(f, encoding="utf-8") as fh:
            bars = json.load(fh)
        if len(bars) < WARMUP + 100:
            continue
        res, equity = simulate(sym.replace("USDT", "/USDT"), bars, equity)
        agg = aggregate(res["trades"])
        results[base] = {"window": window, "bars": len(bars), **agg,
                         "max_dd_pct_window": res["max_dd_pct"],
                         "daily_lock_days": res["daily_lock_days"]}
        for t in res["trades"]:
            t["window"] = window
        all_trades.extend(res["trades"])

    n = len(all_trades)
    # DEVELOPMENT (W1-W4) / VALIDATION (W5-W6) / OOS (W7) by window order
    def split(
        tr: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        dev = [t for t in tr if t["window"].startswith(("W1", "W2", "W3", "W4"))]
        val = [t for t in tr if t["window"].startswith(("W5", "W6"))]
        out_sample = [t for t in tr if t["window"].startswith("W7")]
        return dev, val, out_sample

    dev, val, oos = split(all_trades)
    out = {
        "contract": {
            "ema": "9/21", "rsi": "14 (>50/<50)", "stop": "1.5*ATR14",
            "tp_pct": TP_PCT, "risk_pct": RISK_PCT, "notional_clamp": [MIN_NOTIONAL, MAX_NOTIONAL],
            "fees_bps": 5, "slippage_bps": 1, "cooldown_losses": COOLDOWN_LOSSES,
            "daily_loss_pct": DAILY_LOSS_PCT, "max_trades_day": MAX_TRADES_DAY,
            "both_hit_policy": "stop_first",
        },
        "per_window_asset": results,
        "totals": aggregate(all_trades),
        "splits": {
            "development_W1_W4": aggregate(dev),
            "validation_W5_W6": aggregate(val),
            "oos_W7": aggregate(oos),
        },
        "trade_count_total": n,
        "sample_class": (
            "TINY_SAMPLE" if n < 20 else "SMALL_SAMPLE" if n < 60 else
            "PRELIMINARY_SAMPLE" if n < 150 else "ANALYZABLE_SAMPLE"
        ),
    }
    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "BASELINE_RESULTS.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps({"totals": out["totals"], "splits": out["splits"],
                      "sample_class": out["sample_class"], "windows": len(results)}, indent=2))


if __name__ == "__main__":
    main()
