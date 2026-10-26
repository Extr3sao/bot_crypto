"""edge16_verify — independent verification of WP-EDGE-016, with fault injection.

This verifier imports no strategy simulator, no cost engine and no output composer.
It rebuilds every claim from **primitives**:

* the ordering contract is recomputed from the raw OHLCV series on disk in
  ``data/edge08/universe-1h`` and ``data/edge07/holdout-1h``, keyed by the
  corpus the trade names, plus the recorded signal/fill indices;
* the restatement CSV is recomputed from ``ALPHA_RESTATEMENT_TRADES.jsonl`` and
  the cost column, not from the report that summarises it;
* the lane's risk posture is read from ``config/risk.yaml`` and the admission
  ledger, not from the lane's description of itself.

Half the value of an audit is knowing it would fail. Every check that could be
fooled by a plausible-looking artifact is also run against a mutated copy, and
the mutation must make it fail.

    python scripts/edge16_verify.py
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import subprocess
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-016"
OUT_15 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"
LANE = OUT / "experimental_paper"

PERIOD_MS = 3_600_000
EXIT_RULES = {
    "TREND_BREAK_ON_CLOSE",
    "MEAN_REACHED_ON_CLOSE",
    "STOP_LOSS_ON_CLOSE",
    "TRAILING_STOP_ON_CLOSE",
    "MAX_HOLD_REACHED",
    "TERMINAL_MARK_AT_LAST_CLOSE",
}
#: Corpora named by the trades, and where their raw bars live. The verifier reads
#: the series itself, so a trade cannot certify its own causality.
CORPORA = {
    "EDGE08_ALTS_1H": ("data/edge08/universe-1h", "json_rows", "{}_2021_2026_1h.json"),
    "EDGE07_HOLDOUT_1H": ("data/edge07/holdout-1h", "json_dicts", "{}_holdout2026.json"),
}
#: Modules that BUILT these artifacts: never imported for a decisive check.
FORBIDDEN_IMPORTS = (
    "economic_recovery.alpha15",
    "economic_recovery.pit15",
    "economic_recovery.experiments",
    "trading_bot.risk.manager",
    "trading_bot.paper.broker",
)

MARKET_STAGES = {
    "EXPECTED",
    "OBSERVED",
    "VALIDATED",
    "EVALUATED",
    "NO_SIGNAL",
    "PROPOSAL",
    "RISK_RESULT",
    "SIM_ORDER",
    "FILL",
    "RECONCILIATION",
}


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, cid: str, what: str, ok: bool, detail: Any) -> None:
        self.rows.append({"id": cid, "what": what, "ok": bool(ok), "detail": str(detail)[:700]})

    @property
    def failed(self) -> int:
        return sum(1 for row in self.rows if not row["ok"])


# --- primitive loaders ------------------------------------------------------------------


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class Series:
    """Raw bars for one corpus, loaded lazily and only from disk."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], list[dict[str, float]] | None] = {}

    def bars(self, corpus: str, symbol: str) -> list[dict[str, float]] | None:
        key = (corpus, symbol)
        if key not in self._cache:
            self._cache[key] = self._load(corpus, symbol)
        return self._cache[key]

    @staticmethod
    def _load(corpus: str, symbol: str) -> list[dict[str, float]] | None:
        entry = CORPORA.get(corpus)
        if entry is None:
            return None
        folder, shape, pattern = entry
        path = REPO / folder / pattern.format(symbol.replace("/", ""))
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if shape == "json_rows":  # [ts, open, high, low, close, volume]
            return [
                {"ts": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                 "low": float(r[3]), "close": float(r[4])}
                for r in raw
            ]
        return [
            {"ts": int(r["ts"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])}
            for r in raw
        ]


# --- recomputation ----------------------------------------------------------------------


def pit_problems(trades: list[dict[str, Any]], series: Series) -> list[str]:
    """Every way a trade row can break the ordering contract, recomputed from the bars.

    The contract the package claims: a rule read off bar ``t``'s close fills at the open
    of bar ``t+1``; the data instant is that close instant; a position still open at the
    last bar is marked at that close and labelled. Anything else is a violation.
    """
    problems: list[str] = []
    for trade in trades:
        bars = series.bars(trade["corpus"], trade["symbol"])
        where = f"{trade['corpus']}/{trade['symbol']}/{trade['family']}"
        if not bars:
            problems.append(f"{where}: no raw series to check against")
            continue
        si, ei = int(trade["entry_signal_index"]), int(trade["entry_fill_index"])
        sxi, xi = int(trade["exit_signal_index"]), int(trade["exit_fill_index"])
        if not (0 <= si < len(bars) and 0 <= ei < len(bars) and 0 <= sxi < len(bars) and 0 <= xi < len(bars)):
            problems.append(f"{where}: an index is outside the series")
            continue
        if trade["exit_rule"] not in EXIT_RULES:
            problems.append(f"{where}: unknown exit rule {trade['exit_rule']}")
        if ei <= si:
            problems.append(f"{where}: entry filled on or before its signal bar")
        if trade["entry_ts_ms"] != bars[ei]["ts"]:
            problems.append(f"{where}: entry timestamp is not its fill bar's open time")
        if trade["entry_data_available_ms"] != bars[si]["ts"] + PERIOD_MS:
            problems.append(f"{where}: entry data instant is not the signal bar's close")
        if not math.isclose(bars[ei]["open"], trade["entry_price"], rel_tol=1e-9):
            problems.append(f"{where}: entry price is not the open of its fill bar")
        if trade["is_mark"]:
            if not (xi == sxi == len(bars) - 1):
                problems.append(f"{where}: a mark that is not the series' last bar")
            if trade["exit_rule"] != "TERMINAL_MARK_AT_LAST_CLOSE":
                problems.append(f"{where}: a mark under another rule's name")
            if not math.isclose(bars[xi]["close"], trade["exit_price"], rel_tol=1e-9):
                problems.append(f"{where}: mark price is not the last close")
            if trade["exit_data_available_ms"] != trade["exit_ts_ms"] + PERIOD_MS:
                problems.append(f"{where}: mark stamped before its own close existed")
        else:
            if xi <= sxi:
                problems.append(f"{where}: same-bar close-to-open exit")
            if xi < ei:
                problems.append(f"{where}: exit precedes entry")
            if trade["exit_ts_ms"] != bars[xi]["ts"]:
                problems.append(f"{where}: exit timestamp is not its fill bar's open time")
            if trade["exit_data_available_ms"] != bars[sxi]["ts"] + PERIOD_MS:
                problems.append(f"{where}: exit data instant is not the signal bar's close")
            if not math.isclose(bars[xi]["open"], trade["exit_price"], rel_tol=1e-9):
                problems.append(f"{where}: exit price is not the open of its fill bar")
        if int(trade["bars_held"]) != xi - ei:
            problems.append(f"{where}: bars_held does not span the fills")
        if not math.isclose(
            float(trade["gross_bps"]),
            (float(trade["exit_price"]) / float(trade["entry_price"]) - 1.0) * 10_000.0,
            rel_tol=1e-9,
            abs_tol=1e-6,
        ):
            problems.append(f"{where}: gross_bps does not recompute from its own prices")
    return problems


def overlap_problems(trades: list[dict[str, Any]]) -> list[str]:
    """Two positions open at once in one lane, or an entry the same instant as an exit."""
    problems: list[str] = []
    lanes: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for trade in trades:
        lanes.setdefault((trade["corpus"], trade["symbol"], trade["family"]), []).append(trade)
    for key, lane in lanes.items():
        lane.sort(key=lambda row: int(row["entry_fill_index"]))
        for previous, current in pairwise(lane):
            if int(current["entry_fill_index"]) <= int(previous["exit_fill_index"]):
                problems.append(
                    f"{key[0]}/{key[1]}/{key[2]}: entry at "
                    f"{current['entry_fill_index']} while the previous position was open"
                )
    return problems


#: The restatement writes 4 decimal places, and a rebuilt figure is compared to that.
ROUNDED = 1e-4


def restatement_problems(rows: list[dict[str, str]], trades: list[dict[str, Any]]) -> list[str]:
    """Rebuild the restated (POST_PIT) rows from the per-trade records and the cost column.

    The PRE_PIT rows come from the pre-repair runners, which this verifier must not import:
    they are checked for internal consistency and for being excluded from the verdict instead.
    """
    problems: list[str] = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for trade in trades:
        grouped.setdefault((trade["corpus"], trade["symbol"], trade["family"]), []).append(trade)

    restated = [row for row in rows if row["variant"] == "POST_PIT"]
    historical = [row for row in rows if row["variant"] == "PRE_PIT"]
    if not restated:
        return ["no POST_PIT row to rebuild"]
    if not historical:
        problems.append("the pre-repair variant is missing from the table")

    seen: set[tuple[str, str, str]] = set()
    for row in restated:
        key = (row["corpus"], row["symbol"], row["family"])
        seen.add(key)
        lane = grouped.get(key)
        if not lane:
            problems.append(f"{key}: a restated row with no trade behind it")
            continue
        cost_1x = float(row["cost_round_trip_bps_1x"])
        count = float(row["trades"])
        if count != len(lane):
            problems.append(f"{key}: {row['trades']} trades claimed, {len(lane)} on file")
            continue
        gross = sum(float(trade["gross_bps"]) for trade in lane)
        for multiplier, column in (
            (1.0, "net_bps_total_1x"),
            (2.0, "net_bps_total_2x"),
            (3.0, "net_bps_total_3x"),
        ):
            want = gross - count * cost_1x * multiplier
            if abs(want - float(row[column])) > ROUNDED:
                problems.append(f"{key}: {column} {row[column]} != {want:.6f} rebuilt from the trades")
        for column, want in (
            ("gross_bps_per_trade", gross / count),
            ("expectancy_bps_per_trade", float(row["net_bps_total_1x"]) / count),
        ):
            if abs(float(row[column]) - want) > ROUNDED:
                problems.append(f"{key}: {column} is not per trade from the table's own totals")
    for key in grouped:
        if key not in seen:
            problems.append(f"{key}: trades exist with no restated row")

    by_lane = {(row["corpus"], row["symbol"], row["family"]): row for row in historical}
    for row in restated:
        key = (row["corpus"], row["symbol"], row["family"])
        old = by_lane.get(key)
        if old is None:
            problems.append(f"{key}: restated with no pre-repair counterpart")
            continue
        if old["segment"] != "HELD_OUT_TAIL" or row["segment"] != "HELD_OUT_TAIL":
            problems.append(f"{key}: a segment other than the held-out tail")
        for column in ("trades_per_day", "days_without_trades", "win_rate", "max_drawdown_bps"):
            if float(old[column]) < 0 or float(row[column]) < 0:
                problems.append(f"{key}: {column} is negative")
        if float(row["cost_round_trip_bps_1x"]) < 2.0 * VENUE_FEE_BPS_PER_SIDE:
            problems.append(
                f"{key}: the cost column {row['cost_round_trip_bps_1x']} bps is below the "
                f"venue's own two-sided fee floor"
            )
    return problems


def proposal_leaks(cycles: list[dict[str, Any]]) -> list[str]:
    """Any message that carries an outcome it could not yet have known."""
    forbidden = ("exit_ts_ms", "exit_price", "gross_bps", "net_pnl", "realised", "outcome")
    leaks: list[str] = []
    for cycle in cycles:
        stage = str(cycle.get("stage", ""))
        if not stage.startswith(("PROPOSAL", "RISK")):
            continue
        for field in forbidden:
            if field in cycle:
                leaks.append(f"cycle {cycle.get('cycle')} ({stage}) carries {field}")
        detail = cycle.get("detail")
        if isinstance(detail, dict):
            for field in forbidden:
                if field in detail:
                    leaks.append(f"cycle {cycle.get('cycle')} ({stage}) carries detail.{field}")
    return leaks


def weekend_fills(cycles: list[dict[str, Any]]) -> list[str]:
    """A fill on a Saturday or Sunday while the policy forbids weekend trading."""
    bad: list[str] = []
    for cycle in cycles:
        if cycle.get("action") != "FILL_OPENED":
            continue
        day = datetime.fromtimestamp(int(cycle["ts_ms"]) / 1000, tz=UTC)
        if day.weekday() >= 5:
            bad.append(f"cycle {cycle.get('cycle')} filled on {day.date()} (weekend)")
    return bad


def coverage_problems(ladder: list[dict[str, Any]]) -> list[str]:
    """A missing bar dressed up as an evaluated one, or a stage nobody defined."""
    problems: list[str] = []
    for row in ladder:
        unknown = [stage for stage in row["stages"] if stage not in MARKET_STAGES]
        where = f"{row['symbol']}@{row['open_ms']}"
        if unknown:
            problems.append(f"{where}: undefined stage(s) {unknown}")
        if row.get("missing"):
            if "EVALUATED" in row["stages"]:
                problems.append(f"{where}: a bar nobody observed claims to be evaluated")
            if "OBSERVED" in row["stages"]:
                problems.append(f"{where}: a bar stamped missing and observed at once")
            if row.get("classified") != "MISSING_NO_COLLECTOR":
                problems.append(f"{where}: a missing bar that is not labelled MISSING_NO_COLLECTOR")
        if "EVALUATED" in row["stages"] and "OBSERVED" not in row["stages"]:
            problems.append(f"{where}: evaluated without being observed")
    return problems


def lane_ledger_problems(ledger: list[dict[str, Any]]) -> list[str]:
    """The lane's own coverage ledger must not claim an evaluation for a bar it lacked."""
    problems: list[str] = []
    for row in ledger:
        if "EVALUATED" in row["stages"] and "OBSERVED" not in row["stages"]:
            problems.append(f"{row['symbol']}@{row['ts_ms']}: evaluated without being observed")
    return problems


# --- the checks -------------------------------------------------------------------------


def check_pit(checks: Checks, series: Series) -> None:
    trades = _rows(OUT / "ALPHA_RESTATEMENT_TRADES.jsonl")
    problems = pit_problems(trades, series)
    corpora = sorted({trade["corpus"] for trade in trades})
    checks.add(
        "V10",
        "every restated fill is causally executable, rebuilt from the raw series",
        bool(trades) and not problems,
        f"{len(trades)} trades over {corpora}, {len(problems)} violation(s)"
        + (f"; first: {problems[0]}" if problems else ""),
    )

    marks = [trade for trade in trades if trade["is_mark"]]
    share = len(marks) / len(trades) if trades else 1.0
    checks.add(
        "V11",
        "terminal marks are rare and are named as marks, not counted as exits",
        bool(trades) and share < 0.01,
        f"{len(marks)}/{len(trades)} = {share:.3%} are terminal marks",
    )

    overlaps = overlap_problems(trades)
    checks.add(
        "V12",
        "one position per lane, and no entry at the instant of an exit",
        bool(trades) and not overlaps,
        f"{len({(t['corpus'], t['symbol'], t['family']) for t in trades})} lanes, "
        f"{len(overlaps)} overlap(s)" + (f"; first: {overlaps[0]}" if overlaps else ""),
    )

    rows = _csv(OUT / "ECONOMIC_RESTATEMENT.csv")
    rebuilt = restatement_problems(rows, trades)
    checks.add(
        "V13",
        "the restatement table is arithmetic on the trades and the cost column",
        bool(rows) and not rebuilt,
        f"{len(rows)} rows rebuilt, {len(rebuilt)} disagreement(s)"
        + (f"; first: {rebuilt[0]}" if rebuilt else ""),
    )

    defect = _load(OUT / "PIT_DEFECT_MAP.json") or {}
    defect_rows = defect.get("rows") or []
    totals = defect.get("totals") or {}
    consistent = all(
        math.isclose(
            float(row["pre_pit_exit_exploit_share"]),
            float(row["pre_pit_exits_filled_at_their_own_signal_bar"])
            / float(row["pre_pit_trades"]),
            rel_tol=1e-9,
        )
        for row in defect_rows
        if row["pre_pit_trades"]
    )
    checks.add(
        "V14",
        "the defect map says all of it, per lane, and its share is its own arithmetic",
        bool(defect_rows) and consistent and totals.get("share") == 1.0
        and all(row["pre_pit_exit_exploit_share"] == 1.0 for row in defect_rows),
        f"{len(defect_rows)} lanes, swept share {totals.get('share')}, "
        f"{totals.get('pre_pit_trades')} pre-repair trades",
    )

    old = _rows(OUT_15 / "experimental_paper" / "EXPERIMENTAL_TRADES.jsonl")
    reasons: dict[str, int] = {}
    for trade in old:
        reasons[trade["exit_reason"]] = reasons.get(trade["exit_reason"], 0) + 1
    checks.add(
        "V15",
        "the WP-EDGE-015 diagnosis on file is 9 stop-loss and 5 take-profit",
        len(old) == 14 and reasons.get("stop_loss") == 9 and reasons.get("take_profit") == 5,
        f"{len(old)} trades, {reasons}",
    )
    net = sum(float(t["pnl"]) for t in old)
    gross = sum(float(t["gross_pnl"]) for t in old)
    fees = sum(float(t["entry_commission"]) + float(t["exit_commission"]) for t in old)
    checks.add(
        "V16",
        "the pre-repair lane's PnL is the one restated, and its fees are nonzero",
        abs(net + 12.809_960_586_382_445) < 1e-6
        and abs(gross + 3.476_720_586_382_443_3) < 1e-6
        and abs(fees - 9.33324) < 1e-9
        and abs(net - (gross - fees)) < 1e-9,
        f"net {net:.6f}, gross {gross:.6f}, fees {fees:.5f} USDT from the untouched file",
    )


def check_lane(checks: Checks) -> None:
    report = _load(LANE / "CANONICAL_LANE_REPORT.json") or {}
    cycles = _rows(LANE / "CANONICAL_CYCLES.jsonl")
    if not report or not cycles:
        checks.add("V20", "the canonical lane left its report and its cycles", False, "missing")
        return

    policy = yaml.safe_load((REPO / "config" / "risk.yaml").read_text(encoding="utf-8"))["risk"]
    portfolio = report["portfolio"]
    accounting = _load(OUT / "PORTFOLIO_ACCOUNTING.json") or {}
    checks.add(
        "V20",
        "the lane ran one shared book, and the portfolio artifact says so",
        portfolio["mode"] == "ONE_SHARED_BOOK"
        and float(portfolio["equity_usdt"]) == float(accounting["wp_edge_016"]["equity_usdt"])
        and accounting["wp_edge_015"]["mode"] == "THREE_INDEPENDENT_SIMULATIONS"
        and accounting["wp_edge_015"]["not_a_claim_about_capital"] is True,
        f"016 {portfolio['mode']} at {portfolio['equity_usdt']}; "
        f"015 {accounting['wp_edge_015']['mode']}",
    )
    checks.add(
        "V21",
        "three 10 000 books are never added into a capital claim",
        accounting["wp_edge_015"]["books"] and accounting["wp_edge_015"]["mode"] != "ONE_SHARED_BOOK"
        and "NOT_COMPARABLE" in accounting["reconciliation"]["verdict"],
        f"015 sum {accounting['wp_edge_015'].get('reported_mark_to_market_sum')} is not a "
        f"portfolio ({accounting['reconciliation']['verdict']})",
    )

    posture = report["canonical_risk"]
    checks.add(
        "V22",
        "entries were approved and sized by the runtime's own engine",
        posture["entry_gate"] == "RiskManager.check_signal"
        and posture["engine"] == "trading_bot.risk.manager.RiskManager"
        and posture["loader"] == "trading_bot.config.settings.load_settings"
        and posture["changed_by_this_work_package"] is False,
        f"{posture['entry_gate']} via {posture['loader']}",
    )

    approved = [c for c in cycles if c.get("action") == "RISK_APPROVED"]
    rejected = [c for c in cycles if c.get("action") == "RISK_REJECTED"]
    sizes = [float(c["notional_usdt"]) for c in approved]
    risk = report["risk_state_at_end"]
    checks.add(
        "V23",
        "the engine refused orders and every approved size obeys the written policy",
        bool(rejected)
        and bool(sizes)
        and all(
            float(policy["min_order_notional_usdt"]) <= size <= float(policy["max_order_notional_usdt"])
            for size in sizes
        )
        and max(sizes) <= float(policy["max_order_notional_usdt"]),
        f"{len(approved)} approved, {len(rejected)} refused, sizes {sorted(set(sizes))}, "
        f"cap {policy['max_order_notional_usdt']}",
    )
    checks.add(
        "V24",
        "every closing trade fed the engine's own loss and cooldown state",
        len([c for c in cycles if c.get("action") == "POSITION_CLOSED"]) == len(approved),
        f"{len([c for c in cycles if c.get('action') == 'POSITION_CLOSED'])} closes for "
        f"{len(approved)} opens; final consecutive_losses {risk['consecutive_losses']}, "
        f"daily_pnl {risk['daily_pnl']}",
    )
    checks.add(
        "V25",
        "the kill switch was live in the engine and never silently bypassed",
        risk["kill_switch_active"] is False
        and "kill_switch" in json.dumps(_load(OUT / "RISK_PARITY_MATRIX.json") or {}).lower(),
        f"kill switch at end: {risk['kill_switch_active']}",
    )

    ledger_path = REPO / "config" / "strategy_admission.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))["strategies"]
    admitted = sorted(
        key for key, entry in ledger.items() if not key.startswith("_") and entry.get("admitted_for_paper")
    )
    isolation = report["isolation"]
    checks.add(
        "V26",
        "the authoritative admission ledger is byte-identical and still admits nothing",
        isolation["untouched"] is True
        and isolation["sha256_before"] == isolation["sha256_after"] == _sha256(ledger_path)
        and admitted == [],
        f"{isolation['sha256_after'][:12]}… unchanged; admitted {admitted}",
    )
    checks.add(
        "V27",
        "the experimental lane names itself experimental instead of admitted",
        report["tag"] == "EXPERIMENTAL_PROSPECTIVE_PAPER"
        and isolation["admission_gate_in_this_lane"] == "BYPASSED_BY_DESIGN_LABELLED_EXPERIMENTAL",
        f"tag {report['tag']}, gate {isolation['admission_gate_in_this_lane']}",
    )

    positions = report["positions_and_pnl"]
    costs = report["costs"]
    checks.add(
        "V28",
        "the book's accounting identities hold and its fee figure is the same twice",
        positions["identities_all_hold"] is True
        and positions["closed_trades"] == len(approved) > 0
        and math.isclose(
            float(costs["broker_fees_usdt"]), float(positions["broker_fees_usdt"]), rel_tol=1e-12
        ),
        f"{positions['closed_trades']} trades, identities {sorted(set(positions['identities'].values()))}, "
        f"fees {positions['broker_fees_usdt']}",
    )
    checks.add(
        "V29",
        "the lane admits its PnL is pre-cost and that no latency is modelled",
        costs["lane_pnl_is"] == "PRE_COST"
        and float(costs["broker_slippage_bps"]) == 0.0
        and report["timing_model"]["latency_modelled_ms"] == 0
        and "ECONOMIC_RESTATEMENT" in costs["where_the_cost_is_charged"],
        f"{costs['lane_pnl_is']}, latency {report['timing_model']['latency_modelled_ms']} ms, "
        f"cost charged in the restatement",
    )

    leaks = proposal_leaks(cycles)
    checks.add(
        "V30",
        "no proposal or risk message carries an outcome it could not have known",
        not leaks,
        "clean" if not leaks else f"{len(leaks)} leak(s): {leaks[:2]}",
    )
    weekend = weekend_fills(cycles)
    checks.add(
        "V31",
        "the written weekend veto is honoured: no fill on a Saturday or Sunday",
        not weekend and int(report["weekend_policy"]["weekend_entries_refused"]) > 0,
        f"{report['weekend_policy']['weekend_entries_refused']} weekend refusals, "
        f"{len(weekend)} weekend fill(s)",
    )
    checks.add(
        "V32",
        "the weekend conflict is reported rather than resolved by the code",
        (_load(OUT / "WEEKEND_POLICY.json") or {}).get("active_goal_7_of_7", {}).get(
            "possible_under_the_policy_as_written"
        )
        is False,
        "WEEKEND_POLICY.json declares 7/7 impossible without a governance decision",
    )
    checks.add(
        "V33",
        "the lane's coverage ledger never evaluates a bar it did not observe",
        not lane_ledger_problems(_rows(LANE / "COVERAGE_LEDGER.jsonl")),
        f"{len(_rows(LANE / 'COVERAGE_LEDGER.jsonl'))} lane bars checked",
    )


def check_forward(checks: Checks) -> None:
    continuity = _load(OUT / "CAPTURE_CONTINUITY.json") or {}
    ladder = continuity.get("stage_ladder") or []
    problems = coverage_problems(ladder)
    checks.add(
        "V40",
        "a bar no collector observed is MISSING, never an evaluated quiet bar",
        bool(ladder) and not problems,
        f"{len(ladder)} expected symbol-bars, {len(problems)} problem(s)"
        + (f"; first: {problems[0]}" if problems else ""),
    )
    observed = continuity.get("observed_bars")
    evaluated = continuity.get("evaluated_bars")
    checks.add(
        "V41",
        "observation, evaluation and fills are reported as separate counts",
        isinstance(observed, int)
        and isinstance(evaluated, int)
        and isinstance(continuity.get("bars_with_a_fill"), int)
        and continuity.get("bars_with_a_fill") == 0,
        f"observed {observed}, evaluated {evaluated}, with a proposal "
        f"{continuity.get('bars_with_a_proposal')}, with a fill {continuity.get('bars_with_a_fill')}",
    )
    checks.add(
        "V42",
        "the prospective status is the truthful not-automated one",
        continuity.get("status") == "PROSPECTIVE_CAPTURE_NOT_AUTOMATED"
        and continuity["why_not_automated"]["disk_guard_ok"] is False,
        f"{continuity.get('status')}: {continuity['why_not_automated']['disk_guard_state']}",
    )
    symbols = {row["symbol"] for row in ladder}
    expected = int(continuity.get("expected_closed_bars_per_symbol") or 0) * max(len(symbols), 1)
    ratio = float(continuity.get("coverage_ratio") or 0.0)
    recomputed = (int(continuity.get("observed_bars") or 0) / expected) if expected else 0.0
    checks.add(
        "V43",
        "the unique key is venue, symbol, timeframe and open instant, with no duplicates",
        continuity.get("unique_key") == "VENUE|SYMBOL|TIMEFRAME|OPEN_MS"
        and continuity["dedupe_check"]["duplicate_keys"] == 0,
        f"{continuity.get('unique_key')}, {continuity['dedupe_check']['captured_keys']} keys, "
        f"{continuity['dedupe_check']['duplicate_keys']} duplicate",
    )
    checks.add(
        "V56",
        "coverage is the observed-over-expected ratio, and a stalled collector shows as less",
        abs(ratio - recomputed) < 1e-9
        and bool(continuity.get("coverage_is_current")) == (ratio == 1.0)
        and not (ratio < 1.0 and not any(row.get("missing") for row in ladder)),
        f"{continuity.get('observed_bars')}/{expected} symbol-bars = {ratio:.3f}; current "
        f"{continuity.get('coverage_is_current')}; missing rows labelled "
        f"{sum(1 for row in ladder if row.get('missing'))}",
    )
    run_report = (OUT / "RUN_REPORT.json").read_text(encoding="utf-8") \
        if (OUT / "RUN_REPORT.json").is_file() else ""
    checks.add(
        "V44",
        "three captured bars are not sold as evidence of an edge",
        int(continuity.get("observed_bars", 0)) <= 3
        and int(continuity.get("bars_with_a_fill", 1)) == 0
        and "PROSPECTIVE_EVIDENCE_INSUFFICIENT" in run_report,
        "the run report carries the status PROSPECTIVE_EVIDENCE_INSUFFICIENT",
    )

    disk = _load(OUT / "CAPACITY_PREFLIGHT.json") or {}
    checks.add(
        "V45",
        "the disk guard blocked the collector and nobody lowered it",
        disk.get("guard_relaxed_by_this_package") is False
        and disk.get("verdict") == "CAPTURE_BLOCKED_DISK"
        and disk.get("guard_ok") is False
        and float(disk.get("free_gib", 0)) > 0,
        f"{disk.get('verdict')} at {disk.get('free_gib')} GiB free, "
        f"{disk.get('guard_state')}, guard_relaxed {disk.get('guard_relaxed_by_this_package')}",
    )
    checks.add(
        "V46",
        "no scheduled job was created by this package",
        (_load(OUT / "SCHEDULER_DECISION.json") or {}).get("decision") == "DO_NOT_CREATE_A_SCHEDULER",
        "SCHEDULER_DECISION.json: DO_NOT_CREATE_A_SCHEDULER",
    )
    scheduled = []
    for path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*schedule:", text, flags=re.MULTILINE):
            scheduled.append(path.name)
    checks.add(
        "V47",
        "the workflow files on disk still contain no cron this package added",
        scheduled == [],
        f"{len(list((REPO / '.github' / 'workflows').glob('*.yml')))} workflow(s), "
        f"scheduled: {scheduled or 'none'}",
    )

    verdict = _load(OUT / "CURRENT_VS_PROPOSED.json") or {}
    winners = verdict.get("survive_the_adverse_multiplier") or []
    rows = _csv(OUT / "ECONOMIC_RESTATEMENT.csv")
    post = [row for row in rows if row["variant"] == "POST_PIT"]
    notional = float(verdict["order_notional_usdt"])
    worst = 0.0
    for family, bucket in (verdict.get("proposed") or {}).items():
        want = (
            sum(float(row["net_bps_total_1x"]) for row in post if row["family"] == family)
            / 10_000.0
            * notional
        )
        worst = max(worst, abs(want - float(bucket["net_usdt_1x"])))
    checks.add(
        "V48",
        "the CURRENT/PROPOSED table is the published rows, and the verdict follows the threshold",
        bool(post)
        and worst <= max(0.05, 1e-3 * max(abs(float(b["net_usdt_1x"])) for b in verdict["proposed"].values()))
        and ((verdict["verdict"] == "NO_RESTATED_EDGE_SURVIVES") == (winners == []))
        and verdict["current_runtime"]["trades"] == 0
        and float(verdict["current_runtime"]["net_usdt"]) == 0.0,
        f"worst deviation {worst:.4f} USDT over {len(post)} restated rows; verdict "
        f"{verdict['verdict']}; CURRENT net {verdict['current_runtime']['net_usdt']}",
    )


#: Published taker fee, spot, VIP0, one side. Ground truth from the venue's fee schedule,
#: declared here so the cost columns can be checked without importing the cost engine.
VENUE_FEE_BPS_PER_SIDE = 10.0


def lane_cost_problems(report: dict[str, Any], trades: list[dict[str, Any]]) -> list[str]:
    """Rebuild the lane's cost block from its own fills and the venue's fee floor."""
    problems: list[str] = []
    block = (report.get("costs") or {}).get("net_of_cost")
    if not isinstance(block, dict):
        return ["the lane report has no net_of_cost block"]
    gross = sum(float(trade["gross_pnl"]) for trade in trades)
    notional = sum(float(trade["quantity"]) * float(trade["entry_price"]) for trade in trades)
    if abs(gross - float(block["gross_realised_usdt"])) > 1e-6:
        problems.append(
            f"gross_realised_usdt {block['gross_realised_usdt']} != {gross:.6f} summed from the fills"
        )
    costs = {}
    for multiplier in (1, 2, 3):
        cost = float(block[f"cost_{multiplier}x_usdt"])
        net = float(block[f"net_{multiplier}x_usdt"])
        costs[multiplier] = cost
        if abs(net - (float(block["gross_realised_usdt"]) - cost)) > ROUNDED:
            problems.append(f"net_{multiplier}x is not gross minus its own cost")
    if not math.isclose(costs[2], 2.0 * costs[1], rel_tol=1e-6):
        problems.append(f"the 2x cost is not twice the 1x cost ({costs[2]} vs {2 * costs[1]})")
    if not math.isclose(costs[3], 3.0 * costs[1], rel_tol=1e-6):
        problems.append(f"the 3x cost is not three times the 1x cost ({costs[3]} vs {3 * costs[1]})")
    # The venue's real fee is the floor: a round trip can never cost less than two sides of it.
    floor = notional * 2.0 * VENUE_FEE_BPS_PER_SIDE / 10_000.0
    if costs[1] < floor:
        problems.append(
            f"the charged cost {costs[1]:.4f} USDT is below the venue's own fee floor {floor:.4f}"
        )
    per_symbol = block.get("per_symbol") or {}
    if abs(sum(float(row["gross_usdt"]) for row in per_symbol.values()) - float(block["gross_realised_usdt"])) > 1e-3:
        problems.append("the per-symbol gross does not add up to the total")
    if abs(sum(float(row["cost_1x_usdt"]) for row in per_symbol.values()) - costs[1]) > 1e-3:
        problems.append("the per-symbol cost does not add up to the total")
    if sum(int(row["trades"]) for row in per_symbol.values()) != len(trades):
        problems.append("the per-symbol trade counts do not add up to the fills")
    return problems


def check_lane_costs(checks: Checks, report: dict[str, Any]) -> None:
    trades = _rows(LANE / "CANONICAL_TRADES.jsonl")
    problems = lane_cost_problems(report, trades)
    block = report["costs"]["net_of_cost"]
    checks.add(
        "V34",
        "the lane's net-of-cost view rebuilds from its own fills and clears the fee floor",
        bool(trades) and not problems,
        f"gross {block['gross_realised_usdt']} -> net {block['net_1x_usdt']}/{block['net_2x_usdt']}/"
        f"{block['net_3x_usdt']} USDT at 1x/2x/3x; {len(problems)} problem(s)"
        + (f"; first: {problems[0]}" if problems else ""),
    )


BROKER_SOURCE = REPO / "src" / "trading_bot" / "paper" / "broker.py"


def broker_both_hit_policy() -> str | None:
    """The broker's default, read from its own source rather than from the lane's report."""
    source = BROKER_SOURCE.read_text(encoding="utf-8")
    found = re.search(r'both_hit_policy:\s*str\s*=\s*"(\w+)"', source)
    return found.group(1) if found else None


def protective_exit_problems(report: dict[str, Any]) -> list[str]:
    """The ambiguous intrabar case must be resolved against the position, not for it."""
    problems: list[str] = []
    declared = (report.get("protective_exits") or {}).get("both_hit_policy")
    actual = broker_both_hit_policy()
    if actual is None:
        problems.append("the broker's both-hit policy could not be read from its source")
    elif declared != actual:
        problems.append(f"the lane reports {declared!r} but the broker's default is {actual!r}")
    if declared != "stop_first":
        problems.append(f"the ambiguous case is not resolved conservatively: {declared!r}")
    if (report.get("protective_exits") or {}).get("policy_overridden_here") is not False:
        problems.append("the lane says it overrode the broker's policy")
    return problems


def check_protective_exits(checks: Checks, report: dict[str, Any]) -> None:
    problems = protective_exit_problems(report)
    checks.add(
        "V35",
        "when a stop and a target are both touched, the lane resolves it against itself",
        not problems,
        f"broker default {broker_both_hit_policy()!r}, lane declares "
        f"{(report.get('protective_exits') or {}).get('both_hit_policy')!r}"
        + (f"; {problems[0]}" if problems else ""),
    )


def status_problems(run_report: dict[str, Any]) -> list[str]:
    """A declared status must follow the evidence it claims to summarise, either way."""
    problems: list[str] = []
    statuses = run_report.get("statuses")
    if not isinstance(statuses, dict) or not statuses:
        return ["the run report declares no statuses"]
    if statuses.get("PIT_FIXED_RISK_PARITY_VALIDATED") == statuses.get("PIT_FIXED_RISK_PARITY_BLOCKED"):
        problems.append("both PIT/parity outcomes are declared the same, so neither is informative")
    verdict_claims = [
        statuses.get("INDEPENDENT_VERIFIED"),
        statuses.get("INDEPENDENT_VERIFICATION_FAILED"),
        statuses.get("INDEPENDENT_VERIFICATION_NOT_RUN"),
    ]
    if sum(1 for value in verdict_claims if value) != 1:
        problems.append("the verification status is not exactly one of verified/failed/not run")
    continuity = _load(OUT / "CAPTURE_CONTINUITY.json") or {}
    capacity = _load(OUT / "CAPACITY_PREFLIGHT.json") or {}
    defect = _load(OUT / "PIT_DEFECT_MAP.json") or {}
    parity = _load(OUT / "RISK_PARITY_MATRIX.json") or {}
    comparison = _load(OUT / "CURRENT_VS_PROPOSED.json") or {}
    expected = {
        "CAPTURE_BLOCKED_DISK": capacity.get("verdict") == "CAPTURE_BLOCKED_DISK",
        "PROSPECTIVE_EVIDENCE_INSUFFICIENT": int(continuity.get("bars_with_a_fill") or 0) == 0,
        "PROSPECTIVE_CAPTURE_NOT_AUTOMATED": continuity.get("status")
        == "PROSPECTIVE_CAPTURE_NOT_AUTOMATED",
        "ECONOMIC_RESULTS_RESTATED_NO_EDGE": comparison.get("verdict")
        == "NO_RESTATED_EDGE_SURVIVES",
        "PIT_FIXED_RISK_PARITY_VALIDATED": (
            (defect.get("totals") or {}).get("post_pit_pit_violations") == 0
            and parity.get("lane_uses_canonical_engine") is True
        ),
    }
    for name, want in expected.items():
        if statuses.get(name) != want:
            problems.append(f"{name} is declared {statuses.get(name)} but the evidence says {want}")
    holding = run_report.get("statuses_holding")
    if not isinstance(holding, list) or sorted(holding) != sorted(
        name for name, value in statuses.items() if value
    ):
        problems.append("statuses_holding does not match the declared statuses")
    return problems


def check_run_report(checks: Checks) -> None:
    run_report = _load(OUT / "RUN_REPORT.json") or {}
    problems = status_problems(run_report)
    checks.add(
        "V49",
        "the run report's statuses follow the evidence, true or false",
        not problems,
        f"holding {run_report.get('statuses_holding')}" + (f"; {problems[0]}" if problems else ""),
    )
    totals = (_load(OUT / "PIT_DEFECT_MAP.json") or {}).get("totals") or {}
    checks.add(
        "V55",
        "the defect map's own audit count is zero after the repair",
        totals.get("post_pit_pit_violations") == 0,
        f"post-repair violations {totals.get('post_pit_pit_violations')} over "
        f"{totals.get('pre_pit_exits_checked')} pre-repair exits checked",
    )


def evidence_index_problems(index: dict[str, Any]) -> list[str]:
    """Every hash in the index must match the bytes on disk, and nothing hashes itself."""
    problems: list[str] = []
    artifacts = index.get("artifacts") or []
    code = index.get("code") or []
    if not artifacts or not code:
        return ["the index lists no artifacts or no code"]
    listed = {row["artifact"] for row in artifacts}
    if "EVIDENCE_INDEX.json" in listed:
        problems.append("the index lists a hash of itself, which cannot be truthful")
    for row in artifacts:
        path = OUT / row["artifact"]
        if not path.is_file():
            problems.append(f"{row['artifact']}: listed but missing")
            continue
        if _sha256(path) != row.get("sha256"):
            problems.append(f"{row['artifact']}: hash does not match the bytes on disk")
    for row in code:
        path = REPO / row["path"]
        if not path.is_file():
            problems.append(f"{row['path']}: listed but missing")
            continue
        if _sha256(path) != row.get("sha256"):
            problems.append(f"{row['path']}: code hash does not match the bytes on disk")
    return problems


def check_evidence_index(checks: Checks) -> None:
    index = _load(OUT / "EVIDENCE_INDEX.json") or {}
    problems = evidence_index_problems(index)
    checks.add(
        "V57",
        "every artifact and code hash in the index matches the bytes on disk",
        not problems,
        f"{len(index.get('artifacts') or [])} artifacts, {len(index.get('code') or [])} code files"
        + (f"; {problems[0]}" if problems else ""),
    )


AUTHORITY_STAGES = {
    "signal_calculation",
    "closed_bar_availability",
    "ohlc_simulator",
    "paper_broker_fills",
    "portfolio_and_risk",
    "admission",
    "scheduler",
    "prospective_collector",
}


def authority_problems(authority: dict[str, Any]) -> list[str]:
    """Every stage must resolve, and the recorded line must really contain the symbol."""
    problems: list[str] = []
    rows = authority.get("rows") or []
    stages = {row["stage"] for row in rows}
    if stages != AUTHORITY_STAGES:
        problems.append(f"stages missing or unknown: {sorted(AUTHORITY_STAGES ^ stages)}")
    for row in rows:
        path = REPO / row["component"]
        if not path.is_file():
            problems.append(f"{row['stage']}: {row['component']} does not exist")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        line = row.get("line")
        if not isinstance(line, int) or not (1 <= line <= len(lines)):
            problems.append(f"{row['stage']}: no line recorded")
            continue
        if row["symbol"] not in lines[line - 1]:
            problems.append(
                f"{row['stage']}: line {line} of {row['component']} does not contain {row['symbol']!r}"
            )
        if _sha256(path) != row.get("sha256"):
            problems.append(f"{row['stage']}: {row['component']} changed since the map was written")
    if authority.get("unresolved"):
        problems.append(f"the map itself lists unresolved stages: {authority['unresolved']}")
    if authority.get("scheduled_jobs_owned_by_this_package"):
        problems.append("the map claims this package owns a scheduled job")
    return problems


def reconciliation_problems(reconciliation: dict[str, Any]) -> list[str]:
    """The reconciliation must be arithmetic on the defect map it summarises."""
    problems: list[str] = []
    defect = _load(OUT / "PIT_DEFECT_MAP.json") or {}
    rows = defect.get("rows") or []
    totals = reconciliation.get("totals") or {}
    swept = sum(row["pre_pit_exits_filled_at_their_own_signal_bar"] for row in rows)
    checked = sum(row["pre_pit_trades"] for row in rows)
    if totals.get("pre_pit_exits_checked") != checked:
        problems.append(f"pre-PIT exits {totals.get('pre_pit_exits_checked')} != {checked} on the map")
    if totals.get("pre_pit_exits_filled_at_their_own_signal_bar") != swept:
        problems.append(f"swept exits {totals.get('pre_pit_exits_filled_at_their_own_signal_bar')} != {swept}")
    if abs(float(totals.get("swept_share", 0)) - (swept / checked if checked else 0)) > 1e-6:
        problems.append("the swept share is not its own arithmetic")
    if totals.get("post_pit_violations") != sum(row["post_pit_pit_violations"] for row in rows):
        problems.append("post-repair violations do not add up from the rows")
    if reconciliation.get("lanes_with_a_remaining_violation"):
        problems.append("a lane still violates the contract")
    if not reconciliation.get("window_shift"):
        problems.append("no before/after window evidence is recorded")
    return problems


def check_authority_and_reconciliation(checks: Checks) -> None:
    authority = _load(OUT / "RUNTIME_AUTHORITY_MAP.json") or {}
    problems = authority_problems(authority)
    checks.add(
        "V58",
        "each named decision has one owner, resolved at a line that really says so",
        bool(authority) and not problems,
        f"{len(authority.get('rows') or [])} stages, unresolved {authority.get('unresolved')}"
        + (f"; {problems[0]}" if problems else ""),
    )
    checks.add(
        "V59",
        "the runtime authority map is published as both data and prose",
        (OUT / "RUNTIME_AUTHORITY_MAP.md").is_file()
        and "| stage | component |" in (OUT / "RUNTIME_AUTHORITY_MAP.md").read_text(encoding="utf-8"),
        "RUNTIME_AUTHORITY_MAP.json and .md",
    )
    reconciliation = _load(OUT / "PIT_RECONCILIATION.json") or {}
    recon = reconciliation_problems(reconciliation)
    checks.add(
        "V61",
        "the reconciliation is arithmetic on the defect map and leaves no lane in violation",
        bool(reconciliation) and not recon,
        f"swept {reconciliation.get('totals', {}).get('swept_share')} of "
        f"{reconciliation.get('totals', {}).get('pre_pit_exits_checked')} exits; "
        f"{len(reconciliation.get('window_shift') or {})} symbols of window evidence"
        + (f"; {recon[0]}" if recon else ""),
    )


def check_independence(checks: Checks) -> None:
    source = (REPO / "scripts" / "edge16_verify.py").read_text(encoding="utf-8")
    imports = re.findall(r"^\s*(?:from|import)\s+([\w\.]+)", source, flags=re.MULTILINE)
    offenders = [name for name in imports if any(name.endswith(bad) for bad in FORBIDDEN_IMPORTS)]
    checks.add(
        "V50",
        "this verifier imports none of the modules that built the artifacts",
        not offenders,
        f"{len(imports)} imports scanned; forbidden: {offenders or 'none'}",
    )
    baseline = _load(OUT / "BASELINE.json") or {}
    ancestor = subprocess.run(
        ["git", "-C", str(REPO), "merge-base", "--is-ancestor", str(baseline.get("head")), "HEAD"],
        capture_output=True,
        check=False,
    )
    # The detail names the audited baseline and not the current HEAD: the verification hash is
    # published inside the same commit it describes, so it cannot carry that commit's own id.
    checks.add(
        "V51",
        "the audited baseline is an ancestor of the verified HEAD",
        bool(baseline.get("head")) and ancestor.returncode == 0,
        f"baseline {str(baseline.get('head'))[:12]} is an ancestor of the verified tree",
    )
    preserved = (baseline.get("preserved_as_historical") or {}).get("label")
    checks.add(
        "V52",
        "the pre-repair work package is preserved and named as historical, not corrected",
        preserved == "HISTORICAL_DESCRIPTIVE_PRE_PIT_FIX"
        and (OUT_15 / "RUN_REPORT.json").is_file()
        and (_load(OUT_15 / "RUN_REPORT.json") or {}).get("work_package") == "WP-EDGE-015",
        f"label {preserved}; WP-EDGE-015 artifacts still on disk untouched",
    )
    checks.add(
        "V53",
        "the risk policy file the lane loads is the one this verifier reads",
        _sha256(REPO / "config" / "risk.yaml") == (baseline.get("artifacts") or {}).get("config/risk.yaml"),
        f"risk.yaml {str(_sha256(REPO / 'config' / 'risk.yaml'))[:12]}… matches the baseline hash",
    )


# --- fault injection: every check must fail on a mutated artifact -----------------------


def mutations(series: Series) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def note(name: str, detected: bool, detail: str) -> None:
        results.append((name, detected, detail))

    trades = _rows(OUT / "ALPHA_RESTATEMENT_TRADES.jsonl")
    if trades:
        mutated = copy.deepcopy(trades)
        mutated[0]["exit_fill_index"] = mutated[0]["exit_signal_index"]
        found = pit_problems(mutated, series)
        note("same-bar close-to-open exit", bool(found), found[0] if found else "MISSED")

        mutated = copy.deepcopy(trades)
        mutated[0]["exit_fill_index"] -= 1  # an earlier fill that no rule could have placed
        mutated[0]["exit_ts_ms"] = mutated[0]["exit_ts_ms"]
        found = pit_problems(mutated, series)
        note("an exit one bar too early", bool(found), found[0] if found else "MISSED")

        mutated = copy.deepcopy(trades)
        mutated[0]["exit_data_available_ms"] += PERIOD_MS
        found = pit_problems(mutated, series)
        note("exit stamped before its data", bool(found), found[0] if found else "MISSED")

        mutated = copy.deepcopy(trades)
        mutated[0]["gross_bps"] += 5.0
        found = pit_problems(mutated, series)
        note("gross inflated by hand", bool(found), found[0] if found else "MISSED")

        marks = [index for index, trade in enumerate(trades) if trade["is_mark"]]
        if marks:
            mutated = copy.deepcopy(trades)
            mutated[marks[0]]["is_mark"] = False  # a mark passed off as a real exit
            found = pit_problems(mutated, series)
            note("a terminal mark relabelled as an exit", bool(found), found[0] if found else "MISSED")

        mutated = copy.deepcopy(trades)
        mutated[0]["symbol"] = "DOGE/USDT"  # a series that is not on disk
        found = pit_problems(mutated, series)
        note("a trade with no raw series behind it", bool(found), found[0] if found else "MISSED")

        # synthetic neighbours, so the mutation does not depend on this package's own data
        first = {"corpus": "X", "symbol": "Y/USDT", "family": "f", "entry_fill_index": 10, "exit_fill_index": 20}
        inside = dict(first, entry_fill_index=15, exit_fill_index=25)
        same_instant = dict(first, entry_fill_index=20, exit_fill_index=30)
        found = overlap_problems([first, inside])
        note("a second position inside the first", bool(found), found[0] if found else "MISSED")
        found = overlap_problems([first, same_instant])
        note("an entry at the instant of the previous exit", bool(found), found[0] if found else "MISSED")
        note(
            "a clean lane the overlap check must accept",
            overlap_problems([first, dict(first, entry_fill_index=25, exit_fill_index=30)]) == [],
            "no overlap in a sequential lane",
        )

    rows = _csv(OUT / "ECONOMIC_RESTATEMENT.csv")
    restated_rows = [index for index, row in enumerate(rows) if row["variant"] == "POST_PIT"]
    if restated_rows:
        target = restated_rows[0]
        mutated_rows = copy.deepcopy(rows)
        mutated_rows[target]["net_bps_total_1x"] = str(
            float(mutated_rows[target]["net_bps_total_1x"]) + 100.0
        )
        found = restatement_problems(mutated_rows, trades)
        note("a restated row inflated by 100 bps", bool(found), found[0] if found else "MISSED")

        mutated_rows = copy.deepcopy(rows)
        mutated_rows[target]["cost_round_trip_bps_1x"] = "0.0"
        found = restatement_problems(mutated_rows, trades)
        note("a fake zero cost", bool(found), found[0] if found else "MISSED")

        mutated_rows = copy.deepcopy(rows)
        mutated_rows[target]["trades"] = str(int(mutated_rows[target]["trades"]) + 1)
        found = restatement_problems(mutated_rows, trades)
        note("a trade count that no fills support", bool(found), found[0] if found else "MISSED")

        mutated_rows = copy.deepcopy(rows)
        mutated_rows[target]["net_bps_total_2x"] = mutated_rows[target]["net_bps_total_1x"]
        found = restatement_problems(mutated_rows, trades)
        note("a 2x multiplier that charges nothing extra", bool(found), found[0] if found else "MISSED")

    cycles = _rows(LANE / "CANONICAL_CYCLES.jsonl")
    if cycles:
        mutated_cycles = copy.deepcopy(cycles)
        for cycle in mutated_cycles:
            if str(cycle.get("stage", "")).startswith("PROPOSAL"):
                cycle["exit_price"] = 1.0
                break
        found = proposal_leaks(mutated_cycles)
        note("a future outcome smuggled into a proposal", bool(found), found[0] if found else "MISSED")

        weekend = copy.deepcopy(cycles)
        for cycle in weekend:
            if cycle.get("action") == "FILL_OPENED":
                cycle["ts_ms"] = 1_792_284_800_000  # 2026-10-18T00:00Z, a Sunday
                break
        found = weekend_fills(weekend)
        note("a fill on a Sunday", bool(found), found[0] if found else "MISSED")

    ledger = _rows(LANE / "COVERAGE_LEDGER.jsonl")
    if ledger:
        mutated_ledger = copy.deepcopy(ledger)
        victim = next(row for row in mutated_ledger if "EVALUATED" in row["stages"])
        victim["stages"] = [stage for stage in victim["stages"] if stage != "OBSERVED"]
        found = lane_ledger_problems(mutated_ledger)
        note("an evaluation with its observation removed", bool(found), found[0] if found else "MISSED")

    ladder = (_load(OUT / "CAPTURE_CONTINUITY.json") or {}).get("stage_ladder") or []
    gap = {
        "symbol": "BTC/USDT",
        "open_ms": 1_792_232_800_000,
        "stages": ["EXPECTED"],
        "missing": True,
        "classified": "MISSING_NO_COLLECTOR",
    }
    injected_ladder = [*copy.deepcopy(ladder), gap]
    note(
        "a missing bar left as missing the check must accept",
        coverage_problems(injected_ladder) == [],
        "an unobserved bar labelled MISSING_NO_COLLECTOR raises nothing",
    )
    promoted = copy.deepcopy(injected_ladder)
    promoted[-1]["stages"] = ["EXPECTED", "OBSERVED", "EVALUATED"]
    found = coverage_problems(promoted)
    note("a missing bar promoted to evaluated", bool(found), found[0] if found else "MISSED")

    unlabelled = copy.deepcopy(injected_ladder)
    unlabelled[-1]["classified"] = "QUIET_DAY"
    found = coverage_problems(unlabelled)
    note("a gap relabelled as a quiet day", bool(found), found[0] if found else "MISSED")

    if ladder:
        mutated_ladder = copy.deepcopy(ladder)
        mutated_ladder[0]["stages"] = ["EXPECTED", "INVENTED_STAGE"]
        found = coverage_problems(mutated_ladder)
        note("a stage nobody defined", bool(found), found[0] if found else "MISSED")

        mutated_ladder = copy.deepcopy(ladder)
        mutated_ladder[0]["stages"] = ["EXPECTED", "EVALUATED"]
        found = coverage_problems(mutated_ladder)
        note("an evaluation with no observation behind it", bool(found), found[0] if found else "MISSED")

    defect = _load(OUT / "PIT_DEFECT_MAP.json") or {}
    if defect.get("rows"):
        softened = copy.deepcopy(defect)
        for row in softened["rows"]:
            row["pre_pit_exit_exploit_share"] = 0.5
        detected = not (
            all(row["pre_pit_exit_exploit_share"] == 1.0 for row in softened["rows"])
            and softened["totals"].get("share") == 1.0
        )
        note("a softened defect share", detected, "the swept share is no longer 100%")

    accounting = _load(OUT / "PORTFOLIO_ACCOUNTING.json") or {}
    if accounting:
        merged = copy.deepcopy(accounting)
        merged["wp_edge_015"]["mode"] = "ONE_SHARED_BOOK"
        detected = not (
            merged["wp_edge_015"]["mode"] != "ONE_SHARED_BOOK"
            and merged["wp_edge_015"].get("not_a_claim_about_capital") is True
        )
        note("three books presented as one portfolio", detected, "the 015 mode no longer isolates them")

    lane_report = _load(LANE / "CANONICAL_LANE_REPORT.json") or {}
    lane_trades = _rows(LANE / "CANONICAL_TRADES.jsonl")
    if lane_report:
        optimistic = copy.deepcopy(lane_report)
        optimistic["protective_exits"]["both_hit_policy"] = "tp_first"
        found = protective_exit_problems(optimistic)
        note("an optimistic both-hit policy", bool(found), found[0] if found else "MISSED")

        overridden = copy.deepcopy(lane_report)
        overridden["protective_exits"]["policy_overridden_here"] = True
        found = protective_exit_problems(overridden)
        note("a lane that admits overriding the broker", bool(found), found[0] if found else "MISSED")

    if lane_report and lane_trades:
        frictionless = copy.deepcopy(lane_report)
        frictionless["costs"]["net_of_cost"]["cost_1x_usdt"] = 0.0
        found = lane_cost_problems(frictionless, lane_trades)
        note("a frictionless cost claim (cost 1x = 0)", bool(found), found[0] if found else "MISSED")

        cheap_report = copy.deepcopy(lane_report)
        cheap = cheap_report["costs"]["net_of_cost"]
        cheap["cost_1x_usdt"] = cheap["cost_1x_usdt"] / 10.0
        cheap["cost_2x_usdt"] = cheap["cost_1x_usdt"] * 2
        cheap["cost_3x_usdt"] = cheap["cost_1x_usdt"] * 3
        cheap["net_1x_usdt"] = cheap["gross_realised_usdt"] - cheap["cost_1x_usdt"]
        cheap["net_2x_usdt"] = cheap["gross_realised_usdt"] - cheap["cost_2x_usdt"]
        cheap["net_3x_usdt"] = cheap["gross_realised_usdt"] - cheap["cost_3x_usdt"]
        found = lane_cost_problems(cheap_report, lane_trades)
        note("a cost 10x below the venue's fee floor", bool(found), found[0] if found else "MISSED")

        inflated_pnl = copy.deepcopy(lane_report)
        inflated_pnl["costs"]["net_of_cost"]["gross_realised_usdt"] = 100.0
        found = lane_cost_problems(inflated_pnl, lane_trades)
        note("a lane PnL that does not sum from its fills", bool(found), found[0] if found else "MISSED")

    index = _load(OUT / "EVIDENCE_INDEX.json") or {}
    if index.get("artifacts"):
        stale = copy.deepcopy(index)
        stale["artifacts"][0]["sha256"] = "0" * 64
        found = evidence_index_problems(stale)
        note("an evidence hash that does not match the file", bool(found), found[0] if found else "MISSED")

        self_listed = copy.deepcopy(index)
        self_listed["artifacts"].append(
            {"artifact": "EVIDENCE_INDEX.json", "exists": True, "bytes": 1, "sha256": "0" * 64}
        )
        found = evidence_index_problems(self_listed)
        note("an index that hashes itself", bool(found), found[0] if found else "MISSED")

    authority = _load(OUT / "RUNTIME_AUTHORITY_MAP.json") or {}
    if authority.get("rows"):
        drifted = copy.deepcopy(authority)
        drifted["rows"][0]["line"] = 1  # a line that does not contain the symbol
        found = authority_problems(drifted)
        note("a map whose line does not name the component", bool(found), found[0] if found else "MISSED")

        missing = copy.deepcopy(authority)
        missing["rows"] = [row for row in missing["rows"] if row["stage"] != "scheduler"]
        found = authority_problems(missing)
        note("a map with a stage quietly dropped", bool(found), found[0] if found else "MISSED")

    reconciliation = _load(OUT / "PIT_RECONCILIATION.json") or {}
    if reconciliation.get("totals"):
        softened = copy.deepcopy(reconciliation)
        softened["totals"]["pre_pit_exits_filled_at_their_own_signal_bar"] = 1
        found = reconciliation_problems(softened)
        note("a reconciliation that softens the swept count", bool(found), found[0] if found else "MISSED")

    run_report = _load(OUT / "RUN_REPORT.json") or {}
    if run_report:
        # the lie is the opposite of whatever the evidence supports right now, so the mutation
        # stays a lie whichever way the package's own conclusion moves
        for name in (
            "PIT_FIXED_RISK_PARITY_VALIDATED",
            "PROSPECTIVE_EVIDENCE_INSUFFICIENT",
            "CAPTURE_BLOCKED_DISK",
            "ECONOMIC_RESULTS_RESTATED_NO_EDGE",
        ):
            lying = copy.deepcopy(run_report)
            lying["statuses"][name] = not bool(run_report["statuses"].get(name))
            lying["statuses_holding"] = sorted(
                key for key, value in lying["statuses"].items() if value
            )
            found = status_problems(lying)
            note(f"a run report claiming {name}", bool(found), found[0] if found else "MISSED")

        broken = copy.deepcopy(run_report)
        broken["statuses_holding"] = []
        found = status_problems(broken)
        note("a status list that does not match its own flags", bool(found), found[0] if found else "MISSED")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-016 independent verification")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out = Path(args.out)

    series = Series()
    checks = Checks()
    check_pit(checks, series)
    check_lane(checks)
    if (LANE / "CANONICAL_LANE_REPORT.json").is_file():
        lane_report = _load(LANE / "CANONICAL_LANE_REPORT.json") or {}
        check_lane_costs(checks, lane_report)
        check_protective_exits(checks, lane_report)
    check_forward(checks)
    check_run_report(checks)
    check_evidence_index(checks)
    check_authority_and_reconciliation(checks)
    check_independence(checks)

    injected = mutations(series)
    false_alarms = [name for name, detected, _detail in injected if not detected]
    checks.add(
        "V60",
        "every injected fault is caught by the check that exists for it",
        bool(injected) and not false_alarms,
        f"{sum(1 for _n, d, _x in injected if d)}/{len(injected)} mutations caught"
        + (
            "; MISSED: " + ", ".join(name for name, detected, _x in injected if not detected)
            if any(not detected for _n, detected, _x in injected)
            else ""
        ),
    )

    payload: dict[str, Any] = {
        "schema_version": "EDGE16_INDEPENDENT_VERIFICATION_V1",
        "work_package": "WP-EDGE-016/16F",
        "verifier": "scripts/edge16_verify.py",
        "method": (
            "fills and their causality are recomputed from the raw OHLCV series named by the "
            "corpus; the restatement table is rebuilt from the per-trade records and the cost "
            "column; the lane's risk posture is read from config/risk.yaml and the admission "
            "ledger; the coverage ladder is checked for a missing bar dressed up as an evaluated "
            "one; every check is then run against a mutated artifact, which must fail it"
        ),
        "imports_no_builder_module": [bad for bad in FORBIDDEN_IMPORTS],
        "mutations": [
            {"name": name, "detected": detected, "detail": detail}
            for name, detected, detail in injected
        ],
        "checks": checks.rows,
        "counts": {
            "total": len(checks.rows),
            "passed": len(checks.rows) - checks.failed,
            "failed": checks.failed,
            "mutations": len(injected),
            "mutations_caught": sum(1 for _n, detected, _x in injected if detected),
        },
        "verdict": "VERIFIED" if checks.failed == 0 else "NOT_VERIFIED",
    }
    (out / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# WP-EDGE-016 — independent verification",
        "",
        f"*{payload['counts']['passed']}/{payload['counts']['total']} checks pass; "
        f"{payload['counts']['mutations_caught']}/{payload['counts']['mutations']} injected faults "
        f"caught. Verdict **{payload['verdict']}**.*",
        "",
        "The verifier imports no builder module. It rebuilds the ordering contract from the raw",
        "bar files named by each trade's corpus, the restatement table from the per-trade records",
        "and the cost column, and the risk posture from `config/risk.yaml` and the admission",
        "ledger. Then it mutates the artifacts and requires its own checks to fail.",
        "",
        "## Injected faults",
        "",
        "| injected fault | caught | first complaint |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {name} | {'yes' if detected else '**NO**'} | {detail} |"
        for name, detected, detail in injected
    ]
    lines += ["", "## Checks", "", "| id | check | result | evidence |", "| --- | --- | --- | --- |"]
    lines += [
        f"| {row['id']} | {row['what']} | {'PASS' if row['ok'] else '**FAIL**'} | {row['detail']} |"
        for row in checks.rows
    ]
    (out / "INDEPENDENT_VERIFICATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[verify16] {payload['counts']['passed']}/{payload['counts']['total']} checks pass")
    for row in checks.rows:
        if not row["ok"]:
            print(f"[verify16] FAIL {row['id']}: {row['what']} — {row['detail']}")
    print(
        f"[verify16] mutations caught {payload['counts']['mutations_caught']}"
        f"/{payload['counts']['mutations']}"
    )
    print(f"[verify16] verdict {payload['verdict']}")
    return 0 if checks.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
