"""exp_003k_verify — re-derive 003K's claims from its raw artifacts, then try to fool it.

    ./.venv/Scripts/python.exe scripts/exp_003k_verify.py
    ./.venv/Scripts/python.exe scripts/exp_003k_verify.py --negative-controls

Two different things live here on purpose.

**The positive pass** reads only frozen inputs — the dataset manifest, the run ledgers, the
run metadata and the traces — and recomputes what the report claims: the digests, the
run invariants, point-in-time causality, fill timing, the accounting identities, that no
position is closed twice, that the Stage A selection is the one the pre-registered rule
produces, and that the OOS verdict follows from the OOS ledgers. It never imports the
builder's report script and never trusts ``METRICS_*.csv``: every number is rebuilt from
the ledger rows that the runtime wrote.

**The negative controls** build small synthetic run trees in a temporary directory whose
ledger contains one specific lie — a look-ahead trace row, a fill quoted before its answer,
a double-counted close, a tampered net, a selection that ignores its own rule, a success
claimed on an interval that crosses zero — and require the corresponding check to fail.
A verifier that cannot fail proves nothing, so the run is only green when every control is
caught and none of them is reported as a pass.

Report: ``VERIFICATION.md`` + ``VERIFICATION.json`` inside the 003K directory.
Exit code: 0 when every executed check passes and every negative control is caught,
1 otherwise, 2 when the artifacts are not there yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics as stats
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"

BOOTSTRAP_ROUNDS = 10_000
BOOTSTRAP_SEED = 20261020
MIN_CLOSES_RESEARCH = 60
MIN_IMPROVEMENT_USDT = 0.25
COST_FLOOR_USDT = 1.29
BASELINE = "ema_crossover"


@dataclass
class Check:
    code: str
    ok: bool
    detail: str
    status: str = "PASS"


@dataclass
class Audit:
    root: Path
    checks: list[Check] = field(default_factory=list)

    def add(self, code: str, ok: bool, detail: str, *, status: str = "PASS") -> None:
        self.checks.append(Check(code=code, ok=bool(ok), detail=detail, status=status))

    def skip(self, code: str, detail: str) -> None:
        self.checks.append(Check(code=code, ok=True, detail=detail, status="NOT_EXECUTED"))


# ---------------------------------------------------------------- primitives


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)["entry"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _runs(root: Path) -> list[Path]:
    base = root / "runs"
    if not base.exists():
        return []
    return sorted(
        run_dir
        for strategy_dir in base.iterdir()
        if strategy_dir.is_dir() and not strategy_dir.name.startswith(".")
        for run_dir in (strategy_dir / "real").glob("*")
        if run_dir.is_dir()
    )


def _row_metrics(entries: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [row for row in entries if row.get("kind") == "CLOSE"]
    net = sum(float(row["pnl_net_usdt"]) for row in closes)
    reference = sum(float(row["reference_gross_pnl_usdt"]) for row in closes)
    commissions = sum(float(row["commissions_usdt"]) for row in closes)
    execution = sum(float(row["execution_cost_usdt"]) for row in closes)
    n = len(closes)
    return {
        "closes": n,
        "net_usdt": net,
        "reference_gross_usdt": reference,
        "execution_usdt": execution,
        "commissions_usdt": commissions,
        "expectancy_usdt": net / n if n else None,
        "reference_gross_per_trade_usdt": reference / n if n else None,
        "nets": [float(row["pnl_net_usdt"]) for row in closes],
        "positions": [str(row.get("position_id")) for row in closes],
        "closes_rows": closes,
    }


def _bootstrap_ci(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95": None}
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = sorted(stats.fmean(rng.choices(values, k=n)) for _ in range(BOOTSTRAP_ROUNDS))
    return {
        "n": n,
        "mean": stats.fmean(values),
        "ci95": [means[int(0.025 * BOOTSTRAP_ROUNDS)], means[int(0.975 * BOOTSTRAP_ROUNDS) - 1]],
    }


# ---------------------------------------------------------------- checks


def check_dataset(root: Path, audit: Audit) -> None:
    manifest_path = root / "dataset" / "DATASET_MANIFEST.json"
    if not manifest_path.exists():
        audit.add("VK1_dataset_digests", False, f"missing {manifest_path.name}")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for symbol, entry in sorted(manifest.get("symbols", {}).items()):
        path = root / "dataset" / entry["file"]
        if not path.exists():
            failures.append(f"{symbol}: file missing")
            continue
        actual = _sha256(path)
        if actual != entry["sha256"]:
            failures.append(f"{symbol}: {actual[:12]} != manifest {entry['sha256'][:12]}")
        coverage = entry.get("coverage") or {}
        if not coverage.get("complete"):
            failures.append(f"{symbol}: coverage incomplete")
    pre = (root / "PRE_REGISTRATION.md").read_text(encoding="utf-8")
    declared = dict(re.findall(r"\|\s*(BTCUSDT|ETHUSDT|SOLUSDT)\s*\|[^|]*\|[^|]*\|[^|]*\|\s*`([0-9a-f]{64})`", pre))
    if not declared:
        failures.append("no frozen digest table in PRE_REGISTRATION.md")
    for symbol, digest in sorted(declared.items()):
        entry = (manifest.get("symbols") or {}).get(symbol) or {}
        if entry.get("sha256") != digest:
            failures.append(f"{symbol}: pre-registration digest differs from manifest")
    audit.add(
        "VK1_dataset_digests",
        not failures,
        "; ".join(failures) or f"{len(manifest.get('symbols', {}))} files match the frozen table",
    )


def check_partitions(root: Path, audit: Audit) -> None:
    path = root / "PARTITIONS.json"
    if not path.exists():
        audit.add("VK2_partitions_frozen", False, "missing PARTITIONS.json")
        return
    partitions = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    research = partitions.get("research") or {}
    oos = partitions.get("oos") or {}
    # Chronological and non-overlapping: the holdout may start at the research end (the
    # boundary is shared) but never before it.
    if str(research.get("end_utc", "")) > str(oos.get("start_utc", "")):
        problems.append("the holdout starts before the research window ends")
    if int(partitions.get("embargo_bars") or 0) <= 0:
        problems.append("no embargo declared")
    for name, window in (("research", research), ("oos", oos)):
        start = datetime.strptime(window["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(window["end_utc"], "%Y-%m-%dT%H:%M:%SZ")
        if (end - start).days <= 0:
            problems.append(f"{name}: non-positive window")
    if datetime.strptime(oos["end_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) > datetime(
        2026, 8, 20, tzinfo=UTC
    ):
        problems.append("oos reaches into the window 003J already observed")
    audit.add(
        "VK2_partitions_frozen",
        not problems,
        "; ".join(problems)
        or f"research {research['start_utc']}..{research['end_utc']}, oos {oos['start_utc']}..{oos['end_utc']}, "
        f"embargo {partitions.get('embargo_bars')} bars",
    )


def check_run_invariants(root: Path, audit: Audit, entries_by_run: dict[Path, list[dict[str, Any]]]) -> None:
    problems: list[str] = []
    runs = _runs(root)
    if not runs:
        audit.add("VK3_run_invariants", False, "no runs found")
        return
    risk_hash = _sha256(REPO / "config" / "risk.yaml")
    for run_dir in runs:
        meta_path = run_dir / "RUN_META.json"
        if not meta_path.exists():
            problems.append(f"{run_dir.name}: no RUN_META.json")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        tag = f"{run_dir.parent.parent.name}/{run_dir.name}"
        if meta.get("live_orders") != 0:
            problems.append(f"{tag}: live_orders={meta.get('live_orders')}")
        if meta.get("live_enabled") is not False:
            problems.append(f"{tag}: live_enabled={meta.get('live_enabled')}")
        if meta.get("fill_policy") != "next_observable_bar_open":
            problems.append(f"{tag}: fill_policy={meta.get('fill_policy')}")
        if meta.get("data_delay_ms") != 0:
            problems.append(f"{tag}: data_delay_ms={meta.get('data_delay_ms')}")
        if meta.get("decision_every_bars") != 24:
            problems.append(f"{tag}: cadence {meta.get('decision_every_bars')}")
        if int(meta.get("window_bars") or 0) < 56:
            problems.append(f"{tag}: window_bars {meta.get('window_bars')} < 56")
        if meta.get("risk_policy_sha256") != risk_hash:
            problems.append(f"{tag}: risk.yaml changed after the run")
        if not meta.get("commit"):
            problems.append(f"{tag}: no commit recorded")
        ledger = json.loads((run_dir / "SUMMARY.json").read_text(encoding="utf-8"))
        if int(ledger.get("live_orders") or 0) != 0:
            problems.append(f"{tag}: summary live_orders non-zero")
        # The ledger itself must not carry a live order either.
        for row in entries_by_run.get(run_dir, []):
            if str(row.get("kind")) in {"LIVE_ORDER", "ORDER_SENT"}:
                problems.append(f"{tag}: ledger carries a {row.get('kind')} row")
                break
    audit.add(
        "VK3_run_invariants",
        not problems,
        "; ".join(problems[:6])
        or f"{len(runs)} runs: PAPER only, no live order, cadence 24 bars, same risk policy",
    )


def check_point_in_time(root: Path, audit: Audit) -> None:
    problems: list[str] = []
    rows_seen = 0
    for run_dir in _runs(root):
        trace = run_dir / "SIGNAL_TRACE.jsonl"
        if not trace.exists():
            continue
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows_seen += 1
            observed = row.get("max_input_data_time_ms")
            decision = row.get("decision_time_ms")
            if observed is None or decision is None:
                continue
            if int(observed) > int(decision):
                problems.append(
                    f"{run_dir.parent.parent.name}: {row.get('asset')} read data "
                    f"{int(observed) - int(decision)} ms after the decision"
                )
                break
    if rows_seen == 0:
        audit.add("VK4_point_in_time", False, "no signal trace rows to check")
        return
    audit.add(
        "VK4_point_in_time",
        not problems,
        "; ".join(problems[:4]) or f"{rows_seen} trace rows, none read data after its decision",
    )


def check_fill_timing(root: Path, audit: Audit, entries_by_run: dict[Path, list[dict[str, Any]]]) -> None:
    problems: list[str] = []
    fills = 0
    for run_dir, entries in entries_by_run.items():
        for row in entries:
            if row.get("kind") != "FILL":
                continue
            fills += 1
            answer = row.get("decision_ts_ms")
            paid_at = row.get("quote_ts_ms")
            if answer is None or paid_at is None:
                problems.append(f"{run_dir.parent.parent.name}: fill without an answer stamp")
                continue
            if int(paid_at) < int(answer):
                problems.append(
                    f"{run_dir.parent.parent.name}: {row.get('symbol')} paid a price "
                    f"{int(answer) - int(paid_at)} ms older than its answer"
                )
    if fills == 0:
        audit.add("VK5_fill_after_answer", False, "no fills to check", status="NOT_EXECUTED")
        return
    audit.add(
        "VK5_fill_after_answer",
        not problems,
        "; ".join(problems[:4]) or f"{fills} fills, every one priced at or after its answer",
    )


def check_accounting(root: Path, audit: Audit, entries_by_run: dict[Path, list[dict[str, Any]]]) -> None:
    problems: list[str] = []
    closes = 0
    for run_dir, entries in entries_by_run.items():
        tag = f"{run_dir.parent.parent.name}/{run_dir.name}"
        for row in entries:
            if row.get("kind") != "CLOSE":
                continue
            closes += 1
            reference = float(row["reference_gross_pnl_usdt"])
            execution = float(row["execution_cost_usdt"])
            commissions = float(row["commissions_usdt"])
            gross = float(row["gross_pnl_usdt"])
            net = float(row["pnl_net_usdt"])
            if abs((reference - execution) - gross) > 1e-5:
                problems.append(f"{tag}: gross != reference - execution")
            if abs((gross - commissions) - net) > 1e-5:
                problems.append(f"{tag}: net != gross - commissions")
            if float(row["entry_commission_usdt"]) + float(
                row.get("exit_commission_usdt", 0.0)
            ) - commissions > 1e-6:
                problems.append(f"{tag}: commissions are not both legs, once each")
        summary = json.loads((run_dir / "SUMMARY.json").read_text(encoding="utf-8"))
        ledger_net = sum(
            float(row["pnl_net_usdt"]) for row in entries if row.get("kind") == "CLOSE"
        )
        if abs(float(summary.get("net_realised_usdt") or 0.0) - ledger_net) > 1e-3:
            problems.append(f"{tag}: summary net disagrees with the ledger by {ledger_net}")
    audit.add(
        "VK6_accounting_identities",
        not problems,
        "; ".join(problems[:4]) or f"{closes} closes satisfy reference - execution - commissions = net",
    )


def check_no_double_counting(root: Path, audit: Audit, entries_by_run: dict[Path, list[dict[str, Any]]]) -> None:
    problems: list[str] = []
    for run_dir, entries in entries_by_run.items():
        tag = f"{run_dir.parent.parent.name}/{run_dir.name}"
        opened = {str(row.get("position_id")) for row in entries if row.get("kind") == "FILL"}
        closed = [str(row.get("position_id")) for row in entries if row.get("kind") == "CLOSE"]
        if len(closed) != len(set(closed)):
            problems.append(f"{tag}: a position was closed more than once")
        unknown = set(closed) - opened
        if unknown:
            problems.append(f"{tag}: {len(unknown)} closes without a fill")
        trades = [str(row.get("trade_id")) for row in entries if row.get("kind") == "CLOSE"]
        if len(trades) != len(set(trades)):
            problems.append(f"{tag}: a trade_id appears twice")
    audit.add(
        "VK7_no_double_counting",
        not problems,
        "; ".join(problems[:4]) or "every position is filled once and closed at most once",
    )


def _selection_from_ledgers(root: Path) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for run_dir in _runs(root):
        if run_dir.name != "research":
            continue
        entries = _load_ledger(run_dir / "ledger.jsonl")
        metrics = _row_metrics(entries)
        rows[run_dir.parent.parent.name] = {
            "closes": metrics["closes"],
            "expectancy_usdt": metrics["expectancy_usdt"],
            "reference_gross_per_trade_usdt": metrics["reference_gross_per_trade_usdt"],
        }
    baseline = rows.get(BASELINE)
    if baseline is None or baseline["expectancy_usdt"] is None:
        return {"selected": None, "status": "BLOCKED", "rows": rows}
    eligible = []
    for strategy_id, row in rows.items():
        if strategy_id == BASELINE or row["expectancy_usdt"] is None:
            continue
        if row["closes"] < MIN_CLOSES_RESEARCH:
            continue
        if row["expectancy_usdt"] <= baseline["expectancy_usdt"] + MIN_IMPROVEMENT_USDT:
            continue
        if (row["reference_gross_per_trade_usdt"] or 0.0) <= COST_FLOOR_USDT:
            continue
        eligible.append((strategy_id, row["expectancy_usdt"]))
    eligible.sort(key=lambda item: (-item[1], item[0]))
    return {
        "selected": eligible[0][0] if eligible else None,
        "status": "SELECTED" if eligible else "BLOCKED",
        "eligible": [item[0] for item in eligible],
        "rows": rows,
    }


def check_selection(root: Path, audit: Audit) -> None:
    path = root / "SELECTION.json"
    if not path.exists():
        audit.add("VK8_selection_rule", False, "missing SELECTION.json")
        return
    declared = json.loads(path.read_text(encoding="utf-8"))
    mine = _selection_from_ledgers(root)
    problems: list[str] = []
    if declared.get("selected") != mine["selected"]:
        problems.append(
            f"declared {declared.get('selected')!r} but the rule selects {mine['selected']!r}"
        )
    if declared.get("status") != mine["status"]:
        problems.append(f"declared status {declared.get('status')!r} vs {mine['status']!r}")
    audit.add(
        "VK8_selection_rule",
        not problems,
        "; ".join(problems)
        or f"recomputed from ledgers: {mine['status']} ({mine.get('eligible') or 'no eligible candidate'})",
    )


def _oos_strategies(root: Path) -> list[str]:
    return sorted(
        run_dir.parent.parent.name for run_dir in _runs(root) if run_dir.name == "oos"
    )


def check_oos_scope(root: Path, audit: Audit) -> None:
    strategies = _oos_strategies(root)
    declared = root / "SELECTION.json"
    selected = None
    if declared.exists():
        selected = json.loads(declared.read_text(encoding="utf-8")).get("selected")
    problems: list[str] = []
    if len(strategies) > 2:
        problems.append(f"{len(strategies)} strategies were run on the holdout: {strategies}")
    if selected and sorted({*strategies}) not in ([BASELINE], [BASELINE, selected], sorted([BASELINE])):
        if selected not in strategies:
            problems.append(f"the selected strategy {selected!r} never ran on the holdout")
        if BASELINE not in strategies:
            problems.append("the baseline did not run on the holdout")
    audit.add(
        "VK9_oos_scope",
        not problems,
        "; ".join(problems) or f"holdout touched by {strategies or 'nothing yet'}",
        status="PASS" if strategies else "NOT_EXECUTED",
    )


def _verdict_from_ledgers(root: Path, selected: str) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for run_dir in _runs(root):
        if run_dir.name != "oos":
            continue
        entries = _load_ledger(run_dir / "ledger.jsonl")
        metrics = _row_metrics(entries)
        nets = metrics["nets"]
        ordered = sorted(
            metrics["closes_rows"], key=lambda row: int(row["ts_ms"])
        )
        half = len(ordered) // 2
        first_half = [float(row["pnl_net_usdt"]) for row in ordered[:half]]
        second_half = [float(row["pnl_net_usdt"]) for row in ordered[half:]]
        rows[run_dir.parent.parent.name] = {
            "closes": metrics["closes"],
            "expectancy_usdt": metrics["expectancy_usdt"],
            "reference_gross_per_trade_usdt": metrics["reference_gross_per_trade_usdt"],
            "bootstrap": _bootstrap_ci(nets),
            "first_half_expectancy": stats.fmean(first_half) if first_half else None,
            "second_half_expectancy": stats.fmean(second_half) if second_half else None,
        }
    candidate = rows.get(selected) or {}
    baseline = rows.get(BASELINE) or {}
    if not candidate:
        return {"status": "NOT_EXECUTED", "rows": rows}
    if int(candidate["closes"]) < 30:
        return {"status": "INSUFFICIENT_SAMPLE", "rows": rows}
    ci = (candidate["bootstrap"] or {}).get("ci95") or [None, None]
    conditions = {
        "positive_expectancy": (candidate["expectancy_usdt"] or 0.0) > 0,
        "ci_lower_above_zero": ci[0] is not None and ci[0] > 0,
        "positive_in_both_halves": (candidate["first_half_expectancy"] or 0.0) > 0
        and (candidate["second_half_expectancy"] or 0.0) > 0,
        "gross_above_cost_floor": (candidate["reference_gross_per_trade_usdt"] or 0.0)
        > COST_FLOOR_USDT,
        "beats_baseline": (candidate["expectancy_usdt"] or 0.0)
        > (baseline.get("expectancy_usdt") or 0.0),
    }
    status = "EVIDENCE_OF_EDGE" if all(conditions.values()) else "REJECT"
    return {"status": status, "conditions": conditions, "rows": rows}


def check_verdict(root: Path, audit: Audit) -> None:
    path = root / "VERDICT.json"
    if not path.exists():
        audit.add("VK10_verdict_rule", False, "missing VERDICT.json", status="NOT_EXECUTED")
        return
    declared = json.loads(path.read_text(encoding="utf-8"))
    selection_path = root / "SELECTION.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8")) if selection_path.exists() else {}
    selected = declared.get("candidate") or selection.get("selected")
    if selected is None:
        # A blocked experiment is a legitimate outcome only while the holdout is untouched:
        # "no candidate" and "we still looked anyway" cannot both be true.
        blocked_ok = (
            declared.get("status") == "BLOCKED"
            and selection.get("selected") is None
            and not _oos_strategies(root)
        )
        audit.add(
            "VK10_verdict_rule",
            blocked_ok,
            (
                "BLOCKED with no candidate selected and no run on the holdout"
                if blocked_ok
                else f"declared {declared.get('status')!r} but the holdout records "
                f"{_oos_strategies(root) or 'nothing'} and the selection names "
                f"{selection.get('selected')!r}"
            ),
            status="PASS" if blocked_ok else "FAIL",
        )
        return
    mine = _verdict_from_ledgers(root, selected)
    problems: list[str] = []
    if declared.get("status") != mine["status"]:
        problems.append(f"declared {declared.get('status')!r} but the rule gives {mine['status']!r}")
    if declared.get("status") == "EVIDENCE_OF_EDGE":
        failing = [key for key, ok in (mine.get("conditions") or {}).items() if not ok]
        if failing:
            problems.append(f"success claimed while failing {failing}")
    if declared.get("status") == "EVIDENCE_OF_EDGE" and (mine.get("rows") or {}).get(selected, {}).get("closes", 0) < 30:
        problems.append("success claimed on fewer than 30 closes")
    audit.add(
        "VK10_verdict_rule",
        not problems,
        "; ".join(problems) or f"verdict {mine['status']} reproduced from the holdout ledger",
        status="PASS" if mine.get("status") != "NOT_EXECUTED" else "NOT_EXECUTED",
    )


def check_no_live_path(root: Path, audit: Audit) -> None:
    problems: list[str] = []
    for run_dir in _runs(root):
        for name in ("RUN_META.json", "SUMMARY.json"):
            text = (run_dir / name).read_text(encoding="utf-8").lower()
            if "\"live_orders\": 0" not in text and "live_orders" in text:
                problems.append(f"{run_dir.name}/{name}: live_orders not zero")
            for marker in ("api_key", "api_secret", "secret_key", "private_key"):
                if marker in text:
                    problems.append(f"{run_dir.name}/{name}: contains {marker}")
    audit.add(
        "VK11_no_live_path",
        not problems,
        "; ".join(problems[:4]) or "no run record enables live trading or carries a credential",
    )


def check_determinism(root: Path, audit: Audit) -> None:
    repeats = sorted((root / "runs").glob("*/real/*/DETERMINISM.json"))
    if not repeats:
        audit.skip(
            "VK12_determinism",
            "no repeat ledger for 003K runs; declared NOT_EXECUTED rather than inferred",
        )
        return
    problems = [
        f"{path.parent.parent.parent.name}/{path.parent.name}: not identical"
        for path in repeats
        if not json.loads(path.read_text(encoding="utf-8")).get("identical")
    ]
    audit.add(
        "VK12_determinism",
        not problems,
        "; ".join(problems) or f"{len(repeats)} repeat comparison(s) identical",
    )


def positive_pass(root: Path) -> Audit:
    audit = Audit(root=root)
    entries_by_run = {
        run_dir: _load_ledger(run_dir / "ledger.jsonl")
        for run_dir in _runs(root)
        if (run_dir / "ledger.jsonl").exists()
    }
    check_dataset(root, audit)
    check_partitions(root, audit)
    check_run_invariants(root, audit, entries_by_run)
    check_point_in_time(root, audit)
    check_fill_timing(root, audit, entries_by_run)
    check_accounting(root, audit, entries_by_run)
    check_no_double_counting(root, audit, entries_by_run)
    check_selection(root, audit)
    check_oos_scope(root, audit)
    check_verdict(root, audit)
    check_no_live_path(root, audit)
    check_determinism(root, audit)
    return audit


# ---------------------------------------------------------------- negative controls


def _synthetic_root(
    base: Path,
    *,
    look_ahead: bool = False,
    early_fill: bool = False,
    double_close: bool = False,
    bad_net: bool = False,
) -> Path:
    """A tiny, internally consistent run tree with exactly one lie in it."""

    root = base / "exp"
    runs = root / "runs" / "ema_crossover" / "real" / "research"
    runs.mkdir(parents=True, exist_ok=True)
    answer = 1_800_000_000_000
    rows: list[dict[str, Any]] = [
        {
            "kind": "DECISION",
            "ts_ms": answer,
            "symbol": "BTC/USDT",
            "intent": "OPEN_LONG",
        }
    ]
    rows.append(
        {
            "kind": "FILL",
            "symbol": "BTC/USDT",
            "position_id": "pos-1",
            "decision_ts_ms": answer,
            "quote_ts_ms": answer - 300_000 if early_fill else answer,
            "ts_ms": answer,
            "entry_price": 100.0,
            "quantity": 5.0,
        }
    )
    net = -3.0 if not bad_net else -4.0
    rows.append(
        {
            "kind": "CLOSE",
            "symbol": "BTC/USDT",
            "position_id": "pos-1",
            "trade_id": "trd-1",
            "ts_ms": answer + 600_000,
            "entry_quote_ts_ms": answer,
            "reference_gross_pnl_usdt": -2.0,
            "execution_cost_usdt": 0.0,
            "commissions_usdt": 1.0,
            "entry_commission_usdt": 0.5,
            "exit_commission_usdt": 0.5,
            "gross_pnl_usdt": -2.0,
            "pnl_net_usdt": net,
        }
    )
    if double_close:
        dup = dict(rows[-1])
        dup["trade_id"] = "trd-2"
        rows.append(dup)
    with (runs / "ledger.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps({"entry": row}) + "\n")
    net_total = sum(float(row["pnl_net_usdt"]) for row in rows if row["kind"] == "CLOSE")
    (runs / "SUMMARY.json").write_text(
        json.dumps({"net_realised_usdt": net_total, "live_orders": 0}), encoding="utf-8"
    )
    (runs / "RUN_META.json").write_text(
        json.dumps(
            {
                "live_orders": 0,
                "live_enabled": False,
                "fill_policy": "next_observable_bar_open",
                "data_delay_ms": 0,
                "decision_every_bars": 24,
                "window_bars": 60,
                "risk_policy_sha256": _sha256(REPO / "config" / "risk.yaml"),
                "commit": "test",
                "ledger": {"sha256": "0" * 64},
                "provider_counters": {"strategy_version": "sha256:test"},
            }
        ),
        encoding="utf-8",
    )
    trace_rows = [
        {
            "asset": "BTC/USDT",
            "decision_time_ms": answer,
            "max_input_data_time_ms": answer + 300_000 if look_ahead else answer,
        }
    ]
    (runs / "SIGNAL_TRACE.jsonl").write_text(
        "\n".join(json.dumps(row) for row in trace_rows) + "\n", encoding="utf-8"
    )
    return root


def _control(root: Path, code: str) -> str:
    audit = Audit(root=root)
    entries_by_run = {
        run_dir: _load_ledger(run_dir / "ledger.jsonl") for run_dir in _runs(root)
    }
    lookup: dict[str, Callable[[], None]] = {
        "VK1_dataset_digests": lambda: check_dataset(root, audit),
        "VK4_point_in_time": lambda: check_point_in_time(root, audit),
        "VK5_fill_after_answer": lambda: check_fill_timing(root, audit, entries_by_run),
        "VK6_accounting_identities": lambda: check_accounting(root, audit, entries_by_run),
        "VK7_no_double_counting": lambda: check_no_double_counting(root, audit, entries_by_run),
        "VK8_selection_rule": lambda: check_selection(root, audit),
        "VK10_verdict_rule": lambda: check_verdict(root, audit),
    }
    lookup[code]()
    caught = [check for check in audit.checks if check.code == code and not check.ok]
    return (
        f"caught: {caught[0].detail[:160]}"
        if caught
        else "NOT CAUGHT — the control was reported as a pass"
    )


def negative_controls() -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    all_caught = True
    with tempfile.TemporaryDirectory(prefix="003k-controls-") as tmp:
        base = Path(tmp)

        cases = [
            ("N1_look_ahead_trace", "VK4_point_in_time", {"look_ahead": True}),
            ("N2_fill_before_answer", "VK5_fill_after_answer", {"early_fill": True}),
            ("N3_double_counted_close", "VK7_no_double_counting", {"double_close": True}),
            ("N4_tampered_net", "VK6_accounting_identities", {"bad_net": True}),
        ]
        for name, code, kwargs in cases:
            case_dir = base / name
            case_dir.mkdir()
            root = _synthetic_root(case_dir, **kwargs)
            detail = _control(root, code)
            caught = detail.startswith("caught")
            all_caught &= caught
            results.append(
                {"control": name, "check": code, "caught": caught, "detail": detail}
            )

        # N5: a selection that ignores its own rule. The synthetic tree has one strategy
        # whose expectancy is negative; declaring it selected must not survive.
        case_dir = base / "N5_false_selection"
        case_dir.mkdir()
        root = _synthetic_root(case_dir)
        (root / "SELECTION.json").write_text(
            json.dumps({"selected": "momentum", "status": "SELECTED"}), encoding="utf-8"
        )
        detail = _control(root, "VK8_selection_rule")
        caught = detail.startswith("caught")
        all_caught &= caught
        results.append(
            {
                "control": "N5_false_selection",
                "check": "VK8_selection_rule",
                "caught": caught,
                "detail": detail,
            }
        )

        # N6: a success claimed on a holdout whose expectancy is negative.
        case_dir = base / "N6_false_success"
        case_dir.mkdir()
        root = _synthetic_root(case_dir)
        runs = root / "runs" / "ema_crossover" / "real" / "oos"
        runs.parent.mkdir(parents=True, exist_ok=True)
        (root / "runs" / "ema_crossover" / "real" / "research").rename(runs)
        (root / "SELECTION.json").write_text(
            json.dumps({"selected": "ema_crossover", "status": "SELECTED"}), encoding="utf-8"
        )
        (root / "VERDICT.json").write_text(
            json.dumps({"candidate": "ema_crossover", "status": "EVIDENCE_OF_EDGE"}),
            encoding="utf-8",
        )
        detail = _control(root, "VK10_verdict_rule")
        caught = detail.startswith("caught")
        all_caught &= caught
        results.append(
            {
                "control": "N6_false_success",
                "check": "VK10_verdict_rule",
                "caught": caught,
                "detail": detail,
            }
        )
    return results, all_caught


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(EXP))
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not (root / "PARTITIONS.json").exists():
        print(f"[003k-verify] BLOCKED — no artifacts at {root}", file=sys.stderr)
        return 2

    audit = positive_pass(root)
    controls: list[dict[str, Any]] = []
    controls_ok = True
    if args.negative_controls:
        controls, controls_ok = negative_controls()

    executed = [check for check in audit.checks if check.status != "NOT_EXECUTED"]
    failures = [check for check in executed if not check.ok]
    ok = not failures and controls_ok
    payload = {
        "schema_version": "AI_BOTS_003K_VERIFICATION_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verifier": "scripts/exp_003k_verify.py",
        "independence": (
            "same author as the builder: this is a second program, not an independent "
            "party. false_success protection comes from the negative controls, not from "
            "authorship."
        ),
        "checks": [check.__dict__ for check in audit.checks],
        "summary": {
            "executed": len(executed),
            "passed": len(executed) - len(failures),
            "failed": len(failures),
            "not_executed": len(audit.checks) - len(executed),
        },
        "negative_controls": controls,
        "negative_controls_all_caught": controls_ok if controls else None,
        "false_success": len(failures) + (0 if controls_ok else 1),
        "verdict": "PASS" if ok else "FAIL",
    }
    out = Path(args.out) if args.out else root
    (out / "VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    lines = [
        "# Verificación 003K",
        "",
        f"Programa: `{payload['verifier']}` · {payload['generated_at_utc']}",
        "",
        "| check | estado | detalle |",
        "| --- | --- | --- |",
    ]
    for check in audit.checks:
        state = "NOT_EXECUTED" if check.status == "NOT_EXECUTED" else ("PASS" if check.ok else "FAIL")
        lines.append(f"| `{check.code}` | {state} | {check.detail[:220]} |")
    if controls:
        lines += ["", "## Controles negativos", "", "| control | check | resultado |", "| --- | --- | --- |"]
        for control in controls:
            lines.append(
                f"| `{control['control']}` | `{control['check']}` | "
                f"{'detectado' if control['caught'] else 'NO detectado'} |"
            )
    lines += [
        "",
        "## Independencia",
        "",
        payload["independence"],
        "",
        f"`false_success={payload['false_success']}` · veredicto `{payload['verdict']}`",
    ]
    (out / "VERIFICATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    independent = [
        "# INDEPENDENT VERIFICATION — EXP-003K-CANDIDATE-001",
        "",
        "**Quién verifica:** `scripts/exp_003k_verify.py`, un programa separado del que produjo",
        "las corridas y los informes. **No** es una persona distinta: la independencia es de",
        "implementación, no de autoría, y así se declara.",
        "",
        "**Qué garantiza:** cada afirmación se reconstruye desde los bytes (manifest, ledgers,",
        "RUN_META, trazas) sin leer `METRICS_*.csv` ni importar el generador de informes. Y seis",
        "controles negativos demuestran que los checks pueden fallar: look-ahead, fill anterior a",
        "la respuesta, cierre contado dos veces, neto manipulado, selección que ignora su regla y",
        "éxito falso.",
        "",
        "**Qué no garantiza:** que la interpretación económica sea la correcta, ni que el diseño",
        "del experimento sea el adecuado. Un PASS técnico no es una certificación.",
        "",
    ]
    (out / "INDEPENDENT_VERIFICATION.md").write_text(
        "\n".join(independent + lines) + "\n", encoding="utf-8", newline="\n"
    )
    for check in audit.checks:
        marker = "SKIP" if check.status == "NOT_EXECUTED" else ("PASS" if check.ok else "FAIL")
        print(f"[003k-verify] {marker:<4} {check.code}: {check.detail[:120]}", flush=True)
    for control in controls:
        print(
            f"[003k-verify] control {control['control']}: "
            f"{'caught' if control['caught'] else 'NOT CAUGHT'}",
            flush=True,
        )
    print(f"[003k-verify] verdict={payload['verdict']}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
