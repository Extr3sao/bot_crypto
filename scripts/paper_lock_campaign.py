"""paper_lock_campaign — N forced terminations of a real PAPER session, each recovered.

The single-crash rehearsal proved the mechanism once. One observation of a distributed
property is not a property, and the failure an operator actually faces is not one crash: it
is a session that is started, killed, resumed, killed again, while the evidence has to stay
**one** chain — no repeated cycle, no duplicated decision, no residual lock, and no previous
owner still able to write.

Per iteration this harness does exactly what an operator does, in separate processes, with
no mocks:

1. start the authoritative entrypoint (``scripts/def_run_019_prospective_run.py``), fresh on
   the first iteration and with ``--resume`` afterwards;
2. while it runs, try to reclaim its stream lock from a *separate* interpreter — the runtime
   must refuse (the owner is alive) and must leave the record byte-identical;
3. wait for a new ``CYCLE`` row (or, on the designated interruption iteration, kill before
   any cycle is persisted — the other side of the persistence boundary);
4. kill the whole process tree with no warning and record every leftover lock, its owner and
   the verdict on that owner, how long the platform took to prove the owner gone, and the
   state of the chain at the moment of the crash;
5. optionally race two interpreters to reclaim the abandoned lock (exactly one may win);
6. resume the same directory with the same entrypoint, then — while the new owner holds the
   lock — present the *old* owner's record and require ``LOCK_LOST`` and a refused release;
7. wait for a clean exit, then re-read the chain, the cycle numberings, the fences and the
   session status, and assert no lock is left.

Every iteration writes its own ``POST_CRASH.json`` / ``RECOVERY.json``. Nothing is reused
from a previous campaign: ``run`` refuses a session directory that already has a stream.

What this harness does *not* claim: it does not certify strategy, economics or admission.
It writes ``live_orders = 0`` because the entrypoint is PAPER-only and has no order path.

Usage::

    python scripts/paper_lock_campaign.py run --out reports/.../campaign
    python scripts/paper_lock_campaign.py probe-reclaim PATH      # one refusal probe
    python scripts/paper_lock_campaign.py probe-race PATH 2       # two racers
    python scripts/paper_lock_campaign.py probe-stale PATH OLD.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops import windowless  # noqa: E402
from trading_bot.ops.session_status import session_status  # noqa: E402
from trading_bot.ops.single_writer import (  # noqa: E402
    LockLost,
    LockRefused,
    SingleWriter,
    diagnose_lock,
    pid_alive,
)
from trading_bot.vision.ledger import read_entries, verify_chain  # noqa: E402

ENTRYPOINT = REPO / "scripts" / "def_run_019_prospective_run.py"

#: Both the crash run and the resume run MUST declare the same values: ``duration_s`` and
#: ``max_cycles`` are part of the pinned identity, so a resume that declares different
#: numbers is refused ``CONFIG_CHANGED`` before it touches a lock.
DURATION_S = 300
MAX_CYCLES = 2
WINDOW_BARS = 20
WARMUP_MINUTES = 120
POLL_S = 5.0


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def session_rows(session: Path) -> list[dict[str, Any]]:
    return read_entries(session / "STREAM.jsonl")


def rows_of(session: Path, kind: str) -> list[dict[str, Any]]:
    return [row for row in session_rows(session) if row["entry"].get("kind") == kind]


def cycles_exceed(session: Path, count: int) -> bool:
    """Predicate for ``wait_for``: has this session persisted more than ``count`` cycles?"""

    return len(cycle_numbers(session)) > count


def cycle_numbers(session: Path) -> list[int]:
    return [
        int(entry["cycle"])
        for entry in (row["entry"] for row in session_rows(session))
        if entry.get("kind") == "CYCLE" and entry.get("cycle") is not None
    ]


def locks_snapshot(root: Path) -> list[dict[str, Any]]:
    """Every lock-shaped file, with its full record and the verdict on its owner."""

    found: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.lock")):
        record = SingleWriter(path, purpose="campaign-audit").read()
        verdict = diagnose_lock(record)
        found.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "record": record,
                "state": verdict["state"],
                "reason": verdict["reason"],
                "owner_pid": (record or {}).get("pid"),
                "owner_start_ms": (record or {}).get("process_start_ms"),
                "owner_host": (record or {}).get("host"),
                "token": (record or {}).get("token"),
                "fence": (record or {}).get("fence"),
                "owner_alive_now": (
                    pid_alive(int((record or {}).get("pid")))
                    if isinstance((record or {}).get("pid"), int)
                    else None
                ),
            }
        )
    return found


def fence_snapshot(root: Path) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for path in sorted(root.rglob("*.lock.fence")):
        try:
            out[path.relative_to(root).as_posix()] = int(
                path.read_text(encoding="utf-8").strip() or 0
            )
        except (OSError, ValueError):
            out[path.relative_to(root).as_posix()] = None
    return out


def wait_for_abandoned(
    session: Path, *, timeout_s: float
) -> tuple[list[dict[str, Any]], float | None]:
    """Poll until every leftover lock is *proved* abandoned, or report what is still held."""

    started = time.monotonic()
    found = locks_snapshot(session)
    while found and not all(item["state"] == "ABANDONED" for item in found):
        if time.monotonic() - started >= timeout_s:
            return found, None
        time.sleep(0.2)
        found = locks_snapshot(session)
    return found, round(time.monotonic() - started, 2)


def wait_for(predicate, *, timeout_s: float, poll_s: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def start_session(
    session: Path, *, log: Path, resume: bool, symbols: list[str]
) -> subprocess.Popen[bytes]:
    argv = [
        sys.executable,
        str(ENTRYPOINT),
        "--out",
        str(session),
        "--symbols",
        *symbols,
        "--timeframe",
        "1m",
        "--window-bars",
        str(WINDOW_BARS),
        "--warmup-minutes",
        str(WARMUP_MINUTES),
        "--duration-s",
        str(DURATION_S),
        "--poll-s",
        str(POLL_S),
        "--max-cycles",
        str(MAX_CYCLES),
    ]
    if resume:
        argv.append("--resume")
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("wb")
    process = windowless.spawn(
        argv,
        cwd=str(REPO),
        stdout=handle,
        stderr=subprocess.STDOUT,
        new_group=True,
    )
    handle.close()
    return process


def kill_tree(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Terminate the whole tree with no chance to release anything."""

    already_exited = process.poll() is not None
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        detail = ((completed.stdout or "") + (completed.stderr or "")).strip()[:600]
        taskkill_exit: int | None = completed.returncode
    else:  # pragma: no cover - this host is Windows
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)  # type: ignore[attr-defined]
        detail = "killpg SIGKILL"
        taskkill_exit = None
    try:
        exit_code: int | None = process.wait(timeout=120)
    except subprocess.TimeoutExpired:  # pragma: no cover - the tree is being killed
        exit_code = None
    return {
        "pid": process.pid,
        "already_exited_before_kill": already_exited,
        "taskkill_exit": taskkill_exit,
        "detail": detail,
        "exit_code": exit_code,
        "main_pid_alive_after": pid_alive(process.pid),
    }


# -------------------------------------------------------------------------- probes


def probe_reclaim(path: Path, *, hold_s: float = 0.0) -> dict[str, Any]:
    """Take one lock through the real guard, hold it, and release it.

    The outcome is the guard's own vocabulary — ``ACQUIRED`` (nobody held it) versus
    ``RECLAIMED`` (a proved-abandoned owner was dispossessed) versus ``REFUSED`` with a code.
    Calling a fresh acquisition "reclaimed" would make two sequential, perfectly legal
    takeovers look like two simultaneous writers, so the distinction is kept.
    """

    lock = SingleWriter(path, purpose="campaign-probe")
    try:
        result = lock.acquire()
    except LockRefused as exc:
        return {"outcome": "REFUSED", "code": exc.code, "detail": str(exc)[:400]}
    acquired_at = utc_now()
    started = time.monotonic()
    try:
        if hold_s:
            time.sleep(hold_s)
    finally:
        released = lock.release()
    return {
        "outcome": str(result.get("status")),
        "acquired_at_utc": acquired_at,
        "held_s": round(time.monotonic() - started, 3),
        "released": released,
        "fence": result.get("fence"),
        "previous_owner": result.get("previous_owner"),
        "reason": result.get("reason"),
    }


def probe_live(path: Path) -> dict[str, Any]:
    """Attempt a takeover of a lock that is supposed to be *held*, and prove no damage."""

    before_path = path
    before = SingleWriter(before_path, purpose="campaign-probe").read()
    out = probe_reclaim(before_path)
    after = SingleWriter(before_path, purpose="campaign-probe").read()
    return {
        "path": str(before_path),
        "before": before,
        "after": after,
        "unchanged": before == after,
        **out,
    }


def probe_stale(path: Path, old_record: dict[str, Any]) -> dict[str, Any]:
    """Present a previous owner's record to the live guard: it must fail closed."""

    writer = SingleWriter(path, purpose="campaign-stale-probe")
    writer.token = str(old_record.get("token") or "")
    writer.fence = int(old_record.get("fence") or 0)
    writer.record = dict(old_record)
    lock_lost: dict[str, Any] = {}
    try:
        writer.assert_held()
    except LockLost as exc:
        lock_lost = {"raised": True, "code": exc.code, "detail": str(exc)[:400]}
    released = writer.release()
    still = SingleWriter(path, purpose="campaign-stale-probe").read()
    return {
        "path": str(path),
        "old_token": writer.token,
        "old_fence": writer.fence,
        "lock_lost": lock_lost,
        "release_refused": released is False,
        "lock_still_present": still is not None,
        "current": still,
    }


def race_reclaim(path: Path, *, racers: int, hold_s: float, out: Path) -> dict[str, Any]:
    """Spawn independent interpreters that all try to take the same abandoned lock.

    The winner holds it for ``hold_s`` *before* releasing, so a loser's attempt lands inside
    a real ownership window rather than after it: that is the only way the evidence can
    distinguish "refused because somebody holds it" from "took it later, one at a time".
    """

    go = out / f"go-{uuid_suffix()}"
    reports = [out / f"race-{index}-{uuid_suffix()}.json" for index in range(racers)]
    children = [
        subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "probe-race-child",
                "--lock",
                str(path),
                "--go",
                str(go),
                "--hold-s",
                str(hold_s),
                "--out",
                str(report),
            ],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for report in reports
    ]
    time.sleep(1.0)
    go.write_text("go\n", encoding="utf-8")
    for child in children:
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=60)
    return {
        "path": str(path),
        "racers": racers,
        "outcomes": [json.loads(report.read_text(encoding="utf-8")) for report in reports if report.exists()],
        "children_exit_codes": [child.returncode for child in children],
    }


def uuid_suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def race_child(lock: Path, go: Path, hold_s: float) -> dict[str, Any]:
    if not wait_for(go.exists, timeout_s=30, poll_s=0.005):
        return {"outcome": "NO_GO"}
    result = probe_reclaim(lock, hold_s=hold_s)
    return {"pid": os.getpid(), **result}


# ------------------------------------------------------------------- the campaign


def iteration_dir(out: Path, index: int) -> Path:
    return out / "iterations" / f"iteration-{index:02d}"


def run_campaign(args: argparse.Namespace) -> int:
    out = Path(args.out)
    session = out / "session"
    if (session / "STREAM.jsonl").exists():
        print(json.dumps({"error": "SESSION_ALREADY_EXISTS", "session": str(session)}))
        return 3
    session.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    campaign: dict[str, Any] = {
        "schema_version": "TAP_PAPER_LOCK_CAMPAIGN_V1",
        "started_at_utc": utc_now(),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "entrypoint": ENTRYPOINT.relative_to(REPO).as_posix(),
        "mode": "PAPER",
        "live_orders": 0,
        "symbols": list(args.symbols),
        "config": {
            "duration_s": DURATION_S,
            "max_cycles": MAX_CYCLES,
            "window_bars": WINDOW_BARS,
            "warmup_minutes": WARMUP_MINUTES,
            "poll_s": POLL_S,
            "timeframe": "1m",
        },
        "iterations": [],
    }
    write(out / "CAMPAIGN.json", campaign)

    for index, mode in enumerate(args.modes, start=1):
        target = iteration_dir(out, index)
        target.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "iteration": index,
            "mode": mode,
            "resume": index > 1,
            "started_at_utc": utc_now(),
        }
        campaign["iterations"].append(record)
        write(out / "CAMPAIGN.json", campaign)

        rows_before = len(session_rows(session))
        cycles_before = cycle_numbers(session)
        status_before_launch = session_status(session)
        write(target / "STATUS_BEFORE_LAUNCH.json", status_before_launch)

        crash_log = target / "crash.log"
        process = start_session(session, log=crash_log, resume=index > 1, symbols=list(args.symbols))
        record["launch"] = {
            "pid": process.pid,
            "started_at_utc": utc_now(),
            "resume": index > 1,
            "rows_before": rows_before,
            "cycles_before": cycles_before,
        }
        write(target / "LAUNCH.json", record)

        started = wait_for(
            lambda before=rows_before: len(session_rows(session)) > before, timeout_s=120
        )
        if not started:
            record["failure"] = "NO_SESSION_START"
            record["tail"] = crash_log.read_text(encoding="utf-8", errors="replace")[-3000:]
            write(target / "POST_CRASH.json", record)
            break

        # The stream lock is held by the running session. A takeover attempt must be refused
        # and must not change one byte of the record; this is the live-owner invariant asked
        # of the *real* guard while a *real* session runs.
        stream_lock = session / "STREAM.jsonl.lock"
        wait_for(
            lambda lock_path=stream_lock: diagnose_lock(SingleWriter(lock_path).read())["state"]
            == "HELD",
            timeout_s=60,
        )
        live_probe = {
            "stream": probe_live(stream_lock),
            "cycles": [],
        }
        for symbol in args.symbols[:2]:
            cycle_lock = session / "market-1m" / f"{symbol}.jsonl.lock"
            #: Only a lock that is actually held is a valid live-owner probe. Probing an
            #: absent one would *acquire* it, which is the opposite of the test.
            if diagnose_lock(SingleWriter(cycle_lock).read())["state"] != "HELD":
                live_probe["cycles"].append(
                    {"path": str(cycle_lock), "outcome": "NOT_HELD", "unchanged": True}
                )
                continue
            live_probe["cycles"].append(probe_live(cycle_lock))
        write(target / "LIVE_OWNER.json", live_probe)
        record["live_owner"] = {
            "stream_outcome": live_probe["stream"]["outcome"],
            "stream_unchanged": live_probe["stream"]["unchanged"],
            "harness_locks": [
                {"outcome": item["outcome"], "unchanged": item["unchanged"]}
                for item in live_probe["cycles"]
            ],
        }

        if mode == "before_cycle":
            # Die on the far side of the persistence boundary: the session has started and
            # written its head, but no cycle exists yet.
            time.sleep(max(0.0, float(args.before_cycle_wait_s)))
            reached = "BEFORE_CYCLE"
        else:
            reached = (
                "AFTER_CYCLE"
                if wait_for(
                    partial(cycles_exceed, session, len(cycles_before)),
                    timeout_s=args.wait_cycle_timeout_s,
                    poll_s=0.2,
                )
                else "CYCLE_TIMEOUT"
            )
        if reached == "CYCLE_TIMEOUT":
            record["failure"] = "NO_CYCLE_BEFORE_CRASH"
            record["tail"] = crash_log.read_text(encoding="utf-8", errors="replace")[-3000:]
            kill_tree(process)
            write(target / "POST_CRASH.json", record)
            break

        killed = kill_tree(process)
        record["crash_site"] = reached
        record["killed"] = killed
        leftover, abandoned_after_s = wait_for_abandoned(
            session, timeout_s=args.wait_abandoned_timeout_s
        )
        record["abandoned_after_s"] = abandoned_after_s
        record["leftovers"] = leftover
        record["chain_at_crash"] = verify_chain(session / "STREAM.jsonl")
        record["cycles_at_crash"] = cycle_numbers(session)
        record["rows_at_crash"] = len(session_rows(session))
        write(target / "POST_CRASH.json", record)

        if killed["already_exited_before_kill"]:
            record["failure"] = "PROCESS_EXITED_BEFORE_KILL"
            break
        if abandoned_after_s is None or not all(
            item["state"] == "ABANDONED" for item in leftover
        ):
            record["failure"] = "OWNER_NOT_PROVED_GONE"
            break

        if args.race_iterations and index in args.race_iterations:
            race = race_reclaim(stream_lock, racers=2, hold_s=4.0, out=target)
            write(target / "CONCURRENCY.json", race)
            record["concurrency"] = {
                "outcomes": [item.get("outcome") for item in race["outcomes"]],
                "reclaimers": sum(
                    1 for item in race["outcomes"] if item.get("outcome") == "RECLAIMED"
                ),
            }

        status_at_crash = session_status(session)
        write(target / "STATUS_AT_CRASH.json", status_at_crash)
        record["status_at_crash"] = status_at_crash["state"]

        old_stream = next(
            (item["record"] for item in leftover if item["path"] == "STREAM.jsonl.lock"), None
        )

        resume_log = target / "resume.log"
        resumed = start_session(session, log=resume_log, resume=True, symbols=list(args.symbols))
        record["resume"] = {"pid": resumed.pid, "started_at_utc": utc_now()}

        # While the new owner holds the lock, the *old* owner presents itself. Ownership is
        # fenced, so its guard must refuse; a probe that succeeded would be a silent fork.
        if old_stream:
            appeared = wait_for(
                lambda lock_path=stream_lock, old=old_stream: (
                    (SingleWriter(lock_path).read() or {}).get("token")
                    not in (None, old.get("token"))
                    and diagnose_lock(SingleWriter(lock_path).read())["state"] == "HELD"
                ),
                timeout_s=120,
            )
            stale = probe_stale(stream_lock, old_stream) if appeared else {"error": "NEW_OWNER_NEVER_APPEARED"}
            write(target / "STALE_OWNER.json", stale)
            record["stale_owner"] = {
                "raised": bool((stale.get("lock_lost") or {}).get("raised")),
                "code": (stale.get("lock_lost") or {}).get("code"),
                "release_refused": stale.get("release_refused"),
                "lock_still_present": stale.get("lock_still_present"),
            }

        try:
            resume_exit = resumed.wait(timeout=DURATION_S + 420)
        except subprocess.TimeoutExpired:  # pragma: no cover - the session has its own deadline
            kill_tree(resumed)
            resume_exit = 124
        record["resume"]["exit_code"] = resume_exit

        rows_after = session_rows(session)
        status_after = session_status(session)
        remaining = locks_snapshot(session)
        write(
            target / "RECOVERY.json",
            {
                "iteration": index,
                "resume_pid": resumed.pid,
                "exit_code": resume_exit,
                "rows_before_resume": record["rows_at_crash"],
                "rows_after_resume": len(rows_after),
                "new_rows": [row["entry"].get("kind") for row in rows_after[record["rows_at_crash"] :]],
                "cycle_numbers": cycle_numbers(session),
                "reclaimed": [
                    {"seq": row["seq"], "entry": row["entry"]}
                    for row in rows_after
                    if row["entry"].get("kind") == "LOCK_RECLAIMED"
                    and int(row["seq"]) > record["rows_at_crash"]
                ],
                "chain_after": verify_chain(session / "STREAM.jsonl"),
                "fences_after": fence_snapshot(session),
                "locks_after": remaining,
                "status_after": status_after,
                "tail": resume_log.read_text(encoding="utf-8", errors="replace")[-3000:],
            },
        )
        record["after"] = {
            "rows": len(rows_after),
            "cycles": cycle_numbers(session),
            "locks": len(remaining),
            "state": status_after["state"],
            "exit_code": resume_exit,
        }
        write(out / "CAMPAIGN.json", campaign)

        if resume_exit != 0 or remaining:
            break

    campaign["finished_at_utc"] = utc_now()
    campaign["final_status"] = session_status(session)
    campaign["final_locks"] = locks_snapshot(session)
    campaign["chains"] = {
        "stream": verify_chain(session / "STREAM.jsonl"),
        "cycle_numbers": cycle_numbers(session),
        "fences": fence_snapshot(session),
    }
    write(out / "CAMPAIGN.json", campaign)
    print(
        json.dumps(
            {
                "iterations": len(campaign["iterations"]),
                "state": campaign["final_status"]["state"],
                "cycles": campaign["chains"]["cycle_numbers"],
                "locks": len(campaign["final_locks"]),
            },
            indent=2,
        )
    )
    return 0 if campaign["final_status"]["state"] in ("RECOVERED", "READY") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repeated-crash PAPER lock campaign")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the campaign")
    run.add_argument("--out", required=True)
    run.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    run.add_argument(
        "--modes",
        nargs="*",
        default=[
            "after_cycle",
            "after_cycle",
            "before_cycle",
            "after_cycle",
            "after_cycle",
            "after_cycle",
        ],
        help="crash site per iteration; before_cycle kills before any cycle is persisted",
    )
    run.add_argument("--wait-cycle-timeout-s", type=float, default=420.0)
    run.add_argument("--wait-abandoned-timeout-s", type=float, default=90.0)
    run.add_argument("--before-cycle-wait-s", type=float, default=6.0)
    run.add_argument(
        "--race-iterations",
        nargs="*",
        type=int,
        default=[2, 5],
        help="iterations that also race two reclaimers over the abandoned lock",
    )

    one = sub.add_parser("probe-reclaim", help="attempt the real recovery once")
    one.add_argument("--lock", required=True)

    race = sub.add_parser("probe-race", help="race independent interpreters for one lock")
    race.add_argument("--lock", required=True)
    race.add_argument("--racers", type=int, default=2)
    race.add_argument("--hold-s", type=float, default=2.0)
    race.add_argument("--out", required=True)

    stale = sub.add_parser("probe-stale", help="present a previous owner's record")
    stale.add_argument("--lock", required=True)
    stale.add_argument("--record", required=True)

    child = sub.add_parser("probe-race-child", help=argparse.SUPPRESS)
    child.add_argument("--lock", required=True)
    child.add_argument("--go", required=True)
    child.add_argument("--hold-s", type=float, default=2.0)
    child.add_argument("--out", required=True)

    args = parser.parse_args(argv)

    if args.command == "run":
        return run_campaign(args)
    if args.command == "probe-reclaim":
        payload = probe_reclaim(Path(args.lock))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["outcome"] == "REFUSED" else 3
    if args.command == "probe-race":
        payload = race_reclaim(
            Path(args.lock), racers=args.racers, hold_s=args.hold_s, out=Path(args.out)
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        winners = sum(1 for item in payload["outcomes"] if item.get("outcome") == "RECLAIMED")
        return 0 if winners == 1 else 3
    if args.command == "probe-stale":
        payload = probe_stale(
            Path(args.lock),
            json.loads(Path(args.record).read_text(encoding="utf-8")),
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if (payload["lock_lost"] or {}).get("raised") else 3
    if args.command == "probe-race-child":
        result = race_child(Path(args.lock), Path(args.go), args.hold_s)
        write(Path(args.out), result)
        return 0
    return 2  # pragma: no cover - argparse rejects anything else


if __name__ == "__main__":
    raise SystemExit(main())
