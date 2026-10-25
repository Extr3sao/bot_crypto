"""Independent verification of the WP-EDGE-01 H5 risk-budget ablation.

    python scripts/edge01_risk_ablation_verify.py [--dir reports/edge-recovery/WP-EDGE-01/risk-budget-h5]
                                                  [--self-test] [--json-out FILE]

This process imports NOTHING from ``trading_bot``: it reads the published
artefacts and rebuilds the numbers itself. What it insists on:

1. ``ARTIFACTS_PRESENT``            every artefact matches the digest the run published
2. ``WINDOW_IS_PREREGISTERED_DEV``  every trade/refusal/signal sits in DEV, and only DEV
3. ``BUDGET_IS_ONE_FIELD_APART``    the two budgets differ in EXACTLY one field, the one
                                    the experiment names, and the base is the runtime's
                                    config read verbatim (checked against its own sha256)
4. ``HALT_IS_INERT_IN_VARIANT``     the base arm used the halt, the variant cannot: 0 refusals
5. ``CANDIDATE_LAYER_IDENTICAL``    the risk budget cannot change what the candidate prints:
                                    same signals and same candidate-level refusals in both arms
6. ``GROSS_BEFORE_COSTS_RECOMPUTED`` gross mid-to-mid recomputed from the trade rows
7. ``COST_SPLIT_IDENTITY``          gross - price_costs - fees == net, per trade and per arm
8. ``FUNNEL_ARITHMETIC``            the funnel is a count of the raw refusal rows
9. ``FUNNEL_SPLIT_BY_LAYER``        risk-layer refusals may move, candidate-layer ones may not
10. ``MARGINAL_ARITHMETIC``         the marginal trades/gross/net are the difference of the arms
11. ``MARKET_CONTEXT_ATTRIBUTION`` every trade's benchmark label is the one readable at its decision
12. ``DECISION_RULE_FROZEN``        the rule matches the constants frozen before the run
13. ``VERDICT_RECOMPUTED``          the published verdict is what the rule gives on these numbers

``--self-test`` mutates a copy of the artefacts and requires the matching check to
fail; a check nobody can break is reported as a failure, not as a pass.
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
# What the run is allowed to be, written here rather than read from it
# --------------------------------------------------------------------------- #

#: Pre-registered intraday DEV window (WP-EDGE-01 splits / ADR-0027).
PREREGISTERED_DEV = (
    int(datetime(2024, 10, 1, tzinfo=UTC).timestamp() * 1000),
    int(datetime(2025, 6, 30, tzinfo=UTC).timestamp() * 1000),
)
BAR_MS = 15 * 60 * 1000

#: The runtime's own drawdown halt, from ``config/risk.yaml`` (max_total_drawdown_pct).
#: Stated here so a base arm that quietly relaxed it is not "the runtime's budget".
RUNTIME_HALT_PCT = 5.0
#: A halt at or above this can never fire: 100% of peak equity is unreachable.
HALT_INERT_FLOOR_PCT = 100.0

EXPECTED_DECISION_RULE: dict[str, Any] = {
    "min_extra_trades": 20,
    "marginal_net_positive_usdt": 0.0,
}

FILTER_REASONS = ("risk_drawdown_halt",)

REQUIRED = (
    "RISK_ABLATION.json",
    "RISK_ABLATION.md",
    "RISK_TRADES.csv",
    "RISK_REFUSALS.csv",
    "RISK_SIGNALS.csv",
    "MARKET_CONTEXT.csv",
)

TOL = 0.05
ARMS = ("base", "variant")


class Fatal(Exception):
    """An artefact that cannot even be read: reported, never skipped."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Dataset:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = Path(__file__).resolve().parents[1]
        for name in REQUIRED:
            if not (root / name).exists():
                raise Fatal(f"missing artefact {name} under {root}")
        self.payload = json.loads((root / "RISK_ABLATION.json").read_text(encoding="utf-8"))
        self.trades = _read_csv(root / "RISK_TRADES.csv")
        self.refusals = _read_csv(root / "RISK_REFUSALS.csv")
        self.signals = _read_csv(root / "RISK_SIGNALS.csv")
        self.market_rows = _read_csv(root / "MARKET_CONTEXT.csv")

    def arm(self, role: str) -> dict[str, Any]:
        arms = self.payload.get("arms") or {}
        if role not in arms:
            raise Fatal(f"RISK_ABLATION.json has no '{role}' arm")
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


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def check_artifacts_present(ds: Dataset) -> tuple[bool, str]:
    inventory = ds.payload.get("artifacts") or {}
    if not inventory:
        return False, "RISK_ABLATION.json carries no artefact inventory"
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
    abl = ds.payload.get("risk_ablation") or {}
    start, end = PREREGISTERED_DEV
    problems: list[str] = []
    if int(abl.get("window_start_ms") or 0) != start:
        problems.append(f"declared window starts {abl.get('window_start_ms')}, DEV starts {start}")
    if int(abl.get("window_end_ms") or 0) != end:
        problems.append(f"declared window ends {abl.get('window_end_ms')}, DEV ends {end}")
    if str(abl.get("window")) != "DEV":
        problems.append(f"declared window name {abl.get('window')!r} is not DEV")
    if abl.get("split") != "intraday":
        problems.append(f"declared split {abl.get('split')!r} is not the intraday corpus")

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


def check_budget_is_one_field_apart(ds: Dataset) -> tuple[bool, str]:
    """The variant must be the runtime budget minus ONE rule, not a re-tuned budget."""

    abl = ds.payload.get("risk_ablation") or {}
    base = dict(ds.arm("base").get("policy") or {})
    variant = dict(ds.arm("variant").get("policy") or {})
    problems: list[str] = []
    if not base or not variant:
        return False, "one of the arms publishes no risk policy"
    if set(base) != set(variant):
        problems.append("the two budgets expose different fields")
    changed = sorted(k for k in base if base.get(k) != variant.get(k))
    named = str(abl.get("changed_field"))
    if changed != [named]:
        problems.append(f"the budgets differ in {changed}, the experiment declares only [{named!r}]")
    if float(base.get("drawdown_halt_pct", -1)) != RUNTIME_HALT_PCT:
        problems.append(
            f"the base drawdown halt is {base.get('drawdown_halt_pct')}, the runtime config says "
            f"{RUNTIME_HALT_PCT}: the base arm is not the runtime's budget"
        )
    if float(variant.get("drawdown_halt_pct", 0)) < HALT_INERT_FLOOR_PCT:
        problems.append(
            f"the variant halt is {variant.get('drawdown_halt_pct')}, below the inert floor "
            f"{HALT_INERT_FLOOR_PCT}: it can still fire"
        )
    declared = float(abl.get("inert_halt_pct") or 0)
    if declared != float(variant.get("drawdown_halt_pct") or -1):
        problems.append(
            f"the declared inert value {declared} is not the value the variant ran with"
        )

    # The base budget claims to be config/risk.yaml read verbatim: check the file.
    rel = str(abl.get("risk_config_path") or "")
    declared_sha = str(abl.get("risk_config_sha256") or "")
    if not rel or not declared_sha:
        problems.append("the run does not name the risk config it read or its digest")
    else:
        path = ds.repo / rel
        if not path.exists():
            problems.append(f"declared risk config {rel} is not in the repo")
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != declared_sha:
                problems.append(
                    f"{rel} digests to {actual[:12]}, the run declares {declared_sha[:12]}: the "
                    f"base arm does not come from the config it names"
                )
    return (not problems), "; ".join(problems) or (
        f"one field apart ({named}: {base.get(named)} -> {variant.get(named)}) and the base "
        f"matches {rel}"
    )


def check_halt_is_inert_in_variant(ds: Dataset) -> tuple[bool, str]:
    """The intervention must have happened, and must be visible in the raw rows."""

    problems: list[str] = []
    base_funnel = ds.funnel_from_rows("base")
    variant_funnel = ds.funnel_from_rows("variant")
    detail: list[str] = []
    for reason in FILTER_REASONS:
        key = f"risk:{reason}"
        b = base_funnel.get(key, 0)
        v = variant_funnel.get(key, 0)
        detail.append(f"{key} {b} -> {v}")
        if b <= 0:
            problems.append(f"the base arm never refused with {key}: there is no halt to ablate")
        if v != 0:
            problems.append(f"the variant still refused {v} entries with {key}: the halt is not inert")
    for role in ARMS:
        declared = int(ds.arm(role).get("halt_refusals") or 0)
        counted = sum(ds.funnel_from_rows(role).get(f"risk:{r}", 0) for r in FILTER_REASONS)
        if declared != counted:
            problems.append(f"{role}: declares {declared} halt refusals, the rows carry {counted}")
    return (not problems), "; ".join(problems) or " | ".join(detail)


def check_candidate_layer_identical(ds: Dataset) -> tuple[bool, str]:
    """A risk budget cannot change what the candidate prints.

    The simulator asks the candidate for a setup on every bar regardless of open
    positions or limits, so the signals and the candidate-level refusals must be the
    same in both arms. If they are not, the comparison is measuring something else
    (a different corpus, a different candidate, a different window).
    """

    problems: list[str] = []
    for role in ARMS:
        arm = ds.arm(role)
        rows = ds.rows(ds.signals, role)
        if len(rows) != int(arm.get("signal_count") or 0):
            problems.append(f"{role}: {len(rows)} signal rows but {arm.get('signal_count')} declared")
    signatures = {}
    for role in ARMS:
        signals = ds.rows(ds.signals, role)
        signals = sorted(
            (r["symbol"], int(r["bar_index"]), int(r["decision_ts"]), r.get("regime")) for r in signals
        )
        signatures[role] = signals
        candidate_funnel = {
            key: count
            for key, count in ds.funnel_from_rows(role).items()
            if key.startswith("candidate:")
        }
        signatures[f"{role}:funnel"] = sorted(candidate_funnel.items())
        if int(arm.get("bars_evaluated") or 0) != int(
            ds.arm(ARMS[0]).get("bars_evaluated") or 0
        ):
            problems.append(
                f"{role} evaluated {arm.get('bars_evaluated')} bars against "
                f"{ds.arm(ARMS[0]).get('bars_evaluated')} in the base arm"
            )
    if signatures["base"] != signatures["variant"]:
        problems.append("the two arms did not print the same signals")
    if signatures["base:funnel"] != signatures["variant:funnel"]:
        problems.append("the candidate-level refusals differ between the arms")
    return (not problems), "; ".join(p for p in problems if p) or (
        f"{len(signatures['base'])} identical signals and "
        f"{len(signatures['base:funnel'])} identical candidate-level refusal counts in both arms"
    )


def check_gross_before_costs_recomputed(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    detail: list[str] = []
    for role in ARMS:
        rows = ds.rows(ds.trades, role)
        recomputed = sum((_f(r, "exit_mid") - _f(r, "entry_mid")) * _f(r, "qty") for r in rows)
        declared = float(ds.arm(role).get("gross_usdt") or 0.0)
        detail.append(f"{role}: gross {declared:,.2f} vs recomputed {recomputed:,.2f}")
        if abs(recomputed - declared) > _tol(rows):
            problems.append(f"{role}: declared gross {declared:,.2f} != recomputed {recomputed:,.2f}")
        if len(rows) != int(ds.arm(role).get("trades") or 0):
            problems.append(
                f"{role}: {len(rows)} trade rows but {ds.arm(role).get('trades')} declared"
            )
    return (not problems), "; ".join(problems) or " | ".join(detail)


def check_cost_split_identity(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    for role in ARMS:
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
        for name, column in (("fees_usdt", "fees"), ("price_costs_usdt", "price_costs"), ("net_usdt", "net")):
            declared = float(ds.arm(role).get(name) or 0.0)
            counted = sum(_f(r, column) for r in rows)
            if abs(counted - declared) > tol:
                problems.append(f"{role}: declared {name} {declared:,.2f} != the sum of the rows")
    return (not problems), "; ".join(problems) or "cost split reconciles on both arms"


def check_funnel_arithmetic(ds: Dataset) -> tuple[bool, str]:
    problems: list[str] = []
    summary: list[str] = []
    for role in ARMS:
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


def check_funnel_split_by_layer(ds: Dataset) -> tuple[bool, str]:
    """Only risk-layer refusals may move; the candidate layer is fixed.

    ``level_already_traded`` and the other candidate reasons are decided from bars
    alone, so a single one of them changing means the arms are not comparable. The
    risk layer is exactly where the intervention lives, and it may move in both
    directions: a freed entry becomes a position, which changes the drawdown path
    and therefore the cooldown history.
    """

    base = ds.funnel_from_rows("base")
    variant = ds.funnel_from_rows("variant")
    problems: list[str] = []
    moved_candidate = []
    for key in sorted(set(base) | set(variant)):
        if key.startswith("candidate:") and base.get(key, 0) != variant.get(key, 0):
            moved_candidate.append(f"{key} {base.get(key, 0)} -> {variant.get(key, 0)}")
    if moved_candidate:
        problems.append("candidate-layer refusals moved: " + ", ".join(moved_candidate))
    risk_moved = [
        f"{key} {base.get(key, 0)} -> {variant.get(key, 0)}"
        for key in sorted(set(base) | set(variant))
        if key.startswith("risk:") and base.get(key, 0) != variant.get(key, 0)
    ]
    return (not problems), "; ".join(problems) or (
        "candidate layer frozen; risk layer moved: " + (", ".join(risk_moved) or "nothing")
    )


def check_marginal_arithmetic(ds: Dataset) -> tuple[bool, str]:
    """The marginal numbers must be the difference of the two arms, recomputed."""

    verdict = ds.payload.get("verdict") or {}
    problems: list[str] = []
    counts = {}
    nets = {}
    grosses = {}
    for role in ARMS:
        rows = ds.rows(ds.trades, role)
        counts[role] = len(rows)
        nets[role] = sum(_f(r, "net") for r in rows)
        grosses[role] = sum((_f(r, "exit_mid") - _f(r, "entry_mid")) * _f(r, "qty") for r in rows)
    expected = {
        "extra_trades": counts["variant"] - counts["base"],
        "marginal_gross_usdt": grosses["variant"] - grosses["base"],
        "marginal_net_usdt": nets["variant"] - nets["base"],
    }
    tol = _tol(ds.trades)
    for key, value in expected.items():
        declared = verdict.get(key)
        if declared is None:
            problems.append(f"the verdict carries no {key}")
        elif abs(float(declared) - value) > (tol if key != "extra_trades" else 0):
            problems.append(f"{key}: declared {declared} != recomputed {round(value, 4)}")
    extra = expected["extra_trades"]
    expectancy = verdict.get("marginal_expectancy_usdt")
    if extra:
        if expectancy is None or abs(float(expectancy) - expected["marginal_net_usdt"] / extra) > tol:
            problems.append(
                f"marginal expectancy {expectancy} != {round(expected['marginal_net_usdt'] / extra, 4)}"
            )
    elif expectancy is not None:
        problems.append("a marginal expectancy is declared with no extra trades")
    return (not problems), "; ".join(problems) or (
        f"marginal {expected['extra_trades']:+d} trades, {round(expected['marginal_net_usdt'], 2):+} USDT "
        f"net, {round(expected['marginal_gross_usdt'], 2):+} USDT gross"
    )


def check_market_context_attribution(ds: Dataset) -> tuple[bool, str]:
    rows = ds.market_rows
    if not rows:
        return False, "MARKET_CONTEXT.csv is empty: every trade cites a benchmark label"
    declared = ds.payload.get("market_context") or {}
    if not str(declared.get("rule") or ""):
        return False, "RISK_ABLATION.json does not state the market-context rule"
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
            f"RISK_ABLATION.json declares {declared_days} benchmark days, the file has {len(days)}"
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


def _recompute_verdict(base: dict[str, Any], variant: dict[str, Any]) -> str:
    min_extra = int(EXPECTED_DECISION_RULE["min_extra_trades"])
    threshold = float(EXPECTED_DECISION_RULE["marginal_net_positive_usdt"])
    extra = int(variant.get("trades") or 0) - int(base.get("trades") or 0)
    marginal_net = float(variant.get("net_usdt") or 0.0) - float(base.get("net_usdt") or 0.0)
    variant_net = float(variant.get("net_usdt") or 0.0)
    if extra < min_extra:
        return "INCONCLUSIVE"
    if marginal_net <= threshold:
        return "RISK_NOT_BINDING_ON_PROFITABILITY"
    if variant_net <= 0:
        return "RISK_BUDGET_WAS_THE_CONSTRAINT"
    return "FREQUENCY_VIABLE"


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
        "INCONCLUSIVE",
        "RISK_NOT_BINDING_ON_PROFITABILITY",
        "RISK_BUDGET_WAS_THE_CONSTRAINT",
        "FREQUENCY_VIABLE",
    ):
        if label not in meaning:
            problems.append(f"the rule does not state what {label} means")
    return (not problems), "; ".join(problems) or (
        f"the decision rule matches the pre-registered constants ({EXPECTED_DECISION_RULE})"
    )


def check_verdict_recomputed(ds: Dataset) -> tuple[bool, str]:
    verdict = ds.payload.get("verdict") or {}
    declared = str(verdict.get("verdict"))
    recomputed = _recompute_verdict(ds.arm("base"), ds.arm("variant"))
    allowed = {
        "INCONCLUSIVE",
        "RISK_NOT_BINDING_ON_PROFITABILITY",
        "RISK_BUDGET_WAS_THE_CONSTRAINT",
        "FREQUENCY_VIABLE",
    }
    if declared not in allowed:
        return False, f"verdict {declared!r} is not one of {sorted(allowed)}"
    if declared != recomputed:
        return False, f"declared {declared} but the rule on the published numbers gives {recomputed}"
    extra = int(ds.arm("variant").get("trades") or 0) - int(ds.arm("base").get("trades") or 0)
    marginal = float(ds.arm("variant").get("net_usdt") or 0.0) - float(
        ds.arm("base").get("net_usdt") or 0.0
    )
    return True, (
        f"{declared} recomputed: {extra:+d} trades, {marginal:+,.2f} USDT marginal net"
    )


CHECKS: tuple[tuple[str, Callable[[Dataset], tuple[bool, str]]], ...] = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("WINDOW_IS_PREREGISTERED_DEV", check_window_is_preregistered_dev),
    ("BUDGET_IS_ONE_FIELD_APART", check_budget_is_one_field_apart),
    ("HALT_IS_INERT_IN_VARIANT", check_halt_is_inert_in_variant),
    ("CANDIDATE_LAYER_IDENTICAL", check_candidate_layer_identical),
    ("GROSS_BEFORE_COSTS_RECOMPUTED", check_gross_before_costs_recomputed),
    ("COST_SPLIT_IDENTITY", check_cost_split_identity),
    ("FUNNEL_ARITHMETIC", check_funnel_arithmetic),
    ("FUNNEL_SPLIT_BY_LAYER", check_funnel_split_by_layer),
    ("MARGINAL_ARITHMETIC", check_marginal_arithmetic),
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
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["arms"]["variant"]["gross_usdt"] = round(
        float(payload["arms"]["variant"]["gross_usdt"]) + 25.0, 4
    )
    _store_json(path, payload)


def _mutate_fees(root: Path) -> None:
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["arms"]["base"]["fees_usdt"] = round(
        float(payload["arms"]["base"]["fees_usdt"]) + 7.0, 4
    )
    _store_json(path, payload)


def _mutate_window_to_val(root: Path) -> None:
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["risk_ablation"]["window_start_ms"] = int(
        datetime(2025, 7, 1, tzinfo=UTC).timestamp() * 1000
    )
    _store_json(path, payload)


def _mutate_second_field(root: Path) -> None:
    """Re-tune a second limit: the variant stops being one rule apart."""
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["arms"]["variant"]["policy"]["max_trades_per_day"] = 40
    _store_json(path, payload)


def _mutate_relax_base_halt(root: Path) -> None:
    """Quietly relax the BASE halt so it is no longer the runtime's budget."""
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["arms"]["base"]["policy"]["drawdown_halt_pct"] = 20.0
    _store_json(path, payload)


def _mutate_halt_refusal_in_variant(root: Path) -> None:
    path = root / "RISK_REFUSALS.csv"
    rows = _read_csv(path)
    sample = next(row for row in rows if row["run"] == "variant")
    injected = dict(sample)
    injected["source"] = "risk"
    injected["reason"] = "risk_drawdown_halt"
    rows.insert(0, injected)
    _rewrite_csv(path, rows)


def _mutate_signal_in_one_arm(root: Path) -> None:
    """Change a signal in the variant only: the arms are no longer the same candidate."""
    path = root / "RISK_SIGNALS.csv"
    rows = _read_csv(path)
    for row in rows:
        if row["run"] == "variant":
            row["decision_ts"] = str(int(row["decision_ts"]) + 1)
            break
    _rewrite_csv(path, rows)


def _mutate_drop_refusals(root: Path) -> None:
    path = root / "RISK_REFUSALS.csv"
    rows = _read_csv(path)
    base_rows = [row for row in rows if row["run"] == "base"]
    variant_rows = [row for row in rows if row["run"] == "variant"]
    _rewrite_csv(path, base_rows + variant_rows[: len(variant_rows) // 2])


def _mutate_candidate_refusal(root: Path) -> None:
    """Give ONE arm an extra CANDIDATE-layer refusal: the arms stop being like for like.

    A risk budget cannot add or remove a candidate refusal, so this must break the
    layer check. Editing the declared funnel instead would only be an arithmetic
    mismatch and would (correctly) be caught by FUNNEL_ARITHMETIC alone.
    """
    path = root / "RISK_REFUSALS.csv"
    rows = _read_csv(path)
    sample = next(
        row for row in rows if row["run"] == "variant" and row["source"] == "candidate"
    )
    injected = dict(sample)
    injected["decision_ts"] = str(int(sample["decision_ts"]) + BAR_MS)
    rows.append(injected)
    _rewrite_csv(path, rows)


def _mutate_marginal(root: Path) -> None:
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["verdict"]["marginal_net_usdt"] = round(
        float(payload["verdict"]["marginal_net_usdt"]) + 30.0, 4
    )
    _store_json(path, payload)


def _mutate_market_context(root: Path) -> None:
    path = root / "RISK_TRADES.csv"
    rows = _read_csv(path)
    rotation = {"BULL": "BEAR", "BEAR": "SIDEWAYS", "SIDEWAYS": "BULL", "UNDEFINED": "BULL"}
    for row in rows:
        row["market_context"] = rotation.get(row["market_context"], "BULL")
    _rewrite_csv(path, rows)


def _mutate_flip_verdict(root: Path) -> None:
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["verdict"]["verdict"] = "FREQUENCY_VIABLE"
    _store_json(path, payload)


def _mutate_rule_threshold(root: Path) -> None:
    path = root / "RISK_ABLATION.json"
    payload = _load_json(path)
    payload["verdict"]["rule"]["min_extra_trades"] = 1
    _store_json(path, payload)


def _mutate_out_of_window_trade(root: Path) -> None:
    path = root / "RISK_TRADES.csv"
    rows = _read_csv(path)
    sample = next(row for row in rows if row["run"] == "variant")
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
    ("M4_second_field_retuned", "BUDGET_IS_ONE_FIELD_APART", _mutate_second_field),
    ("M5_base_halt_relaxed", "BUDGET_IS_ONE_FIELD_APART", _mutate_relax_base_halt),
    ("M6_halt_back_in_variant", "HALT_IS_INERT_IN_VARIANT", _mutate_halt_refusal_in_variant),
    ("M7_signal_changed_in_one_arm", "CANDIDATE_LAYER_IDENTICAL", _mutate_signal_in_one_arm),
    ("M8_refusals_trimmed", "FUNNEL_ARITHMETIC", _mutate_drop_refusals),
    ("M9_candidate_refusal_moved", "FUNNEL_SPLIT_BY_LAYER", _mutate_candidate_refusal),
    ("M10_marginal_tampered", "MARGINAL_ARITHMETIC", _mutate_marginal),
    ("M11_relabelled_market_context", "MARKET_CONTEXT_ATTRIBUTION", _mutate_market_context),
    ("M12_flipped_verdict", "VERDICT_RECOMPUTED", _mutate_flip_verdict),
    ("M13_relaxed_rule", "DECISION_RULE_FROZEN", _mutate_rule_threshold),
    ("M14_out_of_window_trade", "WINDOW_IS_PREREGISTERED_DEV", _mutate_out_of_window_trade),
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
    parser.add_argument("--dir", default="reports/edge-recovery/WP-EDGE-01/risk-budget-h5")
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
                f"[{status}] {item['mutation']:<32} -> {item['expected_check']} "
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
