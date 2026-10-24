"""G-1 — the stop outlives the process that requested it.

G-2 proved that a **running** process can be stopped. This file proves the
narrower, harder claim that survives a reboot of the process: the marker is the
authority, it is adopted **in the constructor** (therefore before any broker
call can begin), and nothing else — not the audit trail, not the checkpoint,
not a successful-looking CLI exit code — can rearm the gate.

What this file refuses to accept as evidence:

1. **Re-instantiating a Python object.** That proves a field was parsed, not
   that a process inherits a stop. ``test_two_processes_share_the_stop`` drives
   the real CLI and the real runtime as two operating-system processes.
2. **Rule 0 doing the work.** The runtime fixtures use a *hostile* engine that
   always returns ``TRADE_PAPER``, so a blocked order can only come from the
   dispatch boundary.
3. **A file that exists but was never honoured.** Every "blocked" assertion is
   paired with a control over a sibling run directory that really does reach
   the broker.

The mutation matrix that proves these tests are *sensitive* lives in
``scripts/audit/g1_mutants.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.hot_stop import (
    AUDIT_FILE_NAME,
    HOT_STOP_FILE_NAME,
    HotStopGate,
    write_control_file,
)
from trading_bot.domain.enums.kill_switch import KillSwitchState
from trading_bot.paper.kill_switch_v2 import KillSwitch

from .helpers import (
    BAR_MS,
    FakeSnapshot,
    StaticFamily,
    StaticReader,
    bars,
    make_admitted_ledger,
    risk_manager,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = REPO_ROOT / "scripts" / "audit" / "g1_restart_probe.py"
NOW_MS = 1_700_000_000_000


# --- fixtures ----------------------------------------------------------------


def _gate(run_dir: Path, switch: KillSwitch | None = None, **kwargs: Any) -> HotStopGate:
    return HotStopGate(
        kill_switch=switch if switch is not None else KillSwitch(),
        run_dir=run_dir,
        now_ms=lambda: NOW_MS,
        **kwargs,
    )


def _events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / AUDIT_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _child_env() -> dict[str, str]:
    """The child must import this checkout, not an installed copy."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_cli(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "trading_bot.app", *argv],
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _probe(run_dir: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(PROBE), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"probe failed for {run_dir}: {completed.stderr[-800:] or completed.stdout[-800:]}"
    )
    return json.loads(completed.stdout)


class _SpyBroker:
    def __init__(self) -> None:
        self.calls = 0
        self.positions: dict[str, Any] = {}
        self.equity = 10_000.0

    def execute_signal(self, signal: Any) -> Any:
        self.calls += 1
        return object()

    def reconcile_session(self, session_id: str, snapshots: Any, risk: Any) -> Any:
        class _Summary:
            def __init__(self) -> None:
                self.new_closed_trades: list[Any] = []
                self.fills_opened = 0
                self.fills_closed = 0

        return _Summary()


class _AlwaysTradeEngine:
    """A hostile decision engine: rule 0 is bypassed by construction."""

    version = "hostile"

    def intend(self, request: Any) -> Any:
        from trading_bot.autonomous.contracts import DecisionMode
        from trading_bot.autonomous.decision import DecisionResult

        return DecisionResult(
            mode=DecisionMode.TRADE_PAPER,
            reason="hostile_intent",
            classification="PAPER_ADMITTED",
            order_authorised=False,
        )

    def decide(self, request: Any) -> Any:
        from trading_bot.autonomous.contracts import DecisionMode
        from trading_bot.autonomous.decision import DecisionResult

        return DecisionResult(
            mode=DecisionMode.TRADE_PAPER,
            reason="hostile_decision",
            classification="PAPER_ADMITTED",
            order_authorised=True,
            notional_usdt=250.0,
        )


class _FixedScanner:
    def __init__(self) -> None:
        history = bars("BTC/USDT", 80)
        self._snapshot = FakeSnapshot(symbol="BTC/USDT", timestamp=history[-1].timestamp + BAR_MS)

    async def run(self) -> list[FakeSnapshot]:
        return [self._snapshot]


def _build_runtime(*, run_dir: Path, broker: Any, hot_stop: Any | None = None) -> Any:
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime

    ledger = make_admitted_ledger(gross_bps=50.0)
    history = {"BTC/USDT": bars("BTC/USDT", 80)}
    strategy_map = {
        strategy_id: {
            "family": entry.family,
            "regimes": [],
            "direction": "BOTH",
            "enabled": True,
            "status": entry.status.value,
            "priority": 0.0,
        }
        for strategy_id, entry in ledger.entries_for_timeframe("5m").items()
    }
    families = {
        entry.family: StaticFamily(entry.family)
        for entry in ledger.entries_for_timeframe("5m").values()
    }

    class _Settings:
        class runtime:
            mode = "PAPER"
            exchange_id = "fake"

        class risk:
            kill_switch_enabled = True

    return AutonomousPaperRuntime(
        settings=_Settings(),
        scanner_factory=_FixedScanner,
        history_reader=StaticReader(history),
        broker=broker,
        risk_manager=risk_manager(),
        families=families,
        strategy_map=strategy_map,
        ledger=ledger,
        run_dir=run_dir,
        assets=("BTC",),
        timeframe="5m",
        horizon_minutes=5.0,
        size_usd=1_000.0,
        decision_engine=_AlwaysTradeEngine(),
        hot_stop=hot_stop,
    )


# --- the marker is the authority --------------------------------------------


def test_a_fresh_run_dir_boots_operational(tmp_path: Path) -> None:
    """ACC-G1-01: absence is the only answer that leaves the gate open."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    switch = KillSwitch()
    gate = _gate(run_dir, switch)

    assert gate.engaged is False
    assert gate.stats()["restored"] is False
    assert switch.state is KillSwitchState.NORMAL
    with gate.order_boundary() as allowed:
        assert allowed is True
    assert gate.stats()["broker_calls_allowed"] == 1
    assert _events(run_dir) == []
    assert not (run_dir / HOT_STOP_FILE_NAME).exists()


def test_a_marker_left_by_a_previous_process_engages_at_construction(tmp_path: Path) -> None:
    """ACC-G1-03 / REQ-G1-02: no ``poll``, no cycle, no second chance to wire it."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: restart after crash")

    switch = KillSwitch()
    gate = _gate(run_dir, switch)  # constructed, never polled

    assert gate.engaged is True
    assert gate.stats()["restored"] is True
    assert switch.state is KillSwitchState.HALTED
    assert switch.is_active is True
    with gate.order_boundary() as allowed:
        assert allowed is False
    assert gate.stats()["broker_calls_allowed"] == 0


def test_restore_is_recorded_as_a_restored_event(tmp_path: Path) -> None:
    """REQ-G1-07: a boot adopts the stop *and* says so, with its own event name."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "drawdown breach\n")

    gate = _gate(run_dir, commit="abc1234", run_id="run-1")

    events = _events(run_dir)
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "restored"
    assert event["restored"] is True
    assert event["persisted"] is True
    assert event["previous_state"] == "normal"
    assert event["new_state"] == "halted"
    assert event["actor"] == f"boot_restore:{run_dir / HOT_STOP_FILE_NAME}"
    assert event["reason"] == "drawdown breach"
    assert event["run_id"] == "run-1"
    assert event["commit"] == "abc1234"
    assert event["boundary"].startswith("autonomous.runtime._execute_paper")
    assert gate.engaged is True


def test_a_directory_marker_fails_closed(tmp_path: Path) -> None:
    """ACC-G1-08: a corrupt entry is a stop that cannot explain itself."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / HOT_STOP_FILE_NAME).mkdir()

    gate = _gate(run_dir)

    assert gate.engaged is True
    assert gate.stats()["restored"] is True
    event = _events(run_dir)[0]
    assert event["event"] == "restored"
    assert event["reason"].startswith("control_file_unreadable")
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_an_unreadable_control_path_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ACC-G1-08: ``lstat`` refusing to answer is not permission to trade."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def deny(path: Any) -> None:
        raise PermissionError("acl denied")

    monkeypatch.setattr(os, "lstat", deny)
    gate = _gate(run_dir)

    assert gate.engaged is True
    event = _events(run_dir)[0]
    assert event["event"] == "restored"
    assert event["reason"] == "control_file_unreadable:PermissionError"
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_an_empty_marker_is_still_a_stop(tmp_path: Path) -> None:
    """REQ-G1-04: presence is the request; the content is only the reason."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / HOT_STOP_FILE_NAME).write_bytes(b"")

    gate = _gate(run_dir)

    assert gate.engaged is True
    assert _events(run_dir)[0]["reason"] == f"persisted stop:{HOT_STOP_FILE_NAME}"


def test_a_crash_after_persisting_before_the_ack_still_blocks(tmp_path: Path) -> None:
    """ACC-G1-07 / REQ-G1-06.

    The operator wrote the request, the process died before appending its
    ``engaged`` event, and a stray temp file survived the crash. The next boot
    has no ACK to read — and must still be stopped, because the marker is the
    authority and the audit is not.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: emergency")
    (run_dir / f"{HOT_STOP_FILE_NAME}.deadbeef.tmp").write_text("partial", encoding="utf-8")
    assert _events(run_dir) == []

    gate = _gate(run_dir)

    assert gate.engaged is True
    events = _events(run_dir)
    assert [e["event"] for e in events] == ["restored"]
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_deleting_the_audit_trail_does_not_rearm(tmp_path: Path) -> None:
    """REQ-G1-07: the JSONL is evidence. Deleting it cannot open the gate."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "stop")
    _gate(run_dir)  # first boot restores and writes the event
    (run_dir / AUDIT_FILE_NAME).unlink()

    second = _gate(run_dir)

    assert second.engaged is True
    assert [e["event"] for e in _events(run_dir)] == ["restored"]


def test_engage_persists_the_marker_for_the_next_process(tmp_path: Path) -> None:
    """REQ-G1-01: an in-process activation is durable, not only in memory."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gate = _gate(run_dir)

    ack = gate.engage("operator: memory pressure")

    assert ack.persisted is True
    assert ack.restored is False
    assert ack.event == "engaged"
    marker = run_dir / HOT_STOP_FILE_NAME
    assert marker.read_text(encoding="utf-8").strip() == "operator: memory pressure"
    assert not list(run_dir.glob(f"{HOT_STOP_FILE_NAME}.*.tmp")), "temp file left behind"

    second = _gate(run_dir)
    assert second.engaged is True
    assert second.stats()["restored"] is True


def test_a_failed_marker_write_is_reported_and_the_gate_stays_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-G1-05: a stop that a restart would not inherit says so."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def refuse(path: Any, reason: str) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr("trading_bot.autonomous.hot_stop.write_control_file", refuse)
    gate = _gate(run_dir, boundary_timeout_seconds=1.0)

    ack = gate.engage("stop now")

    assert ack.persisted is False
    assert gate.engaged is True
    assert _events(run_dir)[0]["persisted"] is False
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_a_failed_replace_leaves_the_previous_marker_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-G1-05: the update is atomic, so a failed write cannot erase a stop."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    marker = run_dir / HOT_STOP_FILE_NAME
    marker.write_text("first\n", encoding="utf-8")

    def explode(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        write_control_file(marker, "second")

    assert marker.read_text(encoding="utf-8") == "first\n"
    assert list(run_dir.glob(f"{HOT_STOP_FILE_NAME}.*.tmp")) == [], "temp file not cleaned up"


def test_a_poll_observed_stop_waits_for_the_in_flight_dispatch(tmp_path: Path) -> None:
    """ACC-G1-05 / REQ-G1-08: the marker path keeps G-2's linearization.

    G-2 proved the barrier for a direct ``engage()``. G-1 routes the marker
    through ``poll()`` before it reaches ``engage()``, so the property is
    re-proved on the path an operator request actually takes: while a broker
    call is in flight the lock is held, and the poll cannot answer before the
    process is quiet.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gate = _gate(run_dir, boundary_timeout_seconds=10.0)
    in_flight = threading.Event()
    release = threading.Event()

    def dispatch() -> None:
        with gate.order_boundary(run_id="run-1") as allowed:
            assert allowed is True
            in_flight.set()
            release.wait(10.0)

    worker = threading.Thread(target=dispatch, daemon=True)
    worker.start()
    assert in_flight.wait(10.0)

    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: stop during dispatch")
    results: list[bool] = []
    poller = threading.Thread(target=lambda: results.append(gate.poll(run_id="run-1")), daemon=True)
    poller.start()
    time.sleep(0.2)
    assert poller.is_alive(), "poll ACKed while a dispatch was in flight"

    release.set()
    poller.join(10.0)
    worker.join(10.0)
    assert results == [True]
    assert gate.engaged is True
    assert gate.stats()["broker_calls_allowed"] == 1
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_a_restored_gate_keeps_the_boundary_semantics(tmp_path: Path) -> None:
    """REQ-G1-08: restoring does not create a second, weaker gate."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "stop")

    gate = _gate(run_dir)
    for _ in range(3):
        with gate.order_boundary() as allowed:
            assert allowed is False

    stats = gate.stats()
    assert stats["orders_blocked"] == 3
    assert stats["broker_calls_allowed"] == 0
    assert stats["restored"] is True


def test_a_new_run_dir_is_outside_the_persisted_scope_this_is_the_documented_limit(
    tmp_path: Path,
) -> None:
    """REQ-G1-09 / ACC-G1-10: the honest limit, asserted instead of implied.

    ``scripts/autonomous_paper.py`` defaults ``--run-id`` to a timestamp, so a
    bare restart is a **new** run directory. This test exists so no later report
    can claim a global stop: if that policy ever changes, this assertion is the
    thing that has to change with it.
    """
    stopped = tmp_path / "run-a"
    stopped.mkdir()
    write_control_file(stopped / HOT_STOP_FILE_NAME, "stop")
    assert _gate(stopped).engaged is True

    fresh = tmp_path / "run-b"  # the new run id the default CLI would create
    fresh.mkdir()
    newcomer = _gate(fresh)

    assert newcomer.engaged is False
    with newcomer.order_boundary() as allowed:
        assert allowed is True


# --- a new process, not a new object ----------------------------------------


def test_the_runtime_is_engaged_before_its_first_cycle(tmp_path: Path) -> None:
    """ACC-G1-03 / REQ-G1-02, at the object the operator actually starts."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: restart")
    broker = _SpyBroker()

    # The gate is constructed first and then handed to the runtime, exactly as
    # ``runtime.py`` does internally; the *default* construction path is covered
    # by ``test_the_runtime_default_gate_restores_from_the_marker`` and by the
    # cross-process probe, which runs in a fresh interpreter.
    runtime = _build_runtime(run_dir=run_dir, broker=broker, hot_stop=_gate(run_dir))

    assert runtime.hot_stop.engaged is True, "the runtime booted open over a persisted stop"
    summary = asyncio.run(runtime.run(cycles=1))
    assert summary.totals()["orders_created"] == 0
    assert broker.calls == 0
    assert summary.cycle_reports[0].assets[0].risk_verdict == "PASS"


def test_a_restart_over_the_same_run_dir_freezes_the_broker(tmp_path: Path) -> None:
    """ACC-G1-04: the second runtime is a new object over the same evidence."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    broker = _SpyBroker()

    first = _build_runtime(run_dir=run_dir, broker=broker, hot_stop=_gate(run_dir))
    assert first.hot_stop.engaged is False
    asyncio.run(first.run(cycles=1))
    assert broker.calls == 1, "the fixture never orders, so the restart proves nothing"

    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: stop before restart")
    second = _build_runtime(run_dir=run_dir, broker=broker, hot_stop=_gate(run_dir))

    assert second.hot_stop.engaged is True
    summary = asyncio.run(second.run(cycles=1))
    assert broker.calls == 1, "the restarted runtime placed an order after the stop"
    assert summary.totals()["orders_created"] == 0


def test_the_runtime_default_gate_restores_from_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-G1-02: the *default* wiring, not only an injected gate.

    ``runtime.py`` builds ``HotStopGate(process_kill_switch(), run_dir)``. That
    default is the one production uses, so it is exercised here — against a
    throw-away process authority, because engaging the real one would stop every
    later test in this interpreter (G1-D-1).
    """
    from trading_bot.autonomous import decision

    fresh = KillSwitch()
    monkeypatch.setattr(decision, "_PROCESS_KILL_SWITCH", fresh)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: restart")

    runtime = _build_runtime(run_dir=run_dir, broker=_SpyBroker(), hot_stop=None)

    assert runtime.hot_stop.kill_switch is fresh
    assert runtime.hot_stop.engaged is True
    assert fresh.state is KillSwitchState.HALTED


def test_a_pre_stop_checkpoint_cannot_rearm(tmp_path: Path) -> None:
    """ACC-G1-06 / REQ-G1-03: the book is restored; the stop is not negotiable.

    A checkpoint is written while the run is still allowed to trade (including
    ``kill_switch_active: false`` in its risk block), then the operator stops
    the run. Startup reconciliation restores that checkpoint first — in the same
    order the production script uses — and the gate must still boot engaged.
    """
    from trading_bot.execution.idempotency import IdempotencyGuard
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.paper_state_store import PaperStateStore, SessionPaperState
    from trading_bot.paper.reconciliation_v4 import ReconciliationStatusV4, StartupReconcilerV4

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    store = PaperStateStore(run_dir / "paper_state.json")
    store.save(
        SessionPaperState(
            schema_version=1,
            run_id="run-1",
            updated_at_ms=0,
            broker_state={
                "equity": 10_000.0,
                "initial_equity": 10_000.0,
                "fills_opened": 1,
                "fills_closed": 0,
            },
            risk_state={
                "daily_pnl": 0.0,
                "weekly_pnl": 0.0,
                "trades_today": 1,
                "consecutive_losses": 0,
                "peak_equity": 10_000.0,
                "kill_switch_active": False,
            },
            open_positions=[],
            closed_trades=[],
            sent_intents=[],
        )
    )
    write_control_file(run_dir / HOT_STOP_FILE_NAME, "operator: stop")

    broker = PaperBroker(equity=10_000.0)
    report = StartupReconcilerV4(
        store=store,
        broker=broker,
        risk_manager=risk_manager(),
        idempotency=IdempotencyGuard(),
    ).reconcile()
    assert report.status is ReconciliationStatusV4.RECOVERED

    gate = _gate(run_dir)
    assert gate.engaged is True
    assert gate.stats()["restored"] is True
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_two_processes_share_the_stop(tmp_path: Path) -> None:
    """ACC-G1-05: the required cross-process proof.

    Process 1 is the real CLI: it writes the request and exits 0 without ever
    claiming enforcement. Process 2 is the real runtime in a fresh interpreter:
    it must boot engaged, with the hostile engine ordering and the broker
    counting. A sibling run directory with no marker is the control that proves
    the fixture can reach the broker at all.
    """
    blocked_dir = tmp_path / "run-blocked"
    blocked_dir.mkdir()
    control_dir = tmp_path / "run-control"
    control_dir.mkdir()

    cli = _run_cli(
        "kill-switch",
        "--run-dir",
        str(blocked_dir),
        "--engage",
        "--reason",
        "operator: cross-process",
    )
    assert cli.returncode == 0, cli.stderr[-600:]
    requested = json.loads(cli.stdout)
    assert requested["status"] == "REQUESTED"
    assert requested["enforced"] is False

    blocked = _probe(blocked_dir)
    assert blocked["engaged_before_first_cycle"] is True
    assert blocked["engaged_after_cycle"] is True
    assert blocked["restored"] is True
    assert blocked["broker_calls"] == 0
    assert blocked["orders_created"] == 0
    assert blocked["risk_verdict"] == "PASS", "the block must not be a risk veto"

    control = _probe(control_dir)
    assert control["engaged_before_first_cycle"] is False
    assert control["broker_calls"] == 1, "the control never orders, so the block proves nothing"
    assert control["orders_created"] == 1

    for payload in (blocked, control):
        module_file = Path(payload["module_file"]).resolve()
        assert module_file.is_relative_to((REPO_ROOT / "src").resolve()), (
            f"the probe imported {module_file}, not this checkout"
        )

    assert [e["event"] for e in _events(blocked_dir)] == ["restored"]


def test_disarm_is_refused_and_does_not_clear_the_marker(tmp_path: Path) -> None:
    """ACC-G1-05 / REQ-G1-08: the stop cannot be undone from the CLI."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    marker = run_dir / HOT_STOP_FILE_NAME
    write_control_file(marker, "operator: stop")

    completed = _run_cli("kill-switch", "--run-dir", str(run_dir), "--engage", "--disarm")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "monotono" in completed.stderr
    assert marker.read_text(encoding="utf-8").strip() == "operator: stop"
    assert _gate(run_dir).engaged is True
