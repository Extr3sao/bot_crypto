"""WP051-02K WP-01 — prove the EDGE-04 guard actually alarms, not just runs.

Each case builds a sandbox state root under the system temp directory, drives the sealed guard
as a subprocess exactly the way the scheduler does, and asserts the pair (status, exit code) the
guard documents. The sandbox roots are test instruments, never campaign evidence: the campaign
root is only ever read here.

What this can prove on this host: UNREADABLE, OK, STALE, BLOCKED, DEGRADED, RECOVERED and the
marker lifecycle. What it cannot prove: the WARNING/CRITICAL disk branches, which would need the
volume to actually cross the floors.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

MIB = 1024**2


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def write_ticks(root: Path, rows: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "runs.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def tick_row(moment: datetime, outcome: str, free: int) -> dict:
    return {
        "run_id": f"FWD-EDGE04-{iso(moment).replace('-', '').replace(':', '')}",
        "started_at_utc": iso(moment),
        "finished_at_utc": iso(moment + timedelta(seconds=30)),
        "started_at_ms": ms(moment),
        "outcome": outcome,
        "exit_code": 0 if outcome in ("OBSERVED", "NO_NEW_DATA") else 5,
        "new_bars": 96,
        "disk_after": {"free_bytes": free, "status": "HEALTHY"},
    }


def run_guard(python: Path, script: Path, root: Path, *extra: str) -> dict:
    completed = subprocess.run(
        [str(python), str(script), "--state-root", str(root), "--json", *extra],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(script.parent.parent),
    )
    # ``--json`` prints one indented object, not one object per line: parse the whole stream and
    # only fall back to a line scan if something else shares stdout.
    payload = {}
    try:
        parsed = json.loads(completed.stdout)
        payload = parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        for line in completed.stdout.strip().splitlines():
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
    return {
        "exit_code": completed.returncode,
        "status": payload.get("status"),
        "reasons": payload.get("reasons"),
        "persisted": payload.get("persisted"),
        "delivery": payload.get("delivery"),
        "stdout_tail": completed.stdout.strip().splitlines()[-1:] or [],
        "stderr_tail": completed.stderr.strip().splitlines()[-3:],
        "raw": payload,
    }


def case(name: str, expectation: str, result: dict, root: Path) -> dict:
    passed = result["status"] == expectation and result["exit_code"] == {
        "UNREADABLE": 2,
        "OK": 0,
        "STALE": 9,
        "BLOCKED": 8,
        "DEGRADED": 1,
        "RECOVERED": 0,
    }.get(expectation, -1)
    return {
        "case": name,
        "expected_status": expectation,
        "observed_status": result["status"],
        "exit_code": result["exit_code"],
        "passed": passed,
        "reasons": result["reasons"],
        "state_root": str(root),
        "artifacts": sorted(path.name for path in root.glob("*")) if root.exists() else [],
        "stderr_tail": result["stderr_tail"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="tree that holds the sealed guard")
    parser.add_argument("--python", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--campaign-root", default=None, help="read-only live check")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    python = Path(args.python).resolve()
    script = repo / "scripts" / "edge04_watchdog.py"
    free = shutil.disk_usage(repo).free
    now = datetime.now(tz=UTC)
    results: list[dict] = []
    sandbox = Path(tempfile.mkdtemp(prefix="edge04-guard-"))
    try:
        # 1. the root does not exist at all: the failure the old guard crashed on.
        missing = sandbox / "missing-root"
        results.append(
            case("missing_root", "UNREADABLE", run_guard(python, script, missing), missing)
        )
        marker_raised = (missing / "ATTENTION_REQUIRED.txt").exists()
        results[-1]["marker_raised"] = marker_raised

        # 2. a fresh tick on a healthy volume.
        healthy = sandbox / "healthy"
        write_ticks(healthy, [tick_row(now - timedelta(minutes=2), "OBSERVED", free)])
        results.append(case("fresh_tick", "OK", run_guard(python, script, healthy), healthy))

        # 3. silence past the interval's tolerance (15 min * 3 = 45 min).
        stale = sandbox / "stale"
        write_ticks(stale, [tick_row(now - timedelta(minutes=70), "OBSERVED", free)])
        results.append(case("silent_observer", "STALE", run_guard(python, script, stale), stale))

        # 4. the observer itself refusing every tick for space.
        blocked = sandbox / "blocked"
        write_ticks(
            blocked,
            [
                tick_row(now - timedelta(minutes=3), "DISK_BUDGET_EXCEEDED", 3 * 1024**3),
                tick_row(now - timedelta(minutes=1), "DISK_BUDGET_EXCEEDED", 3 * 1024**3),
            ],
        )
        blocked_result = run_guard(python, script, blocked)
        row = case("blocked_for_space", "BLOCKED", blocked_result, blocked)
        row["marker_raised"] = (blocked / "ATTENTION_REQUIRED.txt").exists()
        row["alert_receipt"] = (blocked_result["delivery"] or {}).get("receipt")
        results.append(row)

        # 5. the blocked root recovers: same root, new healthy tick.
        write_ticks(blocked, [tick_row(now - timedelta(minutes=1), "OBSERVED", free)])
        recovered = run_guard(python, script, blocked)
        row = case("recovery_after_block", "RECOVERED", recovered, blocked)
        row["marker_cleared"] = not (blocked / "ATTENTION_REQUIRED.txt").exists()
        results.append(row)

        # 6. unreadable lines in the log degrade rather than being ignored.
        corrupt = sandbox / "corrupt"
        write_ticks(corrupt, [tick_row(now - timedelta(minutes=2), "OBSERVED", free)])
        with (corrupt / "runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{not json\nalso not json\n")
        results.append(case("corrupt_rows", "DEGRADED", run_guard(python, script, corrupt), corrupt))

        live = None
        if args.campaign_root:
            campaign = Path(args.campaign_root)
            live = run_guard(python, script, campaign, "--no-persist")
            live = {
                "case": "campaign_root_read_only",
                "state_root": str(campaign),
                "status": live["status"],
                "exit_code": live["exit_code"],
                "reasons": live["reasons"],
                "note": "run with --no-persist: observation only, nothing written",
            }
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    report = {
        "schema_version": "EXP004A_WP051_02K_OPS_GUARD_V1",
        "generated_at_utc": iso(now),
        "guard": str(script),
        "python": str(python),
        "cases": results,
        "live_campaign": live,
        "passed": sum(1 for row in results if row["passed"]),
        "failed": [row["case"] for row in results if not row["passed"]],
        "not_covered": (
            "WARNING and CRITICAL disk branches: proving them needs the volume under its floors, "
            "which this host is not; the thresholds are read from the code and unchanged"
        ),
        "verdict": "GUARD_OPERATIONAL" if all(row["passed"] for row in results) else "GUARD_DEFECTIVE",
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "passed": report["passed"],
                      "failed": report["failed"]}, indent=2))
    return 0 if report["verdict"] == "GUARD_OPERATIONAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
