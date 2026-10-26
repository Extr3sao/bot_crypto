"""WP-EDGE-05 — the single portable entry point of the independent forward watchdog.

    python scripts/edge05_watchdog.py                 one check, then its exit code
    python scripts/edge05_watchdog.py --status        print the last verdict, change nothing
    python scripts/edge05_watchdog.py --silence       how long the lane, the market and the
                                                      scheduler have each been quiet
    python scripts/edge05_watchdog.py --install       register the watchdog's own OS task
    python scripts/edge05_watchdog.py --uninstall     remove it
    python scripts/edge05_watchdog.py --run-task      ask the scheduler to fire it now
    python scripts/edge05_watchdog.py --task-status   the watchdog's task, as the OS describes it
    python scripts/edge05_watchdog.py --snapshot DIR  capture its own state, or refuse to repeat
    python scripts/edge05_watchdog.py --json          the whole reading on stdout

The check itself is in :mod:`trading_bot.research.edge05.watchdog`; this file parses arguments,
builds the watchdog, runs one check and returns the verdict as an exit code, so the scheduler's
own last-result field carries the verdict the way the lane's carries its outcome:

    0   WATCH_OK          nothing wrong that this process can see
    10  WATCH_DEGRADED    warnings: a stale reading, a repairable inconsistency, disk pressure
    11  WATCH_ALARM       a fault: the schedule stalled, a rule broken, the store short
    12  WATCH_BLOCKED     the schedule is gone or the volume is below the critical floor
    19  the watchdog itself could not complete a reading

It is not a second orchestrator: it holds no lease, runs no pipeline, evaluates no strategy, makes
no market request and never writes inside the lane's own state root. Two tasks, two processes, two
verdicts — the lane's and this one's.

Research only: public market data, no credentials, no orders, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge05.watchdog import (  # noqa: E402
    TASK_NAME,
    WATCHDOG_TASK_NAME,
    ForwardWatchdog,
    stamp,
)

WATCHDOG_DESCRIPTION = (
    "WP-EDGE-05 independent watchdog: reads the WP-EDGE-04 forward lane's evidence and the "
    "operating system's own reporting and records a verdict. Reads only; no credentials, no "
    "orders, no capital, no promotion."
)
DEFAULT_INTERVAL_MINUTES = 15

EXIT_OK = 0
EXIT_DEGRADED = 10
EXIT_ALARM = 11
EXIT_BLOCKED = 12
EXIT_WATCHDOG_ERROR = 19

EXIT_CODES = {
    "WATCH_OK": EXIT_OK,
    "WATCH_DEGRADED": EXIT_DEGRADED,
    "WATCH_ALARM": EXIT_ALARM,
    "WATCH_BLOCKED": EXIT_BLOCKED,
}


def _supervisor() -> object:
    """The repository's own scheduler helper, imported rather than re-implemented."""
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import cap004_supervisor as sup

    return sup


def _arguments() -> str:
    return f'"{Path(__file__).resolve().as_posix()}"'


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install(watchdog: ForwardWatchdog, *, interval_minutes: int, dry_run: bool) -> int:
    sup = _supervisor()
    sup.TASK_DESCRIPTION = WATCHDOG_DESCRIPTION  # type: ignore[attr-defined]
    arguments = _arguments()
    if dry_run:
        print(json.dumps({"arguments": arguments, "task_name": WATCHDOG_TASK_NAME, "dry_run": True}, indent=2))
        return 0
    result = sup.install_scheduler(  # type: ignore[attr-defined]
        task_name=WATCHDOG_TASK_NAME,
        arguments=arguments,
        interval_minutes=interval_minutes,
        register_in_ledger=False,
    )
    task = result.get("task") or {}
    receipt = {
        "at_utc": stamp(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "task_name": WATCHDOG_TASK_NAME,
        "watched_task": TASK_NAME,
        "description": WATCHDOG_DESCRIPTION,
        "interval_minutes": interval_minutes,
        "arguments": arguments,
        "command": task.get("command"),
        "working_directory": task.get("working_directory"),
        "status": result.get("status"),
        "task": task,
        "note": (
            "the watchdog's registration is evidence that a second, independent check exists; it "
            "is never evidence that a check was taken"
        ),
    }
    previous = watchdog.install()
    receipts = list(previous.get("receipts") or [])
    receipts.append(receipt)
    payload = {
        "task_name": WATCHDOG_TASK_NAME,
        "watched_task": TASK_NAME,
        "installed": bool(task.get("installed")),
        "enabled": bool(task.get("enabled")),
        "interval_minutes": interval_minutes,
        "arguments": arguments,
        "receipts": receipts[-10:],
    }
    watchdog.state_root.mkdir(parents=True, exist_ok=True)
    watchdog.install_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"task      {WATCHDOG_TASK_NAME}")
    print(f"watching  {TASK_NAME}")
    print(f"status    {result.get('status')}")
    print(f"installed {task.get('installed')} | enabled {task.get('enabled')} | state {task.get('state')}")
    print(f"command   {task.get('command')}")
    print(f"next run  {task.get('next_run_time')}")
    print(f"receipt   {watchdog.install_path}")
    return 0 if task.get("installed") and task.get("enabled") else 1


def _uninstall(watchdog: ForwardWatchdog) -> int:
    sup = _supervisor()
    result = sup.uninstall_scheduler(task_name=WATCHDOG_TASK_NAME)  # type: ignore[attr-defined]
    payload = watchdog.install()
    payload["uninstalled_at_utc"] = stamp(int(datetime.now(tz=UTC).timestamp() * 1000))
    payload["uninstall_status"] = result.get("status")
    if watchdog.install_path.is_file():
        watchdog.install_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    print(f"task      {WATCHDOG_TASK_NAME}")
    print(f"status    {result.get('status')}")
    return 0 if result.get("status") == "OK" else 1


def _task_status(watchdog: ForwardWatchdog) -> int:
    sup = _supervisor()
    print(
        json.dumps(
            {
                "watchdog_task": sup.scheduler_status(task_name=WATCHDOG_TASK_NAME),  # type: ignore[attr-defined]
                "watched_task": sup.scheduler_status(task_name=TASK_NAME),  # type: ignore[attr-defined]
                "install_receipt": watchdog.install(),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


def _run_task() -> int:
    sup = _supervisor()
    result = sup.run_task_now(task_name=WATCHDOG_TASK_NAME)  # type: ignore[attr-defined]
    print(json.dumps({"triggered": result}, indent=2, sort_keys=True, default=str))
    return 0 if result.get("status") == "OK" else 1


def _render(row: dict[str, Any]) -> str:
    lines = [
        f"check     {row['check_id']}  ({row['at_utc']})",
        f"verdict   {row['verdict']} · category {row['category']} · "
        f"operational_failure {row['operational_failure']} · market_quiet {row['market_quiet']}",
        f"watching  {row['watching']['task_name']}",
    ]
    for name, body in row["checks"].items():
        lines.append(f"  {body.get('status', '?'):<8} {name:<22} {str(body.get('reason'))[:110]}")
    if row["findings"]:
        lines.append("findings  " + " | ".join(row["findings"]))
    if row["warnings"]:
        lines.append("warnings  " + " | ".join(row["warnings"]))
    history = row["history"]
    lines.append(
        f"history   checks {history['checks_on_file']} · episodes {history['episodes_of_trouble']} "
        f"· recoveries {history['recoveries']} · previous {history['previous_verdict']}"
    )
    if row["alerts"]:
        lines.append("alerts    " + ", ".join(sorted({str(a['kind']) for a in row["alerts"]})))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state-root", default=None, help="where the watchdog's own state lives")
    parser.add_argument("--lane-state-root", default=None, help="the lane's state root to read")
    parser.add_argument("--store-root", default=None, help="the forward store to read")
    parser.add_argument("--status", action="store_true", help="print the last verdict, change nothing")
    parser.add_argument("--silence", action="store_true", help="how long each part has been quiet")
    parser.add_argument("--json", action="store_true", help="print the whole reading")
    parser.add_argument("--no-persist", action="store_true", help="do not write this reading")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--run-task", action="store_true")
    parser.add_argument("--task-status", action="store_true")
    parser.add_argument("--snapshot", default=None, metavar="DIR")
    parser.add_argument("--force-snapshot", action="store_true")
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(argv)

    watchdog = ForwardWatchdog(
        repo_root=REPO_ROOT,
        lane_state_root=Path(options.lane_state_root) if options.lane_state_root else None,
        store_root=Path(options.store_root) if options.store_root else None,
        state_root=Path(options.state_root) if options.state_root else None,
    )

    if options.install:
        return _install(watchdog, interval_minutes=options.interval_minutes, dry_run=options.dry_run)
    if options.uninstall:
        return _uninstall(watchdog)
    if options.run_task:
        return _run_task()
    if options.task_status:
        return _task_status(watchdog)
    if options.snapshot:
        record = watchdog.snapshot(Path(options.snapshot), force=options.force_snapshot)
        print(json.dumps(record, indent=2, sort_keys=True, default=str))
        return 0
    if options.status:
        if not watchdog.latest_path.is_file():
            print(f"no reading on file at {watchdog.latest_path}", file=sys.stderr)
            return EXIT_WATCHDOG_ERROR
        print(json.dumps(json.loads(watchdog.latest_path.read_text(encoding="utf-8")), indent=2, sort_keys=True, default=str))
        return EXIT_OK
    if options.silence:
        print(json.dumps(watchdog.silence_report(), indent=2, sort_keys=True, default=str))
        return EXIT_OK

    try:
        row = watchdog.check(persist=not options.no_persist)
    except Exception as exc:  # the watchdog failing is itself a finding, and never a silent one
        print(
            json.dumps(
                {
                    "verdict": "WATCHDOG_ERROR",
                    "at_utc": stamp(int(datetime.now(tz=UTC).timestamp() * 1000)),
                    "error": repr(exc),
                    "hypothetical": True,
                    "order_sent": False,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_WATCHDOG_ERROR
    print(json.dumps(row, indent=2, sort_keys=True, default=str) if options.json else _render(row))
    return EXIT_CODES.get(str(row["verdict"]), EXIT_WATCHDOG_ERROR)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
