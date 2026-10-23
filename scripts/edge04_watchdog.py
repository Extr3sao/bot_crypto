"""EDGE-04 watchdog: make the observer's silence visible from outside the observer.

The forward observer already records everything a person needs to know. It writes
``alerts.jsonl``, ``health.json`` and one line per tick in ``runs.jsonl``, and on
2026-10-22 it wrote ``HEALTH_BLOCKED`` into all three of them for six hours while the
forward store gained no bars at all. Nobody read them. A file that has to be opened is not
an alarm, and the loss was 87 bars, three of them late enough to quarantine a whole day of
a 90-day declaration.

This program is the missing reader. It is deliberately small and deliberately separate:

* it imports nothing from ``trading_bot``, so a broken import in the lane cannot silence
  the thing that reports the lane is silent;
* it reads only files the observer already writes, and writes exactly two things of its
  own: ``WATCHDOG.json`` (atomic, replaced) and ``ATTENTION_REQUIRED.txt`` (present only
  while something is wrong);
* it exits non-zero when something is wrong, so ``schtasks``' own ``LastTaskResult``
  carries the alarm and any supervisor that already looks at task results sees it;
* it never fetches, never trades and never repairs: a watchdog that fixes things is a
  second thing that can be wrong.

Exit codes, which are the alarm:

    0  OK          the last tick finished inside three intervals and the disk is above the
                   warning floor
    1  DEGRADED    alive, but the disk is between the warning and critical floors: the
                   observer's heavy publication is waiting
    2  UNREADABLE  the state root does not hold a tick log: nothing can be said
    8  BLOCKED     the disk is under the critical floor, or the last tick was refused for
                   lack of space: the store is not growing
    9  STALE       no tick finished within three intervals: the schedule is not firing

Usage:

    python scripts/edge04_watchdog.py                 one check, human-readable
    python scripts/edge04_watchdog.py --json          one check, machine-readable
    python scripts/edge04_watchdog.py --install       register the watchdog task
    python scripts/edge04_watchdog.py --uninstall     remove it
    python scripts/edge04_watchdog.py --task-status   ask the scheduler about it

Research only: reads local files, writes two local files, sends nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "EDGE04_WATCHDOG_V1"
TASK_NAME = "TradingAgentic-EDGE04-Watchdog"
DEFAULT_INTERVAL_MINUTES = 15
SILENCE_FACTOR = 3
WARNING_FREE_BYTES = 5 * 1024**3
CRITICAL_FREE_BYTES = 2 * 1024**3

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_UNREADABLE = 2
EXIT_BLOCKED = 8
EXIT_STALE = 9

REPO_ROOT = Path(__file__).resolve().parents[1]


def now() -> datetime:
    return datetime.now(tz=UTC)


def parse_iso(text: str) -> datetime:
    value = text.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def tail_lines(path: Path, count: int = 20) -> tuple[list[dict[str, Any]], int]:
    """The last ``count`` parsable rows, and how many of the examined rows were not parsable."""
    if not path.is_file():
        return [], 0
    try:
        raw = path.read_bytes()
    except OSError:
        return [], 0
    lines = [line for line in raw.splitlines() if line.strip()]
    window = lines[-count:]
    rows: list[dict[str, Any]] = []
    corrupt = 0
    for line in window:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        else:
            corrupt += 1
    return rows, corrupt


def disk_reading(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    if usage.free < CRITICAL_FREE_BYTES:
        status = "CRITICAL"
    elif usage.free < WARNING_FREE_BYTES:
        status = "WARNING"
    else:
        status = "HEALTHY"
    return {
        "path": str(path),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "free_gib": round(usage.free / 1024**3, 4),
        "used_percent": round(100 * usage.used / usage.total, 2) if usage.total else None,
        "status": status,
        "warning_free_bytes": WARNING_FREE_BYTES,
        "critical_free_bytes": CRITICAL_FREE_BYTES,
    }


def check(
    *,
    state_root: Path,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    """Read the observer's own records and decide whether the lane is alive."""
    observed_now = now_dt or now()
    runs, corrupt = tail_lines(state_root / "runs.jsonl", count=64)
    health = read_json(state_root / "health.json") or {}

    reasons: list[str] = []
    finished = [
        row
        for row in runs
        if row.get("finished_at_utc") or row.get("started_at_utc")
    ]
    last = finished[-1] if finished else None
    last_at = None
    if last is not None:
        stamp = last.get("finished_at_utc") or last.get("started_at_utc")
        try:
            last_at = parse_iso(str(stamp))
        except ValueError:
            last_at = None
    age_seconds = round((observed_now - last_at).total_seconds(), 1) if last_at else None
    silence_limit = interval_minutes * 60 * SILENCE_FACTOR

    consecutive_blocked = 0
    for row in reversed(finished):
        if str(row.get("outcome") or "") == "DISK_BUDGET_EXCEEDED":
            consecutive_blocked += 1
        else:
            break

    disk = disk_reading(state_root)
    if disk["status"] == "CRITICAL":
        reasons.append(
            f"free space {disk['free_gib']} GiB is under the {CRITICAL_FREE_BYTES} byte floor: "
            "the observer refuses to fetch and the store stops growing"
        )
    elif disk["status"] == "WARNING":
        reasons.append(
            f"free space {disk['free_gib']} GiB is under the {WARNING_FREE_BYTES} byte warning "
            "floor: the heavy publication waits"
        )
    if consecutive_blocked:
        reasons.append(
            f"the last {consecutive_blocked} tick(s) were refused for lack of space, "
            f"most recently at {(last or {}).get('started_at_utc')}"
        )
    if age_seconds is None:
        reasons.append("the state root holds no readable tick: the observer has never run here")
    elif age_seconds > silence_limit:
        reasons.append(
            f"no tick finished for {round(age_seconds / 60, 1)} minutes, "
            f"which is more than the {silence_limit // 60} the schedule allows"
        )
    if corrupt:
        reasons.append(f"{corrupt} unreadable line(s) in the last 64 of runs.jsonl")

    if age_seconds is None or not finished:
        status, code = "UNREADABLE", EXIT_UNREADABLE
    elif disk["status"] == "CRITICAL" or consecutive_blocked:
        status, code = "BLOCKED", EXIT_BLOCKED
    elif age_seconds > silence_limit:
        status, code = "STALE", EXIT_STALE
    elif disk["status"] == "WARNING" or corrupt:
        status, code = "DEGRADED", EXIT_DEGRADED
    else:
        status, code = "OK", EXIT_OK

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": observed_now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "state_root": str(state_root),
        "status": status,
        "exit_code": code,
        "reasons": reasons,
        "last_tick": None
        if last is None
        else {
            "started_at_utc": last.get("started_at_utc"),
            "finished_at_utc": last.get("finished_at_utc"),
            "outcome": last.get("outcome"),
            "exit_code": last.get("exit_code"),
            "new_bars": last.get("new_bars"),
            "run_id": last.get("run_id"),
        },
        "age_seconds": age_seconds,
        "silence_limit_seconds": silence_limit,
        "consecutive_blocked_ticks": consecutive_blocked,
        "disk": disk,
        "health_status": health.get("status"),
        "health_generated_at_utc": health.get("generated_at_utc"),
        "corrupt_lines_examined": corrupt,
        "note": (
            "the watchdog reports; it never repairs. A watchdog that fixes the lane is a second "
            "opinion that can be wrong about the same bytes."
        ),
    }


def persist(state_root: Path, result: dict[str, Any]) -> dict[str, str]:
    """Write the verdict atomically and raise or lower the marker file."""
    root = state_root
    root.mkdir(parents=True, exist_ok=True)
    verdict_path = root / "WATCHDOG.json"
    temporary = verdict_path.with_suffix(".json.part")
    temporary.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(temporary, verdict_path)

    marker = root / "ATTENTION_REQUIRED.txt"
    if result["status"] in ("BLOCKED", "STALE", "UNREADABLE"):
        lines = [
            f"{result['generated_at_utc']}  {result['status']}",
            "",
            *[f"- {reason}" for reason in result["reasons"]],
            "",
            "This file exists only while the forward observer needs a person.",
            "It is removed by the next healthy watchdog run.",
        ]
        marker.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        marker_state = "RAISED"
    else:
        if marker.exists():
            marker.unlink()
        marker_state = "ABSENT"
    return {"verdict": str(verdict_path), "marker": marker_state}


def run(argv: list[str], *, timeout: int = 90) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", repr(exc)
    return completed.returncode, completed.stdout, completed.stderr


def install_command(interval_minutes: int, state_root: Path | None = None) -> list[str]:
    """The registration, with the state root spelled out.

    The watchdog lives in the package's worktree, but the state it watches lives in the
    checkout the observer actually writes to. Naming that path in the action keeps the
    task correct without a working directory, which ``schtasks`` cannot set.
    """
    python = Path(sys.executable)
    script = REPO_ROOT / "scripts" / "edge04_watchdog.py"
    target = (state_root or REPO_ROOT / DEFAULT_STATE).resolve()
    return [
        "schtasks",
        "/create",
        "/f",
        "/tn",
        TASK_NAME,
        "/tr",
        f'"{python}" "{script}" --state-root "{target.as_posix()}"',
        "/sc",
        "minute",
        "/mo",
        str(interval_minutes),
        "/rl",
        "LIMITED",
    ]


DEFAULT_STATE = "data/forward/edge04"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-persist", action="store_true", help="report only; write nothing")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--task-status", action="store_true")
    args = parser.parse_args(argv)

    if args.install:
        command = install_command(args.interval_minutes, args.state_root)
        code, out, err = run(command)
        print(
            json.dumps(
                {"installed": code == 0, "command": command, "exit": code,
                 "stdout": out.strip(), "stderr": err.strip()[:400]},
                ensure_ascii=False,
            )
        )
        return EXIT_OK if code == 0 else EXIT_UNREADABLE
    if args.uninstall:
        code, _out, err = run(["schtasks", "/delete", "/f", "/tn", TASK_NAME])
        print(json.dumps({"uninstalled": code == 0, "stderr": err.strip()[:200]}))
        return EXIT_OK if code == 0 else EXIT_UNREADABLE
    if args.task_status:
        code, out, err = run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"])
        print(out.strip() or err.strip())
        return EXIT_OK if code == 0 else EXIT_UNREADABLE

    state_root = (args.state_root or REPO_ROOT / DEFAULT_STATE).resolve()
    result = check(state_root=state_root, interval_minutes=args.interval_minutes)
    if not args.no_persist:
        result["persisted"] = persist(state_root, result)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}  {result['generated_at_utc']}")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        print(f"  last tick: {(result['last_tick'] or {}).get('started_at_utc')}")
        print(f"  disk: {result['disk']['free_gib']} GiB free ({result['disk']['status']})")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
