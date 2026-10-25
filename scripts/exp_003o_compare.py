"""exp_003o_compare — the parity join of EXP-003O.

Two streams of per-instant decisions, produced without reading each other, are joined on
``(cell_id, symbol, decision_ms)``. What the join can say is deliberately narrow and closed:

* a key present in one stream and not the other is a missing or an extra *evaluation*, never
  a silent zero;
* two keys with different states, directions or instants are named by the class that
  describes them, and nothing else;
* two rows that disagree about the window they saw are an input mismatch even when they
  happen to agree about the decision.

There is no numeric tolerance for a decision and no "close enough" bucket. The only
tolerance in the protocol is the absence of one.

Usage
-----
``python scripts/exp_003o_compare.py --original signals/original_evaluations.jsonl.gz \
    --independent signals/independent_evaluations.jsonl.gz``
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    DIFFERENCE_CLASSES,
    OUT,
    PARTITIONS,
    SCHEMA_PARITY,
    iso_ms,
    read_json,
    sha256_file,
    utc_ms,
    write_json,
    write_jsonl_gz,
)

STATE_FIELDS = (
    "state",
    "direction",
    "reason",
    "decision_ms",
    "input_snapshot_hash",
    "parameter_hash",
    "window_first_ms",
    "window_last_ms",
    "window_bars",
    "data_available_ms",
    "bar_open_ms",
    "bar_close_ms",
)


class RowError(AssertionError):
    """A row that cannot be trusted even before it is compared with anything."""


def validate_row(row: dict[str, Any], interval: int) -> None:
    """The row contract, enforced on each stream independently."""

    missing = [field for field in STATE_FIELDS if field not in row]
    if missing:
        raise RowError(f"row lacks {missing}: {row.get('cell_id')}/{row.get('decision_ms')}")
    if row["state"] not in {"SIGNAL", "NO_SIGNAL", "NOT_READY", "NOT_EVALUABLE"}:
        raise RowError(f"unknown state {row['state']!r}")
    if row["state"] == "SIGNAL" and row["direction"] not in {"LONG", "SHORT", "FLAT"}:
        raise RowError(f"SIGNAL without a known direction: {row['direction']!r}")
    if row["state"] != "SIGNAL" and row["direction"] is not None:
        raise RowError(f"{row['state']} carries a direction")
    if row["state"] in {"NOT_READY", "NOT_EVALUABLE"} and not row["reason"]:
        raise RowError(f"{row['state']} without a reason code")
    if int(row["bar_close_ms"]) != int(row["bar_open_ms"]) + interval:
        raise RowError("bar close is not the bar open plus one interval")
    if int(row["decision_ms"]) < int(row["data_available_ms"]):
        raise RowError("the decision precedes its own data")
    if int(row["window_last_ms"]) > int(row["bar_open_ms"]):
        raise RowError("the window reaches past the decision bar")


def _load(
    path: Path,
) -> tuple[dict[str, dict[tuple[str, str, int], dict[str, Any]]], list[tuple[str, str, int]]]:
    """Rows bucketed by cell; a repeated key is counted, never silently overwritten."""

    buckets: dict[str, dict[tuple[str, str, int], dict[str, Any]]] = defaultdict(dict)
    duplicates: list[tuple[str, str, int]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row["cell_id"]), str(row["symbol"]), int(row["decision_ms"]))
            if key in buckets[key[0]]:
                duplicates.append(key)
                continue
            buckets[key[0]][key] = row
    return buckets, duplicates


def classify_pair(original: dict[str, Any], independent: dict[str, Any]) -> str | None:
    """The class of a difference between two rows that share a key, or ``None``."""

    if int(original["decision_ms"]) != int(independent["decision_ms"]):  # pragma: no cover
        return "TIMING_MISMATCH"
    if str(original["parameter_hash"]) != str(independent["parameter_hash"]):
        return "PARAMETER_HASH_MISMATCH"
    if str(original["input_snapshot_hash"]) != str(independent["input_snapshot_hash"]):
        return "INPUT_MISMATCH"
    if str(original["state"]) != str(independent["state"]):
        return "STATE_MISMATCH"
    if (original["direction"] or None) != (independent["direction"] or None):
        return "DIRECTION_MISMATCH"
    for field in ("window_first_ms", "window_last_ms", "window_bars", "data_available_ms"):
        if int(original[field]) != int(independent[field]):
            return "PIT_VIOLATION"
    return None


def _partition(decision_ms: int) -> str:
    for name, (start, end) in PARTITIONS.items():
        if utc_ms(start) <= decision_ms < utc_ms(end):
            return name
    return "OUTSIDE"


def compare(
    protocol: dict[str, Any],
    original_path: Path,
    independent_path: Path,
    out: Path,
    *,
    label: str = "",
    design_sha256: str | None = None,
) -> dict[str, Any]:
    original, duplicate_original = _load(original_path)
    independent, duplicate_independent = _load(independent_path)
    duplicates = [("original", key) for key in duplicate_original] + [
        ("independent", key) for key in duplicate_independent
    ]
    cells = {str(cell["cell_id"]): cell for cell in protocol["cells"]}
    intervals = {
        str(cell["cell_id"]): int(protocol["timeframes_ms"][str(cell["timeframe"])])
        for cell in protocol["cells"]
    }

    violations: list[dict[str, Any]] = []
    for stream, buckets in (("original", original), ("independent", independent)):
        for cell_id, rows in buckets.items():
            interval = intervals.get(cell_id)
            if interval is None:
                violations.append({"stream": stream, "cell_id": cell_id, "error": "unknown cell"})
                continue
            for key, row in rows.items():
                try:
                    validate_row(row, interval)
                except RowError as error:
                    violations.append(
                        {
                            "stream": stream,
                            "cell_id": cell_id,
                            "key": list(key),
                            "error": str(error),
                        }
                    )
                    break

    rows_out: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    class_counts: Counter[str] = Counter()
    per_cell: dict[str, dict[str, Any]] = {}
    for _stream, key in duplicates:
        class_counts["DUPLICATE_KEY"] += 1
        differences.append(
            {
                "cell_id": key[0],
                "symbol": key[1],
                "decision_ms": key[2],
                "decision_utc": iso_ms(key[2]),
                "split": _partition(key[2]),
                "class": "DUPLICATE_KEY",
                "original": None,
                "independent": None,
            }
        )
        if len(examples["DUPLICATE_KEY"]) < 3:
            examples["DUPLICATE_KEY"].append(differences[-1])

    for cell_id in cells:
        interval = intervals[cell_id]
        left = original.get(cell_id, {})
        right = independent.get(cell_id, {})
        keys = sorted(set(left) | set(right), key=lambda item: (item[1], item[2]))
        by_symbol: dict[str, Counter[str]] = defaultdict(Counter)
        for key in keys:
            symbol = key[1]
            bucket = by_symbol[symbol]
            a = left.get(key)
            b = right.get(key)
            if a is not None:
                bucket["evaluations_original"] += 1
                bucket[f"state_original_{a['state']}"] += 1
                if a["state"] == "SIGNAL":
                    bucket["signals_original"] += 1
            if b is not None:
                bucket["evaluations_independent"] += 1
                bucket[f"state_independent_{b['state']}"] += 1
                if b["state"] == "SIGNAL":
                    bucket["signals_independent"] += 1
            if a is None or b is None:
                difference = "MISSING_EVALUATION" if b is None else "EXTRA_EVALUATION"
                if (a is not None and a["state"] == "SIGNAL") or (
                    b is not None and b["state"] == "SIGNAL"
                ):
                    difference = "MISSING_SIGNAL" if b is None else "EXTRA_SIGNAL"
                class_counts[difference] += 1
                bucket[difference.lower()] += 1
                bucket["mismatches"] += 1
                record = {
                    "cell_id": cell_id,
                    "symbol": symbol,
                    "decision_ms": key[2],
                    "decision_utc": iso_ms(key[2]),
                    "split": _partition(key[2]),
                    "class": difference,
                    "original": None
                    if a is None
                    else {k: a[k] for k in ("state", "direction", "reason")},
                    "independent": None
                    if b is None
                    else {k: b[k] for k in ("state", "direction", "reason")},
                }
                if len(examples[difference]) < 3:
                    examples[difference].append(record)
                differences.append(record)
                continue
            bucket["matched"] += 1
            pair_difference = classify_pair(a, b)
            if pair_difference is not None:
                class_counts[pair_difference] += 1
                bucket[pair_difference.lower()] += 1
                bucket["mismatches"] += 1
                record = {
                    "cell_id": cell_id,
                    "symbol": symbol,
                    "decision_ms": key[2],
                    "decision_utc": iso_ms(key[2]),
                    "split": _partition(key[2]),
                    "class": pair_difference,
                    "original": {
                        "state": a["state"],
                        "direction": a["direction"],
                        "reason": a["reason"],
                        "window_last_ms": a["window_last_ms"],
                        "input_snapshot_hash": str(a["input_snapshot_hash"])[:16],
                    },
                    "independent": {
                        "state": b["state"],
                        "direction": b["direction"],
                        "reason": b["reason"],
                        "window_last_ms": b["window_last_ms"],
                        "input_snapshot_hash": str(b["input_snapshot_hash"])[:16],
                    },
                }
                if len(examples[pair_difference]) < 3:
                    examples[pair_difference].append(record)
                differences.append(record)

        symbol_rows = []
        for symbol in sorted(by_symbol):
            bucket = by_symbol[symbol]
            row = {
                "granularity": "cell_symbol",
                "cell_id": cell_id,
                "lane": cells[cell_id]["lane"],
                "symbol": symbol,
                "evaluations_original": bucket["evaluations_original"],
                "evaluations_independent": bucket["evaluations_independent"],
                "signals_original": bucket["signals_original"],
                "signals_independent": bucket["signals_independent"],
                "matched": bucket["matched"],
                "mismatches": bucket["mismatches"],
                "verdict": "PASS" if bucket["mismatches"] == 0 else "FAIL",
            }
            for name in (
                "missing_evaluation",
                "extra_evaluation",
                "missing_signal",
                "extra_signal",
                "state_mismatch",
                "direction_mismatch",
                "timing_mismatch",
                "pit_violation",
                "input_mismatch",
                "parameter_hash_mismatch",
            ):
                row[name] = bucket[name]
            symbol_rows.append(row)

        combined: Counter[str] = Counter()
        for bucket in by_symbol.values():
            combined.update(bucket)
        cell_row = {
            "granularity": "cell",
            "cell_id": cell_id,
            "lane": cells[cell_id]["lane"],
            "symbol": "ALL",
            "evaluations_original": combined["evaluations_original"],
            "evaluations_independent": combined["evaluations_independent"],
            "signals_original": combined["signals_original"],
            "signals_independent": combined["signals_independent"],
            "matched": combined["matched"],
            "mismatches": combined["mismatches"],
            "verdict": "PASS" if combined["mismatches"] == 0 else "FAIL",
        }
        for name in (
            "missing_evaluation",
            "extra_evaluation",
            "missing_signal",
            "extra_signal",
            "state_mismatch",
            "direction_mismatch",
            "timing_mismatch",
            "pit_violation",
            "input_mismatch",
            "parameter_hash_mismatch",
        ):
            cell_row[name] = combined[name]
        per_cell[cell_id] = {
            "lane": cells[cell_id]["lane"],
            "evaluable": combined["evaluations_original"] > 0,
            "evaluations_original": combined["evaluations_original"],
            "evaluations_independent": combined["evaluations_independent"],
            "signals_original": combined["signals_original"],
            "signals_independent": combined["signals_independent"],
            "matched": combined["matched"],
            "mismatches": combined["mismatches"],
            "verdict": "PASS" if combined["mismatches"] == 0 else "FAIL",
        }
        rows_out.extend(symbol_rows)
        rows_out.append(cell_row)

    mismatches = sum(per_cell[cell]["mismatches"] for cell in per_cell) + len(duplicates)
    keys_original = sum(per_cell[cell]["evaluations_original"] for cell in per_cell)
    keys_independent = sum(per_cell[cell]["evaluations_independent"] for cell in per_cell)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_PARITY,
        "run_id": protocol["run_id"],
        "label": label,
        "design_sha256": design_sha256,
        "inputs": {
            "original": {
                "path": str(original_path.name),
                "sha256": sha256_file(original_path),
                "bytes": original_path.stat().st_size,
            },
            "independent": {
                "path": str(independent_path.name),
                "sha256": sha256_file(independent_path),
                "bytes": independent_path.stat().st_size,
            },
        },
        "cells_total": len(cells),
        "cells_evaluable": sum(1 for cell in per_cell if per_cell[cell]["evaluable"]),
        "evaluations_compared": max(keys_original, keys_independent),
        "evaluations_original": keys_original,
        "evaluations_independent": keys_independent,
        "signals_original": sum(per_cell[cell]["signals_original"] for cell in per_cell),
        "signals_independent": sum(per_cell[cell]["signals_independent"] for cell in per_cell),
        "matched": sum(per_cell[cell]["matched"] for cell in per_cell),
        "mismatches_unexplained": mismatches,
        "differences_by_class": {
            name: class_counts[name] for name in DIFFERENCE_CLASSES if class_counts[name]
        },
        "contract_violations": len(violations),
        "violations": violations[:5],
        "per_cell": per_cell,
        "examples": dict(examples),
        "reconciliation": {
            "sum_cell_keys_original": keys_original,
            "sum_cell_keys_independent": keys_independent,
            "matched_plus_differences": sum(per_cell[cell]["matched"] for cell in per_cell)
            + mismatches,
            "keys_union": max(keys_original, keys_independent),
        },
        "verdict": "PASS" if mismatches == 0 and not violations else "FAIL",
    }

    out.mkdir(parents=True, exist_ok=True)
    name = f"SIGNAL_PARITY{('_' + label) if label else ''}"
    write_json(out / f"{name}_SUMMARY.json", summary)
    write_jsonl_gz(
        out / f"parity_differences{('_' + label) if label else ''}.jsonl.gz", differences
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows_out[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows_out)
    (out / f"{name}.csv").write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O parity comparator")
    parser.add_argument("--protocol", default=str(OUT / "design" / "PROTOCOL.json"))
    parser.add_argument(
        "--original", default=str(OUT / "signals" / "original_evaluations.jsonl.gz")
    )
    parser.add_argument(
        "--independent", default=str(OUT / "signals" / "independent_evaluations.jsonl.gz")
    )
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    protocol = read_json(Path(args.protocol))
    protocol_path = Path(args.protocol)
    summary = compare(
        protocol,
        Path(args.original),
        Path(args.independent),
        Path(args.out),
        label=args.label,
        design_sha256=sha256_file(protocol_path),
    )
    print(
        f"[003o-compare] verdict={summary['verdict']} compared={summary['evaluations_compared']} "
        f"signals={summary['signals_original']}/{summary['signals_independent']} "
        f"mismatches={summary['mismatches_unexplained']} "
        f"classes={summary['differences_by_class']} violations={summary['contract_violations']}"
    )
    return 0 if summary["verdict"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
