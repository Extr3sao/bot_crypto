"""RFC-049 DISCOVERY 2 — filter-ablation diagnostic (FASE 4).

Question (operator instruction): do the stablecoin and macro liquidity states improve an
existing strategy?  The ACTIVE audit (``data/rfc049/discovery2/ACTIVE_STRATEGY_STATUS.json``)
shows no admitted ACTIVE strategy exists to filter, so the adoption question cannot be
evaluated today.  This module executes the separable, safe part of the experiment as a
**diagnostic**:

    base          = the declared 200-day trend long/cash state machine (the frozen specs'
                    own comparator), used as a measuring instrument
    +stablecoin   = base AND H-049-001's stablecoin state
    +macro        = base AND H-049-002's macro state
    +both         = base AND both states

Identical data, costs, execution and partitions.  Nothing is adopted by this diagnostic on
any result: adoption would need a new hypothesis, a new experimental budget, and
reproducible improvement outside the data used to select it (forward), per the operator's
instruction.  H-049-001 and H-049-002 are not modified, and this diagnostic consumes no
admitted-hypothesis slot.

Writes ``data/rfc049/discovery2/FILTER_ABLATION.json`` and ``.md``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rfc049c_engine as E  # noqa: E402  (builder-side reuse; the verifier never imports either)

D2 = ROOT / "data" / "rfc049" / "discovery2"
VENDOR_RAW = ROOT / "data" / "rfc049" / "vendor" / "raw"
PRICE = ROOT / "data" / "raw" / "alpha001"


def main() -> int:
    results = json.loads((D2 / "ECONOMIC_RESULTS.json").read_text(encoding="utf-8"))
    cost_bps = results["cost_model"]["round_trip_bps_200_usdt"]

    bars = E.load_bars(PRICE / "BTC-USDT_1d.json")
    stable = E.defillama_rows(VENDOR_RAW / "defillama_stablecoin_supply_all.json")
    macro_inputs = {
        "WALCL": E.load_fred_csv(VENDOR_RAW / "fred_WALCL.csv"),
        "RRPONTSYD": E.load_fred_csv(VENDOR_RAW / "fred_RRPONTSYD.csv"),
        "WTREGEN": E.load_fred_csv(VENDOR_RAW / "fred_WTREGEN.csv"),
    }
    grid = E.build_grid(stable, bars)
    sig_a = E.stablecoin_states(stable, grid)
    sig_b, _ = E.macro_states(macro_inputs, grid)
    trend = E.trend200_states(bars, grid)

    states = {
        "base": dict(trend),
        "base+stablecoin": {s: trend[s] and sig_a[s]["state"] for s in grid},
        "base+macro": {s: trend[s] and sig_b[s]["state"] for s in grid},
        "base+both": {s: trend[s] and sig_a[s]["state"] and sig_b[s]["state"] for s in grid},
    }
    dev_span, val_span = (grid[0], E.DEV_END), (E.VAL_START, grid[-1])

    arms: dict[str, dict] = {}
    trips_by_arm: dict[str, list] = {}
    for name, st in states.items():
        trips, sim = E.simulate(st, bars)
        for t in trips:
            t["partition"] = E.partition_of(t["entry_sunday"])
        trips_by_arm[name] = trips
        dev = [t for t in trips if t["partition"] == "development"]
        val = [t for t in trips if t["partition"] == "validation"]
        arms[name] = {
            "development": E.metrics_for(dev, cost_bps, dev_span),
            "validation": E.metrics_for(val, cost_bps, val_span),
            "all_exposed": E.metrics_for(trips, cost_bps, (grid[0], grid[-1])),
            "simulation": sim,
        }
    base_trips = trips_by_arm["base"]

    # note: a conjunctive filter does not select a subset of the base's trades: gating can
    # also split one base position into several shorter ones, so trip counts can move either way.
    base_by_partition = {
        part: [t for t in base_trips if t["partition"] == part]
        for part in ("development", "validation")
    }
    deltas: dict[str, dict] = {}
    for name, st in states.items():
        if name == "base":
            continue
        trips_n = trips_by_arm[name]
        deltas[name] = {}
        for part in ("development", "validation"):
            b, a = arms["base"][part], arms[name][part]
            base_t = base_by_partition[part]
            arm_ms = {(t["entry_ms"], t["exit_ms"]) for t in trips_n if t["partition"] == part}
            identical = sum(1 for t in base_t if (t["entry_ms"], t["exit_ms"]) in arm_ms)
            deltas[name][part] = {
                "round_trips_base": b["round_trips"],
                "round_trips_arm": a["round_trips"],
                "round_trips_delta": a["round_trips"] - b["round_trips"],
                "base_trips_preserved_exactly": identical,
                "base_trips_reshaped_or_dropped": len(base_t) - identical,
                "net_sum_delta_bps": a["net_sum_bps"] - b["net_sum_bps"],
                "expectancy_delta_bps": (a["net_expectancy_bps"] or 0)
                - (b["net_expectancy_bps"] or 0),
                "max_drawdown_base": b["max_drawdown"],
                "max_drawdown_arm": a["max_drawdown"],
                "max_drawdown_delta": a["max_drawdown"] - b["max_drawdown"],
                "subwindows_positive_arm": a["subwindows_positive"],
                "subwindows_with_trips_arm": a["subwindows_with_trips"],
            }

    regimes = {"both_long": [], "stablecoin_only": [], "macro_only": [], "neither": []}
    for t in base_trips:
        s = date.fromisoformat(t["entry_sunday"])
        key = (
            "both_long"
            if sig_a[s]["state"] and sig_b[s]["state"]
            else "stablecoin_only"
            if sig_a[s]["state"]
            else "macro_only"
            if sig_b[s]["state"]
            else "neither"
        )
        regimes[key].append(t)
    regime_rows = {}
    for key, rows in regimes.items():
        nets = [t["gross_ret"] - cost_bps / 10_000.0 for t in rows]
        regime_rows[key] = {
            "round_trips": len(rows),
            "net_sum_bps": sum(nets) * 10_000.0,
            "mean_net_bps": (sum(nets) / len(nets)) * 10_000.0 if nets else None,
        }

    # cross-check: the base arm must reproduce the engine's trend comparator
    trend_dev = results["H-049-002"]["per_asset"]["BTCUSDT"]["incrementals"]["development"][
        "trend_200d_net_compounded"
    ]
    trend_val = results["H-049-002"]["per_asset"]["BTCUSDT"]["incrementals"]["validation"][
        "trend_200d_net_compounded"
    ]
    base_dev = arms["base"]["development"]["net_compounded"]
    base_val = arms["base"]["validation"]["net_compounded"]
    checks = [
        {
            "check": "base_reproduces_engine_trend_comparator",
            "result": "PASS"
            if abs(base_dev - trend_dev) < 1e-12 and abs(base_val - trend_val) < 1e-12
            else "FAIL",
            "detail": f"dev {base_dev} vs {trend_dev}; val {base_val} vs {trend_val}",
        }
    ]

    out = {
        "artifact": "RFC049_DISCOVERY2_FILTER_ABLATION",
        "generated_at_utc": E.utcnow(),
        "head_at_run": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "classification": "DIAGNOSTIC (non-confirmatory, RESEARCH_EXPOSED); no adoption follows from any result",
        "hypothesis_record": {
            "id": "E-049-ABL-001",
            "status": "DIAGNOSTIC_NOT_ADMITTED",
            "statement": "stablecoin/macro liquidity states, used as gates on a declared base state machine, may improve its net economics; the mechanism is the liquidity regime, not a price pattern",
            "sources": ["SRC-049-001", "SRC-049-002", "SRC-049-008"],
            "falsification": "no improvement (net, drawdown or stability) in forward data outside the selection sample; any result built only on exposed history is non-confirmatory",
            "budget_note": "consumes no admitted-hypothesis slot; a future adoption requires a new hypothesis and a new experimental budget",
        },
        "base": "200-day trend long/cash machine (the frozen specs' own comparator; used as a measuring instrument, not proposed for trading)",
        "cost_bps_round_trip": cost_bps,
        "arms": arms,
        "deltas": deltas,
        "base_regimes": regime_rows,
        "adoption": {
            "status": "NOT_ADOPTED",
            "reasons": [
                "no ACTIVE strategy exists as an adoption target today (paper ledger: 0 admitted, PAPER_ACTIVE=0)",
                "all numbers are RESEARCH_EXPOSED and non-confirmatory",
                "the operator's adoption rule requires reproducible improvement outside the data used to select the filter (forward evidence), which does not exist yet",
            ],
            "prerequisites_for_a_future_decision": [
                "a new admitted hypothesis with its own budget and frozen rules",
                "forward (post-selection) data showing the improvement survives",
            ],
        },
        "checks": checks,
        "checks_failed": sum(1 for c in checks if c["result"] != "PASS"),
        "scope": {
            "sealed_oos_opened": False,
            "trading": "not performed",
            "h_049_001_modified": False,
            "h_049_002_modified": False,
        },
    }
    (D2 / "FILTER_ABLATION.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# RFC-049 DISCOVERY 2 — FILTER ABLATION (DIAGNOSTIC)",
        "",
        f"- generated: `{out['generated_at_utc']}` · head `{out['head_at_run'][:12]}`",
        "- classification: **DIAGNOSTIC / non-confirmatory**. Nothing is adopted. H-049-001 and H-049-002 are not modified.",
        "- base: the declared 200-day trend state machine; arms conjunctive with the liquidity states.",
        "",
        "| arm | partition | round trips | net sum (bps) | expectancy (bps) | PF | max DD | sub-windows positive |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("base", "base+stablecoin", "base+macro", "base+both"):
        for part in ("development", "validation"):
            m = arms[name][part]
            pf = m["net_profit_factor"]
            lines.append(
                f"| {name} | {part} | {m['round_trips']} | {m['net_sum_bps']:.1f} | "
                f"{m['net_expectancy_bps']:.1f} | {pf:.3f} | {m['max_drawdown']:.3f} | "
                f"{m['subwindows_positive']}/{m['subwindows_with_trips']} |"
            )
    lines += [
        "",
        "## Deltas versus the base",
        "",
        "A conjunctive filter is not a subset: gating can split one base position into several "
        "shorter ones, so the trip count can move either way. `reshaped or dropped` counts base "
        "trips whose entry/exit pair is not preserved exactly.",
        "",
        "| arm | partition | trips (base → arm) | preserved exactly | reshaped or dropped | net delta (bps) | DD delta |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for name in ("base+stablecoin", "base+macro", "base+both"):
        for part in ("development", "validation"):
            d = deltas[name][part]
            lines.append(
                f"| {name} | {part} | {d['round_trips_base']} → {d['round_trips_arm']} | "
                f"{d['base_trips_preserved_exactly']} | {d['base_trips_reshaped_or_dropped']} | "
                f"{d['net_sum_delta_bps']:+.1f} | {d['max_drawdown_delta']:+.3f} |"
            )
    lines += [
        "",
        "## Base arm by liquidity regime at entry",
        "",
        "| regime | round trips | net sum (bps) | mean net (bps) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, row in regime_rows.items():
        mean = row["mean_net_bps"]
        lines.append(
            f"| {key} | {row['round_trips']} | {row['net_sum_bps']:.1f} | {mean:.1f} |"
            if mean is not None
            else f"| {key} | 0 | 0.0 | n/a |"
        )
    lines += [
        "",
        "## Adoption",
        "",
        "**NOT_ADOPTED.** " + " ".join(out["adoption"]["reasons"]),
        "",
        "A future decision requires: "
        + "; ".join(out["adoption"]["prerequisites_for_a_future_decision"])
        + ".",
        "",
        f"- base reproduces the engine's trend comparator: **{checks[0]['result']}** ({checks[0]['detail']})",
    ]
    (D2 / "FILTER_ABLATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "checks": checks,
                "arms": {
                    k: {p: arms[k][p]["round_trips"] for p in ("development", "validation")}
                    for k in states
                },
            },
            indent=2,
        )
    )
    return 1 if out["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
