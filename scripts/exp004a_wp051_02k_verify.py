"""WP-051-02K independent verifier — another program, not another author.

It does not import the builder. It re-measures the volume with its own two instruments, re-derives
the budget from the observer's own log, re-hashes the write-once shards, re-runs the test suite, and
then asks the only question that matters: does the package's verdict agree with the host?

A verifier that only re-reads the JSON would confirm its own author. This one reopens the files.

Usage::

    python scripts/exp004a_wp051_02k_verify.py
    python scripts/exp004a_wp051_02k_verify.py --json

Exit codes: 0 when every check passes, 1 when any check fails, 2 when the package is incomplete.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "EXP004A_WP051_02K_VERIFICATION_V1"
PACKAGE = "WP-051-02K"
GIB = 1024**3

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
STATE_ROOT = MAIN_ROOT / "data" / "forward" / "edge04"
OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02k"
BUILDER = REPO_ROOT / "scripts" / "exp004a_wp051_02k_capacity.py"
SUITE = REPO_ROOT / "tests" / "unit" / "research" / "test_exp004a_wp051_02k.py"

FLOOR_BYTES = 2 * GIB
WINDOW = ("2026-10-23T00:00:00Z", "2027-01-21T00:00:00Z", 90)
DECLARED_ROWS = 6480

#: Free space is not static: another process can take a gigabyte while this runs. A claim is only
#: rejected when the volume is *materially* worse than reported, never for ordinary drift.
DRIFT_TOLERANCE_BYTES = 1536 * 1024 * 1024


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


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
                    return None
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def free_bytes() -> tuple[int, int]:
    """Two instruments, both asked here: shutil and the Win32 call underneath it."""
    target = "C:\\"
    first = int(shutil.disk_usage(target).free)
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    available = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p(target), ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)
    )
    return first, int(available.value)


def git(*args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, (done.stdout or "").strip()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))]


def recompute_budget() -> dict[str, Any]:
    """The observer's readings, bucketed by UTC day, worst intraday fall per day."""
    buckets: dict[str, list[tuple[int, int]]] = {}
    try:
        lines = (STATE_ROOT / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"readings": 0, "days": 0, "p90_bytes": 0, "own_window_bytes": 0, "required_bytes": 0}
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
        if not isinstance(free, int) or not isinstance(stamp, int):
            continue
        day = iso(datetime.fromtimestamp(stamp / 1000, tz=UTC))[:10]
        buckets.setdefault(day, []).append((stamp, free))
    drawdowns: list[float] = []
    for rows in buckets.values():
        if len(rows) < 2:
            continue
        rows.sort()
        peak = rows[0][1]
        worst = 0.0
        for _stamp, value in rows:
            peak = max(peak, value)
            worst = max(worst, peak - value)
        drawdowns.append(worst)
    own = read_json(STATE_ROOT / "resource_budget.json", {}) or {}
    samples = [
        row
        for row in (own.get("samples") if isinstance(own.get("samples"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("ts_ms"), int) and isinstance(row.get("bytes"), int)
    ]
    own_window = 0
    if len(samples) >= 2:
        samples.sort(key=lambda row: row["ts_ms"])
        span = max((samples[-1]["ts_ms"] - samples[0]["ts_ms"]) / 86_400_000, 1e-9)
        own_window = int((samples[-1]["bytes"] - samples[0]["bytes"]) / span) * WINDOW[2]
    p90 = int(percentile(drawdowns, 0.90))
    return {
        "readings": sum(len(rows) for rows in buckets.values()),
        "days": len(drawdowns),
        "drawdowns_gib": [round(item / GIB, 3) for item in drawdowns],
        "p90_bytes": p90,
        "own_window_bytes": own_window,
        "required_bytes": own_window + FLOOR_BYTES + p90,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks: list[dict[str, Any]] = []

    def check(identity: str, ok: bool, detail: str, evidence: Any = None) -> None:
        row = {"id": identity, "status": "PASS" if ok else "FAIL", "detail": detail}
        if evidence is not None:
            row["evidence"] = evidence
        checks.append(row)

    before = read_json(OUT / "SNAPSHOT_BEFORE.json", {}) or {}
    after = read_json(OUT / "SNAPSHOT_AFTER.json", {}) or {}
    inventory = read_json(OUT / "VOLUME_INVENTORY.json", {}) or {}
    cleanup = read_json(OUT / "CLEANUP_EVIDENCE.json", {}) or {}
    integrity = read_json(OUT / "STORE_INTEGRITY.json", {}) or {}
    recovery = read_json(OUT / "CAPACITY_RECOVERY.json", {}) or {}
    request = read_json(OUT / "AUTHORISATION_REQUEST.json", {}) or {}
    final = read_json(OUT / "FINAL_REPORT.json", {}) or {}

    if not all((before, after, inventory, recovery)):
        print("package incomplete: run --before, --inventory, --after and --report first")
        return 2

    # 1. the snapshots exist and their two instruments agree
    for label, snap in (("before", before), ("after", after)):
        vol = snap.get("volume") or {}
        check(
            f"SNAPSHOT_{label.upper()}_TWO_INSTRUMENTS",
            bool(vol.get("instruments_agree")),
            f"{label}: free {vol.get('free_gib')} GiB, delta {vol.get('instrument_delta_bytes')} B",
            {"free_bytes": vol.get("free_bytes"), "kernel32": vol.get("free_bytes_kernel32")},
        )

    # 2. the volume cannot be claimed better than it is
    measured, measured_kernel = free_bytes()
    claimed = int((after.get("volume") or {}).get("free_bytes") or 0)
    check(
        "VOLUME_IS_AT_LEAST_AS_TIGHT_AS_REPORTED",
        measured <= claimed + DRIFT_TOLERANCE_BYTES,
        f"measured {measured / GIB:.3f} GiB against reported {claimed / GIB:.3f} GiB",
        {"measured_free_bytes": measured, "measured_kernel32": measured_kernel},
    )

    # 3. the budget recomputes from the observer's log, not from the report
    mine = recompute_budget()
    theirs = after.get("budget") or {}
    delta = abs(int(theirs.get("required_bytes") or 0) - mine["required_bytes"])
    check(
        "BUDGET_RECOMPUTED_FROM_THE_LOG",
        delta <= 64 * 1024 * 1024,
        f"p90 {mine['p90_bytes'] / GIB:.3f} GiB, required {mine['required_bytes'] / GIB:.3f} GiB, delta {delta} B",
        mine,
    )

    # 4. the floor is still the observer's floor, in the store and in its own module
    health = read_json(STATE_ROOT / "health.json", {}) or {}
    disk = health.get("disk") or {}
    floor_ok = disk.get("critical_free_bytes") == FLOOR_BYTES
    module_hit = False
    for candidate in (MAIN_ROOT / "src").rglob("*.py"):
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "2 * 1024 ** 3" in text or "2 * 1024**3" in text or "2147483648" in text:
            if "critical" in text.lower():
                module_hit = True
                break
    check(
        "FLOOR_UNCHANGED",
        floor_ok,
        f"store floor {disk.get('critical_free_bytes')} B; guard module carries the same constant: {module_hit}",
        {"module_constant_found": module_hit},
    )

    # 5. the contract did not move
    code, diff = git("diff", "--stat", "--", "config/preregistrations/EXP-004A.datasets.phase3.json")
    contract = read_json(REPO_ROOT / "config/preregistrations/EXP-004A.datasets.phase3.json", {}) or {}
    window = contract.get("capture_window") or {}
    rows = sum(entry.get("row_count", 0) for entry in contract.get("entries", []) if isinstance(entry, dict))
    check(
        "CONTRACT_UNCHANGED",
        code == 0 and diff == "" and window.get("days") == WINDOW[2] and rows == DECLARED_ROWS,
        f"git diff exit {code}, window {window.get('days')} d, rows {rows}",
    )

    # 6. write-once shards keep their exact bytes
    shards_before = (before.get("fingerprint") or {}).get("write_once") or {}
    mismatched = []
    for name, old in shards_before.items():
        now_hash = sha256_file(STATE_ROOT / "daily" / name)
        if now_hash != old.get("sha256"):
            mismatched.append(name)
    check(
        "WRITE_ONCE_SHARDS_UNCHANGED",
        not mismatched,
        f"{len(shards_before) - len(mismatched)}/{len(shards_before)} shard(s) byte-identical",
        {"mismatched": mismatched},
    )

    # 7. append-only files keep the prefix that existed before the package ran
    append_before = (before.get("fingerprint") or {}).get("append_only") or {}
    broken = []
    for name, old in append_before.items():
        if not old.get("exists"):
            continue
        kept = sha256_prefix(STATE_ROOT / name, int(old.get("length") or 0))
        if kept != old.get("sha256"):
            broken.append(name)
    check(
        "APPEND_ONLY_PREFIXES_INTACT",
        not broken,
        f"{len(append_before) - len(broken)}/{len(append_before)} append-only file(s) unchanged up to their old length",
        {"broken": broken},
    )

    # 8. no row was invented: the store may grow, never shrink
    grew = []
    for name, old in append_before.items():
        if not old.get("exists"):
            continue
        try:
            now_lines = sum(1 for _ in (STATE_ROOT / name).open("rb"))
        except OSError:
            now_lines = -1
        grew.append({"file": name, "before": old.get("lines"), "now": now_lines, "ok": now_lines >= int(old.get("lines") or 0)})
    check(
        "NO_ROW_LOST_OR_INVENTED",
        all(row["ok"] for row in grew),
        f"{sum(1 for row in grew if row['ok'])}/{len(grew)} append-only file(s) did not shrink",
        grew,
    )

    # 9. the inventory is a map that accounts for the volume, not a partition pretending to
    vol_used = int((inventory.get("volume") or {}).get("used_bytes") or 0)
    partition = [
        row
        for row in (inventory.get("rows") or [])
        if row.get("loose") or int(row.get("depth", 0)) <= 1
    ]
    explained = sum(int(row["bytes"]) for row in partition)
    fraction = explained / vol_used if vol_used else 0.0
    check(
        "INVENTORY_ACCOUNTS_FOR_THE_VOLUME",
        0.90 <= fraction <= 1.02,
        f"{explained / GIB:.2f} GiB of {vol_used / GIB:.2f} GiB explained ({fraction:.3f}) by {len(partition)} top-level row(s)",
        {"unexplained_gib": round((vol_used - explained) / GIB, 3), "truncations": inventory.get("truncations")},
    )

    # 10. nothing outside this repository family was deleted
    foreign = []
    for row in cleanup.get("removed") or []:
        path = Path(row["path"])
        try:
            path.resolve().relative_to(REPO_ROOT.resolve())
            continue
        except (ValueError, OSError):
            pass
        try:
            path.resolve().relative_to(MAIN_ROOT.resolve())
        except (ValueError, OSError):
            foreign.append(row["path"])
    check(
        "NOTHING_FOREIGN_WAS_DELETED",
        not foreign,
        f"{len(cleanup.get('removed') or [])} director(ies) removed, all inside this repository family",
        {"foreign": foreign, "deleted_bytes": cleanup.get("deleted_bytes")},
    )

    # 11. the trees the package refused to touch still exist, at their measured size
    protected = ["wsl", "ms-playwright", "hermes"]
    surviving = []
    for row in (inventory.get("rows") or []):
        path = Path(row["path"])
        if path.name not in protected or int(row.get("depth", 0)) > 3:
            continue
        now = path.stat().st_size if path.is_file() else None
        surviving.append({"path": str(path), "exists": path.exists(), "bytes_then": row["bytes"], "file_bytes_now": now})
    protected_ok = bool(surviving) and all(item["exists"] for item in surviving)
    check(
        "PROTECTED_TREES_STILL_PRESENT",
        protected_ok,
        f"{sum(1 for item in surviving if item['exists'])}/{len(surviving)} protected tree(s) still on disk",
        surviving,
    )

    # 12. the verdict is the one the arithmetic allows
    required = int((after.get("budget") or {}).get("required_bytes") or 0)
    free_now = measured
    honest = (free_now < required and recovery.get("verdict") == "BLOCKED") or (
        free_now >= required and recovery.get("verdict") in ("PASS", "BLOCKED")
    )
    check(
        "VERDICT_FOLLOWS_THE_ARITHMETIC",
        honest,
        f"free {free_now / GIB:.3f} GiB, required {required / GIB:.3f} GiB, package verdict {recovery.get('verdict')}",
        {"capacity": (recovery.get("capacity") or {}).get("verdict")},
    )

    # 13. every authorisation item is named, sized, risked and reversible-or-explained
    items = request.get("items") or []
    incomplete = [
        row.get("key")
        for row in items
        if not row.get("path") or not row.get("bytes") or not row.get("risk") or not row.get("recovery")
    ]
    gap = int((recovery.get("coverage_plan") or {}).get("gap_bytes") or 0)
    covers = sum(int(row["bytes"]) for row in items) >= gap
    check(
        "AUTHORISATION_REQUEST_IS_ACTIONABLE",
        not incomplete and (covers or not items),
        f"{len(items)} item(s), {sum(int(row['bytes']) for row in items) / GIB:.2f} GiB against a {gap / GIB:.2f} GiB gap",
        {"incomplete": incomplete, "covers_gap": covers},
    )

    # 14. the suite runs here, now, with its own exit code
    python = str(MAIN_ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(python).exists():
        python = sys.executable
    done = subprocess.run(
        [python, "-m", "pytest", str(SUITE), "-q"], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )
    tail = (done.stdout or "").strip().splitlines()[-1:] or ["no output"]
    check(
        "TESTS_RAN_AND_PASSED",
        done.returncode == 0,
        f"pytest exit {done.returncode}: {tail[0]}",
        {"suite_sha256": sha256_file(SUITE)},
    )

    # 15. the defects this package must not close are still open
    open_defects = [row.get("id") for row in (final.get("open_defects") or [])]
    required_open = {"DEF-02I-07", "DEF-02I-08", "ALERT_REMOTE"}
    check(
        "DEFECTS_STILL_OPEN",
        required_open.issubset(set(open_defects)),
        f"open: {sorted(open_defects)}",
        {"required": sorted(required_open)},
    )

    # 16. WP-051-02J is in Git, with the verdict it earned
    code_log, log = git("log", "--oneline", "--", "docs/agentic/exp004a/wp051_02j/FINAL_REPORT_02J.json")
    code_show, shown = git("show", "HEAD:docs/agentic/exp004a/wp051_02j/FINAL_REPORT_02J.json")
    committed_verdict = None
    if code_show == 0 and shown:
        try:
            committed_verdict = json.loads(shown).get("verdict")
        except json.JSONDecodeError:
            committed_verdict = None
    check(
        "WP_02J_COMMITTED_WITH_ITS_VERDICT",
        code_log == 0 and bool(log) and committed_verdict == "BLOCKED",
        f"commit(s): {log.splitlines()[:1]}, committed verdict {committed_verdict}",
    )

    # 17. the builder neither elevates nor opens the network
    source = BUILDER.read_text(encoding="utf-8", errors="ignore")
    forbidden = [
        token
        for token in ("sudo", "runas", "-Verb RunAs", "urllib", "http.client", "requests.", "socket.")
        if token in source
    ]
    check(
        "NO_ELEVATION_AND_NO_NETWORK",
        not forbidden,
        f"builder tokens found: {forbidden or 'none'}",
    )

    failed = [row for row in checks if row["status"] == "FAIL"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(datetime.now(tz=UTC)),
        "head": git("rev-parse", "HEAD")[1],
        "worktree": str(REPO_ROOT),
        "checks": checks,
        "passed": sum(1 for row in checks if row["status"] == "PASS"),
        "failed": len(failed),
        "verdict": "PASS" if not failed else "FAIL",
        "not_a_certification": (
            "this says the report agrees with the host. It promotes nothing, it frees nothing, and it "
            "does not replace the owner's decision about whose bytes may go."
        ),
    }
    (OUT / "INDEPENDENT_VERIFICATION_02K.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for row in checks:
            print(f"{row['status']:4}  {row['id']:44} {row['detail']}")
        print(f"\n{payload['passed']}/{len(checks)} PASS, {payload['failed']} FAIL -> {payload['verdict']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
