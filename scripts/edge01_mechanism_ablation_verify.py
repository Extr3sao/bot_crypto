"""Independent verification of the WP-EDGE-01 mechanism experiments (H2, H4).

    python scripts/edge01_mechanism_ablation_verify.py [--experiment h2|h4|all]
                                                       [--self-test] [--json-out FILE]

This process imports NOTHING from ``trading_bot``: it reads the published
artefacts and rebuilds the numbers itself. What it insists on:

 1. ``ARTIFACTS_PRESENT``            every artefact matches the digest the run published
 2. ``WINDOW_IS_PREREGISTERED_DEV``  every trade/refusal/signal sits in DEV, and only DEV
 3. ``TRADE_SIGNAL_JOIN``            every executed trade names the signal that printed it
 4. ``GROSS_BEFORE_COSTS_RECOMPUTED`` gross mid-to-mid recomputed from the trade rows
 5. ``COST_SPLIT_IDENTITY``          gross - price_costs - fees == net, per trade and per arm
 6. ``FUNNEL_ARITHMETIC``            the funnel is a count of the raw refusal rows
 7. ``ARM_METRICS_RECOMPUTED``       the published arm metrics are the metrics of its own rows
 8. ``MARKET_CONTEXT_ATTRIBUTION``   every trade's benchmark label is the one readable at its decision
 9. ``DECISION_RULE_FROZEN``         the rule matches the constants frozen before the run
10. ``VERDICT_RECOMPUTED``           the published verdict is what the rule gives on these numbers

H2 (entry timing) adds:
11. ``BUCKET_ARITHMETIC``            the distance buckets are the declared edges and nothing else
12. ``LEVEL_JOIN_RECOMPUTED``        distance_atr is (entry_mid - level) / atr, recomputed
13. ``FILL_IS_AFTER_THE_SIGNAL``     the fill never precedes the signal it came from

H4 (entry volatility) adds:
11. ``GRID_IS_DATASET_DERIVED``       the frozen grid is the declared percentiles of the DEV ATR sample
12. ``ARMS_ONE_FIELD_APART``          every arm is the frozen candidate plus min_atr_pct, nothing else
13. ``GATE_SOUNDNESS``                the gate only refuses bars below its own threshold, and adds no reason
14. ``SELECTION_MATCHES_THE_RUN``     the frozen threshold is the one the rule selects, and VAL/OOS was not read

``--self-test`` mutates a copy of the artefacts and requires the matching check to
fail; a check nobody can break is reported as a failure, not as a pass.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# What the runs are allowed to be, written here rather than read from them
# --------------------------------------------------------------------------- #

#: Pre-registered splits (WP-EDGE-01 / ADR-0027). Both mechanism experiments are
#: DEV only: VAL and OOS are stated so a window that drifted cannot pass.
INTRADAY_DEV = (
    int(datetime(2024, 10, 1, tzinfo=UTC).timestamp() * 1000),
    int(datetime(2025, 6, 30, tzinfo=UTC).timestamp() * 1000),
)
TREND_DEV = (
    int(datetime(2019, 1, 1, tzinfo=UTC).timestamp() * 1000),
    int(datetime(2023, 12, 31, tzinfo=UTC).timestamp() * 1000),
)

#: H2's frozen rule and the edges its buckets are cut with.
EXPECTED_H2_RULE: dict[str, Any] = {"min_trades_per_side": 25}
EXPECTED_H2_EDGES: tuple[float, ...] = (0.25, 0.5, 1.0)
H2_CODES = ("ENTRY_IS_LATE", "ENTRY_NOT_THE_PROBLEM", "INCONCLUSIVE")

#: H4's frozen rule, the percentiles its grid is read at, and the parameters the
#: candidate was frozen with (restated here, not read from the payload).
EXPECTED_H4_RULE: dict[str, Any] = {
    "min_dev_trades": 30,
    "min_improvement_usdt": 0.0,
    "max_single_trade_share_of_net": 0.5,
}
EXPECTED_H4_PERCENTILES: tuple[float, ...] = (25.0, 50.0, 75.0)
H4_CODES = (
    "FILTER_FROZEN_FOR_VALIDATION",
    "FILTER_NOT_JUSTIFIED_ON_DEV",
    "INCONCLUSIVE",
)
FROZEN_TREND_PARAMS: dict[str, Any] = {
    "ema_fast": 50,
    "ema_slow": 200,
    "breakout_lookback": 20,
    "atr_period": 14,
    "trailing_atr": 3.00,
    "exit_ema": 50,
    "cost_margin": 1.50,
}
VOL_FILTER_REASONS = ("candidate:volatility_filter_fail",)

TOL = 0.05
MIN_FILL_GAP_BARS = 1


class Fatal(Exception):
    """An artefact that cannot even be read: reported, never skipped."""


SPECS: dict[str, dict[str, Any]] = {
    "h2": {
        "label": "H2 entry timing",
        "root": "reports/edge-recovery/WP-EDGE-01/entry-timing-h2",
        "payload": "ENTRY_TIMING.json",
        "verification": "ENTRY_TIMING_VERIFICATION.json",
        "markdown": "ENTRY_TIMING.md",
        "trades": "ENTRY_TIMING_TRADES.csv",
        "signals": "ENTRY_TIMING_SIGNALS.csv",
        "refusals": "ENTRY_TIMING_REFUSALS.csv",
        "join": "ENTRY_TIMING_LEVELS.csv",
        "atr": "",
        "required": (
            "ENTRY_TIMING.json",
            "ENTRY_TIMING.md",
            "ENTRY_TIMING_TRADES.csv",
            "ENTRY_TIMING_LEVELS.csv",
            "ENTRY_TIMING_SIGNALS.csv",
            "ENTRY_TIMING_REFUSALS.csv",
            "MARKET_CONTEXT.csv",
        ),
        "split": "intraday",
        "dev": INTRADAY_DEV,
        "bar_ms": 15 * 60 * 1000,
        "arms": ("diagnostic",),
        "codes": H2_CODES,
        "rule": EXPECTED_H2_RULE,
    },
    "h4": {
        "label": "H4 entry volatility filter",
        "root": "reports/edge-recovery/WP-EDGE-01/vol-filter-h4",
        "payload": "VOL_FILTER.json",
        "verification": "VOL_FILTER_VERIFICATION.json",
        "markdown": "VOL_FILTER.md",
        "trades": "VOL_FILTER_TRADES.csv",
        "signals": "VOL_FILTER_SIGNALS.csv",
        "refusals": "VOL_FILTER_REFUSALS.csv",
        "join": "",
        "atr": "VOL_FILTER_ATR.csv",
        "required": (
            "VOL_FILTER.json",
            "VOL_FILTER.md",
            "VOL_FILTER_TRADES.csv",
            "VOL_FILTER_REFUSALS.csv",
            "VOL_FILTER_SIGNALS.csv",
            "VOL_FILTER_ATR.csv",
            "MARKET_CONTEXT.csv",
        ),
        "split": "trend",
        "dev": TREND_DEV,
        "bar_ms": 4 * 60 * 60 * 1000,
        "arms": ("baseline", "p25", "p50", "p75"),
        "codes": H4_CODES,
        "rule": EXPECTED_H4_RULE,
    },
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Dataset:
    def __init__(self, root: Path, spec: dict[str, Any]) -> None:
        self.root = root
        self.spec = spec
        for name in spec["required"]:
            if not (root / name).exists():
                raise Fatal(f"missing artefact {name} under {root}")
        self.payload = json.loads((root / spec["payload"]).read_text(encoding="utf-8"))
        self.trades = _read_csv(root / spec["trades"])
        self.refusals = _read_csv(root / spec["refusals"])
        self.signals = _read_csv(root / spec["signals"])
        self.market_rows = _read_csv(root / "MARKET_CONTEXT.csv")
        self.join_rows = _read_csv(root / spec["join"]) if spec["join"] else []
        self.atr_rows = _read_csv(root / spec["atr"]) if spec["atr"] else []

    def experiment(self) -> dict[str, Any]:
        return self.payload.get("experiment") or {}

    def arm(self, role: str) -> dict[str, Any]:
        arms = self.payload.get("arms") or {}
        if role not in arms:
            raise Fatal(f"{self.spec['payload']} has no '{role}' arm")
        return arms[role]

    def rows(self, table: list[dict[str, str]], role: str) -> list[dict[str, str]]:
        return [row for row in table if row.get("run") == role]

    def funnel_from_rows(self, role: str) -> dict[str, int]:
        mix: dict[str, int] = {}
        for row in self.rows(self.refusals, role):
            key = f"{row.get('source') or 'candidate'}:{row.get('reason')}"
            mix[key] = mix.get(key, 0) + 1
        return mix


def _f(row: dict[str, Any], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise Fatal(f"row is missing a numeric {key!r}: {row}") from exc


def _tol(rows: list[dict[str, str]]) -> float:
    """Rounding tolerance that grows with the number of rounded rows summed."""
    return max(TOL, TOL * len(rows) / 20.0)


def _direction(row: dict[str, Any]) -> float:
    """+1 for a long, -1 for a short, so gross is recomputed on both sides."""
    return -1.0 if str(row.get("side")) in ("SHORT", "short") else 1.0


def _labels(edges: tuple[float, ...]) -> list[str]:
    """Bucket keys derived from the edges, exactly as the campaign derives them."""
    labels: list[str] = []
    previous: float | None = None
    for edge in edges:
        labels.append(f"<{edge:g}" if previous is None else f"{previous:g}-{edge:g}")
        previous = edge
    labels.append(f">={edges[-1]:g}")
    return labels


def _bucket_of(edges: tuple[float, ...], distance: float) -> str:
    previous: float | None = None
    for edge in edges:
        if distance < edge:
            return f"<{edge:g}" if previous is None else f"{previous:g}-{edge:g}"
        previous = edge
    return f">={edges[-1]:g}"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _nearest_rank(ascending: list[float], pct: float) -> float:
    """Nearest rank: index = ceil(pct/100 * n) - 1. The rule the run declared."""
    rank = math.ceil(pct / 100.0 * len(ascending))
    return float(ascending[min(max(rank - 1, 0), len(ascending) - 1)])


# --------------------------------------------------------------------------- #
# Checks shared by both experiments
# --------------------------------------------------------------------------- #


def check_artifacts_present(ds: Dataset) -> tuple[bool, str]:
    inventory = ds.payload.get("artifacts") or {}
    if not inventory:
        return False, f"{ds.spec['payload']} carries no artefact inventory"
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


def check_window_is_preregistered_dev(ds: Dataset) -> tuple[bool, str]:
    exp = ds.experiment()
    start, end = ds.spec["dev"]
    problems: list[str] = []
    if int(exp.get("window_start_ms") or 0) != start:
        problems.append(f"declared window starts {exp.get('window_start_ms')}, DEV starts {start}")
    if int(exp.get("window_end_ms") or 0) != end:
        problems.append(f"declared window ends {exp.get('window_end_ms')}, DEV ends {end}")
    if str(exp.get("window")) != "DEV":
        problems.append(f"declared window name {exp.get('window')!r} is not DEV")
    if exp.get("split") != ds.spec["split"]:
        problems.append(
            f"declared split {exp.get('split')!r} is not the {ds.spec['split']!r} corpus"
        )
    grace = int(ds.spec["bar_ms"])
    out: list[str] = []
    for row in ds.trades:
        decision = int(row["decision_ts"])
        if not (start <= decision <= end + grace):
            out.append(f"trade decision_ts {decision} outside DEV")
        for key in ("entry_ts", "exit_ts"):
            value = int(row[key])
            if not (start <= value <= end):
                out.append(f"trade {key} {value} outside DEV")
    for table, name in ((ds.refusals, "refusal"), (ds.signals, "signal"), (ds.join_rows, "join")):
        for row in table:
            decision = int(row["decision_ts"])
            if not (start <= decision <= end + grace):
                out.append(f"{name} decision_ts {decision} outside DEV")
    if out:
        problems.extend(out[:5] + ([f"...and {len(out) - 5} more"] if len(out) > 5 else []))
    return (not problems), "; ".join(problems) or (
        f"every one of {len(ds.trades)} trades, {len(ds.refusals)} refusals and "
        f"{len(ds.signals)} signals sits inside the DEV window"
    )


def check_trade_signal_join(ds: Dataset) -> tuple[bool, str]:
    """A trade must name the signal that printed it, in EVERY arm."""
    problems: list[str] = []
    for role in ds.spec["arms"]:
        trades = ds.rows(ds.trades, role)
        signals = {(row["asset"], int(row["bar_index"])) for row in ds.rows(ds.signals, role)}
        missing = sorted(
            {(row["asset"], int(row["signal_bar"])) for row in trades} - signals
        )
        if missing:
            problems.append(f"{role}: {len(missing)} trades name a signal that is not published")
        if len(trades) != int(ds.arm(role).get("trades") or 0):
            problems.append(
                f"{role}: {len(trades)} trade rows but {ds.arm(role).get('trades')} declared"
            )
    if ds.spec["join"]:
        keys = [(row["asset"], int(row["signal_bar"])) for row in ds.join_rows]
        if len(set(keys)) != len(keys):
            problems.append("the join table repeats a (asset, signal_bar) pair")
        trade_keys = {(row["asset"], int(row["signal_bar"])) for row in ds.trades}
        if set(keys) != trade_keys:
            problems.append(
                f"the join table covers {len(set(keys))} trades, the run executed {len(trade_keys)}"
            )
    return (not problems), "; ".join(problems) or (
        f"{len(ds.trades)} trades join their signal across {len(ds.spec['arms'])} arm(s)"
    )


def check_gross_before_costs_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The arm sum AND every single row: a flattered row must not survive the sum."""
    problems: list[str] = []
    detail: list[str] = []
    for role in ds.spec["arms"]:
        rows = ds.rows(ds.trades, role)
        recomputed = sum(
            _direction(r) * (_f(r, "exit_mid") - _f(r, "entry_mid")) * _f(r, "qty") for r in rows
        )
        declared = float(ds.arm(role).get("gross_usdt") or 0.0)
        detail.append(f"{role}: gross {declared:,.2f} vs recomputed {recomputed:,.2f}")
        if abs(recomputed - declared) > _tol(rows):
            problems.append(
                f"{role}: declared gross {declared:,.2f} != recomputed {recomputed:,.2f}"
            )
        for row in rows:
            per_row = _direction(row) * (_f(row, "exit_mid") - _f(row, "entry_mid")) * _f(row, "qty")
            if abs(per_row - _f(row, "gross")) > TOL:
                problems.append(
                    f"{role}: {row['asset']} @ {row['decision_ts']} publishes gross "
                    f"{_f(row, 'gross'):.4f}, its own prices give {per_row:.4f}"
                )
            if len(problems) > 5:
                break
    return (not problems), "; ".join(problems) or " | ".join(detail)


def check_cost_split_identity(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    for role in ds.spec["arms"]:
        rows = ds.rows(ds.trades, role)
        tol = _tol(rows)
        for row in rows:
            gross = _f(row, "gross")
            fees = _f(row, "fees")
            price = _f(row, "price_costs")
            net = _f(row, "net")
            if abs((gross - price - fees) - net) > TOL:
                problems.append(
                    f"{role}: gross {gross:.4f} - costs {price:.4f} - fees {fees:.4f} != net {net:.4f}"
                )
            fills = (_f(row, "exit_fill") - _f(row, "entry_fill")) * _f(row, "qty") - fees
            if abs(fills - net) > TOL:
                problems.append(f"{role}: fills x qty - fees = {fills:.4f} != net {net:.4f}")
            if len(problems) > 5:
                break
        for name, column in (
            ("fees_usdt", "fees"),
            ("price_costs_usdt", "price_costs"),
            ("net_usdt", "net"),
        ):
            declared = float(ds.arm(role).get(name) or 0.0)
            counted = sum(_f(r, column) for r in rows)
            if abs(counted - declared) > tol:
                problems.append(f"{role}: declared {name} {declared:,.2f} != the sum of the rows")
    return (not problems), "; ".join(problems) or "cost split reconciles on every arm"


def check_funnel_arithmetic(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    summary: list[str] = []
    for role in ds.spec["arms"]:
        counted = ds.funnel_from_rows(role)
        declared = {str(k): int(v) for k, v in (ds.arm(role).get("refusals") or {}).items()}
        summary.append(f"{role}: {sum(counted.values())} refusals over {len(counted)} reasons")
        if counted != declared:
            only_file = {k: v for k, v in counted.items() if declared.get(k) != v}
            only_json = {k: v for k, v in declared.items() if counted.get(k) != v}
            problems.append(
                f"{role}: file and JSON disagree (file-only {only_file}, json-only {only_json})"
            )
    return (not problems), "; ".join(problems) or " | ".join(summary)


def check_arm_metrics_recomputed(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    detail: list[str] = []
    for role in ds.spec["arms"]:
        arm = ds.arm(role)
        rows = ds.rows(ds.trades, role)
        tol = _tol(rows)
        nets = [_f(row, "net") for row in rows]
        checks = (
            ("trades", float(len(rows))),
            ("gross_usdt", sum(_f(row, "gross") for row in rows)),
            ("net_usdt", sum(nets)),
            ("fees_usdt", sum(_f(row, "fees") for row in rows)),
            ("price_costs_usdt", sum(_f(row, "price_costs") for row in rows)),
            ("expectancy_usdt", (sum(nets) / len(nets)) if nets else 0.0),
        )
        for key, recomputed in checks:
            declared = float(arm.get(key) or 0.0)
            if abs(recomputed - declared) > tol:
                problems.append(
                    f"{role}.{key}: declared {declared:,.4f} != recomputed {recomputed:,.4f}"
                )
        wins = sum(1 for net in nets if net > 0)
        win_rate = round(100.0 * wins / len(nets), 4) if nets else None
        declared_rate = arm.get("win_rate_pct")
        if win_rate is None:
            if declared_rate is not None:
                problems.append(f"{role}.win_rate_pct: declared {declared_rate} with no rows")
        elif declared_rate is None or abs(float(declared_rate) - win_rate) > TOL:
            problems.append(
                f"{role}.win_rate_pct: declared {declared_rate} != recomputed {win_rate}"
            )
        detail.append(f"{role}: {len(rows)} trades, net {sum(nets):,.2f}")
    return (not problems), "; ".join(problems) or " | ".join(detail)


def check_market_context_attribution(ds: Dataset) -> tuple[bool, str]:
    rows = ds.market_rows
    if not rows:
        return False, "MARKET_CONTEXT.csv is empty: every trade cites a benchmark label"
    declared = ds.payload.get("market_context") or {}
    if not str(declared.get("rule") or ""):
        return False, f"{ds.spec['payload']} does not state the market-context rule"
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
        problems.append(
            f"{ds.spec['payload']} declares {declared_days} benchmark days, the file has {len(days)}"
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
                f"{row['run']}/{row['asset']} @ {row['decision_ts']}: market_context "
                f"{actual!r} != {expected!r} readable at that instant"
            )
        if len(problems) > 5:
            break
    spread = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return (not problems), "; ".join(problems) or (
        f"{len(ds.trades)} trades attributed from {len(days)} benchmark days ({spread})"
    )


def check_decision_rule_frozen(ds: Dataset) -> tuple[bool, str]:
    verdict = ds.payload.get("verdict") or {}
    declared = verdict.get("rule") or {}
    problems: list[str] = []
    for key, expected in ds.spec["rule"].items():
        if declared.get(key) != expected:
            problems.append(f"rule.{key} is {declared.get(key)!r}, frozen value is {expected!r}")
    if not declared:
        problems.append("the verdict does not quote the rule it was applied with")
    if not str(verdict.get("rule_text") or ""):
        problems.append("the verdict does not quote the rule text it was applied with")
    meaning = verdict.get("meaning") or {}
    for label in ds.spec["codes"]:
        if label not in meaning:
            problems.append(f"the rule does not state what {label} means")
    if ds.spec["payload"].startswith("VOL_FILTER"):
        grid = ds.payload.get("grid") or {}
        if [float(p) for p in grid.get("percentiles") or []] != list(EXPECTED_H4_PERCENTILES):
            problems.append(
                f"the grid percentiles are {grid.get('percentiles')}, frozen ones are "
                f"{list(EXPECTED_H4_PERCENTILES)}"
            )
    else:
        if [float(e) for e in verdict.get("bucket_edges_atr") or []] != list(EXPECTED_H2_EDGES):
            problems.append(
                f"the bucket edges are {verdict.get('bucket_edges_atr')}, frozen ones are "
                f"{list(EXPECTED_H2_EDGES)}"
            )
    return (not problems), "; ".join(problems) or (
        f"the decision rule matches the pre-registered constants ({ds.spec['rule']})"
    )


def _recompute_h2(ds: Dataset) -> tuple[str, str]:
    """H2's rule, applied to the published join table only."""
    labels = _labels(EXPECTED_H2_EDGES)
    totals = {
        label: {
            "trades": 0,
            "net": 0.0,
        }
        for label in labels
    }
    for row in ds.join_rows:
        totals[_bucket_of(EXPECTED_H2_EDGES, float(row["distance_atr"]))]["trades"] += 1
        totals[_bucket_of(EXPECTED_H2_EDGES, float(row["distance_atr"]))]["net"] += _f(row, "net")
    near_key, far_keys = labels[0], labels[1:]
    near_trades = totals[near_key]["trades"]
    far_trades = sum(totals[key]["trades"] for key in far_keys)
    near_exp = (totals[near_key]["net"] / near_trades) if near_trades else 0.0
    far_exp = (sum(totals[key]["net"] for key in far_keys) / far_trades) if far_trades else 0.0
    floor = int(EXPECTED_H2_RULE["min_trades_per_side"])
    if near_trades < floor or far_trades < floor:
        code = "INCONCLUSIVE"
    elif far_trades >= near_trades and near_exp > far_exp:
        code = "ENTRY_IS_LATE"
    else:
        code = "ENTRY_NOT_THE_PROBLEM"
    return code, (
        f"near {near_trades} @ {near_exp:+.4f}, far {far_trades} @ {far_exp:+.4f}, "
        f"floor {floor}"
    )


def _recompute_h4(ds: Dataset) -> tuple[str, float | None, str]:
    """H4's rule, applied to the published arm metrics only."""
    floor = int(EXPECTED_H4_RULE["min_dev_trades"])
    ceiling = float(EXPECTED_H4_RULE["max_single_trade_share_of_net"])
    baseline = ds.arm("baseline")
    eligible = {
        name: ds.arm(name)
        for name in ds.spec["arms"]
        if int(ds.arm(name).get("trades") or 0) >= floor
    }
    if "baseline" not in eligible:
        return "INCONCLUSIVE", None, (
            f"the unfiltered baseline prints {baseline.get('trades')} DEV trades, under {floor}"
        )
    ranking = sorted(
        eligible.items(),
        key=lambda item: (
            -float(item[1].get("net_usdt") or 0.0),
            float(item[1].get("min_atr_pct") or 0.0),
        ),
    )
    name, winner = ranking[0]
    improvement = float(winner.get("net_usdt") or 0.0) - float(baseline.get("net_usdt") or 0.0)
    share = winner.get("largest_trade_share_of_net")
    carried = share is not None and float(share) > ceiling
    not_justified = (
        name == "baseline"
        or improvement <= float(EXPECTED_H4_RULE["min_improvement_usdt"])
        or float(winner.get("net_usdt") or 0.0) <= 0.0
        or carried
    )
    code = "FILTER_NOT_JUSTIFIED_ON_DEV" if not_justified else "FILTER_FROZEN_FOR_VALIDATION"
    frozen = (
        float(winner.get("min_atr_pct"))
        if code == "FILTER_FROZEN_FOR_VALIDATION" and winner.get("min_atr_pct") is not None
        else None
    )
    return code, frozen, (
        f"winner {name} at {float(winner.get('net_usdt') or 0.0):,.2f} USDT against "
        f"{float(baseline.get('net_usdt') or 0.0):,.2f} unfiltered ({improvement:+,.2f})"
    )


def check_verdict_recomputed(ds: Dataset) -> tuple[bool, str]:
    verdict = ds.payload.get("verdict") or {}
    declared = str(verdict.get("verdict"))
    if declared not in ds.spec["codes"]:
        return False, f"verdict {declared!r} is not one of {list(ds.spec['codes'])}"
    if ds.spec["join"]:
        recomputed, detail = _recompute_h2(ds)
        frozen = None
    else:
        recomputed, frozen, detail = _recompute_h4(ds)
    if declared != recomputed:
        return False, f"declared {declared} but the rule on the published numbers gives {recomputed} ({detail})"
    if frozen is not None:
        published = verdict.get("frozen_threshold_pct")
        if published is None or abs(float(published) - frozen) > 1e-9:
            return False, f"frozen threshold {published} is not the selected one ({frozen})"
    return True, f"{declared} recomputed: {detail}"


# --------------------------------------------------------------------------- #
# H2 checks
# --------------------------------------------------------------------------- #


def check_bucket_arithmetic(ds: Dataset) -> tuple[bool, str]:
    """The buckets are the declared edges and nothing else, and they are complete."""
    labels = _labels(EXPECTED_H2_EDGES)
    buckets = ds.payload.get("buckets") or {}
    problems: list[str] = []
    if sorted(buckets) != sorted(labels):
        problems.append(f"the payload's buckets are {sorted(buckets)}, declared edges give {labels}")
    misassigned = [
        row
        for row in ds.join_rows
        if row.get("bucket") != _bucket_of(EXPECTED_H2_EDGES, float(row["distance_atr"]))
    ]
    if misassigned:
        problems.append(f"{len(misassigned)} rows sit in a bucket their distance is not in")
    placed = sum(len([r for r in ds.join_rows if r.get("bucket") == label]) for label in labels)
    if placed != len(ds.join_rows):
        problems.append(f"{len(ds.join_rows)} join rows but {placed} counted in the buckets")
    for label in labels:
        subset = [row for row in ds.join_rows if row.get("bucket") == label]
        entry = buckets.get(label) or {}
        nets = [_f(row, "net") for row in subset]
        expected = {
            "trades": len(subset),
            "net_usdt": round(sum(nets), 4),
            "gross_usdt": round(sum(_f(row, "gross") for row in subset), 4),
            "fees_usdt": round(sum(_f(row, "fees") for row in subset), 4),
            "price_costs_usdt": round(sum(_f(row, "price_costs") for row in subset), 4),
            "cost_usdt": round(
                sum(_f(row, "fees") + _f(row, "price_costs") for row in subset), 4
            ),
            "expectancy_usdt": round(sum(nets) / len(subset), 4) if subset else None,
        }
        for key, value in expected.items():
            declared = entry.get(key)
            if value is None:
                if declared is not None:
                    problems.append(f"{label}.{key}: declared {declared} with no rows")
                continue
            if declared is None or abs(float(declared) - float(value)) > _tol(subset):
                problems.append(f"{label}.{key}: declared {declared} != recomputed {value}")
        median = _median([_f(row, "distance_atr") for row in subset])
        declared_median = entry.get("median_distance_atr")
        if median is None:
            if declared_median is not None:
                problems.append(f"{label}.median_distance_atr: declared with no rows")
        elif declared_median is None or abs(float(declared_median) - median) > 1e-6:
            problems.append(
                f"{label}.median_distance_atr: declared {declared_median} != recomputed {median}"
            )
    near = buckets.get(labels[0]) or {}
    verdict = ds.payload.get("verdict") or {}
    declared_near = (verdict.get("near") or {}).get("trades")
    actual_near = near.get("trades")
    # an empty first bucket is a legitimate reading, so 0 must compare equal to 0
    if declared_near is None or actual_near is None or int(declared_near) != int(actual_near):
        problems.append(
            f"the verdict's `near` is {declared_near} trades, the first bucket holds {actual_near}"
        )
    return (not problems), "; ".join(problems) or (
        f"{len(ds.join_rows)} fills split into {labels} and every aggregate recomputed"
    )


def check_level_join_recomputed(ds: Dataset) -> tuple[bool, str]:
    """distance_atr really is (entry_mid - level) / atr, on the published rows."""
    signals = {(row["asset"], int(row["bar_index"])): row for row in ds.signals}
    trades = {(row["asset"], int(row["signal_bar"])): row for row in ds.trades}
    problems: list[str] = []
    for row in ds.join_rows:
        key = (row["asset"], int(row["signal_bar"]))
        signal = signals.get(key)
        trade = trades.get(key)
        if signal is None or trade is None:
            problems.append(f"{key}: join row names a signal or a trade that is not published")
            continue
        level = _f(row, "level")
        atr_value = _f(row, "atr")
        if atr_value <= 0 or level <= 0:
            problems.append(f"{key}: level {level} or atr {atr_value} is not positive")
            continue
        if abs(level - _f(signal, "hard_invalidation")) > 1e-8:
            problems.append(f"{key}: level {level} is not the signal's own hard_invalidation")
        if abs(atr_value - _f(signal, "atr")) > 1e-8:
            problems.append(f"{key}: atr {atr_value} is not the signal's own atr")
        if abs(_f(row, "entry_mid") - _f(trade, "entry_mid")) > 1e-6:
            problems.append(f"{key}: entry_mid differs from the executed trade")
        recomputed = (_f(row, "entry_mid") - level) / atr_value
        if abs(recomputed - _f(row, "distance_atr")) > 1e-6:
            problems.append(
                f"{key}: distance_atr {_f(row, 'distance_atr')} != recomputed {recomputed:.6f}"
            )
        if len(problems) > 5:
            break
    spread = _median([_f(row, "distance_atr") for row in ds.join_rows])
    return (not problems), "; ".join(problems) or (
        f"{len(ds.join_rows)} fills: distance recomputed from the level each signal names "
        f"(median {spread:.4f} ATR)"
    )


def check_fill_is_after_the_signal(ds: Dataset) -> tuple[bool, str]:
    """A fill cannot precede the signal, and the distance is not a rounding artefact."""
    problems: list[str] = []
    for row in ds.trades:
        if str(row.get("side")) != "LONG":
            problems.append(f"{row['asset']} @ {row['decision_ts']}: side {row.get('side')!r}")
        if int(row["entry_bar"]) - int(row["signal_bar"]) < MIN_FILL_GAP_BARS:
            problems.append(
                f"{row['asset']} @ {row['decision_ts']}: entry bar {row['entry_bar']} is not "
                f"after signal bar {row['signal_bar']}"
            )
        if int(row["entry_ts"]) < int(row["decision_ts"]):
            problems.append(f"{row['asset']} @ {row['decision_ts']}: entry_ts precedes the signal")
        if _f(row, "qty") <= 0:
            problems.append(f"{row['asset']} @ {row['decision_ts']}: qty {row['qty']} is not positive")
        if len(problems) > 5:
            break
    return (not problems), "; ".join(problems) or (
        f"all {len(ds.trades)} fills happen after the signal that printed them"
    )


# --------------------------------------------------------------------------- #
# H4 checks
# --------------------------------------------------------------------------- #


def check_grid_is_dataset_derived(ds: Dataset) -> tuple[bool, str]:
    """The frozen grid is the declared percentile of the published DEV ATR sample."""
    values = sorted(_f(row, "atr_pct") for row in ds.atr_rows)
    if not values:
        return False, "VOL_FILTER_ATR.csv is empty: the grid cannot be recomputed"
    grid = ds.payload.get("grid") or {}
    sample = grid.get("sample") or {}
    declared = grid.get("values_pct") or {}
    problems: list[str] = []
    if int(sample.get("bars_with_atr") or -1) != len(values):
        problems.append(
            f"the sample claims {sample.get('bars_with_atr')} bars, the file has {len(values)}"
        )
    for pct in EXPECTED_H4_PERCENTILES:
        key = f"p{int(pct)}"
        if key not in declared:
            problems.append(f"the grid does not carry {key}")
            continue
        recomputed = _nearest_rank(values, pct)
        if abs(float(declared[key]) - recomputed) > 1e-9:
            problems.append(
                f"{key}: declared {declared[key]} != nearest-rank {recomputed} of the published sample"
            )
    for key, recomputed in (
        ("min_atr_pct", values[0]),
        ("max_atr_pct", values[-1]),
        ("median_atr_pct", _median(values)),
    ):
        declared_value = sample.get(key)
        if declared_value is None or abs(float(declared_value) - float(recomputed)) > 1e-5:
            problems.append(f"sample.{key}: declared {declared_value} != recomputed {recomputed}")
    return (not problems), "; ".join(problems) or (
        f"grid {declared} recomputed from {len(values)} DEV bars "
        f"(nearest rank at {list(EXPECTED_H4_PERCENTILES)})"
    )


def check_arms_one_field_apart(ds: Dataset) -> tuple[bool, str]:
    """Every arm is the FROZEN candidate plus min_atr_pct: not a re-tuned candidate."""
    exp = ds.experiment()
    base = exp.get("frozen_params_baseline") or {}
    grid = (ds.payload.get("grid") or {}).get("values_pct") or {}
    problems: list[str] = []
    if base != FROZEN_TREND_PARAMS:
        problems.append(f"the run's frozen baseline params {base} are not {FROZEN_TREND_PARAMS}")
    for name in ds.spec["arms"]:
        arm = ds.arm(name)
        params = arm.get("params") or {}
        threshold = arm.get("min_atr_pct")
        if name == "baseline":
            if threshold is not None:
                problems.append("the baseline arm carries a threshold")
            if params != FROZEN_TREND_PARAMS:
                problems.append(f"the baseline arm's params are {params}")
            continue
        expected = {**FROZEN_TREND_PARAMS, "min_atr_pct": threshold}
        if params != expected:
            extra = {k: v for k, v in params.items() if expected.get(k) != v}
            problems.append(f"{name}: params differ from the frozen candidate plus one field ({extra})")
        if threshold is None or not any(abs(float(threshold) - float(v)) < 1e-12 for v in grid.values()):
            problems.append(f"{name}: threshold {threshold} is not one of the declared grid values")
        delta = arm.get("params_delta") or {}
        if delta != {"added": ["min_atr_pct"], "removed": [], "changed": []}:
            problems.append(f"{name}: published params_delta {delta} is not one added field")
    return (not problems), "; ".join(problems) or (
        f"{len(ds.spec['arms'])} arms: the frozen candidate with {list(grid)} and nothing else"
    )


def check_gate_soundness(ds: Dataset) -> tuple[bool, str]:
    """The gate only refuses what is below its own threshold, and adds no other reason."""
    baseline_reasons = {f"{r.get('source') or 'candidate'}:{r.get('reason')}" for r in ds.rows(ds.refusals, "baseline")}
    problems: list[str] = []
    summary: list[str] = []
    for name in ds.spec["arms"]:
        arm = ds.arm(name)
        rows = ds.rows(ds.refusals, name)
        vol = [row for row in rows if f"{row.get('source')}:{row.get('reason')}" in VOL_FILTER_REASONS]
        summary.append(f"{name}: {len(vol)} volatility refusals")
        if name == "baseline":
            if vol:
                problems.append(f"the baseline refuses {len(vol)} bars for volatility")
        else:
            threshold = arm.get("min_atr_pct")
            if int(arm.get("vol_refusals") or 0) != len(vol):
                problems.append(
                    f"{name}: declares {arm.get('vol_refusals')} volatility refusals, "
                    f"the file has {len(vol)}"
                )
            above = [
                row
                for row in vol
                if row.get("atr_pct") in (None, "")
                or row.get("min_atr_pct") in (None, "")
                or _f(row, "atr_pct") >= _f(row, "min_atr_pct")
            ]
            if above:
                problems.append(
                    f"{name}: {len(above)} volatility refusals are at or above their own threshold"
                )
            if threshold is not None and any(
                abs(_f(row, "min_atr_pct") - float(threshold)) > 1e-12 for row in vol
            ):
                problems.append(f"{name}: a refusal was decided with a different threshold")
            published = [
                row
                for row in ds.rows(ds.signals, name)
                if _f(row, "atr_pct") < float(threshold if threshold is not None else 0.0)
            ]
            if published:
                problems.append(
                    f"{name}: {len(published)} published signals sit below their own threshold"
                )
        reasons = {f"{r.get('source') or 'candidate'}:{r.get('reason')}" for r in rows}
        unknown = sorted(reasons - baseline_reasons - set(VOL_FILTER_REASONS))
        if unknown:
            problems.append(f"{name}: refusals for reasons the baseline never had ({unknown})")
    return (not problems), "; ".join(problems) or " | ".join(summary)


def check_selection_matches_the_run(ds: Dataset) -> tuple[bool, str]:
    """The frozen threshold is the one the rule selects, and VAL/OOS was not read."""
    ds_verdict = ds.payload.get("verdict") or {}
    code, frozen, detail = _recompute_h4(ds)
    problems: list[str] = []
    if code == "FILTER_FROZEN_FOR_VALIDATION":
        published = ds_verdict.get("frozen_threshold_pct")
        if published is None or abs(float(published) - float(frozen)) > 1e-12:
            problems.append(f"the frozen threshold is {published}, the rule selects {frozen}")
    elif ds_verdict.get("frozen_threshold_pct") is not None:
        problems.append(
            f"the verdict froze {ds_verdict.get('frozen_threshold_pct')} while the rule "
            f"answers {code}"
        )
    if ds_verdict.get("val_oos_read") is not False:
        problems.append(f"val_oos_read is {ds_verdict.get('val_oos_read')!r}, not False")
    ranking = ds_verdict.get("ranking") or []
    expected_ranking = [
        name
        for name, _ in sorted(
            (
                (name, ds.arm(name))
                for name in ds.spec["arms"]
                if int(ds.arm(name).get("trades") or 0) >= int(EXPECTED_H4_RULE["min_dev_trades"])
            ),
            key=lambda item: (
                -float(item[1].get("net_usdt") or 0.0),
                float(item[1].get("min_atr_pct") or 0.0),
            ),
        )
    ]
    if list(ranking) != expected_ranking:
        problems.append(f"the published ranking {ranking} is not {expected_ranking}")
    return (not problems), "; ".join(problems) or (
        f"{code}: {detail}; VAL/OOS not read, ranking {ranking}"
    )


SHARED_CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("WINDOW_IS_PREREGISTERED_DEV", check_window_is_preregistered_dev),
    ("TRADE_SIGNAL_JOIN", check_trade_signal_join),
    ("GROSS_BEFORE_COSTS_RECOMPUTED", check_gross_before_costs_recomputed),
    ("COST_SPLIT_IDENTITY", check_cost_split_identity),
    ("FUNNEL_ARITHMETIC", check_funnel_arithmetic),
    ("ARM_METRICS_RECOMPUTED", check_arm_metrics_recomputed),
    ("MARKET_CONTEXT_ATTRIBUTION", check_market_context_attribution),
    ("DECISION_RULE_FROZEN", check_decision_rule_frozen),
    ("VERDICT_RECOMPUTED", check_verdict_recomputed),
)

H2_CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("BUCKET_ARITHMETIC", check_bucket_arithmetic),
    ("LEVEL_JOIN_RECOMPUTED", check_level_join_recomputed),
    ("FILL_IS_AFTER_THE_SIGNAL", check_fill_is_after_the_signal),
)

H4_CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("GRID_IS_DATASET_DERIVED", check_grid_is_dataset_derived),
    ("ARMS_ONE_FIELD_APART", check_arms_one_field_apart),
    ("GATE_SOUNDNESS", check_gate_soundness),
    ("SELECTION_MATCHES_THE_RUN", check_selection_matches_the_run),
)


def checks_for(spec: dict[str, Any]) -> tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...]:
    if spec["join"]:
        return SHARED_CHECKS + H2_CHECKS
    return SHARED_CHECKS + H4_CHECKS


def run_checks(root: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
    ds = Dataset(root, spec)
    out: list[dict[str, Any]] = []
    for name, fn in checks_for(spec):
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _store_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mutate_gross(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    rows[0]["gross"] = str(_f(rows[0], "gross") + 25.0)
    _rewrite_csv(path, rows)


def _mutate_fees(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    rows[1]["fees"] = str(_f(rows[1], "fees") + 5.0)
    _rewrite_csv(path, rows)


def _mutate_window_to_val(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    start, end = spec["dev"]
    payload["experiment"]["window_start_ms"] = start + 90 * 86_400_000
    payload["experiment"]["window_end_ms"] = end + 400 * 86_400_000
    _store_json(path, payload)


def _mutate_out_of_window_trade(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    start, _end = spec["dev"]
    rows[0]["entry_ts"] = str(start - 86_400_000)
    _rewrite_csv(path, rows)


def _mutate_drop_refusals(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["refusals"]
    rows = _read_csv(path)
    _rewrite_csv(path, rows[1:])


def _mutate_drop_trade(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    _rewrite_csv(path, rows[1:])


def _mutate_orphan_signal(root: Path, spec: dict[str, Any]) -> None:
    trades = _read_csv(root / spec["trades"])
    key = (trades[0]["asset"], trades[0]["signal_bar"])
    path = root / spec["signals"]
    rows = [row for row in _read_csv(path) if (row["asset"], row["bar_index"]) != key]
    _rewrite_csv(path, rows)


def _mutate_market_context(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    rows = _read_csv(path)
    labels = list((_load_json(root / spec["payload"]).get("market_context") or {}).get("labels") or [])
    alternative = next((label for label in labels if label != rows[0].get("market_context")), "UNDEFINED")
    rows[0]["market_context"] = alternative
    _rewrite_csv(path, rows)


def _mutate_flip_verdict(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    codes = [code for code in spec["codes"] if code != payload["verdict"]["verdict"]]
    payload["verdict"]["verdict"] = codes[0]
    _store_json(path, payload)


def _mutate_rule_threshold(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    for key, value in list(payload["verdict"]["rule"].items()):
        payload["verdict"]["rule"][key] = value - 1 if isinstance(value, int) else value
    _store_json(path, payload)


def _mutate_arm_net(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    arm = payload["arms"][spec["arms"][0]]
    arm["net_usdt"] = float(arm.get("net_usdt") or 0.0) + 250.0
    _store_json(path, payload)


def _mutate_touched_artifact(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["trades"]
    path.write_bytes(path.read_bytes() + b"\n")


SHARED_MUTATIONS: tuple[tuple[str, str, Callable[[Path, dict[str, Any]], None]], ...] = (
    ("M1_flattered_gross", "GROSS_BEFORE_COSTS_RECOMPUTED", _mutate_gross),
    ("M2_tampered_fees", "COST_SPLIT_IDENTITY", _mutate_fees),
    ("M3_window_moved_to_val", "WINDOW_IS_PREREGISTERED_DEV", _mutate_window_to_val),
    ("M4_out_of_window_trade", "WINDOW_IS_PREREGISTERED_DEV", _mutate_out_of_window_trade),
    ("M5_refusals_trimmed", "FUNNEL_ARITHMETIC", _mutate_drop_refusals),
    ("M6_trade_dropped", "TRADE_SIGNAL_JOIN", _mutate_drop_trade),
    ("M7_signal_removed", "TRADE_SIGNAL_JOIN", _mutate_orphan_signal),
    ("M8_relabelled_market_context", "MARKET_CONTEXT_ATTRIBUTION", _mutate_market_context),
    ("M9_flipped_verdict", "VERDICT_RECOMPUTED", _mutate_flip_verdict),
    ("M10_relaxed_rule", "DECISION_RULE_FROZEN", _mutate_rule_threshold),
    ("M11_arm_net_tampered", "ARM_METRICS_RECOMPUTED", _mutate_arm_net),
    ("M12_artifact_touched", "ARTIFACTS_PRESENT", _mutate_touched_artifact),
)


def _mutate_level_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["join"]
    rows = _read_csv(path)
    rows[0]["level"] = str(_f(rows[0], "level") * 1.01)
    _rewrite_csv(path, rows)


def _mutate_bucket_misassigned(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["join"]
    rows = _read_csv(path)
    labels = _labels(EXPECTED_H2_EDGES)
    rows[0]["bucket"] = next(label for label in labels if label != rows[0]["bucket"])
    _rewrite_csv(path, rows)


def _mutate_bucket_edges_relaxed(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    edges = list(payload["verdict"]["bucket_edges_atr"])
    edges[0] = edges[0] * 2
    payload["verdict"]["bucket_edges_atr"] = edges
    _store_json(path, payload)


H2_MUTATIONS: tuple[tuple[str, str, Callable[[Path, dict[str, Any]], None]], ...] = (
    ("M13_level_tampered", "LEVEL_JOIN_RECOMPUTED", _mutate_level_tampered),
    ("M14_bucket_misassigned", "BUCKET_ARITHMETIC", _mutate_bucket_misassigned),
    ("M15_edges_relaxed", "DECISION_RULE_FROZEN", _mutate_bucket_edges_relaxed),
)


def _mutate_grid_tampered(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    key = sorted(payload["grid"]["values_pct"])[0]
    payload["grid"]["values_pct"][key] = float(payload["grid"]["values_pct"][key]) + 0.01
    _store_json(path, payload)


def _mutate_second_field_retuned(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    arm = payload["arms"]["p50"]
    arm["params"]["trailing_atr"] = 2.5
    _store_json(path, payload)


def _mutate_vol_refusal_above_threshold(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["refusals"]
    rows = _read_csv(path)
    target = next(
        row for row in rows
        if row.get("run") != "baseline" and row.get("reason") == "volatility_filter_fail"
    )
    target["atr_pct"] = str(_f(target, "min_atr_pct") + 0.5)
    _rewrite_csv(path, rows)


def _mutate_baseline_gate_fires(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["refusals"]
    rows = _read_csv(path)
    clone = dict(rows[0])
    clone["run"] = "baseline"
    clone["reason"] = "volatility_filter_fail"
    clone["source"] = "candidate"
    clone["atr_pct"] = "0.1"
    clone["min_atr_pct"] = "1.0"
    _rewrite_csv(path, [*rows, clone])


def _mutate_frozen_threshold_flipped(root: Path, spec: dict[str, Any]) -> None:
    path = root / spec["payload"]
    payload = _load_json(path)
    payload["verdict"]["frozen_threshold_pct"] = float(
        sorted(payload["grid"]["values_pct"].values())[0]
    )
    _store_json(path, payload)


H4_MUTATIONS: tuple[tuple[str, str, Callable[[Path, dict[str, Any]], None]], ...] = (
    ("M13_grid_tampered", "GRID_IS_DATASET_DERIVED", _mutate_grid_tampered),
    ("M14_second_field_retuned", "ARMS_ONE_FIELD_APART", _mutate_second_field_retuned),
    ("M15_vol_refusal_above_threshold", "GATE_SOUNDNESS", _mutate_vol_refusal_above_threshold),
    ("M16_baseline_gate_fires", "GATE_SOUNDNESS", _mutate_baseline_gate_fires),
    ("M17_frozen_threshold_flipped", "SELECTION_MATCHES_THE_RUN", _mutate_frozen_threshold_flipped),
)


def mutations_for(
    spec: dict[str, Any],
) -> tuple[tuple[str, str, Callable[[Path], None]], ...]:
    extra = H2_MUTATIONS if spec["join"] else H4_MUTATIONS
    return tuple(
        (name, expected, partial(fn, spec=spec)) for name, expected, fn in SHARED_MUTATIONS + extra
    )


def self_test(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    baseline = {entry["check"]: entry["ok"] for entry in run_checks(root, spec)}
    results: list[dict[str, Any]] = []
    for name, expected, mutate in mutations_for(spec):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "artefacts"
            shutil.copytree(root, copy)
            mutate(copy)
            try:
                after = {entry["check"]: entry for entry in run_checks(copy, spec)}
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
                f"[{status}] {item['mutation']:<32} -> {item['expected_check']} "
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
    parser.add_argument("--experiment", choices=("h2", "h4", "all"), default="all")
    parser.add_argument("--dir", default="", help="override the artefact directory")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json-out", default="", help="write the report to one file")
    args = parser.parse_args(argv)

    keys = ("h2", "h4") if args.experiment == "all" else (args.experiment,)
    reports: list[dict[str, Any]] = []
    failures = 0
    for key in keys:
        spec = SPECS[key]
        report, failed = verify_one(
            key, root=Path(args.dir) if args.dir else None, self_test_run=args.self_test
        )
        reports.append(report)
        failures += failed
        if args.dir:
            out = Path(args.dir) / spec["verification"]
        else:
            out = Path(spec["root"]) / spec["verification"]
        if not report.get("fatal"):
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
