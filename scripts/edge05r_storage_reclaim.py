#!/usr/bin/env python
"""WP-EDGE-05R — give the volume back what a tool will simply write again.

Dry run by default; `--apply` is the only thing that deletes, and it deletes only what
passes three checks *for that exact path*, re-derived here rather than read from a plan
that may have gone stale:

1. **It is a tool cache by name** — bytecode, or one of the caches mypy, pytest, ruff,
   hypothesis and coverage write. Nothing else is ever a candidate.
2. **Git does not track it** (`git ls-files`), so no history depends on it.
3. **`.gitignore` names it** (`git check-ignore`), so its absence is already the norm.

A path that fails any check is reported and kept. Market data, evidence, other
workstreams' artefacts, source and the environment directory itself are not candidates,
whatever their size: deleting those is an owner's decision, not a cleanup.

It also states plainly whether the result clears the floors the lane's own guard uses —
because "we freed 113 MiB" means nothing until it is compared with the 2 GiB the tick
refuses below and the 5 GiB it calls healthy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UTC = UTC
REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "EDGE05R_STORAGE_RECLAIM_V1"
DEFAULT_LABEL = "WP-EDGE-05R"
GIB = 1024**3
MIB = 1024**2

CRITICAL_FLOOR_BYTES = 2 * GIB
HEALTHY_FLOOR_BYTES = 5 * GIB

CACHE_DIR_NAMES = (
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
)


def floor_reading(*, free_after: int, reclaimed_bytes: int, would_reclaim_bytes: int) -> str:
    """One sentence about the floors, derived from the same numbers the table prints.

    It is a function and not a string literal for a reason: the literal this replaced asserted the
    crossing of the 2 GiB line unconditionally, and a run whose own table said
    ``reaches_the_critical_floor: False`` printed the assertion beside it. A sentence and a figure
    that can disagree are two readings of the same instant, which is the defect this work package
    exists to remove.
    """
    if free_after >= HEALTHY_FLOOR_BYTES:
        return (
            f"the reclaim alone clears both declared floors: {free_after / GIB:.3f} GiB free is above "
            f"the 2 GiB the tick refuses below and above the 5 GiB the heavy publication waits below"
        )
    if free_after >= CRITICAL_FLOOR_BYTES:
        return (
            f"the reclaim alone clears the 2 GiB the tick refuses below, so ingestion may resume, but "
            f"it is {round((HEALTHY_FLOOR_BYTES - free_after) / MIB, 1)} MiB short of the 5 GiB the "
            f"heavy publication waits below"
        )
    return (
        f"caches alone do not take the volume across the 2 GiB line the lane refuses below: after "
        f"reclaiming {round(reclaimed_bytes / MIB, 2)} MiB it is still "
        f"{round((CRITICAL_FLOOR_BYTES - free_after) / MIB, 1)} MiB short, so the next tick still "
        f"records DISK_BUDGET_EXCEEDED before making any market request, and the 5 GiB line the "
        f"heavy publication waits below is {round((HEALTHY_FLOOR_BYTES - free_after) / MIB, 1)} MiB "
        f"away. Every tool cache this rule recognises is worth "
        f"{round(would_reclaim_bytes / MIB, 2)} MiB here, so the rest of the shortfall is not this "
        f"repository's to close: it is the volume owner's decision"
    )


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tracked(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False
    )
    if result.returncode != 0:
        return set()
    return {
        item.decode("utf-8", "replace").replace("\\", "/")
        for item in result.stdout.split(b"\0")
        if item
    }


def ignored(root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", relative],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def candidates(root: Path) -> list[Path]:
    """Every tool cache under ``root``, by name only — the first of the three checks."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        if Path(dirpath).name == ".git":
            dirnames[:] = []
            continue
        for name in list(dirnames):
            if name in CACHE_DIR_NAMES:
                found.append(Path(dirpath) / name)
                dirnames.remove(name)
        for name in filenames:
            if name == ".coverage" or name.startswith(".coverage."):
                found.append(Path(dirpath) / name)
    return sorted(found)


def measure(path: Path) -> tuple[int, int]:
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    total = 0
    files = 0
    for dirpath, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
                files += 1
            except OSError:
                continue
    return total, files


def plan(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tracked_paths = tracked(root)
    deletable: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for path in candidates(root):
        rel = path.relative_to(root).as_posix()
        size, files = measure(path)
        tracked_here = [t for t in tracked_paths if t == rel or t.startswith(rel + "/")]
        is_ignored = ignored(root, rel)
        row = {
            "path": rel,
            "bytes": size,
            "files": files,
            "scope": (
                "interpreter bytecode inside the project environment"
                if rel.startswith(".venv/")
                else "repository tool cache"
            ),
            "regenerated_by": (
                "python (bytecode cache)"
                if path.name == "__pycache__"
                else path.name.strip(".").split("_")[0]
            ),
            "tracked_by_git": bool(tracked_here),
            "ignored_by_gitignore": is_ignored,
            "checks_passed": (not tracked_here) and is_ignored,
            "refused_because": (
                "" if (not tracked_here) and is_ignored else
                "git tracks it" if tracked_here else
                ".gitignore does not name it"
            ),
        }
        (deletable if row["checks_passed"] else kept).append(row)
    deletable.sort(key=lambda row: -int(row["bytes"]))
    kept.sort(key=lambda row: -int(row["bytes"]))
    return deletable, kept


def delete(path: Path) -> tuple[bool, str]:
    try:
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
        return True, ""
    except OSError as exc:  # a locked file is a fact, not a crash
        return False, repr(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually delete; without it the run is a dry run and nothing is removed",
    )
    parser.add_argument("--json", action="store_true")
    #: The work package re-running the sweep, so a later reading is not filed under the
    #: earlier work package's name (see the inventory tool's option of the same name).
    parser.add_argument("--label", default=DEFAULT_LABEL)
    options = parser.parse_args(argv)

    root = Path(options.root).resolve() if options.root else REPO_ROOT
    out = (
        Path(options.out)
        if options.out
        else REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-05R"
    )

    instant = now_ms()
    as_of = stamp(instant)
    before = shutil.disk_usage(root)
    deletable, kept = plan(root)

    removed: list[dict[str, Any]] = []
    if options.apply:
        for row in deletable:
            ok, error = delete(root / row["path"])
            removed.append({**row, "removed": ok, "error": error})
    after = shutil.disk_usage(root)

    reclaimed = sum(int(row["bytes"]) for row in removed if row["removed"])
    would_reclaim = sum(int(row["bytes"]) for row in deletable)

    def verdict(free: int) -> str:
        if free < CRITICAL_FLOOR_BYTES:
            return "BELOW_CRITICAL"
        if free < HEALTHY_FLOOR_BYTES:
            return "ABOVE_CRITICAL_BELOW_HEALTHY"
        return "HEALTHY"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": options.label,
        "run_id": f"EDGE05R-RECLAIM-{as_of.replace('-', '').replace(':', '')}",
        "as_of_utc": as_of,
        "host": os.environ.get("COMPUTERNAME", "unknown"),
        "repo_root": str(root),
        "applied": bool(options.apply),
        "rule": (
            "a tool cache by name, untracked by git, and named in .gitignore — all three "
            "re-checked here for every path, never read from a plan"
        ),
        "volume": {
            "free_bytes_before": before.free,
            "free_bytes_after": after.free,
            "total_bytes": before.total,
            "free_gib_before": round(before.free / GIB, 3),
            "free_gib_after": round(after.free / GIB, 3),
            "verdict_before": verdict(before.free),
            "verdict_after": verdict(after.free),
            "critical_floor_bytes": CRITICAL_FLOOR_BYTES,
            "healthy_floor_bytes": HEALTHY_FLOOR_BYTES,
        },
        "deletable": deletable,
        "kept_with_reason": kept,
        "removed": removed,
        "reclaimed_bytes": reclaimed,
        "reclaimed_mib": round(reclaimed / MIB, 2),
        "would_reclaim_bytes": would_reclaim,
        "would_reclaim_mib": round(would_reclaim / MIB, 2),
        "not_candidates": (
            "market data, evidence and snapshots, other workstreams' artefacts, source, "
            "config and the environment directory's own files — sized by "
            "edge05r_storage_inventory.py and left alone here"
        ),
        "reaches_the_critical_floor": after.free >= CRITICAL_FLOOR_BYTES,
        "reaches_the_healthy_floor": after.free >= HEALTHY_FLOOR_BYTES,
        "reading": floor_reading(
            free_after=after.free,
            reclaimed_bytes=reclaimed,
            would_reclaim_bytes=would_reclaim,
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
    payload["figures"] = [
        {
            "figure": name,
            "value": value,
            "unit": "bytes",
            "run_id": payload["run_id"],
            "as_of_utc": as_of,
            "source_artifact": "operating system, disk_usage of the repository volume",
            "source_digest": sha256_text(f"{name}:{value}:{as_of}"),
            "measurement_scope": f"volume {root.drive} at {root}",
        }
        for name, value in (
            ("volume_free_bytes_before", before.free),
            ("volume_free_bytes_after", after.free),
            ("reclaimed_bytes", reclaimed),
            ("reclaimable_bytes_remaining", sum(int(r["bytes"]) for r in deletable if options.apply)),
        )
    ]

    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "STORAGE_RECLAIM.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    # Each sweep is appended to a history: the caches come back as the tools run again, so the
    # interesting quantity is not one sweep but how much space the sweeps return and how fast the
    # volume takes it away again.
    history = out / "STORAGE_RECLAIM_HISTORY.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "run_id": payload["run_id"],
                    "as_of_utc": as_of,
                    "applied": payload["applied"],
                    "free_bytes_before": before.free,
                    "free_bytes_after": after.free,
                    "reclaimed_bytes": reclaimed,
                    "would_reclaim_bytes": would_reclaim,
                    "deletable_paths": len(deletable),
                    "kept_paths": len(kept),
                    "verdict_before": payload["volume"]["verdict_before"],
                    "verdict_after": payload["volume"]["verdict_after"],
                    "hypothetical": True,
                    "order_sent": False,
                    "promotion": "NONE",
                },
                sort_keys=True,
                default=str,
            )
            + "\n"
        )
    (out / "STORAGE_RECLAIM.md").write_text(render(payload), encoding="utf-8")
    mode = "APPLIED" if options.apply else "DRY RUN"
    print(f"{mode}: reclaimed {payload['reclaimed_mib']} MiB, free {before.free / GIB:.3f} -> {after.free / GIB:.3f} GiB")
    print(f"verdict {payload['volume']['verdict_before']} -> {payload['volume']['verdict_after']}")
    print(f"kept {len(kept)} path(s) that failed a check")
    return 0


def render(payload: dict[str, Any]) -> str:
    volume = payload["volume"]
    lines = [
        f"# {payload.get('label', DEFAULT_LABEL)} — storage recovery: what came back, and what did not",
        "",
        f"*Read at `{payload['as_of_utc']}` on `{payload['host']}`. Mode: "
        f"**{'applied' if payload['applied'] else 'dry run — nothing was deleted'}**.*",
        "",
        "## 1. The result",
        "",
        "| | |",
        "| --- | --- |",
        f"| Free before | {volume['free_gib_before']} GiB |",
        f"| Free after | **{volume['free_gib_after']} GiB** |",
        f"| Reclaimed | **{payload['reclaimed_mib']} MiB** ({payload['reclaimed_bytes']} bytes) |",
        f"| Verdict before | `{volume['verdict_before']}` |",
        f"| Verdict after | `{volume['verdict_after']}` |",
        f"| Clears the 2 GiB critical floor | {payload['reaches_the_critical_floor']} |",
        f"| Clears the 5 GiB healthy floor | {payload['reaches_the_healthy_floor']} |",
        "",
        payload["reading"] + ".",
        "",
        "## 2. What was removed, and the three checks each one passed",
        "",
        "| Path | Size | Files | Regenerated by | Tracked | Ignored | Removed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = payload["removed"] or payload["deletable"]
    for row in rows[:60]:
        lines.append(
            f"| `{row['path']}` | {row['bytes'] / 1024:,.1f} KiB | {row['files']} | "
            f"{row['regenerated_by']} | {row['tracked_by_git']} | "
            f"{row['ignored_by_gitignore']} | {row.get('removed', '(dry run)')} |"
        )
    if len(rows) > 60:
        lines.append(f"| *({len(rows) - 60} more rows in the JSON)* | | | | | | |")

    lines += [
        "",
        "## 3. What was kept, and why",
        "",
        "| Path | Size | Refused because |",
        "| --- | --- | --- |",
    ]
    for row in payload["kept_with_reason"][:20]:
        lines.append(
            f"| `{row['path']}` | {row['bytes'] / 1024:,.1f} KiB | {row['refused_because']} |"
        )
    if not payload["kept_with_reason"]:
        lines.append("| *(none)* | | |")

    lines += [
        "",
        "## 4. What was never a candidate",
        "",
        payload["not_candidates"] + ".",
        "",
        "## 5. Every figure, with the instant it was read at",
        "",
        "| Figure | Value | as_of_utc | Source artefact | Source digest | Scope |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["figures"]:
        lines.append(
            f"| `{row['figure']}` | {row['value']} | {row['as_of_utc']} | "
            f"{row['source_artifact']} | `{row['source_digest'][:16]}…` | "
            f"{row['measurement_scope']} |"
        )
    lines += [
        "",
        f"*`run_id`: `{payload['run_id']}`.*",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
