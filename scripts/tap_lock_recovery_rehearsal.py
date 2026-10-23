"""tap_lock_recovery_rehearsal — crash a real PAPER session, then resume it.

This is the operational evidence for the lock defect, not a unit test. It drives the
authoritative entrypoint (``scripts/def_run_019_prospective_run.py``) in a **separate
process**, kills that process tree with no warning (the way a power cut or an operator's
``Stop-Process -Force`` does), and then asks the same entrypoint to resume the same session
directory. Between the two runs it records every lock the crash left behind and the verdict
the recovery code reached about each one.

What it proves, in order:

1. the crash leaves locks (that is the defect's precondition);
2. each leftover is diagnosed ``ABANDONED`` with a reason (not "assumed stale");
3. the resume takes them over, writes ``LOCK_RECLAIMED`` into the chained stream, and
   continues the same session instead of starting a new one;
4. the chain still verifies and no sequence number is reused or skipped — a resume appends.

It does not touch capital, credentials or permissions: the entrypoint is PAPER-only and has
no path to a live order. It writes only under ``--out``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops.single_writer import SingleWriter, diagnose_lock  # noqa: E402
from trading_bot.vision.ledger import read_entries, verify_chain  # noqa: E402

ENTRYPOINT = REPO / "scripts" / "def_run_019_prospective_run.py"


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def start_session(
    out: Path, *, log: Path, resume: bool, duration_s: int, max_cycles: int, symbols: list[str]
) -> subprocess.Popen[bytes]:
    argv = [
        sys.executable,
        str(ENTRYPOINT),
        "--out",
        str(out),
        "--symbols",
        *symbols,
        "--timeframe",
        "1m",
        "--window-bars",
        "20",
        "--warmup-minutes",
        "120",
        "--duration-s",
        str(duration_s),
        "--poll-s",
        "5",
        "--max-cycles",
        str(max_cycles),
    ]
    if resume:
        argv.append("--resume")
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("wb")
    #: A process group, so the kill takes the interpreters the launcher started with it.
    return subprocess.Popen(
        argv,
        cwd=str(REPO),
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
    )


def kill_tree(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Terminate the whole tree with no chance to release anything."""

    pids = [proc.pid]
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        detail = (completed.stdout or "") + (completed.stderr or "")
    else:  # pragma: no cover - the host is Windows
        with contextlib.suppress(ProcessLookupError):
            #: ``killpg``/``SIGKILL`` are absent from the Windows stubs mypy reads here.
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # type: ignore[attr-defined]
        detail = "killpg SIGKILL"
    exit_code = proc.wait(timeout=120)
    return {"pids": pids, "detail": detail.strip()[:400], "exit_code": exit_code}


def stream_rows(out: Path) -> list[dict[str, Any]]:
    return read_entries(out / "STREAM.jsonl")


def locks_under(out: Path) -> list[dict[str, Any]]:
    """Every lock-shaped file the crash left behind, with the verdict on its owner."""

    found: list[dict[str, Any]] = []
    for path in sorted(out.rglob("*.lock")):
        lock = SingleWriter(path, purpose="audit")
        record = lock.read()
        verdict = diagnose_lock(record)
        found.append(
            {
                "path": path.relative_to(out).as_posix(),
                "bytes": path.stat().st_size,
                "owner_pid": (record or {}).get("pid"),
                "owner_host": (record or {}).get("host"),
                "owner_start_ms": (record or {}).get("process_start_ms"),
                "fence": (record or {}).get("fence"),
                "state": verdict["state"],
                "reason": verdict["reason"],
            }
        )
    return found


def wait_for_cycles(out: Path, count: int, *, timeout_s: float) -> tuple[int, float]:
    """Wait until the stream holds ``count`` CYCLE rows; returns (cycles, waited seconds)."""

    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        cycles = sum(1 for row in stream_rows(out) if row["entry"].get("kind") == "CYCLE")
        if cycles >= count:
            return cycles, round(time.monotonic() - started, 2)
        time.sleep(1.0)
    cycles = sum(1 for row in stream_rows(out) if row["entry"].get("kind") == "CYCLE")
    return cycles, round(time.monotonic() - started, 2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crash/reclaim/resume rehearsal")
    parser.add_argument(
        "--out",
        default=str(REPO / "reports" / "ai-bots" / "CODEX-PAPER-UNBLOCK-001" / "lock-recovery"),
    )
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--crash-duration-s", type=int, default=900)
    parser.add_argument("--resume-duration-s", type=int, default=300)
    parser.add_argument("--wait-cycle-timeout-s", type=float, default=420.0)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    session = out / "session"
    evidence: dict[str, Any] = {
        "schema_version": "TAP_LOCK_RECOVERY_REHEARSAL_V1",
        "started_at_utc": utc_now(),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "symbols": list(args.symbols),
        "entrypoint": ENTRYPOINT.relative_to(REPO).as_posix(),
        "live_orders": 0,
    }

    # ---- phase 1: run until at least one cycle is on disk, then crash -------------
    crash_log = out / "phase1-crash.log"
    proc = start_session(
        session,
        log=crash_log,
        resume=False,
        duration_s=args.crash_duration_s,
        max_cycles=6,
        symbols=list(args.symbols),
    )
    cycles, waited = wait_for_cycles(session, 1, timeout_s=args.wait_cycle_timeout_s)
    evidence["phase1"] = {
        "cycles_before_kill": cycles,
        "waited_s": waited,
        "process_pid": proc.pid,
        "log": crash_log.name,
    }
    if cycles < 1:
        evidence["phase1"]["killed"] = kill_tree(proc)
        evidence["verdict"] = "FAIL"
        evidence["failure"] = "NO_CYCLE_BEFORE_CRASH_TIMEOUT"
        evidence["tail"] = crash_log.read_text(encoding="utf-8", errors="replace")[-4000:]
        write(out / "REHEARSAL.json", evidence)
        print(json.dumps(evidence, indent=2))
        return 1
    evidence["phase1"]["killed"] = kill_tree(proc)
    evidence["phase1"]["stream_rows_at_crash"] = len(stream_rows(session))
    evidence["phase1"]["chain_at_crash"] = verify_chain(session / "STREAM.jsonl")

    # ---- phase 2: what did the crash leave, and what does the code think of it? ----
    leftover = locks_under(session)
    evidence["leftover_locks"] = leftover

    # ---- phase 3: resume the same directory with the same entrypoint --------------
    resume_log = out / "phase3-resume.log"
    resumed = start_session(
        session,
        log=resume_log,
        resume=True,
        duration_s=args.resume_duration_s,
        max_cycles=3,
        symbols=list(args.symbols),
    )
    try:
        resume_exit = resumed.wait(timeout=args.resume_duration_s + 420)
    except subprocess.TimeoutExpired:  # pragma: no cover - the session has its own deadline
        kill_tree(resumed)
        resume_exit = 124
    evidence["phase3"] = {
        "exit_code": resume_exit,
        "log": resume_log.name,
        "tail": resume_log.read_text(encoding="utf-8", errors="replace")[-4000:],
    }

    # ---- phase 4: does the evidence hold up? -------------------------------------
    rows = stream_rows(session)
    entries = [row["entry"] for row in rows]
    seqs = [int(row["seq"]) for row in rows]
    starts = [entry for entry in entries if entry.get("kind") == "SESSION_START"]
    reclaimed = [entry for entry in entries if entry.get("kind") == "LOCK_RECLAIMED"]
    chain = verify_chain(session / "STREAM.jsonl")
    after_crash = sum(1 for entry in entries if entry.get("kind") == "CYCLE")
    evidence["stream"] = {
        "rows": len(rows),
        "chain": chain,
        "seqs_are_1_to_n": seqs == list(range(1, len(seqs) + 1)),
        "session_starts": [
            {
                "session_id": entry.get("provenance", {}).get("session_id"),
                "resumed": entry.get("provenance", {}).get("resumed"),
            }
            for entry in starts
        ],
        "lock_reclaimed_rows": [
            {"scope": entry.get("scope"), "locks": entry.get("locks")} for entry in reclaimed
        ],
        "cycles_total": after_crash,
        "kinds": {
            kind: sum(1 for entry in entries if entry.get("kind") == kind)
            for kind in sorted({str(entry.get("kind")) for entry in entries})
        },
    }
    evidence["phase3"]["stream_rows_after_resume"] = len(rows)

    checks = {
        "leftover_locks_were_abandoned": bool(leftover)
        and all(item["state"] == "ABANDONED" for item in leftover),
        "resume_exited_zero": resume_exit == 0,
        "stream_chain_intact": bool(chain.get("ok")),
        "seq_continuous": evidence["stream"]["seqs_are_1_to_n"],
        "resume_was_a_continuation": any(
            item["resumed"] is True for item in evidence["stream"]["session_starts"]
        ),
        "reclaim_is_on_the_record": bool(reclaimed),
        "no_lock_left_after_resume": not locks_under(session),
    }
    evidence["checks"] = checks
    evidence["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    evidence["finished_at_utc"] = utc_now()
    write(out / "REHEARSAL.json", evidence)
    print(json.dumps({"verdict": evidence["verdict"], "checks": checks}, indent=2))
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
