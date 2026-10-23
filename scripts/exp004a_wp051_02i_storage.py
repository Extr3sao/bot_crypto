"""EDGE-04 storage stability: measure the volume, attribute the consumption, reclaim only
what this package owns, and project the campaign's own 90-day need.

The forward observer already refuses a tick when free space falls under its critical floor,
and already records the reading it refused on. That is a correct guard and it is not the
subject of this program. The subject is the question the guard cannot answer from inside a
single tick: *how fast is the volume being spent, by whom, and will it last the window?*

Three rules shape everything below.

1. **Measured, never assumed.** Every number in the report is either read from the
   filesystem, recomputed from the lane's own ``runs.jsonl`` history, or derived from an
   explicitly labelled hypothesis. A number that cannot be measured is reported as
   ``UNKNOWN`` with the reason, never as a default.
2. **Attribution before action.** A directory is only a reclamation candidate when this
   package can name its owner, say why the bytes are regenerable, and prove the bytes are
   not tracked by Git. Everything else is reported and left alone — including the bytes
   that would help most.
3. **The campaign's footprint is not the host's consumption.** These are two different
   series with two different owners, and reporting them as one number is how a 20 MiB
   dataset gets blamed for a 3.5 GiB decline.

Usage::

    python scripts/exp004a_wp051_02i_storage.py --audit
    python scripts/exp004a_wp051_02i_storage.py --sweep            # dry run
    python scripts/exp004a_wp051_02i_storage.py --sweep --apply    # delete, with evidence
    python scripts/exp004a_wp051_02i_storage.py --json

Research only: reads the filesystem, deletes only whitelisted untracked caches inside its
own worktree, sends nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "EXP004A_WP051_02I_STORAGE_V1"
PACKAGE = "WP-051-02I"

GIB = 1024**3
MIB = 1024**2

#: The campaign's floor, unchanged by this package.  It belongs to the observer's own guard
#: (:mod:`trading_bot.research.disk_space`) and this program only measures against it.
CRITICAL_FREE_BYTES = 2 * GIB
WARNING_FREE_BYTES = 5 * GIB

#: The window the phase-3 declaration fixes.  Repeated here rather than imported: the
#: declaration is a JSON contract, and this program must be able to measure a campaign whose
#: contract it does not import.
WINDOW_DAYS = 90
ROWS_PER_ASSET_PER_DAY = 24
ASSETS = 3

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = Path(
    r"C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04"
)
DEFAULT_OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02i"

#: Directories a sweep may delete, and only when Git does not track a single byte inside
#: them.  Every entry names the *why*; an entry without a reason does not belong here.
SWEEP_PATTERNS: tuple[tuple[str, str], ...] = (
    ("__pycache__", "byte-compiled Python, rebuilt by the next import"),
    (".pytest_cache", "pytest's own result cache, never an input"),
    (".mypy_cache", "type-checker cache, rebuilt by `mypy`"),
    (".ruff_cache", "linter cache, rebuilt by `ruff`"),
    (".hypothesis", "property-test example database, rebuilt by `pytest`"),
)

#: Scratch files this package writes while it measures.  Kept out of the sweep list above
#: because they are files, not directories, and they are the evidence of the measurement.
SCRATCH_KEEP = ("samples.jsonl", "audit.json")

#: Roots measured for attribution.  ``owner`` says who can authorise deletion; ``class``
#: says what kind of bytes they are.  ``deletable_here`` is the only field a sweep reads.
CONSUMERS: tuple[dict[str, Any], ...] = (
    {
        "id": "lane_state",
        "path": "data/forward/edge04",
        "root": "main",
        "owner": "this campaign",
        "class": "PROTECTED_EVIDENCE",
        "why": "the forward store, its run log, its daily shards and its publications",
    },
    {
        "id": "lane_source_store",
        "path": "data/forward/edge03",
        "root": "main",
        "owner": "this campaign",
        "class": "PROTECTED_EVIDENCE",
        "why": "the frozen 1h/4h store the lane reads; rewritable only by the venue",
    },
    {
        "id": "phase3_shards",
        "path": "data/exp004a",
        "root": "main",
        "owner": "this campaign",
        "class": "PROTECTED_EVIDENCE",
        "why": "write-once prospective shards, one per day per asset",
    },
    {
        "id": "git_objects",
        "path": ".git",
        "root": "main",
        "owner": "the repository",
        "class": "PROTECTED_REPOSITORY",
        "why": "history; every package's evidence manifest resolves through it",
    },
    {
        "id": "other_agent_temp",
        "path": "%TEMP%/edge14r",
        "root": "temp",
        "owner": "another agent (running processes)",
        "class": "FOREIGN_IN_USE",
        "why": "two live python processes have their virtualenv and database here",
    },
    {
        "id": "audit_baseline",
        "path": ".tmp/audit/baseline-wt",
        "root": "main",
        "owner": "another agent",
        "class": "FOREIGN",
        "why": "a second checkout of this repository, not this package's",
    },
    {
        "id": "downloads_worktrees",
        "path": "%HOME%/Downloads",
        "root": "home",
        "owner": "the user and other packages",
        "class": "FOREIGN",
        "why": "other worktrees and user files; deleting them is not this package's call",
    },
    {
        "id": "temp",
        "path": "%TEMP%",
        "root": "temp",
        "owner": "every process on this host",
        "class": "SHARED_TEMP",
        "why": "pytest and browser scratch, regenerable but owned by whoever is running",
    },
)


# --------------------------------------------------------------------------- #
# clock, git, io
# --------------------------------------------------------------------------- #
def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


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


def home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or REPO_ROOT)


def temp() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")


def expand(spec: str) -> Path:
    return Path(
        spec.replace("%TEMP%", str(temp())).replace("%HOME%", str(home()))
    )


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #
def volume_anchor(path: Path) -> Path:
    """The nearest existing ancestor: free space is a property of the volume."""
    current = Path(path).resolve()
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    return current


def volume(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(volume_anchor(path))
    free, total = int(usage.free), int(usage.total)
    return {
        "path": str(path),
        "anchor": str(volume_anchor(path)),
        "free_bytes": free,
        "total_bytes": total,
        "used_bytes": total - free,
        "free_gib": round(free / GIB, 4),
        "total_gib": round(total / GIB, 4),
        "used_percent": round((total - free) / total * 100, 2) if total else None,
        "critical_free_bytes": CRITICAL_FREE_BYTES,
        "warning_free_bytes": WARNING_FREE_BYTES,
        "status": (
            "CRITICAL"
            if free < CRITICAL_FREE_BYTES
            else ("WARNING" if free < WARNING_FREE_BYTES else "HEALTHY")
        ),
    }


def measure_tree(root: Path, *, max_files: int = 400_000, max_seconds: float = 120.0) -> dict[str, Any]:
    """Bytes and file count under ``root``, bounded in both files and wall time.

    A bound rather than an estimate: when either limit is hit the result says so, so a
    truncated measurement can never be read as a complete one.
    """
    import time

    started = time.monotonic()
    total = files = 0
    truncated = None
    if not root.exists():
        return {"path": str(root), "exists": False, "bytes": 0, "files": 0, "truncated": None}
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
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
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
        "truncated": truncated,
        "bytes_gib": round(total / GIB, 4),
        "bytes_mib": round(total / MIB, 2),
    }


def consumer_table(main_root: Path) -> list[dict[str, Any]]:
    """Every consumer, with its size measured at a named instant.

    ``root`` decides where a relative path is anchored: ``main`` paths belong to the checkout
    the lane writes to, not to this worktree. Resolving them against the working directory
    would measure a directory that does not exist and report it as zero bytes -- an absence
    that reads like a finding.
    """
    rows: list[dict[str, Any]] = []
    for spec in CONSUMERS:
        target = (
            main_root / str(spec["path"])
            if spec.get("root") == "main"
            else expand(str(spec["path"]))
        )
        measured = measure_tree(target)
        rows.append(
            {
                **spec,
                "measured": measured,
                "measured_at_utc": iso(now_ms()),
                "volatile": spec["class"] in ("SHARED_TEMP", "FOREIGN", "FOREIGN_IN_USE"),
            }
        )
    return rows


def lane_history(state_root: Path) -> dict[str, Any]:
    """Every free-space reading the observer itself wrote, oldest first.

    The lane records a reading before and after every tick. Using the *after* reading when it
    exists keeps the series to one sample per tick: mixing both would report the publication's
    own temporary copy as volume consumption.
    """
    runs = state_root / "runs.jsonl"
    samples: list[dict[str, Any]] = []
    unparsable = 0
    if not runs.is_file():
        return {"available": False, "reason": f"{runs} does not exist", "samples": []}
    try:
        raw = runs.read_bytes()
    except OSError as exc:
        return {"available": False, "reason": f"{runs}: {exc}", "samples": []}
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            unparsable += 1
            continue
        if not isinstance(row, dict):
            unparsable += 1
            continue
        reading = row.get("disk_after") or row.get("disk") or {}
        free = reading.get("free_bytes") if isinstance(reading, dict) else None
        stamp = row.get("started_at_ms")
        if isinstance(free, int) and isinstance(stamp, int):
            samples.append(
                {
                    "ts_ms": stamp,
                    "free_bytes": free,
                    "outcome": row.get("outcome"),
                    "run_id": row.get("run_id"),
                }
            )
    samples.sort(key=lambda item: item["ts_ms"])
    return {
        "available": bool(samples),
        "path": str(runs),
        "samples": samples,
        "sample_count": len(samples),
        "unparsable_lines": unparsable,
        "first_at_utc": iso(samples[0]["ts_ms"]) if samples else None,
        "last_at_utc": iso(samples[-1]["ts_ms"]) if samples else None,
    }


#: Two refusals belong to the same episode when no accepted tick separates them by more than
#: two collection intervals.  The interval is the lane's own; the tolerance exists because a
#: tick can be skipped entirely (machine asleep) without the episode having ended.
EPISODE_GAP_MS = 2 * 15 * 60 * 1000


def breach_episodes(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Every stretch during which the volume was under the floor, and what it cost the lane.

    Two independent readings, both kept because they answer different questions:

    * the *free-space* series says how long the volume was under 2 GiB;
    * the *outcome* series says how many slots the guard actually refused.

    A volume can be under the floor between two ticks and recover before the next one, in
    which case it costs nothing. Reporting only the first number would overstate the loss;
    reporting only the second would hide how close the host came.
    """
    breaches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for sample in samples:
        free = sample["free_bytes"]
        if free < CRITICAL_FREE_BYTES:
            if current is not None and sample["ts_ms"] - current["last_ms"] <= EPISODE_GAP_MS:
                current["last_ms"] = sample["ts_ms"]
                current["samples"] += 1
                current["min_free_bytes"] = min(current["min_free_bytes"], free)
            else:
                if current is not None:
                    breaches.append(current)
                current = {
                    "start_ms": sample["ts_ms"],
                    "last_ms": sample["ts_ms"],
                    "samples": 1,
                    "min_free_bytes": free,
                }
        elif current is not None:
            breaches.append(current)
            current = None
    if current is not None:
        breaches.append(current)
    for item in breaches:
        item["start_at_utc"] = iso(item["start_ms"])
        item["end_at_utc"] = iso(item["last_ms"])
        item["hours"] = round((item["last_ms"] - item["start_ms"]) / 3_600_000 + 0.25, 2)
        item["min_free_gib"] = round(item["min_free_bytes"] / GIB, 3)
    refusals = [s for s in samples if str(s.get("outcome")) == "DISK_BUDGET_EXCEEDED"]
    by_day: dict[str, int] = {}
    for item in refusals:
        day = iso(item["ts_ms"])[:10]
        by_day[day] = by_day.get(day, 0) + 1
    # Refusals are grouped over the whole series, not over the refusals alone: a tick that ran
    # and was accepted ends an episode, and a gap in the refusals alone cannot see it.
    refusal_episodes: list[dict[str, Any]] = []
    current_refusal: dict[str, Any] | None = None
    for item in samples:
        if str(item.get("outcome")) == "DISK_BUDGET_EXCEEDED":
            if (
                current_refusal is not None
                and item["ts_ms"] - current_refusal["last_ms"] <= EPISODE_GAP_MS
            ):
                current_refusal["last_ms"] = item["ts_ms"]
                current_refusal["ticks"] += 1
            else:
                if current_refusal is not None:
                    refusal_episodes.append(current_refusal)
                current_refusal = {"start_ms": item["ts_ms"], "last_ms": item["ts_ms"], "ticks": 1}
        elif current_refusal is not None:
            refusal_episodes.append(current_refusal)
            current_refusal = None
    if current_refusal is not None:
        refusal_episodes.append(current_refusal)
    for item in refusal_episodes:
        item["start_at_utc"] = iso(item["start_ms"])
        item["end_at_utc"] = iso(item["last_ms"])
        item["hours"] = round(item["ticks"] * 0.25, 2)
    return {
        "free_space_episodes": breaches,
        "free_space_episode_count": len(breaches),
        "refusal_episodes": refusal_episodes,
        "refusal_episode_count": len(refusal_episodes),
        "hours_under_floor": round(sum(item["hours"] for item in breaches), 2),
        "lowest_free_bytes": min((item["min_free_bytes"] for item in breaches), default=None),
        "lowest_free_gib": (
            round(min(item["min_free_bytes"] for item in breaches) / GIB, 3) if breaches else None
        ),
        "refused_ticks": len(refusals),
        "refused_ticks_by_day": dict(sorted(by_day.items())),
        "refused_hours": round(len(refusals) * 0.25, 2),
        "bar_opportunities_refused": len(refusals) * ASSETS,
        "note": (
            "a refused tick costs its slot: the guard refuses before any request, so the bars "
            "in that slot are never fetched, and the lag policy forbids fetching them later."
        ),
    }


def daily_series(samples: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per UTC day: first, last, minimum and maximum free bytes."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        day = iso(sample["ts_ms"])[:10]
        buckets.setdefault(day, []).append(sample)
    rows: list[dict[str, Any]] = []
    for day in sorted(buckets):
        ordered = sorted(buckets[day], key=lambda item: item["ts_ms"])
        frees = [item["free_bytes"] for item in ordered]
        rows.append(
            {
                "day": day,
                "samples": len(ordered),
                "first_free_bytes": frees[0],
                "last_free_bytes": frees[-1],
                "min_free_bytes": min(frees),
                "max_free_bytes": max(frees),
                "net_change_bytes": frees[-1] - frees[0],
                "first_at_utc": iso(ordered[0]["ts_ms"]),
                "last_at_utc": iso(ordered[-1]["ts_ms"]),
            }
        )
    return rows


def max_drawdown(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """The largest fall from a peak inside one UTC day, chronologically.

    Not ``max - min`` of the day: a day that starts at 0.5 GiB, is cleaned back to 22 GiB and
    then falls to 9 GiB has a range of 22 GiB and a drawdown of 14 GiB. Only the second number
    is headroom the volume had to *hold*; the first is the size of somebody's cleanup.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        buckets.setdefault(iso(sample["ts_ms"])[:10], []).append(sample)
    best: dict[str, Any] = {"bytes": 0, "day": None, "from_bytes": None, "to_bytes": None}
    for day, rows in buckets.items():
        peak = None
        for row in sorted(rows, key=lambda item: item["ts_ms"]):
            free = row["free_bytes"]
            if peak is None or free > peak:
                peak = free
            fall = peak - free
            if fall > best["bytes"]:
                best = {
                    "bytes": fall,
                    "day": day,
                    "from_bytes": peak,
                    "to_bytes": free,
                    "at_utc": iso(row["ts_ms"]),
                }
    return best


def trend(daily: list[dict[str, Any]]) -> dict[str, Any]:
    """The median daily net change, with the spread that decides whether to trust it.

    The median rather than the mean: one day that started right after a cleanup would drag a
    mean far from what the volume is doing on an ordinary day. The spread is reported next to
    it, because a median with a range of ±3 GiB is not a forecast — it is a shape.
    """
    deltas = [row["net_change_bytes"] for row in daily if row["samples"] >= 2]
    if len(deltas) < 2:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": f"{len(deltas)} day(s) hold two or more readings; two are the minimum",
            "days": len(deltas),
            "median_bytes_per_day": None,
        }
    ordered = sorted(deltas)
    median = statistics.median(ordered)
    return {
        "status": "MEASURED",
        "basis": "median of per-UTC-day net change, first reading to last reading of the day",
        "days": len(deltas),
        "median_bytes_per_day": int(median),
        "median_gib_per_day": round(median / GIB, 4),
        "min_bytes_per_day": int(ordered[0]),
        "max_bytes_per_day": int(ordered[-1]),
        "days_spending": sum(1 for item in deltas if item < 0),
        "days_recovering": sum(1 for item in deltas if item > 0),
        "per_day_bytes": [int(item) for item in deltas],
    }


def lane_growth(state_root: Path) -> dict[str, Any]:
    """How fast the campaign's own tree grows, from its own history.

    Two independent readings, both recorded: the file's own growth over the window it covers,
    and the per-day increment implied by the objects it writes (a daily shard per asset, the
    run log's own line rate). Neither is extrapolated into the other.
    """
    store = state_root
    budget = read_json(store / "resource_budget.json") or {}
    samples = budget.get("samples") if isinstance(budget.get("samples"), list) else []
    usable = [
        row for row in samples if isinstance(row, dict) and isinstance(row.get("ts_ms"), int)
        and isinstance(row.get("bytes"), int)
    ]
    result: dict[str, Any] = {
        "resource_budget_samples": len(usable),
        "resource_budget_note": (
            "the observer samples its own tree size into resource_budget.json; a series with "
            "fewer than two usable samples supports no rate"
        ),
    }
    if len(usable) >= 2:
        ordered = sorted(usable, key=lambda row: row["ts_ms"])
        span_days = max((ordered[-1]["ts_ms"] - ordered[0]["ts_ms"]) / 86_400_000, 1e-9)
        result["resource_budget_span_days"] = round(span_days, 3)
        result["resource_budget_bytes_per_day"] = int(
            (ordered[-1]["bytes"] - ordered[0]["bytes"]) / span_days
        )
    runs = store / "runs.jsonl"
    if runs.is_file():
        stat = runs.stat()
        result["runs_jsonl_bytes"] = stat.st_size
    return result


def shard_sizes(roots: Iterable[Path]) -> dict[str, Any]:
    """Bytes per row, measured on the write-once shards the campaign actually produces.

    This is the one place where the campaign's future size is *not* guessed: a shard holds a
    fixed grid of bars, so bytes-per-row is a property of the file format, and 90 days of the
    same format needs 90 times that.

    Several roots are searched because the phase-3 shards were produced by a package that
    lived in its own worktree and were never merged into the checkout. Reporting `no shard`
    because they are one directory over would understate the campaign's need by omission.
    """
    rows: list[dict[str, Any]] = []
    searched: list[str] = []
    for root in roots:
        search = root / "data" / "exp004a"
        searched.append(str(search))
        if not search.is_dir():
            continue
        for path in sorted(search.rglob("*.jsonl")):
            if "rehearsal" in path.parts:
                continue
            lines = _count_lines(path)
            if lines <= 0:
                continue
            rows.append({"path": str(path), "bytes": path.stat().st_size, "lines": lines})
    per_row = [item["bytes"] / item["lines"] for item in rows if item["lines"] > 0]
    return {
        "searched_roots": searched,
        "shards_found": len(rows),
        "shards": rows[:20],
        "bytes_per_row": round(statistics.median(per_row), 2) if per_row else None,
        "basis": "median of bytes-per-line over every non-rehearsal phase-3 shard found",
    }


def _count_lines(path: Path, *, limit: int = 200_000) -> int:
    count = 0
    try:
        with path.open("rb") as handle:
            for line in handle:
                count += 1
                if count >= limit:
                    break
    except OSError:
        return 0
    return count


def project(
    *,
    own_bytes_per_day: int | None,
    bytes_per_row: float | None,
    max_daily_drawdown_bytes: int | None,
    current_free: int,
    breaches: dict[str, Any],
    days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    """What the window needs, and whether the volume can supply it.

    Three terms, kept apart on purpose:

    * ``own``      — the campaign's increment for the whole window (measured, tiny);
    * ``floor``    — the critical floor the guard enforces, which must stay reachable;
    * ``drawdown`` — the largest fall in free space observed inside one UTC day, which is
      the amount of headroom the volume must have in hand *before* the fall starts.

    The verdict is about all three. A 100 MB dataset on a volume that loses 8 GiB between
    breakfast and lunch is not a small data problem, and no amount of frugality in the
    campaign changes it: the campaign already writes a rounding error.

    The measured record outranks the arithmetic. When the volume has already fallen through
    the floor, saying the requirement is met *this minute* would be a forecast contradicted
    by ten days of evidence.
    """
    rows_per_day = ROWS_PER_ASSET_PER_DAY * ASSETS
    deltas_rows = None
    if bytes_per_row is not None:
        deltas_rows = int(bytes_per_row * rows_per_day * days)
    deltas_measured = own_bytes_per_day * days if own_bytes_per_day is not None else None
    own_candidates = [value for value in (deltas_rows, deltas_measured) if value is not None]
    own_total = max(own_candidates) if own_candidates else None
    required = None
    if own_total is not None and max_daily_drawdown_bytes is not None:
        required = own_total + CRITICAL_FREE_BYTES + max(0, max_daily_drawdown_bytes)
    verdict = "UNKNOWN"
    reasons: list[str] = []
    if required is not None:
        if current_free < required:
            verdict = "INSUFFICIENT"
            reasons.append(
                f"free space {round(current_free / GIB, 3)} GiB is under the "
                f"{round(required / GIB, 3)} GiB the floor plus one day's observed drawdown needs"
            )
        elif breaches.get("refused_ticks"):
            verdict = "INSUFFICIENT"
            reasons.append(
                f"the volume has already refused {breaches['refused_ticks']} tick(s): the "
                "floor is not being held, whatever this minute's reading says"
            )
        else:
            verdict = "SUFFICIENT"
    eta_hours = None
    if max_daily_drawdown_bytes and max_daily_drawdown_bytes > 0:
        eta_hours = round(
            (current_free - CRITICAL_FREE_BYTES) / (max_daily_drawdown_bytes / 24), 2
        )
        if eta_hours < 0:
            eta_hours = 0.0
    return {
        "window_days": days,
        "rows_per_day": rows_per_day,
        "own": {
            "from_shard_format_bytes": deltas_rows,
            "from_measured_tree_bytes": deltas_measured,
            "adopted_bytes": own_total,
            "adopted_basis": (
                "the larger of the two estimates: a projection that under-states its own "
                "need is the one a full disk punishes"
                if own_total is not None
                else "no measurable basis"
            ),
        },
        "floor_bytes": CRITICAL_FREE_BYTES,
        "max_daily_drawdown_bytes": max_daily_drawdown_bytes,
        "required_free_bytes": required,
        "required_free_gib": round(required / GIB, 3) if required is not None else None,
        "current_free_bytes": current_free,
        "current_free_gib": round(current_free / GIB, 3),
        "headroom_bytes": None if required is None else current_free - required,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "hours_to_floor_at_worst_observed_rate": eta_hours,
        "hypotheses": [
            f"the window is {days} consecutive UTC days",
            f"every day holds {rows_per_day} rows ({ASSETS} assets x {ROWS_PER_ASSET_PER_DAY} hours)",
            "the host's own drawdown repeats at the largest rate already observed",
            "the critical floor stays at 2 GiB and is never spent",
            "the bytes this package cannot name are not claimed as available",
            "recovery of free space is not planned: it has happened, and it is not a plan",
        ],
    }


# --------------------------------------------------------------------------- #
# reclamation
# --------------------------------------------------------------------------- #
def tracked_by_git(root: Path, target: Path) -> bool:
    listing = git(root, "ls-files", "--", str(target))
    return bool(listing.strip())


def sweep_candidates(root: Path) -> list[dict[str, Any]]:
    """Whitelisted, untracked, regenerable directories inside this package's own worktree.

    A candidate survives every filter or it is not deleted: the name must be on the list, the
    directory must be inside the repository, and Git must not hold a single byte of it. The
    third check is what keeps a ``__pycache__`` from being removed out of a tree that
    actually tracks one.
    """
    found: list[dict[str, Any]] = []
    for pattern, reason in SWEEP_PATTERNS:
        for path in sorted(root.rglob(pattern)):
            if not path.is_dir():
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if any(part == ".git" for part in relative.parts):
                continue
            if tracked_by_git(root, relative):
                found.append(
                    {
                        "path": str(relative).replace("\\", "/"),
                        "reason": reason,
                        "eligible": False,
                        "excluded_because": "Git tracks bytes inside this directory",
                    }
                )
                continue
            measured = measure_tree(path)
            found.append(
                {
                    "path": str(relative).replace("\\", "/"),
                    "reason": reason,
                    "eligible": True,
                    "bytes": measured["bytes"],
                    "files": measured["files"],
                }
            )
    return found


def sweep(root: Path, *, apply: bool) -> dict[str, Any]:
    before = volume(root)
    candidates = sweep_candidates(root)
    eligible = [item for item in candidates if item["eligible"]]
    removed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if apply:
        for item in eligible:
            target = root / item["path"]
            try:
                shutil.rmtree(target)
                removed.append({"path": item["path"], "bytes": item.get("bytes", 0)})
            except OSError as exc:
                failures.append({"path": item["path"], "error": str(exc)})
    after = volume(root)
    return {
        "applied": apply,
        "before": before,
        "after": after,
        "deleted_bytes": sum(int(item.get("bytes") or 0) for item in removed),
        "volume_delta_bytes": after["free_bytes"] - before["free_bytes"] if apply else 0,
        "volume_delta_note": (
            "the volume moves for reasons this sweep does not control: other processes write "
            "and delete while it runs, so the change in free space is not the bytes reclaimed. "
            "deleted_bytes is the quantity the sweep is responsible for."
        ),
        "reclaimable_bytes": sum(int(item.get("bytes") or 0) for item in eligible),
        "reclaimable_files": sum(int(item.get("files") or 0) for item in eligible),
        "candidates": candidates,
        "removed": removed,
        "failures": failures,
        "protected_note": (
            "the sweep never walks outside this worktree, never touches a tracked path, and "
            "never removes evidence, data, configuration or another agent's files"
        ),
    }


# --------------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------------- #
def sample_path(out: Path) -> Path:
    return out / "samples.jsonl"


def append_sample(out: Path, reading: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"ts_ms": now_ms(), "free_bytes": reading["free_bytes"], "status": reading["status"]},
        sort_keys=True,
    )
    with sample_path(out).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def session_growth(out: Path) -> dict[str, Any]:
    path = sample_path(out)
    rows: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row.get("ts_ms"), int) and isinstance(row.get("free_bytes"), int):
                rows.append(row)
    rows.sort(key=lambda item: item["ts_ms"])
    result: dict[str, Any] = {"samples": len(rows), "path": str(path)}
    if len(rows) >= 2:
        span_hours = (rows[-1]["ts_ms"] - rows[0]["ts_ms"]) / 3_600_000
        result["span_hours"] = round(span_hours, 3)
        result["first_free_bytes"] = rows[0]["free_bytes"]
        result["last_free_bytes"] = rows[-1]["free_bytes"]
        result["note"] = (
            "the samples this package took while it worked. A span under an hour sits inside "
            "the volume's own oscillation, so the delta is evidence of the session, not a rate."
        )
        if span_hours >= 1:
            result["bytes_per_hour"] = int(
                (rows[-1]["free_bytes"] - rows[0]["free_bytes"]) / span_hours
            )
    return result


def survey() -> dict[str, Any]:
    """A filesystem survey of the volume, one level deeper where the bytes are.

    This exists so the report can name the consumers it does *not* own. Naming them is the
    point: a campaign of 20 MiB cannot be asked to shrink itself out of a 230 GiB problem,
    and a report that only measured its own tree would recommend exactly that.
    """
    local = Path(os.environ.get("LOCALAPPDATA") or home() / "AppData" / "Local")
    roots = [
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path("C:/ProgramData"),
        Path("C:/ESD"),
        Path("C:/tmp"),
        local,
        Path(os.environ.get("APPDATA") or home() / "AppData" / "Roaming"),
        home() / "Downloads",
        home() / "OneDrive - Generalitat de Catalunya",
    ]
    rows = []
    for root in roots:
        # 800k files covers the two largest trees on this host (~470k and ~380k). A limit that
        # truncates the biggest consumer would rank the tree it cut short as smaller than it
        # is, and the ranking is the point of the survey.
        measured = measure_tree(root, max_files=800_000, max_seconds=300)
        rows.append({**measured, "bytes_gib": round(measured["bytes"] / GIB, 3)})
    children = []
    if local.is_dir():
        for entry in sorted(local.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            measured = measure_tree(entry, max_files=300_000, max_seconds=120)
            if measured["bytes"] >= 256 * MIB:
                children.append(
                    {
                        "path": str(entry),
                        "bytes": measured["bytes"],
                        "bytes_gib": round(measured["bytes"] / GIB, 3),
                        "truncated": measured["truncated"],
                    }
                )
    children.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now_ms()),
        "volume": volume(Path("C:/")),
        "roots": rows,
        "largest_local_appdata_children": children[:15],
        "threshold_note": "directories under 256 MiB are not listed; absence here is not zero",
    }


def render_markdown(report: dict[str, Any]) -> str:
    vol = report["volume"]
    consumers = report["consumers"]
    trend_row = report["host_trend"]
    projection = report["projection"]
    lane = report["lane"]
    sweep_info = report["sweep"]
    breaches = report["breaches"]

    lines: list[str] = []
    lines.append("# EDGE-04 growth and projected capacity")
    lines.append("")
    lines.append(
        f"Measured at `{report['generated_at_utc']}` on `{vol['anchor']}`: "
        f"**{vol['total_gib']} GiB** total, **{vol['free_gib']} GiB** free "
        f"({vol['used_percent']} % used), state `{vol['status']}`."
    )
    lines.append("")
    lines.append("## 1. The record, before the arithmetic")
    lines.append("")
    lines.append(
        f"The observer's own log holds **{report['history']['sample_count']}** free-space "
        f"readings from `{report['history']['first_at_utc']}` to "
        f"`{report['history']['last_at_utc']}`. In that record the volume went under the 2 GiB "
        f"floor **{breaches['free_space_episode_count']}** time(s), spent "
        f"**{breaches['hours_under_floor']} "
        f"hour(s)** there, and reached **{breaches['lowest_free_gib']} GiB** free at its worst."
    )
    lines.append("")
    lines.append(
        f"The guard refused **{breaches['refused_ticks']}** tick(s) "
        f"(`DISK_BUDGET_EXCEEDED`, {breaches['refused_hours']} hour(s) of slots) — "
        f"every one of them a slot whose bars were never fetched, because the lag policy "
        f"forbids fetching them later."
    )
    lines.append("")
    if breaches["free_space_episodes"]:
        lines.append("| Under the floor | Hours | Lowest free |")
        lines.append("| --- | --- | --- |")
        for item in breaches["free_space_episodes"]:
            lines.append(
                f"| `{item['start_at_utc']}` → `{item['end_at_utc']}` | {item['hours']} | "
                f"{item['min_free_gib']} GiB |"
            )
        lines.append("")
    lines.append("## 2. Where the bytes are")
    lines.append("")
    lines.append("| Consumer | Owner | Class | Size |")
    lines.append("| --- | --- | --- | --- |")
    for row in consumers:
        measured = row["measured"]
        size = "absent" if not measured["exists"] else f"{measured['bytes_mib']} MiB"
        if measured.get("truncated"):
            size += f" (truncated: {measured['truncated']})"
        lines.append(
            f"| `{row['path']}` | {row['owner']} | {row['class']} | {size} |"
        )
    lines.append("")
    lines.append("## 3. The two series, kept apart")
    lines.append("")
    lines.append(
        f"- The campaign's own tree: **{lane['state_bytes_mib']} MiB**."
    )
    if report["shards"]["bytes_per_row"] is not None:
        lines.append(
            f"- Shard format: **{report['shards']['bytes_per_row']} bytes per row** over "
            f"{report['shards']['shards_found']} shard(s) found in "
            f"{len(report['shards']['searched_roots'])} searched root(s)."
        )
    else:
        lines.append(
            "- Shard format: `UNKNOWN` — no phase-3 shard was found in any searched root, so "
            "the format term is unavailable rather than zero."
        )
    lines.append(
        f"- The campaign's own measured growth: "
        f"**{report['lane_growth'].get('resource_budget_bytes_per_day')} bytes/day** over "
        f"{report['lane_growth'].get('resource_budget_span_days')} day(s) of its own samples."
    )
    lines.append(
        f"- The host's oscillation: largest fall from a peak inside one UTC day "
        f"**{round((projection['max_daily_drawdown_bytes'] or 0) / GIB, 3)} GiB**"
        f"{(report.get('drawdown') or {}).get('day') and ' on ' + str((report.get('drawdown') or {}).get('day'))}; "
        f"median daily net change "
        f"**{trend_row.get('median_gib_per_day')} GiB** over {trend_row.get('days')} day(s) "
        f"(`{trend_row.get('status')}`), with "
        f"{trend_row.get('days_spending')} day(s) spending and "
        f"{trend_row.get('days_recovering')} day(s) recovering."
    )
    lines.append("")
    lines.append(
        "The two are not the same series and must not be added into one number: the campaign "
        "writes roughly a megabyte a day, and the volume loses gigabytes a day to processes "
        "this package cannot name."
    )
    lines.append("")
    lines.append("## 4. The projection")
    lines.append("")
    lines.append(
        f"- Own need for {projection['window_days']} days: "
        f"**{projection['own']['adopted_bytes']} bytes** "
        f"(format {projection['own']['from_shard_format_bytes']}, "
        f"measured tree {projection['own']['from_measured_tree_bytes']})."
    )
    lines.append(f"- Floor that must never be spent: **{CRITICAL_FREE_BYTES} bytes**.")
    lines.append(
        "- Headroom the volume must already hold: "
        f"**{projection['max_daily_drawdown_bytes']} bytes**, the largest observed daily fall."
    )
    lines.append(
        f"- Required free space: **{projection['required_free_gib']} GiB**; available now: "
        f"**{projection['current_free_gib']} GiB** → headroom "
        f"**{projection['headroom_bytes']} bytes**."
    )
    lines.append(
        f"- At the worst observed drawdown, the floor is "
        f"**{projection['hours_to_floor_at_worst_observed_rate']} hour(s)** away."
    )
    lines.append("")
    lines.append(f"**Verdict: `{projection['verdict']}`.**")
    for reason in projection["verdict_reasons"]:
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("Hypotheses this verdict rests on:")
    lines.append("")
    for hypothesis in projection["hypotheses"]:
        lines.append(f"- {hypothesis}")
    lines.append("")
    lines.append("## 5. What this package reclaimed")
    lines.append("")
    lines.append(
        f"- Eligible inside its own worktree: **{sweep_info['reclaimable_bytes']} bytes** in "
        f"{sweep_info['reclaimable_files']} file(s)."
    )
    if sweep_info["applied"]:
        lines.append(
            f"- Removed across {sweep_info.get('runs_recorded', 1)} recorded run(s): "
            f"**{sweep_info.get('directories_removed_total', len(sweep_info['removed']))}** "
            f"director(ies), **{sweep_info.get('deleted_bytes_total', sweep_info.get('deleted_bytes'))} "
            "bytes**; the volume itself moved "
            f"{sweep_info.get('volume_delta_bytes')} bytes while the last run lasted, which is "
            "not the same quantity."
        )
    else:
        lines.append("- Not applied: this run only measured.")
    lines.append(
        "- Foreign and shared bytes (temp, other agents' checkouts, browser caches, Downloads) "
        "are listed and left untouched: this package cannot name their owner or their retention."
    )
    lines.append("")
    return "\n".join(lines)


def sweep_section(out: Path) -> dict[str, Any]:
    """What the sweep did, read from its own evidence, or what it would do now.

    A report that re-ran the sweep as a dry run after an applied run would say "not applied"
    about bytes that are gone. The evidence file is the record of the action; it is used when
    it exists, and labelled so a reader knows which one they are looking at.
    """
    existing = read_json(out / "SWEEP_EVIDENCE.json")
    if existing:
        history = list(existing.get("history") or [])
        return {
            **existing,
            "source": "SWEEP_EVIDENCE.json",
            "runs_recorded": len(history),
            "deleted_bytes_total": sum(int(item.get("deleted_bytes") or 0) for item in history),
            "directories_removed_total": sum(len(item.get("removed") or []) for item in history),
            "deleted_bytes_note": (
                "the top-level fields describe the most recent run; the totals here are the "
                "whole recorded history, because a later run that finds nothing does not undo "
                "an earlier one"
            ),
        }
    return {**sweep(REPO_ROOT, apply=False), "source": "measured in this run"}


def audit(main_root: Path, state_root: Path, out: Path, *, include_sweep: bool) -> dict[str, Any]:
    vol = volume(state_root)
    consumers = consumer_table(main_root)
    history = lane_history(state_root)
    daily = daily_series(history.get("samples") or [])
    host_trend = trend(daily)
    breaches = breach_episodes(history.get("samples") or [])
    lane_state = measure_tree(state_root)
    shard_roots = [
        main_root,
        REPO_ROOT,
        REPO_ROOT.parent / "bot-freebuff-exp004a-02g",
    ]
    shards = shard_sizes(shard_roots)
    growth = lane_growth(state_root)
    own_rate = growth.get("resource_budget_bytes_per_day")
    drawdown = max_drawdown(history.get("samples") or [])
    max_drawdown_bytes = drawdown["bytes"] or None
    projection = project(
        own_bytes_per_day=own_rate if isinstance(own_rate, int) else None,
        bytes_per_row=shards.get("bytes_per_row"),
        max_daily_drawdown_bytes=max_drawdown_bytes,
        current_free=vol["free_bytes"],
        breaches=breaches,
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now_ms()),
        "head": git(REPO_ROOT, "rev-parse", "HEAD"),
        "worktree": str(REPO_ROOT),
        "main_checkout": str(main_root),
        "state_root": str(state_root),
        "volume": vol,
        "consumers": consumers,
        "history": {
            key: value for key, value in history.items() if key != "samples"
        },
        "daily": daily,
        "host_trend": host_trend,
        "breaches": breaches,
        "drawdown": drawdown,
        "lane": {**lane_state, "state_bytes_mib": lane_state["bytes_mib"]},
        "lane_growth": growth,
        "shards": shards,
        "projection": projection,
        "sweep": sweep_section(out) if include_sweep else {"applied": False, "removed": []},
        "session": session_growth(out),
        "note": (
            "every byte figure here is either measured on this host or derived from a stated "
            "hypothesis. Nothing in this report moves the experiment's coverage, grades a day, "
            "or repairs a capture."
        ),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--main-root", type=Path, default=Path(DEFAULT_STATE).parents[2])
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--audit", action="store_true", help="measure and write the report")
    parser.add_argument("--survey", action="store_true", help="measure the volume's consumers")
    parser.add_argument("--sweep", action="store_true", help="list reclaimable caches")
    parser.add_argument("--apply", action="store_true", help="delete them (needs --sweep)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    main_root = args.main_root.resolve()
    state_root = (args.state_root or main_root / "data" / "forward" / "edge04").resolve()
    out = args.out.resolve()

    if args.survey:
        payload = survey()
        write_json(out / "FILESYSTEM_SURVEY.json", payload)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for row in payload["roots"]:
                print(f"{row['path']:55} {row.get('bytes_gib', 0):8.2f} GiB {row.get('truncated') or ''}")
            for row in payload["largest_local_appdata_children"][:10]:
                print(f"  {row['path']:53} {row['bytes_gib']:8.2f} GiB")
        return 0

    if args.sweep:
        result = sweep(REPO_ROOT, apply=args.apply)
        evidence_path = out / "SWEEP_EVIDENCE.json"
        previous = read_json(evidence_path) or {}
        history = list(previous.get("history") or [])
        history.append(
            {
                "at_utc": iso(now_ms()),
                "applied": result["applied"],
                "deleted_bytes": result.get("deleted_bytes", 0),
                "removed": result["removed"],
                "candidates": len(result["candidates"]),
            }
        )
        # The evidence accumulates: a second run that finds nothing must not erase the record
        # of the first run that removed 13 MiB.
        write_json(
            evidence_path,
            {**result, "generated_at_utc": iso(now_ms()), "history": history},
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"sweep  applied={result['applied']}")
            for item in result["candidates"]:
                state = "remove" if item["eligible"] else "keep"
                print(
                    f"  {state:6} {item['path']:40} "
                    f"{item.get('bytes', 0) / MIB:8.2f} MiB  {item['reason']}"
                )
            print(
                f"  eligible {result['reclaimable_bytes'] / MIB:.2f} MiB in "
                f"{result['reclaimable_files']} file(s); deleted "
                f"{result['deleted_bytes'] / MIB:.2f} MiB; volume moved "
                f"{result['volume_delta_bytes'] / MIB:.2f} MiB"
            )
            for failure in result["failures"]:
                print(f"  FAILED {failure['path']}: {failure['error']}")
        return 0 if not result["failures"] else 1

    report = audit(main_root, state_root, out, include_sweep=True)
    append_sample(out, report["volume"])
    write_json(out / "STORAGE_CAPACITY_REPORT.json", report)
    (out / "GROWTH_DIAGNOSIS.md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        vol = report["volume"]
        print(f"volume   {vol['free_gib']} GiB free of {vol['total_gib']} GiB ({vol['status']})")
        print(f"trend    {report['host_trend'].get('median_gib_per_day')} GiB/day "
              f"({report['host_trend'].get('status')})")
        print(f"verdict  {report['projection']['verdict']}")
        print(f"report   {out / 'STORAGE_CAPACITY_REPORT.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
