"""CODEX-SUPERVISOR — restart a crashed PAPER session only when restarting is proved safe.

Three groups, one per question:

* **policy** — every branch of ``classify`` is decided from artefacts, and the unsafe ones
  (broken chain, unattributed lock, refusal, exhausted budget) never produce a spawn;
* **evidence** — a child that exits 0 without appending a ``SESSION_START`` at the next
  sequence number is not a recovery, and a clean exit that leaves a lock is not one either;
* **isolation** — the supervisor's own coordination lock lives beside the session, because
  ``session_status`` would otherwise report the supervisor as a live writer.

The loop is exercised with an injected spawner, so it runs in milliseconds and still goes
through the real status reader and the real chained stream.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

from trading_bot.ops import paper_supervisor as supervisor_module
from trading_bot.ops import windowless
from trading_bot.ops.paper_supervisor import (
    ALREADY_ACTIVE,
    OBSERVE,
    RESUME,
    START,
    STOP_AMBIGUOUS,
    STOP_BLOCKED,
    STOP_BUDGET,
    STOP_COMPLETED,
    STOP_FAILED,
    STOP_NO_PROGRESS,
    STOP_NO_SESSION,
    Policy,
    Supervisor,
    classify,
    entrypoint_argv,
)
from trading_bot.ops.session_status import session_status
from trading_bot.ops.single_writer import SingleWriter
from trading_bot.vision.ledger import GENESIS, line_hash

REPO = Path(__file__).resolve().parents[3]
POLICY = Policy(max_restarts=3, poll_s=0.001)


# ----------------------------------------------------------------------- fixtures


def _dead_pid() -> int:
    """A pid that existed and no longer does, started through the only allowed launcher."""

    process = windowless.spawn([sys.executable, "-c", "pass"], cwd=str(REPO))
    process.wait()
    return int(process.pid)


def _write_chain(path: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = GENESIS
    rows = []
    for index, entry in enumerate(entries, start=1):
        digest = line_hash(index, prev, entry)
        rows.append({"seq": index, "prev_sha256": prev, "entry": entry, "sha256": digest})
        prev = digest
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    return rows


def _start(*, resumed: bool) -> dict[str, Any]:
    return {
        "kind": "SESSION_START",
        "recorded_at_utc": "2026-10-23T00:00:00Z",
        "started_at_utc": "2026-10-23T00:00:00Z",
        "live_orders": 0,
        "runtime_sha256": {"src/a.py": "a"},
        "provenance": {
            "run_id": "run-1",
            "session_id": "sess-1" if not resumed else "sess-2",
            "pinned_identity": "pin-1",
            "runtime_digest": "digest-1",
            "resumed": resumed,
        },
    }


def _cycle(number: int) -> dict[str, Any]:
    return {
        "kind": "CYCLE",
        "recorded_at_utc": "2026-10-23T00:01:00Z",
        "cycle": number,
        "live_orders": 0,
    }


def _abandoned_record(pid: int, *, purpose: str = "session") -> dict[str, Any]:
    return {
        "schema_version": "TAP_SINGLE_WRITER_LOCK_V1",
        "purpose": purpose,
        "host": socket.gethostname(),
        "pid": pid,
        "process_start_ms": None,
        "token": "dead-owner" * 4,
        "fence": 1,
    }


def _run_meta(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "mode": "PAPER",
        "live_enabled": False,
        "live_orders": 0,
        "config": config
        or {
            "symbols": ["BTCUSDT"],
            "timeframe": "1m",
            "window_bars": 20,
            "decision_every_bars": 1,
            "duration_s": 60,
            "poll_interval_s": 5.0,
            "settle_ms": 0,
            "latency_ms": 30_000,
            "warmup_minutes": 120,
            "equity": 10_000.0,
            "mode": "PAPER",
            "max_cycles": 2,
            "stale_after_ms": 150_000,
            "max_skew_ms": 5_000,
            "signal_source": "legacy_parity",
            "strategy_id": "ema_crossover",
        },
    }


def _cycle_ledger(root: Path, number: int) -> None:
    _write_chain(
        root / "cycles" / f"cycle-{number:04d}" / "ledger.jsonl",
        [
            {"kind": "RUN", "recorded_at_utc": "2026-10-23T00:00:00Z", "run": number},
            {"kind": "DECISION", "recorded_at_utc": "2026-10-23T00:00:30Z", "cycle": number},
        ],
    )


def _session(tmp_path: Path, *, lock: bool = True, pid: int | None = None) -> Path:
    root = tmp_path / "session"
    root.mkdir()
    _write_chain(root / "STREAM.jsonl", [_start(resumed=False), _cycle(1)])
    _cycle_ledger(root, 1)
    (root / "RUN_META.json").write_text(json.dumps(_run_meta()), encoding="utf-8")
    (root / "RUN_RESULT.json").write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    if lock:
        (root / "STREAM.jsonl.lock").write_text(
            json.dumps(_abandoned_record(pid if pid is not None else _dead_pid())), encoding="utf-8"
        )
    return root


def _status(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "state": "RECOVERING",
        "why": [],
        "ledger": {
            "chain_ok": True,
            "seq_continuous": True,
            "cycle_ledgers_ok": True,
            "cycles": [1],
            "rows": 3,
        },
        "session": {"pinned_identity": "pin-1"},
        "locks": {
            "all": [{"path": "STREAM.jsonl.lock", "state": "ABANDONED"}],
            "awaiting_recovery": [
                {
                    "path": "STREAM.jsonl.lock",
                    "state": "ABANDONED",
                    "reason": "OWNER_PROCESS_DEAD",
                }
            ],
        },
        "last_attempt": {"exit_code": 0, "refused": False, "aborted": False},
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------------- policy


def test_nothing_to_supervise_is_not_an_error() -> None:
    decision = classify({"state": "ABSENT"}, restarts_done=0, policy=POLICY)
    assert (decision["action"], decision["reason"]) == (STOP_NO_SESSION, "NOTHING_TO_SUPERVISE")


def test_start_is_opt_in() -> None:
    decision = classify({"state": "ABSENT"}, restarts_done=0, policy=POLICY, allow_start=True)
    assert decision["action"] == START


def test_a_broken_chain_is_never_restarted_even_with_a_recoverable_lock() -> None:
    decision = classify(
        _status(state="FAILED", why=["CHAIN_BAD_JSON_AT_4"]), restarts_done=0, policy=POLICY
    )
    assert decision["action"] == STOP_FAILED
    assert decision["reason"] == "STATE_FAILED"


def test_a_live_owner_is_observed_and_never_touched() -> None:
    decision = classify(_status(state="RUNNING"), restarts_done=0, policy=POLICY)
    assert decision["action"] == OBSERVE


def test_an_abandoned_lock_is_the_only_permission_to_resume() -> None:
    decision = classify(_status(), restarts_done=0, policy=POLICY)
    assert (decision["action"], decision["reason"]) == (RESUME, "ABANDONED_LOCK_PROVED")


def test_an_unattributable_lock_is_fail_closed() -> None:
    status = _status(
        locks={
            "all": [{"path": "STREAM.jsonl.lock", "state": "UNATTRIBUTED"}],
            "awaiting_recovery": [
                {"path": "STREAM.jsonl.lock", "state": "UNATTRIBUTED", "reason": "EMPTY"}
            ],
        }
    )
    decision = classify(status, restarts_done=0, policy=POLICY)
    assert (decision["action"], decision["reason"]) == (STOP_AMBIGUOUS, "LOCK_NOT_ATTRIBUTABLE")


@pytest.mark.parametrize(
    ("ledger", "reason"),
    [
        (
            {"chain_ok": False, "seq_continuous": True, "cycle_ledgers_ok": True},
            "LEDGER_CHAIN_BROKEN",
        ),
        (
            {"chain_ok": True, "seq_continuous": False, "cycle_ledgers_ok": True},
            "SEQ_NOT_CONTINUOUS",
        ),
        (
            {"chain_ok": True, "seq_continuous": True, "cycle_ledgers_ok": False},
            "CYCLE_LEDGER_BROKEN",
        ),
    ],
)
def test_corrupt_evidence_blocks_the_resume(ledger: dict[str, Any], reason: str) -> None:
    decision = classify(_status(ledger=ledger), restarts_done=0, policy=POLICY)
    assert decision["action"] == STOP_FAILED
    assert decision["reason"] == reason


def test_a_resume_without_a_pin_would_claim_an_identity_it_never_had() -> None:
    decision = classify(_status(session={"pinned_identity": None}), restarts_done=0, policy=POLICY)
    assert (decision["action"], decision["reason"]) == (STOP_AMBIGUOUS, "NO_PINNED_IDENTITY")


def test_the_retry_budget_is_a_stop_not_a_suggestion() -> None:
    decision = classify(_status(), restarts_done=3, policy=POLICY)
    assert (decision["action"], decision["reason"]) == (STOP_BUDGET, "RETRY_BUDGET_EXHAUSTED")


@pytest.mark.parametrize(
    ("state", "attempt", "action"),
    [
        ("RECOVERED", {"exit_code": 0}, STOP_COMPLETED),
        ("READY", {"exit_code": 2}, STOP_BLOCKED),
        ("READY", {"exit_code": None}, STOP_AMBIGUOUS),
        ("RECOVERED", {"exit_code": 4}, STOP_FAILED),
        ("READY", {"exit_code": 5}, STOP_FAILED),
        ("READY", {"exit_code": 0, "refused": True}, STOP_FAILED),
    ],
)
def test_a_lock_free_session_is_classified_by_its_recorded_outcome(
    state: str, attempt: dict[str, Any], action: str
) -> None:
    decision = classify(_status(state=state, last_attempt=attempt), restarts_done=0, policy=POLICY)
    assert decision["action"] == action


def test_backoff_grows_and_is_capped() -> None:
    policy = Policy(backoff_base_s=2.0, backoff_cap_s=30.0)
    assert [policy.backoff_s(n) for n in (0, 1, 2, 3, 10)] == [0.0, 2.0, 4.0, 8.0, 30.0]


def test_the_entrypoint_is_rebuilt_from_the_pinned_configuration() -> None:
    config = _run_meta()["config"]
    argv = entrypoint_argv(
        config, out_dir=Path("session"), entrypoint=Path("entry.py"), resume=True
    )
    joined = " ".join(argv)
    assert "--resume" in argv
    assert "--duration-s 60" in joined
    assert "--max-cycles 2" in joined
    assert "--symbols BTCUSDT" in joined


def test_a_live_configuration_is_refused_by_name() -> None:
    config = {**_run_meta()["config"], "mode": "LIVE"}
    with pytest.raises(ValueError, match="PAPER only"):
        entrypoint_argv(config, out_dir=Path("s"), entrypoint=Path("e"), resume=False)


# -------------------------------------------------------------------- the loop


class _FakeChild:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


def _supervisor(
    session: Path, *, policy: Policy = POLICY, spawner=None, allow_start: bool = False
) -> Supervisor:
    return Supervisor(
        session=session,
        state_dir=session.with_name(session.name + ".supervisor"),
        root=session.parent,
        entrypoint=session.parent / "entry.py",
        policy=policy,
        allow_start=allow_start,
        spawn=spawner,
        sleep=lambda _seconds: None,
    )


def test_a_crash_is_resumed_and_the_recovery_is_proved_from_the_stream(tmp_path: Path) -> None:
    session = _session(tmp_path)
    calls: list[bool] = []

    def spawner(argv, **kwargs):
        calls.append("--resume" in argv)
        entries = [
            json.loads(line)["entry"]
            for line in (session / "STREAM.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        _write_chain(session / "STREAM.jsonl", [*entries, _start(resumed=True), _cycle(2)])
        _cycle_ledger(session, 2)
        (session / "STREAM.jsonl.lock").unlink()
        return _FakeChild()

    result = _supervisor(session, spawner=spawner).run()

    assert calls == [True], "a crash must be resumed, never restarted fresh"
    assert result["action"] == STOP_COMPLETED
    assert result["restarts"] == 1
    attempt = result["attempts"][0]
    assert attempt["continued"] is True
    assert attempt["start_seq"] == 3
    assert attempt["resumed_flag"] is True
    assert attempt["new_cycles"] == [2]
    assert attempt["progress"] is True
    assert result["locks"] == []
    journal = [
        json.loads(line)
        for line in (session.with_name(session.name + ".supervisor") / "SUPERVISOR.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    actions = [row.get("action") for row in journal if row["event"] == "DECISION"]
    assert actions[0] == RESUME


def test_a_session_that_already_ended_cleanly_is_not_restarted(tmp_path: Path) -> None:
    session = _session(tmp_path, lock=False)
    calls: list[Any] = []

    result = _supervisor(session, spawner=lambda *a, **k: calls.append(a)).run()

    assert calls == []
    assert (result["action"], result["reason"]) == (STOP_COMPLETED, "CLEAN_END")


def test_a_clean_exit_that_appends_no_row_is_refused_as_false_success(tmp_path: Path) -> None:
    session = _session(tmp_path)

    def spawner(argv, **kwargs):
        (session / "STREAM.jsonl.lock").unlink()
        return _FakeChild()

    result = _supervisor(session, spawner=spawner).run()
    assert (result["action"], result["reason"]) == (STOP_NO_PROGRESS, "CLEAN_EXIT_WITHOUT_EVIDENCE")


def test_a_clean_exit_that_leaves_a_lock_is_ambiguous(tmp_path: Path) -> None:
    session = _session(tmp_path)

    def spawner(argv, **kwargs):
        entries = [
            json.loads(line)["entry"]
            for line in (session / "STREAM.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        _write_chain(session / "STREAM.jsonl", [*entries, _start(resumed=True)])
        (session / "STREAM.jsonl.lock").write_text(
            json.dumps(_abandoned_record(os.getpid(), purpose="leak")), encoding="utf-8"
        )
        return _FakeChild()

    result = _supervisor(session, spawner=spawner).run()
    assert (result["action"], result["reason"]) == (STOP_AMBIGUOUS, "CLEAN_EXIT_LEFT_LOCKS")


def test_a_failed_session_is_not_spawned_into(tmp_path: Path) -> None:
    session = _session(tmp_path)
    rows = (session / "STREAM.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[1])
    payload["entry"]["cycle"] = 99
    rows[1] = json.dumps(payload, sort_keys=True)
    (session / "STREAM.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    calls: list[Any] = []

    result = _supervisor(session, spawner=lambda *a, **k: calls.append(a)).run()

    assert calls == []
    assert result["action"] == STOP_FAILED
    assert result["final_state"] == "FAILED"


def test_an_exhausted_budget_spawns_nothing(tmp_path: Path) -> None:
    session = _session(tmp_path)
    calls: list[Any] = []

    result = _supervisor(
        session,
        policy=Policy(max_restarts=0, poll_s=0.001),
        spawner=lambda *a, **k: calls.append(a),
    ).run()

    assert calls == []
    assert (result["action"], result["reason"]) == (STOP_BUDGET, "RETRY_BUDGET_EXHAUSTED")


def test_two_supervisors_do_not_both_act(tmp_path: Path) -> None:
    session = _session(tmp_path)
    state_dir = session.with_name(session.name + ".supervisor")
    state_dir.mkdir(parents=True)
    holder = SingleWriter(state_dir / "SUPERVISOR.lock", purpose="test-holder")
    holder.acquire()
    calls: list[Any] = []
    try:
        result = _supervisor(session, spawner=lambda *a, **k: calls.append(a)).run()
    finally:
        holder.release()

    assert calls == []
    assert result["action"] == ALREADY_ACTIVE
    assert result["exit_code"] == 4


def test_the_supervisor_lock_is_invisible_to_the_session_diagnosis(tmp_path: Path) -> None:
    session = _session(tmp_path, lock=False)
    supervisor = _supervisor(session)
    state_dir = session.with_name(session.name + ".supervisor")
    state_dir.mkdir(parents=True)
    holder = SingleWriter(state_dir / "SUPERVISOR.lock", purpose="paper-supervisor")
    holder.acquire()
    try:
        status = session_status(session)
    finally:
        holder.release()
    assert status["state"] == "READY"
    assert status["owner"]["pid"] is None, "the supervisor is not a session writer"
    assert supervisor.state_dir.parent != session


def test_a_foreign_live_owner_is_waited_for_then_refused(tmp_path: Path) -> None:
    session = _session(tmp_path, lock=False)
    holder = SingleWriter(session / "STREAM.jsonl.lock", purpose="foreign")
    holder.acquire()
    calls: list[Any] = []
    try:
        result = _supervisor(
            session,
            policy=Policy(observe_timeout_s=0.0, poll_s=0.001),
            spawner=lambda *a, **k: calls.append(a),
        ).run()
    finally:
        holder.release()
    assert calls == []
    assert (result["action"], result["reason"]) == (STOP_AMBIGUOUS, "FOREIGN_OWNER_NEVER_LEFT")


def test_the_operator_can_stop_the_supervisor_safely(tmp_path: Path) -> None:
    session = _session(tmp_path, lock=False)
    state_dir = session.with_name(session.name + ".supervisor")
    state_dir.mkdir(parents=True)
    (state_dir / "STOP").write_text("stop\n", encoding="utf-8")
    calls: list[Any] = []
    result = _supervisor(session, spawner=lambda *a, **k: calls.append(a)).run()
    assert calls == []
    assert result["action"] == "STOP_OPERATOR"
    assert result["exit_code"] == 0


def test_the_module_names_every_action_it_can_return() -> None:
    assert {
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
        "STOP_OPERATOR",
    } == set(supervisor_module.ACTIONS)
