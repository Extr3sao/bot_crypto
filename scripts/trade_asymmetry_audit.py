"""Trade asymmetry audit for PAPER-BURN-IN-V2 (read-only, spec §8).

Joins:
  - state.json closed_trades (authoritative economic record)
  - events.jsonl paper.session portfolio snapshots (per-position
    stop_loss_pct / take_profit_pct / notional at open time)

Produces per-trade planned vs actual R-multiples and classifies the
TP/SL asymmetry origin (A designed / B config / C strategy / D accounting
bug / E fill-slippage artifact).
"""

from __future__ import annotations

import json
import os
from statistics import mean
from typing import Any

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(HERE, "reports", "paper-burn-in", "PAPER-BURN-IN-V2")
STATE = os.path.join(RUN, "state.json")
EVENTS = os.path.join(RUN, "events.jsonl")
COMMISSION_BPS = 5.0


def _portfolio_params(events_path: str) -> dict[tuple[str, float], dict[str, float]]:
    """Map (symbol, opened_at) -> {sl_pct, tp_pct, notional} from snapshots."""
    out: dict[tuple[str, float], dict[str, float]] = {}
    with open(events_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            pf = ev.get("portfolio") or {}
            if not isinstance(pf, dict):
                continue
            for sym, pos in pf.items():
                if not isinstance(pos, dict):
                    continue
                key = (sym, float(pos.get("opened_at", 0.0)))
                out[key] = {
                    "sl_pct": float(pos.get("stop_loss_pct", 0.0) or 0.0),
                    "tp_pct": float(pos.get("take_profit_pct", 0.0) or 0.0),
                    "notional": float(pos.get("notional_usdt", 0.0) or 0.0),
                }
    return out


def main() -> None:
    with open(STATE, encoding="utf-8") as fh:
        state = json.load(fh)
    closed: list[dict[str, Any]] = state.get("closed_trades", [])
    params = _portfolio_params(EVENTS)

    rows: list[dict[str, Any]] = []
    unmatched = 0
    for t in closed:
        key = (t["symbol"], float(t["opened_at"]))
        p = params.get(key)
        qty, entry, exitp = float(t["quantity"]), float(t["entry_price"]), float(t["exit_price"])
        notional = qty * entry
        fees = notional * COMMISSION_BPS / 1e4 + qty * exitp * COMMISSION_BPS / 1e4
        gross = float(t["pnl"]) + fees
        ret_pct = gross / notional * 100.0 if notional else 0.0
        planned_risk = planned_reward = None
        if p and p["notional"] > 0:
            planned_risk = p["notional"] * p["sl_pct"] / 100.0
            planned_reward = p["notional"] * p["tp_pct"] / 100.0
            planned_rr = planned_reward / planned_risk if planned_risk else None
            actual_rr = gross / planned_risk if planned_risk else None
            stop_gap_pct = ret_pct + p["sl_pct"] if gross < 0 else None
            src = "matched"
        else:
            planned_risk = planned_reward = planned_rr = actual_rr = stop_gap_pct = None
            src = "UNMATCHED"
            unmatched += 1
        rows.append({
            "trade_id": f'{t["symbol"]}-{t["opened_at"]:.0f}',
            "asset": t["symbol"],
            "strategy": t.get("strategy_name"),
            "entry_price": entry,
            "exit_price": exitp,
            "notional": round(notional, 2),
            "planned_risk_usdt": round(planned_risk, 2) if planned_risk else None,
            "planned_reward_usdt": round(planned_reward, 2) if planned_reward else None,
            "planned_RR": round(planned_rr, 3) if planned_rr else None,
            "actual_gross_pnl": round(gross, 2),
            "fees": round(fees, 2),
            "net_pnl": round(float(t["pnl"]), 2),
            "actual_return_pct": round(ret_pct, 3),
            "actual_R": round(actual_rr, 3) if actual_rr else None,
            "stop_slippage_pct_beyond_stop": round(stop_gap_pct, 3) if stop_gap_pct else None,
            "exit_reason": t.get("exit_reason"),
            "duration_min": round((float(t["closed_at"]) - float(t["opened_at"])) / 60.0, 1),
            "source": src,
        })

    stops = [r for r in rows if r["exit_reason"] == "stop_loss" and r["source"] == "matched"]
    tps = [r for r in rows if r["exit_reason"] == "take_profit" and r["source"] == "matched"]
    summary = {
        "total_closed": len(rows),
        "unmatched_to_snapshot": unmatched,
        "planned_RR_obs": sorted({r["planned_RR"] for r in rows if r["planned_RR"] is not None}),
        "stop_exits": {
            "count": len(stops),
            "avg_actual_R": round(mean([r["actual_R"] for r in stops if r["actual_R"] is not None]), 3) if stops else None,
            "max_stop_slippage_pct": max([r["stop_slippage_pct_beyond_stop"] or 0.0 for r in stops], default=None),
            "avg_stop_slippage_pct": round(mean([r["stop_slippage_pct_beyond_stop"] or 0.0 for r in stops]), 3) if stops else None,
        },
        "tp_exits": {
            "count": len(tps),
            "avg_actual_R": round(mean([r["actual_R"] for r in tps if r["actual_R"] is not None]), 3) if tps else None,
        },
        "worst_5_losses": sorted(rows, key=lambda r: r["net_pnl"])[:5],
        "classification": None,
    }
    out = os.path.join(RUN, "TRADE_ASYMMETRY.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "trades": rows}, fh, indent=2)
    print(json.dumps(summary, indent=2)[:2400])
    print("... -> TRADE_ASYMMETRY.json")


if __name__ == "__main__":
    main()
