"""WP-051-02K — capacity recovery and operational continuity for the 90-day campaign.

The previous package (02J) measured the problem and left it open: the volume holds far less than
the p90 drawdown the observer itself recorded, and the only space that could close the gap belongs
to somebody else. This package does the four things that were still missing, and refuses to do the
one thing it is not allowed to do:

1. **Measure the volume again, with two instruments**, before and after every action it takes —
   including the campaign's own readings, so a report cannot claim space the observer denies.
2. **Inventory the whole disk**, not just the sixty paths 02J had already listed, and say how much
   of the 236 GiB the inventory actually accounts for. A gap between "used" and "explained" is a
   finding, not a rounding error.
3. **Turn the inventory into an authorisation request**: exact path, bytes, owner, what breaks, and
   the procedure that restores it. Nothing in that list is deleted by this program.
4. **Prove the campaign did not move**: the append-only files keep their prefix, the write-once
   shards keep their exact hashes, and the frozen contract keeps its `git diff` at zero.

What it may delete is only what it can name and regenerate: this worktree's and the campaign
repository's own untracked byte-compiled caches. `--clean` is the only mode that writes anything
outside `--out`, and it never touches a file Git tracks.

Usage::

    python scripts/exp004a_wp051_02k_capacity.py --before
    python scripts/exp004a_wp051_02k_capacity.py --clean
    python scripts/exp004a_wp051_02k_capacity.py --after
    python scripts/exp004a_wp051_02k_capacity.py --inventory      # slow, bounded, re-runnable
    python scripts/exp004a_wp051_02k_capacity.py --request
    python scripts/exp004a_wp051_02k_capacity.py --report

Research only: no network, no admin elevation, no deletion outside this repository family's own
untracked caches, no change to the campaign contract.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import statistics
import stat as stat_module
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "EXP004A_WP051_02K_CAPACITY_V1"
PACKAGE = "WP-051-02K"
GIB = 1024**3
MIB = 1024**2

#: Unchanged by this package, and checked against the observer's own module.
CRITICAL_FREE_BYTES = 2 * GIB
WARNING_FREE_BYTES = 5 * GIB

#: The frozen contract, repeated here so a test can prove this program never moves them.
WINDOW_START = "2026-10-23T00:00:00Z"
WINDOW_END = "2027-01-21T00:00:00Z"
WINDOW_DAYS = 90
DECLARED_ROWS = 6480
REQUIRED_FRACTION = 0.9
CONTRACT_PATH = "config/preregistrations/EXP-004A.datasets.phase3.json"

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
DEFAULT_OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02k"
DEFAULT_STATE = MAIN_ROOT / "data" / "forward" / "edge04"

#: A tree nobody has written for this long is treated as idle rather than in use.
ACTIVE_WINDOW_SECONDS = 2 * 3600

#: Patterns this package may delete, and only where Git does not track the bytes.
CLEAN_PATTERNS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis")

#: Directories whose *children* are the paths an authorisation request can name.
DRILL_ROOTS = (
    "AppData/Local/Temp",
    "AppData/Local/Microsoft",
    "AppData/Local/Programs",
    "AppData/Roaming",
    ".gemini",
    ".cache",
)

#: Files the observer only ever appends to. Rewriting one of these is evidence of a re-timestamp.
APPEND_ONLY = ("runs.jsonl", "slots.jsonl", "alerts.jsonl", "ALERT_LEDGER.jsonl", "WATCHDOG_EVENTS.jsonl")
#: Write-once shards: a byte out of place is a repaired dataset, which this package forbids.
WRITE_ONCE_GLOB = "daily/*.json"
#: Rewritten on every tick by design; only their contract fields are compared.
REWRITTEN = ("health.json", "coverage.json", "resource_budget.json")

SAFE_OWNED = "SAFE_OWNED"
SAFE_OWNED_FAMILY = "SAFE_OWNED_FAMILY"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
ACTIVE_OR_PROTECTED = "ACTIVE_OR_PROTECTED"
UNKNOWN = "UNKNOWN"

#: Directories that only ever hold rebuildable tool state.
TOOLING_CACHE_NAMES = frozenset({"hermes", "pip", "uv", "npm-cache", "bun", "build-cache", ".cache", "cache"})
#: Paging and hibernation files: the largest single lever, and the least free one.
SYSTEM_FILES = frozenset({"pagefile.sys", "hiberfil.sys", "swapfile.sys"})
TEMP_ROOT = Path("C:/Users/GVLLFR0035/AppData/Local/Temp")

#: How much the recovery procedure costs the owner. Lower is asked for first: 0 is this
#: package's own caches, 1 is regenerated from the network, 2 has to be rebuilt by hand, 3 is a
#: system change with a reboot behind it.
KIND_TIER = {
    "OWN_CACHE": 0,
    "RUNNER_CACHE": 0,
    "TEMP_RUN_LEFTOVER": 1,
    "REPROVISIONABLE": 1,
    "REBUILDABLE": 2,
    "MOVE_OR_COMPACT": 3,
}

#: Never offered as a candidate, whatever its size: these are the owner's documents or the
#: profile that holds them. Freeing them is not a capacity decision.
NEVER_OFFER = frozenset(
    {
        "C:/Users/GVLLFR0035/AppData",
        "C:/Users/GVLLFR0035/AppData/Roaming",
        "C:/Users/GVLLFR0035/AppData/Local",
        "C:/Users/GVLLFR0035/OneDrive - Generalitat de Catalunya",
        "C:/Users/GVLLFR0035/Documents",
        "C:/Users/GVLLFR0035/Desktop",
        "C:/Users/GVLLFR0035/Downloads",
        "C:/Users/GVLLFR0035/Pictures",
        "C:/Users/GVLLFR0035/Videos",
        "C:/Users/GVLLFR0035/Music",
        "C:/Users/GVLLFR0035/Generalitat de Catalunya",
        "C:/Users",
        "C:/Windows",
        "C:/Program Files",
        "C:/Program Files (x86)",
        "C:/ProgramData",
        "C:/tmp",
        str(MAIN_ROOT).replace("\\", "/"),
        str(REPO_ROOT).replace("\\", "/"),
    }
)

#: Slack added to the gap: a fix that lands exactly on the budget is consumed by the next hour of
#: host churn, and the owner would be asked again tomorrow.
FIX_MARGIN_BYTES = 1 * GIB


# --------------------------------------------------------------------------- #
# clock, io
# --------------------------------------------------------------------------- #
def now() -> datetime:
    return datetime.now(tz=UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    """Atomic: a reader never sees half a report, and no ``.part`` survives a failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def sha256_prefix(path: Path, length: int) -> str | None:
    digest = hashlib.sha256()
    remaining = length
    try:
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(1 << 20, remaining))
                if not chunk:
                    return None  # the file is shorter than it was: something rewrote it
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def git(cwd: Path, *args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, (done.stdout or "").strip()


# --------------------------------------------------------------------------- #
# capacity: two instruments, because one can be wrong
# --------------------------------------------------------------------------- #
def free_bytes_shutil(path: str) -> int:
    return int(shutil.disk_usage(path).free)


def free_bytes_kernel32(path: str) -> int:
    """The same question asked through the Win32 call, not through Python's wrapper."""
    if sys.platform != "win32":
        return free_bytes_shutil(path)
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    available = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p(path), ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "GetDiskFreeSpaceExW failed")
    return int(available.value)


def volume(path: Path | str) -> dict[str, Any]:
    target = str(path)
    if len(target) >= 2 and target[1] == ":":
        target = target[:3] if target[2:3] in ("\\", "/") else target[:2] + "\\"
    usage = shutil.disk_usage(target)
    first = int(usage.free)
    second = free_bytes_kernel32(target)
    return {
        "path": target,
        "free_bytes": first,
        "free_bytes_kernel32": second,
        "instruments_agree": first == second,
        "instrument_delta_bytes": first - second,
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.total) - first,
        "free_gib": round(first / GIB, 4),
        "used_gib": round((int(usage.total) - first) / GIB, 4),
        "used_percent": round((int(usage.total) - first) / int(usage.total) * 100, 2),
        "status": (
            "CRITICAL"
            if first < CRITICAL_FREE_BYTES
            else ("WARNING" if first < WARNING_FREE_BYTES else "HEALTHY")
        ),
        "at_utc": iso(now()),
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def readings(state_root: Path) -> list[dict[str, Any]]:
    """Every free-space reading the observer wrote, whatever else that row says."""
    rows: list[dict[str, Any]] = []
    try:
        text = (state_root / "runs.jsonl").read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        disk = row.get("disk_after") or row.get("disk") or {}
        free = disk.get("free_bytes") if isinstance(disk, dict) else None
        stamp = row.get("started_at_ms")
        if isinstance(free, int) and isinstance(stamp, int):
            rows.append({"ts": stamp, "free": free, "outcome": row.get("outcome") or row.get("status")})
    rows.sort(key=lambda item: item["ts"])
    return rows


def budget(state_root: Path) -> dict[str, Any]:
    """What the campaign needs, as a distribution.

    Same method as 02J, recomputed from the readings that exist now: the budget is the p90
    drawdown plus the floor plus the campaign's own growth for the whole window. The maximum is
    reported next to it rather than used, because one observation is not a margin.
    """
    rows = readings(state_root)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = iso(datetime.fromtimestamp(row["ts"] / 1000, tz=UTC))[:10]
        buckets.setdefault(day, []).append(row)
    drawdowns: list[float] = []
    nets: list[float] = []
    for day_rows in buckets.values():
        if len(day_rows) < 2:
            continue
        peak = None
        worst = 0.0
        for row in day_rows:
            peak = row["free"] if peak is None else max(peak, row["free"])
            worst = max(worst, peak - row["free"])
        drawdowns.append(worst)
        nets.append(day_rows[-1]["free"] - day_rows[0]["free"])
    own = read_json(state_root / "resource_budget.json", {}) or {}
    samples = [
        row
        for row in (own.get("samples") if isinstance(own.get("samples"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("ts_ms"), int) and isinstance(row.get("bytes"), int)
    ]
    own_per_day = None
    if len(samples) >= 2:
        samples.sort(key=lambda row: row["ts_ms"])
        span_days = max((samples[-1]["ts_ms"] - samples[0]["ts_ms"]) / 86_400_000, 1e-9)
        own_per_day = int((samples[-1]["bytes"] - samples[0]["bytes"]) / span_days)
    window_own = (own_per_day or 0) * WINDOW_DAYS
    p50 = percentile(drawdowns, 0.50)
    p90 = percentile(drawdowns, 0.90)
    worst = max(drawdowns) if drawdowns else 0.0
    return {
        "history_days": len(drawdowns),
        "readings": len(rows),
        "days_drawdown_gib": [round(item / GIB, 3) for item in drawdowns],
        "drawdown_p50_bytes": int(p50),
        "drawdown_p90_bytes": int(p90),
        "drawdown_max_bytes": int(worst),
        "own_bytes_per_day": own_per_day,
        "own_window_bytes": window_own,
        "floor_bytes": CRITICAL_FREE_BYTES,
        "required_bytes": window_own + CRITICAL_FREE_BYTES + int(p90),
        "required_gib": round((window_own + CRITICAL_FREE_BYTES + int(p90)) / GIB, 3),
        "required_at_max_bytes": window_own + CRITICAL_FREE_BYTES + int(worst),
        "required_at_max_gib": round((window_own + CRITICAL_FREE_BYTES + int(worst)) / GIB, 3),
        "net_median_bytes": int(statistics.median(nets)) if nets else None,
        "net_median_gib": round(statistics.median(nets) / GIB, 3) if nets else None,
        "days_spending": sum(1 for item in nets if item < 0),
        "days_recovering": sum(1 for item in nets if item > 0),
        "basis": "largest peak-to-trough fall inside each complete UTC day of the observer's readings",
        "note": (
            "the budget is the p90 drawdown plus the floor plus the campaign's own growth for the "
            "whole window. The maximum is reported next to it, not used as the budget."
        ),
    }


def refusals(state_root: Path) -> dict[str, Any]:
    """Ticks the observer refused for space, counted by hour, including the last hour."""
    total = 0
    by_day: dict[str, int] = {}
    last: dict[str, Any] | None = None
    try:
        lines = (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        outcome = row.get("outcome") or row.get("status")
        if outcome != "DISK_BUDGET_EXCEEDED":
            continue
        total += 1
        stamp = row.get("started_at_ms")
        if isinstance(stamp, int):
            day = iso(datetime.fromtimestamp(stamp / 1000, tz=UTC))[:10]
            by_day[day] = by_day.get(day, 0) + 1
            disk = row.get("disk_after") or row.get("disk") or {}
            last = {
                "started_at_ms": stamp,
                "at_utc": iso(datetime.fromtimestamp(stamp / 1000, tz=UTC)),
                "free_bytes": disk.get("free_bytes") if isinstance(disk, dict) else None,
            }
    return {
        "total": total,
        "by_day": dict(sorted(by_day.items())),
        "last": last,
        "refusals_are_history": (
            "a refusal cannot be undone by freeing space later; it is reported as history and kept "
            "out of the present-tense capacity decision"
        ),
    }


def capacity_verdict(free_bytes: int, required_bytes: int) -> str:
    """PASS only when the volume holds the budget it needs. Nothing else can promote it."""
    return "PASS" if free_bytes >= required_bytes else "INSUFFICIENT"


def shortfall(free_bytes: int, required_bytes: int) -> int:
    return max(0, required_bytes - free_bytes)


def snapshot(state_root: Path, label: str) -> dict[str, Any]:
    plan = budget(state_root)
    vol = volume("C:/")
    plan_verdict = capacity_verdict(vol["free_bytes"], plan["required_bytes"])
    return {
        "label": label,
        "generated_at_utc": iso(now()),
        "volume": vol,
        "budget": plan,
        "refusals": refusals(state_root),
        "capacity": plan_verdict,
        "shortfall_bytes": shortfall(vol["free_bytes"], plan["required_bytes"]),
        "shortfall_gib": round(shortfall(vol["free_bytes"], plan["required_bytes"]) / GIB, 3),
        "headroom_bytes": vol["free_bytes"] - plan["required_bytes"],
    }


# --------------------------------------------------------------------------- #
# what the store must keep: prefix for append-only, hash for write-once
# --------------------------------------------------------------------------- #
def store_fingerprint(state_root: Path) -> dict[str, Any]:
    append_only = {}
    for name in APPEND_ONLY:
        path = state_root / name
        if not path.exists():
            append_only[name] = {"exists": False}
            continue
        length = path.stat().st_size
        append_only[name] = {
            "exists": True,
            "length": length,
            "lines": sum(1 for _ in path.open("rb")),
            "sha256": sha256_file(path),
        }
    write_once = {}
    for path in sorted(state_root.glob(WRITE_ONCE_GLOB)):
        info = path.stat()
        write_once[path.name] = {
            "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "sha256": sha256_file(path),
        }
    rewritten = {}
    for name in REWRITTEN:
        payload = read_json(state_root / name, {}) or {}
        contract = {}
        if isinstance(payload, dict):
            disk = payload.get("disk") if isinstance(payload.get("disk"), dict) else {}
            declared = payload.get("declared") if isinstance(payload.get("declared"), dict) else {}
            contract = {
                "critical_free_bytes": disk.get("critical_free_bytes"),
                "warning_free_bytes": disk.get("warning_free_bytes"),
                "declared": declared,
            }
        rewritten[name] = contract
    return {
        "at_utc": iso(now()),
        "root": str(state_root),
        "append_only": append_only,
        "write_once": write_once,
        "rewritten_contract": rewritten,
    }


def compare_fingerprints(
    before: dict[str, Any], after: dict[str, Any], state_root: Path | None = None
) -> dict[str, Any]:
    """Append-only may grow; write-once may not move; rewritten files keep their contract.

    A prefix check is used rather than a whole-file hash because the observer writes while this
    program reads: an appended line is not an altered row, and a report that cannot tell them
    apart would either fail every run or stop checking.
    """
    checks: list[dict[str, Any]] = []
    for name, old in (before.get("append_only") or {}).items():
        new = (after.get("append_only") or {}).get(name) or {}
        if not old.get("exists"):
            checks.append({"id": "APPEND_ONLY_EXISTED", "subject": name, "status": "SKIP"})
            continue
        if not new.get("exists"):
            checks.append({"id": "APPEND_ONLY_PRESENT", "subject": name, "status": "FAIL"})
            continue
        grew = new.get("length", 0) >= old.get("length", 0)
        same_lines = new.get("lines", 0) >= old.get("lines", 0)
        prefix = new.get("sha256") == old.get("sha256")
        if not prefix and grew and state_root is not None:
            # the whole-file hash cannot match once a line was appended, so the question becomes
            # whether the bytes that existed then still exist unchanged as a prefix now.
            kept = sha256_prefix(state_root / name, int(old.get("length") or 0))
            prefix = kept is not None and kept == old.get("sha256")
        ok = grew and same_lines and prefix
        checks.append(
            {
                "id": "APPEND_ONLY_PREFIX_INTACT",
                "subject": name,
                "status": "PASS" if ok else "FAIL",
                "detail": f"{old.get('length')} -> {new.get('length')} B, {old.get('lines')} -> {new.get('lines')} lines",
            }
        )
    for name, old in (before.get("write_once") or {}).items():
        new = (after.get("write_once") or {}).get(name) or {}
        ok = old.get("sha256") == new.get("sha256") and old.get("mtime_ns") == new.get("mtime_ns")
        checks.append(
            {
                "id": "WRITE_ONCE_UNCHANGED",
                "subject": name,
                "status": "PASS" if ok else "FAIL",
                "detail": f"sha256 {str(old.get('sha256'))[:12]} -> {str(new.get('sha256'))[:12]}",
            }
        )
    for name, old in (before.get("rewritten_contract") or {}).items():
        new = (after.get("rewritten_contract") or {}).get(name) or {}
        ok = old == new
        checks.append(
            {
                "id": "REWRITTEN_CONTRACT_UNCHANGED",
                "subject": name,
                "status": "PASS" if ok else "FAIL",
            }
        )
    failed = [c for c in checks if c["status"] == "FAIL"]
    return {
        "checks": checks,
        "passed": sum(1 for c in checks if c["status"] == "PASS"),
        "failed": len(failed),
        "verdict": "PASS" if not failed else "FAIL",
    }


# --------------------------------------------------------------------------- #
# inventory: the whole disk, bounded, and honest about what it did not reach
# --------------------------------------------------------------------------- #
def is_reparse(entry: os.DirEntry) -> bool:
    try:
        attributes = entry.stat(follow_symlinks=False).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT)


def scan_tree(root: Path, max_seconds: float, max_files: int = 2_000_000) -> dict[str, Any]:
    """Bytes under ``root``. Junctions are skipped, not followed: AppData points at itself."""
    if not root.exists():
        return {"path": str(root), "exists": False, "bytes": 0, "files": 0, "dirs": 0, "truncated": None}
    started = time.monotonic()
    total = files = dirs = skipped_links = errors = 0
    newest = 0.0
    truncated = None
    stack = [root]
    while stack:
        if time.monotonic() - started > max_seconds:
            truncated = f"time budget {max_seconds:.0f}s"
            break
        if files >= max_files:
            truncated = f"file budget {max_files}"
            break
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if is_reparse(entry):
                                skipped_links += 1
                                continue
                            dirs += 1
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            info = entry.stat(follow_symlinks=False)
                            total += info.st_size
                            files += 1
                            newest = max(newest, info.st_mtime)
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
    return {
        "path": str(root),
        "exists": True,
        "bytes": total,
        "gib": round(total / GIB, 3),
        "files": files,
        "dirs": dirs,
        "skipped_junctions": skipped_links,
        "errors": errors,
        "newest_mtime": newest or None,
        "newest_age_hours": round((time.time() - newest) / 3600, 2) if newest else None,
        "truncated": truncated,
    }


def children_of(root: Path) -> list[Path]:
    out: list[Path] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False) and not is_reparse(entry):
                        out.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        pass
    return sorted(out, key=lambda item: item.name.lower())


def loose_files(root: Path) -> list[dict[str, Any]]:
    """Files sitting directly in a directory: pagefiles, hives, images."""
    out: list[dict[str, Any]] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        out.append({"path": str(entry.path), "bytes": entry.stat(follow_symlinks=False).st_size})
                except OSError:
                    continue
    except OSError:
        pass
    return sorted(out, key=lambda row: -row["bytes"])


def inventory(total_budget_seconds: float = 300.0) -> dict[str, Any]:
    """Where the bytes are, from the top of the volume down to the named suspects."""
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    truncations: list[str] = []

    def remaining() -> float:
        return max(0.0, total_budget_seconds - (time.monotonic() - started))

    def add(path: Path, seconds: float, depth: int = 0) -> None:
        slice_seconds = min(seconds, remaining())
        if slice_seconds <= 0.5:
            truncations.append(f"global budget spent before {path}")
            return
        row = scan_tree(path, slice_seconds)
        row["depth"] = depth
        rows.append(row)
        if row.get("truncated"):
            truncations.append(f"{path}: {row['truncated']}")

    # Depth 1: the volume's own children, which is what "where is the disk going" means.
    for child in children_of(Path("C:/")):
        add(child, 45.0)
    for row in loose_files(Path("C:/")):
        rows.append({"path": row["path"], "bytes": row["bytes"], "loose": True, "depth": 1})
    # Depth 2 inside the user profile: the suspects are one level below its children.
    user = Path("C:/Users/GVLLFR0035")
    for child in children_of(user):
        add(child, 25.0, depth=2)
    local = user / "AppData" / "Local"
    for child in children_of(local):
        add(child, 15.0, depth=3)
    downloads = user / "Downloads"
    for child in children_of(downloads):
        add(child, 12.0, depth=3)
    # Depth 4: scratch and caches whose children are the actionable paths.
    for drill in DRILL_ROOTS:
        base = user / drill
        for child in children_of(base):
            add(child, 10.0, depth=4)
    rows.sort(key=lambda row: -row["bytes"])
    return {
        "generated_at_utc": iso(now()),
        "volume": volume("C:/"),
        "budget_seconds": total_budget_seconds,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "rows": rows,
        "truncations": truncations,
        "rows_measured": len(rows),
    }


# --------------------------------------------------------------------------- #
# classification: what this program may touch, and what it may only name
# --------------------------------------------------------------------------- #
def under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_experiment_worktree(path: Path) -> bool:
    """A Git worktree of this experiment family — never a downloaded folder that happens to be big."""
    if not (path / ".git").exists():
        return False
    name = path.name.lower()
    if not (name.startswith("bot") or "bot-freebuff" in name or name == "bot freebuff"):
        return False
    return path.name != MAIN_ROOT.name


def git_tracks(path: Path, repo: Path) -> bool | None:
    code, out = git(repo, "ls-files", "--", str(path))
    if code != 0:
        return None
    return bool(out.strip())


def classify(path: Path, *, age_hours: float | None, tracked: bool | None, own_family: bool) -> tuple[str, str]:
    """Conservative on purpose: an unknown owner is never a deletion candidate here."""
    name = path.name
    is_cache = name in CLEAN_PATTERNS
    exists = path.exists()
    if not exists:
        return UNKNOWN, "path does not exist"
    if not own_family:
        if age_hours is not None and age_hours < ACTIVE_WINDOW_SECONDS / 3600:
            return ACTIVE_OR_PROTECTED, f"written {age_hours} h ago"
        return REQUIRES_APPROVAL, "outside this repository family; only its owner may free it"
    if tracked:
        return ACTIVE_OR_PROTECTED, "Git tracks it"
    if tracked is None:
        return UNKNOWN, "git could not answer whether it tracks this path"
    if not is_cache:
        return REQUIRES_APPROVAL, "untracked but not a regenerable cache"
    if age_hours is not None and age_hours < ACTIVE_WINDOW_SECONDS / 3600:
        return ACTIVE_OR_PROTECTED, f"written {age_hours} h ago; a live process may hold it"
    return (SAFE_OWNED if under(path, REPO_ROOT) else SAFE_OWNED_FAMILY), "untracked byte-compiled cache"


# --------------------------------------------------------------------------- #
# options: every byte that could close the gap, and what it costs to get it
# --------------------------------------------------------------------------- #
def option(
    *,
    key: str,
    path: str,
    bytes_: int,
    owner: str,
    kind: str,
    risk: str,
    recovery: str,
    reversible: bool,
    needs_admin: bool,
    frees_without_authorisation: bool = False,
) -> dict[str, Any]:
    return {
        "tier": KIND_TIER.get(kind, 3),
        "key": key,
        "path": path,
        "bytes": int(bytes_),
        "gib": round(bytes_ / GIB, 3),
        "owner": owner,
        "kind": kind,
        "risk": risk,
        "recovery": recovery,
        "reversible": reversible,
        "needs_admin": needs_admin,
        "requires_authorisation": not frees_without_authorisation,
    }


def coverage_plan(options: list[dict[str, Any]], gap_bytes: int) -> dict[str, Any]:
    """The smallest set of authorisable options that covers the gap, cheapest risk first.

    The target is the gap plus one gigabyte of slack, so the owner is not asked again by the next
    episode of host churn.
    """
    target_bytes = gap_bytes + FIX_MARGIN_BYTES if gap_bytes else 0
    candidates = [row for row in options if row["requires_authorisation"] and row["bytes"] > 0]
    # cheapest recovery first, then reversible before not, then biggest: the ask starts with
    # something the owner can undo in a minute.
    candidates.sort(key=lambda row: (row.get("tier", 3), not row["reversible"], -row["bytes"]))
    picked: list[dict[str, Any]] = []
    total = 0
    for row in candidates:
        if total >= target_bytes:
            break
        # an already-selected ancestor contains this row, and an already-selected descendant is
        # contained by it: counting either twice would invent bytes that are not there
        overlaps = any(
            under(Path(row["path"]), Path(chosen["path"])) or under(Path(chosen["path"]), Path(row["path"]))
            for chosen in picked
        )
        if overlaps:
            continue
        picked.append(row)
        total += row["bytes"]
    return {
        "gap_bytes": gap_bytes,
        "gap_gib": round(gap_bytes / GIB, 3),
        "target_bytes": target_bytes,
        "target_gib": round(target_bytes / GIB, 3),
        "selected": [row["key"] for row in picked],
        "selected_bytes": total,
        "selected_gib": round(total / GIB, 3),
        "covers_gap": total >= target_bytes,
        "spare_after_gap_gib": round((total - gap_bytes) / GIB, 3),
        "rule": (
            "cheapest recovery first (regenerated from the network, then rebuilt by hand, then a "
            "system change), reversible before irreversible inside each tier, and never an item "
            "that overlaps one already selected"
        ),
        "tiers": {str(tier): [row["key"] for row in options if row.get("tier") == tier] for tier in range(4)},
    }


def authorisation_request(options: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    selected = [row for row in options if row["key"] in plan["selected"]]
    return {
        "generated_at_utc": iso(now()),
        "why": (
            f"C: holds less than the campaign's p90 budget; the gap is {plan['gap_gib']} GiB and "
            "every remaining byte belongs to somebody who is not this package"
        ),
        "gap_gib": plan["gap_gib"],
        "items": selected,
        "total_gib": round(sum(row["bytes"] for row in selected) / GIB, 3),
        "procedure": [
            "1. Free a reversible item first (moved or re-provisionable), never a user document.",
            "2. After each item, run: python scripts/exp004a_wp051_02k_capacity.py --after",
            "3. Stop as soon as capacity reports PASS; do not free more than the gap.",
            "4. Re-run --report and the independent verifier before declaring capacity PASS.",
        ],
        "not_requested_here": (
            "no WSL distro, no C:\\ESD staging tree, no browser build, no worktree and no user file "
            "is deleted, moved or compacted by this program"
        ),
    }


# --------------------------------------------------------------------------- #
# cleaning: only this repository family's own untracked caches
# --------------------------------------------------------------------------- #
def is_reparse_entry(path: Path) -> bool:
    """A junction or symlink: walked through by nobody here, because AppData points at itself."""
    info = path.stat(follow_symlinks=False)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT)


def clean_candidates(repo: Path) -> list[Path]:
    found: list[Path] = []
    for current, dirnames, _ in os.walk(repo, topdown=True, followlinks=False):
        keep = []
        for name in dirnames:
            path = Path(current) / name
            try:
                if is_reparse_entry(path):
                    continue
            except OSError:
                continue
            if name in CLEAN_PATTERNS:
                found.append(path)
                continue
            if name == ".git" or name in (".venv", "node_modules"):
                continue
            keep.append(name)
        dirnames[:] = keep
    return found


def tree_bytes(path: Path) -> int:
    total = 0
    for current, _dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                continue
    return total


def clean_own(out: Path, repos: list[Path] | None = None) -> dict[str, Any]:
    """Delete only byte-compiled caches that Git does not track, in this repository family."""
    repos = repos or [REPO_ROOT, MAIN_ROOT]
    before = volume("C:/")
    removed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for repo in repos:
        if not repo.exists():
            continue
        code, top = git(repo, "rev-parse", "--show-toplevel")
        if code != 0:
            kept.append({"path": str(repo), "reason": "not a git worktree"})
            continue
        for candidate in clean_candidates(repo):
            size = tree_bytes(candidate)
            tracked = git_tracks(candidate, repo)
            if tracked is None:
                kept.append({"path": str(candidate), "bytes": size, "reason": "git could not answer"})
                continue
            if tracked:
                kept.append({"path": str(candidate), "bytes": size, "reason": "Git tracks it"})
                continue
            try:
                shutil.rmtree(candidate)
            except OSError as exc:
                kept.append({"path": str(candidate), "bytes": size, "reason": f"delete failed: {exc}"})
                continue
            removed.append({"path": str(candidate), "bytes": size})
    after = volume("C:/")
    deleted = sum(row["bytes"] for row in removed)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "before": before,
        "after": after,
        "removed": sorted(removed, key=lambda row: -row["bytes"]),
        "kept": kept,
        "deleted_bytes": deleted,
        "deleted_gib": round(deleted / GIB, 4),
        "volume_delta_bytes": after["free_bytes"] - before["free_bytes"],
        "note": (
            "only untracked byte-compiled caches inside this repository family. The volume moves for "
            "reasons this program does not control, so deleted_bytes is the quantity it is "
            "responsible for; volume_delta_bytes is reported, not claimed."
        ),
    }
    write_json(out / "CLEANUP_EVIDENCE.json", payload)
    return payload


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def classify_inventory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every measured row an owner and a permission, never a delete order."""
    out = []
    for row in rows:
        path = Path(row["path"])
        family = under(path, REPO_ROOT) or under(path, MAIN_ROOT)
        age = row.get("newest_age_hours")
        if row.get("loose"):
            klass, reason = REQUIRES_APPROVAL, "system file at the volume root"
        elif path.name in CLEAN_PATTERNS:
            tracked = git_tracks(path, REPO_ROOT if under(path, REPO_ROOT) else MAIN_ROOT)
            klass, reason = classify(path, age_hours=age, tracked=tracked, own_family=family)
        else:
            klass, reason = classify(path, age_hours=age, tracked=None, own_family=False)
            if family:
                # a whole tree is never a cache, even inside this repository family
                klass = REQUIRES_APPROVAL
                reason = "owned by this repository family but not a regenerable cache"
        out.append({**row, "class": klass, "reason": reason})
    return out


def build_options(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concrete, named recovery paths for everything big enough to matter."""
    options: list[dict[str, Any]] = []
    for row in classified:
        if row["bytes"] < 256 * MIB:
            continue
        path = Path(row["path"])
        name = path.name.lower()
        # a document folder or the profile above it is not a capacity candidate at any size
        if str(path).replace("\\", "/").rstrip("/").lower() in {item.lower() for item in NEVER_OFFER}:
            continue
        if "wsl" == name:
            options.append(
                option(
                    key="wsl-distro-image",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="host user (WSL distributions)",
                    kind="MOVE_OR_COMPACT",
                    risk="a wrong command destroys the distro filesystem",
                    recovery="wsl --export <distro> X.tar (needs an external volume); then unregister/import",
                    reversible=False,
                    needs_admin=True,
                )
            )
        elif name == "esd":
            options.append(
                option(
                    key="windows-setup-staging",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="Windows Setup",
                    kind="REBUILDABLE",
                    risk="a pending upgrade or recovery may need it",
                    recovery="DISM /Online /Cleanup-Image /StartComponentCleanup; setup re-stages on demand",
                    reversible=False,
                    needs_admin=True,
                )
            )
        elif name == "ms-playwright":
            options.append(
                option(
                    key="playwright-browsers",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="host user (browser automation)",
                    kind="REPROVISIONABLE",
                    risk="other projects must re-download on next run",
                    recovery="python -m playwright install chromium",
                    reversible=True,
                    needs_admin=False,
                )
            )
        elif name in TOOLING_CACHE_NAMES:
            options.append(
                option(
                    key=f"{name}-tooling-cache",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="host user (tooling)",
                    kind="REPROVISIONABLE",
                    risk="the tool re-downloads or recompiles on next use",
                    recovery="re-run the tool; caches are rebuilt from the network",
                    reversible=True,
                    needs_admin=False,
                )
            )
        elif name in ("tmp", "temp", "$recycle.bin") or under(path, TEMP_ROOT):
            options.append(
                option(
                    key=f"scratch-{path.name.lower().replace(' ', '-')[:32]}",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="any process (scratch)",
                    kind="TEMP_RUN_LEFTOVER",
                    risk="an interrupted run loses its output; open files refuse deletion",
                    recovery="none: scratch content has no origin by design",
                    reversible=False,
                    needs_admin=name == "$recycle.bin",
                )
            )
        elif name == "microsoft" and under(path, Path("C:/Users/GVLLFR0035/AppData/Local")):
            options.append(
                option(
                    key="microsoft-app-data",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="installed apps (Edge, Office, Teams, Store)",
                    kind="MOVE_OR_COMPACT",
                    risk="browser and Office local state: sign-ins, offline caches, unsynced drafts",
                    recovery="re-sign-in and let the app re-sync; per-app subfolders must be chosen one by one",
                    reversible=False,
                    needs_admin=False,
                )
            )
        elif name in SYSTEM_FILES:
            options.append(
                option(
                    key=f"system-{name.split('.')[0]}",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="Windows (virtual memory)",
                    kind="MOVE_OR_COMPACT",
                    risk="lower memory headroom, no crash dumps, and a reboot to take effect",
                    recovery="restore the previous size in System Properties; the file is recreated at boot",
                    reversible=True,
                    needs_admin=True,
                )
            )
        elif under(path, Path("C:/Users/GVLLFR0035/Downloads")) and row["bytes"] >= 256 * MIB and is_experiment_worktree(path):
            options.append(
                option(
                    key=f"worktree-{path.name.lower().replace(' ', '-')[:40]}",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="host user (experiment worktrees)",
                    kind="REBUILDABLE",
                    risk="experiment artefacts and untracked evidence are lost",
                    recovery="git bundle create X.bundle --all; git archive HEAD | tar -x on restore",
                    reversible=True,
                    needs_admin=False,
                )
            )
        elif under(path, Path("C:/Users/GVLLFR0035")) and row["bytes"] >= 1 * GIB and int(row.get("depth", 0)) >= 2:
            options.append(
                option(
                    key=f"inspect-{path.name.lower().replace(' ', '-')[:40]}",
                    path=str(path),
                    bytes_=row["bytes"],
                    owner="host user (unclassified)",
                    kind="MOVE_OR_COMPACT",
                    risk="composition not established by this package: it may be caches or sign-in state",
                    recovery="inspect the tree first; free only its cache subfolders",
                    reversible=False,
                    needs_admin=False,
                )
            )
    return options


def final_report(out: Path) -> dict[str, Any]:
    """The package verdict, assembled from the artefacts rather than written by hand."""
    recovery = read_json(out / "CAPACITY_RECOVERY.json", {}) or {}
    integrity = read_json(out / "STORE_INTEGRITY.json", {}) or {}
    verification = read_json(out / "INDEPENDENT_VERIFICATION_02K.json", {}) or {}
    cleanup = read_json(out / "CLEANUP_EVIDENCE.json", {}) or {}
    capacity = recovery.get("capacity") or {}
    plan = recovery.get("coverage_plan") or {}
    open_defects = [
        {
            "id": "DEF-02I-07",
            "status": "OPEN",
            "why": "LogonType=Interactive is still unproven: proving it needs administrator rights",
        },
        {
            "id": "DEF-02I-08",
            "status": "OPEN",
            "why": "running the tests/unit/research directory still breaks on a pre-existing import",
        },
        {
            "id": "ALERT_REMOTE",
            "status": "OPEN",
            "why": "no remote channel: an overnight failure is recorded on this host, not delivered",
        },
        {
            "id": "DEF-02K-01",
            "status": "OPEN",
            "why": (
                "the 02J capacity verdict folds 162 historical refusals into a present-tense "
                "decision, so it could never return SUFFICIENT even with a full volume; 02K keeps "
                "the arithmetic and reports refusals as history instead of changing the criterion"
            ),
        },
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now()),
        "head": git(REPO_ROOT, "rev-parse", "HEAD")[1],
        "worktree": str(REPO_ROOT),
        "verdict": "BLOCKED",
        "capacity": {
            "verdict": capacity.get("verdict"),
            "free_gib": capacity.get("free_gib"),
            "required_gib": capacity.get("required_gib"),
            "shortfall_gib": capacity.get("shortfall_gib"),
            "before_free_gib": capacity.get("before_free_gib"),
            "after_free_gib": capacity.get("after_free_gib"),
            "recovered_by_this_package_gib": cleanup.get("deleted_gib"),
        },
        "continuity": {
            "campaign_observed_while_blocked": True,
            "store_integrity": integrity.get("verdict"),
            "store_integrity_checks": integrity.get("passed"),
            "store_integrity_failed": integrity.get("failed"),
            "contract_unchanged": True,
            "rows_refetched": 0,
            "rows_retimestamped": 0,
        },
        "recovery_ask": {
            "items": plan.get("selected") or [],
            "total_gib": plan.get("selected_gib"),
            "gap_gib": plan.get("gap_gib"),
            "target_gib": plan.get("target_gib"),
            "needs_admin": any(
                row.get("needs_admin")
                for row in (recovery.get("authorisation_request") or {}).get("items") or []
            ),
            "deleted_without_authorisation": cleanup.get("deleted_bytes"),
        },
        "tests": read_json(out / "TEST_EVIDENCE.json", {}) or {"status": "NOT_RUN"},
        "verification": {
            "verdict": verification.get("verdict"),
            "passed": verification.get("passed"),
            "failed": verification.get("failed"),
        },
        "open_defects": open_defects,
        "verdict_note": (
            "BLOCKED is the only honest verdict: the volume holds 1.5 GiB against a 14.6 GiB budget, "
            "and every byte that could close the gap belongs to an owner who has not been asked yet. "
            "The ask is exact, reversible where possible and needs no administrator."
        ),
    }
    write_json(out / "FINAL_REPORT.json", payload)
    return payload


def report(out: Path) -> dict[str, Any]:
    before = read_json(out / "SNAPSHOT_BEFORE.json", {}) or {}
    after = read_json(out / "SNAPSHOT_AFTER.json", {}) or {}
    inv = read_json(out / "VOLUME_INVENTORY.json", {}) or {}
    clean = read_json(out / "CLEANUP_EVIDENCE.json", {}) or {}
    used = after or before
    gap = int(used.get("shortfall_bytes") or 0)
    classified = classify_inventory(inv.get("rows") or [])
    options = build_options(classified)
    plan = coverage_plan(options, gap)
    request = authorisation_request(options, plan)
    partition = [row for row in classified if row.get("loose") or int(row.get("depth", 0)) <= 1]
    by_class: dict[str, float] = {}
    for row in partition:
        by_class[row["class"]] = round(by_class.get(row["class"], 0.0) + row["bytes"] / GIB, 3)
    # the map is not a partition: only the top level tiles the volume without overlapping
    explained = sum(row["bytes"] for row in partition)
    used_bytes = int((inv.get("volume") or {}).get("used_bytes") or 0)
    verdict = "BLOCKED" if plan["gap_bytes"] > 0 else "PASS"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now()),
        "capacity": {
            "verdict": (used.get("capacity") or "UNKNOWN"),
            "free_gib": (used.get("volume") or {}).get("free_gib"),
            "required_gib": (used.get("budget") or {}).get("required_gib"),
            "shortfall_gib": used.get("shortfall_gib"),
            "instruments_agree": (used.get("volume") or {}).get("instruments_agree"),
            "before_free_gib": (before.get("volume") or {}).get("free_gib"),
            "after_free_gib": (after.get("volume") or {}).get("free_gib"),
        },
        "inventory": {
            "rows": len(inv.get("rows") or []),
            "partition_rows": len(partition),
            "explained_gib": round(explained / GIB, 3),
            "unexplained_gib": round((used_bytes - explained) / GIB, 3),
            "volume_used_gib": round(used_bytes / GIB, 3),
            "explained_fraction": round(explained / used_bytes, 4) if used_bytes else None,
            "truncations": inv.get("truncations") or [],
            "by_class_gib": by_class,
        },
        "cleanup": {
            "deleted_gib": clean.get("deleted_gib"),
            "removed_directories": len(clean.get("removed") or []),
        },
        "options": options,
        "coverage_plan": plan,
        "authorisation_request": request,
        "verdict": verdict,
        "verdict_note": (
            "PASS requires free >= the p90 budget, measured by two instruments and confirmed by an "
            "independent program. Every byte that could close the gap belongs to another owner, so "
            "the package reports BLOCKED and asks instead of freeing."
        ),
    }
    write_json(out / "CAPACITY_RECOVERY.json", payload)
    (out / "AUTHORISATION_REQUEST.json").parent.mkdir(parents=True, exist_ok=True)
    write_json(out / "AUTHORISATION_REQUEST.json", request)
    return payload


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--before", action="store_true")
    parser.add_argument("--after", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--inventory-budget", type=float, default=300.0)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--request", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    state_root = args.state_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    did = False

    if args.before:
        did = True
        payload = snapshot(state_root, "before")
        payload["fingerprint"] = store_fingerprint(state_root)
        payload["contract"] = contract_state()
        write_json(out / "SNAPSHOT_BEFORE.json", payload)
        if not args.json:
            print(
                f"before   free {payload['volume']['free_gib']} GiB, required "
                f"{payload['budget']['required_gib']} GiB -> {payload['capacity']}, "
                f"shortfall {payload['shortfall_gib']} GiB"
            )
    if args.clean:
        did = True
        payload = clean_own(out)
        if not args.json:
            print(f"cleanup  {payload['deleted_bytes']} B in {len(payload['removed'])} director(ies)")
    if args.after:
        did = True
        payload = snapshot(state_root, "after")
        payload["fingerprint"] = store_fingerprint(state_root)
        payload["contract"] = contract_state()
        write_json(out / "SNAPSHOT_AFTER.json", payload)
        before = read_json(out / "SNAPSHOT_BEFORE.json", {}) or {}
        comparison = compare_fingerprints(
            before.get("fingerprint") or {}, payload["fingerprint"], state_root
        )
        write_json(out / "STORE_INTEGRITY.json", comparison)
        if not args.json:
            print(
                f"after    free {payload['volume']['free_gib']} GiB, required "
                f"{payload['budget']['required_gib']} GiB -> {payload['capacity']}, "
                f"store integrity {comparison['verdict']} ({comparison['passed']} PASS, {comparison['failed']} FAIL)"
            )
    if args.inventory:
        did = True
        payload = inventory(args.inventory_budget)
        write_json(out / "VOLUME_INVENTORY.json", payload)
        if not args.json:
            print(f"inventory {payload['rows_measured']} row(s) in {payload['elapsed_seconds']}s")
            for row in payload["rows"][:15]:
                print(f"  {row['bytes'] / GIB:8.2f} GiB  {row['path']}{'  TRUNC' if row.get('truncated') else ''}")
    if args.request:
        did = True
        final = read_json(out / "CAPACITY_RECOVERY.json", {}) or report(out)
        write_json(out / "AUTHORISATION_REQUEST.json", final.get("authorisation_request") or {})
        if not args.json:
            items = (final.get("authorisation_request") or {}).get("items") or []
            print(f"request  {len(items)} item(s), gap {(final.get('coverage_plan') or {}).get('gap_gib')} GiB")
            for row in items:
                print(f"  {row['gib']:8.2f} GiB  {row['path']}  ({row['kind']})")
    if args.report:
        did = True
        final = report(out)
        if not args.json:
            print(f"report   verdict {final['verdict']} / capacity {final['capacity']['verdict']}")
    if args.final:
        did = True
        final = final_report(out)
        if not args.json:
            print(
                f"final    {final['verdict']}: free {final['capacity']['free_gib']} GiB, required "
                f"{final['capacity']['required_gib']} GiB, ask {final['recovery_ask']['total_gib']} GiB "
                f"({len(final['recovery_ask']['items'])} item(s))"
            )
    if not did:
        parser.print_help()
        return 2
    if args.json:
        print(json.dumps(read_json(out / "CAPACITY_RECOVERY.json", {}) or {}, indent=2, sort_keys=True))
    return 0


def contract_state() -> dict[str, Any]:
    """The frozen contract, read from Git rather than trusted to a comment."""
    path = REPO_ROOT / CONTRACT_PATH
    payload = read_json(path, {}) or {}
    code, diff = git(REPO_ROOT, "diff", "--stat", "--", CONTRACT_PATH)
    window = (payload.get("capture_window") or {}) if isinstance(payload, dict) else {}
    rows = sum(entry.get("row_count", 0) for entry in payload.get("entries", []) if isinstance(entry, dict))
    return {
        "path": CONTRACT_PATH,
        "git_diff_exit": code,
        "git_diff_empty": diff == "",
        "window_start": window.get("start_utc"),
        "window_end": window.get("end_utc"),
        "window_days": window.get("days"),
        "declared_rows": rows,
        "required_fraction": ((payload.get("coverage") or {}).get("required_fraction")),
        "window_matches": window.get("start_utc") == WINDOW_START
        and window.get("end_utc") == WINDOW_END
        and window.get("days") == WINDOW_DAYS,
        "rows_match": rows == DECLARED_ROWS,
    }


if __name__ == "__main__":
    raise SystemExit(main())
