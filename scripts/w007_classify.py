#!/usr/bin/env python3
"""Classify the WP-006 evaluation into ADMIT / EXPERIMENT / REJECT (WP-007).

The criteria are declared here, before the numbers are read, and are applied to the
published artifacts without adjustment:

ADMIT      net_pnl > 0 under BASE **and** 2X_COST **and** STRESSED_SLIPPAGE, and
           net_pnl > 0 in DEV and in OOS, and at least ``MIN_TRADES`` trades.
           Cost stress is part of admission: an edge that dies at 2x cost is not an
           edge that survives a live exchange.
EXPERIMENT gross_pnl > 0 under BASE (the signal carries information before costs), or
           net_pnl > 0 at ZERO_COST with at least ``MIN_TRADES`` trades. Such a family
           is worth bounded follow-up work; it is not admissible.
REJECT     neither: no evidence of a gross edge.

Nothing here promotes anything: ``admitted_for_paper`` is a separate ledger and this
script does not write it. No parameter is tuned on OOS; the partitions are the ones
the engine published.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MIN_TRADES = 100
ADMISSION_SCENARIOS = ("BASE", "2X_COST", "STRESSED_SLIPPAGE")


def classify(scenarios: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify one family from its published scenario blocks."""
    reasons: list[str] = []
    block = scenarios["BASE"]
    totals = block["totals"]
    trades = totals["trades"]
    if trades < MIN_TRADES:
        return "REJECT", [f"insufficient sample: {trades} < {MIN_TRADES} trades"]

    net_by_scenario = {s: scenarios[s]["totals"]["net_pnl"] if s in scenarios else None
                       for s in ADMISSION_SCENARIOS}
    if any(v is None for v in net_by_scenario.values()):
        reasons.append("cost scenarios missing from the artifact")
    else:
        if all(v > 0 for v in net_by_scenario.values()):
            if block["DEV"]["net_pnl"] > 0 and block["OOS"]["net_pnl"] > 0:
                reasons.append("net positive under every cost scenario and in DEV and OOS")
                return "ADMIT", reasons
            reasons.append("net positive under stress but not in DEV and OOS together")
        else:
            reasons.append("net not positive under all cost scenarios: "
                           + ", ".join(f"{s}={v:.2f}" for s, v in net_by_scenario.items()))

    if totals["gross_pnl"] > 0:
        reasons.append(f"gross edge before costs: {totals['gross_pnl']:.2f}")
        return "EXPERIMENT", reasons
    zero = scenarios.get("ZERO_COST")
    if zero and zero["totals"]["net_pnl"] > 0 and zero["totals"]["trades"] >= MIN_TRADES:
        reasons.append(f"positive only at zero cost: {zero['totals']['net_pnl']:.2f}")
        return "EXPERIMENT", reasons
    reasons.append(f"no gross edge: gross={totals['gross_pnl']:.2f}")
    return "REJECT", reasons


def diagnostics(scenarios: dict[str, Any], days: float, symbols: int) -> dict[str, Any]:
    block = scenarios["BASE"]
    totals = block["totals"]
    trades = totals["trades"]
    if not trades:
        return {"trades_per_day_per_symbol": 0.0}
    gross_per_trade = totals["gross_pnl"] / trades
    cost_per_trade = totals["cost_per_trade"]
    avg_notional = 500.0  # the size cap binds for every family here; published per trade
    breakeven_bps_round_trip = (gross_per_trade / avg_notional) * 1e4 if avg_notional else None
    return {
        "trades_per_day_per_symbol": round(trades / (days * symbols), 2) if days and symbols else None,
        "gross_per_trade": round(gross_per_trade, 4),
        "cost_per_trade": round(cost_per_trade, 4),
        "net_per_trade": round(totals["net_pnl"] / trades, 4),
        "edge_to_cost_ratio": round(gross_per_trade / cost_per_trade, 3) if cost_per_trade else None,
        "breakeven_round_trip_bps_at_typical_size": round(breakeven_bps_round_trip, 3)
        if breakeven_bps_round_trip is not None else None,
        "partition_net_base": {p: block[p]["net_pnl"] for p in ("DEV", "VAL", "OOS")},
        "partition_net_zero_cost": {p: scenarios["ZERO_COST"][p]["net_pnl"]
                                    for p in ("DEV", "VAL", "OOS")}
        if "ZERO_COST" in scenarios else None,
        "per_symbol_net_base": {s: v["totals"]["net_pnl"] for s, v in block["per_symbol"].items()},
        "per_symbol_trades_base": {s: v["totals"]["trades"] for s, v in block["per_symbol"].items()},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", type=Path, default=Path("reports/economic/w006/MULTI_FAMILY_RESULTS.json"))
    p.add_argument("--out", type=Path, default=Path("reports/economic/w006/ECONOMIC_CLASSIFICATION.json"))
    p.add_argument("--days", type=float, default=120.0)
    args = p.parse_args(argv)

    payload = json.loads(args.results.read_text(encoding="utf-8"))
    boundaries = payload["partitions"]["boundaries_ms"]
    span_days = (boundaries["oos"][1] - boundaries["dev"][0]) / 86_400_000
    out: dict[str, Any] = {
        "schema": "W007_ECONOMIC_CLASSIFICATION_V1",
        "results": str(args.results),
        "criteria": {
            "ADMIT": "net_pnl > 0 at BASE, 2X_COST and STRESSED_SLIPPAGE; net_pnl > 0 in DEV "
                     "and OOS; at least 100 trades",
            "EXPERIMENT": "gross_pnl > 0 at BASE, or net_pnl > 0 at ZERO_COST with >= 100 trades",
            "REJECT": "no gross edge",
            "min_trades": MIN_TRADES,
        },
        "sample": {"days": round(span_days, 2), "symbols": sorted(
            list(payload["results"][next(iter(payload["results"]))]["BASE"]["per_symbol"])),
            "bar": "5m", "partitions_utc": payload["partitions"]["boundaries_utc"]},
        "families": {},
        "counts": {},
    }
    for family, scenarios in sorted(payload["results"].items()):
        block = scenarios["BASE"]
        verdict, reasons = classify(scenarios)
        out["families"][family] = {
            "classification": verdict, "reasons": reasons,
            "diagnostics": diagnostics(scenarios, span_days,
                                       len(block["per_symbol"])),
            "totals_base": {k: block["totals"][k] for k in
                            ("trades", "gross_pnl", "spread_cost", "slippage_cost", "fees",
                             "net_pnl", "profit_factor", "win_rate", "expectancy_net",
                             "cost_per_trade")},
            "scenario_net": {s: scenarios[s]["totals"]["net_pnl"] for s in scenarios},
        }
    counts: dict[str, int] = {}
    for fam in out["families"].values():
        counts[fam["classification"]] = counts.get(fam["classification"], 0) + 1
    out["counts"] = counts
    out["status"] = "NO_ADMITTED_STRATEGY" if counts.get("ADMIT", 0) == 0 else "ADMITTED"
    out["limitations"] = [
        "one venue, three symbols, 120 days: a family that fails here is rejected for this "
        "sample, not proven dead on every market",
        "spread is a declared assumption (0 bps by default); the cost model is charged per leg "
        "and the spread assumption is tested by the 2X_COST scenario",
        "no walk-forward refit is performed because no hyperparameters are fitted; the "
        "partitions are evaluation buckets, not training folds",
        "ZERO_COST is diagnostic only and can never support admission",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    for family, fam in out["families"].items():
        d = fam["diagnostics"]
        print(f"{family:15s} {fam['classification']:10s} trades={fam['totals_base']['trades']:5d} "
              f"net_base={fam['totals_base']['net_pnl']:9.2f} "
              f"gross={fam['totals_base']['gross_pnl']:8.2f} "
              f"gross/trade={d['gross_per_trade']:7.4f} cost/trade={d['cost_per_trade']:6.4f} "
              f"net0={fam['scenario_net'].get('ZERO_COST', 0):8.2f}")
        print(f"{'':15s}            {fam['reasons'][0]}")
    print(f"COUNT: {out['counts']} | STATUS: {out['status']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
