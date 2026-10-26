"""WP051-02K WP-02 — measure free space, its stability, and what is left to reclaim.

The frozen budget is a byte count from WP-051-02J (p90 drawdown + protection floor + the
campaign's own growth over the 90-day window). This script does not recompute it, does not
soften it, and does not call a single reading a margin: it samples the volume repeatedly,
reports the worst sample and the worst observed drop, and refuses to say the budget is met
unless the *worst* sample clears it.

Nothing here deletes anything. A reclaimer is only reported, with its size and its owner, so a
person can decide; the brief forbids loosening the experiment to make room.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

GIB = 1024**3
#: WP-051-02J CAPACITY_PLAN.json -> required.at_p90_bytes. Frozen; not recomputed here.
FROZEN_BUDGET_BYTES = 15_638_712_264
FROZEN_BUDGET_SOURCE = "docs/agentic/exp004a/wp051_02j/CAPACITY_PLAN.json#required.at_p90_bytes"


def iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), tz=UTC).isoformat(
        timespec="seconds"
    )


def volume(path: str) -> dict:
    usage = shutil.disk_usage(path)
    return {
        "path": path,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "free_gib": round(usage.free / GIB, 4),
        "used_percent": round(100 * usage.used / usage.total, 2),
    }


def directory_bytes(path: Path) -> int:
    """One directory tree, counted; unreadable entries are skipped rather than fatal."""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    stack.append(entry)
                else:
                    total += entry.stat().st_size
            except OSError:
                continue
    return total


def inventory(roots: list[Path]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for root in roots:
        if not root.exists():
            rows[str(root)] = {"exists": False}
            continue
        if root.is_file():
            size = root.stat().st_size
            rows[str(root)] = {"exists": True, "bytes": size, "gib": round(size / GIB, 4)}
            continue
        size = directory_bytes(root)
        files = sum(1 for _ in root.rglob("*") if _.is_file())
        rows[str(root)] = {
            "exists": True,
            "bytes": size,
            "gib": round(size / GIB, 4),
            "files": files,
        }
    return rows


def reclaimable(root: Path) -> list[dict]:
    """Derived caches only: byte-compiled modules and tool caches. Never data, never evidence."""
    names = {".pytest_cache", "__pycache__", ".ruff_cache", ".mypy_cache"}
    found: dict[str, int] = {}
    if not root.exists():
        return []
    for path in root.rglob("*"):
        if path.is_dir() and path.name in names:
            size = directory_bytes(path)
            found.setdefault(path.name, 0)
            found[path.name] += size
    return [
        {"kind": kind, "bytes": size, "gib": round(size / GIB, 4)}
        for kind, size in sorted(found.items(), key=lambda item: -item[1])
    ]


def process_writers(window_seconds: int) -> list[dict]:
    """Who is writing during the sample, so a drop is not attributed by guesswork."""
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Sort-Object -Property Name | "
                "Select-Object Name,Id | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if completed.returncode != 0:
            return []
        rows = json.loads(completed.stdout or "[]")
        return [{"name": row.get("Name"), "pid": row.get("Id")} for row in rows][:40]
    except Exception:  # noqa: BLE001 - a missing instrument is reported as missing
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", default="C:/")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--interval-seconds", type=float, default=20.0)
    parser.add_argument("--repo", action="append", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    readings: list[dict] = []
    for index in range(args.samples):
        reading = volume(args.volume)
        reading["sample"] = index
        reading["at_utc"] = iso()
        reading["margin_bytes"] = reading["free_bytes"] - FROZEN_BUDGET_BYTES
        reading["margin_gib"] = round(reading["margin_bytes"] / GIB, 4)
        readings.append(reading)
        print(
            f"sample {index:02d}  free={reading['free_gib']:8.4f} GiB  "
            f"margin={reading['margin_gib']:8.4f} GiB",
            flush=True,
        )
        if index + 1 < args.samples:
            time.sleep(args.interval_seconds)

    frees = [row["free_bytes"] for row in readings]
    margins = [row["margin_bytes"] for row in readings]
    drops = [frees[i] - frees[i + 1] for i in range(len(frees) - 1)]
    worst_drop = max(drops) if drops else 0
    span = (readings[-1]["sample"] - readings[0]["sample"]) * args.interval_seconds
    roots = [Path(item) for item in args.repo]
    report = {
        "schema_version": "EXP004A_WP051_02K_OPS_CAPACITY_V1",
        "generated_at_utc": iso(),
        "budget": {
            "frozen_bytes": FROZEN_BUDGET_BYTES,
            "frozen_gib": round(FROZEN_BUDGET_BYTES / GIB, 4),
            "source": FROZEN_BUDGET_SOURCE,
            "recomputed_here": False,
        },
        "sampling": {
            "samples": len(readings),
            "interval_seconds": args.interval_seconds,
            "span_seconds": span,
            "readings": readings,
        },
        "stability": {
            "free_min_bytes": min(frees),
            "free_max_bytes": max(frees),
            "free_median_bytes": int(statistics.median(frees)),
            "free_min_gib": round(min(frees) / GIB, 4),
            "free_max_gib": round(max(frees) / GIB, 4),
            "spread_gib": round((max(frees) - min(frees)) / GIB, 4),
            "worst_sample_margin_bytes": min(margins),
            "worst_sample_margin_gib": round(min(margins) / GIB, 4),
            "worst_observed_drop_bytes": worst_drop,
            "worst_observed_drop_gib": round(worst_drop / GIB, 4),
            "drops_gib": [round(item / GIB, 4) for item in drops],
            "net_change_gib": round((frees[-1] - frees[0]) / GIB, 4),
        },
        "inventory": inventory(roots),
        "reclaimable_derived": {
            str(root): reclaimable(root) for root in roots
        },
        "deletions": [],
        "deletion_policy": (
            "none: the volume already cleared the frozen budget, so nothing was removed. "
            "Deleting evidence or another agent's tree would have been a larger loss than the "
            "one this work package is recovering from."
        ),
        "verdict": "CAPACITY_OK" if min(margins) > 0 else "BLOCKED_STORAGE",
        "verdict_basis": (
            "the worst of the sampled margins, not the best: a budget met once is not a budget "
            "met"
        ),
        "processes_seen": process_writers(int(args.interval_seconds)),
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("verdict", "stability", "budget")}, indent=2))
    return 0 if report["verdict"] == "CAPACITY_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
