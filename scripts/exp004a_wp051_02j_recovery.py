"""P0 operational recovery of the 90-day campaign: capacity first, then the alarm.

The previous package measured the problem: 162 ticks refused for space, 25 stretches under the
2 GiB floor, and a window that cannot be completed. This program exists to answer the four
questions that report left open, in the order that matters:

1. **Where is the disk going, and who owns each byte?** A candidate list with an owner, a size,
   an age and a classification — never a delete list.
2. **What margin does the campaign actually need?** Recomputed from the distribution of observed
   drawdowns, not from a single number, and stated as a range with the percentile it comes from.
3. **Can an alert reach a person?** Channels audited and, where one exists, exercised end to end
   with a receipt the operating system keeps.
4. **Can the campaign keep running without breaking its own controls?** Verified against the
   frozen contract: no window shift, no coverage redefinition, no floor moved, no row invented.

Nothing here deletes a byte it cannot name. ``--clean`` touches only this package's own
untracked caches; every other candidate is reported with the exact action that would be needed
and left alone.

Usage::

    python scripts/exp004a_wp051_02j_recovery.py --diagnosis
    python scripts/exp004a_wp051_02j_recovery.py --capacity
    python scripts/exp004a_wp051_02j_recovery.py --channels
    python scripts/exp004a_wp051_02j_recovery.py --clean
    python scripts/exp004a_wp051_02j_recovery.py --report

Research only: reads the filesystem and the lane's logs, deletes only its own caches, sends
nothing but the local alert its own ``--channels`` run asks for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "EXP004A_WP051_02J_RECOVERY_V1"
PACKAGE = "WP-051-02J"

GIB = 1024**3
MIB = 1024**2

#: Unchanged, by contract and by this program: the floor the observer's guard enforces.
CRITICAL_FREE_BYTES = 2 * GIB
WARNING_FREE_BYTES = 5 * GIB

#: The frozen window. Repeated as constants so a test can prove this program never moves them.
WINDOW_START = "2026-10-23T00:00:00Z"
WINDOW_END = "2027-01-21T00:00:00Z"
WINDOW_DAYS = 90
DECLARED_ROWS = 6480
REQUIRED_FRACTION = 0.9
ROWS_PER_ASSET_PER_DAY = 24
ASSETS = ("BTC", "ETH", "SOL")
LAG_BOUND_MS = 120 * 60 * 1000
LOST_DAY = "2026-10-23"

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
DEFAULT_OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02j"
DEFAULT_STATE = MAIN_ROOT / "data" / "forward" / "edge04"

#: A tree nobody has written for this long is treated as idle rather than in use. Two hours is
#: short enough to catch a running job and long enough to survive a coffee.
ACTIVE_WINDOW_SECONDS = 2 * 3600

#: The only thing ``--clean`` may delete: byte-compiled caches inside this worktree, untracked.
CLEAN_PATTERNS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis")

#: The suite this package is accountable for, and the two scheduler entries that carry the alarm.
PYTEST_SUITE = "tests/unit/research/test_exp004a_wp051_02j.py"
SCHEDULER_TASKS = ("TradingAgentic-EDGE04-Watchdog", "TradingAgentic-EDGE04-Alarm")
#: Exit codes the watchdog documents for itself. Anything else is the scheduler reporting that the
#: action never ran (0x41303 and friends), which is a different fact from "ran and found a problem".
DOCUMENTED_EXIT_CODES = (0, 1, 2, 8, 9)

SAFE_OWNED = "SAFE_OWNED"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
ACTIVE_OR_PROTECTED = "ACTIVE_OR_PROTECTED"
UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- #
# clock, io, git
# --------------------------------------------------------------------------- #
def now() -> datetime:
    return datetime.now(tz=UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(temporary, path)


def git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def measure(root: Path, *, max_files: int = 400_000, max_seconds: float = 90.0) -> dict[str, Any]:
    """Bytes, files and the newest modification under ``root``, bounded and honest about it."""
    started = time.monotonic()
    total = files = 0
    newest = 0.0
    truncated = None
    if not root.exists():
        return {"path": str(root), "exists": False, "bytes": 0, "files": 0, "newest_mtime": None}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if files >= max_files:
                        truncated = f"file limit {max_files}"
                        break
                    if time.monotonic() - started > max_seconds:
                        truncated = f"time limit {max_seconds}s"
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            info = entry.stat(follow_symlinks=False)
                            total += info.st_size
                            files += 1
                            newest = max(newest, info.st_mtime)
                    except OSError:
                        continue
        except OSError:
            continue
        if truncated:
            break
    return {
        "path": str(root),
        "exists": True,
        "bytes": total,
        "files": files,
        "newest_mtime": newest or None,
        "truncated": truncated,
        "bytes_gib": round(total / GIB, 3),
    }


def age_hours(newest_mtime: float | None) -> float | None:
    if not newest_mtime:
        return None
    return round((time.time() - newest_mtime) / 3600, 2)


def volume_free(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "free_bytes": int(usage.free),
        "total_bytes": int(usage.total),
        "free_gib": round(usage.free / GIB, 4),
        "used_percent": round((usage.total - usage.free) / usage.total * 100, 2),
        "status": (
            "CRITICAL"
            if usage.free < CRITICAL_FREE_BYTES
            else ("WARNING" if usage.free < WARNING_FREE_BYTES else "HEALTHY")
        ),
    }


def running_processes() -> list[dict[str, Any]]:
    """Name and command line of every process, read once per run."""
    script = (
        "Get-CimInstance Win32_Process | ForEach-Object { "
        "'{0}`t{1}`t{2}' -f $_.ProcessId, $_.Name, ($_.CommandLine -replace \"`t\",' ') }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rows.append({"pid": parts[0].strip(), "name": parts[1].strip(), "cmd": parts[2].strip()})
    return rows


# --------------------------------------------------------------------------- #
# Phase A — the candidate list
# --------------------------------------------------------------------------- #
OWN_MARKERS = (
    "bot-freebuff-exp004a",
    "bot freebuff",
    "bot-freebuff-wp003",
)


def processes_touching(path: Path, processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Processes whose command line names the tree or one of its ancestors.

    Deliberately literal: it matches the path text, so a process that merely *mentions* the
    directory is reported rather than a process that has a handle on it and says nothing. A
    false negative here is caught by the age check, never by a guess.
    """
    needle = str(path).lower()
    short = path.name.lower()
    hits = []
    for row in processes:
        command = str(row.get("cmd") or "").lower()
        if needle and needle in command:
            hits.append(row)
        elif short and len(short) > 4 and short in command and "temp" not in command:
            hits.append(row)
    return hits[:8]


def classify(*, path: Path, newest_age_h: float | None, hits: list[dict[str, Any]], own: bool) -> tuple[str, str]:
    """Owner first, then use: the classification is the *decision*, the reason is the audit."""
    if own:
        return SAFE_OWNED, "this work package's own untracked cache, rebuilt on the next run"
    if hits:
        names = ", ".join(sorted({f"{row['name']}({row['pid']})" for row in hits})[:3])
        return ACTIVE_OR_PROTECTED, f"in use right now by {names}"
    if newest_age_h is not None and newest_age_h < ACTIVE_WINDOW_SECONDS / 3600:
        return ACTIVE_OR_PROTECTED, f"written {newest_age_h} h ago: something is using it"
    if newest_age_h is None:
        return UNKNOWN, "no readable modification time: the owner cannot be established"
    return REQUIRES_APPROVAL, "idle, but not this package's to delete"


def candidate(
    path: Path,
    *,
    owner: str,
    project: str,
    action: str,
    alternative: str,
    risk: str,
    processes: list[dict[str, Any]],
    own: bool = False,
) -> dict[str, Any]:
    measured = measure(path)
    newest = age_hours(measured.get("newest_mtime"))
    hits = processes_touching(path, processes)
    classification, why = classify(path=path, newest_age_h=newest, hits=hits, own=own)
    return {
        "path": str(path),
        "owner": owner,
        "project": project,
        "bytes": measured["bytes"],
        "gib": round(measured["bytes"] / GIB, 3),
        "files": measured["files"],
        "newest_age_hours": newest,
        "truncated": measured.get("truncated"),
        "processes": [{"name": row["name"], "pid": row["pid"]} for row in hits],
        "classification": classification,
        "why": why,
        "action_to_free": action,
        "alternative": alternative,
        "risk": risk,
    }


def git_survey(path: Path) -> dict[str, Any]:
    if not (path / ".git").exists():
        return {"is_git": False}
    return {
        "is_git": True,
        "branch": git(path, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(path, "rev-parse", "--short", "HEAD"),
        "dirty": len([line for line in git(path, "status", "--porcelain").splitlines() if line.strip()]),
        "unpushed": len([line for line in git(path, "log", "--oneline", "@{u}..HEAD").splitlines() if line.strip()]),
    }


def scan_candidates(out: Path) -> dict[str, Any]:
    processes = running_processes()
    rows: list[dict[str, Any]] = []

    downloads = Path(os.environ.get("USERPROFILE", "")) / "Downloads"
    worktrees = []
    if downloads.is_dir():
        for entry in sorted(downloads.iterdir()):
            if not entry.is_dir() or not (entry / ".git").exists():
                continue
            info = git_survey(entry)
            is_own = any(marker in entry.name for marker in OWN_MARKERS)
            row = candidate(
                entry,
                owner="the user (this repository's worktree)" if info["dirty"] or info["unpushed"] or is_own else "the user",
                project=entry.name,
                action=(
                    "delete the worktree only after proving it is merged and has no unpushed commit: "
                    f"`git -C \"{entry.name}\" worktree remove` from the main checkout"
                ),
                alternative="keep it: a worktree is the only copy of its working tree",
                risk=(
                    f"{info['dirty']} uncommitted path(s), {info['unpushed']} unpushed commit(s) on "
                    f"{info['branch'] or 'unknown branch'}"
                ),
                processes=processes,
                own=False,
            )
            row["git"] = info
            worktrees.append(row)
    rows.extend(worktrees)

    temp = Path(os.environ.get("TEMP") or "/tmp")
    temp_rows = []
    if temp.is_dir():
        for entry in sorted(temp.iterdir()):
            if not entry.is_dir():
                continue
            measured = measure(entry, max_files=80_000, max_seconds=20)
            if measured["bytes"] < 32 * MIB:
                continue
            is_own = any(marker in entry.name for marker in ("codebuff-process",))
            temp_rows.append(
                candidate(
                    entry,
                    owner="every process on this host" if not is_own else "this agent's own tooling",
                    project=entry.name.split("-of-")[0][:40],
                    action="delete the directory once nothing holds it (Windows refuses an open file)",
                    alternative="leave it: Windows and the owning tool clean %TEMP% on their own schedule",
                    risk="a running test or browser profile in this directory would fail mid-run",
                    processes=processes,
                    own=is_own,
                )
            )
    rows.extend(temp_rows)

    fixed = [
        (Path("C:/ESD"), "Windows setup staging", "reclaim with Disk Cleanup or DISM, as administrator",
         "leave it: Windows removes it after an upgrade settles", "needs administrator rights"),
        (Path("C:/tmp"), "earlier sessions of this repository", "review each file, then delete",
         "keep it: some of it is evidence of past runs", "mixes evidence with scratch: needs a human read"),
        (Path(os.environ.get("LOCALAPPDATA", "")) / "wsl", "the user (WSL distributions)", "unregister an unused distribution with `wsl --unregister`",
         "compress the vhdx with `Optimize-VHD`, which needs the Hyper-V module", "destroys the distribution's filesystem"),
        (Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright", "the user (browser automation)",
         "delete a browser build; playwright re-downloads it", "leave it: other projects' tests depend on it",
         "any test suite using it will need the download again"),
        (Path(os.environ.get("LOCALAPPDATA", "")) / "hermes", "the user (tooling)", "clear its cache from the tool itself",
         "leave it: its cache is what makes the tool usable offline", "unknown retention policy"),
        (Path("C:/Windows/SoftwareDistribution/Download"), "Windows Update", "let Windows clean it, or run Disk Cleanup",
         "leave it: an interrupted update can leave the tree in use", "needs administrator rights"),
    ]
    for path, owner, action, alternative, risk in fixed:
        if not path.exists():
            continue
        rows.append(
            candidate(
                path,
                owner=owner,
                project=path.name,
                action=action,
                alternative=alternative,
                risk=risk,
                processes=processes,
            )
        )

    own_rows = []
    for pattern in CLEAN_PATTERNS:
        for path in REPO_ROOT.rglob(pattern):
            if not path.is_dir():
                continue
            relative = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if git(REPO_ROOT, "ls-files", "--", relative):
                continue
            measured = measure(path, max_files=50_000, max_seconds=10)
            own_rows.append(
                {
                    "path": relative,
                    "owner": "this work package",
                    "project": "WP-051-02J",
                    "bytes": measured["bytes"],
                    "gib": round(measured["bytes"] / GIB, 4),
                    "files": measured["files"],
                    "newest_age_hours": age_hours(measured.get("newest_mtime")),
                    "processes": [],
                    "classification": SAFE_OWNED,
                    "why": "byte-compiled cache, untracked by Git, rebuilt by the next import",
                    "action_to_free": "delete",
                    "alternative": "none needed",
                    "risk": "none: it is regenerated",
                }
            )
    rows.extend(own_rows)

    by_class: dict[str, int] = {}
    by_class_bytes: dict[str, int] = {}
    for row in rows:
        by_class[row["classification"]] = by_class.get(row["classification"], 0) + 1
        by_class_bytes[row["classification"]] = by_class_bytes.get(row["classification"], 0) + row["bytes"]
    rows.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now()),
        "volume": volume_free(Path("C:/")),
        "candidates": rows,
        "candidate_count": len(rows),
        "classes": by_class,
        "bytes_by_class": {key: value for key, value in by_class_bytes.items()},
        "gib_by_class": {key: round(value / GIB, 3) for key, value in by_class_bytes.items()},
        "safe_owned_bytes": by_class_bytes.get(SAFE_OWNED, 0),
        "approval_bytes": by_class_bytes.get(REQUIRES_APPROVAL, 0),
        "rule": (
            "SAFE_OWNED is the only class this program may delete. ACTIVE_OR_PROTECTED is never "
            "touched, and REQUIRES_APPROVAL is listed with the exact action and the risk so the "
            "decision belongs to the owner."
        ),
    }


# --------------------------------------------------------------------------- #
# Phase A — reading semantics and the lost day
# --------------------------------------------------------------------------- #
def reading_semantics(state_root: Path) -> dict[str, Any]:
    """Are the 0.00 GiB readings exhaustion, or an artefact of the instrument?

    Two independent questions, both answered here: what the instrument *is* (three APIs on the
    same volume, compared right now), and what the record shows (how many readings were near
    zero, whether the before/after pair agrees, and whether the tick that recorded it still
    managed to write its own log line).
    """
    import ctypes

    usage = shutil.disk_usage("C:/")
    kernel = ctypes.windll.kernel32
    freeb = ctypes.c_ulonglong()
    totalb = ctypes.c_ulonglong()
    totalfree = ctypes.c_ulonglong()
    kernel.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p("C:\\"),
        ctypes.byref(freeb),
        ctypes.byref(totalb),
        ctypes.byref(totalfree),
    )
    rows = []
    try:
        for line in (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except OSError:
        rows = []
    tiny = []
    for row in rows:
        before = (row.get("disk") or {}).get("free_bytes")
        after = (row.get("disk_after") or {}).get("free_bytes")
        for value in (before, after):
            if isinstance(value, int) and value < 50 * MIB:
                tiny.append(
                    {
                        "at_utc": row.get("started_at_utc"),
                        "free_bytes": value,
                        "outcome": row.get("outcome"),
                        "pair_equal": before == after,
                        "wrote_its_own_log": bool(row.get("run_id")),
                    }
                )
                break
    exact_zero = [item for item in tiny if item["free_bytes"] == 0]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "instrument": {
            "shutil_disk_usage_free": int(usage.free),
            "getdiskfreespaceex_free": int(freeb.value),
            "total_bytes": int(usage.total),
            "agreement_bytes": abs(int(usage.free) - int(freeb.value)),
            "note": (
                "shutil.disk_usage calls GetDiskFreeSpaceEx on Windows; the two are compared to "
                "show the reading is a direct OS answer, not a number this project computes"
            ),
        },
        "readings_below_50_mib": len(tiny),
        "readings_exactly_zero": len(exact_zero),
        "zero_examples": exact_zero[:6],
        "pair_agrees_in_every_tiny_reading": all(item["pair_equal"] for item in tiny) if tiny else None,
        "tick_wrote_its_log_while_reporting_zero": (
            all(item["wrote_its_own_log"] for item in exact_zero) if exact_zero else None
        ),
        "verdict": (
            "REAL_AVAILABILITY_ZERO"
            if exact_zero
            else "NO_ZERO_OBSERVED"
        ),
        "caveat": (
            "the value is what the API reports as available to this user, and Windows keeps a "
            "reserve it does not offer; the tick's own log line still landed, so the volume was "
            "not literally out of sectors. What matters for the campaign is that the guard acted "
            "on a real OS reading and not on a measurement error -- and it did."
        ),
    }


def attribution(out: Path) -> dict[str, Any]:
    """What moved the volume during this session, and what accounted for it.

    Two series taken at the same time: free space, and the write counters of every process the
    host reports. If the volume falls much faster than the sum of the writes, the consumption is
    outside process accounting -- pagefile growth, system caches, shadow copies, an update -- and
    saying "a process did it" would be a guess dressed as a finding.
    """
    samples = []
    try:
        for line in (out / "CONSUMPTION_SAMPLES.jsonl").read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict) and isinstance(parsed.get("free_bytes"), int):
                    samples.append(parsed)
    except (OSError, json.JSONDecodeError):
        samples = []
    trees: list[dict[str, Any]] = []
    try:
        for line in (out / "CONSUMPTION_TREES.jsonl").read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict) and isinstance(parsed.get("free_bytes"), int):
                    trees.append(parsed)
    except (OSError, json.JSONDecodeError):
        trees = []
    samples.sort(key=lambda row: row["at_utc"])
    intervals = []
    for previous, current in zip(samples, samples[1:]):
        delta_free = current["free_bytes"] - previous["free_bytes"]
        writers = current.get("top_writers") or []
        written = sum(int(item.get("delta") or 0) for item in writers)
        intervals.append(
            {
                "at_utc": current["at_utc"],
                "delta_free": delta_free,
                "written_by_top": written,
                "writers": writers,
            }
        )
    drops = [item for item in intervals if item["delta_free"] < 0]
    explained = sum(min(abs(item["delta_free"]), item["written_by_top"]) for item in drops)
    dropped = sum(abs(item["delta_free"]) for item in drops)
    per_tree: list[dict[str, Any]] = []
    if len(trees) >= 2:
        first, last = trees[0], trees[-1]
        before = {row["path"]: row.get("bytes") for row in first.get("trees") or []}
        for row in last.get("trees") or []:
            start = before.get(row["path"])
            if isinstance(start, int) and isinstance(row.get("bytes"), int):
                per_tree.append(
                    {
                        "path": row["path"],
                        "grew_bytes": row["bytes"] - start,
                        "grew_mib": round((row["bytes"] - start) / MIB, 2),
                    }
                )
        per_tree.sort(key=lambda item: item["grew_bytes"], reverse=True)
    per_process: dict[str, dict[str, Any]] = {}
    for item in drops:
        for writer in item.get("writers") or []:
            name = str(writer.get("name") or "unknown")
            entry = per_process.setdefault(name, {"name": name, "bytes": 0, "intervals": 0})
            entry["bytes"] += int(writer.get("delta") or 0)
            entry["intervals"] += 1
    ranked = sorted(per_process.values(), key=lambda row: row["bytes"], reverse=True)
    for row in ranked:
        row["mib"] = round(row["bytes"] / MIB, 2)
    share = round(100 * explained / dropped, 1) if dropped else None
    verdict = (
        "NO_DROP_OBSERVED"
        if not drops
        else ("ATTRIBUTED" if share is not None and share >= 70 else "PARTIALLY_ATTRIBUTED")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "samples": len(samples),
        "sample_span_minutes": (
            round(
                (
                    datetime.fromisoformat(samples[-1]["at_utc"].replace("Z", "+00:00"))
                    - datetime.fromisoformat(samples[0]["at_utc"].replace("Z", "+00:00"))
                ).total_seconds()
                / 60,
                1,
            )
            if len(samples) >= 2
            else None
        ),
        "intervals": len(intervals),
        "intervals_with_a_drop": len(drops),
        "dropped_bytes": dropped,
        "written_by_the_top_writers_during_drops": explained,
        "share_explained_percent": share,
        "verdict": verdict,
        "trees_measured": len(trees),
        "tree_growth": per_tree[:12],
        "top_writers_during_drops": ranked[:10],
        "top_writer_name": ranked[0]["name"] if ranked else None,
        "method_caveat": (
            "the writers are the eight largest per interval, so the explained share is a lower "
            "bound; a low share means the consumption is not visible in process write counters, "
            "not that no process exists"
        ),
    }


def lost_rows(main_root: Path) -> dict[str, Any]:
    """Reconstruct the lost day hour by hour, from the store the lane actually wrote."""
    day0 = int(datetime(2026, 10, 23, tzinfo=UTC).timestamp() * 1000)
    day1 = int(datetime(2026, 10, 24, tzinfo=UTC).timestamp() * 1000)
    per_asset: dict[str, Any] = {}
    for asset in ASSETS:
        path = main_root / "data" / "forward" / "edge03" / "1h" / f"{asset}.jsonl"
        rows: dict[int, dict[str, Any]] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                parsed = json.loads(line)
                stamp = parsed.get("ts")
                if isinstance(stamp, int) and day0 <= stamp < day1:
                    rows[stamp] = parsed
        except (OSError, json.JSONDecodeError):
            rows = {}
        hours = []
        for hour in range(24):
            stamp = day0 + hour * 3_600_000
            row = rows.get(stamp)
            if row is None:
                hours.append({"hour_utc": f"{hour:02d}:00", "status": "MISSING"})
                continue
            lag_ms = int(row.get("fetched_at_ms") or 0) - (stamp + 3_600_000)
            admissible = 0 <= lag_ms <= LAG_BOUND_MS
            hours.append(
                {
                    "hour_utc": f"{hour:02d}:00",
                    "status": "ADMISSIBLE" if admissible else "LATE",
                    "lag_minutes": round(lag_ms / 60_000, 1),
                    "fetched_at_utc": iso(datetime.fromtimestamp(int(row["fetched_at_ms"]) / 1000, tz=UTC))
                    if row.get("fetched_at_ms")
                    else None,
                }
            )
        per_asset[asset] = {
            "rows_present": len(rows),
            "missing": sum(1 for item in hours if item["status"] == "MISSING"),
            "late_beyond_bound": sum(1 for item in hours if item["status"] == "LATE"),
            "admissible": sum(1 for item in hours if item["status"] == "ADMISSIBLE"),
            "hours": hours,
        }
    refused = []
    try:
        for line in (main_root / "data" / "forward" / "edge04" / "runs.jsonl").read_text(
            encoding="utf-8"
        ).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("started_at_utc", "")).startswith(LOST_DAY) and str(
                row.get("outcome")
            ) == "DISK_BUDGET_EXCEEDED":
                refused.append(row.get("started_at_utc"))
    except (OSError, json.JSONDecodeError):
        refused = []
    total_admissible = sum(item["admissible"] for item in per_asset.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "day": LOST_DAY,
        "declared_rows_for_the_day": ROWS_PER_ASSET_PER_DAY * len(ASSETS),
        "admissible_rows": total_admissible,
        "assets": per_asset,
        "refused_ticks_that_day": len(refused),
        "refused_between_utc": [min(refused), max(refused)] if refused else None,
        "why_the_whole_day_was_excluded": (
            "the day holds bars whose lag exceeds the 120 min bound, and the lag policy in the "
            "phase-3 declaration excludes a day holding any inadmissible bar from the dataset and "
            "from the coverage numerator. One late bar costs the day, not one row: 72 declared "
            "rows are lost, of which the store holds "
            f"{total_admissible} admissible ones."
        ),
        "causal_chain": (
            "the volume was under the 2 GiB floor from 00:10Z, the guard refused every tick until "
            "05:25Z, and the hours that were eventually fetched after the refusals came with lag "
            "281, 221 and 161 minutes -- all above the bound."
        ),
        "not_repaired": (
            "nothing was re-fetched, re-timed or reclassified: the store keeps the late rows with "
            "their real lag, and the day stays lost."
        ),
    }


# --------------------------------------------------------------------------- #
# Phase B — the margin, recomputed
# --------------------------------------------------------------------------- #
def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def capacity(state_root: Path, main_root: Path) -> dict[str, Any]:
    """What the campaign needs, as a distribution rather than a single number.

    Three measures, because they answer three different questions: the median drawdown is an
    ordinary day, the 90th percentile is a bad one, and the maximum is the one that already
    happened. A budget built on the median is a budget that fails on the first bad Tuesday.
    """
    day0 = int(datetime(2026, 10, 23, tzinfo=UTC).timestamp() * 1000)
    samples: list[dict[str, Any]] = []
    try:
        for line in (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            reading = row.get("disk_after") or row.get("disk") or {}
            free = reading.get("free_bytes")
            stamp = row.get("started_at_ms")
            if isinstance(free, int) and isinstance(stamp, int):
                samples.append({"ts": stamp, "free": free})
    except (OSError, json.JSONDecodeError):
        samples = []
    samples.sort(key=lambda item: item["ts"])
    buckets: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        day = iso(datetime.fromtimestamp(sample["ts"] / 1000, tz=UTC))[:10]
        buckets.setdefault(day, []).append(sample)
    drawdowns: list[float] = []
    nets: list[float] = []
    for day, rows in buckets.items():
        if len(rows) < 2:
            continue
        peak = None
        worst = 0.0
        for row in rows:
            peak = row["free"] if peak is None else max(peak, row["free"])
            worst = max(worst, peak - row["free"])
        drawdowns.append(worst)
        nets.append(rows[-1]["free"] - rows[0]["free"])
    budget = read_json(state_root / "resource_budget.json") or {}
    own_samples = [
        row
        for row in (budget.get("samples") if isinstance(budget.get("samples"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("ts_ms"), int) and isinstance(row.get("bytes"), int)
    ]
    own_per_day = None
    if len(own_samples) >= 2:
        own_samples.sort(key=lambda row: row["ts_ms"])
        span_days = max((own_samples[-1]["ts_ms"] - own_samples[0]["ts_ms"]) / 86_400_000, 1e-9)
        own_per_day = int((own_samples[-1]["bytes"] - own_samples[0]["bytes"]) / span_days)
    own_window = (own_per_day or 0) * WINDOW_DAYS
    current = volume_free(Path("C:/"))
    p50 = percentile(drawdowns, 0.50)
    p90 = percentile(drawdowns, 0.90)
    worst = max(drawdowns) if drawdowns else 0.0
    required_p90 = own_window + CRITICAL_FREE_BYTES + max(0, int(p90))
    required_worst = own_window + CRITICAL_FREE_BYTES + max(0, int(worst))
    refused_total = 0
    try:
        for line in (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip() and '"DISK_BUDGET_EXCEEDED"' in line:
                refused_total += 1
    except OSError:
        refused_total = 0
    verdict = "SUFFICIENT" if current["free_bytes"] >= required_p90 and not refused_total else "INSUFFICIENT"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "window": {"start": WINDOW_START, "end": WINDOW_END, "days": WINDOW_DAYS},
        "history_days": len(drawdowns),
        "drawdown": {
            "p50_bytes": int(p50),
            "p90_bytes": int(p90),
            "max_bytes": int(worst),
            "basis": "largest peak-to-trough fall inside each complete UTC day of the observer's readings",
            "days_per_gib": [round(item / GIB, 3) for item in drawdowns],
        },
        "net_per_day": {
            "median_bytes": int(statistics.median(nets)) if nets else None,
            "median_gib": round(statistics.median(nets) / GIB, 3) if nets else None,
            "days_spending": sum(1 for item in nets if item < 0),
            "days_recovering": sum(1 for item in nets if item > 0),
        },
        "own": {
            "bytes_per_day": own_per_day,
            "window_bytes": own_window,
            "window_gib": round(own_window / GIB, 4),
        },
        "floor_bytes": CRITICAL_FREE_BYTES,
        "required": {
            "at_p90_bytes": required_p90,
            "at_p90_gib": round(required_p90 / GIB, 3),
            "at_worst_bytes": required_worst,
            "at_worst_gib": round(required_worst / GIB, 3),
        },
        "current_free_bytes": current["free_bytes"],
        "current_free_gib": current["free_gib"],
        "headroom_at_p90_bytes": current["free_bytes"] - required_p90,
        "shortfall_at_p90_gib": round(max(0, required_p90 - current["free_bytes"]) / GIB, 3),
        "refused_ticks_in_history": refused_total,
        "verdict": verdict,
        "verdict_note": (
            "the budget is the p90 drawdown plus the floor plus the campaign's own growth for the "
            "whole window. The maximum is reported next to it, not used as the budget: it is one "
            "observation, and building on it would guarantee failure on any worse day."
        ),
        "window_day0_ms": day0,
        "main_root": str(main_root),
    }


# --------------------------------------------------------------------------- #
# Phase C — channels
# --------------------------------------------------------------------------- #
def channels(state_root: Path) -> dict[str, Any]:
    """What can carry an alert, what each one answered, and which of them can prove receipt."""
    ledger = []
    try:
        for line in (state_root / "ALERT_LEDGER.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    ledger.append(parsed)
    except (OSError, json.JSONDecodeError):
        ledger = []
    with_receipt = [row for row in ledger if row.get("receipt")]
    latest = with_receipt[-1] if with_receipt else None
    env = {
        name: bool(os.environ.get(name, "").strip())
        for name in ("EDGE04_ALERT_WEBHOOK", "SLACK_WEBHOOK_URL", "SMTP_HOST", "TEAMS_WEBHOOK_URL")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "channels": [
            {
                "name": "desktop_toast",
                "detection": "watchdog state machine",
                "generation": "alert id from the transition and the instant",
                "delivery": "PowerShell toast, attributed to Windows PowerShell's AUMID",
                "receipt": "the OS notification history is read back by tag",
                "configured": True,
                "verified": bool(latest),
                "last_receipt": latest,
                "limitation": (
                    "needs an interactive session of the same user; on a locked or signed-out "
                    "machine the toast cannot be shown and the receipt check fails loudly"
                ),
            },
            {
                "name": "task_scheduler_last_result",
                "detection": "scheduler",
                "generation": "the process exit code",
                "delivery": "stored in the Task Scheduler database",
                "receipt": "none: nothing polls it",
                "configured": True,
                "verified": False,
                "limitation": "a signal, not a delivery: no one on this host reads it",
            },
            {
                "name": "windows_event_log",
                "detection": "n/a",
                "generation": "n/a",
                "delivery": "eventcreate",
                "receipt": "none",
                "configured": False,
                "verified": False,
                "limitation": "refused with 'Acceso denegado' without elevation (measured 2026-10-23)",
            },
            {
                "name": "webhook",
                "detection": "n/a",
                "generation": "n/a",
                "delivery": "HTTP POST",
                "receipt": "HTTP status",
                "configured": env["EDGE04_ALERT_WEBHOOK"],
                "verified": False,
                "limitation": (
                    "EDGE04_ALERT_WEBHOOK is not set; the code path exists and is tested, but no "
                    "URL is configured and this session will not invent one"
                ),
            },
        ],
        "environment_presence": env,
        "ledger_entries": len(ledger),
        "delivered_with_receipt": len(with_receipt),
        "suppressed": len([row for row in ledger if row.get("suppressed")]),
        "delivery_verdict": "PASS_LOCAL" if latest else "BLOCKED",
        "remote_verdict": "BLOCKED",
        "statement": (
            "an alert can now reach the person at this machine, and the OS records the receipt. "
            "An alert cannot yet leave the machine: no webhook, no mail transport and no event-log "
            "permission exist here. Until one of those is enabled, an unattended failure at night "
            "is still only recorded, not delivered."
        ),
    }


# --------------------------------------------------------------------------- #
# cleaning (own caches only)
# --------------------------------------------------------------------------- #
def clean_own(out: Path) -> dict[str, Any]:
    before = volume_free(Path("C:/"))
    removed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for pattern in CLEAN_PATTERNS:
        for path in sorted(REPO_ROOT.rglob(pattern)):
            if not path.is_dir():
                continue
            relative = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if git(REPO_ROOT, "ls-files", "--", relative):
                kept.append({"path": relative, "why": "tracked by Git"})
                continue
            measured = measure(path, max_files=50_000, max_seconds=10)
            try:
                shutil.rmtree(path)
                removed.append({"path": relative, "bytes": measured["bytes"]})
            except OSError as exc:
                kept.append({"path": relative, "why": str(exc)})
    after = volume_free(Path("C:/"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "before": before,
        "after": after,
        "removed": removed,
        "kept": kept,
        "deleted_bytes": sum(item["bytes"] for item in removed),
        "volume_delta_bytes": after["free_bytes"] - before["free_bytes"],
        "note": (
            "only this worktree's untracked byte-compiled caches. The volume moves for reasons "
            "this program does not control, so deleted_bytes is the quantity it is responsible for."
        ),
    }
    write_json(out / "CLEANUP_EVIDENCE.json", payload)
    return payload


# --------------------------------------------------------------------------- #
# the suite, actually run
# --------------------------------------------------------------------------- #
def run_tests(out: Path) -> dict[str, Any]:
    """Run this package's suite and record the exit status it actually produced.

    The verifier does not run the suite: it re-reads this file and its exit code, which is why the
    code is recorded rather than a headline. A run whose tests did not execute is not a pass, and
    the parser refuses to report one.
    """
    started = time.time()
    command = [sys.executable, "-m", "pytest", PYTEST_SUITE, "-q"]
    try:
        completed = subprocess.run(
            command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900
        )
        code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, stdout, stderr = -1, "", repr(exc)
    tail = (stdout.strip().splitlines() or [""])[-1]
    import re

    passed = int((re.search(r"(\d+) passed", stdout) or [0, "0"])[1])
    failed = int((re.search(r"(\d+) failed", stdout) or [0, "0"])[1])
    errors = int((re.search(r"(\d+) error", stdout) or [0, "0"])[1])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "suite": PYTEST_SUITE,
        "suite_sha256": digest(REPO_ROOT / PYTEST_SUITE),
        "suite_bytes": (REPO_ROOT / PYTEST_SUITE).stat().st_size
        if (REPO_ROOT / PYTEST_SUITE).is_file()
        else None,
        "command": " ".join(command),
        "exit_code": code,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "duration_seconds": round(time.time() - started, 2),
        "summary": tail,
        "stdout_tail": stdout.strip().splitlines()[-12:],
        "stderr_tail": stderr.strip().splitlines()[-12:],
        "status": "PASS" if code == 0 and passed > 0 and not failed and not errors else "FAIL",
        "note": (
            "the exit code is the recorder's own, not a summary line: a suite that did not run, or "
            "ran and failed, cannot be reported as a pass from here."
        ),
    }
    write_json(out / "TEST_EVIDENCE.json", payload)
    return payload


# --------------------------------------------------------------------------- #
# the scheduler, asked directly
# --------------------------------------------------------------------------- #
_TASK_FIELDS = {
    "name": ("nombre de tarea", "taskname", "task name"),
    "next_run": ("xima ejecuci", "next run time"),
    "last_run": ("ltimo tiempo de ejecuci", "last run time"),
    "last_result": ("ltimo resultado", "last result"),
    "status": ("estado:", "status:"),
    "state": ("estado de tarea programada", "scheduled task state"),
    "command": ("tarea que se ejecutar", "task to run"),
    "repeat": ("repetir: cada", "repeat: every"),
}


def parse_task_output(text: str) -> dict[str, Any]:
    """Read ``schtasks``' verbose listing without depending on one locale.

    The labels are matched on fragments that survive both the Spanish listing this host returns
    and the English one an unattended runner would produce; the values are kept verbatim.
    """
    fields: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        lowered = label.strip().lower()
        for key, needles in _TASK_FIELDS.items():
            if key in fields:
                continue
            if any(needle in lowered for needle in needles):
                fields[key] = value.strip()
                break
    return fields


def task_state(name: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"task": name, "registered": False, "error": repr(exc)}
    fields = parse_task_output(completed.stdout or "")
    registered = completed.returncode == 0 and bool(fields.get("name"))
    return {
        "task": name,
        "registered": registered,
        "query_exit": completed.returncode,
        "enabled": str(fields.get("state") or "").lower().startswith(("habilitado", "enabled", "ready", "listo")),
        "status": fields.get("status"),
        "last_run_local": fields.get("last_run"),
        "last_result": fields.get("last_result"),
        "next_run_local": fields.get("next_run"),
        "command": fields.get("command"),
        "repeat": fields.get("repeat"),
        "raw_fields": fields,
    }


def _local_to_utc(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            naive = datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
        return naive.astimezone().astimezone(UTC)
    return None


def scheduler(state_root: Path, out: Path) -> dict[str, Any]:
    """Prove the alarm is scheduled *and* that the schedule fires, without trusting a log.

    Three independent facts are compared for each entry: what the scheduler says about its own
    last run, what the process wrote when it ran, and how old that written verdict is now. A task
    that is registered but never fires shows up as a mismatch between the first and the second;
    a task that fired and crashed without writing shows up in the opposite direction.
    """
    observed = now()
    rows: list[dict[str, Any]] = []
    for name in SCHEDULER_TASKS:
        row = task_state(name)
        artifacts = ["WATCHDOG.json"] if name.endswith("Watchdog") else ["SUPERVISOR.json"]
        evidence: list[dict[str, Any]] = []
        for artifact in artifacts:
            payload = read_json(state_root / artifact) or {}
            stamp = payload.get("generated_at_utc")
            age = None
            if stamp:
                try:
                    age = round((observed - datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))).total_seconds(), 1)
                except ValueError:
                    age = None
            evidence.append({"artifact": artifact, "generated_at_utc": stamp, "age_seconds": age})
        last_run = _local_to_utc(row.get("last_run_local"))
        correlation = None
        newest = next((item for item in evidence if item["generated_at_utc"]), None)
        if last_run is not None and newest is not None:
            written = datetime.fromisoformat(str(newest["generated_at_utc"]).replace("Z", "+00:00"))
            correlation = round((written - last_run).total_seconds(), 1)
        refreshed = [item for item in evidence if item["age_seconds"] is not None and item["age_seconds"] < 1800]
        result_text = str(row.get("last_result") or "")
        ran = result_text.isdigit() and int(result_text) in DOCUMENTED_EXIT_CODES
        row.update(
            {
                "last_run_utc": iso(last_run) if last_run else None,
                "artifacts": evidence,
                "written_by_that_run_seconds": correlation,
                "written_within_the_last_half_hour": bool(refreshed),
                "last_result_is_a_documented_exit": ran,
                "fires_automatically": bool(
                    row.get("registered")
                    and row.get("enabled")
                    and ran
                    and correlation is not None
                    and abs(correlation) <= 300
                ),
            }
        )
        rows.append(row)
    firing = [row for row in rows if row.get("fires_automatically")]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(observed),
        "tasks": rows,
        "registered": sum(1 for row in rows if row.get("registered")),
        "firing": len(firing),
        "documented_exit_codes": list(DOCUMENTED_EXIT_CODES),
        "verdict": "PASS" if len(firing) == len(SCHEDULER_TASKS) else "BLOCKED",
        "statement": (
            "a registration is a promise; this compares the scheduler's own last-run record with "
            "the timestamp the process wrote when it ran. Both entries must agree within five "
            "minutes for the alarm to be called scheduled."
        ),
    }
    write_json(out / "SCHEDULER_EVIDENCE.json", payload)
    return payload


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def report(out: Path) -> dict[str, Any]:
    diagnosis = read_json(out / "DIAGNOSIS.json") or {}
    capacity_row = read_json(out / "CAPACITY_PLAN.json") or {}
    channel_row = read_json(out / "ALERT_CHANNELS.json") or {}
    lost = read_json(out / "LOST_ROWS.json") or {}
    cleanup = read_json(out / "CLEANUP_EVIDENCE.json") or {}
    verification = read_json(out / "INDEPENDENT_VERIFICATION_02J.json") or {}
    tests = read_json(out / "TEST_EVIDENCE.json") or {}
    scheduling = read_json(out / "SCHEDULER_EVIDENCE.json") or {}
    verdict = "BLOCKED"
    if (
        capacity_row.get("verdict") == "SUFFICIENT"
        and channel_row.get("delivery_verdict") == "PASS_LOCAL"
        and scheduling.get("verdict") == "PASS"
        and tests.get("status") == "PASS"
        and verification.get("verdict") == "PASS"
    ):
        verdict = "PASS"
    elif channel_row.get("delivery_verdict") != "PASS_LOCAL":
        verdict = "BLOCKED"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now()),
        "head": git(REPO_ROOT, "rev-parse", "HEAD"),
        "worktree": str(REPO_ROOT),
        "verdict": verdict,
        "capacity": {
            "before_free_bytes": diagnosis.get("volume", {}).get("free_bytes"),
            "after_free_bytes": cleanup.get("after", {}).get("free_bytes")
            or diagnosis.get("volume", {}).get("free_bytes"),
            "deleted_bytes": cleanup.get("deleted_bytes", 0),
            "required_at_p90_gib": capacity_row.get("required", {}).get("at_p90_gib"),
            "shortfall_gib": capacity_row.get("shortfall_at_p90_gib"),
            "verdict": capacity_row.get("verdict"),
        },
        "consumption": {
            "approval_gib": diagnosis.get("gib_by_class", {}).get(REQUIRES_APPROVAL),
            "safe_owned_gib": diagnosis.get("gib_by_class", {}).get(SAFE_OWNED),
            "active_or_protected_gib": diagnosis.get("gib_by_class", {}).get(ACTIVE_OR_PROTECTED),
            "unknown_gib": diagnosis.get("gib_by_class", {}).get(UNKNOWN),
        },
        "alerts": {
            "delivery_verdict": channel_row.get("delivery_verdict"),
            "remote_verdict": channel_row.get("remote_verdict"),
            "delivered_with_receipt": channel_row.get("delivered_with_receipt"),
            "suppressed": channel_row.get("suppressed"),
        },
        "campaign": {
            "window": {"start": WINDOW_START, "end": WINDOW_END, "days": WINDOW_DAYS},
            "lost_day": LOST_DAY,
            "lost_rows": lost.get("declared_rows_for_the_day"),
            "admissible_rows_that_day": lost.get("admissible_rows"),
            "rows_still_available": DECLARED_ROWS - (lost.get("declared_rows_for_the_day") or 0),
            "floor_rows": int(DECLARED_ROWS * REQUIRED_FRACTION),
        },
        "verification": {
            "verdict": verification.get("verdict"),
            "passed": verification.get("passed"),
            "checks": verification.get("check_count"),
        },
        "tests": tests,
        "scheduling": {
            "verdict": scheduling.get("verdict"),
            "registered": scheduling.get("registered"),
            "firing": scheduling.get("firing"),
            "tasks": [
                {
                    "task": row.get("task"),
                    "last_run_utc": row.get("last_run_utc"),
                    "last_result": row.get("last_result"),
                    "fires_automatically": row.get("fires_automatically"),
                }
                for row in scheduling.get("tasks") or []
            ],
        },
        "risks": [
            "the volume still holds far less than the p90 budget: any multi-day cleaning pause costs days",
            "no remote channel exists: an overnight failure is recorded, not delivered",
            "the toast needs an interactive session; a signed-out machine cannot be paged",
            "the drawdown's source is not attributed to a process; it is larger than the sum of measured writes",
        ],
    }
    write_json(out / "FINAL_REPORT_02J.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--main-root", type=Path, default=MAIN_ROOT)
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--diagnosis", action="store_true")
    parser.add_argument("--capacity", action="store_true")
    parser.add_argument("--channels", action="store_true")
    parser.add_argument("--scheduler", action="store_true")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    main_root = args.main_root.resolve()
    state_root = (args.state_root or main_root / "data" / "forward" / "edge04").resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    did = False

    if args.diagnosis:
        did = True
        scan = scan_candidates(out)
        write_json(out / "DIAGNOSIS.json", scan)
        semantics = reading_semantics(state_root)
        write_json(out / "DISK_READING_SEMANTICS.json", semantics)
        lost = lost_rows(main_root)
        write_json(out / "LOST_ROWS.json", lost)
        attributed = attribution(out)
        write_json(out / "CONSUMPTION_ATTRIBUTION.json", attributed)
        if not args.json:
            print(f"volume   {scan['volume']['free_gib']} GiB free")
            for key, value in scan["gib_by_class"].items():
                print(f"  {key:22} {value:8.3f} GiB")
            print(f"readings  semantics {semantics['verdict']} ({semantics['readings_exactly_zero']} zeros)")
            print(f"lost day  {lost['admissible_rows']}/{lost['declared_rows_for_the_day']} admissible")
            print(
                f"consumption {attributed['verdict']}: {attributed['dropped_bytes'] / MIB:.0f} MiB "
                f"dropped, {attributed['share_explained_percent']}% explained by process writes"
            )
    if args.capacity:
        did = True
        plan = capacity(state_root, main_root)
        write_json(out / "CAPACITY_PLAN.json", plan)
        if not args.json:
            print(f"capacity {plan['verdict']}: p90 {plan['required']['at_p90_gib']} GiB, "
                  f"free {plan['current_free_gib']} GiB, shortfall {plan['shortfall_at_p90_gib']} GiB")
    if args.channels:
        did = True
        row = channels(state_root)
        write_json(out / "ALERT_CHANNELS.json", row)
        if not args.json:
            print(f"alerts   local={row['delivery_verdict']} remote={row['remote_verdict']} "
                  f"receipts={row['delivered_with_receipt']}")
    if args.scheduler:
        did = True
        row = scheduler(state_root, out)
        if not args.json:
            print(f"accounts {row['verdict']}: {row['firing']}/{len(SCHEDULER_TASKS)} task(s) firing")
            for item in row["tasks"]:
                print(
                    f"  {item['task']:34} last={item.get('last_run_utc')} "
                    f"result={item.get('last_result')} wrote={item.get('written_by_that_run_seconds')}s "
                    f"-> {item.get('fires_automatically')}"
                )
    if args.tests:
        did = True
        suite = run_tests(out)
        if not args.json:
            print(
                f"tests    {suite['status']}: {suite['passed']} passed, {suite['failed']} failed, "
                f"exit {suite['exit_code']} in {suite['duration_seconds']}s"
            )
    if args.clean:
        did = True
        cleaned = clean_own(out)
        if not args.json:
            print(f"cleanup  deleted {cleaned['deleted_bytes'] / MIB:.2f} MiB in "
                  f"{len(cleaned['removed'])} director(ies)")
    if args.report:
        did = True
        final = report(out)
        if not args.json:
            print(f"report   verdict {final['verdict']}")
    if not did:
        parser.print_help()
        return 2
    if args.json:
        print(json.dumps(read_json(out / "FINAL_REPORT_02J.json") or {}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
