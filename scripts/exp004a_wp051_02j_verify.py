"""Independent verifier for WP-051-02J: recompute the recovery claims from bytes.

Shares no code with the builder. It re-measures the candidates, re-derives the lost day from
the forward store, recomputes the capacity budget from the observer's own readings, and — the
part that matters most — re-reads the operating system's notification history to check that the
alert the ledger claims was received is still there.

What it cannot prove it reports as ``UNVERIFIABLE``, never as a pass.

Usage::

    python scripts/exp004a_wp051_02j_verify.py --out docs/agentic/exp004a/wp051_02j \
        --main-root "C:/Users/GVLLFR0035/Downloads/bot freebuff"

Research only: reads files, runs the watchdog and the toast helper in read-only modes.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAIN = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
GIB = 1024**3
MIB = 1024**2
CRITICAL_FREE_BYTES = 2 * GIB
WINDOW_START = "2026-10-23T00:00:00Z"
WINDOW_END = "2027-01-21T00:00:00Z"
WINDOW_DAYS = 90
DECLARED_ROWS = 6480
REQUIRED_FRACTION = 0.9
LAG_BOUND_MS = 120 * 60 * 1000
ASSETS = ("BTC", "ETH", "SOL")
SCHEMA_VERSION = "EXP004A_WP051_02J_VERIFICATION_V1"
TOAST = REPO_ROOT / "scripts" / "edge04_toast.ps1"
WATCHDOG = REPO_ROOT / "scripts" / "edge04_watchdog.py"
CONTRACT = REPO_ROOT / "config" / "preregistrations" / "EXP-004A.datasets.phase3.json"
AUMID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def measure(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def git(cwd: Path, *args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return completed.returncode, completed.stdout.strip()


def check(id_: str, ok: bool | None, detail: str, *, evidence: Any = None) -> dict[str, Any]:
    status = "UNVERIFIABLE" if ok is None else ("PASS" if ok else "FAIL")
    payload = {"id": id_, "status": status, "detail": detail}
    if evidence is not None:
        payload["evidence"] = evidence
    return payload


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_scope(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    problems = []
    owned = []
    for row in diagnosis.get("candidates") or []:
        path = Path(str(row.get("path") or ""))
        if row.get("classification") == "SAFE_OWNED":
            owned.append(str(path))
            if not str(path.resolve()).lower().startswith(str(REPO_ROOT).lower()):
                problems.append(f"{path}: SAFE_OWNED outside this worktree")
                continue
            relative = str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
            code, listing = git(REPO_ROOT, "ls-files", "--", relative)
            if listing.strip():
                problems.append(f"{path}: SAFE_OWNED but tracked by Git")
        if row.get("classification") == "ACTIVE_OR_PROTECTED" and not (
            row.get("processes") or row.get("newest_age_hours") is not None
        ):
            problems.append(f"{path}: ACTIVE_OR_PROTECTED without a reason")
    return [
        check(
            "CLASSIFICATION_IS_CONSERVATIVE",
            not problems,
            "; ".join(problems[:5])
            or f"{len(owned)} SAFE_OWNED path(s), all inside this worktree and untracked",
            evidence={"safe_owned": owned[:20]},
        )
    ]


def check_sizes(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-measure the largest candidates; a tree may grow (it is alive), not shrink silently."""
    problems = []
    measured = 0
    for row in (diagnosis.get("candidates") or [])[:12]:
        path = Path(str(row.get("path") or ""))
        if not path.is_absolute() or not path.exists():
            if row.get("classification") != "SAFE_OWNED" and row.get("bytes"):
                problems.append(f"{path}: reported {row.get('bytes')} bytes but is not there")
            continue
        fresh = measure(path)
        claimed = int(row.get("bytes") or 0)
        measured += 1
        tolerance = max(4 * MIB, int(0.25 * max(claimed, fresh)))
        if abs(fresh - claimed) > tolerance:
            problems.append(f"{path}: {claimed} -> {fresh} (tolerance {tolerance})")
    return [
        check(
            "CANDIDATE_SIZES_RECOMPUTED",
            not problems,
            "; ".join(problems[:5]) or f"{measured} candidate(s) re-measured within tolerance",
        )
    ]


def check_reading_semantics(semantics: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    usage = shutil.disk_usage("C:/")
    kernel = ctypes.windll.kernel32
    freeb = ctypes.c_ulonglong()
    totalb = ctypes.c_ulonglong()
    totalfree = ctypes.c_ulonglong()
    kernel.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p("C:\\"), ctypes.byref(freeb), ctypes.byref(totalb), ctypes.byref(totalfree)
    )
    agreement = abs(int(usage.free) - int(freeb.value))
    zeros = 0
    try:
        for line in (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for key in ("disk", "disk_after"):
                value = (row.get(key) or {}).get("free_bytes")
                if value == 0:
                    zeros += 1
                    break
    except (OSError, json.JSONDecodeError):
        zeros = -1
    reported = int(semantics.get("readings_exactly_zero") or 0)
    ok = agreement <= MIB and zeros == reported and semantics.get("verdict") == "REAL_AVAILABILITY_ZERO"
    return [
        check(
            "READING_SEMANTICS_RECOMPUTED",
            ok,
            f"two OS APIs differ by {agreement} bytes; zeros recomputed {zeros}, reported {reported}",
            evidence={"agreement_bytes": agreement},
        )
    ]


def check_lost_day(lost: dict[str, Any], main_root: Path) -> list[dict[str, Any]]:
    day0 = int(datetime(2026, 10, 23, tzinfo=UTC).timestamp() * 1000)
    day1 = int(datetime(2026, 10, 24, tzinfo=UTC).timestamp() * 1000)
    problems = []
    total_admissible = 0
    for asset in ASSETS:
        path = main_root / "data" / "forward" / "edge03" / "1h" / f"{asset}.jsonl"
        rows = {}
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
        admissible = 0
        for hour in range(24):
            stamp = day0 + hour * 3_600_000
            row = rows.get(stamp)
            if row is None:
                continue
            lag = int(row.get("fetched_at_ms") or 0) - (stamp + 3_600_000)
            if 0 <= lag <= LAG_BOUND_MS:
                admissible += 1
        total_admissible += admissible
        claimed = (lost.get("assets") or {}).get(asset, {})
        if claimed.get("admissible") != admissible:
            problems.append(f"{asset}: report {claimed.get('admissible')}, recomputed {admissible}")
    if lost.get("admissible_rows") != total_admissible:
        problems.append(f"total: report {lost.get('admissible_rows')}, recomputed {total_admissible}")
    if lost.get("declared_rows_for_the_day") != 24 * len(ASSETS):
        problems.append("declared rows for the day are not 72")
    return [
        check(
            "LOST_DAY_RECOMPUTED",
            not problems,
            "; ".join(problems[:5])
            or f"{total_admissible} admissible row(s) of 72 declared, recomputed hour by hour",
        )
    ]


def check_capacity(capacity: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    samples = []
    try:
        for line in (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            reading = row.get("disk_after") or row.get("disk") or {}
            free = reading.get("free_bytes")
            stamp = row.get("started_at_ms")
            if isinstance(free, int) and isinstance(stamp, int):
                samples.append((stamp, free))
    except (OSError, json.JSONDecodeError):
        samples = []
    samples.sort()
    buckets: dict[str, list[int]] = {}
    for stamp, free in samples:
        buckets.setdefault(
            datetime.fromtimestamp(stamp / 1000, tz=UTC).strftime("%Y-%m-%d"), []
        ).append(free)
    drawdowns = []
    for values in buckets.values():
        if len(values) < 2:
            continue
        peak = None
        worst = 0
        for value in values:
            peak = value if peak is None else max(peak, value)
            worst = max(worst, peak - value)
        drawdowns.append(worst)
    if not drawdowns:
        return [check("CAPACITY_ARITHMETIC", None, "no drawdown series in the store")]
    ordered = sorted(drawdowns)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    own = int((capacity.get("own") or {}).get("window_bytes") or 0)
    claimed_p90 = int((capacity.get("drawdown") or {}).get("p90_bytes") or 0)
    required_claimed = int((capacity.get("required") or {}).get("at_p90_bytes") or 0)
    free_now = shutil.disk_usage("C:/").free
    problems = []
    if claimed_p90 != p90:
        problems.append(f"p90 drawdown: report {claimed_p90}, recomputed {p90}")
    if required_claimed != own + CRITICAL_FREE_BYTES + p90:
        problems.append(
            f"required: report {required_claimed}, recomputed {own + CRITICAL_FREE_BYTES + p90}"
        )
    refused = 0
    try:
        refused = sum(
            1
            for line in (state_root / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            if '"DISK_BUDGET_EXCEEDED"' in line
        )
    except OSError:
        refused = -1
    expected_verdict = "SUFFICIENT" if free_now >= required_claimed and not refused else "INSUFFICIENT"
    if capacity.get("verdict") != expected_verdict:
        problems.append(f"verdict {capacity.get('verdict')} contradicts the recomputation {expected_verdict}")
    return [
        check(
            "CAPACITY_ARITHMETIC",
            not problems,
            "; ".join(problems[:5])
            or f"p90 {p90 / GIB:.3f} GiB, required {required_claimed / GIB:.3f} GiB, free now "
            f"{free_now / GIB:.3f} GiB, refusals {refused} -> {expected_verdict}",
        )
    ]


def check_alerts(out: Path, channel_row: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    ledger = []
    try:
        for line in (state_root / "ALERT_LEDGER.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    ledger.append(parsed)
    except (OSError, json.JSONDecodeError):
        ledger = []
    delivered = [row for row in ledger if row.get("receipt")]
    checks: list[dict[str, Any]] = []
    if not delivered:
        checks.append(check("ALERT_HAS_A_RECEIPT", False, "the ledger holds no delivered alert"))
    else:
        latest = delivered[-1]
        tag = str(latest.get("alert_id") or "")
        code, out_text = -1, ""
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOAST),
                 "-Tag", tag, "-Mode", "history"],
                capture_output=True, text=True, timeout=60,
            )
            code, out_text = completed.returncode, completed.stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            out_text = repr(exc)
        found = f'"receipt":true' in out_text.replace(" ", "")
        checks.append(
            check(
                "ALERT_HAS_A_RECEIPT",
                found,
                f"alert {tag}: the OS history {'still holds' if found else 'no longer holds'} it "
                f"(helper exit {code})",
                evidence={"helper": out_text.strip()[:300]},
            )
        )
    ids = [str(row.get("alert_id")) for row in delivered]
    checks.append(
        check(
            "NO_DUPLICATE_DELIVERY",
            len(ids) == len(set(ids)),
            f"{len(ids)} delivered alert(s), {len(set(ids))} distinct id(s)",
        )
    )
    configured = (channel_row.get("environment_presence") or {}).get("EDGE04_ALERT_WEBHOOK")
    remote_ok = channel_row.get("remote_verdict") == "BLOCKED" and not configured
    checks.append(
        check(
            "CHANNELS_STATE_THEIR_LIMITS",
            remote_ok,
            "the remote verdict is BLOCKED and no webhook is configured"
            if remote_ok
            else "the report claims a remote channel that is not configured",
        )
    )
    return checks


def check_campaign(state_root: Path, main_root: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    code, _ = git(REPO_ROOT, "diff", "--quiet", "HEAD", "--", str(CONTRACT.relative_to(REPO_ROOT)))
    contract = read_json(CONTRACT) or {}
    window = contract.get("capture_window") or {}
    floor_ok = window.get("start_utc") == WINDOW_START and window.get("end_utc") == WINDOW_END
    stated_ok = (
        window.get("days") == WINDOW_DAYS
        and float((contract.get("coverage") or {}).get("required_fraction") or 0) == REQUIRED_FRACTION
        and sum(int(item.get("row_count") or 0) for item in contract.get("entries") or [])
        == DECLARED_ROWS
    )
    checks.append(
        check(
            "CONTRACT_UNCHANGED",
            code == 0 and floor_ok and stated_ok,
            f"git diff exit {code}; window {window.get('start_utc')}..{window.get('end_utc')} "
            f"({window.get('days')} d), floor {REQUIRED_FRACTION}, rows {DECLARED_ROWS}",
        )
    )
    disk_space = REPO_ROOT / "src" / "trading_bot" / "research" / "disk_space.py"
    text = disk_space.read_text(encoding="utf-8") if disk_space.exists() else ""
    checks.append(
        check(
            "FLOOR_UNCHANGED",
            "CRITICAL_FREE_BYTES = 2 * GIB" in text and "HEALTHY_FREE_BYTES = 5 * GIB" in text,
            "the 2 GiB floor and the 5 GiB warning in the guard's own module are untouched",
        )
    )
    before = {name: digest(state_root / name) for name in ("runs.jsonl", "health.json")}
    try:
        subprocess.run(
            [sys.executable, str(WATCHDOG), "--state-root", str(state_root), "--json", "--no-persist"],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    after = {name: digest(state_root / name) for name in before}
    checks.append(
        check(
            "TOOLS_DO_NOT_TOUCH_THE_STORE",
            before == after,
            "runs.jsonl and health.json are byte-identical after a reporting run"
            if before == after
            else "a reporting run changed the store",
        )
    )
    return checks


SUITE = "tests/unit/research/test_exp004a_wp051_02j.py"
TASK_NAMES = ("TradingAgentic-EDGE04-Watchdog", "TradingAgentic-EDGE04-Alarm")
DOCUMENTED_EXITS = (0, 1, 2, 8, 9)


def check_tests(out: Path) -> list[dict[str, Any]]:
    """The suite ran, passed, and the record is about the suite that is on disk.

    This reads the recorder's exit code rather than a summary line, then hashes the test file
    again: evidence that cites a suite no longer on disk is evidence about a different file.
    """
    evidence = read_json(out / "TEST_EVIDENCE.json") or {}
    suite = REPO_ROOT / SUITE
    recorded = evidence.get("suite_sha256")
    current = digest(suite)
    code = evidence.get("exit_code")
    passed = int(evidence.get("passed") or 0)
    failed = int(evidence.get("failed") or 0)
    problems = []
    if not evidence:
        problems.append("no TEST_EVIDENCE.json: the suite was not recorded as run")
    else:
        if code != 0:
            problems.append(f"the recorded exit code is {code}, not 0")
        if passed < 1 or failed:
            problems.append(f"{passed} passed / {failed} failed")
        if recorded != current:
            problems.append("the suite on disk is not the suite that was run")
    return [
        check(
            "TESTS_RAN_AND_PASSED",
            not problems,
            "; ".join(problems)
            or f"{passed} test(s) passed under exit 0, suite digest {str(current)[:12]} matches",
            evidence={"suite_sha256": current, "recorded": recorded},
        )
    ]


def _task_field(text: str, needles: tuple[str, ...]) -> str | None:
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        lowered = label.strip().lower()
        if any(needle in lowered for needle in needles):
            return value.strip()
    return None


def _task_digest(name: str, state_root: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"task": name, "registered": False, "error": repr(exc)}
    text = completed.stdout or ""
    last_result = _task_field(text, ("ltimo resultado", "last result"))
    last_run_raw = _task_field(text, ("ltimo tiempo de ejecuci", "last run time"))
    state = str(_task_field(text, ("estado de tarea programada", "scheduled task state")) or "").lower()
    last_run = None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            last_run = datetime.strptime(str(last_run_raw or "").strip(), fmt).astimezone().astimezone(UTC)
            break
        except ValueError:
            continue
    artifact_name = "WATCHDOG.json" if name.endswith("Watchdog") else "SUPERVISOR.json"
    artifact = read_json(state_root / artifact_name) or {}
    written = None
    stamp = artifact.get("generated_at_utc")
    if stamp:
        try:
            written = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            written = None
    return {
        "task": name,
        "registered": bool(_task_field(text, ("nombre de tarea", "task name"))) and completed.returncode == 0,
        "enabled": state.startswith(("habilitado", "enabled", "ready", "listo")),
        "last_result": last_result,
        "last_run_utc": last_run.isoformat() if last_run else None,
        "last_run_raw": last_run_raw,
        "artifact": artifact_name,
        "artifact_at_utc": stamp,
        "written_by_that_run_seconds": round((written - last_run).total_seconds(), 1)
        if written and last_run
        else None,
        "query_exit": completed.returncode,
    }


def check_scheduler(state_root: Path) -> list[dict[str, Any]]:
    """Both entries are registered, enabled, and provably fired.

    Asked of the scheduler directly rather than read from the report, so a report that says the
    alarm is scheduled cannot survive a machine where it is not. The proof that the task *ran* is
    the process's own timestamped verdict written within five minutes of the scheduler's last-run
    record -- two independent witnesses of the same event.
    """
    rows = [_task_digest(name, state_root) for name in TASK_NAMES]
    problems = []
    for row in rows:
        if not row.get("registered"):
            problems.append(f"{row['task']} is not registered")
            continue
        if not row.get("enabled"):
            problems.append(f"{row['task']} is not enabled")
        result = str(row.get("last_result") or "")
        if not (result.isdigit() and int(result) in DOCUMENTED_EXITS):
            problems.append(f"{row['task']} last result {result!r} is not an exit the watchdog documents")
        delta = row.get("written_by_that_run_seconds")
        if delta is None or abs(float(delta)) > 300:
            problems.append(
                f"{row['task']} last run {row.get('last_run_raw')!r} does not match "
                f"{row.get('artifact')} {row.get('artifact_at_utc')!r}"
            )
    return [
        check(
            "SCHEDULE_FIRES_WITHOUT_AN_OPERATOR",
            not problems,
            "; ".join(problems)
            or "; ".join(
                f"{row['task']} last ran {row['last_run_utc']} (result {row['last_result']}), "
                f"writing {row['artifact']} {row['written_by_that_run_seconds']}s later"
                for row in rows
            ),
            evidence={"tasks": rows},
        )
    ]


def check_verdict(out: Path) -> list[dict[str, Any]]:
    final = read_json(out / "FINAL_REPORT_02J.json") or {}
    verdict = final.get("verdict")
    ok = verdict in ("PASS", "FAIL", "BLOCKED")
    capacity = (final.get("capacity") or {}).get("verdict")
    consistent = not (verdict == "PASS" and capacity != "SUFFICIENT")
    return [
        check(
            "VERDICT_IS_HONEST",
            ok and consistent,
            f"verdict {verdict!r} with capacity {capacity!r}",
        )
    ]


def verify(out: Path, main_root: Path) -> dict[str, Any]:
    state_root = main_root / "data" / "forward" / "edge04"
    diagnosis = read_json(out / "DIAGNOSIS.json") or {}
    semantics = read_json(out / "DISK_READING_SEMANTICS.json") or {}
    lost = read_json(out / "LOST_ROWS.json") or {}
    capacity_row = read_json(out / "CAPACITY_PLAN.json") or {}
    channel_row = read_json(out / "ALERT_CHANNELS.json") or {}
    checks: list[dict[str, Any]] = []
    checks.append(
        check(
            "DIAGNOSIS_PRESENT",
            bool(diagnosis.get("candidates")),
            f"{diagnosis.get('candidate_count')} candidate(s), volume "
            f"{(diagnosis.get('volume') or {}).get('free_gib')} GiB free",
        )
    )
    checks.extend(check_scope(diagnosis))
    checks.extend(check_sizes(diagnosis))
    checks.extend(check_reading_semantics(semantics, state_root))
    checks.extend(check_lost_day(lost, main_root))
    checks.extend(check_capacity(capacity_row, state_root))
    checks.extend(check_alerts(out, channel_row, state_root))
    checks.extend(check_scheduler(state_root))
    checks.extend(check_tests(out))
    checks.extend(check_campaign(state_root, main_root))
    checks.extend(check_verdict(out))
    failures = [item for item in checks if item["status"] == "FAIL"]
    return {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02J",
        "generated_at_utc": now_iso(),
        "head": git(REPO_ROOT, "rev-parse", "HEAD")[1],
        "worktree": str(REPO_ROOT),
        "main_root": str(main_root),
        "checks": checks,
        "check_count": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": len(failures),
        "unverifiable": sum(1 for item in checks if item["status"] == "UNVERIFIABLE"),
        "verdict": "PASS" if not failures else "FAIL",
        "not_a_certification": (
            "this says the recovery report agrees with the host. It promotes nothing and it does "
            "not restore the days the campaign has already lost."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs/agentic/exp004a/wp051_02j")
    parser.add_argument("--main-root", type=Path, default=DEFAULT_MAIN)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    result = verify(out, args.main_root.resolve())
    destination = args.json_out or (out / "INDEPENDENT_VERIFICATION_02J.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["checks"]:
            print(f"{item['status']:12} {item['id']}: {item['detail']}")
        print(
            f"\n{result['verdict']}  {result['passed']}/{result['check_count']} PASS, "
            f"{result['failed']} FAIL, {result['unverifiable']} UNVERIFIABLE"
        )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
