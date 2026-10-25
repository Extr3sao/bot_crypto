"""Independent verification of EXP-003J-REAL-SIGNAL-PAPER-001.

This program was written in a different session from the one that produced the experiment.  It
imports nothing from ``trading_bot`` and never executes ``scripts/exp_003j_*.py``: every number is
re-derived from the bytes on disk (the compressed datasets, the two hash-chained ledgers, the SQL
free CSVs, the summaries and the runtime metadata).  That is what the RFC asks for at
``WP-003J-05``/``WP-003J-06``, minus the part no program can supply: a human or organisational
separation of author and verifier.

    python scripts/exp_003j_verify_external.py --root reports/ai-bots/EXP-003J-REAL-SIGNAL-PAPER-001
    python scripts/exp_003j_verify_external.py --root <dir> --negative-controls

Exit code: 0 when every executed check passes and every injected control is caught, 1 otherwise,
2 when the artifact tree is missing something the checks need.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
TOL = 1e-6
VOLATILE = {"recorded_at_utc", "generated_at_utc", "received_at_ms", "latency_ms"}

FAILED: set[str] = set()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def rows_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rows_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def check(code: str, ok: bool, detail: str) -> dict[str, Any]:
    if not ok:
        FAILED.add(code)
    return {"code": code, "ok": bool(ok), "detail": detail}


def strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_volatile(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [strip_volatile(item) for item in value]
    return value


def load_ledger(path: Path) -> list[dict[str, Any]]:
    return rows_jsonl(path)


def ledger_chain_ok(path: Path) -> tuple[bool, str]:
    rows = load_ledger(path)
    if not rows:
        return False, "empty ledger"
    previous = GENESIS
    for index, row in enumerate(rows):
        if int(row.get("seq", -1)) != index + 1:
            return False, f"row {index}: seq={row.get('seq')} expected {index + 1}"
        if str(row.get("prev_sha256")) != previous:
            return False, f"row {index}: prev_sha256 does not chain"
        expected = hashlib.sha256(
            canonical({"seq": row["seq"], "prev_sha256": row["prev_sha256"], "entry": row["entry"]}).encode(
                "utf-8"
            )
        ).hexdigest()
        if str(row.get("sha256")) != expected:
            return False, f"row {index}: sha256 does not re-derive from its entry"
        previous = str(row["sha256"])
    return True, f"{len(rows)} rows, head {previous[:16]}"


def run_dirs(root: Path) -> dict[tuple[str, str], Path]:
    out: dict[tuple[str, str], Path] = {}
    for arm in ("control", "real"):
        for partition in ("research", "oos"):
            path = root / "runs" / arm / partition
            if path.is_dir():
                out[(arm, partition)] = path
    return out


# --------------------------------------------------------------------------- #
# integrity of the frozen inputs
# --------------------------------------------------------------------------- #


def checks_dataset(root: Path, heavy: bool) -> list[dict[str, Any]]:
    manifest_path = root / "dataset" / "DATASET_MANIFEST.json"
    if not manifest_path.is_file():
        return [check("A1_dataset_sha256", False, "DATASET_MANIFEST.json missing")]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metas = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((root / "runs").glob("*/*/RUN_META.json"))]
    out: list[dict[str, Any]] = []

    bad: list[str] = []
    for symbol, entry in (manifest.get("symbols") or {}).items():
        path = root / "dataset" / entry["file"]
        if not path.is_file():
            bad.append(f"{symbol}: file missing")
            continue
        digest = sha_file(path)
        if digest != entry.get("sha256"):
            bad.append(f"{symbol}: manifest {entry.get('sha256', '')[:12]} != {digest[:12]}")
        declared = {meta["dataset"][symbol]["file_sha256"] for meta in metas if symbol in (meta.get("dataset") or {})}
        if declared and declared != {digest}:
            bad.append(f"{symbol}: RUN_META disagrees with the file ({declared})")
    out.append(check("A1_dataset_sha256", not bad, "; ".join(bad) or f"{len(manifest.get('symbols') or {})} files match"))

    if not heavy:
        return out

    problems: list[str] = []
    total = 0
    for symbol, entry in (manifest.get("symbols") or {}).items():
        path = root / "dataset" / entry["file"]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            opens = [json.loads(line)[0] for line in handle if line.strip()]
        total += len(opens)
        span = int(entry["coverage"]["expected_bars"])
        if len(opens) != span:
            problems.append(f"{symbol}: {len(opens)} bars != {span} expected")
        if len(set(opens)) != len(opens):
            problems.append(f"{symbol}: duplicated minute stamps")
        step = 60_000
        expected_first = int(entry["coverage"]["first_open_ms"])
        for index, value in enumerate(opens):
            if value != expected_first + index * step:
                problems.append(f"{symbol}: bar {index} at {value} breaks the 1m grid")
                break
        if opens and opens[-1] + step != int(manifest["requested_end_ms"]):
            problems.append(f"{symbol}: last bar does not close on the requested end")
    out.append(
        check(
            "A2_dataset_minutes",
            not problems,
            "; ".join(problems) or f"{total} minutes re-read, contiguous 1m grid, no duplicates",
        )
    )
    return out


def checks_ledgers(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dirs = run_dirs(root)
    if not dirs:
        return [check("A3_ledger_chain", False, "no runs/*/*/ledger.jsonl found")]
    bad: list[str] = []
    for (arm, partition), path in dirs.items():
        ledger = path / "ledger.jsonl"
        ok, detail = ledger_chain_ok(ledger)
        if not ok:
            bad.append(f"{arm}/{partition}: {detail}")
            continue
        meta = json.loads((path / "RUN_META.json").read_text(encoding="utf-8"))
        if meta["ledger"]["sha256"] != sha_file(ledger):
            bad.append(f"{arm}/{partition}: file sha256 differs from RUN_META")
        if int(meta["ledger"]["rows"]) != len(load_ledger(ledger)):
            bad.append(f"{arm}/{partition}: row count differs from RUN_META")
    out.append(check("A3_ledger_chain", not bad, "; ".join(bad) or f"{len(dirs)} ledgers re-derived to the last byte"))

    diffs: list[str] = []
    compared = 0
    for arm in ("control", "real"):
        base = root / "runs" / arm / "oos" / "ledger.jsonl"
        repeat = root / "runs" / "repeat" / arm / "oos" / "ledger.jsonl"
        if not (base.is_file() and repeat.is_file()):
            continue
        first = [strip_volatile(row["entry"]) for row in load_ledger(base)]
        second = [strip_volatile(row["entry"]) for row in load_ledger(repeat)]
        compared += len(first)
        if len(first) != len(second):
            diffs.append(f"{arm}: {len(first)} vs {len(second)} entries")
            continue
        mismatch = next((i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b), None)
        if mismatch is not None:
            diffs.append(f"{arm}: entry {mismatch} differs")
    out.append(
        check(
            "A4_determinism",
            compared > 0 and not diffs,
            "; ".join(diffs) or f"{compared} replayed entries identical once run stamps are removed",
        )
    )
    return out


# --------------------------------------------------------------------------- #
# semantics: point in time, one slot per symbol, counts
# --------------------------------------------------------------------------- #


def trace_by_run(root: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows_jsonl(root / "DECISION_TRACE.jsonl"):
        grouped[str(row.get("run_id"))].append(row)
    return grouped


def checks_pit(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dirs = run_dirs(root)
    bad: list[str] = []
    future: list[str] = []
    seen = 0
    for (arm, partition), path in dirs.items():
        for row in rows_jsonl(path / "SIGNAL_TRACE.jsonl"):
            seen += 1
            decision_ms = row.get("decision_time_ms")
            latest = row.get("max_input_data_time_ms")
            if decision_ms is None or latest is None:
                bad.append(f"{arm}/{partition}: a trace row has no decision or input stamp")
                continue
            if int(latest) > int(decision_ms) + 1:
                future.append(f"{arm}/{partition}: input {latest} after decision {decision_ms}")
            bar_ms = row.get("decision_bar_open_ms")
            if bar_ms is not None and int(bar_ms) + 300_000 > int(decision_ms) + 1:
                bad.append(f"{arm}/{partition}: decision precedes the close of its own bar")
    detail = "; ".join((bad + future)[:5]) or f"{seen} signal rows, none reads a bar after its decision instant"
    out.append(check("B1_signal_trace_pit", not (bad or future), detail))

    # trade-level: the nth fill of a symbol cannot be quoted before the nth filled decision
    traces = trace_by_run(root)
    pdf = rows_csv(root / "PAPER_LEDGER.csv")
    trades: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pdf:
        trades[(row["arm"], row["symbol"])].append(row)
    ordering: list[str] = []
    matched = 0
    for key, rows in trades.items():
        rows.sort(key=lambda r: r["entry_utc"])
        arm = key[0]
        filled: list[dict[str, Any]] = []
        for run_id, run_rows in traces.items():
            if not run_id.startswith(f"003j-{arm}-"):
                continue
            filled += [r for r in run_rows if r.get("asset") == key[1] and r.get("broker_result") == "FILLED"]
        filled.sort(key=lambda r: r["decision_time_utc"])
        for index, trade in enumerate(rows):
            if index >= len(filled):
                ordering.append(f"{key}: trade {index} has no filled decision")
                break
            if utc(trade["entry_utc"]) < utc(filled[index]["decision_time_utc"]):
                ordering.append(f"{key}: trade {index} entered before its decision")
                break
            matched += 1
    out.append(
        check(
            "B2_fill_after_decision",
            not ordering,
            "; ".join(ordering[:5]) or f"{matched} trades entered at or after the decision that caused them",
        )
    )
    return out


def checks_ledger_semantics(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pdf = rows_csv(root / "PAPER_LEDGER.csv")
    if not pdf:
        return [check("B3_one_slot_per_symbol", False, "PAPER_LEDGER.csv is empty")]

    overlaps: list[str] = []
    for (arm, symbol), rows in _group_trades(pdf).items():
        ordered = sorted(rows, key=lambda r: r["entry_utc"])
        for first, second in itertools.pairwise(ordered):
            if utc(second["entry_utc"]) < utc(first["exit_utc"]):
                overlaps.append(f"{arm}/{symbol}: {first['trade_id']} still open when {second['trade_id']} opened")
    out.append(
        check(
            "B3_one_slot_per_symbol",
            not overlaps,
            "; ".join(overlaps[:5]) or f"{len(pdf)} trades, no symbol holds two positions at once",
        )
    )

    bad: list[str] = []
    for row in pdf:
        if utc(row["exit_utc"]) <= utc(row["entry_utc"]):
            bad.append(f"{row['trade_id']}: exit not after entry")
        held = (utc(row["exit_utc"]) - utc(row["entry_utc"])).total_seconds() / 60.0
        if abs(held - float(row["holding_minutes"])) > 0.01:
            bad.append(f"{row['trade_id']}: holding_minutes disagrees with the stamps")
    out.append(check("B4_trade_intervals", not bad, "; ".join(bad[:5]) or "every close follows its entry and its duration"))

    bad = []
    for row in pdf:
        quantity = float(row["quantity"])
        notional = float(row["notional_usdt"])
        price = float(row["entry_price"])
        if abs(quantity * price - notional) > 0.01:
            bad.append(f"{row['trade_id']}: quantity x entry != notional")
        if not (0 < notional <= 500.0 + 1e-6):
            bad.append(f"{row['trade_id']}: notional {notional} outside the sizing bound")
    out.append(check("B5_notional_consistency", not bad, "; ".join(bad[:5]) or "notional = quantity x entry and stays within 500 USDT"))

    partitions_path = root / "PARTITIONS.json"
    parts = json.loads(partitions_path.read_text(encoding="utf-8")) if partitions_path.is_file() else {}
    leaks: list[str] = []
    if parts:
        research_end = utc(parts["research"]["end_utc"])
        oos_start = utc(parts["oos"]["start_utc"])
        if research_end > oos_start:
            leaks.append("partitions overlap in their own definition")
        for row in pdf:
            if row["arm"] != "real":
                continue
            entry = utc(row["entry_utc"])
            if entry < oos_start and entry >= research_end:
                leaks.append(f"{row['trade_id']}: entry inside the embargo")
            if entry < research_end and utc(row["exit_utc"]) > oos_start:
                leaks.append(f"{row['trade_id']}: a research trade resolves inside the holdout")
    else:
        leaks.append("PARTITIONS.json missing")
    out.append(check("B6_no_oos_leakage", not leaks, "; ".join(leaks[:5]) or "holdout starts after research ends; no trade crosses the boundary"))
    return out


def _group_trades(pdf: Iterable[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pdf:
        grouped[(row["arm"], row["symbol"])].append(row)
    return grouped


def checks_counts(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dirs = run_dirs(root)
    traces = trace_by_run(root)
    pdf = rows_csv(root / "PAPER_LEDGER.csv")
    parts_path = root / "PARTITIONS.json"
    oos_start = utc(json.loads(parts_path.read_text(encoding="utf-8"))["oos"]["start_utc"]) if parts_path.is_file() else None
    problems: list[str] = []
    for (arm, partition), path in dirs.items():
        summary = json.loads((path / "SUMMARY.json").read_text(encoding="utf-8"))
        run_id = f"003j-{arm}-{partition}"
        rows = traces.get(run_id, [])
        if not rows:
            problems.append(f"{run_id}: no decision rows")
            continue
        if len(rows) != int(summary["calls"]):
            problems.append(f"{run_id}: {len(rows)} decisions vs calls={summary['calls']}")
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            counts[str(row.get("action"))] += 1
        for action, total in counts.items():
            if int(summary["counters"].get(f"action:{action}", -1)) != total:
                problems.append(f"{run_id}: action {action} {total} vs summary")
        filled = sum(1 for row in rows if row.get("broker_result") == "FILLED")
        if filled != int(summary["fills"]):
            problems.append(f"{run_id}: {filled} filled decisions vs fills={summary['fills']}")
        closed = sum(
            1
            for row in pdf
            if row["arm"] == arm
            and (oos_start is None or (utc(row["entry_utc"]) >= oos_start) == (partition == "oos"))
        )
        if closed != int(summary["closed_trades"]):
            problems.append(f"{run_id}: {closed} ledger closes vs closed_trades={summary['closed_trades']}")
        noop_filled = [row for row in rows if row.get("action") == "NO_TRADE" and row.get("broker_result") == "FILLED"]
        if noop_filled:
            problems.append(f"{run_id}: {len(noop_filled)} NO_TRADE rows claim a fill")
    out.append(
        check(
            "B7_counts_reconcile",
            not problems,
            "; ".join(problems[:6]) or "decisions = actions + no_trade, fills = filled decisions = ledger closes",
        )
    )
    return out


# --------------------------------------------------------------------------- #
# accounting
# --------------------------------------------------------------------------- #


def checks_accounting(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pdf = rows_csv(root / "PAPER_LEDGER.csv")
    parts = json.loads((root / "PARTITIONS.json").read_text(encoding="utf-8")) if (root / "PARTITIONS.json").is_file() else {}
    oos_start = utc(parts["oos"]["start_utc"]) if parts else None

    bad: list[str] = []
    for row in pdf:
        net = float(row["pnl_net_usdt"])
        gross = float(row["gross_pnl_usdt"])
        commissions = float(row["commissions_usdt"])
        execution = float(row.get("execution_cost_usdt") or 0.0)
        reference = float(row.get("reference_gross_pnl_usdt") or gross)
        if abs(net - (gross - commissions)) > TOL and abs(net - (reference - execution - commissions)) > TOL:
            bad.append(f"{row['trade_id']}: net {net} != gross - costs")
        if commissions <= 0:
            bad.append(f"{row['trade_id']}: no commission charged")
    out.append(check("C1_close_nets_its_costs", not bad, "; ".join(bad[:5]) or f"{len(pdf)} closes net every named cost"))

    problems: list[str] = []
    for (arm, partition), path in run_dirs(root).items():
        summary = json.loads((path / "SUMMARY.json").read_text(encoding="utf-8"))
        if oos_start is None:
            selected = [row for row in pdf if row["arm"] == arm]
        elif partition == "oos":
            selected = [row for row in pdf if row["arm"] == arm and utc(row["entry_utc"]) >= oos_start]
        else:
            selected = [row for row in pdf if row["arm"] == arm and utc(row["entry_utc"]) < oos_start]
        net = sum(float(row["pnl_net_usdt"]) for row in selected)
        commissions = sum(float(row["commissions_usdt"]) for row in selected)
        execution = sum(float(row.get("execution_cost_usdt") or 0.0) for row in selected)
        if abs(net - float(summary["net_realised_usdt"])) > 1e-4:
            problems.append(f"{arm}/{partition}: net {net:.6f} vs summary {summary['net_realised_usdt']:.6f}")
        if abs(commissions - float(summary["entry_commissions_realised_usdt"] + summary["exit_commissions_realised_usdt"])) > 1e-4:
            problems.append(f"{arm}/{partition}: commissions do not rebuild")
        if abs(execution - float(summary["execution_costs_realised_usdt"])) > 1e-4:
            problems.append(f"{arm}/{partition}: execution costs do not rebuild")
        equity = float(summary["accounting"]["initial_equity_usdt"]) + net
        if abs(equity - float(summary["final_equity_usdt"])) > 1e-4:
            problems.append(f"{arm}/{partition}: equity != initial + realised")
        if abs(float(summary["marked_equity_usdt"]) - float(summary["final_equity_usdt"])) > 1e-4:
            problems.append(f"{arm}/{partition}: marked equity differs from final equity")
        if int(summary["closed_trades"]) == 0 and net != 0:
            problems.append(f"{arm}/{partition}: zero closes but non-zero PnL")
    out.append(check("C2_summary_rebuilds", not problems, "; ".join(problems[:6]) or "every summary rebuilds from the CSV"))

    # per-asset table, recomputed from the CSV
    table = {(row["arm"], row["partition"], row["symbol"]): row for row in rows_csv(root / "METRICS_BY_ASSET.csv")}
    problems = []
    for (arm, partition, symbol), published in table.items():
        selected = [
            row
            for row in pdf
            if row["arm"] == arm
            and row["symbol"] == symbol
            and (oos_start is None or (utc(row["entry_utc"]) >= oos_start) == (partition == "oos"))
        ]
        if len(selected) != int(published["closes"]):
            problems.append(f"{arm}/{partition}/{symbol}: {len(selected)} closes vs {published['closes']}")
            continue
        net = sum(float(row["pnl_net_usdt"]) for row in selected)
        if abs(net - float(published["net_realised_usdt"])) > 1e-3:
            problems.append(f"{arm}/{partition}/{symbol}: net {net:.4f} vs {published['net_realised_usdt']}")
    out.append(check("C3_per_asset_table", not problems, "; ".join(problems[:5]) or f"{len(table)} rows recomputed"))
    return out


# --------------------------------------------------------------------------- #
# safety
# --------------------------------------------------------------------------- #


def checks_safety(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bad: list[str] = []
    for path in sorted(root.glob("runs/*/*/RUN_META.json")) + sorted(root.glob("live/*/RUN_META.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        if meta.get("live_enabled") not in (False, None):
            bad.append(f"{path.parent.name}: live_enabled={meta.get('live_enabled')}")
        if int(meta.get("live_orders", 0)) != 0:
            bad.append(f"{path.parent.name}: live_orders={meta.get('live_orders')}")
        if meta.get("mode") not in (None, "PAPER"):
            bad.append(f"{path.parent.name}: mode={meta.get('mode')}")
    for path in sorted(root.glob("live/*/SESSION_START.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("live_orders", 0) or 0) != 0:
            bad.append(f"{path.parent.name}: session live_orders={payload.get('live_orders')}")
        if payload.get("live_enabled") not in (False, None):
            bad.append(f"{path.parent.name}: session live_enabled={payload.get('live_enabled')}")
    out.append(check("D1_no_live_session", not bad, "; ".join(bad[:5]) or "every run and session is PAPER with live_orders=0"))

    markers: list[str] = []
    for path in sorted(root.glob("runs/*/*/ledger.jsonl")) + sorted(root.glob("live/*/STREAM.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if '"exchange_order_id"' in line and '"exchange_order_id":null' not in line.replace(" ", ""):
                markers.append(f"{path}: exchange_order_id set")
                break
            if '"live_order"' in line and '"live_order":false' not in line.replace(" ", ""):
                markers.append(f"{path}: live_order marker")
                break
    out.append(check("D2_no_exchange_order_ids", not markers, "; ".join(markers[:5]) or "no exchange order id or live marker in any ledger or stream"))
    return out


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #


def verify(root: Path, heavy: bool = True) -> dict[str, Any]:
    FAILED.clear()
    checks: list[dict[str, Any]] = []
    if not (root / "PAPER_LEDGER.csv").is_file():
        return {"verdict": "BLOCKED", "reason": f"{root} is not an EXP-003J artifact tree", "checks": []}
    checks += checks_dataset(root, heavy)
    checks += checks_ledgers(root)
    checks += checks_pit(root)
    checks += checks_ledger_semantics(root)
    checks += checks_counts(root)
    checks += checks_accounting(root)
    checks += checks_safety(root)
    failed = [item["code"] for item in checks if not item["ok"]]
    return {
        "schema_version": "EXP_003J_EXTERNAL_VERIFICATION_V1",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(root),
        "checks": checks,
        "passed": sum(1 for item in checks if item["ok"]),
        "failed": failed,
        "verdict": "PASS" if not failed else "FAIL",
    }


def _mutations(root: Path) -> dict[str, Any]:
    """Each entry returns a function that corrupts a copy of the tree in one specific way."""

    def forged_live_order(path: Path) -> None:
        target = path / "runs" / "real" / "oos" / "RUN_META.json"
        meta = json.loads(target.read_text(encoding="utf-8"))
        meta["live_orders"] = 1
        target.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def duplicated_fill(path: Path) -> None:
        target = path / "PAPER_LEDGER.csv"
        lines = target.read_text(encoding="utf-8").splitlines()
        target.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")

    def altered_hash(path: Path) -> None:
        target = path / "runs" / "real" / "oos" / "ledger.jsonl"
        lines = target.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[2])
        row["sha256"] = ("f" if row["sha256"][0] != "f" else "0") + row["sha256"][1:]
        lines[2] = json.dumps(row)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def future_data(path: Path) -> None:
        target = path / "runs" / "real" / "oos" / "SIGNAL_TRACE.jsonl"
        lines = target.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["max_input_data_time_ms"] = int(row["decision_time_ms"]) + 300_000
        lines[0] = json.dumps(row)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def noop_as_trade(path: Path) -> None:
        target = path / "DECISION_TRACE.jsonl"
        lines = target.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            row = json.loads(line)
            if row.get("action") == "NO_TRADE":
                row["broker_result"] = "FILLED"
                lines[index] = json.dumps(row)
                break
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def missing_cost(path: Path) -> None:
        target = path / "PAPER_LEDGER.csv"
        rows = rows_csv(target)
        rows[-1]["commissions_usdt"] = "0.0"
        rows[-1]["execution_cost_usdt"] = "0.0"
        rows[-1]["reference_gross_pnl_usdt"] = rows[-1]["gross_pnl_usdt"]
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def pass_with_zero_fills(path: Path) -> None:
        target = path / "runs" / "real" / "oos" / "SUMMARY.json"
        summary = json.loads(target.read_text(encoding="utf-8"))
        summary["closed_trades"] = 0
        summary["fills"] = 0
        summary["counters"]["closed_trades"] = 0
        summary["counters"]["fills"] = 0
        target.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def oos_leakage(path: Path) -> None:
        target = path / "PARTITIONS.json"
        parts = json.loads(target.read_text(encoding="utf-8"))
        parts["oos"]["start_utc"] = "2026-09-01T00:00:00Z"
        target.write_text(json.dumps(parts, indent=2), encoding="utf-8")

    return {
        "forged_live_order": (forged_live_order, "D1_no_live_session"),
        "duplicated_fill": (duplicated_fill, "C2_summary_rebuilds"),
        "altered_hash": (altered_hash, "A3_ledger_chain"),
        "future_data": (future_data, "B1_signal_trace_pit"),
        "noop_as_trade": (noop_as_trade, "B7_counts_reconcile"),
        "missing_cost": (missing_cost, "C1_close_nets_its_costs"),
        "pass_with_zero_fills": (pass_with_zero_fills, "C2_summary_rebuilds"),
        "oos_leakage": (oos_leakage, "B6_no_oos_leakage"),
    }


def run_negative_controls(root: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    scratch = Path(tempfile.mkdtemp(prefix="003j-negative-"))
    try:
        for name, (mutate, expected) in _mutations(root).items():
            target = scratch / name
            shutil.copytree(root, target)
            mutate(target)
            outcome = verify(target, heavy=False)
            detected = expected in outcome["failed"]
            results.append(
                {
                    "control": name,
                    "expected_check": expected,
                    "detected": detected,
                    "failed_checks": outcome["failed"],
                }
            )
            shutil.rmtree(target, ignore_errors=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {
        "controls": results,
        "detected": sum(1 for item in results if item["detected"]),
        "total": len(results),
        "false_success": sum(1 for item in results if not item["detected"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--light", action="store_true", help="skip the 259k-minute dataset re-read")
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = verify(root, heavy=not args.light)
    if args.negative_controls:
        report["negative_controls"] = run_negative_controls(root)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({key: report[key] for key in ("verdict", "passed", "failed") if key in report}, indent=2))
    for item in report.get("checks", []):
        print(f"[{'PASS' if item['ok'] else 'FAIL'}] {item['code']}: {item['detail']}")
    if "negative_controls" in report:
        controls = report["negative_controls"]
        print(f"negative controls detected: {controls['detected']}/{controls['total']}, false_success={controls['false_success']}")
        for item in controls["controls"]:
            print(f"  [{'OK' if item['detected'] else 'MISSED'}] {item['control']} -> {item['expected_check']}")
        if controls["false_success"]:
            return 1
    if report.get("verdict") == "BLOCKED":
        return 2
    return 0 if not report.get("failed") else 1


if __name__ == "__main__":
    sys.exit(main())
