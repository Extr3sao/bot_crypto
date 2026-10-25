"""Independent verifier for the WP-EDGE-01 closure experiments (H6 and the OOS review).

    python scripts/edge01_closure_verify.py [--experiment h6|oos|all] [--dir DIR]
                                            [--self-test] [--json-out FILE]

This process imports NOTHING from ``trading_bot``: it reads the published artefacts,
restates the frozen ruleset and the frozen decision rules from constants written here,
and recomputes what the payload claims — the metrics, the identities the book has to
satisfy, the lifecycle of every planned limit order, the verdicts themselves and the
window each row belongs to. If the run and the code disagreed about any of those, the
recomputation fails here rather than in prose.

``--self-test`` sabotages a copy of the artefacts once per mutation and requires the
declared check to break: a check nobody can break is a check nobody is running.
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
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable

TOL = 0.05


def _ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


INTRADAY_WINDOWS: dict[str, tuple[int, int]] = {
    "DEV": (_ms(2024, 10, 1), _ms(2025, 6, 30)),
    "VAL": (_ms(2025, 7, 1), _ms(2025, 12, 31)),
    "OOS": (_ms(2026, 1, 1), _ms(2026, 10, 7)),
}
TREND_WINDOWS: dict[str, tuple[int, int]] = {
    "DEV": (_ms(2019, 1, 1), _ms(2023, 12, 31)),
    "VAL": (_ms(2024, 1, 1), _ms(2024, 12, 31)),
    "OOS": (_ms(2025, 1, 1), _ms(2026, 2, 28)),
}

#: The frozen rulesets, restated here so the payload cannot quietly retune them.
FROZEN_INTRA_PARAMS: dict[str, Any] = {
    "resistance_lookback": 20,
    "atr_period": 14,
    "breakout_buffer_atr": 0.10,
    "volume_lookback": 20,
    "volume_mult": 1.20,
    "stop_atr_below_level": 0.50,
    "max_stop_atr": 2.50,
    "min_rr": 1.50,
    "cost_margin": 1.50,
    "trailing_atr": 2.00,
    "level_reset_atr": 1.00,
}
FROZEN_TREND_PARAMS: dict[str, Any] = {
    "ema_fast": 50,
    "ema_slow": 200,
    "breakout_lookback": 20,
    "atr_period": 14,
    "trailing_atr": 3.00,
    "exit_ema": 50,
    "cost_margin": 1.50,
}

#: The declared plan of the retest arm, restated: the expiry is the only number H6 adds
#: to the frozen ruleset, and the outcome codes are the vocabulary the book may print.
RETEST_EXPIRY_BARS = 8
RETEST_OUTCOMES = (
    "filled",
    "expired",
    "refused_by_risk_budget",
    "cancelled_close_below_level",
    "cancelled_window_end",
)
RETEST_UNREACHABLE = ("cancelled_close_below_level",)
RETEST_ARMS = ("frozen_market", "plan_market", "plan_limit")

#: H6's frozen decision rule, restated from the artefact's own declaration.
EXPECTED_H6_RULE: dict[str, Any] = {
    "primary_window": "DEV",
    "primary_scenario": "BASE",
    "baseline_arm": "frozen_market",
    "variant_arm": "plan_limit",
    "min_orders_placed": 100,
    "min_filled_trades": 50,
    "min_fill_rate": 0.40,
}
H6_CODES = (
    "RETEST_UNPOWERED",
    "RETEST_IMPROVES_NET",
    "RETEST_IMPROVES_EXPECTANCY_ONLY",
    "RETEST_DOES_NOT_HELP",
)
H6_EXECUTION_CODES = ("VIABLE", "STARVED")

#: The PAPER gate of the OOS review, restated from the artefact's own declaration.
EXPECTED_OOS_RULE: dict[str, Any] = {
    "decision_window": "OOS",
    "require_oos_net_positive": True,
    "require_oos_net_positive_under_2x_fees": True,
    "min_oos_trades": 30,
    "max_single_trade_share_of_net": 0.50,
    "min_positive_assets": 2,
    "require_drawdown_below_buy_and_hold": True,
    "min_positive_periods": 2,
}
EXPECTED_PERIODS: dict[str, tuple[int, int]] = {
    "2025H1": (_ms(2025, 1, 1), _ms(2025, 7, 1)),
    "2025H2": (_ms(2025, 7, 1), _ms(2026, 1, 1)),
    "2026Q1": (_ms(2026, 1, 1), _ms(2026, 3, 1)),
}
OOS_CODES = ("SUFFICIENT_EVIDENCE_FOR_PAPER", "NOT_SUFFICIENT_EVIDENCE", "UNPOWERED")
ASSETS = ("BTC", "ETH", "SOL")


class Fatal(Exception):
    """An artefact that cannot even be read: reported, never skipped."""


SPECS: dict[str, dict[str, Any]] = {
    "h6": {
        "label": "H6 retest entry",
        "root": "reports/edge-recovery/WP-EDGE-01/retest-h6",
        "payload": "RETEST.json",
        "verification": "RETEST_VERIFICATION.json",
        "markdown": "RETEST.md",
        "trades": "RETEST_TRADES.csv",
        "orders": "RETEST_ORDERS.csv",
        "signals": "RETEST_SIGNALS.csv",
        "refusals": "RETEST_REFUSALS.csv",
        "required": (
            "RETEST.json",
            "RETEST.md",
            "RETEST_TRADES.csv",
            "RETEST_ORDERS.csv",
            "RETEST_SIGNALS.csv",
            "RETEST_REFUSALS.csv",
            "MARKET_CONTEXT.csv",
        ),
        "windows": INTRADAY_WINDOWS,
        "bar_ms": 15 * 60 * 1000,
        "arms": RETEST_ARMS,
        "codes": H6_CODES,
        "execution_codes": H6_EXECUTION_CODES,
        "rule": EXPECTED_H6_RULE,
        "frozen_params": FROZEN_INTRA_PARAMS,
    },
    "oos": {
        "label": "OOS review of the 4h trend ruleset",
        "root": "reports/edge-recovery/WP-EDGE-01/oos-trend-4h",
        "payload": "OOS_TREND.json",
        "verification": "OOS_TREND_VERIFICATION.json",
        "markdown": "OOS_TREND.md",
        "trades": "OOS_TREND_TRADES.csv",
        "orders": "",
        "signals": "",
        "refusals": "",
        "assets": "OOS_TREND_ASSETS.csv",
        "periods": "OOS_TREND_PERIODS.csv",
        "regimes": "OOS_TREND_REGIMES.csv",
        "hold": "BUY_AND_HOLD.csv",
        "required": (
            "OOS_TREND.json",
            "OOS_TREND.md",
            "OOS_TREND_TRADES.csv",
            "OOS_TREND_ASSETS.csv",
            "OOS_TREND_PERIODS.csv",
            "OOS_TREND_REGIMES.csv",
            "BUY_AND_HOLD.csv",
            "MARKET_CONTEXT.csv",
        ),
        "windows": TREND_WINDOWS,
        "bar_ms": 4 * 60 * 60 * 1000,
        "arms": ("combined",) + ASSETS,
        "codes": OOS_CODES,
        "execution_codes": (),
        "rule": EXPECTED_OOS_RULE,
        "frozen_params": FROZEN_TREND_PARAMS,
    },
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Dataset:
    """The published artefacts, read as a reader reads them: files, not objects."""

    def __init__(self, root: Path, spec: dict[str, Any]) -> None:
        self.root = root
        self.spec = spec
        for name in spec["required"]:
            if not (root / name).exists():
                raise Fatal(f"missing artefact {name} under {root}")
        self.payload = json.loads((root / spec["payload"]).read_text(encoding="utf-8"))
        self.trades = _read_csv(root / spec["trades"])
        self.market_rows = _read_csv(root / "MARKET_CONTEXT.csv")
        self.orders = _read_csv(root / spec["orders"]) if spec.get("orders") else []
        self.signals = _read_csv(root / spec["signals"]) if spec.get("signals") else []
        self.refusals = _read_csv(root / spec["refusals"]) if spec.get("refusals") else []
        self.asset_rows = _read_csv(root / spec["assets"]) if spec.get("assets") else []
        self.period_rows = _read_csv(root / spec["periods"]) if spec.get("periods") else []
        self.regime_rows = _read_csv(root / spec["regimes"]) if spec.get("regimes") else []
        self.hold_rows = _read_csv(root / spec["hold"]) if spec.get("hold") else []
        self.markdown = (root / spec["markdown"]).read_text(encoding="utf-8")

    def experiment(self) -> dict[str, Any]:
        return self.payload.get("experiment") or {}

    def runs(self) -> dict[str, Any]:
        return self.payload.get("runs") or {}

    def run(self, key: str) -> dict[str, Any]:
        runs = self.runs()
        if key not in runs:
            raise Fatal(f"{self.spec['payload']} has no run {key!r}")
        return runs[key]

    def book(self, run_key: str, name: str) -> dict[str, Any]:
        run = self.run(run_key)
        if name == "combined":
            return run["combined"]
        if name in (run.get("assets") or {}):
            return run["assets"][name]
        raise Fatal(f"run {run_key!r} has no book {name!r}")

    def trades_for(self, run_key: str, book: str) -> list[dict[str, str]]:
        return [row for row in self.trades if row.get("run") == run_key and row.get("book") == book]

    def orders_for(self, run_key: str) -> list[dict[str, str]]:
        return [row for row in self.orders if row.get("run") == run_key]


def _f(row: dict[str, Any], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise Fatal(f"row is missing a numeric {key!r}: {row}") from exc


def _tol(rows: list[dict[str, str]]) -> float:
    return max(TOL, TOL * len(rows) / 20.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _close(left: float, right: float, tol: float) -> bool:
    return abs(left - right) <= tol


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _sum(rows: list[dict[str, str]], key: str) -> float:
    return sum(_f(row, key) for row in rows)


def _window_bounds(spec: dict[str, Any], window: str) -> tuple[int, int]:
    if window not in spec["windows"]:
        raise Fatal(f"{window!r} is not a declared window")
    return spec["windows"][window]


def _trades_for(ds: Dataset, run_key: str, arm: str) -> list[dict[str, str]]:
    """The rows of one book: H6 tags them with ``arm``, the OOS review with ``book``."""
    key = "arm" if ds.spec.get("orders") else "book"
    return [
        row
        for row in ds.trades
        if row.get("run") == run_key and row.get(key) == arm
    ]


def _book(ds: Dataset, run_key: str, arm: str) -> dict[str, Any]:
    run = ds.run(run_key)
    if ds.spec.get("orders"):
        arms = run.get("arms") or {}
        if arm not in arms:
            raise Fatal(f"run {run_key!r} has no arm {arm!r}")
        return arms[arm]
    if arm == "combined":
        return run["combined"]
    assets = run.get("assets") or {}
    if arm not in assets:
        raise Fatal(f"run {run_key!r} has no asset book {arm!r}")
    return assets[arm]


# --------------------------------------------------------------------------- #
# Checks shared by both experiments
# --------------------------------------------------------------------------- #


def check_artifacts_present(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    declared = ds.payload.get("artifacts") or {}
    if not declared:
        return False, "the payload declares no artefact inventory"
    for name, entry in declared.items():
        path = ds.root / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        if _sha256(path) != entry.get("sha256"):
            problems.append(f"{name}: sha256 does not match the inventory")
        if int(entry.get("bytes") or -1) != path.stat().st_size:
            problems.append(f"{name}: {path.stat().st_size} bytes, inventory says {entry.get('bytes')}")
    for name in ds.spec["required"]:
        if name != ds.spec["payload"] and name not in declared:
            problems.append(f"{name}: present but not in the inventory")
    return (not problems), "; ".join(problems) or f"{len(declared)} artefactos, digests y tamanos verificados"


def check_params_unchanged(ds: Dataset) -> tuple[bool, str]:
    """The frozen ruleset must be the frozen ruleset, restated independently here."""
    frozen = ds.spec["frozen_params"]
    problems: list[str] = []
    detail: list[str] = []
    exp = ds.experiment()
    if ds.spec.get("orders"):
        declared = exp.get("frozen_params_baseline") or {}
        if declared != frozen:
            problems.append(f"experiment.frozen_params_baseline != the restated ruleset: {declared}")
        for key, run in ds.runs().items():
            for arm_name, arm in run["arms"].items():
                if arm.get("params") != frozen:
                    problems.append(f"{key}/{arm_name}: params differ from the frozen ruleset")
                delta = arm.get("params_delta") or {}
                if any(delta.get(name) for name in ("added", "removed", "changed")):
                    problems.append(f"{key}/{arm_name}: params_delta is not empty: {delta}")
        detail.append(f"{len(ds.runs())} runs x {len(ds.spec['arms'])} arms keep the frozen ruleset")
        variant = exp.get("variant_params") or {}
        if int(variant.get("retest_expiry_bars") or -1) != RETEST_EXPIRY_BARS:
            problems.append(
                f"the declared expiry is {variant.get('retest_expiry_bars')!r}, "
                f"not the restated {RETEST_EXPIRY_BARS}"
            )
        detail.append(f"expiry {RETEST_EXPIRY_BARS} bars declared with the plan")
    else:
        declared = exp.get("frozen_params") or {}
        if declared != frozen:
            problems.append(f"experiment.frozen_params != the restated ruleset: {declared}")
        hashes = {str(run.get("combined", {}).get("params_hash")) for run in ds.runs().values()}
        if hashes != {str(ds.payload.get("params_hash"))}:
            problems.append(f"run params_hash {sorted(hashes)} != payload params_hash")
        if len(str(ds.payload.get("params_hash"))) != 64:
            problems.append("params_hash is not a sha256 hex digest")
        detail.append(f"params_hash {str(ds.payload.get('params_hash'))[:12]}… on every run")
    return (not problems), "; ".join(problems) or "; ".join(detail)


def check_equity_conservation(ds: Dataset) -> tuple[bool, str]:
    """start + the sum of the trades must be the final equity, per book."""
    problems: list[str] = []
    start = float((ds.experiment().get("risk_policy") or {}).get("start_equity") or 0.0)
    if start <= 0:
        return False, "the payload does not state the starting equity"
    books = 0
    for key in ds.runs():
        for arm in ds.spec["arms"]:
            rows = _trades_for(ds, key, arm)
            block = _book(ds, key, arm)
            if len(rows) != int(block.get("trades") or 0):
                problems.append(f"{key}/{arm}: {len(rows)} trade rows but {block.get('trades')} declared")
            total = _sum(rows, "net")
            expected = start + total
            declared = float(block.get("final_equity") or 0.0)
            if not _close(expected, declared, _tol(rows)):
                problems.append(
                    f"{key}/{arm}: start {start:,.2f} + net {total:,.2f} = {expected:,.2f} "
                    f"!= final equity {declared:,.2f}"
                )
            if not _close(total, float(block.get("net_usdt") or 0.0), _tol(rows)):
                problems.append(
                    f"{key}/{arm}: the rows sum to {total:,.4f} but the payload says "
                    f"{block.get('net_usdt')}"
                )
            books += 1
    if problems:
        return False, "; ".join(problems[:6])
    return True, f"{books} libros: capital inicial + suma de operaciones = capital final, al centavo"


def check_cost_split_identity(ds: Dataset) -> tuple[bool, str]:
    """Every trade row must decompose its own result, on both sides of the book."""
    problems: list[str] = []
    tol = TOL
    checked = 0
    for row in ds.trades:
        checked += 1
        gross = _f(row, "gross")
        fees = _f(row, "fees")
        costs = _f(row, "price_costs")
        net = _f(row, "net")
        if abs((gross - costs - fees) - net) > tol:
            problems.append(
                f"{row.get('run')}/{row.get('asset')}: gross {gross:.4f} - costs {costs:.4f} "
                f"- fees {fees:.4f} != net {net:.4f}"
            )
        fills = (_f(row, "exit_fill") - _f(row, "entry_fill")) * _f(row, "qty") - fees
        if abs(fills - net) > tol:
            problems.append(f"fills x qty - fees = {fills:.4f} != net {net:.4f}")
        if _f(row, "qty") <= 0 or _f(row, "notional") <= 0:
            problems.append("a trade carries a non-positive size")
        if len(problems) > 5:
            break
    return (not problems), "; ".join(problems) or f"{checked} operaciones cuadran gross - costes - fees = net"


def check_metrics_recomputed(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    detail: list[str] = []
    for key in ds.runs():
        for arm in ds.spec["arms"]:
            rows = _trades_for(ds, key, arm)
            block = _book(ds, key, arm)
            tol = _tol(rows)
            nets = [_f(r, "net") for r in rows]
            wins = [n for n in nets if n > 0]
            losses = [n for n in nets if n <= 0]
            checks = {
                "net_usdt": sum(nets),
                "gross_usdt": _sum(rows, "gross"),
                "fees_usdt": _sum(rows, "fees"),
                "price_costs_usdt": _sum(rows, "price_costs"),
                "expectancy_usdt": (sum(nets) / len(nets)) if nets else 0.0,
                "win_rate_pct": (100.0 * len(wins) / len(nets)) if nets else 0.0,
                "profit_factor": (sum(wins) / abs(sum(losses))) if losses else 0.0,
                "avg_duration_min": (sum(_f(r, "duration_min") for r in rows) / len(rows)) if rows else 0.0,
            }
            for name, recomputed in checks.items():
                declared = block.get(name)
                if declared is None:
                    problems.append(f"{key}/{arm}: {name} is missing from the payload")
                    continue
                scale = max(abs(recomputed), abs(float(declared)), 1.0)
                if not _close(recomputed, float(declared), max(tol, scale * 1e-6)):
                    problems.append(
                        f"{key}/{arm}: {name} declared {declared} vs recomputed {recomputed:,.6f}"
                    )
            detail.append(f"{key}/{arm}: {len(rows)} ops")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def check_market_context_attribution(ds: Dataset) -> tuple[bool, str]:
    """Every trade cites the benchmark label readable at its own decision instant."""
    rows = ds.market_rows
    if not rows:
        return False, "MARKET_CONTEXT.csv is empty: every trade cites a benchmark label"
    declared = ds.payload.get("market_context") or {}
    if not str(declared.get("rule") or ""):
        return False, "the payload does not state the market-context rule"
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
    declared_days = declared.get("days")
    if declared_days is not None and int(declared_days) != len(days):
        problems.append(f"the payload declares {declared_days} benchmark days, the file has {len(days)}")
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
                f"{row.get('run')}/{row.get('asset')} @ {row.get('decision_ts')}: market_context "
                f"{actual!r} != {expected!r} readable at that instant"
            )
        if len(problems) > 5:
            break
    spread = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return (not problems), "; ".join(problems) or (
        f"{len(ds.trades)} operaciones atribuidas desde {len(days)} dias de benchmark ({spread})"
    )


def check_window_is_declared(ds: Dataset) -> tuple[bool, str]:
    """Every run and every row must belong to the window it claims to belong to."""
    problems: list[str] = []
    detail: list[str] = []
    for key, run in ds.runs().items():
        window = str(run.get("window"))
        start, end = _window_bounds(ds.spec, window)
        if int(run.get("window_start_ms") or -1) != start or int(run.get("window_end_ms") or -1) != end:
            problems.append(
                f"{key}: declares {run.get('window_start_ms')}..{run.get('window_end_ms')} "
                f"but {window} is {start}..{end}"
            )
        rows = [row for row in ds.trades if row.get("run") == key]
        for row in rows:
            for column in ("decision_ts", "entry_ts", "exit_ts"):
                stamp = int(_f(row, column))
                if not (start <= stamp <= end):
                    problems.append(f"{key}/{row.get('asset')}: {column}={stamp} outside {window}")
                    break
        for row in ds.orders_for(key):
            for column in ("placement_ts", "outcome_ts"):
                if row.get(column) in (None, "", "None"):
                    problems.append(f"{key}: an order has no {column}")
                    continue
                stamp = int(float(row[column]))
                if not (start <= stamp <= end):
                    problems.append(f"{key}/{row.get('asset')}: {column}={stamp} outside {window}")
        detail.append(f"{key}: {len(rows)} operaciones dentro de {window}")
        if problems and len(problems) > 5:
            break
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


# --------------------------------------------------------------------------- #
# H6 checks
# --------------------------------------------------------------------------- #


def check_orders_lifecycle(ds: Dataset) -> tuple[bool, str]:
    """Every planned order ends with a declared outcome, on the bar its rules allow."""
    problems: list[str] = []
    counts: dict[str, int] = {}
    for row in ds.orders:
        outcome = str(row.get("outcome"))
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome not in RETEST_OUTCOMES:
            problems.append(f"{row.get('run')}/{row.get('asset')}: outcome {outcome!r} is not declared")
            continue
        if outcome == "RESTING":
            problems.append(f"{row.get('run')}/{row.get('asset')}: an order is still resting")
        if int(float(row.get("expiry_bars") or 0)) != RETEST_EXPIRY_BARS:
            problems.append(
                f"{row.get('run')}/{row.get('asset')}: expiry {row.get('expiry_bars')} != the "
                f"declared {RETEST_EXPIRY_BARS}"
            )
        placed = int(float(row.get("placed_bar") or 0))
        ended = int(float(row.get("outcome_bar") or 0))
        resting = int(float(row.get("bars_resting") or 0))
        if resting != max(0, ended - placed):
            problems.append(f"bars_resting {resting} != {ended} - {placed}")
        if float(row.get("outcome_ts") or 0) < float(row.get("placement_ts") or 0):
            problems.append(f"{row.get('asset')}: the order ends before it was placed")
        if outcome == "filled":
            if ended <= placed:
                problems.append(f"{row.get('asset')}: a fill on bar {ended} placed on bar {placed}")
            if resting > RETEST_EXPIRY_BARS:
                problems.append(f"{row.get('asset')}: filled after the expiry ({resting} bars)")
        if outcome == "expired" and resting != RETEST_EXPIRY_BARS + 1:
            problems.append(
                f"{row.get('asset')}: expired after {resting} bars, not on the first bar past "
                f"the {RETEST_EXPIRY_BARS}-bar window"
            )
        if outcome == "refused_by_risk_budget" and not str(row.get("refusal_reason") or ""):
            problems.append(f"{row.get('asset')}: refused by the budget without saying why")
        level = float(row.get("level") or 0.0)
        close = float(row.get("breakout_close") or 0.0)
        stop = float(row.get("stop") or 0.0)
        target = float(row.get("target") or 0.0)
        if not (stop < level < target):
            problems.append(f"{row.get('asset')}: stop {stop} / nivel {level} / target {target} desordenados")
        if close > 0 and not _close(float(row.get("discount_bps") or 0.0), (close - level) / close * 10_000.0, 0.01):
            problems.append(f"{row.get('asset')}: discount_bps does not recompute")
        if len(problems) > 5:
            break
    spread = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return (not problems), "; ".join(problems[:6]) or f"{len(ds.orders)} ordenes terminadas ({spread})"


def check_filled_orders_match_trades(ds: Dataset) -> tuple[bool, str]:
    """A filled order is a trade, and a trade is a filled order: one to one."""
    problems: list[str] = []
    detail: list[str] = []
    variant_arm = str(EXPECTED_H6_RULE["variant_arm"])
    for key, run in ds.runs().items():
        for arm_name, arm in run["arms"].items():
            if arm_name != variant_arm:
                continue  # only the arm that rests orders can have one per trade
            filled = [
                row
                for row in ds.orders_for(key)
                if row.get("arm") == arm_name and row.get("outcome") == "filled"
            ]
            rows = _trades_for(ds, key, arm_name)
            if len(rows) != len(filled):
                problems.append(f"{key}/{arm_name}: {len(filled)} rellenos pero {len(rows)} operaciones")
                continue
            index: dict[tuple[str, int], list[dict[str, str]]] = {}
            for row in rows:
                index.setdefault((row["asset"], int(_f(row, "entry_ts"))), []).append(row)
            for order in filled:
                cell = index.get((order["asset"], int(float(order["outcome_ts"]))))
                if not cell:
                    problems.append(
                        f"{key}/{arm_name}: el relleno de {order['asset']} en {order['outcome_ts']} "
                        "no tiene operacion"
                    )
                    continue
                if len(cell) > 1:
                    problems.append(f"{key}/{arm_name}: dos operaciones reclaman un relleno")
                if not _close(float(cell[0]["entry_mid"]), float(order["level"]), 1e-6):
                    problems.append(
                        f"{key}/{arm_name}: la operacion entro en {cell[0]['entry_mid']} pero la "
                        f"orden esperaba en {order['level']}"
                    )
            if arm_name == "plan_limit" and int(arm.get("orders_filled") or 0) != len(filled):
                problems.append(
                    f"{key}/{arm_name}: el payload dice {arm.get('orders_filled')} rellenos, el "
                    f"fichero tiene {len(filled)}"
                )
            detail.append(f"{key}/{arm_name}: {len(filled)} ordenes <-> {len(rows)} operaciones")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def check_limit_is_never_better(ds: Dataset) -> tuple[bool, str]:
    """A limit fill is scored at the limit, never better, and pays its own costs."""
    problems: list[str] = []
    fills = 0
    for key in ds.runs():
        orders = {
            (row["asset"], int(float(row["outcome_ts"]))): row
            for row in ds.orders_for(key)
            if row.get("arm") == "plan_limit" and row.get("outcome") == "filled"
        }
        for row in _trades_for(ds, key, "plan_limit"):
            order = orders.get((row["asset"], int(_f(row, "entry_ts"))))
            if order is None:
                problems.append(f"{key}/{row['asset']}: una operacion sin su orden")
                continue
            entry_mid = _f(row, "entry_mid")
            entry_fill = _f(row, "entry_fill")
            level = float(order["level"])
            if not _close(entry_mid, level, 1e-9):
                problems.append(f"{key}/{row['asset']}: la operacion se puntuo en {entry_mid}, no en el nivel {level}")
            if entry_fill < entry_mid:
                problems.append(f"{key}/{row['asset']}: el relleno {entry_fill} es mejor que el limite {entry_mid}")
            if entry_mid > 0 and (entry_fill / entry_mid - 1.0) * 10_000.0 > 200.0:
                problems.append(f"{key}/{row['asset']}: la entrada cuesta mas de 200 bps en un limite")
            fills += 1
            if len(problems) > 5:
                break
    return (not problems), "; ".join(problems[:6]) or (
        f"{fills} rellenos limite: puntuados en el nivel exacto, ninguno mejor, con sus costes"
    )


def check_no_plan_on_the_market_arms(ds: Dataset) -> tuple[bool, str]:
    """The frozen arm never plans a limit, and only the limit arm rests orders."""
    problems: list[str] = []
    detail: list[str] = []
    for key, run in ds.runs().items():
        for arm_name in run["arms"]:
            orders = [row for row in ds.orders_for(key) if row.get("arm") == arm_name]
            signals = [
                row for row in ds.signals if row.get("run") == key and row.get("arm") == arm_name
            ]
            planned = sum(1 for row in signals if str(row.get("entry_limit") or ""))
            if arm_name == "plan_limit":
                if not orders:
                    problems.append(f"{key}/{arm_name}: no hay ninguna orden en la rama limite")
                if planned != len(signals):
                    problems.append(f"{key}/{arm_name}: {len(signals) - planned} senales sin plan")
                for order in orders:
                    match = [
                        row
                        for row in signals
                        if row["asset"] == order["asset"]
                        and int(float(row["decision_ts"])) == int(float(order["placement_ts"]))
                    ]
                    if not match:
                        problems.append(f"{key}: una orden sin senal detras")
                    elif not _close(float(match[0]["entry_limit"]), float(order["level"]), 1e-9):
                        problems.append(f"{key}: el nivel de la orden no es la entrada planificada de la senal")
            elif orders:
                problems.append(f"{key}/{arm_name}: {len(orders)} ordenes en una rama de mercado")
            if arm_name == "frozen_market" and planned:
                problems.append(f"{key}: {planned} senales congeladas planifican un limite")
            if arm_name == "plan_market" and planned != len(signals):
                problems.append(f"{key}/{arm_name}: la rama del plan imprime senales sin plan")
            detail.append(f"{key}/{arm_name}: {len(orders)} ordenes, {planned}/{len(signals)} senales con plan")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def check_unreachable_outcome_absent(ds: Dataset) -> tuple[bool, str]:
    """A declared-unreachable outcome must be declared, explained, and never printed."""
    declared = ds.experiment().get("unreachable_outcomes") or {}
    problems: list[str] = []
    for name in RETEST_UNREACHABLE:
        if name not in declared:
            problems.append(f"{name} no esta declarado")
        elif len(str(declared[name])) < 40:
            problems.append(f"{name} se declara sin explicar por que")
        seen = sum(1 for row in ds.orders if row.get("outcome") == name)
        if seen:
            problems.append(f"{name} aparece {seen} veces aunque se declaro inalcanzable")
    return (not problems), "; ".join(problems[:6]) or (
        "declarado e inalcanzable: " + ", ".join(RETEST_UNREACHABLE)
    )


def check_fill_rate_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The order summary must be the outcomes of the order file, not a summary of them."""
    problems: list[str] = []
    detail: list[str] = []
    for key, run in ds.runs().items():
        for arm_name, arm in run["arms"].items():
            rows = [row for row in ds.orders_for(key) if row.get("arm") == arm_name]
            outcomes: dict[str, int] = {}
            for row in rows:
                name = str(row.get("outcome"))
                outcomes[name] = outcomes.get(name, 0) + 1
            if int(arm.get("orders_placed") or 0) != len(rows):
                problems.append(f"{key}/{arm_name}: {len(rows)} filas pero {arm.get('orders_placed')} declaradas")
            if (arm.get("orders_by_outcome") or {}) != outcomes:
                problems.append(f"{key}/{arm_name}: declarado {arm.get('orders_by_outcome')} vs fichero {outcomes}")
            filled = outcomes.get("filled", 0)
            if int(arm.get("orders_filled") or 0) != filled:
                problems.append(f"{key}/{arm_name}: {filled} rellenos en el fichero, {arm.get('orders_filled')} declarados")
            rate = (filled / len(rows)) if rows else None
            declared_rate = arm.get("fill_rate")
            if rate is None and declared_rate is not None:
                problems.append(f"{key}/{arm_name}: hay fill rate sin ordenes")
            elif rate is not None and not _close(float(declared_rate or 0.0), rate, 1e-6):
                problems.append(f"{key}/{arm_name}: fill rate {declared_rate} vs {rate:.6f}")
            medians = {
                "median_discount_bps": _median(
                    [float(row["discount_bps"]) for row in rows if str(row.get("discount_bps") or "")]
                ),
                "median_bars_resting": _median([float(row.get("bars_resting") or 0) for row in rows]),
            }
            for name, value in medians.items():
                declared_value = arm.get(name)
                if value is None and declared_value is None:
                    continue
                if value is None or declared_value is None or not _close(float(declared_value), value, 1e-6):
                    problems.append(f"{key}/{arm_name}: {name} declarado {declared_value} vs {value}")
            detail.append(f"{key}/{arm_name}: {len(rows)} ordenes")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def _recompute_h6(ds: Dataset) -> tuple[str, str, str]:
    """The declared rule applied to the published arms, in a process that ran nothing."""
    window = str(EXPECTED_H6_RULE["primary_window"])
    scenario = str(EXPECTED_H6_RULE["primary_scenario"])
    arms = ds.run(f"{window}:{scenario}")["arms"]
    baseline = arms[str(EXPECTED_H6_RULE["baseline_arm"])]
    variant = arms[str(EXPECTED_H6_RULE["variant_arm"])]
    orders = int(variant.get("orders_placed") or 0)
    fills = int(variant.get("orders_filled") or 0)
    rate = float(variant.get("fill_rate") or 0.0)
    net_delta = float(variant["net_usdt"]) - float(baseline["net_usdt"])
    exp_delta = float(variant.get("expectancy_usdt") or 0.0) - float(
        baseline.get("expectancy_usdt") or 0.0
    )
    if orders < int(EXPECTED_H6_RULE["min_orders_placed"]) or fills < int(
        EXPECTED_H6_RULE["min_filled_trades"]
    ):
        verdict = "RETEST_UNPOWERED"
    elif net_delta > 0.0 and exp_delta > 0.0:
        verdict = "RETEST_IMPROVES_NET"
    elif exp_delta > 0.0:
        verdict = "RETEST_IMPROVES_EXPECTANCY_ONLY"
    else:
        verdict = "RETEST_DOES_NOT_HELP"
    execution = "VIABLE" if rate >= float(EXPECTED_H6_RULE["min_fill_rate"]) else "STARVED"
    detail = (
        f"net {float(variant['net_usdt']):,.4f} vs {float(baseline['net_usdt']):,.4f} "
        f"({net_delta:+,.4f}) | expectativa {exp_delta:+,.6f} | {fills}/{orders} rellenos "
        f"({rate:.2%})"
    )
    return verdict, execution, detail


def check_verdict_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The verdict must be the frozen rule applied to the published numbers."""
    declared_rule = ds.payload["verdict"].get("decision_rule") or {}
    problems = [
        f"decision_rule.{key} = {declared_rule.get(key)!r}, se esperaba {value!r}"
        for key, value in EXPECTED_H6_RULE.items()
        if declared_rule.get(key) != value
    ]
    for key, value in (ds.experiment().get("decision_rule") or {}).items():
        if key in EXPECTED_H6_RULE and value != EXPECTED_H6_RULE[key]:
            problems.append(f"experiment.decision_rule.{key} = {value!r}")
    verdict, execution, detail = _recompute_h6(ds)
    if verdict not in H6_CODES:
        problems.append(f"el veredicto recalculado {verdict!r} no es un codigo declarado")
    if execution not in H6_EXECUTION_CODES:
        problems.append(f"la lectura de ejecucion {execution!r} no es un codigo declarado")
    if ds.payload["verdict"].get("verdict") != verdict:
        problems.append(
            f"el payload dice {ds.payload['verdict'].get('verdict')!r}, la regla da {verdict!r}"
        )
    if ds.payload["verdict"].get("execution") != execution:
        problems.append(
            f"el payload dice ejecucion {ds.payload['verdict'].get('execution')!r}, la regla da {execution!r}"
        )
    dev = ds.run("DEV:BASE")["arms"]
    for key, expected in (
        ("baseline_net_usdt", float(dev["frozen_market"]["net_usdt"])),
        ("variant_net_usdt", float(dev["plan_limit"]["net_usdt"])),
    ):
        if not _close(float(ds.payload["verdict"].get(key) or 0.0), expected, TOL):
            problems.append(f"verdict.{key} no es el neto de su rama")
    return (not problems), "; ".join(problems[:6]) or f"{verdict} / {execution}: {detail}"


def check_confirmation_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The confirmation windows are what the runs say, and DEV is not one of them."""
    problems: list[str] = []
    primary = str(EXPECTED_H6_RULE["primary_window"])
    if str(ds.experiment().get("primary_window")) != primary:
        problems.append(
            f"la ventana primaria es {ds.experiment().get('primary_window')!r}, no {primary!r}"
        )
    declared = ds.payload.get("confirmation") or {}
    if primary in declared:
        problems.append("la ventana de decision figura como ventana de confirmacion")
    for window, block in declared.items():
        arms = ds.run(f"{window}:BASE")["arms"]
        expected = {
            "baseline_net_usdt": float(arms["frozen_market"]["net_usdt"]),
            "variant_net_usdt": float(arms["plan_limit"]["net_usdt"]),
            "net_delta_usdt": float(arms["plan_limit"]["net_usdt"])
            - float(arms["frozen_market"]["net_usdt"]),
            "trades": int(arms["plan_limit"]["trades"]),
        }
        for key, value in expected.items():
            if not _close(float(block.get(key) or 0.0), value, TOL):
                problems.append(f"confirmation.{window}.{key} declarado {block.get(key)} vs {value:.4f}")
        rate = arms["plan_limit"].get("fill_rate")
        if rate is not None and not _close(float(block.get("fill_rate") or 0.0), float(rate), 1e-9):
            problems.append(f"confirmation.{window}.fill_rate no es el fill rate de su rama")
    if set(declared) != set(ds.experiment()["windows"]) - {primary}:
        problems.append(
            f"las ventanas de confirmacion {sorted(declared)} no son las no primarias declaradas"
        )
    return (not problems), "; ".join(problems[:6]) or (
        f"decision en {primary}; confirmacion en {', '.join(sorted(declared))}"
    )


# --------------------------------------------------------------------------- #
# OOS review checks
# --------------------------------------------------------------------------- #


def _recompute_oos(ds: Dataset) -> tuple[str, list[dict[str, Any]]]:
    """The declared PAPER gate, applied to the published numbers, by a reader."""
    window = str(EXPECTED_OOS_RULE["decision_window"])
    run = ds.run(f"{window}:BASE")
    combined = run["combined"]
    stress = ds.run(f"{window}:2X_FEES")["combined"]
    checks: list[dict[str, Any]] = []

    def add(criterion: str, passed: bool, detail: str) -> None:
        checks.append({"criterion": criterion, "result": "PASS" if passed else "FAIL", "detail": detail})

    trades = int(combined["trades"])
    net = float(combined["net_usdt"] or 0.0)
    add("oos_net_positive", net > 0, f"neto OOS {net:,.2f} USDT")
    stress_net = float(stress["net_usdt"] or 0.0)
    add("oos_net_positive_under_2x_fees", stress_net > 0, f"neto OOS con 2x fees {stress_net:,.2f} USDT")
    add(
        "oos_trades_floor",
        trades >= int(EXPECTED_OOS_RULE["min_oos_trades"]),
        f"{trades} operaciones OOS contra el suelo {EXPECTED_OOS_RULE['min_oos_trades']}",
    )
    share = combined.get("largest_trade_share_of_net")
    add(
        "no_single_trade_carries_the_net",
        share is not None and float(share) <= float(EXPECTED_OOS_RULE["max_single_trade_share_of_net"]),
        f"la mayor operacion es {share} del neto OOS",
    )
    positive = [
        asset for asset, block in run["assets"].items() if float(block["net_usdt"] or 0.0) > 0
    ]
    add(
        "assets_positive",
        len(positive) >= int(EXPECTED_OOS_RULE["min_positive_assets"]),
        f"{len(positive)}/{len(run['assets'])} libros por activo positivos ({', '.join(positive) or 'ninguno'})",
    )
    candidate_dd = float(combined["max_drawdown_pct"] or 0.0)
    hold_dd = max((float(block["max_drawdown_pct"] or 0.0) for block in run["buy_and_hold"].values()), default=0.0)
    add(
        "drawdown_below_buy_and_hold",
        candidate_dd < hold_dd,
        f"drawdown OOS {candidate_dd:.2f}% contra el mayor drawdown de buy & hold {hold_dd:.2f}%",
    )
    periods = [row["period"] for row in run["periods"] if float(row["net_usdt"]) > 0]
    add(
        "periods_positive",
        len(periods) >= int(EXPECTED_OOS_RULE["min_positive_periods"]),
        f"{len(periods)}/{len(run['periods'])} periodos OOS positivos ({', '.join(periods) or 'ninguno'})",
    )
    failed = [check for check in checks if check["result"] == "FAIL"]
    if trades < int(EXPECTED_OOS_RULE["min_oos_trades"]):
        verdict = "UNPOWERED"
    elif failed:
        verdict = "NOT_SUFFICIENT_EVIDENCE"
    else:
        verdict = "SUFFICIENT_EVIDENCE_FOR_PAPER"
    return verdict, checks


def check_oos_verdict_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The PAPER verdict must be the declared gate applied to the published numbers."""
    problems: list[str] = []
    declared_rule = ds.payload["verdict"].get("decision_rule") or {}
    for key, value in EXPECTED_OOS_RULE.items():
        if declared_rule.get(key) != value:
            problems.append(f"decision_rule.{key} = {declared_rule.get(key)!r}, se esperaba {value!r}")
    verdict, checks = _recompute_oos(ds)
    published = ds.payload["verdict"].get("checks") or []
    if [c["criterion"] for c in published] != [c["criterion"] for c in checks]:
        problems.append(
            f"los criterios publicados {[c['criterion'] for c in published]} no son los declarados "
            f"{[c['criterion'] for c in checks]}"
        )
    else:
        for mine, theirs in zip(checks, published):
            if theirs.get("result") != mine["result"]:
                problems.append(
                    f"{mine['criterion']}: publicado {theirs.get('result')!r}, recalculado {mine['result']!r}"
                )
            if not str(theirs.get("detail") or ""):
                problems.append(f"{mine['criterion']}: sin detalle publicado")
    if verdict not in OOS_CODES:
        problems.append(f"el veredicto recalculado {verdict!r} no es un codigo declarado")
    if ds.payload["verdict"].get("verdict") != verdict:
        problems.append(f"el payload dice {ds.payload['verdict'].get('verdict')!r}, la regla da {verdict!r}")
    failures = [check["criterion"] for check in checks if check["result"] == "FAIL"]
    reasons = ds.payload["verdict"].get("reasons") or []
    if verdict == "NOT_SUFFICIENT_EVIDENCE" and not reasons:
        problems.append("el veredicto falla sin nombrar el criterio que falla")
    if verdict == "NOT_SUFFICIENT_EVIDENCE" and len(reasons) != len(failures):
        problems.append(f"{len(failures)} criterios fallan y se publican {len(reasons)} motivos")
    detail = f"{verdict}: falla {', '.join(failures) if failures else 'nada'}"
    return (not problems), "; ".join(problems[:6]) or detail


def check_asset_books_recomputed(ds: Dataset) -> tuple[bool, str]:
    """Each single-asset book is recomputed from its own published trades."""
    problems: list[str] = []
    detail: list[str] = []
    published_csv = {(row["run"], row["asset"]): row for row in ds.asset_rows}
    for key in ds.runs():
        for asset in ds.spec["arms"]:
            if asset == "combined":
                continue
            rows = _trades_for(ds, key, asset)
            if any(row["asset"] != asset for row in rows):
                problems.append(f"{key}/{asset}: un libro por activo contiene otro activo")
            block = _book(ds, key, asset)
            nets = [_f(row, "net") for row in rows]
            wins = [n for n in nets if n > 0]
            expected = {
                "trades": len(rows),
                "net_usdt": sum(nets),
                "expectancy_usdt": (sum(nets) / len(nets)) if nets else None,
                "win_rate_pct": (100.0 * len(wins) / len(nets)) if nets else None,
            }
            for name, value in expected.items():
                declared_value = block.get(name)
                if value is None or declared_value is None:
                    if value != declared_value:
                        problems.append(f"{key}/{asset}: {name} declarado {declared_value} vs {value}")
                    continue
                if not _close(float(declared_value), float(value), _tol(rows)):
                    problems.append(f"{key}/{asset}: {name} declarado {declared_value} vs {float(value):,.6f}")
            csv_row = published_csv.get((key, asset))
            if csv_row is None:
                problems.append(f"{key}/{asset}: no aparece en {ds.spec['assets']}")
            else:
                for name in ("trades", "net_usdt", "max_drawdown_pct"):
                    if str(csv_row.get(name)) != str(block.get(name)):
                        problems.append(f"{key}/{asset}: {name} difiere entre el CSV y el JSON")
            detail.append(f"{key}/{asset}: {len(rows)} ops, {sum(nets):,.2f} USDT")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def check_periods_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The calendar decomposition must be the trades it claims to decompose."""
    problems: list[str] = []
    detail: list[str] = []
    published = {(row["run"], row["period"]): row for row in ds.period_rows}
    for key in ds.runs():
        rows = _trades_for(ds, key, "combined")
        declared = {row["period"]: row for row in ds.run(key)["periods"]}
        if set(declared) != set(EXPECTED_PERIODS):
            problems.append(f"{key}: periodos {sorted(declared)} != declarados {sorted(EXPECTED_PERIODS)}")
        for name, (start, end) in EXPECTED_PERIODS.items():
            subset = [row for row in rows if start <= int(_f(row, "decision_ts")) < end]
            nets = [_f(row, "net") for row in subset]
            wins = [n for n in nets if n > 0]
            block = declared.get(name)
            if block is None:
                problems.append(f"{key}: falta el periodo {name}")
                continue
            if int(block.get("trades") or 0) != len(subset):
                problems.append(f"{key}/{name}: {block.get('trades')} declaradas vs {len(subset)} filas")
            if not _close(float(block.get("net_usdt") or 0.0), sum(nets), _tol(subset)):
                problems.append(f"{key}/{name}: neto declarado {block.get('net_usdt')} vs {sum(nets):,.4f}")
            expectancy = (sum(nets) / len(nets)) if nets else None
            if expectancy is not None and not _close(float(block.get("expectancy_usdt") or 0.0), expectancy, TOL):
                problems.append(f"{key}/{name}: expectativa declarada {block.get('expectancy_usdt')}")
            win_rate = (100.0 * len(wins) / len(nets)) if nets else None
            if win_rate is not None and not _close(float(block.get("win_rate_pct") or 0.0), win_rate, 0.01):
                problems.append(f"{key}/{name}: win rate declarado {block.get('win_rate_pct')}")
            csv_row = published.get((key, name))
            if csv_row is None or str(csv_row.get("net_usdt")) != str(block.get("net_usdt")):
                problems.append(f"{key}/{name}: el CSV de periodos no coincide con el JSON")
        detail.append(f"{key}: {len(declared)} periodos")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def check_regimes_recomputed(ds: Dataset) -> tuple[bool, str]:
    """Both regime labels must be recomputed from the trades and the benchmark file."""
    problems: list[str] = []
    detail: list[str] = []
    published = {(row["run"], row["label_kind"], row["label"]): row for row in ds.regime_rows}
    for key in ds.runs():
        rows = _trades_for(ds, key, "combined")
        block = ds.run(key)["combined"]
        for kind, column, declared_map in (
            ("candidate_trend_state", "regime", block.get("by_regime") or {}),
            ("benchmark_market_context", "market_context", block.get("by_market_context") or {}),
        ):
            recomputed: dict[str, Any] = {}
            for label in sorted({row.get(column) or "UNDEFINED" for row in rows}):
                subset = [row for row in rows if (row.get(column) or "UNDEFINED") == label]
                nets = [_f(row, "net") for row in subset]
                recomputed[label] = {
                    "trades": len(subset),
                    "net": round(sum(nets), 4),
                    "win_rate": round(100.0 * sum(1 for n in nets if n > 0) / len(subset), 4),
                }
            if set(recomputed) != set(declared_map):
                problems.append(f"{key}/{kind}: etiquetas {sorted(declared_map)} != {sorted(recomputed)}")
            for label, expected in recomputed.items():
                declared_value = declared_map.get(label) or {}
                if int(declared_value.get("trades") or 0) != expected["trades"]:
                    problems.append(f"{key}/{kind}/{label}: operaciones declaradas != recalculadas")
                if not _close(float(declared_value.get("net") or 0.0), expected["net"], _tol(rows)):
                    problems.append(
                        f"{key}/{kind}/{label}: neto declarado {declared_value.get('net')} vs {expected['net']}"
                    )
                csv_row = published.get((key, kind, label))
                if csv_row is None or str(csv_row.get("net_usdt")) != str(declared_value.get("net")):
                    problems.append(f"{key}/{kind}/{label}: el CSV de regimenes no coincide con el JSON")
            detail.append(f"{key}: {len(declared_map)} etiquetas de {kind}")
    return (not problems), "; ".join(problems[:6]) or "; ".join(detail)


def check_buy_and_hold_consistent(ds: Dataset) -> tuple[bool, str]:
    """The reference must be internally consistent and inside its own window."""
    problems: list[str] = []
    rows = 0
    for key, run in ds.runs().items():
        start = float((ds.experiment().get("risk_policy") or {}).get("start_equity") or 0.0)
        for asset, block in run["buy_and_hold"].items():
            rows += 1
            if int(block.get("bars") or 0) < 2:
                problems.append(f"{key}/{asset}: buy & hold over {block.get('bars')} bars")
            if not (int(run["window_start_ms"]) <= int(block.get("first_ts") or 0) <= int(run["window_end_ms"])):
                problems.append(f"{key}/{asset}: the buy & hold window starts outside the run window")
            if not (int(run["window_start_ms"]) <= int(block.get("last_ts") or 0) <= int(run["window_end_ms"])):
                problems.append(f"{key}/{asset}: the buy & hold window ends outside the run window")
            expected = start * (1.0 + float(block.get("return_pct") or 0.0) / 100.0)
            if not _close(float(block.get("equity_final") or 0.0), expected, TOL):
                problems.append(
                    f"{key}/{asset}: equity_final {block.get('equity_final')} != start x (1+ret) {expected:,.4f}"
                )
            if len(block) and "return_pct" not in block:
                problems.append(f"{key}/{asset}: the reference states no return")
    return (not problems), "; ".join(problems[:6]) or f"{rows} referencias de buy & hold coherentes y dentro de su ventana"


def check_decision_is_oos(ds: Dataset) -> tuple[bool, str]:
    """The decision must come from OOS, with DEV and VAL published as the reference."""
    problems: list[str] = []
    window = str(EXPECTED_OOS_RULE["decision_window"])
    exp = ds.experiment()
    if str(exp.get("decision_window")) != window:
        problems.append(f"la ventana de decision es {exp.get('decision_window')!r}, no {window!r}")
    keys = set(ds.runs())
    for name in exp["windows"]:
        if f"{name}:BASE" not in keys:
            problems.append(f"falta el pase BASE de {name}")
    if f"{window}:2X_FEES" not in keys:
        problems.append(f"falta el estres de coste en {window}")
    elif str(ds.run(f"{window}:2X_FEES").get("scenario")) != "2X_FEES":
        problems.append(
            f"la corrida {window}:2X_FEES se etiqueta como "
            f"{ds.run(f'{window}:2X_FEES').get('scenario')!r}"
        )
    if f"{window}:ADVERSE" in keys:
        problems.append("se publica un escenario ADVERSE que la regla no declara")
    published = {check["criterion"]: check for check in (ds.payload["verdict"].get("checks") or [])}
    stress = ds.run(f"{window}:2X_FEES")["combined"]["net_usdt"]
    detail = str((published.get("oos_net_positive_under_2x_fees") or {}).get("detail") or "")
    if f"{float(stress):,.2f}" not in detail:
        problems.append(
            f"el criterio de coste estresado no cita el neto publicado de 2x fees ({float(stress):,.2f})"
        )
    admission = (ds.payload["verdict"].get("wp_admission") or {})
    if admission.get("verdict") not in ("ADMIT", "REJECT", "INSUFFICIENT_EVIDENCE"):
        problems.append(f"la admision del WP no es un codigo declarado: {admission.get('verdict')!r}")
    for name in ("DEV", "VAL", "OOS"):
        if name not in (admission.get("evidence", {}).get("window_net_usdt") or {}):
            problems.append(f"la admision del WP no cita el neto de {name}")
    return (not problems), "; ".join(problems[:6]) or (
        f"decision en {window} (BASE y 2x fees), referencias {', '.join(exp['windows'])}; "
        f"admit del WP: {admission.get('verdict')}"
    )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

SHARED_CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("PARAMS_UNCHANGED", check_params_unchanged),
    ("EQUITY_CONSERVATION", check_equity_conservation),
    ("COST_SPLIT_IDENTITY", check_cost_split_identity),
    ("ARM_METRICS_RECOMPUTED", check_metrics_recomputed),
    ("MARKET_CONTEXT_ATTRIBUTION", check_market_context_attribution),
    ("WINDOW_IS_DECLARED", check_window_is_declared),
)

H6_CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("ORDERS_LIFECYCLE", check_orders_lifecycle),
    ("FILLED_ORDERS_MATCH_TRADES", check_filled_orders_match_trades),
    ("LIMIT_IS_NEVER_BETTER", check_limit_is_never_better),
    ("NO_PLAN_ON_THE_MARKET_ARMS", check_no_plan_on_the_market_arms),
    ("UNREACHABLE_OUTCOME_ABSENT", check_unreachable_outcome_absent),
    ("FILL_RATE_RECOMPUTED", check_fill_rate_recomputed),
    ("VERDICT_RECOMPUTED", check_verdict_recomputed),
    ("CONFIRMATION_RECOMPUTED", check_confirmation_recomputed),
)

OOS_CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("VERDICT_RECOMPUTED", check_oos_verdict_recomputed),
    ("ASSET_BOOKS_RECOMPUTED", check_asset_books_recomputed),
    ("PERIODS_RECOMPUTED", check_periods_recomputed),
    ("REGIMES_RECOMPUTED", check_regimes_recomputed),
    ("BUY_AND_HOLD_CONSISTENT", check_buy_and_hold_consistent),
    ("DECISION_IS_OOS", check_decision_is_oos),
)


def checks_for(spec: dict[str, Any]) -> tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...]:
    return SHARED_CHECKS + (H6_CHECKS if spec.get("orders") else OOS_CHECKS)


def run_checks(root: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
    ds = Dataset(root, spec)
    out: list[dict[str, Any]] = []
    for name, fn in checks_for(spec):
        try:
            ok, detail = fn(ds)
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _store_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mutate_gross(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    rows[0]["gross"] = str(_f(rows[0], "gross") + 25.0)
    _rewrite_csv(path, rows)


def _mutate_drop_trade(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    _rewrite_csv(path, rows[1:])


def _mutate_metrics_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    block = payload["runs"]["DEV:BASE"]
    block = block["arms"] if spec.get("orders") else {"combined": block["combined"]}
    target = block["plan_limit"] if spec.get("orders") else block["combined"]
    target["net_usdt"] = float(target["net_usdt"]) + 50.0
    _store_json(path, payload)


def _mutate_window_moved(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    run = payload["runs"]["DEV:BASE"]
    start, end = spec["windows"]["DEV"]
    run["window_start_ms"] = start + 90 * 86_400_000
    run["window_end_ms"] = end + 400 * 86_400_000
    _store_json(path, payload)


def _mutate_out_of_window_trade(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    start, _end = spec["windows"]["DEV"]
    rows[0]["entry_ts"] = str(start - 86_400_000)
    _rewrite_csv(path, rows)


def _mutate_market_context(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    labels = list((_load_json(root / spec["payload"]).get("market_context") or {}).get("labels") or [])
    alternative = next((label for label in labels if label != rows[0].get("market_context")), "UNDEFINED")
    rows[0]["market_context"] = alternative
    _rewrite_csv(path, rows)


def _mutate_artifact_touched(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["markdown"]
    path.write_text(path.read_text(encoding="utf-8") + "\n<!-- an edit no digest covers -->\n", encoding="utf-8")


def _mutate_verdict_flipped(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    codes = [code for code in spec["codes"] if code != payload["verdict"]["verdict"]]
    payload["verdict"]["verdict"] = codes[0]
    _store_json(path, payload)


def _mutate_rule_relaxed(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    key = "min_fill_rate" if spec.get("orders") else "min_oos_trades"
    payload["verdict"]["decision_rule"][key] = 0.0 if spec.get("orders") else 1
    payload["experiment"]["decision_rule"][key] = 0.0 if spec.get("orders") else 1
    _store_json(path, payload)


def _mutate_params_retuned(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    if spec.get("orders"):
        arm = payload["runs"]["DEV:BASE"]["arms"]["plan_limit"]
        arm["params"]["volume_mult"] = 1.5
        arm["params_delta"] = {"volume_mult": [1.2, 1.5]}
    else:
        payload["experiment"]["frozen_params"]["trailing_atr"] = 2.0
    _store_json(path, payload)


def _mutate_order_outcome_flipped(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["orders"]
    rows = _read_csv(path)
    for row in rows:
        if row.get("outcome") == "filled" and row.get("arm") == "plan_limit":
            row["outcome"] = "expired"
            break
    _rewrite_csv(path, rows)


def _mutate_fill_before_placement(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["orders"]
    rows = _read_csv(path)
    for row in rows:
        if row.get("outcome") == "filled":
            row["placed_bar"] = row["outcome_bar"]
            row["bars_resting"] = "0"
            break
    _rewrite_csv(path, rows)


def _mutate_expiry_changed(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["orders"]
    rows = _read_csv(path)
    rows[0]["expiry_bars"] = str(RETEST_EXPIRY_BARS - 4)
    _rewrite_csv(path, rows)


def _mutate_level_moved_on_a_trade(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = [row for row in _read_csv(path) if row.get("arm") == "plan_limit"]
    rows[0]["entry_mid"] = str(_f(rows[0], "entry_mid") * 1.0001)
    _rewrite_csv(path, rows)


def _mutate_frozen_signal_gets_a_limit(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["signals"]
    rows = _read_csv(path)
    for row in rows:
        if row.get("arm") == "frozen_market":
            row["entry_limit"] = row["entry_reference"]
            break
    _rewrite_csv(path, rows)


def _mutate_unreachable_outcome_printed(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["orders"]
    rows = _read_csv(path)
    rows[0]["outcome"] = RETEST_UNREACHABLE[0]
    _rewrite_csv(path, rows)


def _mutate_fill_rate_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    arm = payload["runs"]["DEV:BASE"]["arms"]["plan_limit"]
    arm["fill_rate"] = float(arm["fill_rate"] or 0.0) + 0.1
    _store_json(path, payload)


def _mutate_confirmation_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    window = sorted(payload["confirmation"])[0]
    payload["confirmation"][window]["net_delta_usdt"] = (
        float(payload["confirmation"][window]["net_delta_usdt"]) + 10.0
    )
    _store_json(path, payload)


def _mutate_primary_window_moved(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    payload["experiment"]["primary_window"] = "VAL"
    _store_json(path, payload)


def _mutate_asset_net_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    payload["runs"]["OOS:BASE"]["assets"]["BTC"]["net_usdt"] = (
        float(payload["runs"]["OOS:BASE"]["assets"]["BTC"]["net_usdt"]) + 123.0
    )
    _store_json(path, payload)


def _mutate_period_net_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    period = payload["runs"]["OOS:BASE"]["periods"][0]
    period["net_usdt"] = float(period["net_usdt"]) + 77.0
    _store_json(path, payload)


def _mutate_regime_net_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    block = payload["runs"]["OOS:BASE"]["combined"]["by_market_context"]
    label = sorted(block)[0]
    block[label]["net"] = float(block[label]["net"]) + 42.0
    _store_json(path, payload)


def _mutate_buy_and_hold_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    hold = payload["runs"]["OOS:BASE"]["buy_and_hold"]["BTC"]
    hold["equity_final"] = float(hold["equity_final"]) + 500.0
    _store_json(path, payload)


def _mutate_criterion_result_flipped(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    for check in payload["verdict"]["checks"]:
        if check["result"] == "PASS":
            check["result"] = "FAIL"
            break
    _store_json(path, payload)


def _mutate_decision_window_moved(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    payload["experiment"]["decision_window"] = "VAL"
    _store_json(path, payload)


def _mutate_stress_run_dropped(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    payload["runs"].pop("OOS:2X_FEES", None)
    _store_json(path, payload)


SHARED_MUTATIONS: tuple[tuple[str, str, Callable[[Path], None]], ...] = (
    ("gross_plus_25", "COST_SPLIT_IDENTITY", _mutate_gross),
    ("drop_a_trade", "EQUITY_CONSERVATION", _mutate_drop_trade),
    ("metrics_tampered", "ARM_METRICS_RECOMPUTED", _mutate_metrics_tampered),
    ("window_moved", "WINDOW_IS_DECLARED", _mutate_window_moved),
    ("out_of_window_trade", "WINDOW_IS_DECLARED", _mutate_out_of_window_trade),
    ("market_context_flipped", "MARKET_CONTEXT_ATTRIBUTION", _mutate_market_context),
    ("artifact_touched", "ARTIFACTS_PRESENT", _mutate_artifact_touched),
    ("verdict_flipped", "VERDICT_RECOMPUTED", _mutate_verdict_flipped),
    ("rule_relaxed", "VERDICT_RECOMPUTED", _mutate_rule_relaxed),
    ("params_retuned", "PARAMS_UNCHANGED", _mutate_params_retuned),
)

H6_MUTATIONS: tuple[tuple[str, str, Callable[[Path], None]], ...] = (
    ("order_outcome_flipped", "FILLED_ORDERS_MATCH_TRADES", _mutate_order_outcome_flipped),
    ("fill_before_placement", "ORDERS_LIFECYCLE", _mutate_fill_before_placement),
    ("expiry_changed", "ORDERS_LIFECYCLE", _mutate_expiry_changed),
    ("level_moved_on_a_trade", "LIMIT_IS_NEVER_BETTER", _mutate_level_moved_on_a_trade),
    ("frozen_signal_gets_a_limit", "NO_PLAN_ON_THE_MARKET_ARMS", _mutate_frozen_signal_gets_a_limit),
    ("unreachable_outcome_printed", "UNREACHABLE_OUTCOME_ABSENT", _mutate_unreachable_outcome_printed),
    ("fill_rate_tampered", "FILL_RATE_RECOMPUTED", _mutate_fill_rate_tampered),
    ("confirmation_tampered", "CONFIRMATION_RECOMPUTED", _mutate_confirmation_tampered),
    ("primary_window_moved", "CONFIRMATION_RECOMPUTED", _mutate_primary_window_moved),
)

OOS_MUTATIONS: tuple[tuple[str, str, Callable[[Path], None]], ...] = (
    ("asset_net_tampered", "ASSET_BOOKS_RECOMPUTED", _mutate_asset_net_tampered),
    ("period_net_tampered", "PERIODS_RECOMPUTED", _mutate_period_net_tampered),
    ("regime_net_tampered", "REGIMES_RECOMPUTED", _mutate_regime_net_tampered),
    ("buy_and_hold_tampered", "BUY_AND_HOLD_CONSISTENT", _mutate_buy_and_hold_tampered),
    ("criterion_result_flipped", "VERDICT_RECOMPUTED", _mutate_criterion_result_flipped),
    ("decision_window_moved", "DECISION_IS_OOS", _mutate_decision_window_moved),
    ("stress_run_dropped", "DECISION_IS_OOS", _mutate_stress_run_dropped),
)


def mutations_for(spec: dict[str, Any]) -> tuple[tuple[str, str, Callable[[Path], None]], ...]:
    extra = H6_MUTATIONS if spec.get("orders") else OOS_MUTATIONS
    return tuple(
        (name, expected, partial(fn, spec=spec)) for name, expected, fn in SHARED_MUTATIONS + extra
    )


def self_test(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    baseline = {entry["check"]: entry["ok"] for entry in run_checks(root, spec)}
    results: list[dict[str, Any]] = []
    for name, expected, mutate in mutations_for(spec):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "artefacts"
            shutil.copytree(root, copy_dir)
            mutate(copy_dir)
            try:
                after = {entry["check"]: entry for entry in run_checks(copy_dir, spec)}
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


def verify_one(
    key: str, *, root: Path | None = None, self_test_run: bool = False
) -> tuple[dict[str, Any], int]:
    spec = SPECS[key]
    directory = root or Path(spec["root"])
    try:
        checks = run_checks(directory, spec)
    except Fatal as exc:
        print(f"FATAL [{key}]: {exc}")
        return {"experiment": key, "fatal": str(exc)}, 2

    passed = sum(1 for entry in checks if entry["ok"])
    print(f"\n== {spec['label']} ==")
    for entry in checks:
        print(f"[{'PASS' if entry['ok'] else 'FAIL'}] {entry['check']:<32} {entry['detail']}")
    print(f"\nchecks: {passed}/{len(checks)} passed")

    payload: dict[str, Any] = {
        "experiment": key,
        "dir": str(directory),
        "checks": checks,
        "passed": passed,
        "total": len(checks),
    }
    failed = len(checks) - passed
    if self_test_run:
        report = self_test(directory, spec)
        payload["self_test"] = report
        print("\n-- self-test (each mutation must break its check) --")
        for item in report["mutations"]:
            status = "PASS" if item["expected_check_failed"] else "FAIL"
            print(
                f"[{status}] {item['mutation']:<30} -> {item['expected_check']} "
                f"(failed: {', '.join(item['detected']) or 'nothing'})"
            )
        print(
            f"mutations detected: "
            f"{sum(1 for m in report['mutations'] if m['expected_check_failed'])}"
            f"/{len(report['mutations'])}"
        )
        failed += 0 if report["all_detected"] else 1
        failed += 0 if report["baseline_all_green"] else 1
    payload["failed"] = failed
    return payload, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=("h6", "oos", "all"), default="all")
    parser.add_argument("--dir", default="", help="override the artefact directory")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json-out", default="", help="write the report to one file")
    args = parser.parse_args(argv)

    keys = ("h6", "oos") if args.experiment == "all" else (args.experiment,)
    reports: list[dict[str, Any]] = []
    failures = 0
    for key in keys:
        spec = SPECS[key]
        report, failed = verify_one(
            key, root=Path(args.dir) if args.dir else None, self_test_run=args.self_test
        )
        reports.append(report)
        failures += failed
        if not report.get("fatal"):
            out = (
                Path(args.dir) / spec["verification"]
                if args.dir
                else Path(spec["root"]) / spec["verification"]
            )
            out.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(reports if len(reports) > 1 else reports[0], indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
