#!/usr/bin/env python3
"""WP-051-02C — recompute EXP-004A admission under the corrected rule, without touching evidence.

The recorded ledger is append-only and is **not** rewritten. This script reads each record's
attested byte prefix, recomputes the verdict under ``RULE_VERSION`` (every stored bar must be closed
and inside its bound), and writes a versioned sidecar that keeps both readings side by side:

    recorded_verdict   what the old rule sealed, preserved verbatim
    corrected_verdict  what RFC-050 section 3 requires over the same bytes
    runtime_verdict    what the corrected ``classify_day`` returns over the live store today

A day is only reported as corrected when all three agree on the rule and ``runtime == corrected``.
Any disagreement is data, not something to smooth away.

Output: ``docs/agentic/exp004a/wp051_02c/WP_051_02C_RECALCULATION.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LEDGERS = {
    "1h": REPO / "data" / "exp004a" / "admission_1h.jsonl",
    "1h+15m": REPO / "data" / "exp004a" / "admission_1h+15m.jsonl",
}
STORE = REPO / "data" / "forward" / "edge03"
OUT = REPO / "docs" / "agentic" / "exp004a" / "wp051_02c" / "WP_051_02C_RECALCULATION.json"
DAY_MS = 86_400_000
INTERVAL_MS = {"1h": 3_600_000, "15m": 900_000}
COVERAGE = 0.90
DEFAULT_BOUNDS = {"1h": 7_200_000, "15m": 1_800_000}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path, limit: int | None = None) -> str:
    data = path.read_bytes()
    return sha256(data if limit is None else data[:limit])


def read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(ms: int) -> str:
    return iso(ms)[:10]


def classify(rows: Sequence[dict[str, Any]]) -> str:
    """RFC-050 section 3 under the corrected rule, from counts already computed per series."""
    if any(row["duplicates"] > 0 for row in rows):
        return "INCOMPLETE"
    if any(row["stored_coverage"] < COVERAGE for row in rows):
        return "INCOMPLETE"
    if all(row["stored"] > 0 and row["timely"] == row["stored"] for row in rows):
        return "PROSPECTIVELY_OBSERVED"
    return "DENSE_BUT_BACKFILLED"


def recompute_record(record: dict[str, Any]) -> dict[str, Any]:
    day = str(record["day"])
    bounds = {str(k): int(v) for k, v in record["lag_bounds_ms"].items()}
    series: dict[str, Any] = {}
    late_bars: list[dict[str, Any]] = []
    for key, seal in sorted(record["series"].items()):
        interval, _, asset = key.partition(":")
        path = STORE / interval / f"{asset}.jsonl"
        byte_end = int(seal.get("byte_end") or 0)
        prefix = path.read_bytes()[:byte_end] if byte_end else b""
        digest_ok = bool(seal.get("sha256")) and sha256(prefix) == seal["sha256"]
        bars = []
        if prefix:
            for line in prefix.split(b"\n"):
                if line.strip():
                    bars.append(json.loads(line))
        day_bars = [bar for bar in bars if day_of(int(bar["ts"])) == day]
        span = INTERVAL_MS[interval]
        bound = bounds[interval]
        timely = 0
        for bar in day_bars:
            lag = int(bar["fetched_at_ms"]) - (int(bar["ts"]) + span)
            if bool(bar.get("closed", False)) and 0 <= lag <= bound:
                timely += 1
            else:
                late_bars.append(
                    {
                        "asset": asset,
                        "interval": interval,
                        "bar_open_utc": iso(int(bar["ts"])),
                        "fetched_at_utc": iso(int(bar["fetched_at_ms"])),
                        "lag_seconds": round(lag / 1000.0, 3),
                        "bound_seconds": bound / 1000.0,
                        "closed": bool(bar.get("closed", False)),
                    }
                )
        duplicates = len(day_bars) - len({int(bar["ts"]) for bar in day_bars})
        series[key] = {
            "stored": len(day_bars),
            "timely": timely,
            "late": len(day_bars) - timely,
            "duplicates": duplicates,
            "stored_coverage": round(len(day_bars) / (DAY_MS // span), 6),
            "prospective_coverage": round(timely / (DAY_MS // span), 6),
            "recorded_stored_bars": seal.get("stored_bars"),
            "recorded_prospectively_observed_bars": seal.get("prospectively_observed_bars"),
            "recorded_sha256": seal.get("sha256"),
            "prefix_digest_ok": digest_ok,
        }
    corrected = classify(list(series.values()))
    return {
        "day": day,
        "lane": record.get("lane"),
        "recorded_verdict": record.get("class"),
        "recorded_admissible": bool(record.get("admissible")),
        "corrected_verdict": corrected,
        "corrected_admissible": corrected == "PROSPECTIVELY_OBSERVED",
        "changed": corrected != record.get("class"),
        "series": series,
        "late_bars": late_bars,
    }


def git_head() -> str:
    import subprocess

    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                          text=True, check=False).stdout.strip()


def runtime_verdicts(days: Sequence[str]) -> dict[str, Any]:
    """Ask the corrected runtime directly, over the live store, for the same days."""
    from trading_bot.research.prospective.admission import RULE_VERSION, classify_day
    from trading_bot.research.prospective.store import index_series

    indexes = {
        interval: [index_series(STORE / interval / f"{asset}.jsonl", asset, interval)
                   for asset in ("BTC", "ETH", "SOL")]
        for interval in ("1h", "15m")
    }
    out: dict[str, Any] = {"rule_version": RULE_VERSION}
    for day in days:
        out[day] = {
            "1h": classify_day(day, indexes["1h"], lag_bounds={"1h": DEFAULT_BOUNDS["1h"]}).classification,
            "1h+15m": classify_day(
                day,
                indexes["1h"] + indexes["15m"],
                lag_bounds={"1h": DEFAULT_BOUNDS["1h"], "15m": DEFAULT_BOUNDS["15m"]},
            ).classification,
        }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    lanes: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for lane, path in LEDGERS.items():
        records = read_lines(path)
        inputs.append({"path": str(path.relative_to(REPO)).replace("\\", "/"),
                       "sha256": digest_file(path), "bytes": path.stat().st_size})
        rows = []
        for record in records:
            row = recompute_record(record)
            row["lane"] = lane
            rows.append(row)
        for row in rows:
            all_rows.append(row)
        recorded = Counter(row["recorded_verdict"] for row in rows)
        corrected = Counter(row["corrected_verdict"] for row in rows)
        lanes[lane] = {
            "records": len(rows),
            "recorded_classes": dict(sorted(recorded.items())),
            "corrected_classes": dict(sorted(corrected.items())),
            "recorded_admissible": recorded.get("PROSPECTIVELY_OBSERVED", 0),
            "corrected_admissible": corrected.get("PROSPECTIVELY_OBSERVED", 0),
            "changed_days": [row["day"] for row in rows if row["changed"]],
        }

    changed = [row for row in all_rows if row["changed"]]
    days = sorted({row["day"] for row in changed})
    runtime = runtime_verdicts(days)
    runtime_mismatch = [
        {"day": row["day"], "lane": row["lane"], "corrected": row["corrected_verdict"],
         "runtime": runtime[row["day"]][row["lane"]]}
        for row in changed
        if runtime[row["day"]][row["lane"]] != row["corrected_verdict"]
    ]

    capture_start = "2026-10-22"
    payload = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": "wp051-02c/EXP-004A/2026-10-21",
        "code_commit": git_head(),
        "rule_version": runtime["rule_version"],
        "rule": {
            "coverage": "stored_bars / expected_bars >= 0.90 (presence, unchanged)",
            "lag": "every stored bar is closed and 0 <= fetched_at_ms - (ts + interval) <= lag_bound (universal, corrected)",
            "absence_vs_lateness": "absence is judged by coverage; lateness is never given the 10 % budget",
            "duplicates": "two records for one open instant make the day INCOMPLETE (fail closed)",
        },
        "inputs": inputs,
        "lanes": lanes,
        "changed": [
            {
                "day": row["day"],
                "lane": row["lane"],
                "recorded_verdict": row["recorded_verdict"],
                "corrected_verdict": row["corrected_verdict"],
                "runtime_verdict": runtime[row["day"]][row["lane"]],
                "before_capture_start": row["day"] < capture_start,
                "series": row["series"],
                "late_bars": row["late_bars"],
            }
            for row in changed
        ],
        "runtime": runtime,
        "runtime_mismatch": runtime_mismatch,
        "summary": {
            "records": len(all_rows),
            "changed": len(changed),
            "changed_days": days,
            "changed_before_capture_start": sum(1 for row in changed if row["day"] < capture_start),
            "changed_inside_capture_window": sum(1 for row in changed if row["day"] >= capture_start),
            "runtime_agrees_with_sidecar": not runtime_mismatch,
            "recorded_admissible_total": sum(lanes[lane]["recorded_admissible"] for lane in lanes),
            "corrected_admissible_total": sum(lanes[lane]["corrected_admissible"] for lane in lanes),
        },
        "immutability": {
            "ledger_rewritten": False,
            "day_resealed": False,
            "store_modified": False,
            "note": "the recorded verdicts above are read, not replaced; the sidecar is the new evidence",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    return 0 if not runtime_mismatch else 1


if __name__ == "__main__":
    raise SystemExit(main())
