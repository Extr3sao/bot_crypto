"""Multi-family strategy baseline (MULTI-STRATEGY-ENABLEMENT-V1).

PARITY (§13-14): evaluation drives the PRODUCTIVE family classes
(trading_bot.research.families.*) and each family's own
``_compute_indicators`` over a trailing 100-bar window — the same shape the
paper runtime feeds (fetch limit=100, PIT slice). No reimplementation of
signal logic anywhere.

Execution contract mirrors PaperBroker + RiskManager defaults:
  SL      : adapter semantic — |entry-stop|/entry if 0<stop<entry else 1.0%
            (runtime quirk preserved: SHORT structural stops sit ABOVE price
            -> adapter falls back to the flat 1% default)
  TP      : 0.75% (risk.yaml default_take_profit_pct)
  sizing  : 0.25% equity / SL%, clamp [25, 500]
  fees    : 5 bps/side, slippage 1 bp/side (BASE; 2X_COST; STRESSED=5x slip)
  exits   : intra-bar H/L, stop_first on ambiguity; opposite signal closes
            (PaperBroker.execute_signal semantics); same-side skipped
  risk    : cooldown after 3 consecutive losses; daily -1% lock; 20/day cap
"""

from __future__ import annotations

import glob
import json
import os
import sys
from statistics import mean
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from trading_bot.market_data.types import OHLCV
from trading_bot.research.families.breakout_family import BreakoutFamily
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily
from trading_bot.research.families.mean_reversion_family import MeanReversionFamily
from trading_bot.research.families.momentum_family import MomentumFamily
from trading_bot.research.families.trend_family import TrendFamily
from trading_bot.research.families.volatility_family import VolatilityFamily

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "reports", "strategy-baseline", "data")
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")
WINDOW = 100
START_EVAL = 60
FEES = 0.0005
SLIP = 0.0001
TP_PCT = 0.75
RISK_PCT = 0.25
MIN_NOTIONAL, MAX_NOTIONAL = 25.0, 500.0
MAX_TRADES_DAY = 20
COOLDOWN_LOSSES = 3
DAILY_LOSS_PCT = 1.0
START_EQUITY = 10_000.0

FAMILIES: dict[str, Any] = {
    "ema_crossover": EmaCrossoverFamily(),
    "momentum": MomentumFamily(),
    "breakout": BreakoutFamily(),
    "trend": TrendFamily(),
    "mean_reversion": MeanReversionFamily(),
    "volatility": VolatilityFamily(),
}
MIN_BARS = {"ema_crossover": 22, "momentum": 36, "breakout": 21,
            "trend": 56, "mean_reversion": 22, "volatility": 33}


def day_key(ts_ms: int) -> int:
    return ts_ms // 86_400_000


def to_ohlcv(bars: list[dict]) -> list[OHLCV]:
    return [OHLCV(symbol="X", timestamp=b["ts"], open=b["open"], high=b["high"],
                  low=b["low"], close=b["close"], volume=b["volume"]) for b in bars]


def simulate_family(fam_id: str, symbol: str, bars: list[dict], cost_mult: float,
                    slip_mult: float) -> dict[str, Any]:
    fam = FAMILIES[fam_id]
    min_bars = MIN_BARS[fam_id]
    fees = FEES * cost_mult
    slip = SLIP * slip_mult
    eq = START_EQUITY
    peak = eq
    max_dd = 0.0
    equity_curve: list[float] = []
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
        fill = price * (1 - slip) if pos["side"] == "buy" else price * (1 + slip)
        gross = (fill - pos["entry"]) * pos["qty"] * (1 if pos["side"] == "buy" else -1)
        f = pos["notional"] * fees + abs(fill * pos["qty"]) * fees
        net = gross - f
        eq += net
        consec = 0 if net > 0 else consec + 1
        trades.append({"window": bars[0]["ts"], "asset": symbol, "net": round(net, 4),
                       "gross": round(gross, 4), "fees": round(f, 4), "reason": reason,
                       "entry_ts": pos["entry_ts"], "exit_ts": ts,
                       "duration_min": round((ts - pos["entry_ts"]) / 60_000, 1)})
        pos = None

    for i in range(max(START_EVAL, min_bars + 1), len(bars)):
        b = bars[i]
        ts, o, h, l, cl = b["ts"], b["open"], b["high"], b["low"], b["close"]
        d = day_key(ts)
        if d != cur_day:
            cur_day, trades_today, daily_start, locked = d, 0, eq, False
        if pos is not None:
            sl_hit = l <= pos["sl"] if pos["side"] == "buy" else h >= pos["sl"]
            tp_hit = h >= pos["tp"] if pos["side"] == "buy" else l <= pos["tp"]
            if sl_hit and tp_hit:
                close(pos["sl"], ts, "stop_loss")
            elif sl_hit:
                close(pos["sl"], ts, "stop_loss")
            elif tp_hit:
                close(pos["tp"], ts, "take_profit")
        if not locked and (daily_start - eq) / daily_start * 100.0 >= DAILY_LOSS_PCT:
            locked = True
        pit = bars[max(0, i - WINDOW + 1):i + 1]
        if len(pit) >= min_bars:
            ohlcv = to_ohlcv(pit)
            try:
                indicators = fam._compute_indicators(ohlcv)  # type: ignore[attr-defined]
                alphas = fam.generate(ohlcv, indicators, None)
            except Exception:
                alphas = []
            alpha = alphas[-1] if alphas else None  # family emits <=1 per direction; last wins deterministically
            if alpha is not None and pos is None and not locked and trades_today < MAX_TRADES_DAY \
                    and not (consec >= COOLDOWN_LOSSES and d <= cooldown_day):
                direction = str(alpha.direction).upper()
                side = "buy" if direction == "LONG" else "sell"
                entry_ref = float(alpha.entry_reference)
                stop = float(getattr(alpha, "effective_stop", 0.0) or 0.0) or float(
                    getattr(alpha, "structural_stop", 0.0) or 0.0)
                if 0 < stop < entry_ref:
                    sl_pct = abs(entry_ref - stop) / entry_ref * 100.0
                else:
                    sl_pct = 1.0  # adapter default (SHORT structural stops sit above price)
                if sl_pct <= 0:
                    sl_pct = 1.0
                notional = min(MAX_NOTIONAL, max(MIN_NOTIONAL, eq * (RISK_PCT / 100.0) / (sl_pct / 100.0)))
                fill = cl * (1 + slip) if side == "buy" else cl * (1 - slip)
                stop_dist = fill * sl_pct / 100.0
                pos = {"side": side, "entry": fill, "qty": notional / fill, "notional": notional,
                       "sl": fill - stop_dist if side == "buy" else fill + stop_dist,
                       "tp": fill * (1 + TP_PCT / 100.0) if side == "buy" else fill * (1 - TP_PCT / 100.0),
                       "entry_ts": ts}
                trades_today += 1
                if consec >= COOLDOWN_LOSSES:
                    cooldown_day = d
            elif alpha is not None and pos is not None:
                side = "buy" if str(alpha.direction).upper() == "LONG" else "sell"
                if side != pos["side"]:
                    close(cl, ts, "signal_flip")  # PaperBroker opposite-close semantics
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100.0 if peak else 0.0)
        equity_curve.append(eq)

    # simple per-bar Sharpe/Sortino proxy (annualized on 5m bars)
    rets = [ (equity_curve[i] / equity_curve[i-1] - 1) for i in range(1, len(equity_curve)) if equity_curve[i-1] > 0 ]
    sharpe = sortino = None
    if len(rets) > 100:
        mu, sd = mean(rets), (sum((r - mean(rets))**2 for r in rets) / len(rets)) ** 0.5
        downside = (sum(min(r, 0.0)**2 for r in rets) / len(rets)) ** 0.5
        ann = (288 * 365) ** 0.5
        sharpe = round(mu / sd * ann, 3) if sd > 0 else None
        sortino = round(mu / downside * ann, 3) if downside > 0 else None
    return {"trades": trades, "final_equity": round(eq, 2), "max_dd_pct": round(max_dd, 4),
            "sharpe_proxy": sharpe, "sortino_proxy": sortino}


def aggregate(trades: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    out: dict[str, Any] = {
        "trades": len(trades),
        "gross": round(sum(t["gross"] for t in trades), 2),
        "fees": round(sum(t["fees"] for t in trades), 2),
        "net": round(sum(nets), 2),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(100.0 * len(wins) / len(nets), 2) if nets else 0.0,
        "avg_win": round(mean(wins), 4) if wins else 0.0,
        "avg_loss": round(mean(losses), 4) if losses else 0.0,
        "payoff": round(mean(wins) / abs(mean(losses)), 4) if wins and losses else None,
        "expectancy": round(mean(nets), 4) if nets else 0.0,
        "profit_factor": round(gw / gl, 4) if gl else None,
        "exit_mix": {"stop": sum(1 for t in trades if t["reason"] == "stop_loss"),
                     "tp": sum(1 for t in trades if t["reason"] == "take_profit"),
                     "flip": sum(1 for t in trades if t["reason"] == "signal_flip")},
    }
    return out


def main() -> None:
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    scenarios = {"BASE": (1.0, 1.0), "2X_COST": (2.0, 1.0), "STRESSED_SLIPPAGE": (1.0, 5.0)}
    results: dict[str, Any] = {}
    fam_filter = os.environ.get("FAM")
    fam_iter = {k: v for k, v in FAMILIES.items() if not fam_filter or k == fam_filter}
    for fam_id in fam_iter:
        results[fam_id] = {}
        for sc, (cm, sm) in scenarios.items():
            all_trades: list[dict[str, Any]] = []
            per_window: dict[str, dict[str, float]] = {}
            for f in files:
                base = os.path.basename(f)[:-5]
                sym, window = base.split("_", 1)
                bars = json.load(open(f, encoding="utf-8"))
                res = simulate_family(fam_id, sym.replace("USDT", "/USDT"), bars, cm, sm)
                for t in res["trades"]:
                    t["window"] = window
                all_trades.extend(res["trades"])
                w = per_window.setdefault(window, {"net": 0.0, "trades": 0})
                w["net"] = round(w["net"] + sum(t["net"] for t in res["trades"]), 2)
                w["trades"] += len(res["trades"])
            dev = [t for t in all_trades if t["window"].startswith(("W1", "W2", "W3", "W4"))]
            val = [t for t in all_trades if t["window"].startswith(("W5", "W6"))]
            oos = [t for t in all_trades if t["window"].startswith("W7")]
            results[fam_id][sc] = {
                "totals": aggregate(all_trades),
                "DEV_W1_W4": aggregate(dev),
                "VAL_W5_W6": aggregate(val),
                "OOS_W7": aggregate(oos),
                "per_window": per_window,
            }
            t = results[fam_id][sc]["totals"]
            print(f"{fam_id} [{sc}]: trades={t['trades']} net={t['net']} PF={t['profit_factor']} "
                  f"WR={t['win_rate']} exit={t['exit_mix']}", flush=True)
    os.makedirs(OUTDIR, exist_ok=True)
    suffix = f"_{fam_filter}" if fam_filter else ""
    with open(os.path.join(OUTDIR, f"MULTI_FAMILY_RESULTS{suffix}.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"-> MULTI_FAMILY_RESULTS{suffix}.json")


if __name__ == "__main__":
    main()
