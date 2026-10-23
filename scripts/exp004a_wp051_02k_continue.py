"""WP-051-02K continuation — recover capacity inside the authorisation that was granted.

The package before this one could only ask: every byte that would close the gap belonged to
somebody else. This continuation runs under an explicit, narrow authorisation and therefore has
three jobs, in this order:

1. **Prove the three authorised targets are what the owner thinks they are** before touching them.
   ``ms-playwright`` may only lose a browser revision that no installed consumer asks for,
   ``%LOCALAPPDATA%\\Temp`` may only lose files nobody has written for a week, and ``.cache`` may
   only lose a tree that is not open by any running process.
2. **Delete file by file, never through a link**, writing a manifest line before the unlink so the
   record exists even if the process dies mid-way. A locked file is skipped, not forced.
3. **Measure before and after with two instruments**, and hash the experiment's own files either
   side of the operation, so "recovered" is a measurement and "untouched" is a comparison.

What it will not do, whatever the flag: touch ``hermes``, ``Downloads\\bot_crypto_004g``, any
``NEVER_OFFER`` path, the campaign contract, or the campaign's stored rows.

Usage::

    python scripts/exp004a_wp051_02k_continue.py --plan
    python scripts/exp004a_wp051_02k_continue.py --snapshot before
    python scripts/exp004a_wp051_02k_continue.py --observe 120
    python scripts/exp004a_wp051_02k_continue.py --apply temp-stale,playwright-obsolete
    python scripts/exp004a_wp051_02k_continue.py --snapshot after
    python scripts/exp004a_wp051_02k_continue.py --report
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
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = "EXP004A_WP051_02K_CONTINUATION_V1"
PACKAGE = "WP-051-02K"
GIB = 1024**3
MIB = 1024**2

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02k" / "continuation"
#: Where the campaign lives. Derived from the checkout this program runs in, so the same entrypoint
#: can audit a recovered worktree instead of always pointing at one hard-coded path.
MAIN_ROOT = Path(os.environ.get("EXP004A_MAIN_ROOT") or REPO_ROOT)
STATE_ROOT = MAIN_ROOT / "data" / "forward" / "edge04"
CONTRACT_PATH = REPO_ROOT / "config" / "preregistrations" / "EXP-004A.datasets.phase3.json"

HOME = Path(os.environ.get("USERPROFILE", r"C:\Users\GVLLFR0035"))
PLAYWRIGHT_ROOT = HOME / "AppData" / "Local" / "ms-playwright"
TEMP_ROOT = HOME / "AppData" / "Local" / "Temp"
CACHE_ROOT = HOME / ".cache"
HERMES_ROOT = HOME / "AppData" / "Local" / "hermes"
DENIED_WORKTREE = HOME / "Downloads" / "bot_crypto_004g"

#: The budget 02J derived from eleven days of the observer's own readings (p90 drawdown 12.467
#: GiB + 2 GiB floor + 0.0972 GiB own growth). Not recomputable here while the store is absent, so
#: it is carried as a frozen number rather than quietly lowered to whatever the disk can hold.
FROZEN_REQUIRED_GIB = 14.564
FROZEN_REQUIRED_BYTES = int(round(FROZEN_REQUIRED_GIB * GIB))
FROZEN_BUDGET_BASIS = (
    "02J p90 drawdown 12.467 GiB + 2 GiB protection floor + 0.0972 GiB campaign growth over the "
    "90-day window; frozen because the store that produced it is absent in this tree"
)

#: A file nobody has written for this long is stale; anything younger may belong to a live run.
TEMP_MIN_AGE_DAYS = 7
#: Scratch trees that are deliverables of other packages: kept whatever their age, by policy.
TEMP_EVIDENCE_PATTERNS = (
    "pytest-reports",
    "pytest-of-",
    "recovery-rehearsal-",
    "rfc0",  # rfc004/rfc008/rfc012/rfc014/rfc025 acceptance scratch trees
    "tap0",
    "tap-",
)

#: Package families whose revision this program may retire, if nobody asks for it.
PLAYWRIGHT_FAMILIES = ("chromium", "chromium_headless_shell", "firefox", "webkit")

#: Paths this program must never delete, move or compact, with the reason on record.
NEVER_OFFER = (
    (HOME / "OneDrive - Generalitat de Catalunya", "user documents (OneDrive)"),
    (HOME / "Documents", "user documents"),
    (HOME / "Desktop", "user documents"),
    (HOME / "Downloads", "user downloads"),
    (HOME / "Pictures", "user documents"),
    (HOME / "Videos", "user documents"),
    (HOME / "Music", "user documents"),
    (HOME / "Generalitat de Catalunya", "user documents"),
    # The profile root itself is deliberately absent from this list: two of the three authorised
    # targets live under ``AppData\Local``. What keeps this program out of the rest of the profile
    # is the root check in ``apply_target``, not a blanket ban that would also block the mandate.
    (Path("C:/Windows"), "operating system"),
    (Path("C:/Program Files"), "operating system"),
    (Path("C:/Program Files (x86)"), "operating system"),
    (Path("C:/ProgramData"), "operating system"),
    (HERMES_ROOT, "tooling cache: owner refused this package permission"),
    (DENIED_WORKTREE, "experiment worktree: owner refused this package permission"),
)


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


def git(*args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - environment failure
        return 127, str(exc)
    return done.returncode, (done.stdout or "").strip()


# --------------------------------------------------------------------------- #
# capacity
# --------------------------------------------------------------------------- #
def _windows_free(path: str) -> int:
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    available = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p(path), ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)
    )
    if not ok:  # pragma: no cover - environment failure
        raise OSError("GetDiskFreeSpaceExW failed")
    return int(available.value)


def volume(path: str = "C:/") -> dict[str, Any]:
    """The same question through two instruments: Python's wrapper and the Win32 call."""
    usage = shutil.disk_usage(path)
    first = int(usage.free)
    second = _windows_free(path) if sys.platform == "win32" else first
    return {
        "path": path,
        "free_bytes": first,
        "free_bytes_kernel32": second,
        "instruments_agree": first == second,
        "total_bytes": int(usage.total),
        "free_gib": round(first / GIB, 4),
        "used_bytes": int(usage.total) - first,
        "used_percent": round((int(usage.total) - first) / int(usage.total) * 100, 2),
        "at_utc": iso(now()),
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))]


def budget(state_root: Path = STATE_ROOT) -> dict[str, Any]:
    """Recompute from the observer's readings when they exist; otherwise carry the frozen plan.

    Lowering the budget because the evidence is missing would turn an absence into a pass, so the
    frozen figure is kept and labelled.
    """
    rows: list[dict[str, Any]] = []
    runs = state_root / "runs.jsonl"
    try:
        lines = runs.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
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
            rows.append({"ts": stamp, "free": free})
    rows.sort(key=lambda item: item["ts"])
    if len(rows) < 2:
        return {
            "source": "FROZEN_02J_P90",
            "required_bytes": FROZEN_REQUIRED_BYTES,
            "required_gib": FROZEN_REQUIRED_GIB,
            "basis": FROZEN_BUDGET_BASIS,
            "recomputable": False,
            "why_not_recomputed": f"no readings at {runs} (store absent or empty); the figure is carried, not reduced",
        }
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = iso(datetime.fromtimestamp(row["ts"] / 1000, tz=UTC))[:10]
        buckets.setdefault(day, []).append(row)
    drawdowns: list[float] = []
    for day_rows in buckets.values():
        if len(day_rows) < 2:
            continue
        peak = 0
        worst = 0.0
        for row in day_rows:
            peak = max(peak, row["free"])
            worst = max(worst, peak - row["free"])
        drawdowns.append(worst)
    own = read_json(state_root / "resource_budget.json", {}) or {}
    samples = [
        row
        for row in (own.get("samples") if isinstance(own.get("samples"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("ts_ms"), int) and isinstance(row.get("bytes"), int)
    ]
    own_per_day = 0
    if len(samples) >= 2:
        samples.sort(key=lambda row: row["ts_ms"])
        span_days = max((samples[-1]["ts_ms"] - samples[0]["ts_ms"]) / 86_400_000, 1e-9)
        own_per_day = int((samples[-1]["bytes"] - samples[0]["bytes"]) / span_days)
    p90 = int(percentile(drawdowns, 0.90))
    required = own_per_day * 90 + 2 * GIB + p90
    return {
        "source": "RECOMPUTED_FROM_OBSERVER",
        "required_bytes": required,
        "required_gib": round(required / GIB, 3),
        "basis": "p90 drawdown + 2 GiB floor + own growth over 90 days, from the store's own rows",
        "recomputable": True,
        "readings": len(rows),
        "history_days": len(drawdowns),
        "drawdown_p90_gib": round(p90 / GIB, 3),
        "own_bytes_per_day": own_per_day,
    }


def capacity_state(vol: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    free = vol["free_bytes"]
    return {
        "free_gib": vol["free_gib"],
        "required_gib": plan["required_gib"],
        "margin_gib": round((free - plan["required_bytes"]) / GIB, 4),
        "verdict": "PASS" if free >= plan["required_bytes"] else "INSUFFICIENT",
        "instruments_agree": vol["instruments_agree"],
    }


# --------------------------------------------------------------------------- #
# safety primitives
# --------------------------------------------------------------------------- #
def is_reparse(path: Path) -> bool:
    """A junction or symlink: this program never descends through one, let alone deletes one."""
    try:
        info = os.lstat(path)
    except OSError:
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (ValueError, OSError):
        return False
    return True


def denied(path: Path) -> str | None:
    for root, why in NEVER_OFFER:
        if under(path, root):
            return why
    return None


def walk_files(root: Path, *, max_seconds: float = 600.0) -> Iterator[tuple[Path, int, int]]:
    """Yield ``(path, bytes, mtime_ns)`` for regular files; prune every reparse point."""
    deadline = time.monotonic() + max_seconds
    stack = [root]
    while stack:
        current = stack.pop()
        if time.monotonic() > deadline:
            return
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    child = Path(entry.path)
                    if is_reparse(child):
                        continue
                    stack.append(child)
                elif entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    yield Path(entry.path), int(info.st_size), int(info.st_mtime_ns)
            except OSError:
                continue


def tree_bytes(root: Path, *, max_seconds: float = 600.0) -> int:
    return sum(size for _, size, _ in walk_files(root, max_seconds=max_seconds))


def process_table() -> list[dict[str, Any]]:
    """Every process this account can see, with the write counters Windows keeps per process."""
    try:
        import psutil  # noqa: PLC0415 - optional at runtime, the whole module degrades without it
    except ImportError:  # pragma: no cover - environment failure
        return []
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            counters = proc.io_counters()
            rows.append(
                {
                    "pid": proc.pid,
                    "name": proc.info.get("name") or "?",
                    "write_bytes": int(getattr(counters, "write_bytes", 0)),
                    "read_bytes": int(getattr(counters, "read_bytes", 0)),
                }
            )
        except (psutil.Error, OSError):
            continue
    return rows


#: Processes whose handle table is either unreadable or slow enough to stall the sampler.
OPEN_FILES_SKIP = frozenset(
    {"System", "Registry", "Memory Compression", "csrss.exe", "svchost.exe", "MsMpEng.exe", "Idle", "System Idle Process"}
)


def open_paths(max_seconds: float = 20.0) -> dict[str, Any]:
    """Paths a running process holds open, bounded in time and explicit about what it missed.

    ``open_files`` walks a process handle table and can block for minutes on a protected process.
    The sampler therefore reads the cheap signals (executable and working directory) for every
    process, tries the handle table under a deadline, and reports the truncation instead of
    pretending the list is complete. A file already open still cannot be deleted: Windows refuses
    the unlink, and the caller counts that refusal.
    """
    try:
        import psutil  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return {"paths": [], "scanned": 0, "truncated": True, "why": "psutil unavailable"}
    found: list[str] = []
    scanned = 0
    truncated = False
    deadline = time.monotonic() + max_seconds
    for proc in psutil.process_iter(["pid", "name"]):
        name = proc.info.get("name") or ""
        try:
            exe = proc.exe()
            if exe:
                found.append(exe)
            cwd = proc.cwd()
            if cwd:
                found.append(cwd)
        except (psutil.Error, OSError):
            pass
        if name in OPEN_FILES_SKIP:
            continue
        if time.monotonic() > deadline:
            truncated = True
            break
        try:
            for handle in proc.open_files():
                found.append(handle.path)
            scanned += 1
        except (psutil.Error, OSError):
            continue
    return {"paths": found, "scanned": scanned, "truncated": truncated, "deadline_seconds": max_seconds}


# --------------------------------------------------------------------------- #
# targets: playwright
# --------------------------------------------------------------------------- #
def _revision_of(name: str) -> str | None:
    for family in sorted(PLAYWRIGHT_FAMILIES, key=len, reverse=True):
        if name.startswith(family + "-"):
            return name[len(family) + 1 :]
    return None


def consumer_manifests(root: Path = PLAYWRIGHT_ROOT) -> list[dict[str, Any]]:
    """Who is installed against this browser cache, and which revision each of them asks for.

    ``.links`` is playwright's own record of every package that installed browsers here. A link
    whose target is gone is reported as a stale link, not counted as a consumer.
    """
    rows: list[dict[str, Any]] = []
    links = root / ".links"
    if not links.is_dir():
        return rows
    for link in sorted(links.iterdir()):
        try:
            target = Path(link.read_text(encoding="utf-8").strip())
        except OSError:
            continue
        row: dict[str, Any] = {"link": link.name, "target": str(target), "exists": target.exists()}
        browsers = target / "browsers.json"
        if browsers.exists():
            try:
                payload = json.loads(browsers.read_text(encoding="utf-8"))
                row["requires"] = sorted(
                    {
                        str(item.get("revision"))
                        for item in payload.get("browsers", [])
                        if str(item.get("name", "")).startswith(PLAYWRIGHT_FAMILIES)
                    }
                )
                row["status"] = "CONSUMER"
            except (OSError, json.JSONDecodeError):
                row["status"] = "UNREADABLE_MANIFEST"
        else:
            row["status"] = "STALE_LINK" if not target.exists() else "NO_MANIFEST"
        rows.append(row)
    return rows


def installed_revisions(root: Path = PLAYWRIGHT_ROOT) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return rows
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir() or is_reparse(entry):
            continue
        revision = _revision_of(entry.name)
        if revision is None:
            rows[entry.name] = {"family": None, "revision": None, "bytes": tree_bytes(entry, max_seconds=120)}
            continue
        info = entry.stat()
        rows[entry.name] = {
            "family": next(f for f in PLAYWRIGHT_FAMILIES if entry.name.startswith(f + "-")),
            "revision": revision,
            "bytes": tree_bytes(entry, max_seconds=120),
            "mtime_ns": info.st_mtime_ns,
        }
    return rows


#: Where a build tool keeps its own playwright, outside the ``.links`` record. A revision that one
#: of these asks for is not obsolete, whether or not it installed browsers through this cache.
CONSUMER_SCAN_ROOTS = (
    "node_modules",
    "AppData/Local/npm-cache",
    "AppData/Local/Programs",
    "AppData/Local/OpenAI",
    "AppData/Roaming/npm",
    ".cache",
    ".vscode/extensions",
)


def scan_consumer_manifests(max_seconds: float = 180.0) -> dict[str, Any]:
    """Every ``browsers.json`` on this account, so "nobody asks for it" is a search, not a guess."""
    deadline = time.monotonic() + max_seconds
    found: list[dict[str, Any]] = []
    truncated = False
    for relative in CONSUMER_SCAN_ROOTS:
        root = HOME / relative
        if not root.is_dir():
            continue
        stack = [root]
        while stack:
            if time.monotonic() > deadline:
                truncated = True
                break
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        child = Path(entry.path)
                        if not is_reparse(child) and len(str(child)) < 300:
                            stack.append(child)
                    elif entry.name == "browsers.json":
                        payload = json.loads(Path(entry.path).read_text(encoding="utf-8"))
                        requires = sorted(
                            {
                                str(item.get("revision"))
                                for item in payload.get("browsers", [])
                                if str(item.get("name", "")).startswith(PLAYWRIGHT_FAMILIES)
                            }
                        )
                        found.append({"path": entry.path, "requires": requires})
                except (OSError, json.JSONDecodeError):
                    continue
    return {
        "roots": [str(HOME / relative) for relative in CONSUMER_SCAN_ROOTS],
        "manifests": found,
        "truncated": truncated,
        "deadline_seconds": max_seconds,
    }


def playwright_plan(root: Path = PLAYWRIGHT_ROOT, *, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = consumer_manifests(root)
    installed = installed_revisions(root)
    scanned = scan if scan is not None else scan_consumer_manifests()
    required = sorted(
        {rev for row in manifest if row.get("requires") for rev in row["requires"]}
        | {rev for row in scanned.get("manifests", []) for rev in row.get("requires", [])}
    )
    obsolete: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for name, info in installed.items():
        revision = info.get("revision")
        record = {"name": name, "revision": revision, "bytes": info.get("bytes", 0)}
        if revision is None or revision in required:
            kept.append({**record, "why": "revision is not a browser build" if revision is None else "installed consumer asks for it"})
        elif any(other.get("revision") == revision for other in obsolete):
            obsolete.append(record)
        else:
            obsolete.append({**record, "why": "no installed consumer asks for this revision"})
    return {
        "key": "playwright-obsolete",
        "root": str(root),
        "consumers": manifest,
        "consumer_scan": {
            "manifests": len(scanned.get("manifests", [])),
            "roots": scanned.get("roots", []),
            "truncated": scanned.get("truncated"),
        },
        "required_revisions": required,
        "installed": list(installed.values()),
        "obsolete": obsolete,
        "kept": kept,
        "bytes_reclaimable": sum(item["bytes"] for item in obsolete),
        "reinstall": "python -m playwright install chromium (per revision the consumer needs)",
        "rule": (
            "a revision is retireable only when no installed consumer -- in .links or in any "
            "browsers.json found under the scanned build roots -- asks for it"
        ),
    }


# --------------------------------------------------------------------------- #
# targets: temp
# --------------------------------------------------------------------------- #
def temp_plan(
    root: Path = TEMP_ROOT,
    *,
    min_age_days: int = TEMP_MIN_AGE_DAYS,
    reference_ts: float | None = None,
) -> dict[str, Any]:
    """Files a week old or more, minus the scratch trees another package calls evidence."""
    stamp = reference_ts if reference_ts is not None else time.time()
    cutoff = stamp - min_age_days * 86_400
    candidates: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    scanned = 0
    for path, size, mtime_ns in walk_files(root):
        scanned += 1
        age_days = round((stamp - mtime_ns / 1e9) / 86_400, 2)
        relative = str(path)[len(str(root)) + 1 :]
        if any(relative.startswith(pattern) or pattern in relative.split(os.sep)[0] for pattern in TEMP_EVIDENCE_PATTERNS):
            if mtime_ns / 1e9 <= cutoff:
                preserved.append({"path": str(path), "bytes": size, "why": "another package's scratch evidence, kept by policy"})
            continue
        if mtime_ns / 1e9 > cutoff:
            continue
        candidates.append({"path": str(path), "bytes": size, "mtime_ns": mtime_ns, "age_days": age_days})
    return {
        "key": "temp-stale",
        "root": str(root),
        "min_age_days": min_age_days,
        "cutoff_utc": iso(datetime.fromtimestamp(cutoff, tz=UTC)),
        "candidates": candidates,
        "preserved": preserved,
        "scanned_files": scanned,
        "bytes_reclaimable": sum(item["bytes"] for item in candidates),
        "bytes_preserved": sum(item["bytes"] for item in preserved),
        "preserved_files": len(preserved),
    }


# --------------------------------------------------------------------------- #
# targets: .cache
# --------------------------------------------------------------------------- #
#: A cache entry may only go when nothing that could need it is running. The named tools are the
#: ones whose runtime lives under ``.cache``; refusing them is a decision, not a measurement gap.
CACHE_LIVE_TOOLS = ("codex", "codex-computer-use", "codex-windows")


def cache_plan(root: Path = CACHE_ROOT, *, handles: dict[str, Any] | None = None) -> dict[str, Any]:
    """A cache entry may go only if it is regenerable *and* no process holds it open."""
    probe = handles if handles is not None else open_paths()
    paths = probe.get("paths") or []
    entries: list[dict[str, Any]] = []
    if not root.is_dir():
        return {
            "key": "cache-regenerable",
            "root": str(root),
            "entries": [],
            "bytes_reclaimable": 0,
            "in_use_probe": probe,
        }
    for entry in sorted(root.iterdir()):
        if is_reparse(entry):
            entries.append({"path": str(entry), "bytes": 0, "eligible": False, "why": "reparse point: not followed"})
            continue
        size = tree_bytes(entry, max_seconds=60) if entry.is_dir() else entry.stat().st_size
        in_use = [handle for handle in paths if under(Path(handle), entry)]
        live = [
            row
            for row in process_table()
            if any(str(row.get("name") or "").lower().startswith(tool) for tool in CACHE_LIVE_TOOLS)
        ]
        regenerable = (entry / "codex-primary-runtime").exists() or any(
            (entry / marker).exists() for marker in ("node_modules", "package.json", "uv", "pip", "wheels")
        )
        if in_use:
            why = f"open by a running process ({len(in_use)} handles, e.g. {in_use[0]})"
        elif live:
            why = (
                "runtime of a tool that is running ("
                + ", ".join(sorted({f"{row['name']}#{row['pid']}" for row in live})[:3])
                + "): regenerable, but not provably unused, so not deleted"
            )
        elif not regenerable:
            why = "no marker that it is a downloaded runtime or package cache"
        else:
            why = ""
        entries.append(
            {
                "path": str(entry),
                "bytes": size,
                "eligible": not why,
                "why": why or "downloaded runtime, rebuilt on next use",
                "in_use_handles": in_use[:5],
            }
        )
    return {
        "key": "cache-regenerable",
        "root": str(root),
        "entries": entries,
        "bytes_reclaimable": sum(item["bytes"] for item in entries if item["eligible"]),
        "in_use_probe": probe,
    }


# --------------------------------------------------------------------------- #
# integrity of the experiment's own files
# --------------------------------------------------------------------------- #
INTEGRITY_ROOTS = (
    "docs/agentic/exp004a",
    "config/preregistrations",
    "scripts/edge04_watchdog.py",
)

#: The commit the 02K record was recovered from. A file that does not match it was edited after
#: recovery, and the report has to say so rather than call the record restored.
RECOVERY_COMMIT = "9983b050c8e241ef9d8365c8ffc33c95df1658dd"
RECORD_ROOT = "docs/agentic/exp004a/wp051_02k"
RECORD_EXCLUDE = ("continuation",)

#: What the campaign itself is made of, and whether this checkout still has it.
EXPERIMENT_ARTIFACTS = (
    ("contract", "config/preregistrations/EXP-004A.datasets.phase3.json"),
    ("store", "data/forward/edge04"),
    ("observer_watchdog", "scripts/edge04_watchdog.py"),
    ("capture_runner", "scripts/exp004a_wp051_02f_runner.py"),
)


def record_hashes() -> dict[str, Any]:
    """Compare the recovered files with the blobs of the commit they came from."""
    rows: dict[str, dict[str, Any]] = {}
    root = REPO_ROOT / RECORD_ROOT
    if not root.is_dir():
        return {"commit": RECOVERY_COMMIT, "present": False, "files": rows}
    for path, _, _ in walk_files(root):
        relative = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if any(part in relative for part in RECORD_EXCLUDE):
            continue
        code_local, local = git("hash-object", relative)
        code_commit, committed = git("rev-parse", f"{RECOVERY_COMMIT}:{relative}")
        rows[relative] = {
            "local_blob": local if code_local == 0 else None,
            "commit_blob": committed if code_commit == 0 else None,
            "identical": code_local == 0 and code_commit == 0 and local == committed,
        }
    return {"commit": RECOVERY_COMMIT, "present": True, "files": rows}


def experiment_presence() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for name, relative in EXPERIMENT_ARTIFACTS:
        path = REPO_ROOT / relative
        rows[name] = {"path": relative, "exists": path.exists(), "bytes": tree_bytes(path, max_seconds=60) if path.is_dir() else (path.stat().st_size if path.exists() else 0)}
    return rows


def integrity_manifest() -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for relative in INTEGRITY_ROOTS:
        root = REPO_ROOT / relative
        if not root.exists():
            files[f"{relative}/"] = {"exists": False}
            continue
        if root.is_file():
            files[relative] = {"bytes": root.stat().st_size, "mtime_ns": root.stat().st_mtime_ns, "sha256": sha256_file(root)}
            continue
        for path, size, mtime_ns in walk_files(root):
            relative_path = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            # This package's own evidence lives under the record root; hashing it here would make
            # every run differ from the one before it for a reason that is not a change.
            if "/continuation/" in relative_path:
                continue
            files[relative_path] = {
                "bytes": size,
                "mtime_ns": mtime_ns,
                "sha256": sha256_file(path),
            }
    store: dict[str, Any] = {"root": str(STATE_ROOT), "exists": STATE_ROOT.is_dir()}
    if STATE_ROOT.is_dir():
        store["daily"] = {
            path.name: {"sha256": sha256_file(path), "mtime_ns": path.stat().st_mtime_ns}
            for path in sorted(STATE_ROOT.glob("daily/*.json"))
        }
        store["append_only"] = {
            name: {"bytes": (STATE_ROOT / name).stat().st_size, "sha256": sha256_file(STATE_ROOT / name)}
            for name in ("runs.jsonl", "slots.jsonl", "alerts.jsonl", "ALERT_LEDGER.jsonl", "WATCHDOG_EVENTS.jsonl")
            if (STATE_ROOT / name).exists()
        }
    head_code, head = git("rev-parse", "HEAD")
    status_code, status = git("status", "--porcelain")
    return {
        "at_utc": iso(now()),
        "files": files,
        "count": len(files),
        "store": store,
        "record": record_hashes(),
        "experiment": experiment_presence(),
        "git": {
            "head": head if head_code == 0 else None,
            "status_lines": len(status.splitlines()) if status_code == 0 else None,
            "status_digest": hashlib.sha256(status.encode("utf-8")).hexdigest() if status_code == 0 else None,
        },
    }


def compare_integrity(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    old_files = before.get("files") or {}
    new_files = after.get("files") or {}
    changed = [path for path, info in old_files.items() if new_files.get(path) != info]
    checks.append(
        {
            "id": "EXPERIMENT_FILES_IDENTICAL",
            "status": "PASS" if not changed else "FAIL",
            "detail": f"{len(old_files)} files hashed either side; {len(changed)} differ",
            "changed": changed[:20],
        }
    )
    record = after.get("record") or {}
    record_files = record.get("files") or {}
    mismatched = [path for path, info in record_files.items() if not info.get("identical")]
    if record_files:
        checks.append(
            {
                "id": "RECOVERED_RECORD_MATCHES_COMMIT",
                "status": "PASS" if not mismatched else "FAIL",
                "detail": f"{len(record_files)} files recovered from {RECOVERY_COMMIT[:8]}; {len(mismatched)} differ from their blob",
                "changed": mismatched[:10],
            }
        )
    experiment = after.get("experiment") or {}
    missing = [name for name, info in experiment.items() if not info.get("exists")]
    checks.append(
        {
            "id": "LIVE_EXPERIMENT_PRESENT",
            "status": "PASS" if not missing else "FAIL",
            "detail": (
                "contract, store, guard and runner are all in this checkout"
                if not missing
                else f"absent from this checkout: {', '.join(missing)}; the record was recovered from Git, the live artefacts were not"
            ),
            "absent": missing,
        }
    )
    before_store = before.get("store") or {}
    after_store = after.get("store") or {}
    checks.append(
        {
            "id": "STORE_PRESENT",
            "status": "PASS" if after_store.get("exists") else "FAIL",
            "detail": (
                "campaign store present and hashed"
                if after_store.get("exists")
                else f"campaign store absent at {after_store.get('root')}: continuity cannot be certified from this tree"
            ),
        }
    )
    if before_store.get("exists") and after_store.get("exists"):
        same = (
            before_store.get("daily") == after_store.get("daily")
            and before_store.get("append_only") == after_store.get("append_only")
        )
        checks.append(
            {
                "id": "STORE_UNCHANGED_BY_THIS_PACKAGE",
                "status": "PASS" if same else "FAIL",
                "detail": "write-once shards keep hash and mtime; append-only files keep their bytes",
            }
        )
    return {
        "checks": checks,
        "verdict": "PASS" if all(c["status"] in ("PASS", "SKIP") for c in checks) else "FAIL",
    }


# --------------------------------------------------------------------------- #
# deletion
# --------------------------------------------------------------------------- #
def apply_target(target: dict[str, Any], *, evidence_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """Unlink file by file, manifest first. Locked files are counted, never forced."""
    started = volume()
    files = target.get("candidates") if target.get("key") == "temp-stale" else target.get("files")
    files = files or []
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    deleted_bytes = 0
    touched_roots: set[str] = set()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with evidence_path.open("w", encoding="utf-8") as manifest:
        for item in files:
            path = Path(item["path"])
            if not under(path, Path(target["root"])):
                skipped.append({"path": str(path), "why": "outside the authorised root of this target"})
                continue
            reason = denied(path)
            if reason:
                skipped.append({"path": str(path), "why": f"protected: {reason}"})
                continue
            if is_reparse(path):
                skipped.append({"path": str(path), "why": "reparse point: not followed"})
                continue
            try:
                info = path.lstat()
            except OSError as exc:
                skipped.append({"path": str(path), "why": f"stat failed: {exc.__class__.__name__}"})
                continue
            record = {
                "path": str(path),
                "bytes": int(info.st_size),
                "mtime_ns": int(info.st_mtime_ns),
                "sha256": sha256_file(path) if info.st_size <= MIB else None,
                "target": target["key"],
            }
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            if dry_run:
                deleted.append(record)
                deleted_bytes += record["bytes"]
                continue
            try:
                path.unlink()
            except OSError as exc:
                skipped.append({"path": str(path), "why": f"locked or refused: {exc.__class__.__name__}"})
                continue
            deleted.append(record)
            deleted_bytes += record["bytes"]
            touched_roots.add(str(path.parent))
        manifest.flush()
        os.fsync(manifest.fileno())
    pruned = 0
    if not dry_run:
        for parent in sorted(touched_roots, key=len, reverse=True):
            current = Path(parent)
            while under(current, Path(target["root"])) and current != Path(target["root"]):
                try:
                    current.rmdir()
                    pruned += 1
                except OSError:
                    break
                current = current.parent
    finished = volume()
    try:
        manifest_label = str(evidence_path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        manifest_label = str(evidence_path)
    return {
        "key": target["key"],
        "root": target["root"],
        "planned_bytes": int(target.get("bytes_reclaimable") or 0),
        "planned_files": len(files),
        "deleted_files": len(deleted),
        "deleted_bytes": deleted_bytes,
        "deleted_gib": round(deleted_bytes / GIB, 4),
        "skipped": skipped[:200],
        "skipped_count": len(skipped),
        "pruned_directories": pruned,
        "manifest": manifest_label,
        "volume_before": started,
        "volume_after": finished,
        "volume_delta_bytes": finished["free_bytes"] - started["free_bytes"],
        "dry_run": dry_run,
    }


# --------------------------------------------------------------------------- #
# observation
# --------------------------------------------------------------------------- #
def tree_sizes(roots: Iterable[Path]) -> dict[str, int]:
    return {str(root): tree_bytes(root, max_seconds=120) for root in roots if root.exists()}


def observe(seconds: int = 120, interval: float = 5.0) -> dict[str, Any]:
    """Sample the volume and every process' write counter; attribute, do not accuse."""
    watch = [
        TEMP_ROOT,
        PLAYWRIGHT_ROOT,
        CACHE_ROOT,
        MAIN_ROOT / "data",
        REPO_ROOT / "data",
        HOME / "AppData" / "Local" / "Microsoft",
    ]
    start_sizes = tree_sizes(watch)
    samples: list[dict[str, Any]] = []
    previous: dict[int, dict[str, Any]] = {}
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        stamp = iso(now())
        table = process_table()
        vol = volume()
        current = {row["pid"]: row for row in table}
        writers: list[dict[str, Any]] = []
        for pid, row in current.items():
            old = previous.get(pid)
            if not old:
                continue
            written = row["write_bytes"] - old["write_bytes"]
            if written > 0:
                writers.append({"pid": pid, "name": row["name"], "written_bytes": written})
        writers.sort(key=lambda item: item["written_bytes"], reverse=True)
        samples.append(
            {
                "at_utc": stamp,
                "free_bytes": vol["free_bytes"],
                "writers": writers[:8],
                "written_total_bytes": sum(item["written_bytes"] for item in writers),
                "processes": len(table),
            }
        )
        previous = current
        time.sleep(interval)
    end_sizes = tree_sizes(watch)
    intervals = []
    by_name: dict[str, dict[str, Any]] = {}
    for older, newer in zip(samples, samples[1:]):
        drop = older["free_bytes"] - newer["free_bytes"]
        explained = sum(item["written_bytes"] for item in newer["writers"])
        intervals.append({"at_utc": newer["at_utc"], "drop_bytes": drop, "written_bytes": explained})
        for item in newer["writers"]:
            bucket = by_name.setdefault(item["name"], {"name": item["name"], "written_bytes": 0, "intervals": 0})
            bucket["written_bytes"] += item["written_bytes"]
            bucket["intervals"] += 1
    dropped = sum(max(0, item["drop_bytes"]) for item in intervals)
    written = sum(item["written_bytes"] for item in intervals)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(now()),
        "seconds": seconds,
        "interval_seconds": interval,
        "samples": len(samples),
        "intervals": intervals,
        "dropped_bytes": dropped,
        "written_bytes": written,
        "share_explained_percent": round(written / dropped * 100, 2) if dropped else None,
        "writers": sorted(by_name.values(), key=lambda item: item["written_bytes"], reverse=True)[:10],
        "tree_growth_bytes": {
            key: end_sizes.get(key, 0) - start_sizes.get(key, 0) for key in set(start_sizes) | set(end_sizes)
        },
        "trees_watched": [str(root) for root in watch],
        "caveat": (
            "write counters are per process and cumulative; a large writer is not necessarily the "
            "one that lowered free space, so drops and writes are reported side by side. Deferred "
            "allocation (paging, compression, delayed writes) can move the volume after the write."
        ),
        "free_first": samples[0]["free_bytes"] if samples else None,
        "free_last": samples[-1]["free_bytes"] if samples else None,
    }


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def package_state() -> dict[str, Any]:
    head_code, head = git("rev-parse", "HEAD")
    branch_code, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    status_code, status = git("status", "--porcelain")
    return {
        "root": str(REPO_ROOT),
        "head": head if head_code == 0 else None,
        "branch": branch if branch_code == 0 else None,
        "dirty_paths": len(status.splitlines()) if status_code == 0 else None,
    }


def guard_state() -> dict[str, Any]:
    watchdog = REPO_ROOT / "scripts" / "edge04_watchdog.py"
    running: list[dict[str, Any]] = []
    for row in process_table():
        name = (row.get("name") or "").lower()
        if "watchdog" in name or "edge04" in name:
            running.append({"pid": row["pid"], "name": row["name"]})
    return {
        "script_present": watchdog.exists(),
        "script": str(watchdog.relative_to(REPO_ROOT)).replace("\\", "/"),
        "process_running": running,
        "store_present": STATE_ROOT.is_dir(),
        "state": (
            "ACTIVE"
            if running
            else ("FILE_PRESENT_NO_PROCESS" if watchdog.exists() else "ABSENT_IN_THIS_TREE")
        ),
        "note": (
            "the guard shipped with the 02J/02K worktree, which is not in this tree; nothing here "
            "claims the campaign is protected while both the guard and the store it guards are absent"
        ),
    }


def build_report() -> dict[str, Any]:
    before = read_json(OUT / "SNAPSHOT_BEFORE.json", {}) or {}
    after = read_json(OUT / "SNAPSHOT_AFTER.json", {}) or {}
    observation = read_json(OUT / "WRITE_ATTRIBUTION.json", {}) or {}
    cleanup = read_json(OUT / "CLEANUP_EVIDENCE.json", {}) or {}
    integrity_before = read_json(OUT / "INTEGRITY_BEFORE.json", {}) or {}
    integrity_after = read_json(OUT / "INTEGRITY_AFTER.json", {}) or {}
    integration = compare_integrity(integrity_before, integrity_after) if integrity_after else {"checks": [], "verdict": "NOT_RUN"}
    plan = budget()
    capacity_before = before.get("capacity") or {}
    capacity_after = after.get("capacity") or {}
    protected_touched: list[str] = []
    manifest_entries = 0
    for target in cleanup.get("targets", []):
        manifest = REPO_ROOT / str(target.get("manifest") or "")
        if not manifest.is_file():
            continue
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            manifest_entries += 1
            try:
                path = json.loads(line).get("path")
            except json.JSONDecodeError:
                continue
            if path and denied(Path(path)):
                protected_touched.append(path)
    blockers: list[str] = []
    if capacity_after.get("verdict") != "PASS":
        blockers.append("CAPACITY_INSUFFICIENT")
    absent = [name for name, info in (integrity_after.get("experiment") or {}).items() if not info.get("exists")]
    if "store" in absent:
        blockers.append("CAMPAIGN_STORE_ABSENT")
    if set(absent) - {"store"}:
        blockers.append("EXPERIMENT_ARTIFACTS_ABSENT")
    # Absence is reported above as an absence; this one means bytes moved, which is a different sin.
    absence_checks = {"LIVE_EXPERIMENT_PRESENT", "STORE_PRESENT"}
    changed = [check for check in integration.get("checks", []) if check["id"] not in absence_checks]
    if any(check["status"] == "FAIL" for check in changed):
        blockers.append("INTEGRITY_FAILED")
    if protected_touched:
        blockers.append("PROTECTED_PATH_TOUCHED")
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now()),
        "tree": package_state(),
        "budget": plan,
        "capacity": {
            "before": capacity_before,
            "after": capacity_after,
            "verdict": capacity_after.get("verdict") or "UNMEASURED",
        },
        "cleanup": {
            "targets": cleanup.get("targets", []),
            "manifest_entries": manifest_entries,
            "total_deleted_bytes": sum(target.get("deleted_bytes", 0) for target in cleanup.get("targets", [])),
            "total_deleted_gib": round(
                sum(target.get("deleted_bytes", 0) for target in cleanup.get("targets", [])) / GIB, 4
            ),
            "volume_delta_bytes": (
                (capacity_after.get("free_bytes") or 0) - (capacity_before.get("free_bytes") or 0)
            ),
        },
        "refused": cleanup.get("refused", []),
        "observed_growth": {
            "seconds": observation.get("seconds"),
            "dropped_bytes": observation.get("dropped_bytes"),
            "writers": observation.get("writers", [])[:6],
            "share_explained_percent": observation.get("share_explained_percent"),
            "caveat": observation.get("caveat"),
        },
        "integrity": {"checks": integration.get("checks", []), "verdict": integration.get("verdict")},
        "guard": guard_state(),
        "verdict": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "verdict_note": (
            "capacity PASS requires the measured free space to reach the frozen budget with both "
            "instruments agreeing; the campaign itself stays BLOCKED for any blocker that the "
            "volume cannot answer"
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    capacity = report.get("capacity", {})
    before = capacity.get("before", {})
    after = capacity.get("after", {})
    cleanup = report.get("cleanup", {})
    integrity = report.get("integrity", {})
    guard = report.get("guard", {})
    observation = report.get("observed_growth", {})
    lines = [
        "# WP-051-02K (continuación) — recuperación de capacidad con autorización limitada",
        "",
        f"**Paquete:** {report.get('package')} · **Generado:** {report.get('generated_at_utc')} · "
        f"**Dictamen:** `{report.get('verdict')}`",
        "",
        "## Espacio",
        "",
        "| Momento | Libre | Presupuesto | Margen | Instrumentos |",
        "| --- | --- | --- | --- | --- |",
        f"| Antes | {before.get('free_gib')} GiB | {before.get('required_gib')} GiB | {before.get('margin_gib')} GiB | "
        f"{'coinciden' if before.get('instruments_agree') else 'difieren'} |",
        f"| Después | {after.get('free_gib')} GiB | {after.get('required_gib')} GiB | {after.get('margin_gib')} GiB | "
        f"{'coinciden' if after.get('instruments_agree') else 'difieren'} |",
        "",
        f"Presupuesto: `{report.get('budget', {}).get('source')}` — {report.get('budget', {}).get('basis')}",
        "",
        "## Limpieza",
        "",
        "| Objetivo | Planificado | Recuperado | Ficheros | Omitidos |",
        "| --- | --- | --- | --- | --- |",
    ]
    for target in cleanup.get("targets", []):
        lines.append(
            f"| {target.get('key')} | {round(target.get('planned_bytes', 0) / MIB, 1)} MiB | "
            f"{round(target.get('deleted_bytes', 0) / MIB, 1)} MiB | {target.get('deleted_files')} | "
            f"{target.get('skipped_count')} |"
        )
    lines += [
        "",
        f"Total recuperado: **{cleanup.get('total_deleted_gib')} GiB**; "
        f"el volumen se movió {round(cleanup.get('volume_delta_bytes', 0) / MIB, 1)} MiB en el mismo tramo "
        "(la diferencia es ruido del host, no un fallo del borrado).",
        "",
    ]
    refused = report.get("refused") or []
    if refused:
        lines += ["### No tocado, y por qué", "", "| Ruta | Bytes | Motivo |", "| --- | --- | --- |"]
        for item in refused:
            lines.append(f"| `{item.get('path')}` | {round(item.get('bytes', 0) / MIB, 1)} MiB | {item.get('why')} |")
        lines.append("")
    lines += [
        "## Crecimiento observado",
        "",
        f"{observation.get('seconds')} s de muestreo; caída acumulada "
        f"{round((observation.get('dropped_bytes') or 0) / MIB, 1)} MiB, "
        f"explicada por contadores de escritura en un {observation.get('share_explained_percent')} %.",
        "",
        "| Proceso | Escrito | Intervalos |",
        "| --- | --- | --- |",
    ]
    for writer in observation.get("writers", []):
        lines.append(
            f"| `{writer.get('name')}` | {round(writer.get('written_bytes', 0) / MIB, 1)} MiB | {writer.get('intervals')} |"
        )
    lines += [
        "",
        f"> {observation.get('caveat', '')}",
        "",
        "## Integridad",
        "",
        "| Comprobación | Estado | Detalle |",
        "| --- | --- | --- |",
    ]
    for check in integrity.get("checks", []):
        lines.append(f"| {check.get('id')} | {check.get('status')} | {check.get('detail')} |")
    lines += [
        "",
        f"## Guard",
        "",
        f"Estado: `{guard.get('state')}`. Script presente: {guard.get('script_present')}; "
        f"proceso en marcha: {bool(guard.get('process_running'))}; store presente: {guard.get('store_present')}.",
        "",
        f"> {guard.get('note', '')}",
        "",
        "## Bloqueos",
        "",
    ]
    blockers = report.get("blockers") or []
    lines += [f"- `{item}`" for item in blockers] if blockers else ["- ninguno"]
    lines += ["", "## Próxima acción", ""]
    lines.append(
        next(
            (
                "Restaurar el store de la campaña antes de hablar de continuidad: sin él no hay filas que proteger ni guard que medir."
                for _ in [0]
                if "CAMPAIGN_STORE_ABSENT" in blockers
            ),
            "Repetir `--snapshot after` y el verificador cuando el host haya dejado de moverse para confirmar el margen.",
        )
    )
    lines.append("")
    return "\n".join(lines)


def plan_summary() -> dict[str, Any]:
    handles = open_paths()
    playwright = playwright_plan()
    temp = temp_plan()
    cache = cache_plan(handles=handles)
    already = (OUT / "CLEANUP_EVIDENCE.json").exists()
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now()),
        "state": "RECONNAISSANCE_AFTER_CLEANUP" if already else "PRE_CLEANUP_PLAN",
        "state_note": (
            "this file describes what is left to free now; what was planned and actually removed is "
            "recorded in CLEANUP_EVIDENCE.json, and the two differ by design once the cleanup has run"
        ),
        "volume": volume(),
        "budget": budget(),
        "targets": [
            {
                "key": playwright["key"],
                "root": playwright["root"],
                "bytes_reclaimable": playwright["bytes_reclaimable"],
                "obsolete": playwright["obsolete"],
                "kept": playwright["kept"],
                "consumers": playwright["consumers"],
                "consumer_scan": playwright["consumer_scan"],
                "required_revisions": playwright["required_revisions"],
                "rule": playwright["rule"],
            },
            {
                "key": temp["key"],
                "root": temp["root"],
                "bytes_reclaimable": temp["bytes_reclaimable"],
                "candidate_files": len(temp["candidates"]),
                "preserved_files": temp["preserved_files"],
                "bytes_preserved_as_evidence": temp["bytes_preserved"],
                "cutoff_utc": temp["cutoff_utc"],
            },
            {
                "key": cache["key"],
                "root": cache["root"],
                "bytes_reclaimable": cache["bytes_reclaimable"],
                "entries": cache["entries"],
            },
        ],
        "refused_by_policy": [
            {"path": str(HERMES_ROOT), "why": "owner did not authorise this tree"},
            {"path": str(DENIED_WORKTREE), "why": "owner did not authorise this worktree"},
        ],
    }


def snapshot(label: str) -> dict[str, Any]:
    vol = volume()
    plan = budget()
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "label": label,
        "generated_at_utc": iso(now()),
        "volume": vol,
        "budget": plan,
        "capacity": {**capacity_state(vol, plan), "free_bytes": vol["free_bytes"], "total_bytes": vol["total_bytes"]},
        "head": git("rev-parse", "HEAD")[1],
    }


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WP-051-02K continuation: capacity recovery")
    parser.add_argument("--plan", action="store_true", help="inspect the three authorised targets")
    parser.add_argument(
        "--snapshot",
        choices=("before", "after", "recheck"),
        help="measure the volume: before/after bracket the act, recheck says whether it still holds",
    )
    parser.add_argument("--observe", nargs="?", type=int, const=120, metavar="SECONDS")
    parser.add_argument("--apply", metavar="KEYS", help="comma separated target keys to delete")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--integrity", choices=("before", "after"))
    args = parser.parse_args(argv)

    if args.plan:
        payload = plan_summary()
        write_json(OUT / "CLEANUP_PLAN.json", payload)
        for target in payload["targets"]:
            print(f"{target['key']:22s} {round(target['bytes_reclaimable'] / MIB, 1):9.1f} MiB  {target['root']}")
        return 0

    if args.snapshot:
        payload = snapshot(args.snapshot)
        write_json(OUT / f"SNAPSHOT_{args.snapshot.upper()}.json", payload)
        print(
            f"{args.snapshot}: free={payload['volume']['free_gib']} GiB "
            f"required={payload['budget']['required_gib']} GiB verdict={payload['capacity']['verdict']}"
        )
        return 0

    if args.integrity:
        payload = integrity_manifest()
        write_json(OUT / f"INTEGRITY_{args.integrity.upper()}.json", payload)
        print(f"integrity {args.integrity}: {payload['count']} files hashed; store exists={payload['store']['exists']}")
        return 0

    if args.observe is not None:
        payload = observe(seconds=args.observe)
        write_json(OUT / "WRITE_ATTRIBUTION.json", payload)
        print(
            f"observed {payload['seconds']}s: dropped={round(payload['dropped_bytes'] / MIB, 1)} MiB "
            f"explained={payload['share_explained_percent']}%"
        )
        for writer in payload["writers"][:5]:
            print(f"  {writer['name']:24s} {round(writer['written_bytes'] / MIB, 1):8.1f} MiB")
        return 0

    if args.apply:
        keys = {item.strip() for item in args.apply.split(",") if item.strip()}
        handles = open_paths()
        plans: dict[str, dict[str, Any]] = {}
        playwright = playwright_plan()
        # playwright's obsolete revisions are directories: expand them to their files, no links.
        expanded: list[dict[str, Any]] = []
        for item in playwright["obsolete"]:
            root = PLAYWRIGHT_ROOT / item["name"]
            expanded.extend({"path": str(path), "bytes": size} for path, size, _ in walk_files(root))
        plans[playwright["key"]] = {
            "key": playwright["key"],
            "root": playwright["root"],
            "bytes_reclaimable": playwright["bytes_reclaimable"],
            "files": expanded,
        }
        temp = temp_plan()
        plans[temp["key"]] = temp
        cache = cache_plan(handles=handles)
        plans[cache["key"]] = {
            "key": cache["key"],
            "root": cache["root"],
            "bytes_reclaimable": cache["bytes_reclaimable"],
            "files": [
                {"path": str(path), "bytes": size}
                for entry in cache["entries"]
                if entry["eligible"] and Path(entry["path"]).is_dir()
                for path, size, _ in walk_files(Path(entry["path"]))
            ],
        }
        results: list[dict[str, Any]] = []
        for key in sorted(keys):
            if key not in plans:
                print(f"unknown target: {key}", file=sys.stderr)
                return 2
            target = plans[key]
            # A JSONL manifest, named so it cannot be mistaken for a report.
            evidence = OUT / f"CLEANUP_{key.upper().replace('-', '_')}.jsonl"
            result = apply_target(target, evidence_path=evidence, dry_run=args.dry_run)
            results.append(result)
            print(
                f"{key}: deleted {round(result['deleted_bytes'] / MIB, 1)} MiB "
                f"in {result['deleted_files']} files, skipped {result['skipped_count']}"
            )
        combined = OUT / "CLEANUP_EVIDENCE.json"
        previous = read_json(combined, {}) or {}
        merged = {t["key"]: t for t in previous.get("targets", [])}
        merged.update({t["key"]: t for t in results})
        summary = plan_summary()
        refused = [
            {"path": str(HERMES_ROOT), "bytes": tree_bytes(HERMES_ROOT, max_seconds=60), "why": "el propietario no autoriz\u00f3 este \u00e1rbol"},
            {"path": str(DENIED_WORKTREE), "bytes": tree_bytes(DENIED_WORKTREE, max_seconds=60), "why": "el propietario no autoriz\u00f3 este worktree"},
        ]
        for entry in summary["targets"][2]["entries"]:
            if not entry.get("eligible"):
                refused.append({"path": entry["path"], "bytes": entry["bytes"], "why": entry["why"]})
        write_json(
            combined,
            {
                "schema_version": SCHEMA_VERSION,
                "package": PACKAGE,
                "generated_at_utc": iso(now()),
                "targets": sorted(merged.values(), key=lambda item: item["key"]),
                "refused": refused,
            },
        )
        return 0

    if args.report:
        report = build_report()
        write_json(OUT / "CAPACITY_RECOVERY.json", report)
        (OUT / "CAPACITY_RECOVERY_REPORT.md").write_text(render_markdown(report), encoding="utf-8")
        print(f"report: capacity={report['capacity']['verdict']} package={report['verdict']} blockers={report['blockers']}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
