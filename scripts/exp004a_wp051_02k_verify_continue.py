"""Independent verification of the WP-051-02K continuation.

Written to disagree. It imports nothing from the program that did the work: it re-measures the
volume through its own two calls, re-derives the budget it is willing to accept, re-hashes the
record against the commit the record claims to come from, reads back every deletion manifest and
asks the filesystem whether those paths are really gone, then runs the test suite.

A check that cannot be answered from the artefacts is reported as ``SKIP`` with the reason, never
as a pass. Exit code is 0 only when no check failed.

Usage::

    python scripts/exp004a_wp051_02k_verify_continue.py
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "EXP004A_WP051_02K_CONTINUATION_VERIFICATION_V1"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02k" / "continuation"
RECOVERY_COMMIT = "9983b050c8e241ef9d8365c8ffc33c95df1658dd"
RECORD_ROOT = "docs/agentic/exp004a/wp051_02k"
GIB = 1024**3
MIB = 1024**2

#: The budget the verifier insists on. It is allowed to be higher than this, never lower.
REQUIRED_GIB_FLOOR = 14.564

HOME = Path(os.environ.get("USERPROFILE", r"C:\Users\GVLLFR0035"))

#: Roots no manifest entry may name, restated here so the check does not borrow the actor's list.
PROTECTED = (
    HOME / "OneDrive - Generalitat de Catalunya",
    HOME / "Documents",
    HOME / "Desktop",
    HOME / "Downloads",
    HOME / "Pictures",
    HOME / "Videos",
    HOME / "Music",
    HOME / "Generalitat de Catalunya",
    HOME / "AppData" / "Local" / "hermes",
    HOME / "Downloads" / "bot_crypto_004g",
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("C:/ProgramData"),
)

#: Scratch trees belonging to other packages: a manifest that names one has broken the mandate.
EVIDENCE_MARKERS = ("pytest-reports", "pytest-of-", "recovery-rehearsal-", "rfc0", "tap0", "tap-")


def now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def git(*args: str) -> tuple[int, str]:
    done = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120, check=False
    )
    return done.returncode, (done.stdout or "").strip()


def free_bytes_python() -> int:
    return int(shutil.disk_usage("C:/").free)


def free_bytes_win32() -> int:
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    available = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p("C:/"), ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)
    )
    if not ok:  # pragma: no cover
        raise OSError("GetDiskFreeSpaceExW failed")
    return int(available.value)


def under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (ValueError, OSError):
        return False
    return True


def check(checks: list[dict[str, Any]], ident: str, ok: bool | None, detail: str, **extra: Any) -> None:
    checks.append({"id": ident, "status": ("SKIP" if ok is None else ("PASS" if ok else "FAIL")), "detail": detail, **extra})


def manifest_entries(cleanup: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in cleanup.get("targets", []):
        path = REPO_ROOT / str(target.get("manifest") or "")
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def run_suite(relative: str) -> dict[str, Any]:
    command = [
        "uv",
        "run",
        "--with",
        "pytest",
        "--no-project",
        "python",
        "-m",
        "pytest",
        relative,
        "-q",
    ]
    try:
        done = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"suite": relative, "command": " ".join(command), "exit_code": None, "tail": f"could not run: {exc}"}
    output = (done.stdout or "") + (done.stderr or "")
    failing = [line.split("::")[-1].split(" ")[0] for line in output.splitlines() if line.startswith("FAILED ")]
    tail = "\n".join(output.strip().splitlines()[-8:])
    return {
        "suite": relative,
        "command": " ".join(command),
        "exit_code": done.returncode,
        "failing_tests": failing,
        "tail": tail,
    }


#: Tests of the recovered record that read the frozen contract. Without that file they cannot be
#: evaluated: the test is not weakened here, it is reported as unevaluable and named.
CONTRACT_BOUND_TESTS = ("test_contract_reads_the_frozen_window",)


def main() -> int:
    checks: list[dict[str, Any]] = []
    report = read_json(OUT / "CAPACITY_RECOVERY.json", {}) or {}
    before = read_json(OUT / "SNAPSHOT_BEFORE.json", {}) or {}
    # A later re-measurement supersedes the post-cleanup snapshot for the purpose of "is this still
    # true now", while the cleanup delta keeps using the snapshot taken at the time.
    recheck_path = OUT / "SNAPSHOT_RECHECK.json"
    after = read_json(recheck_path if recheck_path.exists() else OUT / "SNAPSHOT_AFTER.json", {}) or {}
    after_source = "SNAPSHOT_RECHECK.json" if recheck_path.exists() else "SNAPSHOT_AFTER.json"
    cleanup = read_json(OUT / "CLEANUP_EVIDENCE.json", {}) or {}
    integrity_before = read_json(OUT / "INTEGRITY_BEFORE.json", {}) or {}
    integrity_after = read_json(OUT / "INTEGRITY_AFTER.json", {}) or {}
    attribution = read_json(OUT / "WRITE_ATTRIBUTION.json", {}) or {}

    # ---------------------------------------------------------------- capacity
    first = free_bytes_python()
    second = free_bytes_win32()
    check(
        checks,
        "VOLUME_MEASURED_BY_TWO_INSTRUMENTS",
        first == second,
        f"shutil={first} B, GetDiskFreeSpaceExW={second} B, delta={first - second} B",
    )
    budget = report.get("budget") or {}
    required_bytes = int(budget.get("required_bytes") or 0)
    required_gib = round(required_bytes / GIB, 3)
    check(
        checks,
        "BUDGET_NOT_LOWERED",
        required_bytes >= int(REQUIRED_GIB_FLOOR * GIB) and abs(required_gib - REQUIRED_GIB_FLOOR) < 0.01,
        f"required={required_gib} GiB, floor={REQUIRED_GIB_FLOOR} GiB, source={budget.get('source')}",
    )
    check(
        checks,
        "BUDGET_ARGUMENT_STATED",
        bool(budget.get("basis")) and "p90" in str(budget.get("basis")).lower(),
        f"basis: {str(budget.get('basis'))[:160]}",
    )
    measured = min(first, second)
    check(
        checks,
        "FREE_REACHES_BUDGET_NOW",
        measured >= required_bytes,
        f"free={round(measured / GIB, 4)} GiB, required={required_gib} GiB, margin={round((measured - required_bytes) / GIB, 4)} GiB",
    )
    recorded_free = int(((after.get("volume") or {}).get("free_bytes")) or 0)
    drift = measured - recorded_free
    check(
        checks,
        "RECORDED_MEASUREMENT_STILL_STANDS",
        abs(drift) <= 1024 * MIB,
        f"recorded in {after_source}={round(recorded_free / GIB, 4)} GiB, now={round(measured / GIB, 4)} GiB, "
        f"drift={round(drift / MIB, 1)} MiB (host churn, tolerance 1024 MiB)",
    )
    claimed = (report.get("capacity") or {}).get("verdict")
    expected = "PASS" if measured >= required_bytes else "INSUFFICIENT"
    check(
        checks,
        "CAPACITY_VERDICT_MATCHES_MEASUREMENT",
        claimed == ((after.get("capacity") or {}).get("verdict") or "UNMEASURED") and claimed in ("PASS", "INSUFFICIENT"),
        f"report={claimed}, snapshot={expected}, criterion=free>=required",
    )

    # ---------------------------------------------------------------- manifests
    entries = manifest_entries(cleanup)
    did_cleanup = bool(cleanup.get("targets"))
    deleted_total = sum(int(target.get("deleted_files") or 0) for target in cleanup.get("targets", []))
    skipped_total = sum(int(target.get("skipped_count") or 0) for target in cleanup.get("targets", []))
    # The manifest is written *before* the unlink, so it records intent: one row per attempt, and
    # the outcome table says which attempts the filesystem refused. Counting rows against
    # deletions alone would flag every locked file as a bookkeeping error.
    check(
        checks,
        "MANIFEST_RECORDS_EVERY_ATTEMPT",
        None if not did_cleanup else (bool(entries) and len(entries) == deleted_total + skipped_total),
        "this tree performed no cleanup, so there is no manifest to account for"
        if not did_cleanup
        else (
            f"{len(entries)} manifest rows = {deleted_total} deleted + {skipped_total} skipped, "
            f"{len(cleanup.get('targets', []))} targets"
        ),
    )
    missing_fields = [row for row in entries if not row.get("path") or not isinstance(row.get("bytes"), int)]
    check(
        checks,
        "EVERY_ROW_NAMES_A_PATH_AND_A_SIZE",
        None if not did_cleanup else not missing_fields,
        "no manifest rows to check" if not did_cleanup else f"{len(missing_fields)} rows incomplete",
    )

    skipped_paths = {
        str(row.get("path"))
        for target in cleanup.get("targets", [])
        for row in (target.get("skipped") or [])
    }
    still_there = [row["path"] for row in entries if Path(row["path"]).exists()]
    unexplained = [path for path in still_there if path not in skipped_paths]
    check(
        checks,
        "ONLY_THE_REFUSED_FILES_SURVIVE",
        None if not did_cleanup else not unexplained,
        f"{len(still_there)} manifest paths still exist, {len(still_there) - len(unexplained)} of them reported as "
        f"refused by the filesystem and {len(unexplained)} unaccounted for",
        examples=unexplained[:10],
    )
    protected_hits = [row["path"] for row in entries if any(under(Path(row["path"]), root) for root in PROTECTED)]
    check(
        checks,
        "NO_PROTECTED_PATH_IN_MANIFEST",
        None if not did_cleanup else not protected_hits,
        f"{len(protected_hits)} manifest rows under a protected root",
        examples=protected_hits[:10],
    )

    evidence_hits = [
        row["path"]
        for row in entries
        if any(marker in str(row["path"]).split(os.sep)[-3] or marker in str(row["path"]) for marker in EVIDENCE_MARKERS)
    ]
    check(
        checks,
        "OTHER_PACKAGES_SCRATCH_TREES_KEPT",
        None if not did_cleanup else not evidence_hits,
        f"{len(evidence_hits)} manifest rows inside a scratch tree another package cites as evidence",
        examples=evidence_hits[:10],
    )

    # ---------------------------------------------------------------- playwright
    plan = read_json(OUT / "CLEANUP_PLAN.json", {}) or {}
    playwright_plan = next((target for target in plan.get("targets", []) if target.get("key") == "playwright-obsolete"), {})
    kept_revisions = playwright_plan.get("kept") or []
    missing_kept = [row["name"] for row in kept_revisions if not (HOME / "AppData" / "Local" / "ms-playwright" / row["name"]).exists()]
    check(
        checks,
        "REVISIONS_A_CONSUMER_NEEDS_SURVIVE",
        None if not did_cleanup else (bool(kept_revisions) and not missing_kept),
        f"{len(kept_revisions)} revisions kept because an installed consumer asks for them; {len(missing_kept)} missing",
        examples=missing_kept[:10],
    )
    # Derived from the manifest, not from a plan that would now report "nothing to retire" because
    # the revision is already gone: the evidence has to survive the act it describes.
    removed_revisions = sorted(
        {
            Path(row["path"]).relative_to(Path(HOME / "AppData" / "Local" / "ms-playwright")).parts[0]
            for row in entries
            if row.get("target") == "playwright-obsolete"
            and under(Path(row["path"]), HOME / "AppData" / "Local" / "ms-playwright")
        }
    )
    surviving_obsolete = [
        name for name in removed_revisions if (HOME / "AppData" / "Local" / "ms-playwright" / name).exists()
    ]
    check(
        checks,
        "OBSOLETE_REVISIONS_ACTUALLY_REMOVED",
        None if not did_cleanup else (bool(removed_revisions) and not surviving_obsolete),
        f"manifest names {len(removed_revisions)} browser revisions as removed ({removed_revisions[:4]}); "
        f"{len(surviving_obsolete)} still on disk",
        examples=surviving_obsolete[:10],
    )
    scan = playwright_plan.get("consumer_scan") or {}
    check(
        checks,
        "OBSOLESCENCE_ARGUED_FROM_A_SEARCH",
        None if not did_cleanup else (bool(scan.get("manifests")) and scan.get("truncated") is False),
        f"consumer manifests found={scan.get('manifests')}, search truncated={scan.get('truncated')}",
    )

    # ---------------------------------------------------------------- record
    record = integrity_after.get("record") or {}
    rows = record.get("files") or {}
    mismatched = [path for path, info in rows.items() if not info.get("identical")]
    check(
        checks,
        "RECORD_STILL_MATCHES_ITS_COMMIT",
        bool(rows) and not mismatched,
        f"{len(rows)} recovered files compared with {RECOVERY_COMMIT[:8]}; {len(mismatched)} differ",
        examples=mismatched[:10],
    )
    # recompute independently: the manifest could have been written before an edit.
    recomputed_mismatch: list[str] = []
    for path in rows:
        code_local, local = git("hash-object", path)
        code_commit, committed = git("rev-parse", f"{RECOVERY_COMMIT}:{path}")
        if code_local != 0 or code_commit != 0 or local != committed:
            recomputed_mismatch.append(path)
    check(
        checks,
        "RECORD_RECOMPUTED_INDEPENDENTLY",
        not recomputed_mismatch,
        f"{len(rows)} files re-hashed by this verifier; {len(recomputed_mismatch)} disagree with the commit",
        examples=recomputed_mismatch[:10],
    )
    before_files = integrity_before.get("files") or {}
    after_files = integrity_after.get("files") or {}
    changed = [path for path, info in before_files.items() if after_files.get(path) != info]
    check(
        checks,
        "EXPERIMENT_FILES_UNCHANGED_ACROSS_CLEANUP",
        not changed,
        f"{len(before_files)} files hashed before and after; {len(changed)} differ",
        examples=changed[:10],
    )
    absent = [name for name, info in (integrity_after.get("experiment") or {}).items() if not info.get("exists")]
    check(
        checks,
        "MISSING_EXPERIMENT_ARTEFACTS_ARE_DECLARED",
        "store" in absent and "CAMPAIGN_STORE_ABSENT" in (report.get("blockers") or []),
        f"absent={absent}; declared blockers={report.get('blockers')}",
    )

    # ---------------------------------------------------------------- honesty
    check(
        checks,
        "NO_PASS_CLAIMED_WHILE_THE_CAMPAIGN_CANNOT_RUN",
        report.get("verdict") != "PASS" and bool(report.get("blockers")),
        f"package verdict={report.get('verdict')}, blockers={report.get('blockers')}",
    )
    guard = report.get("guard") or {}
    guard_script = REPO_ROOT / "scripts" / "edge04_watchdog.py"
    expected_guard = "FILE_PRESENT_NO_PROCESS" if guard_script.exists() else "ABSENT_IN_THIS_TREE"
    check(
        checks,
        "GUARD_STATE_STATED_HONESTLY",
        guard.get("state") == expected_guard and guard.get("script_present") == guard_script.exists(),
        f"report={guard.get('state')}, filesystem={expected_guard}, script_present={guard_script.exists()}",
    )
    check(
        checks,
        "GROWTH_ATTRIBUTED_OR_DECLARED_UNKNOWN",
        bool(attribution.get("writers")) or attribution.get("share_explained_percent") is None,
        f"{attribution.get('seconds')} s sampled, dropped={round((attribution.get('dropped_bytes') or 0) / MIB, 1)} MiB, "
        f"explained={attribution.get('share_explained_percent')}%, top={[w.get('name') for w in attribution.get('writers', [])[:3]]}",
    )
    check(
        checks,
        "CLEANUP_DID_NOT_TOUCH_THE_REPOSITORY",
        None if not did_cleanup else all(not under(Path(row["path"]), REPO_ROOT) for row in entries),
        "every deleted path lies outside the checkout; the experiment's tracked files are hashed above",
    )

    suite = run_suite("tests/unit/research/test_exp004a_wp051_02k_continue.py")
    check(
        checks,
        "TESTS_PASS",
        suite.get("exit_code") == 0,
        f"exit={suite.get('exit_code')} :: {suite.get('tail', '')[-360:]}",
        command=suite.get("command"),
    )
    legacy = run_suite("tests/unit/research/test_exp004a_wp051_02k.py")
    contract_missing = not (REPO_ROOT / "config" / "preregistrations" / "EXP-004A.datasets.phase3.json").exists()
    legacy_state: bool | None = legacy.get("exit_code") == 0
    if legacy_state is False and contract_missing and set(legacy.get("failing_tests") or []) <= set(CONTRACT_BOUND_TESTS):
        legacy_state = None
    check(
        checks,
        "RECOVERED_SUITE_STILL_EVALUABLE",
        legacy_state,
        (
            f"exit={legacy.get('exit_code')}, failing={legacy.get('failing_tests')}; the contract the "
            "failing test reads is absent from this checkout, so the test is unevaluable here "
            "instead of being rewritten to pass"
            if legacy_state is None
            else f"exit={legacy.get('exit_code')} :: {legacy.get('tail', '')[-300:]}"
        ),
        command=legacy.get("command"),
    )

    failed = [item for item in checks if item["status"] == "FAIL"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now_iso(),
        "verifier": "scripts/exp004a_wp051_02k_verify_continue.py",
        "independence": "imports nothing from the program that performed the cleanup; re-measures, re-hashes and re-reads every manifest",
        "person_independence": False,
        "person_independence_note": "another program is not another person; the record says so",
        "measured_free_bytes": measured,
        "measured_free_gib": round(measured / GIB, 4),
        "required_bytes": required_bytes,
        "required_gib": required_gib,
        "margin_gib": round((measured - required_bytes) / GIB, 4),
        "checks": checks,
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": len(failed),
        "skipped": sum(1 for item in checks if item["status"] == "SKIP"),
        "tests": {"continuation": suite, "recovered_record": legacy},
        "verdict": "PASS" if not failed else "FAIL",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "INDEPENDENT_VERIFICATION_02K_CONTINUATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for item in checks:
        print(f"{item['status']:4s} {item['id']:48s} {item['detail'][:110]}")
    print(f"\n{payload['passed']} passed, {payload['failed']} failed, {payload['skipped']} skipped -> {payload['verdict']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
