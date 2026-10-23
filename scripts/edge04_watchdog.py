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

``RECOVERED`` shares exit code 0 with ``OK`` on purpose: the alarm is a process exit code, and
a supervisor that treats non-zero as "page someone" must stop paging the moment the condition
ends. What distinguishes the two is the report, the event log and the marker, not the code.

Five states, and the difference between them is what a person would do about it:

    OK          nothing to do
    DEGRADED    alive and writing; the volume is low enough that the heavy publication waits
    BLOCKED     the store is not growing, and the reason is space (or a refusal it recorded)
    STALE       the store is not growing, and the reason is the schedule
    RECOVERED   the previous run was BLOCKED/STALE/UNREADABLE and this one is not

What this program adds to a bare exit code, and why each addition exists:

* **velocity and forecast** -- a floor that is 4 GiB away is comfortable or urgent depending on
  how fast the volume is falling. Measured from the observer's own readings, and reported as
  ``UNKNOWN`` when the history is too short to support a rate. Never invented;
* **an event log** -- one line per *transition*, in ``WATCHDOG_EVENTS.jsonl``, rotated at a fixed
  size so the alarm cannot fill the volume it is reporting on;
* **a best-effort marker and a mandatory exit code** -- the marker is a convenience for a person
  who is looking; the exit code is the channel that survives a full volume, because the
  scheduler stores it in its own database rather than in a file;
* **honest escalation** -- every notification channel is attempted and recorded. On this host
  the Windows event log refuses an unprivileged writer, no webhook is configured, and no mail
  transport exists, so the report says so instead of implying somebody was told.

Usage:

    python scripts/edge04_watchdog.py                 one check, human-readable
    python scripts/edge04_watchdog.py --json          one check, machine-readable
    python scripts/edge04_watchdog.py --install       register the watchdog task
    python scripts/edge04_watchdog.py --uninstall     remove it
    python scripts/edge04_watchdog.py --task-status   ask the scheduler about it

Research only: reads local files, writes local files, sends nothing unless a webhook URL is
configured in the environment.
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

SCHEMA_VERSION = "EDGE04_WATCHDOG_V2"
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

#: How many of the observer's own tick rows are read to measure velocity. 700 rows is a little
#: over seven days at the lane's fifteen-minute schedule: enough for a daily drawdown to mean
#: something, small enough that the watchdog stays cheap next to the tick it watches.
HISTORY_ROWS = 700
#: A rate is only reported when the history covers at least this many complete UTC days.
HISTORY_MIN_DAYS = 3

EVENTS_FILE = "WATCHDOG_EVENTS.jsonl"
EVENTS_MAX_BYTES = 256 * 1024

BLOCKING_STATES = ("BLOCKED", "STALE", "UNREADABLE")
RECOVERED = "RECOVERED"
WEBHOOK_ENV = "EDGE04_ALERT_WEBHOOK"

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


def free_space_series(state_root: Path, *, rows: int = HISTORY_ROWS) -> dict[str, Any]:
    """The last ``rows`` tick readings of free space, oldest first.

    Read from the same log the tick writes, so the watchdog measures the volume with the
    observer's own instrument rather than a second one that could disagree with it.
    """
    parsed, corrupt = tail_lines(state_root / "runs.jsonl", count=rows)
    samples: list[dict[str, Any]] = []
    for row in parsed:
        reading = row.get("disk_after") or row.get("disk") or {}
        free = reading.get("free_bytes") if isinstance(reading, dict) else None
        stamp = row.get("started_at_ms")
        if isinstance(free, int) and isinstance(stamp, int):
            samples.append({"ts_ms": stamp, "free_bytes": free, "outcome": row.get("outcome")})
    samples.sort(key=lambda item: item["ts_ms"])
    return {"samples": samples, "rows_examined": len(parsed), "unparsable": corrupt}


def history_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Daily drawdown and net change, and the number of days they rest on.

    A rate is only returned when at least :data:`HISTORY_MIN_DAYS` complete UTC days hold two
    or more readings each. Fewer than that is not a weak forecast, it is no forecast, and the
    caller is told which one it got.
    """
    buckets: dict[str, list[int]] = {}
    for sample in samples:
        day = datetime.fromtimestamp(sample["ts_ms"] / 1000, tz=UTC).strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(sample["free_bytes"])
    usable = {day: values for day, values in buckets.items() if len(values) >= 2}
    if len(usable) < HISTORY_MIN_DAYS:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": (
                f"{len(usable)} complete day(s) with two or more readings; "
                f"{HISTORY_MIN_DAYS} are required before a rate is reported"
            ),
            "days": len(usable),
            "samples": len(samples),
            "max_daily_drawdown_bytes": None,
            "median_daily_net_bytes": None,
        }
    drawdowns = [max(values) - min(values) for values in usable.values()]
    nets = [values[-1] - values[0] for values in usable.values()]
    ordered = sorted(nets)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else int((ordered[middle - 1] + ordered[middle]) / 2)
    )
    return {
        "status": "MEASURED",
        "days": len(usable),
        "samples": len(samples),
        "max_daily_drawdown_bytes": max(drawdowns),
        "median_daily_net_bytes": int(median),
        "days_spending": sum(1 for item in nets if item < 0),
        "days_recovering": sum(1 for item in nets if item > 0),
        "basis": "max/min and first/last free-space reading of each complete UTC day",
    }


def forecast(disk: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    """How long the free space has, at the worst rate this volume has already shown.

    The worst observed daily drawdown rather than the median: a floor is not protected by an
    average day, and the record on this host already holds days that fell several GiB.
    """
    drawdown = history.get("max_daily_drawdown_bytes")
    if history.get("status") != "MEASURED" or not drawdown:
        return {
            "label": "UNKNOWN",
            "reason": history.get("reason") or "no positive drawdown has been observed",
            "max_daily_drawdown_bytes": drawdown,
            "hours_to_critical": None,
        }
    remaining = disk["free_bytes"] - CRITICAL_FREE_BYTES
    hours = round(remaining / (drawdown / 24), 2)
    return {
        "label": "AT_RISK" if hours < 24 else "COMFORTABLE",
        "max_daily_drawdown_bytes": drawdown,
        "base_bytes_per_hour": round(drawdown / 24, 1),
        "hours_to_critical": max(0.0, hours),
        "basis": (
            "worst daily drawdown in the observer's own readings, applied from the current "
            "free space to the critical floor; a rate, not a promise"
        ),
        "history_days": history.get("days"),
    }


def check(
    *,
    state_root: Path,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    now_dt: datetime | None = None,
    previous_status: str | None = None,
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
    history = history_stats(free_space_series(state_root)["samples"])
    ahead = forecast(disk, history)
    if previous_status is None:
        previous_status = (read_json(state_root / "WATCHDOG.json") or {}).get("status")
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
    elif previous_status in BLOCKING_STATES:
        status, code = RECOVERED, EXIT_OK
        reasons.append(
            f"the previous run reported {previous_status} and this one does not: the lane is "
            "alive again, and the bars it lost while it was not are not recoverable"
        )
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
        "history": history,
        "forecast": ahead,
        "previous_status": previous_status,
        "recovered_from": previous_status if status == RECOVERED else None,
        "health_status": health.get("status"),
        "health_generated_at_utc": health.get("generated_at_utc"),
        "corrupt_lines_examined": corrupt,
        "note": (
            "the watchdog reports; it never repairs. A watchdog that fixes the lane is a second "
            "opinion that can be wrong about the same bytes."
        ),
    }


def append_event(root: Path, result: dict[str, Any], *, escalated: bool = False) -> str:
    """One line per transition, rotated at a fixed size.

    An alarm that keeps a file on the volume it is warning about has to bound that file: the
    first thing a full disk stops is the writing of logs, and an unbounded event log would be
    the watchdog's own contribution to the problem.
    """
    path = root / EVENTS_FILE
    line = {
        "at_utc": result.get("generated_at_utc"),
        "status": result.get("status"),
        "previous_status": result.get("previous_status"),
        "exit_code": result.get("exit_code"),
        "reasons": result.get("reasons"),
        "free_gib": (result.get("disk") or {}).get("free_gib"),
        "forecast": result.get("forecast"),
        "last_tick": (result.get("last_tick") or {}).get("started_at_utc"),
        "escalated": escalated,
    }
    try:
        if path.is_file() and path.stat().st_size > EVENTS_MAX_BYTES:
            os.replace(path, path.with_suffix(".jsonl.1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError as exc:
        return f"ERROR:{exc}"
    return "APPENDED"


def escalate(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Attempt every channel that could reach a person, and record what each one said.

    None of this invents a channel. A webhook is used only when its URL is already in the
    environment, and the Windows event log is attempted because it is the one local channel
    that does not need to write to the volume under pressure -- and the answer it gives is
    recorded as given, including a refusal.
    """
    channels: list[dict[str, Any]] = [
        {
            "channel": "scheduler_exit_code",
            "effective": True,
            "detail": (
                f"the task's LastTaskResult carries {result.get('exit_code')} "
                f"({result.get('status')}); poll it with schtasks /query /tn {TASK_NAME} /v"
            ),
        }
    ]
    detail = (result.get("persisted") or {}).get("marker", "UNKNOWN")
    channels.append(
        {
            "channel": "marker_file",
            "effective": detail == "RAISED",
            "detail": f"ATTENTION_REQUIRED.txt {detail} on the volume under pressure",
        }
    )
    url = os.environ.get(WEBHOOK_ENV, "").strip()
    if not url:
        channels.append(
            {
                "channel": "webhook",
                "effective": False,
                "detail": f"{WEBHOOK_ENV} is not set: no remote notification is configured",
            }
        )
    else:
        payload = json.dumps(
            {
                "text": f"EDGE04 {result.get('status')}: {'; '.join(result.get('reasons') or [])}",
                "status": result.get("status"),
                "generated_at_utc": result.get("generated_at_utc"),
            }
        ).encode("utf-8")
        try:
            import urllib.request

            request = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                channels.append(
                    {
                        "channel": "webhook",
                        "effective": 200 <= response.status < 300,
                        "detail": f"HTTP {response.status}",
                    }
                )
        except Exception as exc:  # noqa: BLE001 - the channel's failure is the datum
            channels.append({"channel": "webhook", "effective": False, "detail": repr(exc)[:200]})
    code, _out, err = run(
        [
            "eventcreate",
            "/t",
            "ERROR",
            "/id",
            "901",
            "/l",
            "APPLICATION",
            "/d",
            f"EDGE04 {result.get('status')}: {(result.get('reasons') or [''])[0]}"[:250],
        ],
        timeout=20,
    )
    channels.append(
        {
            "channel": "windows_event_log",
            "effective": code == 0,
            "detail": "written" if code == 0 else (err.strip() or f"exit {code}")[:200],
        }
    )
    return channels


def persist(state_root: Path, result: dict[str, Any]) -> dict[str, str]:
    """Write the verdict atomically, log a transition, and raise or lower the marker.

    Every write here is best-effort. A full volume must not turn the watchdog into a traceback:
    the exit code is the alarm, and the code does not need the disk.
    """
    root = state_root
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"verdict": f"ERROR:{exc}", "marker": "ERROR", "event": "NONE"}
    verdict_path = root / "WATCHDOG.json"
    temporary = verdict_path.with_suffix(".json.part")
    verdict_state = "WRITTEN"
    try:
        temporary.write_bytes(
            (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        os.replace(temporary, verdict_path)
    except OSError as exc:
        verdict_state = f"ERROR:{exc}"
    event_state = (
        append_event(root, result)
        if result.get("status") != result.get("previous_status")
        else "UNCHANGED"
    )

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
        try:
            marker.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
            marker_state = "RAISED"
        except OSError as exc:
            marker_state = f"ERROR:{exc}"
    else:
        try:
            if marker.exists():
                marker.unlink()
            marker_state = "ABSENT"
        except OSError as exc:
            marker_state = f"ERROR:{exc}"
    return {
        "verdict": str(verdict_path),
        "verdict_state": verdict_state,
        "marker": marker_state,
        "event": event_state,
        "events_path": str(root / EVENTS_FILE),
    }


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
    parser.add_argument(
        "--escalate",
        action="store_true",
        help="attempt every notification channel even when the state has not changed",
    )
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
    transition = result["status"] != result.get("previous_status")
    if not args.no_persist and (args.escalate or (transition and result["status"] in BLOCKING_STATES)):
        result["escalation"] = escalate(result)
        if transition and result["status"] in BLOCKING_STATES:
            append_event(state_root, result, escalated=True)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}  {result['generated_at_utc']}")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        print(f"  last tick: {(result['last_tick'] or {}).get('started_at_utc')}")
        print(f"  disk: {result['disk']['free_gib']} GiB free ({result['disk']['status']})")
        ahead = result.get("forecast") or {}
        if ahead.get("hours_to_critical") is not None:
            print(
                f"  forecast: {ahead['label']} -- the floor is "
                f"{ahead['hours_to_critical']} h away at the worst rate this volume has shown"
            )
        else:
            print(f"  forecast: {ahead.get('label')} ({ahead.get('reason')})")
        for channel in result.get("escalation") or []:
            print(f"  escalate {channel['channel']}: effective={channel['effective']} {channel['detail']}")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
