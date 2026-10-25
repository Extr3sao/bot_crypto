"""edge14r_economic_comparison — the economics of every arm, in one table.

The arms are not interchangeable and the table says so per row: a rule measured on
historical bars is an inference about the past, a replay through the runtime is a
connectivity measurement, and a runtime that admits nothing is not a strategy.

Every metric is computed here from the published per-trade records, and the columns that
cannot be computed honestly are left empty with the reason in the `notes` column rather
than filled with a plausible number.

    python scripts/edge14r_economic_comparison.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.economic_recovery import engine_parity as ep

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
FROZEN = OUT / "scratch" / "PAPER_REPLAY_BARS.jsonl"
PAPER = OUT / "PAPER_EXECUTION_EVIDENCE.json"

FEE_SCENARIOS = (0.0, 5.0, 10.0, 20.0)

COLUMNS = [
    "arm",
    "class",
    "instrument_timeframe",
    "window_start_utc",
    "window_end_utc",
    "trades_executed",
    "closed_trades",
    "calendar_days",
    "trades_per_day",
    "days_with_zero_trades",
    "gross_bps_total",
    "net_bps_total",
    "net_return_pct",
    "equity_multiple",
    "fees_bps_per_side",
    "fees_bps_per_round_trip",
    "spread_bps_per_round_trip",
    "slippage_bps_per_side",
    "expectancy_bps_per_trade",
    "per_trade_sharpe",
    "max_drawdown_bps",
    "profit_factor",
    "win_rate",
    "cost_sensitivity_0bps_net_bps",
    "cost_sensitivity_5bps_net_bps",
    "cost_sensitivity_10bps_net_bps",
    "cost_sensitivity_20bps_net_bps",
    "breakeven_fees_bps_per_side",
    "current_vs_proposed",
    "robustness",
    "oos_evidence",
    "statistical_limitations",
    "decision",
    "notes",
]


def _iso(ms: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _stats(net_bps: list[float]) -> dict[str, Any]:
    n = len(net_bps)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "sharpe": None,
            "profit_factor": None,
            "win_rate": None,
        }
    mean = sum(net_bps) / n
    var = sum((x - mean) ** 2 for x in net_bps) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    wins = [x for x in net_bps if x > 0]
    losses = [x for x in net_bps if x <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "n": n,
        "mean": mean,
        "sharpe": (mean / sd) if sd else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss else None,
        "win_rate": len(wins) / n,
    }


def _closed_bars() -> dict[str, list[ep.Bar]]:
    raw = ep.load_bars_jsonl(FROZEN)
    last = max(b.ts_ms for series in raw.values() for b in series)
    return {s: [b for b in series if b.ts_ms < last] for s, series in raw.items()}


def _days(bars: dict[str, list[ep.Bar]]) -> tuple[str, str, float, int]:
    import datetime

    first = min(b.ts_ms for s in bars.values() for b in s)
    last = max(b.ts_ms for s in bars.values() for b in s)
    days = {
        datetime.datetime.fromtimestamp(b.ts_ms / 1000, tz=datetime.UTC).date()
        for s in bars.values()
        for b in s
    }
    span = (last - first) / 86_400_000.0
    return _iso(first), _iso(last), span, len(days)


def main() -> int:
    bars = _closed_bars()
    start, end, span_days, _calendar_days = _days(bars)
    rows: list[dict[str, Any]] = []

    # --- this project's own simulator, on the rule the engines were given ---------
    ta_all: list[dict[str, Any]] = []
    for symbol in sorted(bars):
        for row in ep.ta_side_trades(bars[symbol], fees_bps_per_side=ep.DEFAULT_FEES_BPS_PER_SIDE):
            row["pair"] = symbol
            ta_all.append(row)
    ta_all.sort(key=lambda r: (r["pair"], r["entry_ts_ms"]))
    gross_bps = [r["gross_bps"] for r in ta_all]
    net_bps = [r["net_bps"] for r in ta_all]
    stats = _stats(net_bps)
    curve = ep.EquityCurve.from_net_bps(net_bps)

    import datetime

    trade_days = {
        datetime.datetime.fromtimestamp(r["entry_ts_ms"] / 1000, tz=datetime.UTC).date()
        for r in ta_all
    }
    all_days = {
        datetime.datetime.fromtimestamp(b.ts_ms / 1000, tz=datetime.UTC).date()
        for s in bars.values()
        for b in s
    }
    zero_days = len(all_days - trade_days)

    sensitivity = {}
    for fee in FEE_SCENARIOS:
        fee_rows: list[dict[str, Any]] = []
        for symbol in sorted(bars):
            fee_rows.extend(ep.ta_side_trades(bars[symbol], fees_bps_per_side=fee))
        sensitivity[fee] = round(sum(r["net_bps"] for r in fee_rows), 6)
    breakeven = None
    if gross_bps:
        breakeven = round(sum(gross_bps) / (2.0 * len(gross_bps)), 6)

    buy_hold = {}
    for symbol, series in sorted(bars.items()):
        first, last = series[0].close, series[-1].close
        buy_hold[symbol] = round((last / first - 1.0) * 10_000.0, 4)

    rows.append(
        {
            "arm": "NEUTRAL_MA_CROSS_1H (this project's simulator)",
            "class": "HISTORICAL_BACKTEST",
            "instrument_timeframe": "BTC/USDT+ETH/USDT 1h",
            "window_start_utc": start,
            "window_end_utc": end,
            "trades_executed": len(ta_all),
            "closed_trades": len(ta_all),
            "calendar_days": round(span_days, 4),
            "trades_per_day": round(len(ta_all) / span_days, 4) if span_days else None,
            "days_with_zero_trades": zero_days,
            "gross_bps_total": round(sum(gross_bps), 6),
            "net_bps_total": round(sum(net_bps), 6),
            "net_return_pct": round((curve.equity_multiple - 1.0) * 100.0, 6),
            "equity_multiple": round(curve.equity_multiple, 8),
            "fees_bps_per_side": ep.DEFAULT_FEES_BPS_PER_SIDE,
            "fees_bps_per_round_trip": 2 * ep.DEFAULT_FEES_BPS_PER_SIDE,
            "spread_bps_per_round_trip": 0.0,
            "slippage_bps_per_side": 0.0,
            "expectancy_bps_per_trade": round(stats["mean"], 6)
            if stats["mean"] is not None
            else None,
            "per_trade_sharpe": round(stats["sharpe"], 6) if stats["sharpe"] else None,
            "max_drawdown_bps": round(curve.max_drawdown_bps, 6),
            "profit_factor": round(stats["profit_factor"], 6) if stats["profit_factor"] else None,
            "win_rate": round(stats["win_rate"], 6) if stats["win_rate"] is not None else None,
            "cost_sensitivity_0bps_net_bps": sensitivity[0.0],
            "cost_sensitivity_5bps_net_bps": sensitivity[5.0],
            "cost_sensitivity_10bps_net_bps": sensitivity[10.0],
            "cost_sensitivity_20bps_net_bps": sensitivity[20.0],
            "breakeven_fees_bps_per_side": breakeven,
            "current_vs_proposed": (
                f"PROPOSED. CURRENT for this project is the runtime as it stands (no "
                f"admitted strategy, no trades, flat equity); this arm trades and loses "
                f"{abs(sensitivity[10.0] / 100.0):.2f}% net against that flat CURRENT"
            ),
            "robustness": (
                "no parameter is fitted, so there is no in-sample optimum to be fragile; "
                "the same rule on three independent engines reproduces the same loss, "
                "which is robustness of the measurement rather than of an edge"
            ),
            "oos_evidence": (
                "NONE: this window has been used for engine comparison, so it is not an "
                "out-of-sample slice for anything"
            ),
            "statistical_limitations": (
                f"{len(ta_all)} trades over {span_days:.1f} days in one regime; the "
                "per-trade Sharpe is not annualisable from that, and a negative expectancy "
                "means the sign, not the magnitude, is the finding"
            ),
            "decision": "REJECT",
            "notes": (
                "buy and hold over the same window: "
                + ", ".join(f"{k} {v / 100:.2f}%" for k, v in buy_hold.items())
                + ". Fees are a declared parity input, not a measured venue fee"
            ),
        }
    )

    # --- the same rule as seen by each external engine --------------------------
    for name, path, cls in (
        ("freqtrade", OUT / "BENCHMARK_PARITY_REPORT.json", "HISTORICAL_BACKTEST"),
        ("vnpy_ctastrategy", OUT / "BENCHMARK_PARITY_REPORT_VNPY.json", "HISTORICAL_BACKTEST"),
        ("jesse", OUT / "BENCHMARK_PARITY_REPORT_JESSE.json", "HISTORICAL_BACKTEST"),
    ):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        comparison = payload["comparison"]
        per_trade = comparison["detail"]["per_trade"]
        ext_net = [float(r["ext_net_bps"]) for r in per_trade]
        ext_gross = [float(r["ext_gross_bps"]) for r in per_trade]
        ext_stats = _stats(ext_net)
        gap = comparison["detail"]
        rows.append(
            {
                "arm": f"NEUTRAL_MA_CROSS_1H ({name})",
                "class": cls,
                "instrument_timeframe": "BTC/USDT+ETH/USDT 1h",
                "window_start_utc": start,
                "window_end_utc": end,
                "trades_executed": comparison["external_trades"],
                "closed_trades": comparison["external_trades"],
                "calendar_days": round(span_days, 4),
                "trades_per_day": round(comparison["external_trades"] / span_days, 4)
                if span_days
                else None,
                "days_with_zero_trades": zero_days,
                "gross_bps_total": round(sum(ext_gross), 6),
                "net_bps_total": comparison["external"]["net_bps_sum"],
                "net_return_pct": round(
                    (comparison["external"]["equity_multiple"] - 1.0) * 100.0, 6
                ),
                "equity_multiple": comparison["external"]["equity_multiple"],
                "fees_bps_per_side": payload["costs"]["fees_bps_per_side"],
                "fees_bps_per_round_trip": 2 * payload["costs"]["fees_bps_per_side"],
                "spread_bps_per_round_trip": 0.0,
                "slippage_bps_per_side": 0.0,
                "expectancy_bps_per_trade": round(ext_stats["mean"], 6)
                if ext_stats["mean"] is not None
                else None,
                "per_trade_sharpe": round(ext_stats["sharpe"], 6) if ext_stats["sharpe"] else None,
                "max_drawdown_bps": comparison["external"]["max_drawdown_bps"],
                "profit_factor": round(ext_stats["profit_factor"], 6)
                if ext_stats["profit_factor"]
                else None,
                "win_rate": round(ext_stats["win_rate"], 6)
                if ext_stats["win_rate"] is not None
                else None,
                "cost_sensitivity_0bps_net_bps": "",
                "cost_sensitivity_5bps_net_bps": "",
                "cost_sensitivity_10bps_net_bps": comparison["external"]["net_bps_sum"],
                "cost_sensitivity_20bps_net_bps": "",
                "breakeven_fees_bps_per_side": "",
                "current_vs_proposed": "PROPOSED — the same rule, measured by another engine",
                "robustness": f"independent implementation; matched residual {gap['max_abs_net_bps_diff_compounded']} bps",
                "oos_evidence": "NONE for this window; the arm is an accounting comparison",
                "statistical_limitations": (
                    f"{len(ext_net)} trades; agreement with this project's simulator is "
                    "evidence about the engines, not about the rule"
                ),
                "decision": "REJECT",
                "notes": (
                    "cost sensitivity is not recomputed here because the engine's fee is an "
                    "input to its own run; the parity report publishes both conventions "
                    "instead"
                ),
            }
        )

    # --- the runtime's own arms -------------------------------------------------
    paper = json.loads(PAPER.read_text(encoding="utf-8"))
    for arm in ("GATE_INTACT", "SANDBOX_ADMISSION"):
        block = paper["arms"][arm]
        exits = block["exits"]
        pnls = [float(e["pnl"]) for e in exits]
        st = _stats(pnls) if pnls else _stats([])
        equity = float(block["broker_final_equity"]) / float(block["broker_initial_equity"])
        rows.append(
            {
                "arm": f"PAPER_REPLAY {arm}",
                "class": "PAPER_REPLAY",
                "instrument_timeframe": "BTC/USDT+ETH/USDT 1h",
                "window_start_utc": start,
                "window_end_utc": end,
                "trades_executed": int(block["stage_totals"].get("orders_created", 0)),
                "closed_trades": int(block["fills_closed"]),
                "calendar_days": round(span_days, 4),
                "trades_per_day": round(len(exits) / span_days, 4) if span_days else None,
                "days_with_zero_trades": "",
                "gross_bps_total": "",
                "net_bps_total": "",
                "net_return_pct": round((equity - 1.0) * 100.0, 6),
                "equity_multiple": round(equity, 8),
                "fees_bps_per_side": 5.0,
                "fees_bps_per_round_trip": 10.0,
                "spread_bps_per_round_trip": 0.0,
                "slippage_bps_per_side": 1.0,
                "expectancy_bps_per_trade": round(st["mean"], 6)
                if st["mean"] is not None
                else None,
                "per_trade_sharpe": round(st["sharpe"], 6) if st["sharpe"] else None,
                "max_drawdown_bps": "",
                "profit_factor": round(st["profit_factor"], 6) if st["profit_factor"] else None,
                "win_rate": round(st["win_rate"], 6) if st["win_rate"] is not None else None,
                "cost_sensitivity_0bps_net_bps": "",
                "cost_sensitivity_5bps_net_bps": "",
                "cost_sensitivity_10bps_net_bps": "",
                "cost_sensitivity_20bps_net_bps": "",
                "breakeven_fees_bps_per_side": "",
                "current_vs_proposed": (
                    "CURRENT: the runtime's own behaviour, not a proposal"
                    if arm == "GATE_INTACT"
                    else "SANDBOX: a connectivity arm, never a candidate"
                ),
                "robustness": "",
                "oos_evidence": "NONE — this is a replay, not an observation",
                "statistical_limitations": (
                    "returns are in quote currency from a broker model, so they are not "
                    "comparable with the bps columns of the backtest arms"
                ),
                "decision": "DEFER" if arm == "GATE_INTACT" else "REJECT",
                "notes": (
                    "expectancy is quoted in quote currency per closed fill, not bps"
                    if exits
                    else "no fills: the committed ledger admits nothing, which is the gate working"
                ),
            }
        )

    path = OUT / "ECONOMIC_COMPARISON.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    summary = {
        "schema_version": "EDGE14R_ECONOMIC_COMPARISON_V1",
        "work_package": "WP-EDGE-14R/P5",
        "csv": str(path),
        "rows": len(rows),
        "arms": [r["arm"] for r in rows],
        "decisions": {r["arm"]: r["decision"] for r in rows},
        "target": (
            "ACTIVE asks for at least three executed trades per day in crypto, seven days a "
            "week, only where the economics support it; QUALITY stays independent and no "
            "arm here reaches three trades per day with a positive net"
        ),
        "buy_and_hold_bps": buy_hold,
        "order_sent": False,
        "promotion": "NONE",
    }
    (OUT / "ECONOMIC_COMPARISON.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"[economics] wrote {path} with {len(rows)} arms")
    for r in rows:
        print(
            f"[economics] {r['arm'][:44]:46s} {r['decision']:8s} "
            f"trades={r['trades_executed']} net={r['net_bps_total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
