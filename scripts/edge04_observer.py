"""WP-EDGE-04 — the single portable entry point of the autonomous forward observer.

The derived re-read's receipt is appended to ``<state-root>/derived_refresh.jsonl`` on every
scheduled tick (see :func:`_persist_derived_refresh`): the tick record itself is written before
the re-read happens and the scheduler discards stdout, so without that line nothing durable
said whether the reconciliation had run from the cadence.

    python scripts/edge04_observer.py                     one manual tick
    python scripts/edge04_observer.py --scheduled --due   what the operating system runs
    python scripts/edge04_observer.py --status            read the observer's own state
    python scripts/edge04_observer.py --install           register the OS task (idempotent)
    python scripts/edge04_observer.py --uninstall         remove it
    python scripts/edge04_observer.py --run-task          ask the scheduler to run it now
    python scripts/edge04_observer.py --snapshot DIR      copy live evidence into a directory
    python scripts/edge04_observer.py --report-only DIR   re-render the reports offline
    python scripts/edge04_observer.py --repair-slot-ledger drop duplicate seals from the ledger
    python scripts/edge04_observer.py --no-refresh-derived  tick without re-reading the lane

The tick itself is in :mod:`trading_bot.research.edge03.autonomous`; this file only parses
arguments, builds the observer, calls it, and returns the outcome's exit code. There is no
second pipeline, no second scheduler and no second lock: the OS task is registered through
the same supervisor the CAP-004 and ST-6 lanes use (``scripts/cap004_supervisor.py``).

Exit codes are the outcome vocabulary, so the scheduler's own last-result field carries the
result:

    0  OBSERVED / NO_NEW_DATA / ALREADY_OBSERVED      the tick did its job
    1  RUNTIME_EXCEPTION                              the pipeline or the evidence write raised
    2  ALREADY_RUNNING                                another tick holds the lease
    4  MISSING_BARS / STALE_DATA                      the tick ran and the store is still short
    5  DISK_BUDGET_EXCEEDED                           the storage guard refused before any request
    6  VERIFICATION_FAILED                            the frozen pin refused
    7  PROVIDER_UNAVAILABLE                           every series failed to fetch

The tick is also the trigger for the lane's *derived reading*. A reconciliation that is only
run by hand describes the lane as it was when somebody last ran it, which is how WP-EDGE-05R
found it: three ticks behind the evidence it reads. So a scheduled tick that consumed its slot
re-reads the lane into the watchdog's reconciliation record, with the instant, the duration and
the status of that re-read carried inside the tick's own record. It never changes the tick's
outcome: a lane that observed and could not be re-read has still observed, and the failure is
reported rather than converted into a pass or a stop.

Research only: public market data, no credentials, no orders, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge03.autonomous import (  # noqa: E402
    MODE_MANUAL,
    MODE_SCHEDULED,
    SLOT_CONSUMING_OUTCOMES,
    STATE_SCHEMA_VERSION,
    ForwardObserver,
    read_jsonl,
    stamp,
)

TASK_NAME = "TradingAgentic-EDGE04-Forward"
TASK_DESCRIPTION = (
    "WP-EDGE-04 forward observation: unattended tick of the frozen WP-EDGE-03 forward lane. "
    "Public market data only; no credentials, no orders, no capital."
)
DEFAULT_INTERVAL_MINUTES = 15


def _supervisor() -> object:
    """The repository's own Windows/scheduler helper, imported rather than re-implemented."""
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import cap004_supervisor as sup

    return sup


def _arguments() -> str:
    return f'"{Path(__file__).resolve().as_posix()}" --scheduled --due'


def _parse_instant(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _persist_derived_refresh(observer: object, record: dict[str, Any], receipt: dict[str, Any]) -> Path | None:
    """Append the re-read's receipt where a reader can find it without stdout.

    The receipt used to live only in the tick record the script *prints*: the record itself is
    persisted by ``ForwardObserver.tick`` before the re-read happens, and the scheduler discards
    stdout, so nothing durable said whether the reconciliation had run from the cadence. This
    appends one line per tick to the observer's own state, joined to the tick by ``run_id`` and
    ``slot_key``. A failure here is recorded and never changes the tick's verdict: the tick's
    verdict is about the lane, and this is a receipt about the reading.
    """
    state_root = getattr(observer, "state_root", None)
    if state_root is None:
        receipt["persisted"] = False
        receipt["persist_error"] = "the observer exposes no state root to write to"
        return None
    path = Path(state_root) / "derived_refresh.jsonl"
    line = {
        "schema_version": "EDGE04_DERIVED_REFRESH_V1",
        "at_utc": stamp(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "run_id": record.get("run_id"),
        "slot_key": record.get("slot_key"),
        "mode": record.get("mode"),
        "outcome": record.get("outcome"),
        **{key: receipt.get(key) for key in ("ran", "reason", "seconds", "after_outcome", "status", "unattributed_bars", "artifacts")},
        "hypothetical": bool(record.get("hypothetical")),
        "order_sent": False,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True, default=str) + "\n")
    except OSError as exc:
        receipt["persisted"] = False
        receipt["persist_error"] = f"{type(exc).__name__}: {exc}"
        return None
    receipt["persisted"] = True
    receipt["receipt_log"] = str(path)
    return path


def _refresh_derived(*, outcome: str, repo_root: Path) -> dict[str, Any]:
    """Re-read the lane after a tick that consumed its slot.

    The reconciliation is a reading of what the lane just wrote, so the tick is the only
    trigger it needs and the lane's own state is the only input. It is written into the
    watchdog's state (``data/forward/edge05/reconciliation/``), not into a report directory:
    a reading that rewrote published reports on every 15-minute tick would put the churn
    exactly where the reviewer looks, and the reading is what the reports are rendered from,
    not the other way round.

    Returns the receipt that travels inside the tick record. A failure here is recorded with
    its exception type and message and does not raise: the tick's verdict is about the lane.
    """
    started = time.monotonic()
    try:
        from trading_bot.research.edge05.reconcile import Reconciler

        reconciler = Reconciler(repo_root=repo_root)
        report = reconciler.reconcile()
        written = reconciler.write(report)
    except Exception as exc:  # recorded here, never converted into the tick's verdict
        return {
            "ran": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.monotonic() - started, 3),
            "after_outcome": outcome,
        }
    return {
        "ran": True,
        "reason": None,
        "seconds": round(time.monotonic() - started, 3),
        "after_outcome": outcome,
        "status": report.get("status"),
        "unattributed_bars": report.get("totals", {}).get("unattributed_bars")
        if isinstance(report.get("totals"), dict)
        else None,
        "artifacts": {name: str(path) for name, path in written.items()},
    }


def _install(observer: ForwardObserver, *, interval_minutes: int, dry_run: bool) -> int:
    sup = _supervisor()
    # The supervisor's XML builder carries the CAP-004B campaign's own description as a module
    # constant. This task is a different experiment, so the constant is replaced before the
    # registration: a task list that names another campaign's purpose is a task list a reader
    # cannot trust. Nothing else about the builder is touched.
    sup.TASK_DESCRIPTION = TASK_DESCRIPTION  # type: ignore[attr-defined]
    arguments = _arguments()
    if dry_run:
        print(
            json.dumps({"arguments": arguments, "task_name": TASK_NAME, "dry_run": True}, indent=2)
        )
        return 0
    result = sup.install_scheduler(  # type: ignore[attr-defined]
        task_name=TASK_NAME,
        arguments=arguments,
        interval_minutes=interval_minutes,
        register_in_ledger=False,
    )
    task = result.get("task") or {}
    receipt = {
        "schema_version": STATE_SCHEMA_VERSION,
        "task_name": TASK_NAME,
        "description": TASK_DESCRIPTION,
        "interval_minutes": interval_minutes,
        "arguments": arguments,
        "command": task.get("command"),
        "working_directory": task.get("working_directory"),
        "status": result.get("status"),
        "task": task,
        "at_utc": stamp(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "note": (
            "the scheduler's own registration is a declaration; it is evidence that the task "
            "exists and is enabled, never that a measurement was taken"
        ),
    }
    previous = observer.install()
    receipts = list(previous.get("receipts") or [])
    receipts.append(receipt)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "task_name": TASK_NAME,
        "installed": bool(task.get("installed")),
        "enabled": bool(task.get("enabled")),
        "interval_minutes": interval_minutes,
        "arguments": arguments,
        "receipts": receipts[-10:],
    }
    observer.state_root.mkdir(parents=True, exist_ok=True)
    observer.install_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"task      {TASK_NAME}")
    print(f"status    {result.get('status')}")
    print(
        f"installed {task.get('installed')} | enabled {task.get('enabled')} | state {task.get('state')}"
    )
    print(f"command   {task.get('command')}")
    print(f"args      {arguments}")
    print(f"next run  {task.get('next_run_time')}")
    print(f"receipt   {observer.install_path}")
    return 0 if task.get("installed") and task.get("enabled") else 1


def _uninstall(observer: ForwardObserver) -> int:
    sup = _supervisor()
    result = sup.uninstall_scheduler(task_name=TASK_NAME)  # type: ignore[attr-defined]
    print(f"task      {TASK_NAME}")
    print(f"status    {result.get('status')}")
    print(f"output    {result.get('output')}")
    payload = observer.install()
    payload["uninstalled_at_utc"] = stamp(int(datetime.now(tz=UTC).timestamp() * 1000))
    payload["uninstall_status"] = result.get("status")
    if observer.install_path.is_file():
        observer.install_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    return 0 if result.get("status") == "OK" else 1


def _task_status(observer: ForwardObserver) -> int:
    sup = _supervisor()
    status = sup.scheduler_status(task_name=TASK_NAME)  # type: ignore[attr-defined]
    print(
        json.dumps(
            {"task": status, "install_receipt": observer.install()},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


def _run_task() -> int:
    sup = _supervisor()
    result = sup.run_task_now(task_name=TASK_NAME)  # type: ignore[attr-defined]
    print(
        json.dumps(
            {"triggered": result, "at_utc": stamp(int(datetime.now(tz=UTC).timestamp() * 1000))},
            indent=2,
        )
    )
    return 0 if result.get("status") == "OK" else 1


def _preserved_observation(publication: Path) -> Path | None:
    """Where the tick preserved the payload it reported: the publication's own layout."""
    for candidate in (
        publication / "OBSERVATION.json",
        publication / "forward-observation" / "OBSERVATION.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def _report_only(outdir: Path, *, publication: Path, compare: bool) -> int:
    """Re-render the human-facing reports from a preserved observation, with no network."""
    source = _preserved_observation(publication)
    if source is None:
        print(f"no preserved observation under {publication}", file=sys.stderr)
        return 2
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not payload.get("health") or "ingest" not in payload:
        print(f"{source} is not an EDGE-03 observation", file=sys.stderr)
        return 2
    from trading_bot.research.edge03.reporting import write_observability

    outdir.mkdir(parents=True, exist_ok=True)
    written = write_observability(payload, outdir)
    identical: dict[str, bool] = {}
    for name, path in sorted(written.items()):
        live = publication / path.relative_to(outdir)
        if compare and live.is_file():
            identical[name] = _sha256(path) == _sha256(live)
    print(f"re-rendered from {source} (no fetch):")
    for name, path in sorted(written.items()):
        print(f"  {name}: {path}")
    if compare:
        print(json.dumps({"byte_identical": identical}, indent=2, sort_keys=True))
        return 0 if identical and all(identical.values()) else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state-root", default=None, help="where the observer's own state lives")
    parser.add_argument("--store-root", default=None, help="where the forward store lives")
    parser.add_argument("--observed-at", default=None, help="market instant (ISO-8601 UTC)")
    parser.add_argument(
        "--due", action="store_true", help="observe this slot only if it is unobserved"
    )
    parser.add_argument(
        "--scheduled", action="store_true", help="this invocation is the schedule's own"
    )
    parser.add_argument("--force", action="store_true", help="run the heavy publication now")
    parser.add_argument("--json", action="store_true", help="print the whole tick record")
    parser.add_argument("--status", action="store_true", help="print the observer's state and exit")
    parser.add_argument("--install", action="store_true", help="register the OS task")
    parser.add_argument("--uninstall", action="store_true", help="remove the OS task")
    parser.add_argument("--task-status", action="store_true", help="query the OS task")
    parser.add_argument(
        "--run-task", action="store_true", help="ask the scheduler to run the task now"
    )
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES)
    parser.add_argument(
        "--dry-run", action="store_true", help="print what --install would register"
    )
    parser.add_argument(
        "--repair-slot-ledger", action="store_true", help="drop duplicate seals from slots.jsonl"
    )
    parser.add_argument(
        "--snapshot", default=None, help="copy the live evidence into this directory"
    )
    parser.add_argument(
        "--report-only", nargs="?", const="", default=None, help="re-render reports offline"
    )
    parser.add_argument(
        "--refresh-derived",
        dest="refresh_derived",
        action="store_true",
        default=None,
        help="re-read the lane into the watchdog's reconciliation record after the tick",
    )
    parser.add_argument(
        "--no-refresh-derived",
        dest="refresh_derived",
        action="store_false",
        help="tick without the derived re-read (a manual tick does this by default)",
    )
    parser.add_argument(
        "--compare", action="store_true", help="with --report-only, check byte identity"
    )
    args = parser.parse_args(argv)

    observer = ForwardObserver(
        repo_root=REPO_ROOT,
        state_root=Path(args.state_root) if args.state_root else None,
        store_root=Path(args.store_root) if args.store_root else None,
    )

    if args.install:
        return _install(observer, interval_minutes=args.interval_minutes, dry_run=args.dry_run)
    if args.uninstall:
        return _uninstall(observer)
    if args.task_status:
        return _task_status(observer)
    if args.run_task:
        return _run_task()
    if args.repair_slot_ledger:
        receipt = observer.dedupe_slots()
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
        print(f"dropped  {len(receipt['dropped'])} duplicate seal(s)")
        return 0
    if args.report_only is not None:
        outdir = (
            Path(args.report_only) if args.report_only else observer.state_root / "reports-only"
        )
        return _report_only(outdir, publication=observer.publication_dir, compare=args.compare)
    if args.snapshot:
        copied = observer.snapshot(Path(args.snapshot))
        for name, path in sorted(copied.items()):
            print(f"  {name}: {path}")
        return 0
    if args.status:
        runs, corrupt = read_jsonl(observer.runs_path)
        payload = {
            "state_root": str(observer.state_root),
            "store_root": str(observer.store_root),
            "publication_dir": str(observer.publication_dir),
            "runs": len(runs),
            "corrupt_log_lines": corrupt,
            "last_run": runs[-1] if runs else None,
            "health": observer.health(),
            "coverage": observer.prospective(
                {
                    "observed_at_utc": None,
                    "generated_at_utc": None,
                    "health": {"observation_days": 0},
                }
            ),
            "install": observer.install(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    record = observer.tick(
        observed_at_ms=_parse_instant(args.observed_at),
        due_only=bool(args.due),
        force_publication=bool(args.force),
        mode=MODE_SCHEDULED if args.scheduled else MODE_MANUAL,
    )
    # The cadence, not a person, keeps the derived reading current: the operating system runs
    # `--scheduled --due`, so a scheduled tick that consumed its slot is what re-reads the lane.
    # A tick that found the slot already observed changed nothing, and neither does a manual one.
    wants_refresh = (
        args.refresh_derived if args.refresh_derived is not None else bool(args.scheduled)
    )
    if wants_refresh and record.get("outcome") in SLOT_CONSUMING_OUTCOMES:
        record["derived_refresh"] = _refresh_derived(
            outcome=str(record["outcome"]), repo_root=REPO_ROOT
        )
    elif wants_refresh:
        record["derived_refresh"] = {
            "ran": False,
            "reason": (
                f"the tick's outcome is {record.get('outcome')}: it changed nothing, so there is "
                "nothing for the derived reading to re-read"
            ),
            "seconds": 0.0,
            "after_outcome": record.get("outcome"),
        }
    if wants_refresh:
        # The receipt is durable, not just printed: the scheduler throws stdout away, and a
        # re-read nobody can show afterwards is a re-read a reader has to take on trust.
        _persist_derived_refresh(observer, record, record["derived_refresh"])
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True, default=str))
    else:
        print(f"run          {record['run_id']}")
        print(f"slot         {record['slot_key']}  mode={record['mode']}")
        print(f"outcome      {record['outcome']} — {record['outcome_reason']}")
        print(f"duration     {record['duration_seconds']} s")
        print(
            f"new bars     {record.get('new_bars')} (expected {record.get('expected_new_bars')}, missing {record.get('missing_bars')})"
        )
        print(f"market reqs  {record.get('market_requests')}")
        print(
            f"disk         {record.get('disk_after', {}).get('status')} / {record.get('disk_after', {}).get('free_gib')} GiB free"
        )
        publication = record.get("publication") or {}
        print(
            f"publication  {'ran' if publication.get('ran') else 'skipped'} — {publication.get('reason') or publication.get('at_utc')}"
        )
        print(f"health       {record.get('health_status')}")
        print(f"alerts       {len(record.get('alerts') or [])}")
        derived = record.get("derived_refresh")
        if derived is not None:
            print(
                f"derived      {'re-read in ' + str(derived['seconds']) + ' s' if derived['ran'] else 'NOT re-read — ' + str(derived['reason'])}"
            )
        print(f"exit         {record['exit_code']}")
    return int(record["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
