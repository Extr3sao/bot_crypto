"""Independent verification of the WP-EDGE-01 H1 ablation (EDGE-INTRA-01 minus 1h filter).

    python scripts/edge01_ablation_verify.py [--dir reports/edge-recovery/WP-EDGE-01/ablation-h1]
                                             [--self-test] [--json-out FILE]

This process imports NOTHING from ``trading_bot``: it reads the published
artefacts and rebuilds the numbers itself. Every claim the ablation makes is
re-derived here from the raw rows:

* the window is the pre-registered intraday DEV window, written down in this
  file independently of the artefact;
* the gross BEFORE costs is recomputed as ``(exit_mid - entry_mid) * qty`` per
  trade and summed, and matched against the declared figure;
* the cost split is checked with the identity
  ``gross - price_costs - fees == net`` per trade and per run;
* the refusal funnel is counted from ``ABLATION_REFUSALS.csv``, not trusted from
  the JSON;
* the two arms must differ ONLY in the trend filter: the ablation may not keep a
  single ``trend_filter_fail`` refusal, both arms must evaluate the same bars with
  the same warm-up, and the setups CONSIDERED (signals + candidate refusals) must
  match exactly, so the arms differ in how each setup is resolved rather than in
  which setups exist; the declared parameters must be identical apart from the
  removed switch and the frozen pre-registered block must not carry it;
* the benchmark label of every trade is re-derived from ``MARKET_CONTEXT.csv``
  (the last benchmark day closed at or before the decision), so the market the
  ablation was measured in cannot be relabelled after the fact;
* the verdict is recomputed from the declared gross, net and trade counts using
  the pre-registered rule, so a verdict edited after the fact cannot survive.

``--self-test`` mutates a copy of the artefacts and asserts every check is
breakable; a check that cannot be broken is reported as a failure, not as a pass.
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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# What the ablation is allowed to be, written here rather than read from it
# --------------------------------------------------------------------------- #

#: Pre-registered intraday DEV window (WP-EDGE-01 splits / ADR-0027), stated
#: independently: the artefact does not get to choose its own window.
PREREGISTERED_DEV = (int(datetime(2024, 10, 1, tzinfo=UTC).timestamp() * 1000),
                     int(datetime(2025, 6, 30, tzinfo=UTC).timestamp() * 1000))

#: The intraday clock, so a decision taken at the close of the last in-window
#: bar is legitimate rather than an out-of-window read.
BAR_MS = 15 * 60 * 1000

#: The rule frozen before the ablation ran.
EXPECTED_DECISION_RULE: dict[str, Any] = {
    "min_dev_trades": 30,
    "gross_positive_usdt": 0.0,
}

#: Every refusal reason the 1h filter can be responsible for. The ablation must
#: show none of them.
FILTER_REASONS = ("trend_filter_fail",)

REQUIRED = (
    "ABLATION.json",
    "ABLATION.md",
    "ABLATION_TRADES.csv",
    "ABLATION_REFUSALS.csv",
    "ABLATION_SIGNALS.csv",
    "MARKET_CONTEXT.csv",
)

TOL = 0.05


class Fatal(Exception):
    """An artefact that cannot even be read: reported, never skipped."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Dataset:
    def __init__(self, root: Path) -> None:
        self.root = root
        for name in REQUIRED:
            if not (root / name).exists():
                raise Fatal(f"missing artefact {name} under {root}")
        self.payload = json.loads((root / "ABLATION.json").read_text(encoding="utf-8"))
        self.trades = _read_csv(root / "ABLATION_TRADES.csv")
        self.refusals = _read_csv(root / "ABLATION_REFUSALS.csv")
        self.signals = _read_csv(root / "ABLATION_SIGNALS.csv")
        self.market_rows = _read_csv(root / "MARKET_CONTEXT.csv")

    # -- helpers ---------------------------------------------------------- #
    def arm(self, role: str) -> dict[str, Any]:
        arms = self.payload.get("arms") or {}
        if role not in arms:
            raise Fatal(f"ABLATION.json has no '{role}' arm")
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


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def check_artifacts_present(ds: Dataset) -> tuple[bool, str]:
    inventory = ds.payload.get("artifacts") or {}
    if not inventory:
        return False, "ABLATION.json carries no artefact inventory"
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
    ablation = ds.payload.get("ablation") or {}
    start, end = PREREGISTERED_DEV
    problems: list[str] = []
    if int(ablation.get("window_start_ms") or 0) != start:
        problems.append(f"declared window starts {ablation.get('window_start_ms')}, DEV starts {start}")
    if int(ablation.get("window_end_ms") or 0) != end:
        problems.append(f"declared window ends {ablation.get('window_end_ms')}, DEV ends {end}")
    if str(ablation.get("window")) != "DEV":
        problems.append(f"declared window name {ablation.get('window')!r} is not DEV")
    if ablation.get("split") != "intraday":
        problems.append(f"declared split {ablation.get('split')!r} is not the intraday corpus")
    if list(ablation.get("assets") or []) == []:
        problems.append("no assets declared")

    # Decisions are taken at the CLOSE of an in-window bar, so a decision instant
    # may be up to one bar beyond the window end; nothing may be priced later.
    out: list[str] = []
    for row in ds.trades:
        decision = int(row["decision_ts"])
        if not (start <= decision <= end + BAR_MS):
            out.append(f"trade decision_ts {decision} outside DEV")
        for key in ("entry_ts", "exit_ts"):
            value = int(row[key])
            if not (start <= value <= end):
                out.append(f"trade {key} {value} outside DEV")
    for table, name in ((ds.refusals, "refusal"), (ds.signals, "signal")):
        for row in table:
            decision = int(row["decision_ts"])
            if not (start <= decision <= end + BAR_MS):
                out.append(f"{name} decision_ts {decision} outside DEV")
    if out:
        problems.extend(out[:5] + ([f"...and {len(out) - 5} more"] if len(out) > 5 else []))
    return (not problems), "; ".join(problems) or (
        f"every one of {len(ds.trades)} trades, {len(ds.refusals)} refusals and "
        f"{len(ds.signals)} signals sits inside the DEV window"
    )


def check_gross_before_costs_recomputed(ds: Dataset) -> tuple[bool, str]:
    """The headline number: gross mid-to-mid, recomputed from the trade rows."""

    problems: list[str] = []
    detail: list[str] = []
    for role in ("base", "ablation"):
        rows = ds.rows(ds.trades, role)
        recomputed = sum((_f(r, "exit_mid") - _f(r, "entry_mid")) * _f(r, "qty") for r in rows)
        declared = float(ds.arm(role).get("gross_usdt") or 0.0)
        detail.append(f"{role}: gross {declared:,.2f} vs recomputed {recomputed:,.2f}")
        if abs(recomputed - declared) > TOL:
            problems.append(
                f"{role}: declared gross {declared:,.2f} != recomputed {recomputed:,.2f}"
            )
        if len(rows) != int(ds.arm(role).get("trades") or 0):
            problems.append(
                f"{role}: {len(rows)} trade rows but {ds.arm(role).get('trades')} declared"
            )
    return (not problems), "; ".join(problems) or " | ".join(detail)


def check_cost_split_identity(ds: Dataset) -> tuple[bool, str]:
    """gross - price_costs - fees must equal net, per trade and per run."""

    problems: list[str] = []
    for role in ("base", "ablation"):
        rows = ds.rows(ds.trades, role)
        for row in rows:
            gross = _f(row, "gross")
            fees = _f(row, "fees")
            price = _f(row, "price_costs")
            net = _f(row, "net")
            recomputed = (gross - price - fees)
            if abs(recomputed - net) > TOL:
                problems.append(
                    f"{role}: gross {gross:.4f} - costs {price:.4f} - fees {fees:.4f} "
                    f"= {recomputed:.4f} != net {net:.4f}"
                )
            fills = (_f(row, "exit_fill") - _f(row, "entry_fill")) * _f(row, "qty") - fees
            if abs(fills - net) > TOL:
                problems.append(
                    f"{role}: fills x qty - fees = {fills:.4f} != net {net:.4f}"
                )
            if len(problems) > 5:
                break
        declared_fees = float(ds.arm(role).get("fees_usdt") or 0.0)
        declared_price = float(ds.arm(role).get("price_costs_usdt") or 0.0)
        declared_net = float(ds.arm(role).get("net_usdt") or 0.0)
        if abs(sum(_f(r, "fees") for r in rows) - declared_fees) > TOL:
            problems.append(f"{role}: declared fees {declared_fees:,.2f} != the sum of the rows")
        if abs(sum(_f(r, "price_costs") for r in rows) - declared_price) > TOL:
            problems.append(
                f"{role}: declared price cost {declared_price:,.2f} != the sum of the rows"
            )
        if abs(sum(_f(r, "net") for r in rows) - declared_net) > TOL:
            problems.append(f"{role}: declared net {declared_net:,.2f} != the sum of the rows")
    return (not problems), "; ".join(problems) or "cost split reconciles on both arms"


def check_funnel_arithmetic(ds: Dataset) -> tuple[bool, str]:
    """The funnel is a count of the raw refusal rows, not a declared total."""

    problems: list[str] = []
    summary: list[str] = []
    for role in ("base", "ablation"):
        counted = ds.funnel_from_rows(role)
        declared = {str(k): int(v) for k, v in (ds.arm(role).get("refusals") or {}).items()}
        summary.append(f"{role}: {sum(counted.values())} refusals over {len(counted)} reasons")
        if counted != declared:
            only_file = {k: v for k, v in counted.items() if declared.get(k) != v}
            only_json = {k: v for k, v in declared.items() if counted.get(k) != v}
            problems.append(
                f"{role}: funnel in the file and in the JSON disagree "
                f"(file-only {only_file}, json-only {only_json})"
            )
    return (not problems), "; ".join(problems) or " | ".join(summary)


def check_signals_arithmetic(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    detail: list[str] = []
    for role in ("base", "ablation"):
        arm = ds.arm(role)
        rows = ds.rows(ds.signals, role)
        if len(rows) != int(arm.get("signal_count") or 0):
            problems.append(
                f"{role}: {len(rows)} signal rows but {arm.get('signal_count')} declared"
            )
        bars = int(arm.get("bars_evaluated") or 0)
        candidate_refusals = sum(
            count
            for key, count in ds.funnel_from_rows(role).items()
            if key.startswith("candidate:")
        )
        accounted = len(rows) + candidate_refusals
        detail.append(f"{role}: evaluated {bars}, signals {len(rows)}, candidate refusals {candidate_refusals}")
        if bars and accounted > bars:
            problems.append(
                f"{role}: signals + candidate refusals ({accounted}) exceed the "
                f"{bars} bars the candidate evaluated"
            )
    return (not problems), "; ".join(problems) or " | ".join(detail)


def check_ablation_isolation(ds: Dataset) -> tuple[bool, str]:
    """Only the 1h gate may differ, and the two arms must resolve the SAME setups.

    An earlier version of this check asserted that every non-filter refusal could
    only grow, on the reasoning that removing a gate lets more setups through. That
    is false, and the artefacts proved it: ``level_already_traded`` is candidate
    state, so the ablation marks more levels as traded and can refuse a setup
    EARLIER than the gate it removed — ``volume_filter_fail`` fell by 89 for
    exactly that reason. What is true, and is checked instead:

    * the gate itself is gone (0 refusals) while the base used it;
    * both arms evaluated the same bars with the same warm-up (features do not
      depend on the gate);
    * each evaluated bar yields exactly one outcome, so the number of setups
      CONSIDERED (signals + candidate refusals) must be identical across arms:
      the arms differ in how each setup is resolved, not in which setups exist.
    """

    problems: list[str] = []
    base_params = dict(ds.arm("base").get("params") or {})
    ab_params = dict(ds.arm("ablation").get("params") or {})
    removed = {"use_trend_filter"}
    if set(ab_params) - set(base_params) != removed:
        problems.append(
            f"the ablation's extra parameters are {sorted(set(ab_params) - set(base_params))}, "
            f"expected exactly {sorted(removed)}"
        )
    stripped = {k: v for k, v in ab_params.items() if k not in removed}
    if stripped != base_params:
        problems.append("the two arms differ in more than the trend filter")
    if ds.arm("base").get("use_trend_filter") is not True:
        problems.append("the base arm does not declare the trend filter as enabled")
    if ds.arm("ablation").get("use_trend_filter") is not False:
        problems.append("the ablation arm does not declare the trend filter as removed")
    frozen = ds.payload.get("ablation", {}).get("frozen_params") or {}
    if any(key in frozen for key in removed):
        problems.append("the frozen pre-registered parameters were edited to hold the switch")

    base_funnel = ds.funnel_from_rows("base")
    ab_funnel = ds.funnel_from_rows("ablation")
    for reason in FILTER_REASONS:
        key = f"candidate:{reason}"
        kept = ab_funnel.get(key, 0)
        if kept:
            problems.append(
                f"the ablation still refused {kept} setups with {key}: the gate is not removed"
            )
        if base_funnel.get(key, 0) <= 0:
            problems.append(
                f"the base arm never refused with {key}: there is no filter to ablate"
            )

    base = ds.arm("base")
    ab = ds.arm("ablation")
    if int(base.get("bars_evaluated") or 0) != int(ab.get("bars_evaluated") or 0):
        problems.append(
            f"the arms evaluated different bars ({base.get('bars_evaluated')} vs "
            f"{ab.get('bars_evaluated')}): the corpus or the warm-up is not shared"
        )
    if int(base.get("warmup_bars") or 0) != int(ab.get("warmup_bars") or 0):
        problems.append(
            f"the arms warmed up on different bars ({base.get('warmup_bars')} vs "
            f"{ab.get('warmup_bars')})"
        )
    considered = {
        "base": int(base.get("signal_count") or 0)
        + sum(v for k, v in base_funnel.items() if k.startswith("candidate:")),
        "ablation": int(ab.get("signal_count") or 0)
        + sum(v for k, v in ab_funnel.items() if k.startswith("candidate:")),
    }
    if considered["base"] != considered["ablation"]:
        problems.append(
            f"the arms considered {considered['base']} vs {considered['ablation']} setups: "
            f"removing a gate must re-route setups, not create or destroy them"
        )
    return (not problems), "; ".join(problems) or (
        f"{considered['base']} setups considered in both arms, resolved differently: "
        f"{base.get('signal_count')} signals / "
        f"{sum(v for k, v in base_funnel.items() if k.startswith('candidate:'))} candidate refusals "
        f"(base) vs {ab.get('signal_count')} / "
        f"{sum(v for k, v in ab_funnel.items() if k.startswith('candidate:'))} (ablation); "
        f"filter refusals {base_funnel.get('candidate:trend_filter_fail', 0)} -> "
        f"{ab_funnel.get('candidate:trend_filter_fail', 0)}"
    )


def check_market_context_attribution(ds: Dataset) -> tuple[bool, str]:
    """Each trade's benchmark label must be the one readable at its decision.

    The label is looked up here from ``MARKET_CONTEXT.csv`` alone (the last
    benchmark day whose close is at or before ``decision_ts``), so a label read
    from a later day — a look-ahead — cannot survive, and neither can a label
    invented for a day the benchmark never closed.
    """

    rows = ds.market_rows
    if not rows:
        return False, "MARKET_CONTEXT.csv is empty: every trade cites a benchmark label"
    declared = ds.payload.get("market_context") or {}
    if not str(declared.get("rule") or ""):
        return False, "ABLATION.json does not state the market-context rule"
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
            f"ABLATION.json declares {declared_days} benchmark days, the file has {len(days)}"
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


def _recompute_verdict(base: dict[str, Any], ablation: dict[str, Any]) -> str:
    min_trades = int(EXPECTED_DECISION_RULE["min_dev_trades"])
    threshold = float(EXPECTED_DECISION_RULE["gross_positive_usdt"])
    base_trades = int(base.get("trades") or 0)
    ab_trades = int(ablation.get("trades") or 0)
    ab_gross = float(ablation.get("gross_usdt") or 0.0)
    ab_net = float(ablation.get("net_usdt") or 0.0)
    if base_trades < min_trades or ab_trades < min_trades:
        return "INCONCLUSIVE"
    if ab_gross <= threshold:
        return "BREAKOUT_IS_THE_CAUSE"
    if ab_net <= 0:
        return "FILTER_SUPPRESSED_A_PRECOST_EDGE"
    return "FILTER_HARMS_EDGE"


def check_decision_rule_frozen(ds: Dataset) -> tuple[bool, str]:
    declared = (ds.payload.get("verdict") or {}).get("rule") or {}
    problems: list[str] = []
    for key, expected in EXPECTED_DECISION_RULE.items():
        if declared.get(key) != expected:
            problems.append(f"rule.{key} is {declared.get(key)!r}, frozen value is {expected!r}")
    if not declared.get("rule"):
        problems.append("the verdict does not quote the rule it was applied with")
    meaning = declared.get("meaning") or {}
    for label in (
        "BREAKOUT_IS_THE_CAUSE",
        "FILTER_SUPPRESSED_A_PRECOST_EDGE",
        "FILTER_HARMS_EDGE",
        "INCONCLUSIVE",
    ):
        if label not in meaning:
            problems.append(f"the rule does not state what {label} means")
    return (not problems), "; ".join(problems) or (
        "the decision rule matches the pre-registered constants "
        f"({EXPECTED_DECISION_RULE})"
    )


def check_verdict_recomputed(ds: Dataset) -> tuple[bool, str]:
    verdict = ds.payload.get("verdict") or {}
    declared = str(verdict.get("verdict"))
    recomputed = _recompute_verdict(ds.arm("base"), ds.arm("ablation"))
    allowed = {
        "BREAKOUT_IS_THE_CAUSE",
        "FILTER_SUPPRESSED_A_PRECOST_EDGE",
        "FILTER_HARMS_EDGE",
        "INCONCLUSIVE",
    }
    if declared not in allowed:
        return False, f"verdict {declared!r} is not one of {sorted(allowed)}"
    if declared != recomputed:
        return False, f"declared {declared} but the rule on the published numbers gives {recomputed}"
    base = ds.arm("base")
    ab = ds.arm("ablation")
    return True, (
        f"{declared} recomputed: base gross {float(base.get('gross_usdt') or 0):,.2f} / "
        f"net {float(base.get('net_usdt') or 0):,.2f}; ablation gross "
        f"{float(ab.get('gross_usdt') or 0):,.2f} / net {float(ab.get('net_usdt') or 0):,.2f}"
    )


CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("WINDOW_IS_PREREGISTERED_DEV", check_window_is_preregistered_dev),
    ("GROSS_BEFORE_COSTS_RECOMPUTED", check_gross_before_costs_recomputed),
    ("COST_SPLIT_IDENTITY", check_cost_split_identity),
    ("FUNNEL_ARITHMETIC", check_funnel_arithmetic),
    ("SIGNALS_ARITHMETIC", check_signals_arithmetic),
    ("ABLATION_ISOLATION", check_ablation_isolation),
    ("MARKET_CONTEXT_ATTRIBUTION", check_market_context_attribution),
    ("DECISION_RULE_FROZEN", check_decision_rule_frozen),
    ("VERDICT_RECOMPUTED", check_verdict_recomputed),
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _store_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mutate_gross(root: Path) -> None:
    """Report a flattering gross the trade rows do not support."""
    path = root / "ABLATION.json"
    payload = _load_json(path)
    gross = float(payload["arms"]["ablation"]["gross_usdt"])
    payload["arms"]["ablation"]["gross_usdt"] = round(gross + 40.0, 4)
    payload["arms"]["ablation"]["net_usdt"] = round(
        float(payload["arms"]["ablation"]["net_usdt"]) + 40.0, 4
    )
    _store_json(path, payload)


def _mutate_fees(root: Path) -> None:
    path = root / "ABLATION.json"
    payload = _load_json(path)
    payload["arms"]["base"]["fees_usdt"] = round(
        float(payload["arms"]["base"]["fees_usdt"]) + 5.0, 4
    )
    _store_json(path, payload)


def _mutate_window_to_val(root: Path) -> None:
    """Move the declared window onto VAL: the ablation may not be scored there."""
    path = root / "ABLATION.json"
    payload = _load_json(path)
    payload["ablation"]["window_start_ms"] = int(
        datetime(2025, 7, 1, tzinfo=UTC).timestamp() * 1000
    )
    _store_json(path, payload)


def _mutate_inject_filter_refusal(root: Path) -> None:
    """Put a trend-filter refusal back into the ablation: the gate is not removed."""
    path = root / "ABLATION_REFUSALS.csv"
    rows = _read_csv(path)
    sample = next(row for row in rows if row["run"] == "ablation")
    injected = dict(sample)
    injected["reason"] = "trend_filter_fail"
    rows.insert(0, injected)
    _rewrite_csv(path, rows)


def _mutate_drop_refusals(root: Path) -> None:
    """Publish a funnel total the refusal rows no longer support."""
    path = root / "ABLATION_REFUSALS.csv"
    rows = _read_csv(path)
    base_rows = [row for row in rows if row["run"] != "ablation"]
    ab_rows = [row for row in rows if row["run"] == "ablation"]
    kept = ab_rows[: len(ab_rows) // 2] if len(ab_rows) > 1 else []
    _rewrite_csv(path, base_rows + kept)


def _mutate_add_signal(root: Path) -> None:
    path = root / "ABLATION_SIGNALS.csv"
    rows = _read_csv(path)
    sample = next(row for row in rows if row["run"] == "ablation")
    extra = dict(sample)
    extra["decision_ts"] = str(int(sample["decision_ts"]) + 1)
    rows.append(extra)
    _rewrite_csv(path, rows)


def _mutate_flip_verdict(root: Path) -> None:
    path = root / "ABLATION.json"
    payload = _load_json(path)
    payload["verdict"]["verdict"] = "FILTER_HARMS_EDGE"
    _store_json(path, payload)


def _mutate_rule_threshold(root: Path) -> None:
    """Relax the frozen rule after the fact."""
    path = root / "ABLATION.json"
    payload = _load_json(path)
    payload["verdict"]["rule"]["min_dev_trades"] = 1
    _store_json(path, payload)


def _mutate_market_context(root: Path) -> None:
    """Re-label every trade with a neighbouring regime: the benchmark did not say that."""
    path = root / "ABLATION_TRADES.csv"
    rows = _read_csv(path)
    rotation = {"BULL": "BEAR", "BEAR": "SIDEWAYS", "SIDEWAYS": "BULL", "UNDEFINED": "BULL"}
    for row in rows:
        row["market_context"] = rotation.get(row["market_context"], "BULL")
    _rewrite_csv(path, rows)


def _mutate_out_of_window_trade(root: Path) -> None:
    path = root / "ABLATION_TRADES.csv"
    rows = _read_csv(path)
    sample = next(row for row in rows if row["run"] == "ablation")
    extra = dict(sample)
    out = int(datetime(2026, 2, 1, tzinfo=UTC).timestamp() * 1000)
    extra["decision_ts"] = str(out)
    extra["entry_ts"] = str(out + BAR_MS)
    extra["exit_ts"] = str(out + 2 * BAR_MS)
    rows.append(extra)
    _rewrite_csv(path, rows)


MUTATIONS: tuple[tuple[str, str, Callable[[Path], None]], ...] = (
    ("M1_flattered_gross", "GROSS_BEFORE_COSTS_RECOMPUTED", _mutate_gross),
    ("M2_tampered_fees", "COST_SPLIT_IDENTITY", _mutate_fees),
    ("M3_window_moved_to_val", "WINDOW_IS_PREREGISTERED_DEV", _mutate_window_to_val),
    ("M4_filter_refusal_reinstated", "ABLATION_ISOLATION", _mutate_inject_filter_refusal),
    ("M5_refusals_trimmed", "FUNNEL_ARITHMETIC", _mutate_drop_refusals),
    ("M6_extra_signal", "SIGNALS_ARITHMETIC", _mutate_add_signal),
    ("M7_flipped_verdict", "VERDICT_RECOMPUTED", _mutate_flip_verdict),
    ("M8_relaxed_rule", "DECISION_RULE_FROZEN", _mutate_rule_threshold),
    ("M9_out_of_window_trade", "WINDOW_IS_PREREGISTERED_DEV", _mutate_out_of_window_trade),
    ("M10_relabelled_market_context", "MARKET_CONTEXT_ATTRIBUTION", _mutate_market_context),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="reports/edge-recovery/WP-EDGE-01/ablation-h1")
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
        print(f"[{'PASS' if entry['ok'] else 'FAIL'}] {entry['check']:<32} {entry['detail']}")
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
                f"[{status}] {item['mutation']:<30} -> {item['expected_check']} "
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
