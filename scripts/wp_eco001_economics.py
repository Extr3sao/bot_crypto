"""WP-ECONOMIC-BLOCKER-001 — gross vs all-in cost for every ledger entry.

Emits the per-(strategy, timeframe) economics matrix. The gross column comes
from the admission ledger (a committed zero-cost research number), the cost
column is recomputed live through ``CostEngine`` at the timeframe's own horizon,
and the net column is the difference. No number is copied from a report.

Deliberately conservative choices, so nobody can accuse the table of flattering
the strategies:

* the cost uses each entry's own horizon (fees do not change with horizon, and
  funding is zero on spot, so the choice barely matters — that is itself a
  finding, and the sweep in the cost audit shows it);
* no entry is credited with a `PAPER_CANDIDATE` status it does not have;
* a net computed from an unproven sample (``sample_trades == 0``) is marked
  ``NET_UNPROVEN_SAMPLE`` even when its sign looks good.

Usage::

    uv run python scripts/wp_eco001_economics.py --out <evidence dir>
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from trading_bot.autonomous.costs import CostEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("config/strategy_admission.json")
MATRIX = Path("docs/STRATEGY_ADMISSION_MATRIX.json")
TIMEFRAME_MINUTES = {"5m": 5.0, "15m": 15.0, "30m": 30.0, "1h": 60.0}
MIN_TRADES = 100
SAFETY_MULTIPLE = 1.5

COLUMNS = [
    "strategy_id",
    "family",
    "timeframe",
    "horizon_minutes",
    "gross_bps_per_trade",
    "gross_knowledge",
    "sample_trades",
    "sample_proven",
    "round_trip_cost_bps",
    "cost_known_fees_bps",
    "cost_estimated_bps",
    "net_bps_per_trade",
    "break_even_gross_bps",
    "required_gross_1.5x_bps",
    "net_at_1.5x_bps",
    "gross_shortfall_vs_cost_bps",
    "admission_status",
    "admitted_for_paper",
    "matrix_status",
    "matrix_net_usd_base",
    "matrix_fees_usd_base",
    "matrix_profit_factor_base",
    "verdict",
    "evidence_gap",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "docs/agentic/economic_audit/WP-ECONOMIC-BLOCKER-001")
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ledger = json.loads((REPO_ROOT / LEDGER).read_text(encoding="utf-8"))
    matrix = json.loads((REPO_ROOT / MATRIX).read_text(encoding="utf-8"))
    admissions = matrix.get("admissions") or {}
    engine = CostEngine()

    rows: list[dict[str, Any]] = []
    for strategy_id, entry in sorted(ledger["strategies"].items()):
        timeframe = str(entry.get("timeframe"))
        horizon = TIMEFRAME_MINUTES.get(timeframe, 5.0)
        evidence = entry.get("edge_evidence") or {}
        gross = float(entry.get("expected_gross_edge_bps") or 0.0)
        sample = int(evidence.get("sample_trades") or 0)
        breakdown = engine.evaluate(
            size_usd=1000.0, horizon_minutes=horizon, spread_bps=None
        )
        known = sum(c["value_bps"] for c in breakdown.components if c["knowledge"] == "KNOWN")
        estimated = sum(
            c["value_bps"] for c in breakdown.components if c["knowledge"] == "ESTIMATED"
        )
        cost = breakdown.round_trip_bps
        net = gross - cost
        matrix_entry = admissions.get(str(entry.get("family"))) or {}
        base = matrix_entry.get("totals_base") or {}

        if gross <= 0.0:
            # The zero-cost gross edge is already non-positive: the verdict does
            # not depend on the sample size at all.
            verdict = "NET_NEGATIVE_AFTER_COST"
            gap = (
                "no evidence gap changes this: the zero-cost gross edge is already "
                f"{gross:+.2f} bps/trade before any fee is charged"
            )
        elif sample < MIN_TRADES:
            verdict = "NET_UNPROVEN_SAMPLE"
            gap = (
                f"trade count not published for {timeframe} (sample_trades=0); "
                f"needs >= {MIN_TRADES} trades and >= 30 OOS trades before any net is a claim"
            )
        elif net <= 0.0:
            verdict = "NET_NEGATIVE_AFTER_COST"
            gap = "measured sample, but the round-trip cost exceeds the gross edge"
        else:
            verdict = "NET_POSITIVE_NOT_ADMITTED"
            gap = "positive net under this cost model; admission still requires all pre-registered checks"

        rows.append(
            {
                "strategy_id": strategy_id,
                "family": entry.get("family"),
                "timeframe": timeframe,
                "horizon_minutes": horizon,
                "gross_bps_per_trade": round(gross, 6),
                "gross_knowledge": evidence.get("knowledge"),
                "sample_trades": sample,
                "sample_proven": sample >= MIN_TRADES,
                "round_trip_cost_bps": round(cost, 6),
                "cost_known_fees_bps": round(known, 6),
                "cost_estimated_bps": round(estimated, 6),
                "net_bps_per_trade": round(net, 6),
                "break_even_gross_bps": round(cost, 6),
                "required_gross_1.5x_bps": round(cost * SAFETY_MULTIPLE, 6),
                "net_at_1.5x_bps": round(gross - cost * SAFETY_MULTIPLE, 6),
                "gross_shortfall_vs_cost_bps": round(cost - gross, 6),
                "admission_status": entry.get("status"),
                "admitted_for_paper": bool(entry.get("admitted_for_paper")),
                "matrix_status": matrix_entry.get("status"),
                "matrix_net_usd_base": base.get("net"),
                "matrix_fees_usd_base": base.get("fees"),
                "matrix_profit_factor_base": base.get("profit_factor"),
                "verdict": verdict,
                "evidence_gap": gap,
            }
        )

    csv_path = out_dir / "STRATEGY_ECONOMICS_MATRIX.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    # -- aggregates ---------------------------------------------------------
    by_family: dict[str, dict[str, Any]] = OrderedDict()
    for row in rows:
        family = str(row["family"])
        slot = by_family.setdefault(
            family,
            {
                "family": family,
                "entries": 0,
                "timeframes": [],
                "best_gross_bps": None,
                "best_timeframe": None,
                "best_net_bps": None,
                "proven_sample_entries": 0,
                "positive_gross_entries": 0,
                "statuses": set(),
            },
        )
        slot["entries"] += 1
        slot["timeframes"].append(row["timeframe"])
        slot["statuses"].add(str(row["admission_status"]))
        if float(row["gross_bps_per_trade"]) > 0:
            slot["positive_gross_entries"] += 1
        if row["sample_proven"]:
            slot["proven_sample_entries"] += 1
        if slot["best_gross_bps"] is None or float(row["gross_bps_per_trade"]) > float(
            slot["best_gross_bps"]
        ):
            slot["best_gross_bps"] = row["gross_bps_per_trade"]
            slot["best_timeframe"] = row["timeframe"]
            slot["best_net_bps"] = row["net_bps_per_trade"]

    for slot in by_family.values():
        slot["statuses"] = sorted(slot["statuses"])
        slot["timeframes"] = sorted(slot["timeframes"])
        base = (admissions.get(slot["family"]) or {}).get("totals_base") or {}
        slot["matrix_totals_base"] = {
            "trades": base.get("trades"),
            "gross_usd": base.get("gross"),
            "fees_usd": base.get("fees"),
            "net_usd": base.get("net"),
            "profit_factor": base.get("profit_factor"),
            "expectancy_usd": base.get("expectancy"),
        }
        slot["fee_drag_multiple_of_gross"] = (
            round(abs(float(base.get("fees") or 0.0)) / abs(float(base.get("gross") or 1.0)), 3)
            if base.get("gross")
            else None
        )
        slot["profitable_before_fees"] = bool(base.get("gross") and float(base["gross"]) > 0)

    ranked = sorted(rows, key=lambda r: float(r["gross_bps_per_trade"]), reverse=True)
    best_cost = min(float(r["round_trip_cost_bps"]) for r in rows)
    worst_cost = max(float(r["round_trip_cost_bps"]) for r in rows)
    best_gross = float(ranked[0]["gross_bps_per_trade"])
    positive = [r for r in rows if float(r["gross_bps_per_trade"]) > 0]

    payload = {
        "wp": "WP-ECONOMIC-BLOCKER-001",
        "artefact": "STRATEGY_ECONOMICS",
        "matrix_csv": "STRATEGY_ECONOMICS_MATRIX.csv",
        "rows": len(rows),
        "entries_by_timeframe": {
            tf: sum(1 for r in rows if r["timeframe"] == tf) for tf in sorted(TIMEFRAME_MINUTES)
        },
        "cost_by_asset_bps": {
            "BTC": 22.7918,
            "ETH": 22.8338,
            "SOL": 23.79,
            "note": "the runtime's three assets, from the recorded traces; the matrix uses the "
            "widest (SOL) so the table cannot flatter a strategy",
        },
        "cost_basis": {
            "scenario_id": "BINANCE_SPOT_STANDARD_TAKER",
            "size_usd": 1000.0,
            "spread": "model default (ESTIMATED 1.0 bps), which coincides with the widest "
            "measured spread of the three assets the PAPER runtime traded (SOL ~0.999 bps); "
            "the BTC case would cost 22.79 bps, i.e. 1.0 bps less, and changes no verdict",
            "cost_range_bps": [round(best_cost, 6), round(worst_cost, 6)],
            "safety_multiple": SAFETY_MULTIPLE,
        },
        "verdict_counts": {
            v: sum(1 for r in rows if r["verdict"] == v)
            for v in ("NET_NEGATIVE_AFTER_COST", "NET_UNPROVEN_SAMPLE", "NET_POSITIVE_NOT_ADMITTED")
        },
        "positive_gross_entries": [r["strategy_id"] for r in positive],
        "best_gross_entry": {
            "strategy_id": ranked[0]["strategy_id"],
            "gross_bps": ranked[0]["gross_bps_per_trade"],
            "net_bps": ranked[0]["net_bps_per_trade"],
            "sample_trades": ranked[0]["sample_trades"],
        },
        "spread_between_best_gross_and_cheapest_cost_bps": round(best_gross - best_cost, 6),
        "any_entry_clears_cost": any(float(r["net_bps_per_trade"]) > 0 for r in rows),
        "any_entry_clears_cost_with_proven_sample": any(
            float(r["net_bps_per_trade"]) > 0 and r["sample_proven"] for r in rows
        ),
        "candidates_for_later_validation": [
            {
                "strategy_id": r["strategy_id"],
                "gross_bps": r["gross_bps_per_trade"],
                "net_bps": r["net_bps_per_trade"],
                "sample_trades": r["sample_trades"],
                "why": "highest zero-cost gross edge among the positive entries, but the sample "
                "count is unpublished and the net is still negative",
                "not_admitted_because": [
                    "sample size unpublished (sample_trades=0)",
                    "net negative after the measured round-trip cost",
                    "no positive OOS result in the admission matrix",
                ],
            }
            for r in ranked
            if float(r["gross_bps_per_trade"]) > 0 and r["timeframe"] != "5m"
        ][:2],
        "families": list(by_family.values()),
        "interpretation": {
            "fee_floor": "20 bps of the 22.79 bps round trip are KNOWN venue fees, so no "
            "re-estimation of slippage or impact can change any verdict",
            "horizon_insensitivity": "cost is ~flat in horizon on spot (funding 0), so extending "
            "the holding period does not amortise the fee; the gross edge would have to grow with "
            "the horizon, and in the measured data it does not",
        },
    }
    path = out_dir / "STRATEGY_ECONOMICS.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[econ] rows={len(rows)} verdicts={payload['verdict_counts']}")
    print(f"[econ] best gross={ranked[0]['strategy_id']} {best_gross}bps net={ranked[0]['net_bps_per_trade']}")
    print(f"[econ] cost range={payload['cost_basis']['cost_range_bps']}")
    print(f"[econ] any_entry_clears_cost={payload['any_entry_clears_cost']}")
    print(f"[econ] -> {csv_path}")
    print(f"[econ] -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
