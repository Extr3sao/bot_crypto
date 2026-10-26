#!/usr/bin/env python3
"""Independent verification of a WP-006 evaluation (BUILDER != VERIFIER).

This script does not import the engine. It re-reads the published artifacts, the
manifest and the raw bars, and re-derives every number it can from first
principles:

* PnL identity per trade: ``net = gross - spread - slippage - fees``;
* ``gross`` recomputed from reference prices and quantity, not read from the file;
* fees, slippage and spread recomputed from the published bps and the trade's own
  notional;
* fills recomputed from the reference price and the declared per-side costs;
* causality: the entry bar is exactly one bar after the signal bar, and every
  consulted bar is at or before the decision (no fill at the signal close);
* exits: a stop/target exit lies inside the exit bar's range; a flip or the end of
  data exits at that bar's open / the final close;
* MFE and MAE recomputed from the bars the position was actually exposed to;
* partitions recomputed from the published boundaries;
* aggregates recomputed from the trade file and compared with the published totals.

Exit codes: 0 = PASS, 1 = FAIL, 2 = unusable input. A check that cannot run is a
failure, never a pass.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

PLIMIT = 5  # failures printed per check
# The trade file publishes each component rounded to 6 decimals, so the identity
# ``net = gross - spread - slippage - fees`` can only hold up to the rounding of four
# fields: 4 * 0.5e-6. The bound is derived from the published precision and is not a
# free parameter; the largest residual actually seen is reported alongside it.
IDENTITY_TOL = 4 * 5e-7
# Costs are recomputed from the published bps and notionals, which are themselves
# rounded to 8 and 10 decimals in the file, hence a slightly wider absolute bound.
COST_TOL = 1e-5
MFE_TOL_PCT = 1e-3


def fail(check: dict[str, Any], detail: str) -> None:
    check["failures"].append(detail)
    check["failed"] += 1


def ok(check: dict[str, Any]) -> None:
    check["checked"] += 1


def new_check(name: str, description: str) -> dict[str, Any]:
    return {"name": name, "description": description, "checked": 0, "failed": 0,
            "failures": [], "max_residual": 0.0, "status": "PASS"}


def load_bars(manifest_path: Path) -> dict[str, list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out = {}
    for symbol, entry in manifest["datasets"].items():
        path = manifest_path.parent / entry["path"]
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"dataset digest mismatch for {symbol}: the verification would be "
                             f"over different bytes than the evaluation")
        out[symbol] = json.loads(raw)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", type=Path, default=Path("reports/economic/w006/MULTI_FAMILY_RESULTS.json"))
    p.add_argument("--trades", type=Path, default=Path("reports/economic/w006/TRADES.csv"))
    p.add_argument("--manifest", type=Path, default=Path("data/economic/w006/MANIFEST.json"))
    p.add_argument("--out", type=Path, default=Path("reports/economic/w006/INDEPENDENT_VERIFICATION.json"))
    args = p.parse_args(argv)

    for path in (args.results, args.trades, args.manifest):
        if not path.is_file():
            print(f"ERROR: missing input {path}", file=sys.stderr)
            return 2

    payload = json.loads(args.results.read_text(encoding="utf-8"))
    bars_by_symbol = load_bars(args.manifest)
    index_by_symbol = {s: {b["ts"]: i for i, b in enumerate(bars)} for s, bars in bars_by_symbol.items()}
    boundaries = payload["partitions"]["boundaries_ms"]
    base_cost = payload["cost_model_base"]
    scen_factors = {"BASE": (1.0, 1.0, 1.0), "2X_COST": (2.0, 1.0, 2.0),
                    "STRESSED_SLIPPAGE": (1.0, 5.0, 1.0), "ZERO_COST": (0.0, 0.0, 0.0)}

    opener = gzip.open if args.trades.suffix == ".gz" else open
    with opener(args.trades, "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("ERROR: no trades to verify; an empty trade file is not a pass", file=sys.stderr)
        return 2

    checks = {
        "pnl_identity": new_check("pnl_identity", "net = gross - spread - slippage - fees"),
        "gross_from_prices": new_check("gross_from_prices", "gross recomputed from qty and reference prices"),
        "costs_from_bps": new_check("costs_from_bps", "fees/spread/slippage recomputed from bps"),
        "fills_from_costs": new_check("fills_from_costs", "fill = ref +/- (half_spread+slippage)"),
        "causality": new_check("causality", "entry bar is exactly one bar after the signal bar"),
        "exit_realism": new_check("exit_realism", "exits lie inside the bar that produced them"),
        "mfe_mae": new_check("mfe_mae", "MFE/MAE recomputed from the bars the position was exposed to"),
        "partitions": new_check("partitions", "partition matches the published boundaries"),
        "aggregates": new_check("aggregates", "published totals equal the sums over the trade file"),
        "no_warmup_trade": new_check("no_warmup_trade", "no trade before the 60-bar warmup"),
    }

    for row in rows:
        symbol = row["symbol"]
        bars = bars_by_symbol.get(symbol)
        if bars is None:
            for c in checks.values():
                fail(c, f"unknown symbol {symbol}")
            continue
        idx = index_by_symbol[symbol]
        direction = 1 if row["side"] == "buy" else -1
        qty = float(row["qty"])
        entry_ref, exit_ref = float(row["entry_ref"]), float(row["exit_ref"])
        gross = float(row["gross_pnl"])
        spread, slippage, fees = (float(row["spread_cost"]), float(row["slippage_cost"]),
                                  float(row["fees"]))
        net = float(row["net_pnl"])

        # 1. identity
        residual = abs(net - (gross - spread - slippage - fees))
        checks["pnl_identity"]["max_residual"] = max(checks["pnl_identity"]["max_residual"], residual)
        if residual <= IDENTITY_TOL:
            ok(checks["pnl_identity"])
        else:
            fail(checks["pnl_identity"], f"{row['family']}/{symbol}/{row['entry_bar_ts']}: {net} != "
                                         f"{gross - spread - slippage - fees} (residual {residual})")

        # 2. gross from prices
        expected_gross = direction * qty * (exit_ref - entry_ref)
        if abs(expected_gross - gross) <= COST_TOL:
            ok(checks["gross_from_prices"])
        else:
            fail(checks["gross_from_prices"], f"{row['family']}/{symbol}: {gross} != {expected_gross}")

        # 3. costs from the declared bps
        f_, s_, sp_ = scen_factors[row["scenario"]]
        fees_bps = base_cost["fees_bps"] * f_
        slip_bps = base_cost["slippage_bps"] * s_
        spread_bps = base_cost["half_spread_bps"] * sp_
        entry_notional, exit_notional = entry_ref * qty, exit_ref * qty
        notions = entry_notional + exit_notional
        if abs(fees - notions * fees_bps / 1e4) <= COST_TOL:
            ok(checks["costs_from_bps"])
        else:
            fail(checks["costs_from_bps"], f"fees {fees} != {notions * fees_bps / 1e4}")
        if abs(spread - notions * spread_bps / 1e4) <= COST_TOL:
            ok(checks["costs_from_bps"])
        else:
            fail(checks["costs_from_bps"], f"spread {spread} != {notions * spread_bps / 1e4}")
        if abs(slippage - notions * slip_bps / 1e4) <= COST_TOL:
            ok(checks["costs_from_bps"])
        else:
            fail(checks["costs_from_bps"], f"slippage {slippage} != {notions * slip_bps / 1e4}")

        # 4. fills
        drift = (spread_bps + slip_bps) / 1e4
        if abs(float(row["entry_fill"]) - entry_ref * (1 + direction * drift)) <= COST_TOL and \
                abs(float(row["exit_fill"]) - exit_ref * (1 - direction * drift)) <= COST_TOL:
            ok(checks["fills_from_costs"])
        else:
            fail(checks["fills_from_costs"], f"{row['family']}/{symbol}: fills do not follow the costs")

        # 5. causality: the entry bar is the bar after the signal, never the signal bar
        signal_ts, entry_ts, exit_ts = (int(row["entry_signal_ts"]), int(row["entry_bar_ts"]),
                                        int(row["exit_bar_ts"]))
        si, ei, xi = idx.get(signal_ts), idx.get(entry_ts), idx.get(exit_ts)
        if si is None or ei is None or xi is None:
            fail(checks["causality"], f"{row['family']}/{symbol}: timestamps absent from the dataset")
        elif ei == si + 1 and xi >= ei:
            ok(checks["causality"])
        else:
            fail(checks["causality"], f"{row['family']}/{symbol}: signal idx {si}, entry idx {ei}")

        # 6. exits inside their bar
        if ei is not None and xi is not None:
            exit_bar = bars[xi]
            reason = row["reason"]
            if reason in ("stop_loss", "take_profit"):
                inside = exit_bar["low"] - 1e-9 <= exit_ref <= exit_bar["high"] + 1e-9
            elif reason == "signal_flip":
                inside = abs(exit_ref - exit_bar["open"]) <= 1e-9
            else:  # end_of_data
                inside = xi == len(bars) - 1 and abs(exit_ref - exit_bar["close"]) <= 1e-6
            if inside:
                ok(checks["exit_realism"])
            else:
                fail(checks["exit_realism"], f"{row['family']}/{symbol} {reason} @ {exit_ts}: "
                                             f"exit {exit_ref} outside [{exit_bar['low']}, {exit_bar['high']}]")

            # 7. MFE / MAE recomputed over the bars the position was actually exposed to.
            # A flip closes at the exit bar's open, so that bar's range is not exposure.
            window = bars[ei:xi] if reason == "signal_flip" else bars[ei:xi + 1]
            if direction == 1:
                mfe = max(b["high"] for b in window) - entry_ref
                mae = entry_ref - min(b["low"] for b in window)
            else:
                mfe = entry_ref - min(b["low"] for b in window)
                mae = max(b["high"] for b in window) - entry_ref
            mfe_pct, mae_pct = mfe / entry_ref * 100.0, mae / entry_ref * 100.0
            if abs(mfe_pct - float(row["mfe_pct"])) <= MFE_TOL_PCT and \
                    abs(mae_pct - float(row["mae_pct"])) <= MFE_TOL_PCT:
                ok(checks["mfe_mae"])
            else:
                fail(checks["mfe_mae"], f"{row['family']}/{symbol}: mfe {row['mfe_pct']} != {mfe_pct:.4f} "
                                        f"or mae {row['mae_pct']} != {mae_pct:.4f}")

        # 8. partitions
        expected_partition = ("DEV" if entry_ts < boundaries["dev"][1]
                              else "VAL" if entry_ts < boundaries["val"][1] else "OOS")
        if row["partition"] == expected_partition:
            ok(checks["partitions"])
        else:
            fail(checks["partitions"], f"{row['family']}/{symbol}: {row['partition']} != {expected_partition}")

        # 9. warmup
        if ei is not None and ei >= 60:
            ok(checks["no_warmup_trade"])
        else:
            fail(checks["no_warmup_trade"], f"{row['family']}/{symbol}: entry index {ei}")

    # 10. aggregates: recompute from the trade file, compare with the published totals
    for family, scenarios in payload["results"].items():
        for scenario, block in scenarios.items():
            subset = [r for r in rows if r["family"] == family and r["scenario"] == scenario]
            totals = block["totals"]
            checks_run = [
                ("trades", len(subset)),
                ("gross_pnl", round(sum(float(r["gross_pnl"]) for r in subset), 6)),
                ("net_pnl", round(sum(float(r["net_pnl"]) for r in subset), 6)),
                ("fees", round(sum(float(r["fees"]) for r in subset), 6)),
                ("slippage_cost", round(sum(float(r["slippage_cost"]) for r in subset), 6)),
                ("spread_cost", round(sum(float(r["spread_cost"]) for r in subset), 6)),
            ]
            for key, value in checks_run:
                if abs(value - totals[key]) <= max(IDENTITY_TOL, abs(totals[key]) * 1e-9):
                    ok(checks["aggregates"])
                else:
                    fail(checks["aggregates"], f"{family}/{scenario}: {key} published {totals[key]} "
                                               f"!= recomputed {value}")
            for partition in ("DEV", "VAL", "OOS"):
                subset_p = [r for r in subset if r["partition"] == partition]
                published = block[partition]["net_pnl"]
                recomputed = round(sum(float(r["net_pnl"]) for r in subset_p), 6)
                if abs(recomputed - published) <= max(IDENTITY_TOL, abs(published) * 1e-9):
                    ok(checks["aggregates"])
                else:
                    fail(checks["aggregates"], f"{family}/{scenario}/{partition}: {published} != {recomputed}")

    for c in checks.values():
        c["status"] = "FAIL" if c["failed"] else "PASS"
    overall = "PASS" if all(c["status"] == "PASS" for c in checks.values()) else "FAIL"
    report = {
        "schema": "W006_INDEPENDENT_VERIFICATION_V1",
        "verifier": "scripts/w006_verify.py (does not import the engine under test)",
        "results": str(args.results),
        "results_sha256": hashlib.sha256(args.results.read_bytes()).hexdigest(),
        "trades_sha256": hashlib.sha256(args.trades.read_bytes()).hexdigest(),
        "trades_verified": len(rows),
        "checks": checks,
        "status": overall,
        "limitations": [
            "verifies arithmetic and causality of the published trades; it cannot prove that "
            "the strategy classes are the production ones, only that the artifacts agree",
            "a bar-close signal is verified to fill one bar later; the paper adapter's own "
            "fill semantics are a separate comparison",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    for c in checks.values():
        print(f"{c['name']:20s} {c['status']:4s} checked={c['checked']:6d} failed={c['failed']}")
        for line in c["failures"][:PLIMIT]:
            print(f"   - {line}")
    print(f"OVERALL: {overall} ({len(rows)} trades verified) -> {args.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
