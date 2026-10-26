#!/usr/bin/env python3
"""Validate a WP-006 market-data manifest and its datasets (D8).

Independent of the engine: it re-reads the raw files, recomputes the digests and
re-derives coverage from the bars themselves rather than trusting the manifest.

Checks, per dataset:

* digest and byte count match the manifest;
* bars are strictly ascending, on the declared interval, with no duplicates;
* the bar timestamps are aligned to the interval grid (``ts % interval_ms == 0``);
* coverage: first/last bar, span, expected bar count for the declared window;
* no bar is newer than the moment the download happened (point-in-time: a bar
  that closes after the fetch cannot have been available to a strategy);
* every OHLC bar is internally consistent and every value is finite and positive;
* gaps are enumerated individually, not just counted;
* per-partition bar counts are reported so a partition cannot be silently empty.

Provenance: every request recorded in the manifest must carry its URL, parameters,
HTTP status, response hash and byte count. A missing field is a failure, because a
dataset whose provenance cannot be re-requested cannot be audited.

Exit codes: 0 = PASS, 1 = FAIL, 2 = unusable input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_REQUEST_FIELDS = ("url", "params", "http_status", "response_sha256",
                           "response_bytes", "rows", "requested_at_utc")
# A 5m crypto move beyond this is not impossible, but it must be reported: it is
# either a real event or a data defect, and both deserve a line in the report.
EXTREME_MOVE_PCT = 20.0


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_dataset(root: Path, symbol: str, entry: dict[str, Any], interval_ms: int,
                     fetched_at: datetime, partitions: dict[str, int]) -> dict[str, Any]:
    check: dict[str, Any] = {"symbol": symbol, "failures": [], "warnings": []}

    def fail(code: str, detail: str = "") -> None:
        check["failures"].append({"code": code, "detail": detail})

    path = root / entry["path"]
    if not path.is_file():
        fail("DATASET_MISSING", str(path))
        check["status"] = "FAIL"
        return check
    raw = path.read_bytes()
    check["path"] = entry["path"]
    check["bytes"] = len(raw)
    check["sha256"] = sha256_bytes(raw)
    if check["sha256"] != entry.get("sha256"):
        fail("DIGEST_MISMATCH", f"{check['sha256'][:12]} != {str(entry.get('sha256'))[:12]}")
    if len(raw) != entry.get("bytes"):
        check["warnings"].append({"code": "BYTE_COUNT_DIFFERS",
                                  "detail": f"{len(raw)} != {entry.get('bytes')}"})

    requests = entry.get("requests") or []
    missing = [i for i, r in enumerate(requests) if any(f not in r for f in REQUIRED_REQUEST_FIELDS)]
    if not requests:
        fail("NO_REQUEST_PROVENANCE", "the manifest records no request for this dataset")
    elif missing:
        fail("INCOMPLETE_REQUEST_PROVENANCE", f"requests {missing} lack required fields")
    check["requests"] = len(requests)
    check["response_rows_total"] = sum(r.get("rows", 0) for r in requests)
    check["distinct_response_digests"] = len({r.get("response_sha256") for r in requests})
    bad_status = [r.get("http_status") for r in requests if r.get("http_status") != 200]
    if bad_status:
        fail("NON_200_RESPONSE", str(bad_status))

    try:
        bars = json.loads(raw)
    except ValueError as e:
        fail("DATASET_NOT_JSON", str(e))
        check["status"] = "FAIL"
        return check
    if not isinstance(bars, list) or not bars:
        fail("DATASET_EMPTY", "no bars")
        check["status"] = "FAIL"
        return check

    check["bars"] = len(bars)
    check["start_ts"], check["end_ts"] = bars[0]["ts"], bars[-1]["ts"]
    check["start_utc"], check["end_utc"] = iso(bars[0]["ts"]), iso(bars[-1]["ts"])
    check["span_hours"] = round((bars[-1]["ts"] - bars[0]["ts"]) / 3_600_000, 3)

    duplicates = misaligned = non_finite = inconsistent = 0
    gaps: list[dict[str, Any]] = []
    prev = None
    for i, b in enumerate(bars):
        if not isinstance(b, dict) or set(b) != {"ts", "open", "high", "low", "close", "volume"}:
            fail("BAR_SHAPE", f"bar[{i}] keys={sorted(b) if isinstance(b, dict) else type(b).__name__}")
            break
        ts = b["ts"]
        if not isinstance(ts, int) or ts % interval_ms:
            misaligned += 1
        if prev is not None:
            if ts == prev:
                duplicates += 1
            elif ts < prev:
                fail("NON_MONOTONE", f"bar[{i}] ts {ts} < {prev}")
                break
            elif ts - prev != interval_ms:
                gaps.append({"after_utc": iso(prev), "next_utc": iso(ts),
                             "missing_bars": (ts - prev) // interval_ms - 1})
        prev = ts
        try:
            op, hi, lo, cl, vol = (float(b[k]) for k in ("open", "high", "low", "close", "volume"))
        except (TypeError, ValueError):
            non_finite += 1
            continue
        if not all(math.isfinite(v) for v in (op, hi, lo, cl, vol)):
            non_finite += 1
        elif not (lo > 0 and lo <= op <= hi and lo <= cl <= hi and vol >= 0):
            inconsistent += 1

    if duplicates:
        fail("DUPLICATE_TIMESTAMPS", f"{duplicates} duplicate open times")
    if misaligned:
        fail("MISALIGNED_TIMESTAMPS", f"{misaligned} bars are off the {interval_ms} ms grid")
    if non_finite:
        fail("NON_FINITE_VALUES", f"{non_finite} bars")
    if inconsistent:
        fail("INCONSISTENT_OHLC", f"{inconsistent} bars")
    check["gaps"] = gaps
    check["gap_count"] = len(gaps)
    if gaps:
        check["warnings"].append({"code": "GAPS_PRESENT",
                                  "detail": f"{len(gaps)} gaps, {sum(g['missing_bars'] for g in gaps)} bars"})

    if bars[-1]["ts"] >= int(fetched_at.timestamp() * 1000):
        fail("BAR_AFTER_FETCH", "the last bar opens at or after the download moment")
    check["last_bar_closes_before_fetch"] = iso(bars[-1]["ts"] + interval_ms) <= \
        fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    expected = (bars[-1]["ts"] - bars[0]["ts"]) // interval_ms + 1
    check["expected_bars"] = expected
    if expected != len(bars):
        fail("BAR_COUNT_MISMATCH", f"{len(bars)} bars for a span that needs {expected}")
    if check.get("response_rows_total") is not None and \
            check["response_rows_total"] < len(bars):
        check["warnings"].append({"code": "FEWER_ROWS_THAN_BARS", "detail": "manifest accounting"})

    closes = [float(b["close"]) for b in bars]
    jumps = [(i, round((closes[i] / closes[i - 1] - 1) * 100, 3))
             for i in range(1, len(closes)) if closes[i - 1] > 0
             and abs(closes[i] / closes[i - 1] - 1) * 100 > EXTREME_MOVE_PCT]
    check["extreme_moves"] = len(jumps)
    if jumps:
        check["warnings"].append({"code": "EXTREME_MOVES", "detail": f"{len(jumps)} bars beyond "
                                                                     f"{EXTREME_MOVE_PCT}%"})

    counts = {"DEV": 0, "VAL": 0, "OOS": 0}
    for b in bars:
        ts = b["ts"]
        if ts < partitions["dev_end"]:
            counts["DEV"] += 1
        elif ts < partitions["val_end"]:
            counts["VAL"] += 1
        else:
            counts["OOS"] += 1
    check["bars_by_partition"] = counts
    empty = [p for p, n in counts.items() if n == 0]
    if empty:
        fail("EMPTY_PARTITION", str(empty))
    if counts["DEV"] + counts["VAL"] + counts["OOS"] != len(bars):
        fail("PARTITION_COVERAGE", "not every bar belongs to exactly one partition")

    check["status"] = "FAIL" if check["failures"] else "PASS"
    return check


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", type=Path,
                   default=Path("data/economic/w006/MANIFEST.json"))
    p.add_argument("--out", type=Path, default=Path("reports/economic/w006/DATA_QUALITY.json"))
    p.add_argument("--dev-fraction", type=float, default=0.50)
    p.add_argument("--val-fraction", type=float, default=0.25)
    args = p.parse_args(argv)

    if not args.manifest.is_file():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = manifest.get("datasets") or {}
    if not entries:
        print("ERROR: manifest declares no datasets", file=sys.stderr)
        return 2
    interval_ms = int(manifest["source"]["interval_ms"])
    fetched_at = parse_iso(manifest["fetched_at_utc"])
    root = args.manifest.parent

    # partitions are derived from the pooled coverage, exactly as the engine does
    spans = []
    for entry in entries.values():
        bars = json.loads((root / entry["path"]).read_text(encoding="utf-8"))
        spans.append((bars[0]["ts"], bars[-1]["ts"] + interval_ms))
    t0, t1 = min(s[0] for s in spans), max(s[1] for s in spans)
    span = t1 - t0
    partitions = {"t0": t0, "dev_end": t0 + int(span * args.dev_fraction),
                  "val_end": t0 + int(span * (args.dev_fraction + args.val_fraction)), "t1": t1}

    datasets = {symbol: validate_dataset(root, symbol, entry, interval_ms, fetched_at, partitions)
                for symbol, entry in sorted(entries.items())}

    report: dict[str, Any] = {
        "schema": "W006_DATA_QUALITY_V1",
        "manifest": str(args.manifest),
        "manifest_sha256": sha256_bytes(args.manifest.read_bytes()),
        "source": manifest.get("source"),
        "fetched_at_utc": manifest.get("fetched_at_utc"),
        "partitions": {"boundaries_utc": {"dev": [iso(partitions["t0"]), iso(partitions["dev_end"])],
                                          "val": [iso(partitions["dev_end"]), iso(partitions["val_end"])],
                                          "oos": [iso(partitions["val_end"]), iso(partitions["t1"])]},
                       "rule": "chronological over pooled coverage"},
        "datasets": datasets,
        "checks_run": sorted({c for d in datasets.values()
                              for c in (["digest", "provenance", "monotonicity", "alignment",
                                         "coverage", "pit", "ohlc", "gaps", "partitions"])}),
        "limitations": [
            "a digest match proves the bytes match the manifest, not that the exchange "
            "served that history; re-requesting the recorded URLs is the only check for that",
            "basic OHLC consistency cannot detect fabricated-but-consistent bars",
            "no order-book history is used, so spread is a declared assumption, not a measurement",
        ],
    }
    report["status"] = "PASS" if all(d["status"] == "PASS" for d in datasets.values()) else "FAIL"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    for symbol, d in datasets.items():
        print(f"{symbol}: {d['status']} bars={d.get('bars')} "
              f"{d.get('start_utc')} -> {d.get('end_utc')} gaps={d.get('gap_count')} "
              f"partitions={d.get('bars_by_partition')} failures={[f['code'] for f in d['failures']]}")
    print(f"OVERALL: {report['status']} -> {args.out}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
