"""G-2 — hot activation of the kill switch.

The claim under test is narrow and checkable: a process that is already
running can be stopped **without a restart**, and once it has answered, no new
broker call can begin.

Three things this file refuses to accept as evidence:

1. **A decision, not a stop.** Asserting ``mode == NO_TRADE`` passes even when
   an order was built and thrown away. The counter that matters is
   ``broker.calls``.
2. **Rule 0 doing the work.** The dispatch boundary is proved *independently*:
   the engine in ``test_the_boundary_blocks_even_when_the_engine_always_orders``
   always returns TRADE_PAPER, so a passing test cannot be rule 0.
3. **A test that never orders.** Every "blocked" assertion is paired with a
   control in the same fixture that does reach the broker. Without it, a broken
   fixture would read as a passing safety property.

The mutation matrix that proves these tests are *sensitive* lives in
``scripts/audit/g2_mutants.py``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

from trading_bot.autonomous.contracts import DecisionMode
from trading_bot.autonomous.decision import DecisionResult
from trading_bot.autonomous.hot_stop import (
    AUDIT_FILE_NAME,
    HOT_STOP_FILE_NAME,
    HotStopGate,
)
from trading_bot.domain.enums.kill_switch import KillSwitchState
from trading_bot.market_data.types import OHLCV
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


def _gate(switch: KillSwitch | None, run_dir: Path, **kwargs: Any) -> HotStopGate:
    return HotStopGate(
        kill_switch=switch if switch is not None else KillSwitch(),
        run_dir=run_dir,
        now_ms=lambda: 1_700_000_000_000,
        **kwargs,
    )


def _audit_lines(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / AUDIT_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- unit: the control channel ----------------------------------------------


def test_control_file_engages(tmp_path: Path) -> None:
    switch = KillSwitch()
    gate = _gate(switch, tmp_path)
    (tmp_path / HOT_STOP_FILE_NAME).write_text("dragged by hand\n", encoding="utf-8")

    assert gate.poll(run_id="run-1") is True
    assert gate.engaged is True
    assert switch.state is KillSwitchState.HALTED
    assert switch.is_active is True


def test_the_ack_names_state_actor_and_reason(tmp_path: Path) -> None:
    """REQ-G2-06: an operator reading the file can tell who stopped what, when."""
    switch = KillSwitch()
    gate = _gate(switch, tmp_path, run_id="run-1", commit="abc1234")
    (tmp_path / HOT_STOP_FILE_NAME).write_text("drawdown watching\n", encoding="utf-8")
    gate.poll(run_id="run-1")

    events = _audit_lines(tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "engaged"
    assert event["run_id"] == "run-1"
    assert event["previous_state"] == "normal"
    assert event["new_state"] == "halted"
    assert event["actor"] == f"control_file:{tmp_path / HOT_STOP_FILE_NAME}"
    assert event["reason"] == "drawdown watching"
    assert event["commit"] == "abc1234"
    assert event["version"]
    assert event["boundary"].startswith("autonomous.runtime._execute_paper")
    assert event["activated_at_ms"] == 1_700_000_000_000


def test_engage_is_idempotent_and_audited(tmp_path: Path) -> None:
    """ACC-G2-03: a second and third engage do not rearm, and do get recorded."""
    switch = KillSwitch()
    gate = _gate(switch, tmp_path)

    first = gate.engage("first")
    second = gate.engage("second")
    third = gate.engage("third")

    assert first.repeated is False
    assert second.repeated is True and third.repeated is True
    assert switch.state is KillSwitchState.HALTED
    assert gate.engaged is True
    events = _audit_lines(tmp_path)
    assert [e["event"] for e in events] == ["engaged", "already_engaged", "already_engaged"]
    # The first reason is the one that stopped the process; a later engage must
    # not rewrite history.
    assert gate.engaged_reason == "first"


def test_deleting_the_control_file_does_not_rearm(tmp_path: Path) -> None:
    """REQ-G2-02: engaged is terminal for the life of the process."""
    switch = KillSwitch()
    gate = _gate(switch, tmp_path)
    control = tmp_path / HOT_STOP_FILE_NAME
    control.write_text("stop\n", encoding="utf-8")
    gate.poll(run_id="run-1")
    control.unlink()

    assert gate.poll(run_id="run-2") is True
    assert gate.engaged is True
    assert switch.state is KillSwitchState.HALTED
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_unreadable_control_path_engages(tmp_path: Path) -> None:
    """REQ-G2-05: an unreadable request is a stop, not a reason to keep trading."""
    switch = KillSwitch()
    gate = _gate(switch, tmp_path, control_path=tmp_path)  # a directory: read raises OSError

    assert gate.poll(run_id="run-1") is True
    assert gate.engaged is True
    assert switch.state is KillSwitchState.HALTED
    assert _audit_lines(tmp_path)[0]["reason"].startswith("control_file_unreadable")


def test_the_boundary_refuses_and_counts(tmp_path: Path) -> None:
    gate = _gate(None, tmp_path)
    gate.engage("boom")

    for _ in range(3):
        with gate.order_boundary() as allowed:
            assert allowed is False
    assert gate.stats()["orders_blocked"] == 3
    assert gate.stats()["broker_calls_allowed"] == 0


# --- concurrency: the linearization point -----------------------------------


def test_engage_waits_for_the_in_flight_dispatch(tmp_path: Path) -> None:
    """ACC-G2-04 / REQ-G2-03.

    While a broker call is in flight the gate's lock is held, so ``engage``
    cannot answer. That is what makes its ACK mean "nothing is running": a stop
    that returned early would let an order land after the operator was told the
    process was stopped.
    """
    switch = KillSwitch()
    gate = _gate(switch, tmp_path, boundary_timeout_seconds=10.0)
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

    acks: list[Any] = []
    engager = threading.Thread(target=lambda: acks.append(gate.engage("race")), daemon=True)
    engager.start()
    time.sleep(0.2)
    assert engager.is_alive(), "engage answered ACK while a dispatch was in flight"

    release.set()
    engager.join(10.0)
    worker.join(10.0)
    assert acks and acks[0].repeated is False
    with gate.order_boundary() as allowed:
        assert allowed is False


def test_engage_engages_when_the_lock_is_wedged(tmp_path: Path) -> None:
    """A stop must never wait on the thing it is stopping.

    If the lock cannot be taken, the gate engages anyway and says so
    (``lock_timeout``) rather than reporting a clean shutdown it did not achieve.
    """
    switch = KillSwitch()
    gate = _gate(switch, tmp_path, boundary_timeout_seconds=0.05)
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with gate.order_boundary() as allowed:
            assert allowed is True
            held.set()
            release.wait(5.0)

    worker = threading.Thread(target=hold, daemon=True)
    worker.start()
    assert held.wait(5.0)

    ack = gate.engage("wedged")
    assert ack.lock_timeout is True
    assert gate.engaged is True
    assert switch.state is KillSwitchState.HALTED

    release.set()
    worker.join(5.0)


# --- runtime: the boundary, with the engine deliberately wrong ---------------


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
    """A future regression, simulated: ignores the packet and always orders.

    Rule 0 lives *before* this object, so a test that used the real engine could
    not tell whether the stop worked or the decision engine simply obeyed. Here
    the decision engine is hostile on purpose.
    """

    version = "hostile"

    def intend(self, request: Any) -> DecisionResult:
        return DecisionResult(
            mode=DecisionMode.TRADE_PAPER,
            reason="hostile_intent",
            classification="PAPER_ADMITTED",
            order_authorised=False,
        )

    def decide(self, request: Any) -> DecisionResult:
        return DecisionResult(
            mode=DecisionMode.TRADE_PAPER,
            reason="hostile_decision",
            classification="PAPER_ADMITTED",
            order_authorised=True,
            notional_usdt=250.0,
        )


class _Settings:
    class runtime:
        mode = "PAPER"
        exchange_id = "fake"

    class risk:
        kill_switch_enabled = True


def _build_runtime(
    *,
    run_dir: Path,
    broker: Any,
    ledger: Any,
    reader: Any,
    scanner: Any,
    hot_stop: HotStopGate | None,
    decision_engine: Any,
) -> Any:
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime

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
    return AutonomousPaperRuntime(
        settings=_Settings(),
        scanner_factory=lambda: scanner,
        history_reader=reader,
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
        decision_engine=decision_engine,
        hot_stop=hot_stop,
    )


def test_the_boundary_blocks_even_when_the_engine_always_orders(tmp_path: Path) -> None:
    """ACC-G2-02 / REQ-G2-04: risk PASS, engine orders, broker is never called."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    broker = _SpyBroker()
    history = {"BTC/USDT": bars("BTC/USDT", 80)}

    def build(gate: HotStopGate | None) -> Any:
        return _build_runtime(
            run_dir=tmp_path,
            broker=broker,
            ledger=ledger,
            reader=StaticReader(history),
            scanner=_FixedScanner(history),
            hot_stop=gate,
            decision_engine=_AlwaysTradeEngine(),
        )

    # Control: with the gate open this fixture really does reach the broker.
    open_runtime = build(_gate(None, tmp_path / "open"))
    control = asyncio.run(open_runtime.run(cycles=1))
    row = control.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.TRADE_PAPER
    assert broker.calls == 1, "the fixture never orders, so the block proves nothing"

    engaged_gate = _gate(None, tmp_path / "engaged")
    engaged_gate.engage("pre-engaged")
    closed_runtime = build(engaged_gate)
    blocked = asyncio.run(closed_runtime.run(cycles=1))
    blocked_row = blocked.cycle_reports[0].assets[0]
    assert blocked.totals()["orders_created"] == 0
    assert broker.calls == 1, "the stop let a new order reach the broker"
    # The risk engine is asked and says PASS: the block is not a risk veto.
    assert blocked_row.risk_verdict == "PASS"


class _FixedScanner:
    def __init__(self, history: dict[str, list[OHLCV]]) -> None:
        self._history = history

    async def run(self) -> list[FakeSnapshot]:
        return [
            FakeSnapshot(symbol=symbol, timestamp=series[-1].timestamp + BAR_MS)
            for symbol, series in self._history.items()
        ]


class _EvolvingState:
    def __init__(self, n: int = 90) -> None:
        self.history: dict[str, list[OHLCV]] = {"BTC/USDT": bars("BTC/USDT", n)}

    def advance(self) -> None:
        series = self.history["BTC/USDT"]
        last = series[-1]
        price = last.close + 1.0
        series.append(
            OHLCV(
                symbol=last.symbol,
                timestamp=last.timestamp + BAR_MS,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )

    def last_ts(self) -> int:
        return self.history["BTC/USDT"][-1].timestamp


class _EvolvingScanner:
    def __init__(self, state: _EvolvingState) -> None:
        self._state = state
        self.counters: Any = None

    async def run(self) -> list[FakeSnapshot]:
        return [FakeSnapshot(symbol="BTC/USDT", timestamp=self._state.last_ts() + BAR_MS)]


class _EvolvingReader:
    def __init__(self, state: _EvolvingState) -> None:
        self._state = state

    async def get_ohlcv(
        self, symbol: str, *, as_of_timestamp_ms: int, lookback_bars: int
    ) -> list[OHLCV]:
        window = [
            b for b in self._state.history.get(symbol, []) if b.timestamp <= as_of_timestamp_ms
        ]
        return window[-lookback_bars:]


def test_a_running_runtime_engages_between_cycles_without_restart(tmp_path: Path) -> None:
    """ACC-G2-01 / ACC-G2-11: operational → engaged → NO_ORDER, same process.

    No new runtime, no new interpreter, no re-import: the object that placed the
    first order is the object that refuses the second, which is what "hot" means.
    """
    state = _EvolvingState()
    broker = _SpyBroker()
    runtime = _build_runtime(
        run_dir=tmp_path,
        broker=broker,
        ledger=make_admitted_ledger(gross_bps=50.0),
        reader=_EvolvingReader(state),
        scanner=_EvolvingScanner(state),
        hot_stop=None,  # the runtime builds its own gate over run_dir
        decision_engine=_AlwaysTradeEngine(),
    )
    assert runtime.hot_stop.engaged is False

    first = asyncio.run(runtime.run_cycle(cycle=1))
    assert first.assets[0].mode is DecisionMode.TRADE_PAPER
    assert broker.calls == 1

    # The operator drops the control file while the process is alive.
    (tmp_path / HOT_STOP_FILE_NAME).write_text("operator: runaway\n", encoding="utf-8")
    state.advance()
    second = asyncio.run(runtime.run_cycle(cycle=2))

    assert runtime.hot_stop.engaged is True
    assert broker.calls == 1, "the second cycle placed an order after the stop"
    assert second.assets[0].order_created is False
    events = _audit_lines(tmp_path)
    assert [e["event"] for e in events] == ["engaged"]
    assert events[0]["reason"] == "operator: runaway"
    assert events[0]["run_id"], "the event must name the cycle that observed it"

    # And it stays stopped on the next cycle, without the file being re-read as
    # a reason to rearm.
    state.advance()
    third = asyncio.run(runtime.run_cycle(cycle=3))
    assert third.assets[0].order_created is False
    assert broker.calls == 1


def test_an_open_gate_does_not_touch_the_switch(tmp_path: Path) -> None:
    """Control: no engagement, no state change, dispatch allowed."""
    switch = KillSwitch()
    gate = _gate(switch, tmp_path)
    assert gate.poll(run_id="run-1") is False
    assert switch.state is KillSwitchState.NORMAL
    with gate.order_boundary() as allowed:
        assert allowed is True
    assert gate.stats()["broker_calls_allowed"] == 1
    assert _audit_lines(tmp_path) == []


def test_a_broken_switch_still_leaves_the_gate_closed(tmp_path: Path) -> None:
    """REQ-G2-05: if ``activate`` raises, the boundary must still refuse."""

    class _Exploding:
        state = KillSwitchState.NORMAL
        is_active = False

        def activate(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("switch store unavailable")

    gate = HotStopGate(kill_switch=_Exploding(), run_dir=tmp_path)
    ack = gate.engage("boom")
    assert ack.activation_error is not None
    assert gate.engaged is True
    with gate.order_boundary() as allowed:
        assert allowed is False
