#!/usr/bin/env python
"""WP-EDGE-07 Track C — screen the two ACTIVE books, then read the survivor once.

    python scripts/edge07_active.py                 # screen + (if C0 passes) read the holdout
    python scripts/edge07_active.py --screen-only    # the cost screen on DEV, nothing else
    python scripts/edge07_active.py --json           # print the payload, write nothing

The parameters and the window are not arguments: they are the ones the registration
(`active-research/PREREGISTRATION.json`) froze, and the independent window is read once.

Order of business, which is the registration's own order:

1. **C0, the cost screen** — each candidate is run on DEV. A candidate whose *gross* expectancy is
   not positive loses money before any fee, and no cost change repairs that, so it is reported
   `REJECT_NO_GROSS_EDGE` and never reads the holdout.
2. **The independent window** — a survivor is run on `NEW_HOLDOUT` (2026-03-01…, the window this
   work package fetched, unread by any book), with the campaign's costs, risk policy, simulator
   and metrics, and the four added readings.
3. **The verdict** — C1..C6 from the registration, and nothing else.

Exit codes:

    0  a verdict was reached (ADMIT_PAPER or REJECT)
    1  INSUFFICIENT_EVIDENCE (no result, never a pass)
    2  the run could not be completed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge01 import campaign as C  # noqa: E402
from trading_bot.research.edge01.costs import cost_plane  # noqa: E402
from trading_bot.research.edge01.data import ASSETS, load_1h  # noqa: E402
from trading_bot.research.edge01.simulator import run_portfolio  # noqa: E402
from trading_bot.research.edge07 import active as A  # noqa: E402
from trading_bot.research.edge07 import validation as V  # noqa: E402

OUT_DIR = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07" / "active-research"
DAY_MS = 86_400_000
SCREEN_MIN_TRADES = 30


def hourly_corpus(*, holdout: bool) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    """The 1h bars for the development windows or for the independent one, with provenance."""
    bars: dict[str, list[Any]] = {}
    provenance: dict[str, Any] = {}
    for asset in ASSETS:
        corpus = load_1h(asset, corpus=V.HOLDOUT_DIR) if holdout else load_1h(asset)
        bars[asset] = list(corpus.bars)
        provenance[asset] = corpus.to_dict()
    return bars, provenance


def run_candidate(
    *,
    book_id: str,
    bars_by_asset: dict[str, list[Any]],
    window: dict[str, int],
    regime_rows: tuple[Any, ...] | None,
    scenarios: tuple[str, ...] = V.COST_SCENARIOS,
) -> dict[str, Any]:
    policy = C.load_risk_policy()
    window_minutes = (window["end"] - window["start"]) / 60_000.0
    days = window_minutes / 1440.0
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=60.0)
    out: dict[str, Any] = {"days": round(days, 4)}
    for scenario in scenarios:
        plane = base_plane.scaled(scenario)
        candidate = A.build_active_books()[book_id]
        sim = run_portfolio(
            candidate=candidate,
            bars_by_asset=bars_by_asset,
            plane=plane,
            policy=policy,
            context=None,
            window_start_ts=window["start"],
            window_end_ts=window["end"],
        )
        if regime_rows is not None:
            from trading_bot.research.edge01.features import market_regime_at

            for trade in sim.trades:
                trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        metrics = C._metrics(
            trades=sim.trades,
            equity_curve=sim.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=window_minutes,
            timeframe=A.TIMEFRAME,
            n_assets=len(bars_by_asset),
        )
        refusals: dict[str, int] = {}
        for refusal in sim.refusals:
            key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
            refusals[key] = refusals.get(key, 0) + 1
        out[scenario] = {
            **metrics,
            "trades_per_day": round(len(sim.trades) / days, 4) if days else None,
            "gross_expectancy_usdt": round(
                sum(float(t["gross"]) for t in sim.trades) / len(sim.trades), 4
            )
            if sim.trades
            else None,
            "gross_bps_per_trade": round(
                sum(float(t["gross"]) / float(t["notional"]) for t in sim.trades if t["notional"])
                / max(1, len(sim.trades))
                * 10_000.0,
                4,
            )
            if sim.trades
            else None,
            "with_the_largest_winner_removed": V.C_leave_out_largest(
                trades=sim.trades, start_equity=policy.start_equity
            ),
            "extras": V._extras(trades=sim.trades, window=window),
            "candidate_refusals": refusals,
            "plane": plane.to_dict(),
            "trade_rows": sim.trades,
        }
    return out


def verdict_for(
    book_id: str, screen: dict[str, Any], holdout: dict[str, Any] | None
) -> dict[str, Any]:
    dev_gross = screen["DEV"]["BASE"].get("gross_expectancy_usdt")
    dev_trades = int(screen["DEV"]["BASE"].get("trades") or 0)
    base = {
        "id": "C0",
        "statement": "DEV gross expectancy > 0",
        "value": dev_gross,
        "passed": bool(dev_gross and dev_gross > 0),
    }
    if not base["passed"]:
        return {
            "book": book_id,
            "verdict": "REJECT_NO_GROSS_EDGE",
            "why": (
                f"the setup loses money before any fee on DEV ({dev_gross} USDT/trade over "
                f"{dev_trades} trades), which no cost change can repair"
            ),
            "checks": [base],
            "failed": ["C0"],
            "screen_pass": False,
            "holdout_read": False,
        }
    if holdout is None:
        return {
            "book": book_id,
            "verdict": "INSUFFICIENT_EVIDENCE",
            "why": "the screen passed but the independent window was not read",
            "checks": [base],
            "failed": [],
            "screen_pass": True,
            "holdout_read": False,
        }

    hbase = holdout["NEW_HOLDOUT"]["BASE"]
    hstress = holdout["NEW_HOLDOUT"]["2X_FEES"]
    per_day = hbase.get("trades_per_day")
    share = hbase.get("largest_trade_share_of_net")
    checks = [
        base,
        {
            "id": "C1",
            "statement": "trades >= 3 per day",
            "value": per_day,
            "passed": bool(per_day and per_day >= A.FREQUENCY_TARGET_PER_DAY),
        },
        {
            "id": "C2",
            "statement": "net > 0 at BASE",
            "value": hbase.get("net_usdt"),
            "passed": float(hbase.get("net_usdt") or 0) > 0,
        },
        {
            "id": "C3",
            "statement": "expectancy > 0 at BASE",
            "value": hbase.get("expectancy_usdt"),
            "passed": float(hbase.get("expectancy_usdt") or 0) > 0,
        },
        {
            "id": "C4",
            "statement": "net > 0 at 2X_FEES",
            "value": hstress.get("net_usdt"),
            "passed": float(hstress.get("net_usdt") or 0) > 0,
        },
        {
            "id": "C5",
            "statement": "largest single trade <= 50% of the net",
            "value": share,
            "passed": share is not None and float(share) <= 0.5,
        },
        {
            "id": "C6",
            "statement": "net > 0 in >= 2 of 3 time blocks",
            "value": hbase["extras"]["positive_time_blocks"],
            "passed": int(hbase["extras"]["positive_time_blocks"]) >= 2,
        },
    ]
    failed = [check["id"] for check in checks if not check["passed"]]
    powered = int(hbase.get("trades") or 0) >= SCREEN_MIN_TRADES
    if not failed:
        verdict, why = (
            "ADMIT_PAPER",
            "every registered criterion passed on the independent window: admitted to a paper lane, and to paper only",
        )
    elif not powered:
        verdict, why = (
            "INSUFFICIENT_EVIDENCE",
            f"the independent sample is too small to decide ({hbase.get('trades')} trades)",
        )
    elif failed == ["C1"]:
        verdict, why = (
            "INSUFFICIENT_EVIDENCE",
            f"the frequency aim is missed ({per_day} trades/day < {A.FREQUENCY_TARGET_PER_DAY}) while everything else is non-negative",
        )
    elif "C5" in failed and float(hbase.get("net_usdt") or 0) > 0:
        verdict, why = (
            "INSUFFICIENT_EVIDENCE",
            "one trade carries the net: the concentration criterion failed",
        )
    else:
        verdict, why = (
            "REJECT",
            f"decisive criterion failed on the independent window: {', '.join(failed)}",
        )
    return {
        "book": book_id,
        "verdict": verdict,
        "why": why,
        "checks": checks,
        "failed": failed,
        "screen_pass": True,
        "holdout_read": True,
    }


def evaluate(*, screen_only: bool = False) -> dict[str, Any]:
    from datetime import UTC, datetime

    registration = json.loads((OUT_DIR / "PREREGISTRATION.json").read_text(encoding="utf-8"))
    dev_window = dict(C.SPLITS["trend"]["DEV"])
    val_window = dict(C.SPLITS["trend"]["VAL"])
    as_of = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    result: dict[str, Any] = {
        "schema_version": "EDGE07_ACTIVE_RESEARCH_V1",
        "run_id": f"EDGE07-ACTIVE-{as_of.replace('-', '').replace(':', '')}",
        "as_of_utc": as_of,
        "registration": {
            "run_id": registration["run_id"],
            "registered_at_utc": registration["registered_at_utc"],
            "multiplicity": registration["multiplicity"],
            "frequency_target_per_day": registration["mission_target_trades_per_day"],
            "declared_cost_wall": registration["declared_cost_wall"],
        },
        "params": A.DECLARED_PARAMS,
        "timeframe": A.TIMEFRAME,
    }

    development, dev_provenance = hourly_corpus(holdout=False)
    result["corpus"] = {"development": dev_provenance}
    screen: dict[str, Any] = {}
    for book_id in A.DECLARED_PARAMS:
        screen[book_id] = {
            "DEV": run_candidate(
                book_id=book_id, bars_by_asset=development, window=dev_window, regime_rows=None
            ),
            "VAL": run_candidate(
                book_id=book_id, bars_by_asset=development, window=val_window, regime_rows=None
            ),
        }
    result["screen"] = screen
    result["screen_cost_wall_bps"] = screen[next(iter(screen))]["DEV"]["BASE"]["plane"][
        "round_trip_bps"
    ]

    holdout_readings: dict[str, Any] = {}
    readings: dict[str, Any] = {}
    if screen_only:
        for book_id in A.DECLARED_PARAMS:
            readings[book_id] = verdict_for(book_id, screen[book_id], None)
    else:
        holdout_bars, holdout_provenance = hourly_corpus(holdout=True)
        rows, context_meta = V.context_rows(holdout_bars)
        result["corpus"]["holdout"] = holdout_provenance
        result["corpus"]["holdout_context"] = context_meta
        for book_id in A.DECLARED_PARAMS:
            dev_gross = screen[book_id]["DEV"]["BASE"].get("gross_expectancy_usdt")
            if not dev_gross or dev_gross <= 0:
                readings[book_id] = verdict_for(book_id, screen[book_id], None)
                continue
            holdout_readings[book_id] = {
                "NEW_HOLDOUT": run_candidate(
                    book_id=book_id,
                    bars_by_asset=holdout_bars,
                    window=V.NEW_HOLDOUT,
                    regime_rows=rows,
                ),
                "VAL": screen[book_id]["VAL"],
            }
            readings[book_id] = verdict_for(book_id, screen[book_id], holdout_readings[book_id])

    result["holdout"] = holdout_readings
    result["readings"] = readings
    result["best_observed_gross_bps_per_trade"] = {
        book_id: (reading["DEV"]["BASE"].get("gross_bps_per_trade"))
        for book_id, reading in screen.items()
    }
    result["frequency"] = {
        book_id: {
            "screen_DEV_trades_per_day": reading["DEV"]["BASE"].get("trades_per_day"),
            "screen_VAL_trades_per_day": reading["VAL"]["BASE"].get("trades_per_day"),
            "holdout_trades_per_day": (
                holdout_readings.get(book_id, {})
                .get("NEW_HOLDOUT", {})
                .get("BASE", {})
                .get("trades_per_day")
            ),
        }
        for book_id, reading in screen.items()
    }
    result["hypothetical"] = True
    result["order_sent"] = False
    result["promotion"] = "NONE"
    return result


def summarise(payload: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        "WP-EDGE-07 TRACK C — ACTIVE multi-asset books at three trades a day",
        "=" * 78,
        f"run                 {payload['run_id']}",
        f"declared cost wall  {payload['registration']['declared_cost_wall']['round_trip_bps']:.2f} bps "
        f"per round trip at 1h",
        "",
        "the cost screen (C0), on DEV:",
    ]
    for book_id, reading in payload["screen"].items():
        dev = reading["DEV"]["BASE"]
        lines.append(
            f"  {book_id:<22} trades={dev.get('trades'):>6} net={dev.get('net_usdt'):>10} "
            f"gross/trade={dev.get('gross_expectancy_usdt'):>8} USDT "
            f"({dev.get('gross_bps_per_trade')} bps) per day={dev.get('trades_per_day')}"
        )
    lines.append("")
    lines.append("the verdicts:")
    for book_id, reading in payload["readings"].items():
        lines.append(f"  {book_id:<22} {reading['verdict']:<24} {reading['why'][:96]}")
        if reading.get("holdout_read"):
            base = payload["holdout"][book_id]["NEW_HOLDOUT"]["BASE"]
            stress = payload["holdout"][book_id]["NEW_HOLDOUT"]["2X_FEES"]
            extras = base["extras"]
            lines.append(
                f"      independent window: trades={base.get('trades')} "
                f"per day={base.get('trades_per_day')} net={base.get('net_usdt')} "
                f"expectancy={base.get('expectancy_usdt')} gross/trade={base.get('gross_expectancy_usdt')} "
                f"({base.get('gross_bps_per_trade')} bps) pf={base.get('profit_factor')} "
                f"2x-fees net={stress.get('net_usdt')}"
            )
            lines.append(
                f"      bootstrap 90% CI expectancy "
                f"[{extras['expectancy_ci_90_usdt']['low']}, {extras['expectancy_ci_90_usdt']['high']}] "
                f"| blocks {extras['positive_time_blocks']}/3 "
                f"| lag-1 {extras['serial_dependence'].get('lag1_autocorrelation')}"
            )
    return "\n".join(lines)


def write_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    import csv

    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for book_id, windows in (payload.get("screen") or {}).items():
        for window, scenarios in windows.items():
            for scenario, metrics in scenarios.items():
                if isinstance(metrics, dict) and "trade_rows" in metrics:
                    for trade in metrics["trade_rows"]:
                        rows.append(
                            {"book": book_id, "window": window, "scenario": scenario, **trade}
                        )
    for book_id, windows in (payload.get("holdout") or {}).items():
        for window, scenarios in windows.items():
            for scenario, metrics in scenarios.items():
                if isinstance(metrics, dict) and "trade_rows" in metrics:
                    for trade in metrics["trade_rows"]:
                        rows.append(
                            {"book": book_id, "window": window, "scenario": scenario, **trade}
                        )
    trades_path = outdir / "ACTIVE_TRADES.csv"
    fieldnames = [
        "book",
        "window",
        "scenario",
        "asset",
        "decision_ts",
        "duration_min",
        "notional",
        "gross",
        "fees",
        "price_costs",
        "net",
        "exit_reason",
    ]
    with trades_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    clean = _strip_rows(payload)
    json_path = outdir / "ACTIVE_RESEARCH.json"
    markdown_path = outdir / "ACTIVE_RESEARCH.md"
    json_path.write_text(
        json.dumps(clean, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render(clean), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path, "trades": trades_path}


def _prune(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _prune(value) for key, value in node.items() if key != "trade_rows"}
    if isinstance(node, list):
        return [_prune(item) for item in node]
    return node


def _strip_rows(payload: dict[str, Any]) -> dict[str, Any]:
    pruned: dict[str, Any] = _prune(payload)
    return pruned


def render(payload: dict[str, Any]) -> str:
    wall = payload["registration"]["declared_cost_wall"]["round_trip_bps"]
    lines = [
        "# WP-EDGE-07 Track C — an ACTIVE multi-asset book, and the wall it has to clear",
        "",
        f"*Run at `{payload['as_of_utc']}` (`{payload['run_id']}`), registered "
        f"`{payload['registration']['registered_at_utc']}` — before any candidate was measured, "
        f"with a multiplicity of {payload['registration']['multiplicity']}.*",
        "",
        "## 1. The wall, first",
        "",
        f"`COST_MODEL_V3` at a one-hour horizon is **{wall:.2f} bps per round trip**. Three trades a "
        f"day is therefore **{wall * 3:.0f} bps a day** of cost before any edge exists, and a book at "
        "this frequency must earn more than that per trade, on average, in gross terms. Every "
        "candidate below carries `cost_margin: 1.25`, so the instrument refuses a setup whose own "
        "objective cannot pay for itself — the frequency target is never a reason to force a trade.",
        "",
        "## 2. The verdicts",
        "",
        "| Book | Verdict | Why |",
        "| --- | --- | --- |",
    ]
    for book_id, reading in payload["readings"].items():
        lines.append(f"| `{book_id}` | **{reading['verdict']}** | {reading['why']} |")
    lines += [
        "",
        "## 3. The cost screen (C0), on the development windows",
        "",
        "| Book | Window | Trades | Per day | Gross/trade | Gross bps/trade | Net | Expectancy | PF |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for book_id, windows in payload["screen"].items():
        for window, scenarios in windows.items():
            metrics = scenarios["BASE"]
            lines.append(
                f"| `{book_id}` | {window} | {metrics.get('trades')} | {metrics.get('trades_per_day')} | "
                f"{metrics.get('gross_expectancy_usdt')} | {metrics.get('gross_bps_per_trade')} | "
                f"{metrics.get('net_usdt')} | {metrics.get('expectancy_usdt')} | "
                f"{metrics.get('profit_factor')} |"
            )
    if payload.get("holdout"):
        lines += [
            "",
            "## 4. The independent window, for the candidates that survived the screen",
            "",
            "| Book | Scenario | Trades | Per day | Gross | Net | Expectancy | PF | DD % | Sharpe | Largest share |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for book_id, windows in payload["holdout"].items():
            for scenario, metrics in windows["NEW_HOLDOUT"].items():
                lines.append(
                    f"| `{book_id}` | {scenario} | {metrics.get('trades')} | "
                    f"{metrics.get('trades_per_day')} | {metrics.get('gross_usdt')} | "
                    f"**{metrics.get('net_usdt')}** | {metrics.get('expectancy_usdt')} | "
                    f"{metrics.get('profit_factor')} | {metrics.get('max_drawdown_pct')} | "
                    f"{metrics.get('sharpe_annualised')} | {metrics.get('largest_trade_share_of_net')} |"
                )
        lines += ["", "### The added readings", ""]
        for book_id, windows in payload["holdout"].items():
            base = windows["NEW_HOLDOUT"]["BASE"]
            extras = base["extras"]
            lines += [
                f"- `{book_id}`: bootstrap 90 % expectancy CI "
                f"[{extras['expectancy_ci_90_usdt']['low']}, {extras['expectancy_ci_90_usdt']['high']}], "
                f"net CI [{extras['net_ci_90_usdt']['low']}, {extras['net_ci_90_usdt']['high']}]; "
                f"time blocks {extras['positive_time_blocks']}/3; lag-1 "
                f"{extras['serial_dependence'].get('lag1_autocorrelation')} against a "
                f"±{extras['serial_dependence'].get('band_2_over_sqrt_n')} band, runs z "
                f"{extras['serial_dependence'].get('runs_z')}; per asset "
                + ", ".join(
                    f"{asset} {row['trades']} trades {row['net_usdt']} USDT"
                    for asset, row in sorted(extras["by_asset_detail"].items())
                )
                + ".",
            ]
    lines += [
        "",
        "## 5. What this does not do",
        "",
        "- It promotes nothing: `promotion: NONE`, `order_sent: false`, no capital, no orders.",
        "- It tunes nothing: the parameters are the registered ones, screened in the registered",
        "  order, and the independent window is read once. A candidate that fails is reported with",
        "  its numbers and is not retried here.",
        "- A candidate that cannot reach three trades a day has not answered this mission's",
        "  question, and its verdict says so rather than passing on money alone.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--screen-only", action="store_true")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    payload = evaluate(screen_only=options.screen_only)
    if options.json:
        print(
            json.dumps(
                _strip_rows(payload), indent=2, ensure_ascii=False, sort_keys=True, default=str
            )
        )
        return 0
    written = write_artifacts(payload, Path(options.out))
    print(summarise(payload))
    for name, path in written.items():
        print(f"wrote {name:<9} {path.relative_to(REPO_ROOT)}")
    verdicts = {reading["verdict"] for reading in payload["readings"].values()}
    if verdicts == {"INSUFFICIENT_EVIDENCE"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
