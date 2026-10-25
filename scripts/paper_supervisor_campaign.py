"""paper_supervisor_campaign — crash a supervised PAPER session, repeatedly, for real.

The unit tests prove the *policy*; this harness proves it against the runtime. No mocks, no
injected spawner: two supervisors are started at once over the same directory, one wins the
coordination lock, and the winner keeps a real ``def_run_019_prospective_run.py`` alive
through several forced terminations of its whole process tree.

Per episode, exactly what an operator would see:

1. wait until the child owns the stream lock *and* has persisted a new cycle;
2. try to take the stream lock from this process — it must be refused ``LOCK_HELD`` and the
   record must be byte-identical afterwards;
3. kill the child tree with ``taskkill /F /T`` (no chance to release anything);
4. read the abandoned locks and the verdict on their owner;
5. wait for the supervisor to resume it by itself, and for the resumed ``SESSION_START``
   that continues the chain at the next sequence number;
6. wait for a new cycle from the resumed process, then read the stream, the fences, the
   cycle ledgers and the remaining locks.

The last episode is not killed: the resumed session is allowed to end on its own, so the
campaign finishes with zero locks and an honest ``STOP_COMPLETED``.

Two negative scenarios run in their own directories and cost seconds:

* ``corrupt`` — a copy of the campaign evidence with a truncated stream line: the
  supervisor must refuse (``STOP_FAILED``) and must not spawn anything;
* ``budget`` — a supervised session killed before every cycle with ``--max-restarts 1``: the
  second crash must stop with ``RETRY_BUDGET_EXHAUSTED`` rather than loop.

What this does **not** claim: nothing here is a strategy result. Fills are simulated PAPER
fills, ``live_orders`` is 0 because the entrypoint has no order path, and no admission gate
is touched.

Usage::

    python scripts/paper_supervisor_campaign.py run --out reports/.../campaign
    python scripts/paper_supervisor_campaign.py scenarios --out reports/.../campaign
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops import windowless  # noqa: E402
from trading_bot.ops.session_status import session_status  # noqa: E402
from trading_bot.ops.single_writer import (  # noqa: E402
    LockRefused,
    SingleWriter,
    diagnose_lock,
    pid_alive,
)
from trading_bot.vision.ledger import read_entries, verify_chain  # noqa: E402

ENTRYPOINT = REPO / "scripts" / "def_run_019_prospective_run.py"
SUPERVISOR = REPO / "scripts" / "paper_supervisor.py"

#: ``duration_s`` is part of the pinned identity: every resume must declare the same value,
#: and the supervisor reads it back from ``RUN_META.json`` rather than inventing one.
DURATION_S = 240
MAX_CYCLES = 50
WINDOW_BARS = 20
WARMUP_MINUTES = 120
POLL_S = 5.0
MAX_RESTARTS = 8


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def rows(session: Path) -> list[dict[str, Any]]:
    return read_entries(session / "STREAM.jsonl")


def entries(session: Path) -> list[dict[str, Any]]:
    return [row["entry"] for row in rows(session)]


def cycle_numbers(session: Path) -> list[int]:
    return [
        int(entry["cycle"])
        for entry in entries(session)
        if entry.get("kind") == "CYCLE" and entry.get("cycle") is not None
    ]


def cycle_ledgers(session: Path) -> dict[str, dict[str, Any]]:
    return {
        f"cycle-{number:04d}": verify_chain(
            session / "cycles" / f"cycle-{number:04d}" / "ledger.jsonl"
        )
        for number in cycle_numbers(session)
    }


def locks(session: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in sorted(session.rglob("*.lock")):
        record = SingleWriter(path, purpose="supervisor-campaign").read()
        verdict = diagnose_lock(record)
        found.append(
            {
                "path": path.relative_to(session).as_posix(),
                "record": record,
                "state": verdict["state"],
                "reason": verdict["reason"],
                "pid": (record or {}).get("pid"),
                "token": (record or {}).get("token"),
                "fence": (record or {}).get("fence"),
                "process_start_ms": (record or {}).get("process_start_ms"),
            }
        )
    return found


def wait_for(predicate: Callable[[], bool], *, timeout_s: float, poll_s: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def journal(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "SUPERVISOR.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
    return out


def supervisor_argv(
    session: Path,
    state_dir: Path,
    *,
    start: bool,
    max_restarts: int,
    duration_s: int = DURATION_S,
    max_cycles: int = MAX_CYCLES,
    once: bool = False,
) -> list[str]:
    argv = [
        sys.executable,
        str(SUPERVISOR),
        "--session",
        str(session),
        "--state-dir",
        str(state_dir),
        "--root",
        str(REPO),
        "--max-restarts",
        str(max_restarts),
        "--backoff-base-s",
        "1.0",
        "--backoff-cap-s",
        "10.0",
        "--poll-s",
        "2.0",
        "--symbols",
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "--timeframe",
        "1m",
        "--window-bars",
        str(WINDOW_BARS),
        "--warmup-minutes",
        str(WARMUP_MINUTES),
        "--duration-s",
        str(duration_s),
        "--session-poll-s",
        str(POLL_S),
        "--max-cycles",
        str(max_cycles),
    ]
    if start:
        argv.append("--start")
    if once:
        argv.append("--once")
    return argv


def start_supervisor(
    session: Path, state_dir: Path, *, log: Path, start: bool, max_restarts: int, once: bool = False
) -> subprocess.Popen[bytes]:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as handle:
        process = windowless.spawn(
            supervisor_argv(session, state_dir, start=start, max_restarts=max_restarts, once=once),
            cwd=str(REPO),
            stdout=handle,
            stderr=subprocess.STDOUT,
            new_group=True,
        )
    return process


def kill_tree(pid: int) -> dict[str, Any]:
    completed = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "pid": pid,
        "taskkill_exit": completed.returncode,
        "detail": ((completed.stdout or "") + (completed.stderr or "")).strip()[:400],
        "alive_after": pid_alive(pid),
    }


def probe_live(session: Path) -> dict[str, Any]:
    """A real takeover attempt while the session runs: refusal, and no byte moved."""

    path = session / "STREAM.jsonl.lock"
    before = path.read_bytes() if path.is_file() else b""
    writer = SingleWriter(path, purpose="supervisor-campaign-probe")
    outcome: dict[str, Any] = {}
    try:
        result = writer.acquire()
    except LockRefused as exc:
        outcome = {"outcome": "REFUSED", "code": exc.code, "detail": str(exc)[:300]}
    else:  # pragma: no cover - would mean the running session lost its lock
        outcome = {"outcome": str(result.get("status")), "fence": result.get("fence")}
        writer.release()
    after = path.read_bytes() if path.is_file() else b""
    return {**outcome, "unchanged": before == after, "bytes": len(before)}


def run_campaign(args: argparse.Namespace) -> int:
    out = Path(args.out)
    session = out / "session"
    if (session / "STREAM.jsonl").exists():
        print(json.dumps({"error": "SESSION_ALREADY_EXISTS", "session": str(session)}))
        return 3
    session.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    state_dir = out / "supervisor"

    campaign: dict[str, Any] = {
        "schema_version": "TAP_PAPER_SUPERVISOR_CAMPAIGN_V1",
        "started_at_utc": utc_now(),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "entrypoint": ENTRYPOINT.relative_to(REPO).as_posix(),
        "supervisor": SUPERVISOR.relative_to(REPO).as_posix(),
        "mode": "PAPER",
        "live_orders": 0,
        "config": {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframe": "1m",
            "duration_s": DURATION_S,
            "max_cycles": MAX_CYCLES,
            "window_bars": WINDOW_BARS,
            "warmup_minutes": WARMUP_MINUTES,
            "poll_s": POLL_S,
            "max_restarts": MAX_RESTARTS,
        },
        "episodes": [],
    }
    write(out / "CAMPAIGN.json", campaign)

    #: Two supervisors over one directory, started within milliseconds. The runtime's own
    #: coordination lock decides; the loser must exit 4 without spawning anything.
    first = start_supervisor(
        session, state_dir, log=out / "supervisor-a.log", start=True, max_restarts=MAX_RESTARTS
    )
    second = start_supervisor(
        session, state_dir, log=out / "supervisor-b.log", start=True, max_restarts=MAX_RESTARTS
    )
    appeared = wait_for(
        lambda: any(row.get("event") == "ACQUIRED" for row in journal(state_dir)),
        timeout_s=60,
    )
    if not appeared:
        campaign["failure"] = "SUPERVISOR_NEVER_ACQUIRED"
        write(out / "CAMPAIGN.json", campaign)
        return 1

    winner = next(
        row["supervisor_pid"] for row in journal(state_dir) if row.get("event") == "ACQUIRED"
    )
    #: ``windowless.spawn`` returns a handle whose pid is the interpreter's launcher, and
    #: the journal records the pid the interpreter itself reports. Map the loser by handle,
    #: never by pid, and read its real identity from the REFUSED row.
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and first.poll() is None and second.poll() is None:
        time.sleep(0.5)
    if first.poll() is not None:
        loser_process, supervisor_process = first, second
    else:
        loser_process, supervisor_process = second, first
    with contextlib.suppress(subprocess.TimeoutExpired):
        loser_process.wait(timeout=60)
    refused_pid = next(
        (row.get("supervisor_pid") for row in journal(state_dir) if row.get("event") == "REFUSED"),
        None,
    )
    campaign["supervisor_race"] = {
        "spawn_pids": [first.pid, second.pid],
        "winner_pid": winner,
        "winner_spawn_pid": supervisor_process.pid,
        "loser_spawn_pid": loser_process.pid,
        "loser_real_pid": refused_pid,
        "loser_exit_code": loser_process.returncode,
        "loser_refused": bool(refused_pid),
        "loser_spawned": any(
            row.get("event") == "SPAWNED" and row.get("supervisor_pid") == refused_pid
            for row in journal(state_dir)
        ),
        "acquired_rows": sum(1 for row in journal(state_dir) if row.get("event") == "ACQUIRED"),
    }
    write(out / "SUPERVISOR_RACE.json", campaign["supervisor_race"])
    if loser_process.returncode != 4:
        campaign["failure"] = "LOSER_DID_NOT_REFUSE"
        write(out / "CAMPAIGN.json", campaign)
        return 1

    for index in range(1, int(args.crashes) + 1):
        episode: dict[str, Any] = {"episode": index, "started_at_utc": utc_now()}
        campaign["episodes"].append(episode)

        warmed = wait_for(
            lambda: session_status(session)["state"] == "RUNNING" and bool(cycle_numbers(session)),
            timeout_s=args.start_timeout_s,
        )
        if not warmed:
            episode["failure"] = "SESSION_NEVER_REACHED_A_CYCLE"
            write(out / "CAMPAIGN.json", campaign)
            return 1

        rows_before = len(rows(session))
        cycles_before = cycle_numbers(session)
        status_before = session_status(session)
        #: The lock names the process that holds it; the journal names the one the supervisor
        #: started. On this host they are not the same pid (the interpreter is launched
        #: through a trampoline), and killing the descendant would leave the session alive.
        spawned = [row for row in journal(state_dir) if row.get("event") == "SPAWNED"]
        owner_pid = spawned[-1]["pid"] if spawned else None
        episode["before"] = {
            "rows": rows_before,
            "cycles": cycles_before,
            "state": status_before["state"],
            "owner_pid": owner_pid,
            "lock_owner_pid": (status_before.get("owner") or {}).get("pid"),
            "fence": (status_before.get("owner") or {}).get("fence"),
        }
        episode["live_probe"] = probe_live(session)

        if not isinstance(owner_pid, int):
            episode["failure"] = "NO_OWNER_PID"
            write(out / "CAMPAIGN.json", campaign)
            return 1
        episode["killed"] = kill_tree(owner_pid)

        crashed = wait_for(
            lambda pid=owner_pid: any(
                row.get("event") == "CHILD_EXIT" and row.get("pid") == pid
                for row in journal(state_dir)
            ),
            timeout_s=120,
        )
        if not crashed:
            episode["failure"] = "SUPERVISOR_DID_NOT_NOTICE_THE_CRASH"
            write(out / "CAMPAIGN.json", campaign)
            return 1

        leftover = locks(session)
        episode["crash"] = {
            "rows": len(rows(session)),
            "cycles": cycle_numbers(session),
            "locks": leftover,
            "state": session_status(session)["state"],
            "abandoned": bool(leftover) and all(item["state"] == "ABANDONED" for item in leftover),
            "chain": verify_chain(session / "STREAM.jsonl"),
        }

        #: The last episode is not killed: the resumed session is allowed to finish, so the
        #: campaign can end with no locks and a clean stop.
        final = index == int(args.crashes)
        if final:
            break

        resumed = wait_for(
            lambda before=rows_before: any(
                row["seq"] == before + 1
                and entry.get("kind") == "SESSION_START"
                and (entry.get("provenance") or {}).get("resumed") is True
                for row, entry in zip(rows(session), entries(session), strict=False)
            ),
            timeout_s=args.resume_timeout_s,
        )
        if not resumed:
            episode["failure"] = "SUPERVISOR_DID_NOT_RESUME"
            write(out / "SUPERVISOR_STATE.json", {"journal": journal(state_dir)})
            write(out / "CAMPAIGN.json", campaign)
            return 1

        progressed = wait_for(
            lambda before=cycles_before: (
                len(cycle_numbers(session)) > len(before)
                and session_status(session)["state"] == "RUNNING"
            ),
            timeout_s=args.cycle_timeout_s,
        )
        if not progressed:
            episode["failure"] = "RESUMED_SESSION_NEVER_PRODUCED_A_CYCLE"
            write(out / "CAMPAIGN.json", campaign)
            return 1

        after = session_status(session)
        episode["after"] = {
            "rows": len(rows(session)),
            "cycles": cycle_numbers(session),
            "state": after["state"],
            "locks": [
                {"path": item["path"], "state": item["state"], "reason": item["reason"]}
                for item in locks(session)
            ],
            "chain": verify_chain(session / "STREAM.jsonl"),
            "cycle_ledgers": cycle_ledgers(session),
        }
        write(out / "episodes" / f"episode-{index:02d}.json", episode)
        write(out / "CAMPAIGN.json", campaign)

    #: The final resume owns the session. Let it end on its own: a clean exit is what turns
    #: five recoveries into a closed campaign instead of five crashes and a manual cleanup.
    final_cycle = cycle_numbers(session)[-1] if cycle_numbers(session) else 0
    finished = wait_for(
        lambda: session_status(session)["state"] in ("RECOVERED", "READY") and not locks(session),
        timeout_s=args.finish_timeout_s,
    )
    with contextlib.suppress(subprocess.TimeoutExpired):
        supervisor_process.wait(timeout=args.finish_timeout_s)
    campaign["supervisor_exit_code"] = supervisor_process.returncode
    campaign["final"] = {
        "rows": len(rows(session)),
        "cycles": cycle_numbers(session),
        "last_cycle_before_finish": final_cycle,
        "state": session_status(session)["state"],
        "locks": locks(session),
        "chain": verify_chain(session / "STREAM.jsonl"),
        "cycle_ledgers": cycle_ledgers(session),
        "result": read_json(state_dir / "SUPERVISOR_RESULT.json"),
        "finished_without_locks": bool(finished),
    }
    campaign["finished_at_utc"] = utc_now()
    write(out / "SUPERVISOR_STATE.json", {"journal": journal(state_dir)})
    write(out / "CAMPAIGN.json", campaign)
    print(
        json.dumps(
            {
                "episodes": len(campaign["episodes"]),
                "cycles": campaign["final"]["cycles"],
                "state": campaign["final"]["state"],
                "locks": len(campaign["final"]["locks"]),
                "supervisor": (campaign["final"]["result"] or {}).get("action"),
            },
            indent=2,
        )
    )
    return 0 if campaign["final"]["finished_without_locks"] else 1


def run_scenarios(args: argparse.Namespace) -> int:
    """The two cases that must *not* recover: corrupt evidence, exhausted budget."""

    out = Path(args.out)
    if out.exists() and (out / "SCENARIOS.json").exists():
        print(json.dumps({"error": "SCENARIOS_ALREADY_EXIST", "out": str(out)}))
        return 3
    out.mkdir(parents=True, exist_ok=True)
    scenarios: dict[str, Any] = {"started_at_utc": utc_now(), "scenarios": {}}

    # -- corrupt evidence ----------------------------------------------------
    corrupt_root = out / "corrupt"
    corrupt_session = corrupt_root / "session"
    source = Path(args.source_session) if args.source_session else out.parent / "session"
    if not (source / "STREAM.jsonl").is_file():
        print(json.dumps({"error": "NO_SOURCE_SESSION", "source": str(source)}))
        return 3
    shutil.copytree(source, corrupt_session)
    before_rows = len(rows(corrupt_session))
    #: A half-written line is what a kill between write and fsync leaves behind. The chain
    #: must report it and the supervisor must refuse, not replay a prefix it cannot trust.
    with (corrupt_session / "STREAM.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"seq": 999, "prev_sha256": "deadbeef", "ent')
    dead = _reaped_pid()
    (corrupt_session / "STREAM.jsonl.lock").write_text(
        json.dumps(
            {
                "schema_version": "TAP_SINGLE_WRITER_LOCK_V1",
                "purpose": "campaign-corrupt",
                "host": socket.gethostname(),
                "pid": dead,
                "process_start_ms": None,
                "token": "corrupt-owner" * 4,
                "fence": 1,
            }
        ),
        encoding="utf-8",
    )
    corrupt = start_supervisor(
        corrupt_session,
        corrupt_root / "supervisor",
        log=corrupt_root / "supervisor.log",
        start=False,
        max_restarts=3,
        once=True,
    )
    with contextlib.suppress(subprocess.TimeoutExpired):
        corrupt.wait(timeout=120)
    corrupt_state = session_status(corrupt_session)
    scenarios["scenarios"]["corrupt"] = {
        "source": str(source),
        "rows_before": before_rows,
        "rows_after": _readable_rows(corrupt_session),
        "state": corrupt_state["state"],
        "why": corrupt_state["why"],
        "exit_code": corrupt.returncode,
        "result": read_json(corrupt_root / "supervisor" / "SUPERVISOR_RESULT.json"),
        "spawned": [
            row for row in journal(corrupt_root / "supervisor") if row.get("event") == "SPAWNED"
        ],
        "stream_sha256": sha256_file(corrupt_session / "STREAM.jsonl"),
    }

    # -- retry budget --------------------------------------------------------
    budget_root = out / "budget"
    budget_session = budget_root / "session"
    budget_session.mkdir(parents=True, exist_ok=True)
    budget_state = budget_root / "supervisor"
    process = start_supervisor(
        budget_session,
        budget_state,
        log=budget_root / "supervisor.log",
        start=True,
        max_restarts=1,
    )
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        expected = attempts[-1]["starts"] + 1 if attempts else 1
        started = wait_for(
            lambda want=expected: (
                sum(1 for entry in entries(budget_session) if entry.get("kind") == "SESSION_START")
                >= want
            ),
            timeout_s=180,
        )
        if not started:
            attempts.append({"attempt": attempt, "failure": "NO_SESSION_START"})
            break
        owner = (session_status(budget_session).get("owner") or {}).get("pid")
        if not isinstance(owner, int):
            attempts.append({"attempt": attempt, "failure": "NO_OWNER_PID"})
            break
        #: Kill before the cycle exists: every attempt is a real crash, cheap in wall clock,
        #: and the supervisor must still spend its budget rather than restart forever.
        killed = kill_tree(owner)
        recorded = wait_for(
            lambda want=attempt: (
                sum(1 for row in journal(budget_state) if row.get("event") == "CHILD_EXIT") >= want
            ),
            timeout_s=120,
        )
        resumes = sum(
            1
            for row in journal(budget_state)
            if row.get("event") == "DECISION" and row.get("action") == "RESUME"
        )
        #: Either it resumes within its remaining budget or it stops; both are progress.
        settled = wait_for(
            lambda want=attempt, seen=resumes: process.poll() is not None or seen >= want,
            timeout_s=120,
        )
        attempts.append(
            {
                "attempt": attempt,
                "starts": sum(
                    1 for entry in entries(budget_session) if entry.get("kind") == "SESSION_START"
                ),
                "killed": killed,
                "recorded": recorded,
                "resumes": resumes,
                "settled": settled,
                "supervisor_exited": process.poll() is not None,
                "rows": len(rows(budget_session)),
            }
        )
        if process.poll() is not None:
            break
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=180)
    if process.poll() is None:  # pragma: no cover - the supervisor has its own budget stop
        windowless.terminate_tree(process)
    scenarios["scenarios"]["budget"] = {
        "exit_code": process.returncode,
        "attempts": attempts,
        "result": read_json(budget_state / "SUPERVISOR_RESULT.json"),
        "state": session_status(budget_session)["state"],
        "locks": [
            {"path": item["path"], "state": item["state"], "reason": item["reason"]}
            for item in locks(budget_session)
        ],
    }

    scenarios["finished_at_utc"] = utc_now()
    write(out / "SCENARIOS.json", scenarios)
    print(json.dumps(scenarios["scenarios"], indent=2, default=str)[:4000])
    corrupt_ok = scenarios["scenarios"]["corrupt"]["result"].get("action") == "STOP_FAILED"
    budget_ok = scenarios["scenarios"]["budget"]["result"].get("action") == "STOP_BUDGET"
    return 0 if corrupt_ok and budget_ok else 1


def _readable_rows(session: Path) -> int | None:
    """Rows that parse; the corrupt copy deliberately ends with a truncated line."""

    try:
        return len(rows(session))
    except json.JSONDecodeError:
        return None


def _reaped_pid() -> int:
    process = windowless.spawn([sys.executable, "-c", "pass"], cwd=str(REPO))
    process.wait()
    return int(process.pid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supervised PAPER crash campaign")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="crash the supervised session repeatedly")
    run.add_argument("--out", required=True)
    run.add_argument("--crashes", type=int, default=5)
    run.add_argument("--start-timeout-s", type=float, default=420.0)
    run.add_argument("--resume-timeout-s", type=float, default=420.0)
    run.add_argument("--cycle-timeout-s", type=float, default=420.0)
    run.add_argument("--finish-timeout-s", type=float, default=900.0)

    scenarios = sub.add_parser("scenarios", help="corrupt evidence and exhausted budget")
    scenarios.add_argument("--out", required=True)
    scenarios.add_argument("--source-session", default=None)

    args = parser.parse_args(argv)
    if args.command == "run":
        return run_campaign(args)
    if args.command == "scenarios":
        return run_scenarios(args)
    return 2  # pragma: no cover - argparse rejects anything else


if __name__ == "__main__":
    raise SystemExit(main())
