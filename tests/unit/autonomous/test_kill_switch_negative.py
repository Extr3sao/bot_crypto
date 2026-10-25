"""Negative controls for the kill-switch gate (MT-0004-R1, REISSUED).

MT-0003's suite (`test_decision_kill_switch.py`) proves rule 0 works **while it
is there**. This file asks the complementary question: does the control actually
carry the weight, and does it still behave when something around it is wrong?

Nothing here repeats MT-0003's matrix. The cases are the ones that only exist
when you look for the control's absence:

1. **The broker is never called.** MT-0003 counts orders; an order that is
   built and then discarded would still be a leak. The spy here counts
   ``execute_signal`` calls and asserts the risk engine said PASS — so the
   block demonstrably comes from rule 0 and not from another gate.
2. **A malformed packet cannot preempt the stop.** ``decide`` raises on an
   advisory risk review sitting on an authorising packet. With the switch
   engaged the same packet must return NO_TRADE instead of raising: a halted
   loop reports, it does not crash.
3. **Half-broken state objects fail closed.** A switch that lost ``state``
   entirely, or whose state reads ``None``, must block.
4. **Only an explicit off token boots the process trading.** MT-0003 pins five
   values; this pins the boundary of the off-whitelist (case, whitespace,
   unknown truthy strings).
5. **A blocked packet is not evaluated as a strategy.** ``intend`` must not
   report a shadow evaluation for a packet that cannot be looked at.

The mutation matrix that proves these tests are *sensitive* (and not merely
green) lives in ``scripts/audit/negative_controls.py``: it removes rule 0, makes
the except branch fail open, and changes the boot policy, and fails if the suite
stays green.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import trading_bot
from trading_bot.autonomous.contracts import (
    DecisionMode,
    RiskReview,
    RiskVerdict,
    VerificationResult,
    VerifierVerdict,
)
from trading_bot.autonomous.decision import (
    KILL_SWITCH_ACTIVE,
    KILL_SWITCH_CLASSIFICATION,
    KILL_SWITCH_ENV,
    KILL_SWITCH_STATE_UNREADABLE,
    DecisionEngine,
    DecisionRequest,
    process_kill_switch,
)
from trading_bot.domain.enums.kill_switch import KillSwitchAction, KillSwitchState
from trading_bot.paper.kill_switch_v2 import KillSwitch

from .helpers import make_admitted_ledger, make_runtime
from .test_contracts import _proposal

#: The ``src`` directory of the tree THIS process imported. Derived from the
#: module, not from ``__file__``: under the mutation harness the tests and the
#: production module come from the same exported tree but not from this file's
#: checkout, and a hardcoded path would spawn the subprocess against pristine
#: code — the exact false-green the harness exists to catch.
SRC_DIR = Path(trading_bot.__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_process_authority() -> Any:
    """Leave the process-wide switch NORMAL after every test (same reasoning as
    MT-0003: the authority is module-level, so a failing test must not silence
    the decisions that follow it in the same process)."""
    authority = process_kill_switch()
    yield
    authority.reset()
    assert authority.state is KillSwitchState.NORMAL


def _request(
    *,
    ledger: Any,
    risk: RiskReview | None = None,
    gross: float = 50.0,
    cost: float = 21.1,
) -> DecisionRequest:
    """An order-authorising packet: admitted, positive net edge, verifier PASS."""
    entry = ledger.entry("ema_crossover@5m")
    return DecisionRequest(
        run_id="run-1",
        decision_id="d-1",
        asset="BTC",
        symbol="BTC/USDT",
        market_time_ms=1_000,
        decision_time_ms=2_000,
        regime="RANGE",
        admission=entry,
        proposal=_proposal(
            strategy_id="ema_crossover@5m",
            expected_gross_edge_bps=gross,
            expected_cost_bps=cost,
            expected_net_edge_bps=gross - cost,
            admission_status=entry.status,
        ),
        verification=VerificationResult(decision_id="d-1", verdict=VerifierVerdict.PASS),
        risk=risk
        if risk is not None
        else RiskReview(verdict=RiskVerdict.PASS, reason="", notional_usdt=250.0),
    )


def _engaged() -> KillSwitch:
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER, target=KillSwitchState.HALTED, reason="negative-test")
    return switch


# --- 1. the broker is never called -------------------------------------------


class _SpyBroker:
    """Counts the one call that would create an order, and nothing else."""

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


def test_a_blocked_decision_never_reaches_the_broker(tmp_path: Path) -> None:
    """Risk approves, the strategy is admitted, the edge is positive — still no call.

    This is the case a weaker test misses: asserting ``orders_created == 0``
    passes even when an order was built and thrown away. ``broker.calls == 0``
    does not.
    """
    broker = _SpyBroker()
    process_kill_switch().activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    runtime, _scanner, _ = make_runtime(
        run_dir=tmp_path,
        ledger=make_admitted_ledger(gross_bps=50.0),
        broker=broker,
    )
    summary = asyncio.run(runtime.run(cycles=1))
    row = summary.cycle_reports[0].assets[0]

    assert row.mode is DecisionMode.NO_TRADE
    assert row.reason == KILL_SWITCH_ACTIVE
    assert row.classification == KILL_SWITCH_CLASSIFICATION
    assert row.order_created is False
    assert summary.totals()["orders_created"] == 0
    assert summary.totals()["paper_trades"] == 0
    assert broker.calls == 0, "the safety stop let an order reach the broker"
    assert broker.positions == {}

    # The block did not come from risk: the deterministic engine ran and said
    # PASS (advisory, because the decision cannot order). Only rule 0 stopped it.
    assert row.risk_evaluated is True
    assert row.risk_verdict == RiskVerdict.PASS.value


# --- 2. a malformed packet cannot preempt the stop ---------------------------


def _advisory_on_an_authorising_packet(ledger: Any) -> DecisionRequest:
    return _request(
        ledger=ledger,
        risk=RiskReview(verdict=RiskVerdict.PASS, advisory=True, notional_usdt=250.0),
    )


def test_an_advisory_review_on_an_authorising_packet_is_rejected_while_normal() -> None:
    """Control for the next test: while NORMAL the engine refuses the packet."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    with pytest.raises(ValueError):
        DecisionEngine().decide(_advisory_on_an_authorising_packet(ledger))


def test_the_safety_stop_preempts_that_rejection() -> None:
    """While halted the same malformed packet returns NO_TRADE, it does not raise.

    A halted loop must keep reporting. If rule 0 ran after the packet
    validation, an invalid packet would crash the cycle instead of being
    absorbed by the stop.
    """
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine(kill_switch=_engaged()).decide(
        _advisory_on_an_authorising_packet(ledger)
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.reason == KILL_SWITCH_ACTIVE
    assert result.order_authorised is False


# --- 3. half-broken state objects fail closed --------------------------------


class _NoStateAttribute:
    """A switch object that lost its state entirely."""

    @property
    def is_active(self) -> bool:
        return False


class _NullState:
    """A corrupted store: the attribute exists but reads None."""

    state = None
    is_active = False


@pytest.mark.parametrize("broken", [_NoStateAttribute(), _NullState()])
def test_a_broken_state_object_blocks(broken: Any) -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine(kill_switch=broken).decide(_request(ledger=ledger))
    assert result.mode is DecisionMode.NO_TRADE
    assert result.reason in {KILL_SWITCH_STATE_UNREADABLE, KILL_SWITCH_ACTIVE}
    assert result.order_authorised is False


def test_an_absent_state_is_reported_as_unreadable_not_as_engaged() -> None:
    """The two reasons are different operator instructions; keep them distinct."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine(kill_switch=_NoStateAttribute()).decide(_request(ledger=ledger))
    assert result.reason == KILL_SWITCH_STATE_UNREADABLE


# --- 4. only an explicit off token boots the process trading -----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("halted", "halted"),
        ("HALTED", "halted"),  # case must not matter
        (" halted ", "halted"),  # whitespace must not matter
        ("yes", "halted"),  # unknown truthy: fail safe, never open
        ("", "normal"),
        ("0", "normal"),
        ("off", "normal"),
        ("false", "normal"),
    ],
)
def test_only_an_explicit_off_token_boots_the_process_trading(raw: str, expected: str) -> None:
    """The boot policy is a whitelist of off tokens, not a blacklist of on ones."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env[KILL_SWITCH_ENV] = raw
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import trading_bot, trading_bot.autonomous.decision as d;"
                " print(trading_bot.__file__);"
                " print(d.process_kill_switch().state.value)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr[-400:]
    imported, state = completed.stdout.strip().splitlines()
    # TEST_TARGET == RUNTIME_TARGET: a child that imported another checkout
    # would prove nothing about the code under test.
    assert Path(imported).resolve().is_relative_to(SRC_DIR), (
        f"the subprocess imported {imported}, not the tree under test ({SRC_DIR})"
    )
    assert state == expected


# --- 5. a blocked packet is not evaluated as a strategy ----------------------


def test_a_blocked_intent_does_not_offer_a_shadow_evaluation() -> None:
    """A packet stopped by the safety gate must not consume research machinery."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    intent = DecisionEngine(kill_switch=_engaged()).intend(_request(ledger=ledger))
    assert intent.is_shadow is False
    assert intent.shadow is None
    assert intent.notional_usdt is None
    assert intent.order_authorised is False
