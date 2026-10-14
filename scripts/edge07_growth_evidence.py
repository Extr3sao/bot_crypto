#!/usr/bin/env python
"""WP-EDGE-07 Track A — who is writing to the volume right now, and where.

WP-EDGE-06 showed the volume losing several GiB in minutes while the repository gained
nothing. "Something outside the repository" is a diagnosis; this tool is the evidence behind
it, and it answers three questions that a size table cannot:

1. **Which directories grew in the last window** — files with a recent modification time,
   grouped by the first components below the user profile, with the bytes and the file count
   each group contributed;
2. **Which kinds of file they are** — by extension, because a directory of `.log` and a
   directory of `.dll` are different findings;
3. **Which processes are running from there** — the executable path and command line of every
   running process whose image lives under the profile, which is what turns "a directory grew"
   into "this application is writing".

Read-only, and destructive of nothing: it opens no file for writing outside its own artefact,
it deletes nothing, and it says so. A window is declared in minutes and reported with the
instant it was measured at, because a growth reading without its window is a number that can be
argued with.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3
MIB = 1024**2

SCHEMA_VERSION = "EDGE07_GROWTH_EVIDENCE_V1"

#: The runtime's own thresholds, read from the module that enforces them rather than typed
#: again here: this artefact is the one an operator reads before deciding what to free.
THRESHOLD_SOURCE = "src/trading_bot/research/disk_space.py"

#: Seconds the walk may spend. The profile holds hundreds of thousands of files and a walk
#: without a budget is a walk that can run until the disk is full.
DEFAULT_BUDGET_SECONDS = 90.0


def thresholds() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from trading_bot.research import disk_budget, disk_space

    return {
        "healthy_free_bytes": int(disk_space.HEALTHY_FREE_BYTES),
        "critical_free_bytes": int(disk_space.CRITICAL_FREE_BYTES),
        "launcher_reserve_bytes": int(disk_budget.DEFAULT_RESERVE_BYTES),
        "stress_multiplier": float(disk_budget.DEFAULT_STRESS_MULTIPLIER),
        "source": THRESHOLD_SOURCE,
    }


def group_key(relative: str, depth: int = 3) -> str:
    parts = Path(relative).parts
    return "/".join(parts[:depth]) if parts else "(root)"


def walk_recent(
    root: Path, *, window_minutes: float, budget_seconds: float, depth: int = 3
) -> dict[str, Any]:
    """Files under ``root`` modified inside the window, grouped and summed."""
    cutoff = time.time() - window_minutes * 60.0
    started = time.monotonic()
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"bytes": 0, "files": 0, "newest_mtime": 0.0, "largest": []}
    )
    by_extension: dict[str, dict[str, Any]] = defaultdict(lambda: {"bytes": 0, "files": 0})
    truncated = False
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        dirnames.sort()
        if time.monotonic() - started > budget_seconds:
            truncated = True
            break
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            scanned += 1
            if stat.st_mtime < cutoff:
                continue
            relative = os.path.relpath(path, root)
            key = group_key(relative, depth)
            row = groups[key]
            row["bytes"] += stat.st_size
            row["files"] += 1
            row["newest_mtime"] = max(row["newest_mtime"], stat.st_mtime)
            row["largest"].append((stat.st_size, relative))
            ext = Path(name).suffix.lower() or "(none)"
            by_extension[ext]["bytes"] += stat.st_size
            by_extension[ext]["files"] += 1
    for row in groups.values():
        row["largest"] = sorted(row["largest"], reverse=True)[:5]
        row["newest_utc"] = (
            datetime.fromtimestamp(row["newest_mtime"], tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if row["newest_mtime"]
            else None
        )
        row.pop("newest_mtime", None)
    return {
        "root": str(root),
        "window_minutes": window_minutes,
        "scanned_files": scanned,
        "measured": not truncated,
        "walk_seconds": round(time.monotonic() - started, 2),
        "groups": groups,
        "by_extension": by_extension,
    }


def running_processes() -> dict[str, Any]:
    """Every process whose image or command line mentions the user profile (read-only)."""
    home = str(Path.home()).lower()
    rows: list[dict[str, Any]] = []
    try:
        # Not a project dependency: present on some hosts, absent on others, and never assumed.
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        psutil = None
    if psutil is not None:
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
            try:
                info = proc.info
            except Exception:  # pragma: no cover - a process can exit mid-iteration
                continue
            blob = f"{info.get('exe') or ''} {' '.join(info.get('cmdline') or [])}".lower()
            if home in blob:
                rows.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name"),
                        "exe": info.get("exe"),
                        "cmdline": (info.get("cmdline") or [])[:6],
                        "started_utc": (
                            datetime.fromtimestamp(info["create_time"], tz=UTC).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                            if info.get("create_time")
                            else None
                        ),
                    }
                )
        source = "psutil"
    else:
        out = subprocess.run(["ps", "-W"], capture_output=True, text=True, check=False).stdout
        for line in out.splitlines():
            if home.split("\\")[-1] in line.lower() or "appdata" in line.lower():
                rows.append({"raw": line.strip()[:240]})
        source = "ps -W (psutil unavailable)"
    return {
        "source": source,
        "count": len(rows),
        "processes": sorted(rows, key=lambda r: r.get("name") or ""),
    }


def build(*, window_minutes: float, budget_seconds: float, roots: list[Path]) -> dict[str, Any]:
    instant = datetime.now(tz=UTC)
    usage = shutil.disk_usage(REPO_ROOT)
    limits = thresholds()
    per_root = [
        {
            "name": str(path),
            **walk_recent(path, window_minutes=window_minutes, budget_seconds=budget_seconds),
        }
        for path in roots
        if path.exists()
    ]
    shortfall_critical = max(0, limits["critical_free_bytes"] - usage.free)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"EDGE07-GROWTH-{instant.strftime('%Y%m%dT%H%M%SZ')}",
        "as_of_utc": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": os.environ.get("COMPUTERNAME", "unknown"),
        "volume": {
            "free_bytes": int(usage.free),
            "free_gib": round(usage.free / GIB, 3),
            "total_gib": round(usage.total / GIB, 1),
            "verdict": (
                "BELOW_CRITICAL"
                if usage.free < limits["critical_free_bytes"]
                else "ABOVE_CRITICAL_BELOW_HEALTHY"
                if usage.free < limits["healthy_free_bytes"]
                else "HEALTHY"
            ),
        },
        "thresholds": limits,
        "headroom": {
            "bytes_to_resume_ingestion": shortfall_critical,
            "gib_to_resume_ingestion": round(shortfall_critical / GIB, 3),
            "bytes_to_reach_healthy": max(0, limits["healthy_free_bytes"] - usage.free),
            "gib_to_reach_healthy": round(
                max(0, limits["healthy_free_bytes"] - usage.free) / GIB, 3
            ),
            "reading": (
                "the lane refuses a tick below the critical floor and the heavy publication waits "
                "below the healthy floor; the numbers above are the distance to each, measured now"
            ),
        },
        "growth": per_root,
        "processes": running_processes(),
        "read_only": True,
        "deleted_anything": False,
        "method": (
            f"files whose modification time falls inside the last {window_minutes:.0f} minutes, "
            f"walked with a {budget_seconds:.0f}s budget per root; a truncated walk says so and "
            "its bytes are a floor"
        ),
    }


def render(payload: dict[str, Any]) -> str:
    volume = payload["volume"]
    lines = [
        "# WP-EDGE-07 — who is growing the volume, and what is the share of each writer",
        "",
        f"*Read at `{payload['as_of_utc']}` on `{payload['host']}`. **Read-only**: "
        f"`deleted_anything: {payload['deleted_anything']}`.*",
        "",
        "## 1. The volume, and the distance to each floor",
        "",
        "| | |",
        "| --- | --- |",
        f"| Free | **{volume['free_gib']} GiB** ({volume['free_bytes']} bytes) |",
        f"| Verdict | `{volume['verdict']}` |",
        f"| Critical floor (the lane refuses below it) | "
        f"{payload['thresholds']['critical_free_bytes']} bytes |",
        f"| Healthy floor (the heavy publication waits below it) | "
        f"{payload['thresholds']['healthy_free_bytes']} bytes |",
        f"| Shortfall to resume ingestion | **{payload['headroom']['gib_to_resume_ingestion']} GiB** |",
        f"| Shortfall to reach healthy | {payload['headroom']['gib_to_reach_healthy']} GiB |",
        "",
        payload["headroom"]["reading"] + ".",
        "",
        "## 2. What grew, by directory, inside the declared window",
        "",
        payload["method"] + ".",
        "",
    ]
    for root in payload["growth"]:
        total = sum(row["bytes"] for row in root["groups"].values())
        lines += [
            f"### `{root['name']}`",
            "",
            f"*Window: {root['window_minutes']:.0f} min. Scanned {root['scanned_files']:,} files in "
            f"{root['walk_seconds']} s. Fully walked: {root['measured']}.*",
            "",
            f"Total written inside the window: **{total / MIB:,.1f} MiB**.",
            "",
            "| Directory | Written | Files | Newest write | Largest file in the window |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, row in sorted(root["groups"].items(), key=lambda item: -item[1]["bytes"])[:25]:
            largest = row["largest"][0] if row["largest"] else (0, "—")
            lines.append(
                f"| `{name}` | {row['bytes'] / MIB:,.1f} MiB | {row['files']:,} | "
                f"{row['newest_utc']} | `{largest[1]}` ({largest[0] / MIB:,.2f} MiB) |"
            )
        lines += [
            "",
            "By extension:",
            "",
            "| Extension | Written | Files |",
            "| --- | --- | --- |",
        ]
        for ext, row in sorted(root["by_extension"].items(), key=lambda item: -item[1]["bytes"])[
            :12
        ]:
            lines.append(f"| `{ext}` | {row['bytes'] / MIB:,.1f} MiB | {row['files']:,} |")
        lines.append("")

    lines += [
        "## 3. Processes running from the profile",
        "",
        f"*Source: {payload['processes']['source']}; {payload['processes']['count']} process(es)*",
        "",
        "| PID | Name | Image |",
        "| --- | --- | --- |",
    ]
    for row in payload["processes"]["processes"][:25]:
        if "raw" in row:
            lines.append(f"| — | — | `{row['raw']}` |")
        else:
            lines.append(f"| {row.get('pid')} | `{row.get('name')}` | `{row.get('exe')}` |")
    lines += [
        "",
        "## 4. What this reading authorises",
        "",
        "- It names the writers. It does not stop them and it does not delete their files: every "
        "path in this file belongs to another application or to the user.",
        "- What this work package may clean is its own: the repository's tool caches, and only "
        "those whose removal is provable at the instant of removal.",
        f"- The distance to the floor is **{payload['headroom']['gib_to_resume_ingestion']} GiB**; "
        "if no repository-owned action can close it, that is the volume owner's decision, taken "
        "with this table in hand.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    home = Path.home()
    parser.add_argument("--window-minutes", type=float, default=90.0)
    parser.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS)
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help=f"root to walk (repeatable); default {home / 'AppData' / 'Local'}",
    )
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07")
    )
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    roots = [Path(root) for root in options.root] if options.root else [home / "AppData" / "Local"]
    payload = build(
        window_minutes=options.window_minutes,
        budget_seconds=options.budget_seconds,
        roots=roots,
    )
    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "GROWTH_EVIDENCE.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (out / "GROWTH_EVIDENCE.md").write_text(render(payload), encoding="utf-8")
    for root in payload["growth"]:
        total = sum(row["bytes"] for row in root["groups"].values())
        print(f"{root['name']}: {total / MIB:,.1f} MiB written inside the window")
        for name, row in sorted(root["groups"].items(), key=lambda item: -item[1]["bytes"])[:5]:
            print(f"  {name:<52} {row['bytes'] / MIB:>10,.1f} MiB  {row['files']:>6,} files")
    print(
        f"volume {payload['volume']['free_gib']} GiB free, "
        f"{payload['headroom']['gib_to_resume_ingestion']} GiB short of resuming ingestion"
    )
    print(f"wrote GROWTH_EVIDENCE.json and GROWTH_EVIDENCE.md into {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
