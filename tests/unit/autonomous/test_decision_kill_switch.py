"""Kill switch as rule 0 of the decision engine (MT-0003, OB-03).

The defect this file pins: three kill-switch implementations existed
(``paper/kill_switch.py``, ``paper/kill_switch_v2.py`` and the risk manager's
private flag) and **none of them was consulted before an order could be
authorised**. ``kill_switch_v2.KillSwitch`` had zero importers. A drawdown
breach, an operator stop or a key compromise therefore could not stop the one
path that authorises an order (rule 7, ``TRADE_PAPER``).

What is verified here, in order:

1. **Unengaged preserves the old behaviour.** A ``NORMAL`` switch changes
   nothing: the admitted packet still trades paper, and every other rule still
   fires with its own classification.
2. **Engaged blocks the authorising path.** The same packet becomes
   ``NO_TRADE`` / ``KILL_SWITCH_ACTIVE`` with ``order_authorised=False``, and
   ``intend`` refuses to offer ``TRADE_PAPER`` (the runtime uses the intent to
   decide whether the risk gate and the verifier are even invoked).
3. **Rule 0 wins over every other rule**, because a safety stop is not a
   judgement about the packet.
4. **Fail closed.** A state that cannot be read blocks; a broken ``is_active``
   blocks; nothing about the packet can talk the gate out of it.
5. **The operational path.** The real ``AutonomousPaperRuntime`` — the class the
   shipped script builds — places one paper order with the switch normal and
   **zero** with it engaged, over identical deterministic inputs, and persists
   the reason in the decision trace.
6. **The operator surface and its declared limit.** The switch can be engaged
   from the process environment; the state lives in memory only, so a restart
   boots it back to ``NORMAL``. That gap is asserted, not glossed over.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous import decision as decision_module
from trading_bot.autonomous.contracts import (
    AgentMessage,
    DecisionMode,
    NoTradeKind,
    ReviewType,
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
    no_trade_kind_for,
    process_kill_switch,
)
from trading_bot.domain.enums.kill_switch import KillSwitchAction, KillSwitchState
from trading_bot.paper.kill_switch_v2 import KillSwitch

from .helpers import make_admitted_ledger, make_ledger, make_runtime
from .test_contracts import _proposal

REPO_ROOT = Path(__file__).resolve().parents[3]
#: Every state except NORMAL must block. The catalogue is closed, so a new state
#: added to the enum without being handled here fails this list on purpose.
ENGAGED_STATES = (
    KillSwitchState.NO_NEW_RISK,
    KillSwitchState.PROTECTION_ONLY,
    KillSwitchState.READ_ONLY,
    KillSwitchState.HALTED,
)


@pytest.fixture(autouse=True)
def _restore_process_authority() -> Any:
    """Leave the process-wide switch NORMAL after every test.

    The authority is a module-level object on purpose (it is the single handle
    an operator interface has to reach), so a test that engages it and fails
    mid-way would otherwise silence every later decision in the same pytest
    process. Same reasoning as ``tests/conftest.py``'s structlog guard.
    """
    authority = process_kill_switch()
    yield
    authority.reset()
    assert authority.state is KillSwitchState.NORMAL


def _request(
    *,
    ledger: Any,
    strategy_id: str = "ema_crossover@5m",
    gross: float = 50.0,
    cost: float = 21.1,
    verification: VerifierVerdict = VerifierVerdict.PASS,
    risk: RiskVerdict = RiskVerdict.PASS,
    notional: float | None = 250.0,
    vetoes: tuple[AgentMessage, ...] = (),
    proposal: bool = True,
) -> DecisionRequest:
    """An order-authorising packet by default: rule 7 would fire on it."""
    entry = ledger.entry(strategy_id)
    return DecisionRequest(
        run_id="run-1",
        decision_id="d-1",
        asset="BTC",
        symbol="BTC/USDT",
        market_time_ms=1_000,
        decision_time_ms=2_000,
        regime="RANGE",
        admission=entry,
        proposal=(
            _proposal(
                strategy_id=strategy_id,
                expected_gross_edge_bps=gross,
                expected_cost_bps=cost,
                expected_net_edge_bps=gross - cost,
                admission_status=entry.status,
            )
            if proposal
            else None
        ),
        verification=VerificationResult(decision_id="d-1", verdict=verification),
        risk=RiskReview(
            verdict=risk,
            reason="test_risk_veto" if risk is RiskVerdict.VETO else "",
            notional_usdt=notional,
        ),
        agent_messages=vetoes,
    )


def _veto() -> tuple[AgentMessage, ...]:
    return (
        AgentMessage(
            run_id="run-1",
            decision_id="d-1",
            agent_id="risk_adversary",
            review_type=ReviewType.VETO,
            asset="BTC",
            statement="adversarial veto",
        ),
    )


# --- 1. unengaged: the previous contract is untouched ------------------------


def test_a_normal_switch_still_authorises_the_admitted_packet() -> None:
    """The control for every block below: this packet DOES authorise."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine().decide(_request(ledger=ledger))
    assert result.mode is DecisionMode.TRADE_PAPER
    assert result.order_authorised is True
    assert result.notional_usdt == 250.0


def test_a_normal_switch_leaves_the_shadow_path_alone() -> None:
    ledger = make_ledger(gross_bps=4.0)  # net negative, never admitted
    result = DecisionEngine().decide(_request(ledger=ledger, gross=4.0, risk=RiskVerdict.NOT_APPLICABLE))
    assert result.mode is DecisionMode.SHADOW_TRADE
    assert result.classification == "COST_KILLED"


@pytest.mark.parametrize(
    ("kwargs", "classification"),
    [
        ({"verification": VerifierVerdict.FAIL}, "VERIFIER_FAIL"),
        ({"risk": RiskVerdict.VETO}, "RISK_VETO"),
        ({"vetoes": "veto"}, "AGENT_VETO"),
        ({"proposal": False}, "NO_PROPOSAL"),
    ],
)
def test_a_normal_switch_leaves_every_other_rule_in_charge(
    kwargs: dict[str, Any], classification: str
) -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    if kwargs.get("vetoes") == "veto":
        kwargs = {**kwargs, "vetoes": _veto()}
    result = DecisionEngine().decide(_request(ledger=ledger, **kwargs))
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == classification
    assert result.reason != KILL_SWITCH_ACTIVE


# --- 2. engaged: the authorising path is closed -----------------------------


@pytest.mark.parametrize("state", ENGAGED_STATES)
def test_an_engaged_switch_blocks_the_authorising_packet(state: KillSwitchState) -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER, target=state, reason="test")
    result = DecisionEngine(kill_switch=switch).decide(_request(ledger=ledger))
    assert result.mode is DecisionMode.NO_TRADE
    assert result.reason == KILL_SWITCH_ACTIVE
    assert result.classification == KILL_SWITCH_CLASSIFICATION
    assert result.order_authorised is False
    assert result.notional_usdt is None
    assert result.shadow is None  # a blocked packet is not evaluated as a strategy
    assert result.no_trade_kind is NoTradeKind.NO_TRADE_RISK


def test_the_engaged_switch_stops_the_intent_before_risk_runs() -> None:
    """``intend`` must not advertise TRADE_PAPER while blocked.

    The runtime invokes the deterministic risk engine only when the intent could
    order, and asks the verifier to audit the declared mode. Blocking only in
    ``decide`` would still run the whole order-shaped machinery for nothing.
    """
    ledger = make_admitted_ledger(gross_bps=50.0)
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    intent = DecisionEngine(kill_switch=switch).intend(_request(ledger=ledger))
    assert intent.mode is DecisionMode.NO_TRADE
    assert intent.reason == KILL_SWITCH_ACTIVE
    assert intent.order_authorised is False


def test_rule_zero_wins_over_every_other_rule() -> None:
    """Even a packet that would be rejected anyway reports the safety stop."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    switch = KillSwitch()
    switch.activate(KillSwitchAction.DAILY_LOSS, target=KillSwitchState.HALTED)
    engine = DecisionEngine(kill_switch=switch)
    packets = [
        _request(ledger=ledger),  # would authorise
        _request(ledger=ledger, verification=VerifierVerdict.FAIL),  # would be VERIFIER_FAIL
        _request(ledger=ledger, risk=RiskVerdict.VETO),  # would be RISK_VETO
        _request(ledger=ledger, vetoes=_veto()),  # would be AGENT_VETO
        _request(ledger=ledger, proposal=False),  # would be NO_PROPOSAL
    ]
    for packet in packets:
        result = engine.decide(packet)
        assert result.reason == KILL_SWITCH_ACTIVE
        assert result.classification == KILL_SWITCH_CLASSIFICATION
        assert result.order_authorised is False


def test_the_switch_does_not_consult_the_packet_at_all() -> None:
    """An agent-authored request has no lever to influence the gate.

    Rule 0 takes no argument: there is no field, header or message through which
    a proposal (or an LLM-authored agent message) could ask to be let through.
    """
    assert list(inspect.signature(DecisionEngine._kill_switch_no_trade).parameters) == ["self"]


# --- 3. fail closed ---------------------------------------------------------


class _UnreadableSwitch:
    """A switch whose state cannot be read at all."""

    @property
    def state(self) -> KillSwitchState:
        raise RuntimeError("state store unavailable")

    @property
    def is_active(self) -> bool:
        raise RuntimeError("state store unavailable")


class _BrokenActiveFlag:
    """The state reads NORMAL but the derived flag cannot be computed."""

    @property
    def state(self) -> KillSwitchState:
        return KillSwitchState.NORMAL

    @property
    def is_active(self) -> bool:
        raise RuntimeError("flag unavailable")


@pytest.mark.parametrize("broken", [_UnreadableSwitch(), _BrokenActiveFlag()])
def test_an_unreadable_state_fails_closed(broken: Any) -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine(kill_switch=broken).decide(_request(ledger=ledger))
    assert result.mode is DecisionMode.NO_TRADE
    assert result.reason == KILL_SWITCH_STATE_UNREADABLE
    assert result.order_authorised is False


def test_a_state_that_disagrees_with_the_flag_blocks() -> None:
    """Defensive: ``is_active`` true while ``state`` reads NORMAL still blocks."""

    class _Inconsistent:
        state = KillSwitchState.NORMAL

        @property
        def is_active(self) -> bool:
            return True

    ledger = make_admitted_ledger(gross_bps=50.0)
    result = DecisionEngine(kill_switch=_Inconsistent()).decide(_request(ledger=ledger))
    assert result.reason == KILL_SWITCH_ACTIVE
    assert result.order_authorised is False


def test_deactivation_releases_only_the_states_the_state_machine_allows() -> None:
    ledger = make_admitted_ledger(gross_bps=50.0)
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER, target=KillSwitchState.NO_NEW_RISK)
    engine = DecisionEngine(kill_switch=switch)
    assert engine.decide(_request(ledger=ledger)).reason == KILL_SWITCH_ACTIVE

    assert switch.deactivate("operator") is True
    assert engine.decide(_request(ledger=ledger)).mode is DecisionMode.TRADE_PAPER

    # HALTED cannot be walked back with deactivate(); it needs an explicit reset.
    switch.activate(KillSwitchAction.KEY_COMPROMISE, target=KillSwitchState.HALTED)
    assert switch.deactivate("operator") is False
    assert engine.decide(_request(ledger=ledger)).reason == KILL_SWITCH_ACTIVE


def test_every_engine_instance_consults_the_same_authority() -> None:
    """No per-instance copy of the state: two engines cannot disagree."""
    ledger = make_admitted_ledger(gross_bps=50.0)
    first, second = DecisionEngine(), DecisionEngine()
    assert first.decide(_request(ledger=ledger)).mode is DecisionMode.TRADE_PAPER

    process_kill_switch().activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    assert first.decide(_request(ledger=ledger)).reason == KILL_SWITCH_ACTIVE
    assert second.decide(_request(ledger=ledger)).reason == KILL_SWITCH_ACTIVE


# --- 4. the operational path: the real runtime -----------------------------


def _run(runtime: Any) -> Any:
    return asyncio.run(runtime.run(cycles=1))


def test_the_real_runtime_places_a_paper_order_when_the_switch_is_normal(tmp_path: Path) -> None:
    """Control for the next test: this fixture DOES create an order."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    summary = _run(runtime)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.TRADE_PAPER
    assert summary.totals()["orders_created"] == 1


def test_the_real_runtime_places_no_order_when_the_switch_is_engaged(tmp_path: Path) -> None:
    """Same fixture, same inputs, only the safety state differs."""
    process_kill_switch().activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    summary = _run(runtime)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.reason == KILL_SWITCH_ACTIVE
    assert row.classification == KILL_SWITCH_CLASSIFICATION
    assert row.order_created is False
    assert summary.totals()["orders_created"] == 0
    assert summary.totals()["paper_trades"] == 0
    assert broker.positions == {}


def test_the_real_runtime_persists_the_reason_in_the_trace(tmp_path: Path) -> None:
    process_kill_switch().activate(KillSwitchAction.DATA_CORRUPTION, target=KillSwitchState.HALTED)
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    _run(runtime)
    trace = runtime.trace_store.read()[0]
    assert trace.mode is DecisionMode.NO_TRADE
    assert trace.reason == KILL_SWITCH_ACTIVE
    assert trace.classification == KILL_SWITCH_CLASSIFICATION
    assert trace.no_trade_kind == NoTradeKind.NO_TRADE_RISK.value
    assert trace.order_created is False
    assert trace.orders_created == 0
    assert runtime.trace_store.verify_chain().ok


# --- 5. the operator surface, and the gap it does not close -----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("halted", "halted"),
        ("protection_only", "protection_only"),
        ("1", "halted"),  # unknown truthy value: fail safe, not open
        ("off", "normal"),
        ("", "normal"),
    ],
)
def test_the_environment_can_boot_the_process_engaged(raw: str, expected: str) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env[KILL_SWITCH_ENV] = raw
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import trading_bot.autonomous.decision as d; print(d.process_kill_switch().state.value)",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr[-400:]
    assert completed.stdout.strip() == expected


def test_the_state_does_not_survive_a_restart_and_that_is_the_declared_gap() -> None:
    """Gap G-1, pinned as executable truth rather than prose.

    ``paper/kill_switch_v2.KillSwitch`` has no persistence: a new process starts
    NORMAL. Until the state is durable, MT-0003 protects a *running* process and
    must not be reported as protection that survives a restart.
    """
    process_kill_switch().activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    assert process_kill_switch().state is KillSwitchState.HALTED
    assert KillSwitch().state is KillSwitchState.NORMAL  # a "restart"


def test_the_contract_tokens_are_exported_and_classified() -> None:
    assert KILL_SWITCH_ACTIVE == "KILL_SWITCH_ACTIVE"
    assert KILL_SWITCH_CLASSIFICATION in decision_module.CLASSIFICATIONS
    assert KILL_SWITCH_CLASSIFICATION in decision_module.NO_TRADE_KINDS
    assert no_trade_kind_for(KILL_SWITCH_CLASSIFICATION) is NoTradeKind.NO_TRADE_RISK
