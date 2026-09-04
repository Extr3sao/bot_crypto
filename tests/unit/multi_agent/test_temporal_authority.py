"""Temporal authority regression tests T1-T6.

Verifies:
- T1: Valid proposal accepted when clock is within validity window
- T2: Expired proposal rejected
- T3: Future data_time rejected (data_time > board.now)
- T4: Deterministic replay — same inputs + same clock = same outputs
- T5: Wall-clock independence — result depends on injected clock, not host time
- T6: Canonical evaluate API — strategy_names= used everywhere, no divergent spelling
- DEF-MA2-001: AgentBus clock is an explicit, required constructor dependency
- DEF-MA2-003: swarm derives every timestamp from the single bus run clock
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent import (
    AgentRegistry,
    Blackboard,
    CapabilityRegistry,
    OpportunityBoard,
    TraceContext,
    register_swarm_agents,
)
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.communication_errors import ExpiredMessageError
from trading_bot.multi_agent.contracts import (
    AgentEvidence,
    AgentMessage,
    AgentMessageType,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.opportunity import OpportunityError
from trading_bot.multi_agent.specialists import PROPOSAL_VALIDITY
from trading_bot.multi_agent.swarm import SpecialistSwarm
from trading_bot.research.asset_intelligence.models import AssetContext

# 2026-01-01 12:00:00 UTC — consistent across all fixtures
CLOCK = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
# Millisecond equivalent of CLOCK
CONTEXT_TS = 1_767_268_800_000

TRACE = TraceContext(
    run_id="temporal-test-run",
    trace_id="temporal-test-trace",
    correlation_id="temporal-test-corr",
    causation_id="temporal-test-cause",
)


def _fixed_clock(ts: datetime) -> object:
    return lambda: ts


def _make_bus(clock: Callable[[], datetime]) -> AgentBus:
    """Build a bus with its explicit required run clock (DEF-MA2-001)."""
    agent_reg = AgentRegistry()
    cap_reg = CapabilityRegistry()
    register_swarm_agents(agent_reg, cap_reg)
    bb = Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id)
    return AgentBus(
        agent_registry=agent_reg,
        capability_registry=cap_reg,
        blackboard=bb,
        clock=clock,
    )


def _accelerating_candles(asset: str, count: int = 80) -> list[OHLCV]:
    """Compound accelerating candles that trigger MomentumFamily LONG."""
    start = CONTEXT_TS - (count - 1) * 300_000
    out: list[OHLCV] = []
    price = 100.0
    for i in range(count):
        ts = start + i * 300_000
        price *= 1.002
        out.append(
            OHLCV(f"{asset}/USDT", ts, price * 0.998, price * 1.002, price * 0.996, price, 100.0)
        )
    return out


def _ctx(
    asset: str = "SOL",
    timestamp: int = CONTEXT_TS,
    returns: float = 0.06,
    trend_spread: float = 0.015,
    liquidity: str = "deep",
    bars: int = 120,
    volatility: float = 0.01,
) -> AssetContext:
    return AssetContext(
        asset=asset,
        timestamp=timestamp,
        market_regime="TREND_UP",
        trend_state="up" if returns > 0 else ("down" if returns < 0 else "flat"),
        volatility_state="normal",
        liquidity_state=liquidity,
        momentum_features={
            "returns": returns,
            "trend": {"direction": "up" if returns > 0 else "down", "spread": trend_spread},
            "rsi": 65.0 if returns > 0 else 35.0,
        },
        volatility_features={"atr_norm": volatility},
        volume_features={"surge": 1.2},
        data_quality={"bars_in_window": bars, "newest_bar_ts": timestamp},
        data_fingerprint="a" * 64,
        dataset_id="temporal-test",
        agent_version="base-crypto-v1",
        regime_method_version="asset-agent-regime-v1",
        window_start_ts=timestamp - (bars - 1) * 300_000,
        window_end_ts=timestamp,
        bar_count=bars,
    )


def _run_swarm_at(clock_time: datetime) -> tuple[SpecialistSwarm, OpportunityBoard, AgentBus]:
    """Build a swarm whose single temporal authority is ``clock_time``."""
    bus = _make_bus(clock=_fixed_clock(clock_time))
    board = OpportunityBoard(run_id=TRACE.run_id, now=clock_time)
    swarm = SpecialistSwarm(bus=bus, board=board)
    return swarm, board, bus


# ---------------------------------------------------------------------------
# DEF-MA2-001: bus clock is an explicit constructor dependency
# ---------------------------------------------------------------------------


def test_bus_requires_explicit_clock() -> None:
    """AgentBus must not be constructible without an explicit run clock.

    A silent wall-clock default is the DEF-MA2-001 failure mode: replay
    against historical fixtures then expires every message/proposal against
    host time. If AgentBus ever regresses to clock=None defaulting, this
    test fails because construction succeeds again.
    """
    agent_reg = AgentRegistry()
    cap_reg = CapabilityRegistry()
    register_swarm_agents(agent_reg, cap_reg)
    bb = Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id)
    with pytest.raises(TypeError):
        AgentBus(agent_registry=agent_reg, capability_registry=cap_reg, blackboard=bb)  # type: ignore[call-arg]


def test_bus_rejects_message_when_wall_clock_is_far_ahead() -> None:
    """Reproduce the original 2026-01 vs 2026-09 defect at bus level.

    Messages stamped with 2026-01 fixture times, validated by a bus whose
    injected clock reads 2026-09, must be rejected EXPIRED fail-closed —
    and conversely, a bus injected with the matching 2026-01 clock must
    accept them. Result therefore depends only on the injected run clock,
    never on host wall-clock time.
    """
    fixture_time = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    wall_like_time = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    def _publish(clock_time: datetime) -> str:
        bus = _make_bus(clock=_fixed_clock(clock_time))
        bus.register_evidence(_bus_evidence(fixture_time))
        message = AgentMessage(
            schema_version="ma-2-v1",
            message_id=f"msg:{clock_time.date().isoformat()}",
            run_id=TRACE.run_id,
            trace_id=TRACE.trace_id,
            sender="strategy-expert-momentum",
            receiver="opportunity-board",
            message_type=AgentMessageType.PROPOSAL,
            claim="fixture proposal",
            evidence_refs=("ev:bus-clock",),
            confidence=0.8,
            created_at=fixture_time,
            data_time=fixture_time,
            expires_at=fixture_time + timedelta(minutes=5),
            trace=TRACE,
        )
        return bus.publish(message).message_id

    # Injected clock == fixture time → accepted (temporal authority honored).
    assert _publish(fixture_time) == "msg:2026-01-10"

    # Injected clock ≈ host wall-clock (2026-09) → message EXPIRED fail-closed.
    with pytest.raises(ExpiredMessageError, match="message expired"):
        _publish(wall_like_time)


def test_bus_exposes_single_clock_to_all_temporal_validation() -> None:
    """Every temporal validation on the bus reads the same injected clock."""
    bus = _make_bus(clock=_fixed_clock(CLOCK))
    # The public clock accessor and the internal clock must be one authority.
    assert bus.now() == CLOCK
    bus.register_evidence(_bus_evidence(CLOCK))
    message = AgentMessage(
        schema_version="ma-2-v1",
        message_id="msg:single-clock",
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        sender="strategy-expert-momentum",
        receiver="opportunity-board",
        message_type=AgentMessageType.PROPOSAL,
        claim="fixture proposal",
        evidence_refs=("ev:bus-clock",),
        confidence=0.8,
        created_at=CLOCK,
        data_time=CLOCK,
        trace=TRACE,
    )
    accepted = bus.publish(message)
    assert accepted.created_at == CLOCK


def _bus_evidence(available_at: datetime) -> AgentEvidence:
    from trading_bot.multi_agent.contracts import AgentEvidence

    return AgentEvidence(
        schema_version="ma-2-v1",
        evidence_id="ev:bus-clock",
        run_id=TRACE.run_id,
        producer_agent_id="strategy-expert-momentum",
        evidence_type="strategy_signal",
        source_ref="asset-context:bus-clock",
        claim_refs=("claim:bus-clock",),
        observed_at=available_at,
        available_at=available_at,
        content_hash="a" * 64,
        metadata=(),
        trace=TRACE,
    )


# ---------------------------------------------------------------------------
# DEF-MA2-003: swarm derives every timestamp from the bus clock
# ---------------------------------------------------------------------------


def test_swarm_derives_all_timestamps_from_bus_clock() -> None:
    """No evaluate()-level time injection: the bus clock is the only authority.

    The removed ``run_time=`` override was a second temporal authority
    (DEF-MA2-003 split authority); the signature must not grow it back.
    """
    assert "run_time" not in inspect.signature(SpecialistSwarm.evaluate).parameters

    swarm, board, bus = _run_swarm_at(CLOCK)
    swarm_run = swarm.evaluate(
        contexts={"SOL": _ctx("SOL")},
        candles_by_asset={"SOL": _accelerating_candles("SOL")},
        trace=TRACE,
        timeframe="5m",
        strategy_names=("momentum",),
    )
    assert bus.now() == CLOCK
    for message in swarm_run.messages:
        assert message.created_at == CLOCK, "message timestamps must equal the run clock"
    for evaluation in swarm_run.evaluations:
        for proposal in evaluation.proposals:
            assert proposal.created_at == CLOCK
            assert proposal.expires_at == CLOCK + PROPOSAL_VALIDITY
    assert board.now == CLOCK


# ---------------------------------------------------------------------------
# T1: Valid proposal — clock is within validity window
# ---------------------------------------------------------------------------


def test_t1_valid_proposal_accepted() -> None:
    """Clock at creation time → proposal is still valid."""
    swarm, board, _ = _run_swarm_at(CLOCK)
    swarm.evaluate(
        contexts={"SOL": _ctx("SOL")},
        candles_by_asset={"SOL": _accelerating_candles("SOL")},
        trace=TRACE,
        timeframe="5m",
        strategy_names=("momentum",),
    )
    snap = board.snapshot()
    assert len(snap.opportunities) >= 1, "proposal must be accepted when clock == creation time"


# ---------------------------------------------------------------------------
# T2: Expired proposal — clock past expires_at
# ---------------------------------------------------------------------------


def test_t2_expired_proposal_rejected() -> None:
    """Board rejects a proposal when board.now >= proposal.expires_at."""
    proposal, evidence = _make_proposal(
        created_at=CLOCK,
        expires_at=CLOCK + timedelta(minutes=15),
    )
    board = OpportunityBoard(run_id=TRACE.run_id, now=CLOCK)
    board.add_evidence(evidence)
    board.add(proposal, source_agent_id="strategy-expert-momentum", source_agent_version="1.0.0")
    # Advance clock past expiry
    board_expired = OpportunityBoard(run_id=TRACE.run_id, now=CLOCK + timedelta(minutes=16))
    board_expired.add_evidence(evidence)
    with pytest.raises(OpportunityError, match="expired"):
        board_expired.add(
            proposal, source_agent_id="strategy-expert-momentum", source_agent_version="1.0.0"
        )


# ---------------------------------------------------------------------------
# T3: Future data_time — data_time > board.now
# ---------------------------------------------------------------------------


def test_t3_future_data_time_rejected() -> None:
    """Board rejects proposal where data_time > board.now.

    The TradeProposal schema already prevents data_time > created_at,
    so we test the board-level guard by placing board.now BEFORE the
    proposal's data_time (which equals created_at).
    """
    proposal, evidence = _make_proposal(
        created_at=CLOCK,
        data_time=CLOCK,
        expires_at=CLOCK + timedelta(minutes=30),
    )
    # Board clock is 1 hour BEFORE the proposal's data_time
    early_board = OpportunityBoard(run_id=TRACE.run_id, now=CLOCK - timedelta(hours=1))
    early_board.add_evidence(evidence)
    with pytest.raises(OpportunityError, match="future"):
        early_board.add(
            proposal,
            source_agent_id="strategy-expert-momentum",
            source_agent_version="1.0.0",
        )


# ---------------------------------------------------------------------------
# T4: Deterministic replay — same inputs + same clock = same outputs
# ---------------------------------------------------------------------------


def test_t4_deterministic_replay() -> None:
    """Three runs with identical inputs and clock produce identical boards and rankings."""
    results = []
    for _ in range(3):
        swarm, board, _ = _run_swarm_at(CLOCK)
        swarm_run = swarm.evaluate(
            contexts={"SOL": _ctx("SOL")},
            candles_by_asset={"SOL": _accelerating_candles("SOL")},
            trace=TRACE,
            timeframe="5m",
            strategy_names=("momentum",),
        )
        ranked = board.rank(assessments={a.asset: a for a in swarm_run.assessments})
        results.append((swarm_run, board.snapshot(), ranked))

    for i in range(1, len(results)):
        s0, b0, r0 = results[0]
        s1, b1, r1 = results[i]
        assert s0.assessments == s1.assessments, f"assessments differ on run {i}"
        assert s0.evaluations == s1.evaluations, f"evaluations differ on run {i}"
        # Structural equality of accepted AgentMessages (T4 requirement).
        m0 = [(m.message_id, m.created_at, m.expires_at, m.data_time) for m in s0.messages]
        m1 = [(m.message_id, m.created_at, m.expires_at, m.data_time) for m in s1.messages]
        assert m0 == m1, f"accepted messages differ on run {i}"
        assert b0 == b1, f"board snapshot differs on run {i}"
        assert b0.conflicts == b1.conflicts, f"conflicts differ on run {i}"
        assert r0 == r1, f"ranking differs on run {i}"


# ---------------------------------------------------------------------------
# T5: Wall-clock independence — result depends on injected clock, not host time
# ---------------------------------------------------------------------------


def test_t5_wall_clock_independence() -> None:
    """Proposals from 2025 fixtures are valid under an injected 2025 clock,
    even though the host machine clock is 2026+."""
    old_clock = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)
    old_ts = int(old_clock.timestamp() * 1000)

    ctx = _ctx(
        asset="SOL",
        timestamp=old_ts,
        returns=0.06,
        trend_spread=0.015,
    )

    start = old_ts - 79 * 300_000
    candles: list[OHLCV] = []
    price = 100.0
    for i in range(80):
        ts = start + i * 300_000
        price *= 1.002
        candles.append(
            OHLCV("SOL/USDT", ts, price * 0.998, price * 1.002, price * 0.996, price, 100.0)
        )

    swarm, board, _ = _run_swarm_at(old_clock)
    swarm.evaluate(
        contexts={"SOL": ctx},
        candles_by_asset={"SOL": candles},
        trace=TRACE,
        timeframe="5m",
        strategy_names=("momentum",),
    )
    snap = board.snapshot()
    assert len(snap.opportunities) >= 1, (
        "old-clock proposal must be accepted when board.now matches proposal timestamps"
    )
    assert board.now == old_clock, "board clock must be the injected clock, not host time"


# ---------------------------------------------------------------------------
# T6: Canonical evaluate API — strategy_names= everywhere
# ---------------------------------------------------------------------------


def test_t6_canonical_evaluate_api_uses_strategy_names() -> None:
    """The swarm.evaluate() signature must use strategy_names=, not strategies=."""
    sig = inspect.signature(SpecialistSwarm.evaluate)
    param_names = list(sig.parameters.keys())
    assert "strategy_names" in param_names, (
        f"canonical parameter must be 'strategy_names', got: {param_names}"
    )
    assert "strategies" not in param_names, (
        f"'strategies' must not be a parameter (use 'strategy_names'): {param_names}"
    )
    # No divergent spelling anywhere in the MA-2 test surface either.
    # (Patterns are concatenated so this sweep does not self-flag.)
    test_dir = pathlib.Path("tests/unit/multi_agent")
    divergent_call = "strategies" + "="
    divergent_param = "strategies" + " :"
    divergent: list[str] = []
    for path in sorted(test_dir.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if "strategy_names" in stripped:
                continue
            if (
                divergent_call in stripped or divergent_param in stripped
            ) and not stripped.startswith(("#", '"', "'")):
                divergent.append(f"{path}:{lineno}: {stripped}")
    assert divergent == [], f"divergent evaluate API spelling found: {divergent}"


# ---------------------------------------------------------------------------
# Wall-clock audit: no datetime.now() in MA-2 decision paths
# ---------------------------------------------------------------------------


def _assert_no_datetime_now(filepath: str, module_name: str) -> None:
    """AST audit: fail if datetime.now()/utcnow()/date.today/time.time appear."""
    tree = ast.parse(pathlib.Path(filepath).read_text())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "now"
            and isinstance(func.value, ast.Name)
            and func.value.id == "datetime"
        ):
            offenders.append(f"datetime.now() at line {node.lineno}")
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "utcnow"
            and isinstance(func.value, ast.Name)
            and func.value.id == "datetime"
        ):
            offenders.append(f"datetime.utcnow() at line {node.lineno}")
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "today"
            and isinstance(func.value, ast.Name)
            and func.value.id == "date"
        ):
            offenders.append(f"date.today() at line {node.lineno}")
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "time"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        ):
            offenders.append(f"time.time() at line {node.lineno}")
    assert offenders == [], (
        f"wall-clock decision dependency found in {module_name}: {offenders} — "
        "all decision time must come from the injected clock"
    )


def test_no_datetime_now_in_swarm_evaluate() -> None:
    """SpecialistSwarm.evaluate must not call datetime.now() for decision logic."""
    _assert_no_datetime_now("src/trading_bot/multi_agent/swarm.py", "swarm.py")


def test_no_datetime_now_in_opportunity() -> None:
    """OpportunityBoard must not call datetime.now() for decision logic."""
    _assert_no_datetime_now("src/trading_bot/multi_agent/opportunity.py", "opportunity.py")


def test_no_datetime_now_in_bus() -> None:
    """AgentBus must not call datetime.now() for decision logic (DEF-MA2-001)."""
    _assert_no_datetime_now("src/trading_bot/multi_agent/bus.py", "bus.py")


def test_no_datetime_now_in_specialists() -> None:
    """MA-2 specialists must not call wall-clock functions for decision logic."""
    _assert_no_datetime_now("src/trading_bot/multi_agent/specialists.py", "specialists.py")


# ---------------------------------------------------------------------------
# Helper: build a synthetic proposal + evidence for board-level tests
# ---------------------------------------------------------------------------


def _make_proposal(
    *,
    created_at: datetime = CLOCK,
    data_time: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[TradeProposal, object]:
    """Create a minimal valid proposal and its evidence for board tests."""
    from trading_bot.multi_agent.contracts import AgentEvidence

    if data_time is None:
        data_time = created_at
    if expires_at is None:
        expires_at = created_at + PROPOSAL_VALIDITY

    proposal_id = "proposal:temporal-test-001"
    evidence_id = f"evidence:{proposal_id}"

    evidence = AgentEvidence(
        schema_version="ma-2-v1",
        evidence_id=evidence_id,
        run_id=TRACE.run_id,
        producer_agent_id="strategy-expert-momentum",
        evidence_type="strategy_signal",
        source_ref="asset-context:test",
        claim_refs=(proposal_id,),
        observed_at=created_at,
        available_at=created_at,
        content_hash="a" * 64,
        metadata=(),
        trace=TRACE,
    )

    proposal = TradeProposal(
        schema_version="ma-2-v1",
        proposal_id=proposal_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset="SOL",
        direction=TradeDirection.LONG,
        strategy="momentum",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(evidence_id,),
        counter_evidence_refs=(),
        invalidation="structural stop",
        confidence=0.7,
        data_time=data_time,
        created_at=created_at,
        expires_at=expires_at,
        trace=TRACE,
    )
    return proposal, evidence
