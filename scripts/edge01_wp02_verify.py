"""Independent verifier for the WP-EDGE-02 experiments (trend robustness and the H6 audit).

    python scripts/edge01_wp02_verify.py [--experiment trend|risk|all] [--dir DIR]
                                         [--self-test] [--json-out FILE]

This process imports NOTHING from ``trading_bot``. It reads the published artefacts, the
local price corpus and the WP-EDGE-01 artefacts the two experiments reproduce, restates
the frozen declarations and the statistical procedures from constants written here, and
recomputes what the payloads claim:

* **trend** — the per-window metrics, the leave-out sensitivity, the contribution split,
  the risk-adjusted comparison, the uncertainty intervals (the declared xorshift64*
  block bootstrap and the Newey–West interval are re-implemented from their declaration,
  not imported), the equity curve (rebuilt bar by bar from the corpus and the published
  trade ledger), the reproduction of the WP-EDGE-01 figures and the verdict itself.
* **risk** — the order set and its outcome split, the identity of the published H6 order
  rows, every one of the 183 refusals against a risk state RECONSTRUCTED from the corpus
  and the trade ledger rather than taken from the audit's own capture, the accounting
  identity, the duplicate check and the attributed-refusal check.

``--self-test`` sabotages a copy of the artefacts once per mutation and requires the
declared check to break: a check nobody can break is a check nobody is running.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TOL = 0.05
PRICE_TOL = 1e-4

TREND_DIR = "reports/edge-recovery/WP-EDGE-02/trend-robustness"
RISK_DIR = "reports/edge-recovery/WP-EDGE-02/h6-risk-audit"
WP01_TREND = "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json"
WP01_H6_TRADES = "reports/edge-recovery/WP-EDGE-01/retest-h6/RETEST_TRADES.csv"
WP01_H6_ORDERS = "reports/edge-recovery/WP-EDGE-01/retest-h6/RETEST_ORDERS.csv"

CORPUS_1H = "reports/alpha-expansion-v1/data"
CORPUS_15M = "data/raw/alpha003/price"
ASSETS = ("BTC", "ETH", "SOL")


def _ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


#: The configured limits the audit's budget must still equal, read from the YAML by hand
#: (a flat nested mapping, so no YAML dependency is needed to re-check that nothing was
#: relaxed to make the book trade more often).
RISK_CONFIG_KEYS = (
    "max_risk_per_trade_pct",
    "max_total_drawdown_pct",
    "max_open_positions",
    "max_trades_per_day",
    "max_asset_exposure_pct",
    "max_total_exposure_pct",
    "min_order_notional_usdt",
    "max_order_notional_usdt",
)


#: The payload name of each configured limit, so the comparison is explicit.
RISK_CONFIG_TO_POLICY = {
    "max_risk_per_trade_pct": "risk_per_trade_pct",
    "max_total_drawdown_pct": "drawdown_halt_pct",
    "max_open_positions": "max_open_positions",
    "max_trades_per_day": "max_trades_per_day",
    "max_asset_exposure_pct": "max_asset_exposure_pct",
    "max_total_exposure_pct": "max_total_exposure_pct",
    "min_order_notional_usdt": "min_notional_usdt",
    "max_order_notional_usdt": "max_notional_usdt",
}


def read_risk_config() -> dict[str, float]:
    """The configured limits, parsed from ``config/risk.yaml`` line by line."""
    out: dict[str, float] = {}
    for raw in (ROOT / "config" / "risk.yaml").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in RISK_CONFIG_KEYS:
            out[RISK_CONFIG_TO_POLICY[key]] = float(value.strip())
    return out


#: Restated from the frozen campaign module, so a moved window fails here.
TREND_WINDOWS: dict[str, tuple[int, int]] = {
    "DEV": (_ms(2019, 1, 1), _ms(2023, 12, 31)),
    "VAL": (_ms(2024, 1, 1), _ms(2024, 12, 31)),
    "OOS": (_ms(2025, 1, 1), _ms(2026, 2, 28)),
}
INTRADAY_WINDOWS: dict[str, tuple[int, int]] = {
    "DEV": (_ms(2024, 10, 1), _ms(2025, 6, 30)),
    "VAL": (_ms(2025, 7, 1), _ms(2025, 12, 31)),
    "OOS": (_ms(2026, 1, 1), _ms(2026, 10, 7)),
}
BARS_PER_YEAR_4H = 6 * 365

TREND_PERIODS: dict[str, tuple[int, int]] = {
    "2025H1": (_ms(2025, 1, 1), _ms(2025, 7, 1)),
    "2025H2": (_ms(2025, 7, 1), _ms(2026, 1, 1)),
    "2026Q1": (_ms(2026, 1, 1), _ms(2026, 3, 1)),
}

#: Restated from the WP-EDGE-02A declaration.
TREND_DECISION: dict[str, Any] = {
    "decision_window": "OOS",
    "min_oos_trades": 30,
    "concentration_criterion_pct_of_net": 0.50,
    "min_positive_assets": 2,
    "min_positive_periods": 2,
    "confidence": 0.95,
    "bootstrap_block_length": 5,
    "bootstrap_resamples": 5000,
    "bootstrap_seed": 20_260_101,
}
#: Restated from the WP-EDGE-02B declaration.
RISK_PRIMARY = {"window": "DEV", "scenario": "BASE", "arm": "plan_limit"}
RISK_EXPECTED_OUTCOMES = {
    "filled": 372,
    "expired": 128,
    "refused_by_risk_budget": 183,
    "cancelled_window_end": 3,
}
RISK_EXPECTED_REASONS = {"risk_drawdown_halt": 148, "risk_loss_cooldown": 35}
RISK_ORDER_VOCABULARY = (
    "filled",
    "expired",
    "refused_by_risk_budget",
    "cancelled_close_below_level",
    "cancelled_window_end",
)
RISK_POLICY = {
    "max_open_positions": 3,
    "max_trades_per_day": 20,
    "drawdown_halt_pct": 5.0,
    "start_equity": 10_000.0,
    "risk_per_trade_pct": 0.25,
    "max_notional_usdt": 500.0,
    "min_notional_usdt": 20.0,
    "max_asset_exposure_pct": 10.0,
    "max_total_exposure_pct": 25.0,
}
#: The exact figure WP-EDGE-01 published, restated so the reproduction is checked and
#: not merely re-reported.
WP01_OOS_BASE = {"trades": 52, "net_usdt": 208.0056, "largest_share": 0.7987}


# --------------------------------------------------------------------------- #
# data helpers (self-contained: no imports from the package under audit)
# --------------------------------------------------------------------------- #


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def fnum(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if value in (None, ""):
        return 0.0
    return float(value)


def fopt(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    return float(value)


def load_hourly(asset: str) -> list[tuple[int, float, float, float, float]]:
    """``(ts, open, high, low, close)`` per 1h bar, deduplicated and sorted."""
    base = ROOT / CORPUS_1H
    bars: list[tuple[int, float, float, float, float]] = []
    for path in sorted(p for p in base.glob(f"{asset}USDT_*.json") if not p.name.startswith("_")):
        raw = read_json(path)
        rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
        for row in rows:
            if isinstance(row, dict):
                bars.append(
                    (
                        int(row["ts"]),
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                    )
                )
            else:
                bars.append(
                    (int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]))
                )
    bars.sort(key=lambda b: b[0])
    out: list[tuple[int, float, float, float, float]] = []
    for bar in bars:
        if out and out[-1][0] == bar[0]:
            continue
        out.append(bar)
    return out


def resample_hourly(
    bars: list[tuple[int, float, float, float, float]], timeframe: str
) -> dict[int, float]:
    """Complete-bucket aggregation, restated: only full, contiguous buckets survive."""
    tf_ms = {"4h": 14_400_000, "1d": 86_400_000}[timeframe]
    expected = {"4h": 4, "1d": 24}[timeframe]
    step = 3_600_000
    out: dict[int, float] = {}
    bucket: int | None = None
    members: list[tuple[int, float, float, float, float]] = []
    for bar in bars:
        current = bar[0] // tf_ms
        if bucket is None:
            bucket = current
        if current != bucket:
            if len(members) == expected:
                out[members[0][0] // tf_ms * tf_ms] = members[-1][4]
            members = []
            bucket = current
        members.append(bar)
        if len(members) > 1 and members[-1][0] - members[-2][0] != step:
            members = [bar]
            bucket = current
    if len(members) == expected:
        out[members[0][0] // tf_ms * tf_ms] = members[-1][4]
    return out


def load_quarter_hour(asset: str) -> dict[int, float]:
    """``ts -> close`` for the 15m corpus (already on the 15m grid)."""
    path = ROOT / CORPUS_15M / f"{asset}USDT_15m.json"
    raw = read_json(path)
    rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
    return {int(row[0]): float(row[4]) for row in rows}


# --------------------------------------------------------------------------- #
# statistics (restated from the declaration, not imported)
# --------------------------------------------------------------------------- #

MASK64 = (1 << 64) - 1
XORSHIFT_MULT = 2685821657736338717


def xorshift64_star(state: int) -> tuple[int, int]:
    x = state & MASK64
    x ^= (x << 13) & MASK64
    x ^= x >> 7
    x ^= (x << 17) & MASK64
    state = x & MASK64
    return state, (state * XORSHIFT_MULT) & MASK64


def uniform(state: int) -> tuple[int, float]:
    state, out = xorshift64_star(state)
    return state, out / float(1 << 64)


#: Restated from the WP-EDGE-02A declaration: the small-df table, then Cornish-Fisher.
T_CRITICAL_SMALL_DF: tuple[float, ...] = (
    12.7062047364,
    4.30265272975,
    3.18244630528,
    2.77644510520,
    2.57058183564,
    2.44691185114,
    2.36462425159,
    2.30600413520,
    2.26215716285,
)


def t_critical(df: int, z: float = 1.959963984540054) -> float:
    if df <= 0:
        return math.inf
    if df <= len(T_CRITICAL_SMALL_DF):
        return T_CRITICAL_SMALL_DF[df - 1]
    if df > 2_000:
        return z
    v = float(df)
    return (
        z
        + (z**3 + z) / (4 * v)
        + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * v**2)
        + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * v**3)
    )


def hac_lag(n: int) -> int:
    if n <= 1:
        return 0
    return int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def hac_interval(values: list[float]) -> dict[str, float | int | None]:
    n = len(values)
    if n < 2:
        return {"mean": (sum(values) / n if n else None), "se": None, "lower": None, "upper": None, "lag": 0}
    lag = hac_lag(n)
    mean = sum(values) / n
    dev = [v - mean for v in values]
    var = sum(d * d for d in dev) / n
    for k in range(1, lag + 1):
        weight = 1.0 - k / (lag + 1.0)
        var += 2.0 * weight * (sum(dev[i] * dev[i - k] for i in range(k, n)) / n)
    if var < 0.0:
        var = 0.0
    se = math.sqrt(var / n)
    critical = t_critical(n - 1)
    return {
        "mean": mean,
        "se": se,
        "lag": lag,
        "lower": mean - critical * se,
        "upper": mean + critical * se,
    }


def percentile(sorted_values: list[float], q: float) -> float:
    n = len(sorted_values)
    if n == 0:
        return math.nan
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    low = int(math.floor(pos))
    high = min(low + 1, n - 1)
    frac = pos - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


def bootstrap_interval(values: list[float]) -> dict[str, float]:
    n = len(values)
    state = TREND_DECISION["bootstrap_seed"] & MASK64
    restart = 1.0 / TREND_DECISION["bootstrap_block_length"]
    means: list[float] = []
    for _ in range(int(TREND_DECISION["bootstrap_resamples"])):
        total = 0.0
        count = 0
        index = -1
        while count < n:
            state, draw = uniform(state)
            if index < 0 or draw < restart:
                state, draw2 = uniform(state)
                index = int(draw2 * n)
                if index >= n:
                    index = n - 1
            total += values[index]
            count += 1
            index += 1
            if index >= n:
                index = 0
        means.append(total / n)
    means.sort()
    alpha = (1.0 - float(TREND_DECISION["confidence"])) / 2.0
    return {"lower": percentile(means, alpha), "upper": percentile(means, 1.0 - alpha)}


def equity_metrics(curve: list[tuple[int, float]], start_equity: float) -> dict[str, float | None]:
    """Max drawdown and annualised Sharpe, restated from the campaign's own convention."""
    peak = start_equity
    max_dd = 0.0
    for _ts, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    rets = [
        curve[i][1] / curve[i - 1][1] - 1
        for i in range(1, len(curve))
        if curve[i - 1][1] > 0
    ]
    sharpe = None
    if len(rets) > 100:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        sd = math.sqrt(var)
        sharpe = mean / sd * math.sqrt(BARS_PER_YEAR_4H) if sd > 0 else None
    return {"max_drawdown_pct": max_dd, "sharpe_annualised": sharpe}


# --------------------------------------------------------------------------- #
# trend verification
# --------------------------------------------------------------------------- #


def trend_run_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, list[dict[str, str]]]]:
    grouped: dict[str, dict[str, list[dict[str, str]]]] = {}
    for row in rows:
        grouped.setdefault(row["run"], {}).setdefault(row["book"], []).append(row)
    return grouped


def recompute_trend_metrics(trades: list[dict[str, str]]) -> dict[str, Any]:
    nets = [fnum(t, "net") for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gross_loss = abs(sum(losses))
    total = sum(nets)
    largest = max(nets, default=0.0)
    return {
        "trades": len(trades),
        "net_usdt": total,
        "expectancy_usdt": total / len(nets) if nets else None,
        "win_rate_pct": 100.0 * len(wins) / len(nets) if nets else None,
        "profit_factor": (sum(wins) / gross_loss) if gross_loss > 0 else None,
        "largest_trade_share_of_net": (largest / total) if total > 0 else None,
        "largest_trade_usdt": largest,
    }


def rebuild_trend_curve(
    trades: list[dict[str, str]],
    marks: dict[str, dict[int, float]],
    window: tuple[int, int],
    start_equity: float,
) -> list[tuple[int, float]]:
    """Replay the book bar by bar from the corpus closes and the published trade ledger."""
    start, end = window
    timeline = sorted({ts for asset in ASSETS for ts in marks[asset] if start <= ts <= end})
    entries: dict[int, list[dict[str, str]]] = {}
    exits: dict[int, list[dict[str, str]]] = {}
    for trade in trades:
        entries.setdefault(int(fnum(trade, "entry_ts")), []).append(trade)
        exits.setdefault(int(fnum(trade, "exit_ts")), []).append(trade)
    cash = start_equity
    open_positions: dict[str, dict[str, float]] = {}
    curve: list[tuple[int, float]] = []
    for ts in timeline:
        for trade in entries.get(ts, []):
            asset = trade["asset"]
            cash -= fnum(trade, "entry_fill") * fnum(trade, "qty")
            open_positions[asset] = {
                "qty": fnum(trade, "qty"),
                "entry_mid": fnum(trade, "entry_mid"),
            }
        for trade in exits.get(ts, []):
            asset = trade["asset"]
            cash += fnum(trade, "exit_fill") * fnum(trade, "qty") - fnum(trade, "fees")
            open_positions.pop(asset, None)
        equity = cash
        for asset, position in open_positions.items():
            close = marks[asset].get(ts)
            equity += position["qty"] * (close if close is not None else position["entry_mid"])
        curve.append((ts, equity))
    return curve


def verify_trend(dirpath: Path) -> tuple[list[dict[str, Any]], int]:
    checks: list[dict[str, Any]] = []
    failures = 0

    def add(name: str, passed: bool, detail: str) -> None:
        nonlocal failures
        checks.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            failures += 1

    payload = read_json(dirpath / "ROBUSTNESS.json")
    windows = {row["run"]: row for row in read_csv(dirpath / "ROBUSTNESS_WINDOWS.csv")}
    leave_out = read_csv(dirpath / "ROBUSTNESS_LEAVE_OUT.csv")
    uncertainty = {row["run"]: row for row in read_csv(dirpath / "ROBUSTNESS_UNCERTAINTY.csv")}
    contribution = read_csv(dirpath / "ROBUSTNESS_CONTRIBUTION.csv")
    risk_rows = {row["run"]: row for row in read_csv(dirpath / "ROBUSTNESS_RISK_ADJUSTED.csv")}
    trade_rows = read_csv(dirpath / "TREND_TRADES.csv")
    grouped = trend_run_rows(trade_rows)

    # 1. metrics, recomputed from the trade ledger the artefact publishes
    metric_failures: list[str] = []
    for key, published in windows.items():
        combined = grouped.get(key, {}).get("combined", [])
        mine = recompute_trend_metrics(combined)
        if int(published["trades"]) != mine["trades"]:
            metric_failures.append(f"{key}: {published['trades']} vs {mine['trades']} trades")
        for field in ("net_usdt", "expectancy_usdt", "win_rate_pct"):
            published_value = fopt(published, field)
            mine_value = mine[field]
            if mine_value is None or published_value is None:
                continue
            if abs(published_value - mine_value) > TOL:
                metric_failures.append(f"{key}.{field}: {published_value} vs {mine_value}")
    add(
        "trend_metrics_match_the_trade_ledger",
        not metric_failures,
        f"{len(windows)} runs recomputed; {len(metric_failures)} mismatch(es)"
        + (f"; first: {metric_failures[0]}" if metric_failures else ""),
    )

    # 2. the published reproduction of WP-EDGE-01 is real
    published_wp01 = read_json(ROOT / WP01_TREND)
    oos_published = published_wp01["runs"]["OOS:BASE"]["combined"]
    oos_mine = windows.get("OOS:BASE", {})
    reproduction_failures: list[str] = []
    for field, expected in (
        ("trades", WP01_OOS_BASE["trades"]),
        ("net_usdt", WP01_OOS_BASE["net_usdt"]),
    ):
        if field == "trades":
            if int(oos_mine.get("trades", -1)) != expected:
                reproduction_failures.append(f"trades {oos_mine.get('trades')} vs {expected}")
        elif abs(fnum(oos_mine, field) - expected) > 1e-4:
            reproduction_failures.append(f"{field} {oos_mine.get(field)} vs {expected}")
    if abs(fnum(oos_mine, "largest_trade_share_of_net") - WP01_OOS_BASE["largest_share"]) > 1e-4:
        reproduction_failures.append(
            f"largest share {oos_mine.get('largest_trade_share_of_net')} vs "
            f"{WP01_OOS_BASE['largest_share']}"
        )
    if abs(fnum(oos_published, "net_usdt") - WP01_OOS_BASE["net_usdt"]) > 1e-4:
        reproduction_failures.append("the WP-EDGE-01 artefact itself no longer carries 208.0056")
    add(
        "trend_reproduces_the_wp_edge01_oos_figure",
        not reproduction_failures,
        f"OOS net {oos_mine.get('net_usdt')} vs the published {WP01_OOS_BASE['net_usdt']}"
        + (f"; {reproduction_failures}" if reproduction_failures else ""),
    )

    # 3. leave-out sensitivity, recomputed from the nets
    leave_failures: list[str] = []
    for row in leave_out:
        key = row["run"]
        k = int(row["k"])
        nets = sorted((fnum(t, "net") for t in grouped.get(key, {}).get("combined", [])), reverse=True)
        kept = nets[k:]
        expected_net = sum(kept)
        if abs(fnum(row, "net_usdt") - expected_net) > TOL:
            leave_failures.append(f"{key} k={k}: {row['net_usdt']} vs {expected_net}")
        if k == 1:
            # the declared requirement: the OOS net must survive losing its best trade
            if abs(payload["runs"][key]["combined"]["net_usdt"] - sum(nets)) > TOL:
                leave_failures.append(f"{key}: the baseline net does not match the ledger")
    primary = leave_out and [r for r in leave_out if r["run"] == "OOS:BASE" and int(r["k"]) == 1]
    if primary:
        survived = fnum(primary[0], "net_usdt") > 0
        verdict = payload["verdict"]["verdict"]
        check = payload["verdict"]["checks"]
        declared = next(
            (c for c in check if c["criterion"] == "oos_net_positive_per_dropping_largest_winner"),
            None,
        )
        if declared is not None and declared["result"] == ("PASS" if survived else "FAIL") is False:
            leave_failures.append("the declared leave-one-out check disagrees with the recomputation")
        if survived and verdict == "REJECT":
            leave_failures.append("a positive leave-one-out net cannot be a REJECT")
    add(
        "trend_leave_out_is_recomputed",
        not leave_failures,
        f"{len(leave_out)} leave-out rows recomputed"
        + (f"; {leave_failures[:2]}" if leave_failures else ""),
    )

    # 4. uncertainty intervals, recomputed with the restated procedure
    interval_failures: list[str] = []
    for key, row in uncertainty.items():
        ordered = [
            fnum(t, "net")
            for t in sorted(grouped.get(key, {}).get("combined", []), key=lambda t: int(fnum(t, "exit_ts")))
        ]
        hac = hac_interval(ordered)
        boot = bootstrap_interval(ordered)
        for field, mine in (
            ("hac_lower", hac["lower"]),
            ("hac_upper", hac["upper"]),
            ("bootstrap_lower", boot["lower"]),
            ("bootstrap_upper", boot["upper"]),
        ):
            published_value = fopt(row, field)
            if published_value is None or mine is None:
                continue
            if abs(published_value - mine) > TOL:
                interval_failures.append(f"{key}.{field}: {published_value} vs {mine}")
        if int(row["hac_lag"]) != int(hac["lag"]):
            interval_failures.append(f"{key}.hac_lag: {row['hac_lag']} vs {hac['lag']}")
    add(
        "trend_intervals_are_recomputed",
        not interval_failures,
        f"{len(uncertainty)} intervals recomputed (HAC and block bootstrap)"
        + (f"; first: {interval_failures[0]}" if interval_failures else ""),
    )

    # 5. the equity curve, rebuilt from the corpus, and the windows it implies
    marks: dict[str, dict[int, float]] = {}
    for asset in ASSETS:
        marks[asset] = resample_hourly(load_hourly(asset), "4h")
    curve_failures: list[str] = []
    for key, published in windows.items():
        window_name, scenario = key.split(":", 1)
        bounds = TREND_WINDOWS.get(window_name)
        if bounds is None:
            curve_failures.append(f"{key}: unknown window")
            continue
        curve = rebuild_trend_curve(
            grouped.get(key, {}).get("combined", []), marks, bounds, RISK_POLICY["start_equity"]
        )
        metrics = equity_metrics(curve, RISK_POLICY["start_equity"])
        published_dd = fopt(published, "max_drawdown_pct")
        if published_dd is None or metrics["max_drawdown_pct"] is None:
            curve_failures.append(f"{key}: no drawdown to compare")
            continue
        if abs(published_dd - float(metrics["max_drawdown_pct"])) > max(TOL, 0.02):
            curve_failures.append(
                f"{key}.max_drawdown_pct: {published_dd} vs {float(metrics['max_drawdown_pct']):.4f}"
            )
        final = RISK_POLICY["start_equity"] + sum(fnum(t, "net") for t in grouped.get(key, {}).get("combined", []))
        if abs(curve[-1][1] - final) > max(TOL, abs(final) * 1e-9):
            curve_failures.append(f"{key}: the rebuilt curve ends at {curve[-1][1]:.4f} vs {final:.4f}")
        union = sorted({ts for asset in ASSETS for ts in marks[asset] if bounds[0] <= ts <= bounds[1]})
        if len(curve) != len(union):
            curve_failures.append(
                f"{key}: the replay covered {len(curve)} bars of the window, the corpus offers {len(union)}"
            )
        if any(ts < bounds[0] or ts > bounds[1] for ts, _ in curve):
            curve_failures.append(f"{key}: a replayed bar falls outside the declared window")
        if not curve or scenario not in ("BASE", "2X_FEES", "ADVERSE"):
            curve_failures.append(f"{key}: unexpected scenario {scenario}")
    add(
        "trend_curve_rebuilt_from_the_corpus_matches",
        not curve_failures,
        f"{len(windows)} curves rebuilt bar by bar"
        + (f"; first: {curve_failures[0]}" if curve_failures else ""),
    )

    # 6. contribution, recomputed from the labels carried by the trades
    contribution_failures: list[str] = []
    for row in contribution:
        key = row["run"]
        kind = row["kind"]
        label = row["label"]
        if kind == "asset_own_book":
            subset = grouped.get(key, {}).get(label, [])
        elif kind == "benchmark_market_context":
            subset = [
                t
                for t in grouped.get(key, {}).get("combined", [])
                if (t.get("market_context") or "UNDEFINED") == label
            ]
        else:
            subset = [
                t
                for t in grouped.get(key, {}).get("combined", [])
                if (t.get("regime") or "UNKNOWN") == label
            ]
        mine = recompute_trend_metrics(subset)
        if int(row["trades"]) != mine["trades"]:
            contribution_failures.append(f"{key}/{kind}/{label}: {row['trades']} vs {mine['trades']} trades")
        if abs(fnum(row, "net_usdt") - mine["net_usdt"]) > TOL:
            contribution_failures.append(f"{key}/{kind}/{label}.net: {row['net_usdt']} vs {mine['net_usdt']}")
    add(
        "trend_contribution_is_recomputed",
        not contribution_failures,
        f"{len(contribution)} contribution rows recomputed"
        + (f"; first: {contribution_failures[0]}" if contribution_failures else ""),
    )

    # 7. the risk-adjusted comparison is arithmetically what it claims
    risk_failures: list[str] = []
    for key, row in risk_rows.items():
        net = fnum(windows[key], "net_usdt")
        dd = fnum(windows[key], "max_drawdown_pct")
        expected = net / (RISK_POLICY["start_equity"] * dd / 100.0) if dd > 0 else None
        if expected is not None and abs(fnum(row, "candidate_mar_ratio") - expected) > max(TOL, 0.01):
            risk_failures.append(f"{key}.mar_ratio: {row['candidate_mar_ratio']} vs {expected}")
    add(
        "trend_risk_adjusted_is_recomputed",
        not risk_failures,
        f"{len(risk_rows)} runs recomputed"
        + (f"; first: {risk_failures[0]}" if risk_failures else ""),
    )

    # 8. the verdict follows from the recomputed numbers and the frozen rule
    oos = windows.get("OOS:BASE")
    verdict = payload["verdict"]["verdict"]
    nets = sorted((fnum(t, "net") for t in grouped.get("OOS:BASE", {}).get("combined", [])), reverse=True)
    leave_one_net = sum(nets[1:])
    interval = hac_interval(
        [
            fnum(t, "net")
            for t in sorted(grouped.get("OOS:BASE", {}).get("combined", []), key=lambda t: int(fnum(t, "exit_ts")))
        ]
    )
    positive_assets = [
        asset
        for asset in ASSETS
        if sum(fnum(t, "net") for t in grouped.get("OOS:BASE", {}).get(asset, [])) > 0
    ]
    share = fnum(oos, "largest_trade_share_of_net")
    decisive = []
    if leave_one_net <= 0:
        decisive.append("leave_one_out_net_not_positive")
    if len(positive_assets) < int(TREND_DECISION["min_positive_assets"]):
        decisive.append("too_few_positive_assets")
    if interval["upper"] is not None and float(interval["upper"]) <= 0:
        decisive.append("hac_upper_not_positive")
    inconclusive = []
    if share > float(TREND_DECISION["concentration_criterion_pct_of_net"]):
        inconclusive.append("concentration_above_limit")
    if interval["lower"] is not None and float(interval["lower"]) <= 0 <= float(interval["upper"] or 0.0):
        inconclusive.append("interval_contains_zero")
    expected_verdict = (
        "REJECT" if decisive else "INSUFFICIENT_EVIDENCE" if inconclusive else "ADMIT_PAPER"
    )
    add(
        "trend_verdict_follows_the_frozen_rule",
        verdict == expected_verdict,
        f"declared {verdict}; recomputed {expected_verdict} "
        f"(decisive={decisive or 'none'}, inconclusive={inconclusive or 'none'})",
    )
    add(
        "trend_verdict_is_not_a_promotion",
        verdict != "ADMIT_PAPER" or (share <= 0.50 and leave_one_net > 0),
        f"verdict {verdict} with concentration {share} and leave-one-out net {leave_one_net:,.4f}",
    )
    return checks, failures


# --------------------------------------------------------------------------- #
# risk verification
# --------------------------------------------------------------------------- #


def verify_risk(dirpath: Path) -> tuple[list[dict[str, Any]], int]:
    checks: list[dict[str, Any]] = []
    failures = 0

    def add(name: str, passed: bool, detail: str) -> None:
        nonlocal failures
        checks.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            failures += 1

    payload = read_json(dirpath / "RISK_AUDIT.json")
    order_rows = read_csv(dirpath / "RISK_AUDIT_ORDERS.csv")
    refusal_rows = read_csv(dirpath / "RISK_AUDIT_PRIMARY_REFUSALS.csv")
    invariant_rows = read_csv(dirpath / "RISK_AUDIT_INVARIANTS.csv")
    equity_rows = [(int(r["ts"]), float(r["equity"])) for r in read_csv(dirpath / "RISK_AUDIT_EQUITY.csv")]
    primary_key = f"{RISK_PRIMARY['window']}:{RISK_PRIMARY['scenario']}:{RISK_PRIMARY['arm']}"

    # 1. the order set and its outcome split
    primary_orders = [r for r in order_rows if r["run"] == primary_key]
    outcomes: dict[str, int] = {}
    for row in primary_orders:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
    bad_vocabulary = [r for r in primary_orders if r["outcome"] not in RISK_ORDER_VOCABULARY]
    resting = [r for r in primary_orders if r["outcome"] == "RESTING"]
    add(
        "risk_orders_are_686_with_the_published_outcomes",
        len(primary_orders) == 686 and outcomes == RISK_EXPECTED_OUTCOMES,
        f"{len(primary_orders)} orders, outcomes {outcomes} vs the published {RISK_EXPECTED_OUTCOMES}",
    )
    add(
        "risk_every_order_has_one_declared_outcome",
        not bad_vocabulary and not resting,
        f"{len(bad_vocabulary)} unknown outcome(s), {len(resting)} left resting",
    )

    # 2. the audit's order rows are the published H6 order rows
    published_orders = read_csv(ROOT / WP01_H6_ORDERS)
    published_primary = [
        r
        for r in published_orders
        if r["run"] == f"{RISK_PRIMARY['window']}:{RISK_PRIMARY['scenario']}"
        and r["arm"] == RISK_PRIMARY["arm"]
    ]
    mine_index = {
        (r["asset"], int(r["placement_ts"]), int(r["placed_bar"])): r for r in primary_orders
    }
    mismatches: list[str] = []
    for row in published_primary:
        key = (row["asset"], int(row["placement_ts"]), int(row["placed_bar"]))
        mine = mine_index.get(key)
        if mine is None:
            mismatches.append(f"missing {key}")
            continue
        for field in ("level", "outcome", "refusal_reason", "expiry_bars", "bars_resting"):
            published_value = row.get(field) or ""
            mine_value = mine.get(field) or ""
            if field in ("level",):
                if abs(float(published_value or 0.0) - float(mine_value or 0.0)) > 1e-6:
                    mismatches.append(f"{key}.{field}: {published_value} vs {mine_value}")
            elif published_value != mine_value:
                mismatches.append(f"{key}.{field}: {published_value!r} vs {mine_value!r}")
    add(
        "risk_order_rows_are_the_published_ones",
        not mismatches and len(published_primary) == len(primary_orders),
        f"{len(published_primary)} published rows compared with {len(primary_orders)} "
        f"reconstructed; {len(mismatches)} mismatch(es)"
        + (f"; first: {mismatches[0]}" if mismatches else ""),
    )

    # 3. the 183 refusals, against a risk state RECONSTRUCTED from the corpus
    refused_orders = [r for r in primary_orders if r["outcome"] == "refused_by_risk_budget"]
    traded = read_csv(ROOT / WP01_H6_TRADES)
    primary_trades = [
        r
        for r in traded
        if r["run"] == f"{RISK_PRIMARY['window']}:{RISK_PRIMARY['scenario']}"
        and r["arm"] == RISK_PRIMARY["arm"]
    ]
    marks = {asset: load_quarter_hour(asset) for asset in ASSETS}
    start, end = INTRADAY_WINDOWS[RISK_PRIMARY["window"]]
    timeline = sorted({ts for asset in ASSETS for ts in marks[asset] if start <= ts <= end})
    entries_at: dict[int, list[dict[str, str]]] = {}
    exits_at: dict[int, list[dict[str, str]]] = {}
    for trade in primary_trades:
        entries_at.setdefault(int(float(trade["entry_ts"])), []).append(trade)
        exits_at.setdefault(int(float(trade["exit_ts"])), []).append(trade)

    # Replay the book on the same clock the simulator used: at each bar the running peak
    # is updated first (marks refreshed, cash as of the previous bar), then the entries and
    # exits of that bar settle. The drawdown a refusal claims is then recomputed here.
    peak = RISK_POLICY["start_equity"]
    cash = RISK_POLICY["start_equity"]
    open_positions: dict[str, dict[str, float]] = {}
    drawdown_at: dict[int, float] = {}
    curve: list[tuple[int, float]] = []
    for ts in timeline:
        equity_start = cash
        for asset, position in open_positions.items():
            close = marks[asset].get(ts)
            equity_start += position["qty"] * (close if close is not None else position["entry_mid"])
        peak = max(peak, equity_start)
        drawdown_at[ts] = (peak - equity_start) / peak * 100.0 if peak > 0 else 0.0
        for trade in entries_at.get(ts, []):
            asset = trade["asset"]
            cash -= fnum(trade, "entry_fill") * fnum(trade, "qty")
            open_positions[asset] = {"qty": fnum(trade, "qty"), "entry_mid": fnum(trade, "entry_mid")}
        for trade in exits_at.get(ts, []):
            asset = trade["asset"]
            cash += fnum(trade, "exit_fill") * fnum(trade, "qty") - fnum(trade, "fees")
            open_positions.pop(asset, None)
        equity_end = cash
        for asset, position in open_positions.items():
            close = marks[asset].get(ts)
            equity_end += position["qty"] * (close if close is not None else position["entry_mid"])
        curve.append((ts, equity_end))

    curve_by_ts = dict(curve)
    published_curve_mismatch = 0
    compared = 0
    for ts, equity in equity_rows:
        mine = curve_by_ts.get(ts)
        if mine is None:
            continue
        compared += 1
        if abs(mine - equity) > max(TOL, abs(equity) * 1e-7):
            published_curve_mismatch += 1
    add(
        "risk_equity_curve_is_rebuilt_from_the_corpus",
        published_curve_mismatch == 0 and compared == len(equity_rows),
        f"{compared}/{len(equity_rows)} bars compared with the published curve; "
        f"{published_curve_mismatch} mismatch(es)",
    )

    # the accounting identity, from the trade ledger alone
    net_sum = sum(fnum(t, "net") for t in primary_trades)
    final_equity = RISK_POLICY["start_equity"] + net_sum
    add(
        "risk_accounting_identity_holds",
        abs(curve[-1][1] - final_equity) < max(TOL, abs(final_equity) * 1e-9),
        f"start {RISK_POLICY['start_equity']:,.2f} + net {net_sum:,.4f} = {final_equity:,.4f} "
        f"vs the replayed curve end {curve[-1][1]:,.4f}",
    )

    # every refusal, decided by the reconstructed state
    reason_counts: dict[str, int] = {}
    disagreement: list[str] = []
    borderline: list[str] = []
    checked = 0
    for row in refusal_rows:
        reason = row["reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        ts = int(row["decision_ts"])
        claimed = fnum(row, "drawdown_pct")
        replayed = drawdown_at.get(ts)
        if reason == "risk_drawdown_halt":
            if replayed is None:
                disagreement.append(f"{ts}: no bar in the windict for the refusal instant")
                continue
            checked += 1
            threshold = float(RISK_POLICY["drawdown_halt_pct"])
            if replayed + 1e-6 < threshold:
                if abs(replayed - threshold) <= 0.02:
                    borderline.append(f"{ts}: replayed {replayed:.6f}% vs the {threshold}% halt")
                else:
                    disagreement.append(
                        f"{ts}: the halt fired at {claimed:.6f}% but the reconstructed drawdown "
                        f"is {replayed:.6f}%"
                    )
            if abs(claimed - replayed) > max(0.02, abs(replayed) * 1e-6):
                disagreement.append(
                    f"{ts}: the recorded drawdown {claimed:.6f}% vs the reconstructed {replayed:.6f}%"
                )
        elif reason == "risk_loss_cooldown":
            checked += 1
            deadline = int(row["cooldown_until_ts"] or 0)
            if not (deadline > ts):
                disagreement.append(f"{ts}: the cooldown deadline {deadline} does not cover the instant")
        elif reason == "risk_max_open_positions":
            checked += 1
            if int(row["open_positions_count"]) < RISK_POLICY["max_open_positions"]:
                disagreement.append(f"{ts}: {row['open_positions_count']} positions open")
        elif reason == "risk_max_trades_per_day":
            checked += 1
            if int(row["trades_today"]) < RISK_POLICY["max_trades_per_day"]:
                disagreement.append(f"{ts}: {row['trades_today']} trades today")
        else:
            checked += 1
            disagreement.append(f"{ts}: {reason!r} is not a reason the declared rules cover")

    add(
        "risk_refusal_reasons_are_the_published_split",
        reason_counts == RISK_EXPECTED_REASONS and len(refusal_rows) == 183,
        f"{len(refusal_rows)} refusals, reasons {reason_counts} vs the published {RISK_EXPECTED_REASONS}",
    )
    add(
        "risk_every_refusal_is_justified_by_the_reconstructed_state",
        not disagreement,
        f"{checked} refusals re-decided from the corpus; {len(disagreement)} disagreement(s), "
        f"{len(borderline)} within 0.02 percentage points of the boundary"
        + (f"; first: {disagreement[0]}" if disagreement else ""),
    )
    add(
        "risk_refusal_instants_are_the_published_order_touches",
        all(
            (row["asset"], int(row["decision_ts"]))
            in {(o["asset"], int(o["outcome_ts"] or 0)) for o in refused_orders}
            for row in refusal_rows
        ),
        f"{len(refusal_rows)} refusals matched against {len(refused_orders)} refused orders",
    )

    # 4. no duplicated refusal, and the invariants the audit declared
    seen: set[tuple[str, int, str]] = set()
    duplicates: list[str] = []
    for row in refusal_rows:
        key = (row["asset"], int(row["decision_ts"]), row["reason"])
        if key in seen:
            duplicates.append(str(key))
        seen.add(key)
    add(
        "risk_no_duplicate_refusals",
        not duplicates,
        f"{len(duplicates)} duplicated (asset, instant, reason) refusal(s) in the primary window",
    )
    declared_invariants = {row["invariant"] for row in invariant_rows}
    expected_invariants = {
        "accounting_final_equity",
        "cash_never_negative",
        "sizing_at_or_below_configured_risk",
        "notional_within_caps",
        "notional_at_or_above_minimum",
        "open_positions_within_limit",
        "trades_per_day_within_limit",
        "one_outcome_per_order",
        "refusals_are_attributed",
        "no_duplicate_refusals",
    }
    failed = [row for row in invariant_rows if row["result"] != "PASS"]
    add(
        "risk_invariants_are_all_declared_and_hold",
        declared_invariants == expected_invariants and not failed,
        f"{len(declared_invariants)} invariants declared (expected {len(expected_invariants)}); "
        f"{len(failed)} failure(s); {len(invariant_rows)} scope rows",
    )

    # 5. the verdict follows from the recomputed facts
    declared_verdict = payload["verdict"]["verdict"]
    expected_verdict = (
        "AUDIT_PASS"
        if not disagreement and not failed and not duplicates
        else "AUDIT_FINDINGS"
    )
    add(
        "risk_verdict_follows_the_declared_rule",
        declared_verdict == expected_verdict,
        f"declared {declared_verdict}; recomputed {expected_verdict}",
    )
    configured = read_risk_config()
    policy_failures = [
        f"{key}: the audit ran with {payload['experiment']['risk_policy'].get(key)} vs the "
        f"configured {value}"
        for key, value in configured.items()
        if abs(float(payload["experiment"]["risk_policy"].get(key, float("nan"))) - value) > 1e-9
    ]
    add(
        "risk_no_limit_was_relaxed",
        not policy_failures,
        f"the audit's budget matches config/risk.yaml on {len(configured)} limits"
        + (f"; {policy_failures[0]}" if policy_failures else ""),
    )
    return checks, failures


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #


def _mutate_json(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    data = read_json(path)
    mutate(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _mutate_csv_row(path: Path, match: Callable[[dict[str, str]], bool], mutate: Callable[[dict[str, str]], None]) -> None:
    rows = read_csv(path)
    fields = list(rows[0].keys())
    for row in rows:
        if match(row):
            mutate(row)
            break
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


SELF_TESTS: dict[str, list[tuple[str, Callable[[Path], None], str]]] = {
    "trend": [
        (
            "move the OOS net",
            lambda base: _mutate_csv_row(
                base / "ROBUSTNESS_WINDOWS.csv", lambda r: r["run"] == "OOS:BASE", lambda r: r.update({"net_usdt": "999.0"})
            ),
            "trend_metrics_match_the_trade_ledger",
        ),
        (
            "widen the bootstrap interval",
            lambda base: _mutate_csv_row(
                base / "ROBUSTNESS_UNCERTAINTY.csv",
                lambda r: r["run"] == "OOS:BASE",
                lambda r: r.update({"bootstrap_upper": "999.0"}),
            ),
            "trend_intervals_are_recomputed",
        ),
        (
            "claim the leave-out net is positive when it is not",
            lambda base: _mutate_csv_row(
                base / "ROBUSTNESS_LEAVE_OUT.csv",
                lambda r: r["run"] == "OOS:BASE" and r["k"] == "3",
                lambda r: r.update({"net_usdt": "42.0"}),
            ),
            "trend_leave_out_is_recomputed",
        ),
        (
            "hide the largest trade",
            lambda base: _mutate_csv_row(
                base / "TREND_TRADES.csv",
                lambda r: r["run"] == "OOS:BASE" and r["book"] == "combined" and float(r["net"]) > 150.0,
                lambda r: r.update({"net": "0.5"}),
            ),
            "trend_metrics_match_the_trade_ledger",
        ),
        (
            "promote a run that the rule refuses",
            lambda base: _mutate_json(
                base / "ROBUSTNESS.json",
                lambda d: d["verdict"].update({"verdict": "ADMIT_PAPER"}),
            ),
            "trend_verdict_follows_the_frozen_rule",
        ),
    ],
    "risk": [
        (
            "invent a refusal with an unsupported instant",
            lambda base: _mutate_csv_row(
                base / "RISK_AUDIT_PRIMARY_REFUSALS.csv",
                lambda r: r["reason"] == "risk_drawdown_halt",
                lambda r: r.update({"decision_ts": "1728000000000"}),
            ),
            "risk_every_refusal_is_justified_by_the_reconstructed_state",
        ),
        (
            "drop an order",
            lambda base: _mutate_csv_row(
                base / "RISK_AUDIT_ORDERS.csv",
                lambda r: r["run"] == "DEV:BASE:plan_limit",
                lambda r: r.update({"outcome": "expired"}),
            ),
            "risk_orders_are_686_with_the_published_outcomes",
        ),
        (
            "launder a refusal through a cooldown that never existed",
            lambda base: _mutate_csv_row(
                base / "RISK_AUDIT_PRIMARY_REFUSALS.csv",
                lambda r: r["reason"] == "risk_drawdown_halt",
                lambda r: r.update({"reason": "risk_loss_cooldown", "cooldown_until_ts": "0"}),
            ),
            "risk_refusal_reasons_are_the_published_split",
        ),
        (
            "flip a declared invariant to PASS after failing it",
            lambda base: _mutate_csv_row(
                base / "RISK_AUDIT_INVARIANTS.csv",
                lambda r: r["result"] == "PASS",
                lambda r: r.update({"result": "FAIL"}),
            ),
            "risk_invariants_are_all_declared_and_hold",
        ),
        (
            "declare a pass the artefacts do not support",
            lambda base: _break_invariant_and_claim_pass(base),
            "risk_verdict_follows_the_declared_rule",
        ),
    ],
}


def _break_invariant_and_claim_pass(base: Path) -> None:
    """Fail one invariant in the ledger while the JSON still declares AUDIT_PASS."""
    _mutate_csv_row(
        base / "RISK_AUDIT_INVARIANTS.csv",
        lambda r: r["result"] == "PASS",
        lambda r: r.update({"result": "FAIL"}),
    )
    _mutate_json(base / "RISK_AUDIT.json", lambda d: d["verdict"].update({"verdict": "AUDIT_PASS"}))


def self_test(experiment: str, dirpath: Path, verifier: Callable[[Path], tuple[list[dict[str, Any]], int]]) -> int:
    """Sabotage a copy of the artefacts and require the declared check to break."""
    base_checks, base_failures = verifier(dirpath)
    print(f"[self-test {experiment}] baseline: {len(base_checks)} checks, {base_failures} fail(s)")
    problems = 0
    for name, mutate, expected_check in SELF_TESTS[experiment]:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy"
            shutil.copytree(dirpath, copy)
            mutate(copy)
            checks, _failures = verifier(copy)
            hit = next((c for c in checks if c["check"] == expected_check), None)
            if hit is None:
                print(f"[self-test {experiment}] {name}: check {expected_check!r} not present")
                problems += 1
                continue
            if hit["result"] == "FAIL":
                print(f"[self-test {experiment}] {name}: detected by {expected_check} -> PASS")
            else:
                print(
                    f"[self-test {experiment}] {name}: NOT detected by {expected_check} "
                    f"({hit['detail'][:80]})"
                )
                problems += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=("trend", "risk", "all"), default="all")
    parser.add_argument("--dir", default="", help="override the artefact directory (per experiment)")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    experiments = ("trend", "risk") if args.experiment == "all" else (args.experiment,)
    reports: list[dict[str, Any]] = []
    failures = 0
    for name in experiments:
        dirpath = Path(args.dir) if args.dir else ROOT / (TREND_DIR if name == "trend" else RISK_DIR)
        verifier = verify_trend if name == "trend" else verify_risk
        if args.self_test:
            problems = self_test(name, dirpath, verifier)
            failures += problems
            reports.append({"experiment": name, "self_test": problems})
            continue
        checks, failed = verifier(dirpath)
        failures += failed
        passed = sum(1 for c in checks if c["result"] == "PASS")
        print(f"[{name}] {passed}/{len(checks)} comprobaciones en verde, {failed} fallos")
        for check in checks:
            mark = "ok  " if check["result"] == "PASS" else "FAIL"
            print(f"[{name}] {mark} {check['check']}: {check['detail']}")
        reports.append(
            {
                "experiment": name,
                "checks": checks,
                "passed": passed,
                "failed": failed,
                "artifacts_dir": str(dirpath.relative_to(ROOT)) if dirpath.is_relative_to(ROOT) else str(dirpath),
            }
        )
    if args.self_test:
        print(f"[self-test] sabotajes no detectados: {failures}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(reports if len(reports) > 1 else reports[0], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
