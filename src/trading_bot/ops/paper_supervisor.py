"""ops.paper_supervisor — keep a PAPER session alive, or stop with a reason.

A crashed session is recoverable because the runtime proves the old owner gone before it
takes the lock (``CODEX-PAPER-LOCK-CAMPAIGN-001``). What was still manual was *noticing*:
somebody had to read the state and type ``--resume``. This module is that operator,
reduced to the smallest policy that is safe:

``RUNNING``      a live owner holds a lock. Never intervene — a second writer is exactly
                 what ``SingleWriter`` exists to refuse.
``RECOVERING``   a lock was left behind and its owner is *proved* gone
                 (``ABANDONED``). Re-check the evidence, then resume.
``FAILED``       the chain is broken or the last attempt refused. Never restart: a restart
                 would replay a prefix that no longer matches and call it a recovery.
``RECOVERED`` / ``READY``
                 nothing is waiting. If the last attempt ended cleanly the session is
                 finished; if it never recorded an outcome the state is ambiguous.
``ABSENT``       nothing ran here. Only ``--start`` may create a session.
``UNATTRIBUTED``
                 a lock names no owner this host can verify. Fail closed: it is not
                 permission to recover, and deleting it could corrupt a live writer.

The supervisor never edits evidence. It does not rebuild a broken chain, delete a lock,
rewrite a stream, or count "I started a process" as a recovery: after each child exits it
re-reads the artefacts and requires a new ``SESSION_START`` with ``resumed: true`` at
exactly the next sequence number, more rows than before, and no lock left behind. A clean
exit that produced nothing is a failure (``NO_PROGRESS``), not a success.

Its own state — journal, result, coordination lock — lives in a **sibling** directory
(``<session>.supervisor``) on purpose: ``session_status`` walks the session tree for
``*.lock`` files, and a supervisor lock inside it would be reported as a live writer.
The diagnosis must not be given a second opinion about who is writing.

Usage (the CLI is ``scripts/paper_supervisor.py``)::

    supervisor = Supervisor(session=out, state_dir=out.with_suffix(".supervisor"), ...)
    result = supervisor.run()
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.ops import windowless
from trading_bot.ops.session_status import (
    ABSENT,
    FAILED,
    READY,
    RECOVERED,
    RECOVERING,
    RUNNING,
    session_status,
)
from trading_bot.ops.single_writer import LockRefused, SingleWriter
from trading_bot.vision.ledger import read_entries

__all__ = [
    "ACTIONS",
    "ALREADY_ACTIVE",
    "OBSERVE",
    "RESUME",
    "START",
    "STOP_AMBIGUOUS",
    "STOP_BLOCKED",
    "STOP_BUDGET",
    "STOP_COMPLETED",
    "STOP_FAILED",
    "STOP_NO_PROGRESS",
    "STOP_NO_SESSION",
    "STOP_OPERATOR",
    "Policy",
    "Supervisor",
    "classify",
    "entrypoint_argv",
]

SCHEMA_VERSION = "TAP_PAPER_SUPERVISOR_V1"
JOURNAL_SCHEMA = "TAP_PAPER_SUPERVISOR_JOURNAL_V1"

OBSERVE = "OBSERVE"
RESUME = "RESUME"
START = "START"
ALREADY_ACTIVE = "ALREADY_ACTIVE"

STOP_COMPLETED = "STOP_COMPLETED"
STOP_FAILED = "STOP_FAILED"
STOP_AMBIGUOUS = "STOP_AMBIGUOUS"
STOP_BLOCKED = "STOP_BLOCKED"
STOP_NO_SESSION = "STOP_NO_SESSION"
STOP_BUDGET = "STOP_BUDGET"
STOP_NO_PROGRESS = "STOP_NO_PROGRESS"
STOP_OPERATOR = "STOP_OPERATOR"

ACTIONS = (
    OBSERVE,
    RESUME,
    START,
    ALREADY_ACTIVE,
    STOP_COMPLETED,
    STOP_FAILED,
    STOP_AMBIGUOUS,
    STOP_BLOCKED,
    STOP_NO_SESSION,
    STOP_BUDGET,
    STOP_NO_PROGRESS,
    STOP_OPERATOR,
)

STOP_ACTIONS = frozenset(
    action for action in ACTIONS if action.startswith("STOP_") or action == ALREADY_ACTIVE
)

#: Exit codes an operator can act on without reading a log.
EXIT_OK = 0
EXIT_NOTHING_TO_DO = 2
EXIT_REFUSED = 3
EXIT_ALREADY_ACTIVE = 4

ENTRYPOINT = Path("scripts") / "def_run_019_prospective_run.py"


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class Policy:
    """The limits a restart loop must have before it is allowed to exist."""

    max_restarts: int = 3
    backoff_base_s: float = 2.0
    backoff_cap_s: float = 30.0
    poll_s: float = 1.0
    child_timeout_s: float = 3_600.0
    #: How long to wait for a *foreign* owner that is not our child. ``None`` waits.
    observe_timeout_s: float | None = None

    def __post_init__(self) -> None:
        if self.max_restarts < 0:
            raise ValueError("max_restarts cannot be negative")
        if self.backoff_base_s < 0 or self.backoff_cap_s < 0:
            raise ValueError("backoff cannot be negative")
        if self.poll_s <= 0:
            raise ValueError("poll_s must be positive")

    def backoff_s(self, failures: int) -> float:
        if failures <= 0:
            return 0.0
        return float(min(self.backoff_cap_s, self.backoff_base_s * (2 ** (failures - 1))))


def classify(
    status: Mapping[str, Any],
    *,
    restarts_done: int,
    policy: Policy,
    allow_start: bool = False,
) -> dict[str, Any]:
    """Decide what to do from a session status, and say why.

    Pure on purpose: every branch below is unit-tested against a status payload, so the
    policy that moves a crashed session is not entangled with the process that runs it.
    """

    state = str(status.get("state") or "")
    ledger = status.get("ledger") or {}
    session = status.get("session") or {}
    waiting = list((status.get("locks") or {}).get("awaiting_recovery") or [])
    last = status.get("last_attempt") or {}

    if state == FAILED:
        return _decision(STOP_FAILED, "STATE_FAILED", status.get("why") or [])

    if state == RUNNING:
        return _decision(OBSERVE, "LIVE_OWNER", ["a lock is held by a live owner"])

    if state == RECOVERING:
        unattributed = [item for item in waiting if item.get("state") != "ABANDONED"]
        if unattributed:
            return _decision(
                STOP_AMBIGUOUS,
                "LOCK_NOT_ATTRIBUTABLE",
                [
                    f"{item.get('path')}: {item.get('state')}/{item.get('reason')}"
                    for item in unattributed
                ],
            )
        problem = _ledger_problem(ledger)
        if problem:
            return _decision(STOP_FAILED, problem[0], problem[1])
        if not session.get("pinned_identity"):
            return _decision(
                STOP_AMBIGUOUS,
                "NO_PINNED_IDENTITY",
                ["a resume would claim an identity this session never pinned"],
            )
        if restarts_done >= policy.max_restarts:
            return _decision(
                STOP_BUDGET,
                "RETRY_BUDGET_EXHAUSTED",
                [f"{restarts_done} of {policy.max_restarts} restarts already spent"],
            )
        return _decision(
            RESUME,
            "ABANDONED_LOCK_PROVED",
            [f"{item.get('path')}: {item.get('reason')}" for item in waiting],
        )

    if state in (RECOVERED, READY):
        #: "Completed" means the evidence is intact as well as the exit status: a stream
        #: that claims a cycle whose ledger is missing has not finished, whatever it says.
        problem = _ledger_problem(ledger)
        if problem:
            return _decision(STOP_FAILED, problem[0], problem[1])
        exit_code = last.get("exit_code")
        if last.get("refused") or last.get("aborted"):
            return _decision(
                STOP_FAILED,
                "LAST_ATTEMPT_REFUSED",
                [f"refused={last.get('refused')} aborted={last.get('aborted')}"],
            )
        if exit_code == 0:
            return _decision(STOP_COMPLETED, "CLEAN_END", ["the last attempt exited 0"])
        if exit_code == 2:
            return _decision(
                STOP_BLOCKED,
                "NO_CYCLE_EXECUTED",
                ["the last attempt ran but could not execute a cycle"],
            )
        if exit_code is None:
            return _decision(
                STOP_AMBIGUOUS,
                "NO_RECORDED_OUTCOME",
                ["a lock-free session with no RUN_RESULT cannot be classified"],
            )
        return _decision(STOP_FAILED, "NONZERO_END", [f"the last attempt exited {exit_code}"])

    if state == ABSENT:
        if allow_start:
            return _decision(START, "NO_SESSION_YET", ["nothing has run in this directory"])
        return _decision(STOP_NO_SESSION, "NOTHING_TO_SUPERVISE", ["no session and --start absent"])

    return _decision(STOP_AMBIGUOUS, "UNKNOWN_STATE", [f"state={state!r}"])


def _decision(action: str, reason: str, detail: Sequence[Any]) -> dict[str, Any]:
    return {"action": action, "reason": reason, "detail": [str(item) for item in detail]}


def _ledger_problem(ledger: Mapping[str, Any]) -> tuple[str, list[str]] | None:
    """Name the first integrity defect in a stream summary, or nothing."""

    if ledger.get("chain_ok") is not True:
        return ("LEDGER_CHAIN_BROKEN", [f"reason={ledger.get('chain_reason')}"])
    if not ledger.get("seq_continuous"):
        return ("SEQ_NOT_CONTINUOUS", ["the stream has a gap"])
    if ledger.get("cycle_ledgers_ok") is not True:
        return ("CYCLE_LEDGER_BROKEN", [f"cycles={ledger.get('cycles')}"])
    return None


def entrypoint_argv(
    config: Mapping[str, Any],
    *,
    out_dir: Path,
    entrypoint: Path,
    python: str | None = None,
    resume: bool,
) -> list[str]:
    """Rebuild the exact invocation from the configuration the session pinned.

    The configuration fingerprint covers ``duration_s``, ``max_cycles`` and the rest, so a
    supervisor that invented any of them would be refused ``CONFIG_CHANGED`` before it
    touched a lock. Reading the pinned payload is therefore not a convenience: it is the
    only way a resume can prove it continues the same session.
    """

    mode = str(config.get("mode") or "").upper()
    if mode != "PAPER":
        raise ValueError(f"paper_supervisor refuses mode {mode!r}: this supervisor is PAPER only")
    argv = [
        python or sys.executable,
        str(entrypoint),
        "--out",
        str(out_dir),
        "--symbols",
        *[str(symbol) for symbol in config.get("symbols") or []],
        "--timeframe",
        str(config.get("timeframe")),
        "--window-bars",
        str(int(config.get("window_bars"))),
        "--decision-every-bars",
        str(int(config.get("decision_every_bars") or 1)),
        "--warmup-minutes",
        str(int(config.get("warmup_minutes"))),
        "--duration-s",
        str(int(config.get("duration_s"))),
        "--poll-s",
        str(float(config.get("poll_interval_s"))),
        "--settle-ms",
        str(int(config.get("settle_ms") or 0)),
        "--latency-ms",
        str(int(config.get("latency_ms") or 0)),
    ]
    if config.get("max_cycles") is not None:
        argv.extend(["--max-cycles", str(int(config["max_cycles"]))])
    if resume:
        argv.append("--resume")
    return argv


class Supervisor:
    """Drive one session directory: observe, recover, or stop with a reason."""

    def __init__(
        self,
        *,
        session: Path | str,
        state_dir: Path | str,
        entrypoint: Path | str | None = None,
        policy: Policy | None = None,
        config: Mapping[str, Any] | None = None,
        allow_start: bool = False,
        root: Path | str | None = None,
        spawn: Callable[..., subprocess.Popen[bytes]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = Path(session)
        self.state_dir = Path(state_dir)
        self.root = Path(root) if root else Path(__file__).resolve().parents[3]
        self.entrypoint = Path(entrypoint) if entrypoint else self.root / ENTRYPOINT
        self.policy = policy or Policy()
        self.config = dict(config or {})
        self.allow_start = bool(allow_start)
        self._spawn = spawn or windowless.spawn
        self.sleep = sleep
        self.clock = clock

        self._journal_path = self.state_dir / "SUPERVISOR.jsonl"
        self._result_path = self.state_dir / "SUPERVISOR_RESULT.json"
        self._stop_path = self.state_dir / "STOP"
        self._lock: SingleWriter | None = None
        self._journal_rows = 0
        self._child: subprocess.Popen[bytes] | None = None
        self.restarts = 0
        self.failures = 0
        self.attempts: list[dict[str, Any]] = []
        self._started_at = _utc_now()
        self._started_monotonic = self.clock()

    # -- journal -------------------------------------------------------------

    def _record(self, event: str, **fields: Any) -> dict[str, Any]:
        self._journal_rows += 1
        row = {
            "schema_version": JOURNAL_SCHEMA,
            "seq": self._journal_rows,
            "at_utc": _utc_now(),
            "event": event,
            "supervisor_pid": os.getpid(),
            **fields,
        }
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self._journal_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def _digest(self, status: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "state": status.get("state"),
            "why": list(status.get("why") or [])[:8],
            "rows": int((status.get("ledger") or {}).get("rows") or 0),
            "cycles": list((status.get("ledger") or {}).get("cycles") or []),
            "last_cycle": (status.get("ledger") or {}).get("last_cycle"),
            "locks": len((status.get("locks") or {}).get("all") or []),
            "awaiting": [
                {"path": item.get("path"), "state": item.get("state"), "reason": item.get("reason")}
                for item in (status.get("locks") or {}).get("awaiting_recovery") or []
            ],
            "session_id": (status.get("session") or {}).get("session_id"),
            "recoveries": (status.get("recoveries") or {}).get("count"),
            "exit_code": (status.get("last_attempt") or {}).get("exit_code"),
        }

    # -- helpers -------------------------------------------------------------

    def _status(self) -> dict[str, Any]:
        return session_status(self.session)

    def _stop_requested(self) -> bool:
        return self._stop_path.exists()

    def _pinned_config(self) -> dict[str, Any]:
        """The configuration the session declared, never one the supervisor invented."""

        meta = self.session / "RUN_META.json"
        if meta.is_file():
            try:
                payload = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            pinned = payload.get("config")
            if isinstance(pinned, dict) and pinned.get("mode"):
                return dict(pinned)
        return dict(self.config)

    def _finish(self, action: str, reason: str, status: Mapping[str, Any] | None) -> dict[str, Any]:
        result = {
            "schema_version": SCHEMA_VERSION,
            "action": action,
            "reason": reason,
            "session": str(self.session),
            "state_dir": str(self.state_dir),
            "started_at_utc": self._started_at,
            "finished_at_utc": _utc_now(),
            "elapsed_s": round(self.clock() - self._started_monotonic, 3),
            "restarts": self.restarts,
            "attempts": self.attempts,
            "final_state": (status or {}).get("state"),
            "final_status": status,
            "locks": [
                {"path": item.get("path"), "state": item.get("state"), "reason": item.get("reason")}
                for item in ((status or {}).get("locks") or {}).get("all") or []
            ],
            "live_orders": 0,
            "mode": "PAPER",
            "exit_code": EXIT_OK if action in (STOP_COMPLETED, STOP_OPERATOR) else EXIT_REFUSED,
        }
        if action == STOP_NO_SESSION:
            result["exit_code"] = EXIT_NOTHING_TO_DO
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        self._record("STOP", action=action, reason=reason, restarts=self.restarts)
        return result

    def _spawn_child(self, *, resume: bool) -> subprocess.Popen[bytes]:
        config = self._pinned_config()
        if not config:
            raise ValueError("NO_CONFIG: neither RUN_META.json nor --config declares a session")
        argv = entrypoint_argv(
            config, out_dir=self.session, entrypoint=self.entrypoint, resume=resume
        )
        log = self.state_dir / "child.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as handle:
            child = self._spawn(
                argv,
                cwd=str(self.root),
                stdout=handle,
                stderr=subprocess.STDOUT,
                new_group=True,
            )
        self._record(
            "SPAWNED",
            pid=child.pid,
            resume=resume,
            argv=argv,
            config_fingerprint_keys=sorted(config),
        )
        return child

    def _wait_child(self, child: subprocess.Popen[bytes]) -> int:
        try:
            return int(child.wait(timeout=self.policy.child_timeout_s))
        except subprocess.TimeoutExpired:  # pragma: no cover - the session declares its own end
            windowless.terminate_tree(child)
            return 124

    def _verify_attempt(
        self,
        *,
        action: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        exit_code: int,
    ) -> dict[str, Any]:
        """Require the artefacts to show the attempt, not merely the process to have run."""

        rows_before = int((before.get("ledger") or {}).get("rows") or 0)
        rows_after = int((after.get("ledger") or {}).get("rows") or 0)
        #: A kill can truncate the line that was being written. That is broken evidence, not
        #: an exception the supervisor may die of: it is reported and the loop stops.
        try:
            entries = read_entries(self.session / "STREAM.jsonl")
            readable = True
        except (OSError, json.JSONDecodeError):
            entries, readable = [], False
        expected_seq = rows_before + 1
        start = entries[expected_seq - 1] if len(entries) >= expected_seq else None
        start_kind = (start or {}).get("entry", {}).get("kind")
        resumed_flag = ((start or {}).get("entry", {}).get("provenance") or {}).get("resumed")
        expected_flag = action == RESUME
        continued = bool(
            readable
            and start is not None
            and start_kind == "SESSION_START"
            and resumed_flag is expected_flag
        )
        cycles_before = list((before.get("ledger") or {}).get("cycles") or [])
        cycles_after = list((after.get("ledger") or {}).get("cycles") or [])
        new_cycles = [item for item in cycles_after if item not in cycles_before]
        locks_after = list((after.get("locks") or {}).get("all") or [])
        progress = rows_after > rows_before
        return {
            "action": action,
            "exit_code": exit_code,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "start_seq": (start or {}).get("seq"),
            "start_kind": start_kind,
            "resumed_flag": resumed_flag,
            "continued": continued,
            "new_cycles": new_cycles,
            "progress": progress,
            "locks_after": len(locks_after),
            "stream_readable": readable,
            "clean": exit_code == 0,
        }

    # -- the loop ------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = SingleWriter(self.state_dir / "SUPERVISOR.lock", purpose="paper-supervisor")
        try:
            self._lock.acquire()
        except LockRefused as exc:
            self._record("REFUSED", code=exc.code, detail=str(exc)[:400])
            result = self._finish(ALREADY_ACTIVE, "ANOTHER_SUPERVISOR_IS_ACTIVE", None)
            result["exit_code"] = EXIT_ALREADY_ACTIVE
            result["detail"] = str(exc)[:400]
            self._result_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return result
        self._record(
            "ACQUIRED",
            session=str(self.session),
            policy={
                "max_restarts": self.policy.max_restarts,
                "backoff_base_s": self.policy.backoff_base_s,
                "backoff_cap_s": self.policy.backoff_cap_s,
                "poll_s": self.policy.poll_s,
                "observe_timeout_s": self.policy.observe_timeout_s,
            },
            allow_start=self.allow_start,
        )
        try:
            return self._loop()
        finally:
            self._lock.release()

    def _loop(self) -> dict[str, Any]:
        observed_since: float | None = None
        while True:
            if self._stop_requested():
                self._terminate_child()
                return self._finish(STOP_OPERATOR, "OPERATOR_STOP_REQUESTED", self._status())

            status = self._status()
            decision = classify(
                status,
                restarts_done=self.restarts,
                policy=self.policy,
                allow_start=self.allow_start,
            )
            self._record(
                "DECISION",
                action=decision["action"],
                reason=decision["reason"],
                detail=decision["detail"],
                state=self._digest(status),
                restarts=self.restarts,
            )

            if decision["action"] == OBSERVE:
                if self._child is not None and self._child.poll() is not None:
                    #: The child we spawned is gone but something else holds a live lock:
                    #: two writers on one session is not a state this loop may proceed from.
                    return self._finish(STOP_AMBIGUOUS, "CHILD_EXITED_WITH_A_FOREIGN_LOCK", status)
                if self._child is None:
                    if observed_since is None:
                        observed_since = self.clock()
                    timeout = self.policy.observe_timeout_s
                    if timeout is not None and self.clock() - observed_since > timeout:
                        return self._finish(STOP_AMBIGUOUS, "FOREIGN_OWNER_NEVER_LEFT", status)
                self.sleep(self.policy.poll_s)
                continue

            observed_since = None
            if decision["action"] in STOP_ACTIONS:
                return self._finish(decision["action"], decision["reason"], status)

            if decision["action"] not in (RESUME, START):
                return self._finish(STOP_AMBIGUOUS, "UNKNOWN_ACTION", status)

            #: Re-read immediately before spawning: between the decision and here another
            #: actor may have recovered the session. The runtime's own lock is the final
            #: guard, but spawning into a state that no longer needs it is how loops begin.
            fresh = self._status()
            second = classify(
                fresh,
                restarts_done=self.restarts,
                policy=self.policy,
                allow_start=self.allow_start,
            )
            if second["action"] != decision["action"]:
                self._record(
                    "RE_EVALUATED",
                    first=decision["action"],
                    second=second["action"],
                    why=second["detail"],
                )
                self.sleep(self.policy.poll_s)
                continue

            if decision["action"] == RESUME:
                pause = self.policy.backoff_s(self.failures)
                if pause:
                    self._record("BACKOFF", seconds=pause, failures=self.failures)
                    self.sleep(pause)
                if self.restarts >= self.policy.max_restarts:
                    return self._finish(STOP_BUDGET, "RETRY_BUDGET_EXHAUSTED", fresh)

            before = self._digest(fresh)
            child = self._spawn_child(resume=decision["action"] == RESUME)
            self._child = child
            exit_code = self._wait_child(child)
            self._child = None
            after_status = self._status()
            attempt = self._verify_attempt(
                action=decision["action"], before=fresh, after=after_status, exit_code=exit_code
            )
            attempt["pid"] = child.pid
            attempt["attempt"] = len(self.attempts) + 1
            self.attempts.append(attempt)
            if decision["action"] == RESUME:
                self.restarts += 1
            self._record(
                "CHILD_EXIT",
                action=decision["action"],
                pid=child.pid,
                exit_code=exit_code,
                before=before,
                after=self._digest(after_status),
                verified=attempt,
            )

            if not attempt["stream_readable"]:
                return self._finish(STOP_FAILED, "STREAM_UNREADABLE", after_status)
            if attempt["clean"] and not attempt["progress"]:
                return self._finish(STOP_NO_PROGRESS, "CLEAN_EXIT_WITHOUT_EVIDENCE", after_status)
            if attempt["clean"] and attempt["locks_after"]:
                return self._finish(STOP_AMBIGUOUS, "CLEAN_EXIT_LEFT_LOCKS", after_status)
            if not attempt["continued"] and attempt["progress"]:
                return self._finish(STOP_AMBIGUOUS, "SESSION_START_DOES_NOT_CONTINUE", after_status)

            self.failures = 0 if attempt["clean"] else self.failures + 1
            if self.failures > self.policy.max_restarts + 2:
                return self._finish(STOP_NO_PROGRESS, "RESTART_LOOP_WITHOUT_PROGRESS", after_status)

    def _terminate_child(self) -> None:
        child = self._child
        if child is None or child.poll() is not None:
            return
        windowless.terminate_tree(child)
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=30)
        self._record("CHILD_TERMINATED", pid=child.pid)
        self._child = None


def describe(result: Mapping[str, Any]) -> str:
    """One line an operator can read in a terminal."""

    return (
        f"{result.get('action')} ({result.get('reason')}) "
        f"state={result.get('final_state')} restarts={result.get('restarts')} "
        f"locks={len(result.get('locks') or [])}"
    )
