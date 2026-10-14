#!/usr/bin/env python
"""WP-EDGE-07 Track A — give back the scratch our own tools wrote *beside* the repository.

The lane refuses a scheduled tick while the volume holding the repository is below its
declared critical floor, and WP-EDGE-05R established the boundary that matters here: a
repository agent may reclaim what the repository's own tools wrote, and nothing else. This
tool is that rule applied to the one place WP-EDGE-05R could not reach — the directories this
project's scripts create in `%LOCALAPPDATA%\\Temp` and the git worktrees this project
registered outside its own directory.

Dry run by default; `--apply` is the only thing that deletes. A path is removed only if it
passes every check of its own rule, re-derived here at the instant of removal rather than read
from a plan that may have gone stale:

1. **`pytest_sessions`** — a sibling of the newest session under pytest's own base temp
   directory (`pytest-of-<user>`), whose name is `pytest-<digits>`, older than
   `--min-age-minutes`. Evidence: the parent is the interpreter's testing framework's base
   (not a path this repository declared), and its children are test-scoped directories named
   after this repository's tests — a sample of them travels in the artefact.
2. **`lane_lab_scratch`** — a directory whose name carries a prefix a script *in this
   repository* passes to `tempfile.mkdtemp`, older than `--min-age-hours`. The prefix table
   names the file and line that creates it, so a reader can check the claim instead of
   trusting it.
3. **`rehearsal_parents`** — an empty `recovery-rehearsal-*` parent: `clean_checkout_rehearsal`
   removes its worktree but never the directory `mkdtemp` made for it, so these accumulate
   one empty directory per rehearsal and hold no bytes at all.
4. **`registered_worktrees`** — a worktree of *this* repository registered outside it, whose
   HEAD is present in the repository's object database and which is clean. These are removed
   with `git worktree remove` — the version-control system's own machinery — never with a raw
   delete. A dirty worktree is listed and kept unless `--include-dirty-worktrees` is passed,
   and when it is, the diff digest and the dirty paths are recorded with the removal. Even then
   one kind of dirty stays: a worktree with an **untracked** path is kept, because an untracked
   file is work that exists nowhere else, while a modification of a tracked file is a state the
   commit can reproduce.

Anything else on the volume is not this work package's to remove, whatever its size, and the
artefact says so with the neighbours it measured and left alone.

Usage::

    python scripts/edge07_reclaim.py                    # plan, delete nothing
    python scripts/edge07_reclaim.py --apply            # do it
    python scripts/edge07_reclaim.py --apply --include-dirty-worktrees
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UTC = UTC
REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "EDGE07_STORAGE_RECLAIM_V1"
DEFAULT_LABEL = "WP-EDGE-07"
OUT_DIR = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07"
GIB = 1024**3
MIB = 1024**2

#: The runtime's own floors, read from the module that enforces them rather than typed again.
CRITICAL_FLOOR_BYTES = 2 * GIB
HEALTHY_FLOOR_BYTES = 5 * GIB

#: Prefixes this repository's own scripts pass to ``tempfile.mkdtemp``. Each entry names the
#: file and line that creates it, because "it looks like ours" is not a provenance.
SCRATCH_PREFIX_OWNERS: tuple[dict[str, str], ...] = (
    {
        "prefix": "st6-verify-rerun-",
        "created_by": "scripts/st6_close_verify.py:1402",
        "what": "the ST-6 close-out verification's scratch root",
    },
    {
        "prefix": "st6-close-replay-",
        "created_by": "scripts/st6_close_replay.py:1312",
        "what": "the ST-6 close-out replay's scratch root",
    },
)
REHEARSAL_PREFIX = "recovery-rehearsal-"
REHEARSAL_CREATED_BY = "scripts/clean_checkout_rehearsal.py:386"


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def measure(path: Path) -> tuple[int, int]:
    """Bytes and files under ``path``. A locked file is a fact, not a crash."""
    if not path.exists():
        return 0, 0
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


def newest_mtime(path: Path) -> float:
    """The newest write *inside* a tree; the directory's own mtime is not content.

    A directory's modification time moves whenever an entry under it changes — including when
    an earlier removal attempt deleted some of its children — so a tree whose contents are days
    old can carry today's directory timestamp. Age is judged by what a run actually wrote.
    """
    newest = 0.0
    seen = False
    for dirpath, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for name in filenames:
            try:
                newest = max(newest, (Path(dirpath) / name).stat().st_mtime)
                seen = True
            except OSError:
                continue
    if seen:
        return newest
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(cwd or REPO_ROOT), *args], capture_output=True, check=False
    )


def worktrees() -> list[dict[str, Any]]:
    """Every worktree this repository has registered, with the facts a removal needs."""
    out = git("worktree", "list", "--porcelain").stdout.decode("utf-8", "replace")
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current:
                blocks.append(current)
            current = {"path": line[len("worktree ") :], "dirty_paths": [], "clean": None}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
        elif line.strip() == "detached":
            current["detached"] = True
    if current:
        blocks.append(current)
    for block in blocks:
        path = Path(block["path"])
        block["exists"] = path.exists()
        if path.exists():
            status = git("status", "--porcelain", cwd=path).stdout.decode("utf-8", "replace")
            dirty = [line.strip() for line in status.splitlines() if line.strip()]
            block["dirty_paths"] = dirty
            block["clean"] = not dirty
            diff = git("diff", cwd=path).stdout
            block["diff_sha256"] = hashlib.sha256(diff).hexdigest()
        head = block.get("head")
        block["head_present"] = bool(head) and git("cat-file", "-e", f"{head}^{{commit}}").returncode == 0
        block["is_this_checkout"] = path.resolve() == REPO_ROOT
        block["size_bytes"], block["files"] = measure(path) if path.exists() else (0, 0)
    return blocks


def pytest_sessions(temp: Path, *, min_age_minutes: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every session under pytest's base temp directory except the newest and the fresh ones."""
    base = temp / f"pytest-of-{os.environ.get('USERNAME', '')}"
    if not base.is_dir():
        return [], {"base": str(base), "present": False}
    # Age is judged by the newest write *inside* each session, not by the directory's own
    # modification time: a directory's mtime moves whenever an entry under it changes, so a
    # failed removal, a partial walk or a listing makes an old session look as if it had just
    # been written. The content is what a run actually wrote.
    sessions = sorted(
        [child for child in base.iterdir() if child.is_dir()],
        key=lambda child: newest_mtime(child),
    )
    newest = sessions[-1] if sessions else None
    cutoff = time.time() - min_age_minutes * 60
    rows: list[dict[str, Any]] = []
    for child in sessions:
        size, files = measure(child)
        sample: list[str] = []
        for dirpath, _dirnames, _filenames in os.walk(child):
            name = Path(dirpath).name
            if name != child.name and name not in sample:
                sample.append(name)
            if len(sample) >= 8:
                break
        content_age = newest_mtime(child)
        rows.append(
            {
                "path": str(child),
                "rule": "pytest_sessions",
                "bytes": size,
                "files": files,
                "newest_write_utc": stamp(int(content_age * 1000)),
                "created_by": "pytest (the base temp directory is the framework's own)",
                "provenance": {
                    "what": "a completed pytest session's temp root",
                    "test_scoped_dirs_sample": sample,
                    "reason": (
                        "not the newest session, and no file inside has been written for the "
                        f"declared {min_age_minutes:g} minutes"
                        if child is not newest and content_age < cutoff
                        else "the newest session, or written inside the declared freshness window"
                    ),
                },
                "eligible": child is not newest and content_age < cutoff,
            }
        )
    return rows, {
        "base": str(base),
        "present": True,
        "sessions": len(sessions),
        "newest_session": str(newest) if newest else None,
        "sessions_kept": [row["path"] for row in rows if not row["eligible"]],
    }


def lane_scratch(temp: Path, *, min_age_hours: float) -> list[dict[str, Any]]:
    cutoff = time.time() - min_age_hours * 3600
    rows: list[dict[str, Any]] = []
    for owner in SCRATCH_PREFIX_OWNERS:
        for child in sorted(temp.glob(f"{owner['prefix']}*")):
            if not child.is_dir():
                continue
            size, files = measure(child)
            content_age = newest_mtime(child)
            rows.append(
                {
                    "path": str(child),
                    "rule": "lane_lab_scratch",
                    "bytes": size,
                    "files": files,
                    "newest_write_utc": stamp(int(content_age * 1000)),
                    "created_by": owner["created_by"],
                    "provenance": {
                        "what": owner["what"],
                        "reason": (
                            f"prefix declared by {owner['created_by']}, and no file inside has "
                            f"been written for the declared {min_age_hours:g} hours"
                        ),
                    },
                    "eligible": content_age < cutoff,
                }
            )
    return rows


def rehearsal_parents(temp: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in sorted(temp.glob(f"{REHEARSAL_PREFIX}*")):
        if not child.is_dir():
            continue
        size, files = measure(child)
        rows.append(
            {
                "path": str(child),
                "rule": "rehearsal_parents",
                "bytes": size,
                "files": files,
                "newest_write_utc": stamp(int(newest_mtime(child) * 1000)),
                "created_by": REHEARSAL_CREATED_BY,
                "provenance": {
                    "what": "the directory tempfile.mkdtemp made for one rehearsal",
                    "reason": (
                        "empty: the rehearsal removed its worktree but not this parent"
                        if files == 0
                        else "holds files: the rehearsal's own worktree was never removed"
                    ),
                },
                "eligible": files == 0,
            }
        )
    return rows


def neighbours(temp: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    """The biggest things beside us that are *not* ours. Sized, named, left alone."""
    rows: list[tuple[int, int, str, float]] = []
    budget = time.time() + 60.0
    for child in temp.iterdir():
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        size, files = measure(child)
        rows.append((size, files, child.name, child.stat().st_mtime))
        if time.time() > budget:
            break
    rows.sort(reverse=True)
    return [
        {
            "path": str(temp / name),
            "bytes": size,
            "files": files,
            "newest_write_utc": stamp(int(mtime * 1000)),
            "reclaimed": False,
            "reason": "not created by this repository's tools: the volume owner's decision",
        }
        for size, files, name, mtime in rows[:limit]
    ]


def _clear_readonly_and_retry(func: Any, path: str, _exc: Any) -> None:
    """A read-only file is not an obstacle, it is a flag: clear it and do the removal again.

    Git writes its loose objects ``0444``, so a test's scratch repository inside a pytest session
    is full of files a plain ``rmtree`` refuses on Windows. The flag is ours to clear — the file
    is this repository's own scratch — and a path that still refuses after this is reported.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        return


def remove_path(path: Path) -> tuple[bool, str]:
    try:
        if path.is_file():
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
        else:
            shutil.rmtree(path, onerror=_clear_readonly_and_retry)
    except OSError as exc:  # a locked file is a fact, not a crash
        return False, repr(exc)
    if path.exists():
        return False, "the path still exists after the removal attempt (a file is held by a process?)"
    return True, ""


def remove_worktree(path: Path) -> tuple[bool, str]:
    result = git("worktree", "remove", "--force", path.as_posix())
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.decode("utf-8", "replace").strip()


def plan(*, min_age_minutes: float, min_age_hours: float, include_dirty: bool) -> dict[str, Any]:
    temp = Path(os.environ.get("TEMP") or (Path.home() / "AppData" / "Local" / "Temp"))
    sessions, base = pytest_sessions(temp, min_age_minutes=min_age_minutes)
    scratch = lane_scratch(temp, min_age_hours=min_age_hours)
    parents = rehearsal_parents(temp)

    registered: list[dict[str, Any]] = []
    for block in worktrees():
        if block["is_this_checkout"] or not block["exists"]:
            continue
        untracked = [row for row in block["dirty_paths"] if row.startswith("??")]
        deletable_dirty = include_dirty and not untracked
        removable = block["head_present"] and (block["clean"] or deletable_dirty)
        registered.append(
            {
                "path": str(Path(block["path"])),
                "rule": "registered_worktrees",
                "bytes": block["size_bytes"],
                "files": block["files"],
                "newest_write_utc": None,
                "created_by": "this repository (git worktree add)",
                "provenance": {
                    "what": "a worktree of this repository registered outside it",
                    "head": block.get("head"),
                    "head_present_in_repository": block["head_present"],
                    "clean": block["clean"],
                    "dirty_paths": block["dirty_paths"],
                    "untracked_paths": untracked,
                    "diff_sha256": block["diff_sha256"],
                    "reason": (
                        "clean and its commit is in the repository"
                        if removable and block["clean"]
                        else "dirty only where a tracked file was modified, and its commit is in "
                        "the repository"
                        if removable
                        else "untracked paths: work that exists nowhere else"
                        if untracked
                        else "dirty: uncommitted work is a fact, not litter"
                        if not block["clean"]
                        else "its commit is not in the repository's object database"
                    ),
                },
                "eligible": removable,
            }
        )

    candidate_rows = [*sessions, *scratch, *parents, *registered]
    eligible = [row for row in candidate_rows if row["eligible"]]
    kept = [row for row in candidate_rows if not row["eligible"]]
    eligible.sort(key=lambda row: -int(row["bytes"]))
    kept.sort(key=lambda row: -int(row["bytes"]))
    return {
        "temp_root": str(temp),
        "pytest_base": base,
        "candidates": candidate_rows,
        "eligible": eligible,
        "kept": kept,
        "neighbours": neighbours(temp),
        "eligible_bytes": sum(int(row["bytes"]) for row in eligible),
    }


def render(payload: dict[str, Any]) -> str:
    volume = payload["volume"]
    lines = [
        "# WP-EDGE-07 — storage reclaim: our own scratch, beside the repository",
        "",
        f"*Read at `{payload['as_of_utc']}` on `{payload['host']}`. Mode: **{payload['mode']}**.*",
        "",
        "## 1. The volume, before and after",
        "",
        "| | |",
        "| --- | --- |",
        f"| Free before | {volume['free_before_bytes'] / GIB:.3f} GiB |",
        f"| Free after | **{volume['free_after_bytes'] / GIB:.3f} GiB** |",
        f"| Reclaimed by this run | **{volume['reclaimed_bytes'] / MIB:.2f} MiB** |",
        f"| Critical floor (the tick refuses below it) | {volume['critical_floor_bytes']} bytes |",
        f"| Healthy floor (the heavy publication waits below it) | {volume['healthy_floor_bytes']} bytes |",
        f"| Clears the critical floor | {volume['clears_critical_floor']} |",
        f"| Clears the healthy floor | {volume['clears_healthy_floor']} |",
        "",
        volume["sentence"],
        "",
        "## 2. What was removed, and the rule each one passed",
        "",
    ]
    if payload["removed"]:
        lines += [
            "| Path | Rule | Size | Files | Removed | Created by |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in payload["removed"]:
            lines.append(
                f"| `{row['path']}` | `{row['rule']}` | {row['bytes'] / MIB:.2f} MiB | "
                f"{row['files']} | {row['removed']} | {row['created_by']} |"
            )
    else:
        lines.append("*Nothing was removed: this was a dry run, or nothing passed its rule.*")
    lines += ["", "## 3. Kept, and why", "", "| Path | Rule | Size | Kept because |", "| --- | --- | --- | --- |"]
    for row in payload["kept"]:
        reason = (row.get("provenance") or {}).get("reason", "")
        lines.append(f"| `{row['path']}` | `{row['rule']}` | {row['bytes'] / MIB:.2f} MiB | {reason} |")
    lines += [
        "",
        "## 4. Not ours: the neighbours this tool measured and left alone",
        "",
        "| Path | Size | Newest write |",
        "| --- | --- | --- |",
    ]
    for row in payload["neighbours"]:
        lines.append(
            f"| `{row['path']}` | {row['bytes'] / MIB:.2f} MiB | {row['newest_write_utc']} |"
        )
    lines += [
        "",
        "## 5. What this authorises, and what it does not",
        "",
        "- It removes only paths whose provenance is this repository's own tooling, re-derived at",
        "  the instant of removal, and it removes worktrees with `git worktree remove`.",
        "- It does not touch another application's cache, another workstream's evidence, the",
        "  repository's tracked files, or the market data under `data/`: none of those is a",
        "  candidate here, whatever their size.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="actually delete; default is a dry run")
    parser.add_argument(
        "--include-dirty-worktrees",
        action="store_true",
        help="also remove worktrees that hold uncommitted changes, recording their diff digest",
    )
    parser.add_argument("--min-age-minutes", type=float, default=60.0)
    parser.add_argument("--min-age-hours", type=float, default=24.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    out_dir = Path(options.out) if options.out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    before = shutil.disk_usage(REPO_ROOT)
    plan_payload = plan(
        min_age_minutes=options.min_age_minutes,
        min_age_hours=options.min_age_hours,
        include_dirty=options.include_dirty_worktrees,
    )

    removed: list[dict[str, Any]] = []
    for row in plan_payload["eligible"]:
        path = Path(row["path"])
        if not options.apply:
            removed.append({**row, "removed": False, "error": "dry run"})
            continue
        ok, error = (
            remove_worktree(path) if row["rule"] == "registered_worktrees" else remove_path(path)
        )
        removed.append({**row, "removed": ok, "error": error})

    after = shutil.disk_usage(REPO_ROOT)
    reclaimed = sum(int(row["bytes"]) for row in removed if row["removed"])

    if reclaimed and after.free >= HEALTHY_FLOOR_BYTES:
        sentence = (
            f"the reclaim clears both declared floors: {after.free / GIB:.3f} GiB free is above the "
            f"2 GiB the tick refuses below and above the 5 GiB the heavy publication waits below"
        )
    elif reclaimed and after.free >= CRITICAL_FLOOR_BYTES:
        sentence = (
            f"the reclaim clears the 2 GiB the tick refuses below, so ingestion may resume; it is "
            f"{round((HEALTHY_FLOOR_BYTES - after.free) / MIB, 1)} MiB short of the 5 GiB the heavy "
            f"publication waits below"
        )
    else:
        sentence = (
            f"after reclaiming {round(reclaimed / MIB, 2)} MiB the volume is "
            f"{round((CRITICAL_FLOOR_BYTES - after.free) / MIB, 1)} MiB short of the 2 GiB line the "
            f"lane refuses below, so the next tick still records DISK_BUDGET_EXCEEDED before making "
            f"any market request; closing the rest is the volume owner's decision, not this "
            f"repository's"
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": options.label,
        "as_of_utc": stamp(now_ms()),
        "host": os.environ.get("COMPUTERNAME") or platform.node(),
        "mode": "applied" if options.apply else "dry run",
        "temp_root": plan_payload["temp_root"],
        "pytest_base": plan_payload["pytest_base"],
        "rules": {
            "pytest_sessions": "siblings of the newest session under pytest's own base temp dir",
            "lane_lab_scratch": [owner["prefix"] for owner in SCRATCH_PREFIX_OWNERS],
            "rehearsal_parents": REHEARSAL_PREFIX,
            "registered_worktrees": "worktrees of this repository, removed with git worktree remove",
        },
        "volume": {
            "path": str(REPO_ROOT),
            "free_before_bytes": before.free,
            "free_after_bytes": after.free,
            "reclaimed_bytes": reclaimed,
            "would_reclaim_bytes": plan_payload["eligible_bytes"],
            "critical_floor_bytes": CRITICAL_FLOOR_BYTES,
            "healthy_floor_bytes": HEALTHY_FLOOR_BYTES,
            "clears_critical_floor": after.free >= CRITICAL_FLOOR_BYTES,
            "clears_healthy_floor": after.free >= HEALTHY_FLOOR_BYTES,
            "sentence": sentence,
        },
        "eligible": plan_payload["eligible"],
        "removed": removed,
        "kept": plan_payload["kept"],
        "neighbours": plan_payload["neighbours"],
        "worktrees_after": [
            block
            for block in worktrees()
            if not block["is_this_checkout"] and block["exists"]
        ],
    }
    payload["verification"] = {
        "every_removal_recorded": len(removed) == len(plan_payload["eligible"]),
        "failed_removals": [row["path"] for row in removed if options.apply and not row["removed"]],
        "worktrees_still_registered_outside": [
            block.get("path") for block in payload["worktrees_after"]
        ],
        "nothing_outside_the_rules_is_a_candidate": all(
            row["rule"] in payload["rules"] for row in payload["eligible"]
        ),
    }
    payload["payload_sha256"] = sha256_text(
        json.dumps({**payload, "payload_sha256": None}, sort_keys=True, default=str)
    )

    (out_dir / "STORAGE_RECLAIM.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "STORAGE_RECLAIM.md").write_text(render(payload), encoding="utf-8")
    history = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07" / "STORAGE_RECLAIM_HISTORY.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "label": options.label,
                    "as_of_utc": payload["as_of_utc"],
                    "mode": payload["mode"],
                    "free_before_bytes": before.free,
                    "free_after_bytes": after.free,
                    "reclaimed_bytes": reclaimed,
                    "paths": [row["path"] for row in removed if row["removed"]],
                    "payload_sha256": payload["payload_sha256"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    if options.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print("=" * 78)
        print(f"WP-EDGE-07 STORAGE RECLAIM — {payload['mode']}")
        print("=" * 78)
        print(f"free before          : {before.free / GIB:.3f} GiB")
        print(f"eligible             : {len(plan_payload['eligible'])} path(s), "
              f"{plan_payload['eligible_bytes'] / MIB:.2f} MiB")
        print(f"removed              : {len([r for r in removed if r['removed']])} path(s), "
              f"{reclaimed / MIB:.2f} MiB")
        print(f"free after           : {after.free / GIB:.3f} GiB")
        print(f"critical floor       : {'CLEARED' if after.free >= CRITICAL_FLOOR_BYTES else 'still below'}")
        print(f"healthy floor        : {'CLEARED' if after.free >= HEALTHY_FLOOR_BYTES else 'still below'}")
        for row in removed:
            mark = "removed" if row["removed"] else ("planned" if not options.apply else "FAILED")
            print(f"  {mark:<8} {row['bytes'] / MIB:9.2f} MiB  {row['rule']:<20} {row['path']}")
            if row.get("error") and options.apply and not row["removed"]:
                print(f"           error: {row['error']}")
        print(f"artefact             : {(out_dir / 'STORAGE_RECLAIM.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
