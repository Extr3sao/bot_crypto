#!/usr/bin/env python
"""Independent verification of the WP-EDGE-01 artefacts.

Reads only the published artefacts of a run and re-derives everything it can on its own:

    python scripts/edge01_verify.py --dir reports/edge-recovery/WP-EDGE-01
    python scripts/edge01_verify.py --dir reports/edge-recovery/WP-EDGE-01 --self-test

This script does NOT import ``trading_bot``: it must be able to contradict the
implementation, so it re-implements the checks it needs (the admission rule, the
cost identity, the book band) from the CSVs and the JSON. If it imported the
simulator, a bug in the simulator would be checked by the same bug.

Checks
------
1. ``ARTIFACTS_PRESENT``            every inventoried file exists and matches its recorded digest
2. ``TRADE_SCHEMA``                 required columns, numeric and finite
3. ``NO_LOOKAHEAD_FILL``            every fill happens at the open AFTER the decision instant
4. ``OPEN_POSITION_NOT_DOUBLE_COUNTED``  the equity curve stays inside the book band
5. ``EQUITY_CONSERVATION``          final equity == start + sum(net of closed trades)
6. ``COST_IDENTITY``                net == (exit_fill - entry_fill) * qty - fees, per trade
7. ``COST_PLANE_APPLIED``           every fill carries exactly the declared plane's rates
8. ``EXIT_REASON_DOMAIN``           every exit reason is one the simulator declares
9. ``ZERO_TRADES_EXPLAINED``        a window with no trades must carry its refusal funnel
10. ``VERDICT_CONSISTENCY``         the recorded verdict equals the one the artefacts imply
11. ``EVIDENCE_FROM_METRICS``       the recorded evidence numbers equal the published metrics
12. ``BASELINE_PRESENT``            buy & hold exists for every split/asset and is cost-adjusted
13. ``RUN_IDENTIFIABLE``            every trade says which run produced it, and that run exists
14. ``MARKET_CONTEXT_ATTRIBUTION``  each trade's benchmark regime is the last benchmark day closed before its decision

``--self-test`` copies the artefacts to a temporary directory, injects each defect
in turn (double-counted equity, tampered fees, a fill before its decision, a
flipped verdict, tampered evidence, an unknown exit reason, a deleted scenario)
and requires the matching check to FAIL. A check nobody can break is not a check.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

START_EQUITY = 10_000.0
TRADE_COLUMNS = (
    "candidate",
    "strategy",
    "split",
    "scenario",
    "asset",
    "side",
    "signal_bar",
    "decision_ts",
    "entry_bar",
    "exit_bar",
    "entry_ts",
    "exit_ts",
    "duration_min",
    "entry_mid",
    "entry_fill",
    "exit_mid",
    "exit_fill",
    "qty",
    "notional",
    "gross",
    "price_costs",
    "fees",
    "net",
    "cost_bps_realised",
    "exit_reason",
    "market_context",
)
EXIT_REASONS = frozenset(
    {
        "stop_loss",
        "target",
        "trailing_stop",
        "invalidation",
        "ema_invalidation",
        "end_of_data",
    }
)
SCENARIO_NAMES = ("BASE", "2X_FEES", "ADVERSE")
BASE = "BASE"


class Fatal(Exception):
    """An artefact that cannot even be read: reported, never skipped silently."""


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


class Dataset:
    def __init__(self, root: Path) -> None:
        self.root = root
        for name in (
            "TRADES.csv",
            "EQUITY_CURVE.csv",
            "MARKET_CONTEXT.csv",
            "STRATEGY_RESULTS.json",
            "STRATEGY_RESULTS.md",
            "RUN_REPORT.json",
            "RUN_REPORT.md",
        ):
            if not (root / name).exists():
                raise Fatal(f"missing artefact {name} under {root}")
        self.trades = _read_csv(root / "TRADES.csv")
        self.equity = _read_csv(root / "EQUITY_CURVE.csv")
        self.results = json.loads((root / "STRATEGY_RESULTS.json").read_text(encoding="utf-8"))
        self.report = json.loads((root / "RUN_REPORT.json").read_text(encoding="utf-8"))

    def by_candidate_split(self, scenario: str | None = None) -> dict[tuple[str, str], list[dict[str, Any]]]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in self.trades:
            if scenario is not None and row["scenario"] != scenario:
                continue
            groups[(row["candidate"], row["split"])].append(row)
        return groups

    def equity_rows(self, candidate: str, split: str) -> list[tuple[int, float]]:
        out = [
            (int(r["ts"]), float(r["equity"]))
            for r in self.equity
            if r["candidate"] == candidate and r["split"] == split
        ]
        out.sort()
        return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _floats(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(row[key]) for row in rows]


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def check_artifacts_present(ds: Dataset) -> tuple[bool, str]:
    inventory = ds.report.get("artifacts") or {}
    if not inventory:
        return False, "RUN_REPORT.json carries no artefact inventory"
    problems: list[str] = []
    for name, entry in inventory.items():
        path = ds.root / name
        if not path.exists():
            problems.append(f"{name}: gone")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            problems.append(f"{name}: sha256 {actual[:12]} != {str(entry.get('sha256'))[:12]}")
        elif path.stat().st_size != entry.get("bytes"):
            problems.append(f"{name}: size {path.stat().st_size} != {entry.get('bytes')}")
    return (not problems), "; ".join(problems) or f"{len(inventory)} artefacts match their digests"


def check_trade_schema(ds: Dataset) -> tuple[bool, str]:
    if not ds.trades:
        return False, "TRADES.csv has no rows: a run without trades must still say why"
    missing = [column for column in TRADE_COLUMNS if column not in ds.trades[0]]
    if missing:
        return False, f"TRADES.csv is missing columns: {', '.join(missing)}"
    numeric = (
        "decision_ts",
        "entry_ts",
        "exit_ts",
        "entry_fill",
        "exit_fill",
        "qty",
        "notional",
        "gross",
        "price_costs",
        "fees",
        "net",
    )
    problems: list[str] = []
    for index, row in enumerate(ds.trades):
        for key in numeric:
            try:
                value = float(row[key])
            except (TypeError, ValueError):
                problems.append(f"row {index}: {key}={row[key]!r} is not numeric")
                continue
            if value != value or value in (float("inf"), float("-inf")):
                problems.append(f"row {index}: {key} is not finite")
        if problems and len(problems) > 5:
            break
    return (not problems), "; ".join(problems) or f"{len(ds.trades)} rows, {len(TRADE_COLUMNS)} columns"


def check_no_lookahead_fill(ds: Dataset) -> tuple[bool, str]:
    """A fill may not happen before the instant its decision was taken."""

    grid = {"15m": 900_000, "4h": 14_400_000, "1d": 86_400_000}
    timeframes = {
        candidate: str(payload["timeframe"])
        for candidate, payload in (ds.results.get("candidates") or {}).items()
    }
    problems: list[str] = []
    delayed: list[str] = []
    for row in ds.trades:
        entry_ts, decision_ts = int(row["entry_ts"]), int(row["decision_ts"])
        span = grid.get(timeframes.get(row["candidate"], ""), 0)
        if entry_ts < decision_ts:
            problems.append(
                f"{row['candidate']}/{row['split']}/{row['asset']}: filled {decision_ts - entry_ts} ms "
                "before the decision"
            )
        elif span and (entry_ts - decision_ts) % span:
            problems.append(
                f"{row['candidate']}/{row['split']}/{row['asset']}: filled "
                f"{entry_ts - decision_ts} ms after the decision, off the {row['candidate']} grid"
            )
        elif entry_ts != decision_ts:
            # A corpus gap skips bars; waiting for the asset's next existing bar is
            # legitimate, so it is counted and reported instead of failing.
            delayed.append(f"{row['candidate']}/{row['split']}/{row['asset']}")
        if int(row["exit_ts"]) < entry_ts:
            problems.append(f"{row['candidate']}/{row['split']}/{row['asset']}: exit before entry")
        if float(row["duration_min"]) < 0:
            problems.append(f"{row['candidate']}/{row['split']}/{row['asset']}: negative duration")
        if int(row["signal_bar"]) + 1 != int(row["entry_bar"]):
            problems.append(
                f"{row['candidate']}/{row['split']}/{row['asset']}: entry bar "
                f"{row['entry_bar']} is not signal bar {row['signal_bar']} + 1"
            )
        if span and entry_ts % span:
            problems.append(
                f"{row['candidate']}/{row['split']}/{row['asset']}: entry ts is off the bar grid"
            )
        if len(problems) > 5:
            break
    same_bar = sum(1 for row in ds.trades if int(row["exit_ts"]) == int(row["entry_ts"]))
    detail = f"{len(ds.trades)} fills at or after their decision"
    if same_bar:
        # Legitimate (a stop can be hit after the open of the bar that filled us),
        # but reported so it cannot hide inside an aggregate.
        detail += f"; {same_bar} stopped on the entry bar itself"
    if delayed:
        detail += f"; {len(delayed)} waited for the next existing bar (corpus gap)"
    return (not problems), "; ".join(problems) or detail


def check_open_position_not_double_counted(ds: Dataset) -> tuple[bool, str]:
    """Equity must stay within [start + closed - open, start + closed + open].

    The band is what a book can do: cash plus the marked value of the positions
    that are open at that instant. Counting a position twice (once as cash, once
    as exposure) breaks the ceiling immediately.
    """

    problems: list[str] = []
    for (candidate, split), rows in sorted(ds.by_candidate_split(BASE).items()):
        curve = ds.equity_rows(candidate, split)
        if not curve:
            continue
        entries = sorted(rows, key=lambda r: int(r["entry_ts"]))
        exits = sorted(rows, key=lambda r: int(r["exit_ts"]))
        entry_i = exit_i = 0
        closed = 0.0
        active: list[tuple[int, float]] = []
        for ts, equity in curve:
            while entry_i < len(entries) and int(entries[entry_i]["entry_ts"]) <= ts:
                active.append(
                    (int(entries[entry_i]["exit_ts"]), float(entries[entry_i]["notional"]))
                )
                entry_i += 1
            while exit_i < len(exits) and int(exits[exit_i]["exit_ts"]) <= ts:
                closed += float(exits[exit_i]["net"])
                exit_i += 1
            active = [item for item in active if item[0] > ts]
            open_notional = sum(notional for _exit_ts, notional in active)
            low = START_EQUITY + closed - open_notional - 1.0
            high = START_EQUITY + closed + open_notional + 1.0
            if not (low <= equity <= high):
                problems.append(
                    f"{candidate}/{split} @ {ts}: equity {equity:,.2f} outside "
                    f"[{low:,.2f}, {high:,.2f}] (closed {closed:,.2f}, open {open_notional:,.2f})"
                )
                break
    return (not problems), "; ".join(problems) or "every equity point lies inside the book band"


def check_equity_conservation(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    checked = 0
    for (candidate, split), rows in sorted(ds.by_candidate_split(BASE).items()):
        curve = ds.equity_rows(candidate, split)
        if not curve:
            problems.append(f"{candidate}/{split}: no equity curve")
            continue
        expected = START_EQUITY + sum(float(r["net"]) for r in rows)
        actual = curve[-1][1]
        checked += 1
        if abs(actual - expected) > 0.01:
            problems.append(
                f"{candidate}/{split}: final equity {actual:,.2f} != start + sum(net) {expected:,.2f}"
            )
    return (not problems), "; ".join(problems) or f"{checked} windows conserve cash"


def check_cost_identity(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    for row in ds.trades:
        qty = float(row["qty"])
        fees = float(row["fees"])
        net = float(row["net"])
        expected = (float(row["exit_fill"]) - float(row["entry_fill"])) * qty - fees
        if abs(net - expected) > 1e-4:
            problems.append(
                f"{row['candidate']}/{row['split']}/{row['scenario']}: net {net} != {expected:.6f}"
            )
        if abs(float(row["gross"]) - (float(row["exit_mid"]) - float(row["entry_mid"])) * qty) > 1e-4:
            problems.append(f"{row['candidate']}/{row['split']}: gross does not match the mids")
        notional = float(row["notional"])
        if notional > 0:
            costs = (fees + float(row["price_costs"])) / notional * 10_000.0
            if abs(costs - float(row["cost_bps_realised"])) > 0.05:
                problems.append(
                    f"{row['candidate']}/{row['split']}: cost_bps {row['cost_bps_realised']} "
                    f"!= {costs:.4f} recomputed"
                )
        if fees < 0 or float(row["price_costs"]) < 0:
            problems.append(f"{row['candidate']}/{row['split']}: negative cost component")
        if len(problems) > 5:
            break
    return (not problems), "; ".join(problems) or f"cost identity holds for {len(ds.trades)} trades"


def _planes_by_scenario(ds: Dataset) -> dict[tuple[str, str, str], dict[str, Any]]:
    planes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate, payload in (ds.results.get("candidates") or {}).items():
        for split, scenarios in payload["splits"].items():
            for scenario, data in scenarios.items():
                if data.get("plane"):
                    planes[(candidate, split, scenario)] = dict(data["plane"])
    return planes


def check_cost_plane_applied(ds: Dataset) -> tuple[bool, str]:
    """The cost the artefacts CLAIM must be the cost each fill actually paid.

    Per trade, the realised fee rate is recomputed from the money and the two
    fills, and the realised price rate from the fill against its mid. Both must
    equal the components of the plane that scenario declares. This is the check
    that a scenario cannot be published but not applied, and that no cost is
    silently missing from a fill.
    """

    problems: list[str] = []
    declared = ds.report.get("cost_scenarios") or {}
    planes = _planes_by_scenario(ds)
    checked = 0
    for name in declared:
        if not any(key[2] == name for key in planes):
            problems.append(f"{name}: no cost plane recorded for this scenario")
    for name in ("2X_FEES", "ADVERSE"):
        base = next((p for key, p in planes.items() if key[2] == BASE), None)
        other = next((p for key, p in planes.items() if key[2] == name), None)
        if base is None or other is None:
            continue
        fee_mult, slip_mult = (float(x) for x in declared.get(name, (2.0, 1.0)))
        want_fee = float(base["fee_bps"]) * fee_mult
        want_price = (
            float(base["spread_bps"]) + slip_mult * (float(base["slippage_bps"]) + float(base["impact_bps"]))
        )
        if abs(float(other["fee_bps"]) - want_fee) > 0.01:
            problems.append(f"{name}: plane fee {other['fee_bps']} != {want_fee:.4f}")
        got_price = float(other["spread_bps"]) + float(other["slippage_bps"]) + float(other["impact_bps"])
        if abs(got_price - want_price) > 0.01:
            problems.append(f"{name}: plane price cost {got_price:.4f} != {want_price:.4f}")

    for row in ds.trades:
        key = (row["candidate"], row["split"], row["scenario"])
        plane = planes.get(key)
        if plane is None:
            problems.append(f"{key[0]}/{key[1]}/{key[2]}: no plane recorded")
            break
        checked += 1
        qty = float(row["qty"])
        entry_fill = float(row["entry_fill"])
        exit_fill = float(row["exit_fill"])
        entry_mid = float(row["entry_mid"])
        exit_mid = float(row["exit_mid"])
        weight = qty * (entry_fill + exit_fill) / 2.0
        if weight <= 0:
            continue
        realised_fee = float(row["fees"]) / weight * 10_000.0
        if abs(realised_fee - float(plane["fee_bps"])) > 0.05:
            problems.append(
                f"{key[0]}/{key[1]}/{key[2]}: fee rate {realised_fee:.4f} bps "
                f"!= declared {float(plane['fee_bps']):.4f}"
            )
        half = (
            float(plane["spread_bps"])
            + float(plane["slippage_bps"])
            + float(plane["impact_bps"])
        ) / 2.0
        for label, fill, mid in (("entry", entry_fill, entry_mid), ("exit", exit_fill, exit_mid)):
            if mid <= 0:
                continue
            realised = abs(fill - mid) / mid * 10_000.0
            if abs(realised - half) > 0.05:
                problems.append(
                    f"{key[0]}/{key[1]}/{key[2]}: {label} price cost {realised:.4f} bps "
                    f"!= declared {half:.4f}"
                )
        if len(problems) > 5:
            break
    if not checked:
        return False, "no trade to reconcile against a cost plane"
    return (not problems), "; ".join(problems) or (
        f"{checked} fills pay exactly the declared rates; {len(planes)} planes recorded"
    )


def check_exit_reason_domain(ds: Dataset) -> tuple[bool, str]:
    unknown = sorted({row["exit_reason"] for row in ds.trades} - EXIT_REASONS)
    return (not unknown), (
        f"unknown exit reasons: {', '.join(unknown)}" if unknown else "every exit reason is declared"
    )


def check_zero_trades_explained(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    for candidate, payload in (ds.results.get("candidates") or {}).items():
        for split, scenarios in payload["splits"].items():
            for scenario, data in scenarios.items():
                if int(data.get("trades") or 0) == 0:
                    refusals = data.get("candidate_refusals") or {}
                    if not refusals:
                        problems.append(
                            f"{candidate}/{split}/{scenario}: zero trades with no refusal funnel"
                        )
                    if data.get("net_usdt") not in (0, 0.0):
                        problems.append(
                            f"{candidate}/{split}/{scenario}: zero trades but net "
                            f"{data.get('net_usdt')} (PnL cannot come from nowhere)"
                        )
    return (not problems), "; ".join(problems) or "every empty window carries its reasons"


def _recompute_verdict(splits: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    """The admission rule, re-implemented here from the published metrics."""

    oos = splits["OOS"][BASE]
    net = float(oos.get("net_usdt") or 0.0)
    trades = int(oos.get("trades") or 0)
    expectancy = float(oos.get("expectancy_usdt") or 0.0)
    share = oos.get("largest_trade_share_of_net")
    min_trades = int(criteria["min_oos_trades"])
    fails = []
    if net <= 0:
        fails.append("net")
    if expectancy <= 0:
        fails.append("expectancy")
    if share is not None and float(share) > float(criteria["max_single_trade_share_of_net"]):
        fails.append("single_trade")
    positive_regimes = sum(
        1 for value in (oos.get("by_regime") or {}).values() if float(value.get("net") or 0) > 0
    )
    if positive_regimes < int(criteria["require_min_positive_regimes"]):
        fails.append("regimes")
    if float(splits["OOS"].get("2X_FEES", {}).get("net_usdt") or 0.0) <= 0:
        fails.append("stress")
    window_nets = [float(splits[name][BASE].get("net_usdt") or 0.0) for name in ("DEV", "VAL", "OOS")]
    every_negative = all(value <= 0 for value in window_nets)
    if trades < min_trades:
        fails.append("unpowered")
    if net <= 0 and (trades >= min_trades or every_negative):
        verdict = "REJECT"
    elif fails:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "ADMIT"
    power = (
        f"powered (oos n={trades} >= {min_trades})"
        if trades >= min_trades
        else f"underpowered (oos n={trades} < {min_trades})"
    )
    return {
        "verdict": verdict,
        "power": power,
        "fails": fails,
        "evidence": {
            "window_net_usdt": dict(zip(("DEV", "VAL", "OOS"), window_nets, strict=True)),
            "oos_trades": trades,
            "min_oos_trades": min_trades,
            "oos_net_usdt": net,
            "oos_2x_fees_net_usdt": float(splits["OOS"].get("2X_FEES", {}).get("net_usdt") or 0.0),
            "positive_regimes_oos": positive_regimes,
        },
    }


def check_verdict_consistency(ds: Dataset) -> tuple[bool, str]:
    criteria = ds.report.get("admission_criteria") or {}
    problems: list[str] = []
    checked = 0
    for candidate, payload in (ds.results.get("candidates") or {}).items():
        recomputed = _recompute_verdict(payload["splits"], criteria)
        checked += 1
        if payload.get("verdict") != recomputed["verdict"]:
            problems.append(
                f"{candidate}: recorded {payload.get('verdict')} but the artefacts imply "
                f"{recomputed['verdict']} (failing: {', '.join(recomputed['fails']) or 'none'})"
            )
        if payload.get("verdict_power") != recomputed["power"]:
            problems.append(
                f"{candidate}: power {payload.get('verdict_power')!r} != {recomputed['power']!r}"
            )
        if payload.get("verdict") != "ADMIT" and not payload.get("verdict_reasons"):
            problems.append(f"{candidate}: a non-admission without a single stated reason")
        if payload.get("verdict") == "ADMIT" and recomputed["fails"]:
            problems.append(f"{candidate}: admitted while failing {recomputed['fails']}")
    return (not problems), "; ".join(problems) or f"{checked} verdicts recomputed from the metrics"


def check_evidence_from_metrics(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    for candidate, payload in (ds.results.get("candidates") or {}).items():
        evidence = payload.get("verdict_evidence") or {}
        recomputed = _recompute_verdict(
            payload["splits"], ds.report.get("admission_criteria") or {}
        )["evidence"]
        for key, expected in recomputed.items():
            recorded = evidence.get(key)
            if key == "window_net_usdt":
                recorded = {k: round(float(v), 4) for k, v in (recorded or {}).items()}
                expected = {k: round(float(v), 4) for k, v in expected.items()}
            elif isinstance(expected, float):
                recorded = round(float(recorded), 4) if recorded is not None else None
                expected = round(expected, 4)
            if recorded != expected:
                problems.append(f"{candidate}.{key}: recorded {recorded!r} != {expected!r}")
    return (not problems), "; ".join(problems) or "recorded evidence equals the published metrics"


def check_baseline_present(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    seen = 0
    for candidate, payload in (ds.results.get("candidates") or {}).items():
        for split, scenarios in payload["splits"].items():
            for scenario, data in scenarios.items():
                baseline = data.get("buy_and_hold") or {}
                if not baseline:
                    problems.append(f"{candidate}/{split}/{scenario}: no buy & hold baseline")
                    continue
                for asset, entry in baseline.items():
                    seen += 1
                    if entry.get("return_pct") is None:
                        problems.append(f"{candidate}/{split}/{asset}: baseline has no return")
                        continue
                    expected = START_EQUITY * (1 + float(entry["return_pct"]) / 100.0)
                    if abs(float(entry["equity_final"]) - expected) > 0.05:
                        problems.append(f"{candidate}/{split}/{asset}: baseline equity inconsistent")
                    if int(entry.get("bars") or 0) < 2:
                        problems.append(f"{candidate}/{split}/{asset}: baseline window too short")
    return (not problems), "; ".join(problems) or f"{seen} baselines present and consistent"


def check_run_identifiable(ds: Dataset) -> tuple[bool, str]:
    """A trade must name the run that produced it, not the ruleset that printed it."""

    runs = set(ds.results.get("candidates") or {})
    problems: list[str] = []
    unnamed = sorted({row["candidate"] for row in ds.trades} - runs)
    if unnamed:
        problems.append(f"trades name runs that do not exist: {', '.join(unnamed)}")
    missing = sorted(run for run in runs if run not in {row["candidate"] for row in ds.trades})
    if missing and not problems:
        problems.append(f"runs with no trade rows: {', '.join(missing)}")
    strategies = {row["strategy"] for row in ds.trades}
    if any(not strategy for strategy in strategies):
        problems.append("a trade row does not name the strategy that printed it")
    return (not problems), "; ".join(problems) or (
        f"{len(runs)} runs, {len(strategies)} strategies, every trade attributed"
    )


def check_market_context_attribution(ds: Dataset) -> tuple[bool, str]:
    """The benchmark label of a trade must be the one readable at its decision.

    The claim under test is that the bull/bear/sideways coverage of a run is a
    property of the MARKET, not of the candidate: the label is looked up here
    from ``MARKET_CONTEXT.csv`` alone (last benchmark day whose close is at or
    before ``decision_ts``), so a label that was read from a later day — a
    look-ahead — cannot survive this check, and neither can a label invented for
    a day the benchmark never closed.
    """

    rows = _read_csv(ds.root / "MARKET_CONTEXT.csv")
    if not rows:
        return False, "MARKET_CONTEXT.csv is empty: every trade cites a benchmark label"
    declared = ds.report.get("market_context") or {}
    rule = str(declared.get("rule") or "")
    if not rule:
        return False, "RUN_REPORT.json does not state the market-context rule"
    labels = list(declared.get("labels") or ["BULL", "BEAR", "SIDEWAYS", "UNDEFINED"])
    problems: list[str] = []
    days: list[tuple[int, str]] = []
    for row in rows:
        try:
            close_ms = int(row["close_ms"])
        except (TypeError, ValueError):
            problems.append(f"MARKET_CONTEXT.csv: close_ms={row.get('close_ms')!r} is not an int")
            continue
        label = str(row.get("label"))
        if label not in labels:
            problems.append(f"MARKET_CONTEXT.csv: label {label!r} is not in the declared set")
        days.append((close_ms, label))
    if [ts for ts, _ in days] != sorted(ts for ts, _ in days):
        problems.append("MARKET_CONTEXT.csv is not ordered by close_ms")
    if len({ts for ts, _ in days}) != len(days):
        problems.append("MARKET_CONTEXT.csv repeats a benchmark day")
    declared_days = declared.get("days")
    if declared_days is not None and int(declared_days) != len(days):
        problems.append(f"RUN_REPORT.json declares {declared_days} benchmark days, file has {len(days)}")
    last_label_ms = days[-1][0] if days else None
    if declared.get("last_close_ms") not in (None, last_label_ms):
        problems.append(
            f"RUN_REPORT.json last_close_ms {declared.get('last_close_ms')} != {last_label_ms}"
        )

    ts_list = [ts for ts, _ in days]
    counts: dict[str, int] = {}
    for row in ds.trades:
        expected = "UNDEFINED"
        index = bisect.bisect_right(ts_list, int(row["decision_ts"])) - 1
        if index >= 0:
            expected = days[index][1]
        actual = row.get("market_context")
        counts[actual or "MISSING"] = counts.get(actual or "MISSING", 0) + 1
        if actual != expected:
            problems.append(
                f"{row['candidate']}/{row['split']}/{row['asset']} @ {row['decision_ts']}: "
                f"market_context {actual!r} != {expected!r} readable at that instant"
            )
        if len(problems) > 5:
            break
    spread = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return (not problems), "; ".join(problems) or (
        f"{len(ds.trades)} trades attributed from {len(days)} benchmark days ({spread})"
    )


CHECKS = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("TRADE_SCHEMA", check_trade_schema),
    ("NO_LOOKAHEAD_FILL", check_no_lookahead_fill),
    ("OPEN_POSITION_NOT_DOUBLE_COUNTED", check_open_position_not_double_counted),
    ("EQUITY_CONSERVATION", check_equity_conservation),
    ("COST_IDENTITY", check_cost_identity),
    ("COST_PLANE_APPLIED", check_cost_plane_applied),
    ("EXIT_REASON_DOMAIN", check_exit_reason_domain),
    ("ZERO_TRADES_EXPLAINED", check_zero_trades_explained),
    ("VERDICT_CONSISTENCY", check_verdict_consistency),
    ("EVIDENCE_FROM_METRICS", check_evidence_from_metrics),
    ("BASELINE_PRESENT", check_baseline_present),
    ("RUN_IDENTIFIABLE", check_run_identifiable),
    ("MARKET_CONTEXT_ATTRIBUTION", check_market_context_attribution),
)


def run_checks(root: Path) -> list[dict[str, Any]]:
    ds = Dataset(root)
    out: list[dict[str, Any]] = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(ds)
        except Fatal:
            raise
        except Exception as exc:  # a crashing check is a failed check, never a skip
            ok, detail = False, f"check raised {type(exc).__name__}: {exc}"
        out.append({"check": name, "ok": bool(ok), "detail": detail})
    return out


# --------------------------------------------------------------------------- #
# Self-test: every check must be breakable
# --------------------------------------------------------------------------- #


def _rewrite_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _mutate_equity_double_count(root: Path) -> None:
    """Reproduce the original defect: an open position counted twice at its entry."""
    rows = _read_csv(root / "EQUITY_CURVE.csv")
    trades = _read_csv(root / "TRADES.csv")
    at_entry = {
        (row["candidate"], row["split"], int(row["entry_ts"])): float(row["notional"])
        for row in trades
        if row["scenario"] == BASE
    }
    for row in rows:
        key = (row["candidate"], row["split"], int(row["ts"]))
        if key in at_entry:
            row["equity"] = f"{float(row['equity']) + at_entry[key]:.10f}"
    _rewrite_csv(root / "EQUITY_CURVE.csv", rows)


def _mutate_fee_tamper(root: Path) -> None:
    rows = _read_csv(root / "TRADES.csv")
    rows[0]["fees"] = f"{float(rows[0]['fees']) * 1.5 + 1.0:.10f}"
    _rewrite_csv(root / "TRADES.csv", rows)


def _mutate_lookahead_fill(root: Path) -> None:
    rows = _read_csv(root / "TRADES.csv")
    rows[0]["entry_ts"] = str(int(rows[0]["decision_ts"]) - 900_000)
    _rewrite_csv(root / "TRADES.csv", rows)


def _mutate_exit_reason(root: Path) -> None:
    rows = _read_csv(root / "TRADES.csv")
    rows[0]["exit_reason"] = "magic_exit"
    _rewrite_csv(root / "TRADES.csv", rows)


def _mutate_verdict_flip(root: Path) -> None:
    payload = json.loads((root / "STRATEGY_RESULTS.json").read_text(encoding="utf-8"))
    target = next(
        entry
        for entry in payload["candidates"].values()
        if entry.get("verdict") != "ADMIT"
    )
    target["verdict"] = "ADMIT"
    (root / "STRATEGY_RESULTS.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _mutate_evidence(root: Path) -> None:
    payload = json.loads((root / "STRATEGY_RESULTS.json").read_text(encoding="utf-8"))
    candidate = next(iter(payload["candidates"].values()))
    candidate["verdict_evidence"]["oos_net_usdt"] = (
        float(candidate["verdict_evidence"].get("oos_net_usdt") or 0.0) + 5_000.0
    )
    (root / "STRATEGY_RESULTS.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _mutate_delete_scenario(root: Path) -> None:
    """Publish the fee-stress scenario with BASE fees: a stress that never happened."""
    rows = _read_csv(root / "TRADES.csv")
    for row in rows:
        if row["scenario"] == "2X_FEES":
            row["fees"] = f"{float(row['fees']) / 2.0:.10f}"
    _rewrite_csv(root / "TRADES.csv", rows)


def _mutate_market_context(root: Path) -> None:
    """Re-label every trade with a neighbouring regime: the benchmark did not say that."""
    rows = _read_csv(root / "TRADES.csv")
    rotation = {"BULL": "BEAR", "BEAR": "SIDEWAYS", "SIDEWAYS": "BULL", "UNDEFINED": "BULL"}
    for row in rows:
        row["market_context"] = rotation.get(row["market_context"], "BULL")
    _rewrite_csv(root / "TRADES.csv", rows)


MUTATIONS: tuple[tuple[str, str, Any], ...] = (
    ("M1_double_counted_position", "OPEN_POSITION_NOT_DOUBLE_COUNTED", _mutate_equity_double_count),
    ("M2_tampered_fee", "COST_IDENTITY", _mutate_fee_tamper),
    ("M3_fill_before_decision", "NO_LOOKAHEAD_FILL", _mutate_lookahead_fill),
    ("M4_unknown_exit_reason", "EXIT_REASON_DOMAIN", _mutate_exit_reason),
    ("M5_flipped_verdict", "VERDICT_CONSISTENCY", _mutate_verdict_flip),
    ("M6_tampered_evidence", "EVIDENCE_FROM_METRICS", _mutate_evidence),
    ("M7_scenario_not_applied", "COST_PLANE_APPLIED", _mutate_delete_scenario),
    ("M8_relabelled_market_context", "MARKET_CONTEXT_ATTRIBUTION", _mutate_market_context),
)


def self_test(root: Path) -> dict[str, Any]:
    baseline = {entry["check"]: entry["ok"] for entry in run_checks(root)}
    results: list[dict[str, Any]] = []
    for name, expected, mutate in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "artefacts"
            shutil.copytree(root, copy)
            mutate(copy)
            try:
                after = {entry["check"]: entry for entry in run_checks(copy)}
                failed = sorted(k for k, v in after.items() if not v["ok"])
            except Fatal as exc:
                failed = [f"FATAL: {exc}"]
                after = {}
            results.append(
                {
                    "mutation": name,
                    "expected_check": expected,
                    "detected": failed,
                    "expected_check_failed": expected in failed,
                    "detail": after.get(expected, {}).get("detail", "; ".join(failed)),
                }
            )
    return {
        "baseline_all_green": all(baseline.values()),
        "baseline": baseline,
        "mutations": results,
        "all_detected": all(item["expected_check_failed"] for item in results),
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="reports/edge-recovery/WP-EDGE-01")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    root = Path(args.dir)
    try:
        checks = run_checks(root)
    except Fatal as exc:
        print(f"FATAL: {exc}")
        return 2

    passed = sum(1 for entry in checks if entry["ok"])
    for entry in checks:
        print(f"[{'PASS' if entry['ok'] else 'FAIL'}] {entry['check']:<34} {entry['detail']}")
    print(f"\nchecks: {passed}/{len(checks)} passed")

    payload: dict[str, Any] = {
        "dir": str(root),
        "checks": checks,
        "passed": passed,
        "total": len(checks),
    }
    failed = 0
    if args.self_test:
        report = self_test(root)
        payload["self_test"] = report
        print("\n-- self-test (each mutation must break its check) --")
        for item in report["mutations"]:
            status = "PASS" if item["expected_check_failed"] else "FAIL"
            print(
                f"[{status}] {item['mutation']:<28} -> {item['expected_check']} "
                f"(failed: {', '.join(item['detected']) or 'nothing'})"
            )
        print(
            f"mutations detected: {sum(1 for m in report['mutations'] if m['expected_check_failed'])}"
            f"/{len(report['mutations'])}"
        )
        failed += 0 if report["all_detected"] else 1
        failed += 0 if report["baseline_all_green"] else 1

    failed += len(checks) - passed
    payload["failed"] = failed

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
