"""MA-2 fixture E2E tests covering all 7 required swarm scenarios.

Every test is deterministic: identical inputs produce identical outputs.
No RiskManager, PaperBroker, or live execution is involved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent import (
    AgentRegistry,
    Blackboard,
    CapabilityRegistry,
    OpportunityBoard,
    RankedOpportunity,
    TraceContext,
    register_swarm_agents,
)
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.contracts import AgentEvidence, TradeDirection, TradeProposal
from trading_bot.multi_agent.specialists import MomentumExpert
from trading_bot.multi_agent.swarm import SpecialistSwarm, SwarmRun
from trading_bot.research.asset_intelligence.models import AssetContext

TRACE = TraceContext(
    run_id="ma2-e2e-run",
    trace_id="ma2-e2e-trace",
    correlation_id="ma2-e2e-corr",
    causation_id="ma2-e2e-cause",
)

# Fixed reference time — CONTEXT_TS must be the ms equivalent of NOW.
# 2026-01-01 12:00:00 UTC = 1767268800 seconds = 1767268800000 ms
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CONTEXT_TS = 1_767_268_800_000  # 2026-01-01 12:00:00 UTC


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class E2EResult:
    swarm_run: SwarmRun
    board: OpportunityBoard
    ranked: tuple[RankedOpportunity, ...]
    snapshot: object  # OpportunitySnapshot


def _ctx(
    asset: str,
    timestamp: int = CONTEXT_TS,
    regime: str = "TREND_UP",
    returns: float = 0.04,
    trend_spread: float = 0.01,
    liquidity: str = "deep",
    bars: int = 120,
    volatility: float = 0.01,
) -> AssetContext:
    return AssetContext(
        asset=asset,
        timestamp=timestamp,
        market_regime=regime,
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
        dataset_id="e2e-fixture",
        agent_version="base-crypto-v1",
        regime_method_version="asset-agent-regime-v1",
        window_start_ts=timestamp - (bars - 1) * 300_000,
        window_end_ts=timestamp,
        bar_count=bars,
    )


def _candles_accelerating(asset: str, count: int = 80) -> list[OHLCV]:
    """Accelerating uptrend that triggers MomentumFamily LONG via MACD histogram.

    Uses compound (exponential) returns so the MACD histogram is non-zero.
    Linear series produce histogram=0 by construction and will not trigger.
    """
    start = CONTEXT_TS - (count - 1) * 300_000
    out: list[OHLCV] = []
    price = 100.0
    for i in range(count):
        ts = start + i * 300_000
        price *= 1.002  # 0.2% compound per bar
        out.append(OHLCV(f"{asset}/USDT", ts, price * 0.998, price * 1.002, price * 0.996, price, 100.0))
    return out


def _candles_descending(asset: str, count: int = 80) -> list[OHLCV]:
    """Compound descending candles — weak assessment, no momentum SHORT."""
    start = CONTEXT_TS - (count - 1) * 300_000
    out: list[OHLCV] = []
    price = 100.0
    for i in range(count):
        ts = start + i * 300_000
        price *= 0.998  # 0.2% compound decline per bar
        out.append(OHLCV(f"{asset}/USDT", ts, price * 1.002, price * 0.998, price * 0.996, price, 100.0))
    return out


def _candles_flat(asset: str, count: int = 80) -> list[OHLCV]:
    """Flat candles — no directional signal."""
    start = CONTEXT_TS - (count - 1) * 300_000
    out: list[OHLCV] = []
    for i in range(count):
        ts = start + i * 300_000
        out.append(OHLCV(f"{asset}/USDT", ts, 99.8, 100.2, 99.6, 100.0, 100.0))
    return out


def _make_bus(clock: object | None = None) -> tuple[AgentBus, AgentRegistry, CapabilityRegistry]:
    agent_reg = AgentRegistry()
    cap_reg = CapabilityRegistry()
    register_swarm_agents(agent_reg, cap_reg)
    bb = Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id)
    # DEF-MA2-001: construct directly — no kwargs composition for temporal authority
    if clock is not None:
        bus = AgentBus(
            agent_registry=agent_reg,
            capability_registry=cap_reg,
            blackboard=bb,
            clock=clock,  # type: ignore[arg-type]
        )
    else:
        bus = AgentBus(
            agent_registry=agent_reg,
            capability_registry=cap_reg,
            blackboard=bb,
        )
    return bus, agent_reg, cap_reg


def _fixed_clock(ts: datetime) -> object:
    return lambda: ts


def _run_swarm(
    contexts: Mapping[str, AssetContext],
    candles_by_asset: Mapping[str, Sequence[OHLCV]],
    *,
    strategies: tuple[str, ...] = ("momentum",),
    now: datetime = NOW,
) -> E2EResult:
    bus, _, _ = _make_bus(clock=_fixed_clock(now))
    board = OpportunityBoard(run_id=TRACE.run_id, now=now)
    swarm = SpecialistSwarm(bus=bus, board=board)
    swarm_run = swarm.evaluate(
        contexts,
        candles_by_asset,
        trace=TRACE,
        timeframe="5m",
        run_time=now,
        strategy_names=strategies,
    )
    ranked = board.rank(
        assessments={a.asset: a for a in swarm_run.assessments},
    )
    return E2EResult(swarm_run=swarm_run, board=board, ranked=ranked, snapshot=board.snapshot())


def _make_evidence(
    evidence_id: str,
    producer: str,
    *,
    claim_ref: str = "",
) -> AgentEvidence:
    hash_value = "a" * 64 if not claim_ref else "b" * 64
    return AgentEvidence(
        schema_version="ma-2-v1",
        evidence_id=evidence_id,
        run_id=TRACE.run_id,
        producer_agent_id=producer,
        evidence_type="strategy_signal",
        source_ref="fixture",
        claim_refs=(claim_ref,) if claim_ref else (),
        observed_at=NOW,
        available_at=NOW,
        content_hash=hash_value,
        metadata=(),
        trace=TRACE,
    )


def _make_proposal(
    proposal_id: str,
    asset: str,
    direction: TradeDirection,
    strategy: str,
    evidence_id: str,
    *,
    confidence: float = 0.8,
) -> tuple[TradeProposal, AgentEvidence]:
    ev = _make_evidence(evidence_id, producer=f"strategy-expert-{strategy}", claim_ref=proposal_id)
    proposal = TradeProposal(
        schema_version="ma-2-v1",
        proposal_id=proposal_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset=asset,
        direction=direction,
        strategy=strategy,
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(evidence_id,),
        invalidation="stop",
        confidence=confidence,
        data_time=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        trace=TRACE,
    )
    return proposal, ev


# ---------------------------------------------------------------------------
# CASE 1: SOL strong momentum, BTC neutral, ETH weak
# Expected: MomentumExpert proposes SOL
# ---------------------------------------------------------------------------

def test_case1_sol_strong_momentum_proposal() -> None:
    result = _run_swarm(
        contexts={
            "BTC": _ctx("BTC", returns=0.0, trend_spread=0.002),
            "ETH": _ctx("ETH", returns=-0.02, trend_spread=0.001),
            "SOL": _ctx("SOL", returns=0.06, trend_spread=0.015),
        },
        candles_by_asset={
            "BTC": _candles_flat("BTC"),
            "ETH": _candles_descending("ETH"),
            "SOL": _candles_accelerating("SOL"),
        },
        strategies=("momentum",),
    )
    sol_proposals = [
        opp for opp in result.swarm_run.evaluations
        if opp.asset == "SOL" and opp.proposals
    ]
    assert sol_proposals, "SOL should have momentum proposals"
    btc_proposals = [
        opp for opp in result.swarm_run.evaluations
        if opp.asset == "BTC" and opp.proposals
    ]
    assert not btc_proposals, "BTC should have no proposals (neutral)"
    assert len(result.ranked) >= 1
    assert result.ranked[0].proposal_id.startswith("proposal:")


# ---------------------------------------------------------------------------
# CASE 2: SOL Momentum LONG + SOL Breakout LONG — two opportunities, no conflict
# ---------------------------------------------------------------------------

def test_case2_two_same_direction_no_conflict() -> None:
    """When both Momentum and Breakout emit LONG for SOL, no conflict exists."""
    board = OpportunityBoard(run_id=TRACE.run_id, now=NOW)
    p1, ev1 = _make_proposal("proposal:mom-sol-long", "SOL", TradeDirection.LONG, "momentum", "ev:1")
    p2, ev2 = _make_proposal("proposal:bo-sol-long", "SOL", TradeDirection.LONG, "breakout", "ev:2")
    board.add_evidence(ev1)
    board.add_evidence(ev2)
    board.add(p1, source_agent_id="strategy-expert-momentum", source_agent_version="1.0.0")
    board.add(p2, source_agent_id="strategy-expert-breakout", source_agent_version="1.0.0")
    snap = board.snapshot()
    assert len(snap.opportunities) == 2, "two distinct LONG proposals should produce two opportunities"
    assert len(snap.conflicts) == 0
    ranked = board.rank()
    assert len(ranked) == 2


# ---------------------------------------------------------------------------
# CASE 3: SOL Momentum LONG + SOL MeanReversion SHORT → ConflictCase
# ---------------------------------------------------------------------------

def test_case3_opposite_direction_conflict() -> None:
    """Board detects directional conflict for same asset with opposite directions."""
    board = OpportunityBoard(run_id=TRACE.run_id, now=NOW)
    p1, ev1 = _make_proposal("proposal:mom-sol-long", "SOL", TradeDirection.LONG, "momentum", "ev:1")
    p2, ev2 = _make_proposal("proposal:mr-sol-short", "SOL", TradeDirection.SHORT, "mean_reversion", "ev:2")
    board.add_evidence(ev1)
    board.add_evidence(ev2)
    board.add(p1, source_agent_id="strategy-expert-momentum", source_agent_version="1.0.0")
    board.add(p2, source_agent_id="strategy-expert-mean_reversion", source_agent_version="1.0.0")

    snap = board.snapshot()
    assert len(snap.conflicts) == 1
    conflict = snap.conflicts[0]
    assert conflict.asset == "SOL"
    assert "LONG" in conflict.directions
    assert "SHORT" in conflict.directions
    assert conflict.status == "CONFLICTED"

    ranked = board.rank()
    for item in ranked:
        if item.proposal_id in conflict.proposal_ids:
            assert item.conflict_status == "CONFLICTED"


# ---------------------------------------------------------------------------
# CASE 4: Duplicate proposal → one opportunity
# ---------------------------------------------------------------------------

def test_case4_duplicate_proposal_deduplication() -> None:
    expert = MomentumExpert()
    sol_ctx = _ctx("SOL")
    sol_candles = _candles_accelerating("SOL")
    result = expert.evaluate(sol_ctx, sol_candles, trace=TRACE, now_ts=CONTEXT_TS)
    assert result.proposals, "strong signal should produce proposals"
    proposal = result.proposals[0]
    evidence = result.evidence[0]

    board = OpportunityBoard(run_id=TRACE.run_id, now=proposal.created_at)
    board.add_evidence(evidence)
    opp1 = board.add(proposal, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0")
    dup = proposal.model_copy(update={"proposal_id": proposal.proposal_id + "-dup"})
    opp2 = board.add(dup, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0")
    assert opp1 is opp2 or opp1.proposal.proposal_id == opp2.proposal.proposal_id
    snap = board.snapshot()
    assert len(snap.opportunities) == 1


# ---------------------------------------------------------------------------
# CASE 5: Stale proposal → not rankable
# ---------------------------------------------------------------------------

def test_case5_stale_proposal_not_rankable() -> None:
    """A proposal that was admitted, then expired, is excluded from ranking."""
    expert = MomentumExpert()
    sol_ctx = _ctx("SOL")
    sol_candles = _candles_accelerating("SOL")
    result = expert.evaluate(sol_ctx, sol_candles, trace=TRACE, now_ts=CONTEXT_TS)
    if not result.proposals:
        pytest.skip("momentum fixture emitted no signal for stale test")
    proposal = result.proposals[0]
    evidence = result.evidence[0]
    # Board time is WITHIN validity → admission succeeds
    board = OpportunityBoard(run_id=TRACE.run_id, now=proposal.created_at)
    board.add_evidence(evidence)
    board.add(proposal, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0")
    # Now expire_stale with a time past expiry
    assert proposal.expires_at is not None
    expired = board.expire_stale(now=proposal.expires_at + timedelta(hours=1))
    assert proposal.proposal_id in expired
    ranked = board.rank()
    assert len(ranked) == 0


# ---------------------------------------------------------------------------
# CASE 6: All experts emit NO_PROPOSAL → empty board
# ---------------------------------------------------------------------------

def test_case6_all_experts_no_proposal() -> None:
    bus, _, _ = _make_bus(clock=_fixed_clock(NOW))
    board = OpportunityBoard(run_id=TRACE.run_id, now=NOW)
    swarm = SpecialistSwarm(bus=bus, board=board)

    result = swarm.evaluate(
        contexts={
            "BTC": _ctx("BTC", returns=0.0, trend_spread=0.001),
            "ETH": _ctx("ETH", returns=0.0, trend_spread=0.001),
            "SOL": _ctx("SOL", returns=0.0, trend_spread=0.001),
        },
        candles_by_asset={
            "BTC": _candles_flat("BTC"),
            "ETH": _candles_flat("ETH"),
            "SOL": _candles_flat("SOL"),
        },
        trace=TRACE,
        run_time=NOW,
        strategy_names=("momentum",),
    )
    all_no_proposal = all(ev.no_proposal for ev in result.evaluations)
    assert all_no_proposal, "all evaluations should be NO_PROPOSAL for flat markets"
    snap = board.snapshot()
    assert len(snap.opportunities) == 0
    ranked = board.rank()
    assert len(ranked) == 0


# ---------------------------------------------------------------------------
# CASE 7: One strategy across assets — deterministic ordering
# ---------------------------------------------------------------------------

def test_case7_one_strategy_deterministic_ordering() -> None:
    ctx_map = {
        "BTC": _ctx("BTC", returns=-0.01, trend_spread=0.001),
        "ETH": _ctx("ETH", returns=0.02, trend_spread=0.005),
        "SOL": _ctx("SOL", returns=0.06, trend_spread=0.015),
    }
    candles_map = {
        "BTC": _candles_descending("BTC"),
        "ETH": _candles_accelerating("ETH"),
        "SOL": _candles_accelerating("SOL"),
    }
    run1 = _run_swarm(ctx_map, candles_map, strategies=("momentum",))
    run2 = _run_swarm(ctx_map, candles_map, strategies=("momentum",))
    assert run1.ranked == run2.ranked, "repeated swarm must produce identical ranking"
    ids = [r.proposal_id for r in run1.ranked]
    assert len(ids) > 0, "at least one proposal expected for this fixture"
    # Verify deterministic repeat, not lexicographic order
    run3 = _run_swarm(ctx_map, candles_map, strategies=("momentum",))
    assert [r.proposal_id for r in run3.ranked] == ids, "third run must match first exactly"


# ---------------------------------------------------------------------------
# Determinism: identical inputs → identical outputs
# ---------------------------------------------------------------------------

def test_deterministic_replay() -> None:
    """Given identical inputs, SwarmRun + board + ranking must be identical."""
    ctx_map = {
        "BTC": _ctx("BTC", returns=0.0, trend_spread=0.001),
        "ETH": _ctx("ETH", returns=0.0, trend_spread=0.001),
        "SOL": _ctx("SOL", returns=0.06, trend_spread=0.015),
    }
    candles_map = {
        "BTC": _candles_flat("BTC"),
        "ETH": _candles_flat("ETH"),
        "SOL": _candles_accelerating("SOL"),
    }
    run1 = _run_swarm(ctx_map, candles_map, strategies=("momentum",))
    run2 = _run_swarm(ctx_map, candles_map, strategies=("momentum",))
    assert len(run1.ranked) == len(run2.ranked)
    for r1, r2 in zip(run1.ranked, run2.ranked, strict=True):
        assert r1.proposal_id == r2.proposal_id
        assert r1.score == r2.score
        assert r1.score_components == r2.score_components
        assert r1.conflict_status == r2.conflict_status


# ---------------------------------------------------------------------------
# Execution boundary: no execution imports
# ---------------------------------------------------------------------------

def test_no_execution_imports_in_specialist_modules() -> None:
    """MA-2 specialist/opportunity/swarm modules must not import execution gateways."""
    import ast
    from pathlib import Path

    forbidden = ("trading_bot.paper", "trading_bot.risk", "trading_bot.execution", "trading_bot.config")
    target_files = [
        Path("src/trading_bot/multi_agent/specialists.py"),
        Path("src/trading_bot/multi_agent/opportunity.py"),
        Path("src/trading_bot/multi_agent/swarm.py"),
    ]
    violations = []
    for path in target_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                mod = node.module
            if mod and any(mod.startswith(p) for p in forbidden):
                violations.append(f"{path}:{mod}")
    assert violations == [], f"MA-2 modules import execution gateways: {violations}"


# ---------------------------------------------------------------------------
# Traceability: every proposal traces to evidence
# ---------------------------------------------------------------------------

def test_traceability_chain() -> None:
    """Every ranked opportunity must trace evidence back through proposal."""
    result = _run_swarm(
        contexts={"SOL": _ctx("SOL", returns=0.06, trend_spread=0.015)},
        candles_by_asset={"SOL": _candles_accelerating("SOL")},
        strategies=("momentum",),
    )
    snap = result.board.snapshot()
    for opp in snap.opportunities:
        proposal = opp.proposal
        assert proposal.evidence_refs, f"proposal {proposal.proposal_id} has no evidence"
        assert proposal.trace_id == TRACE.trace_id
        for ref in proposal.evidence_refs:
            evidence = result.board._evidence.get(ref)
            assert evidence is not None, f"evidence {ref} not found"
            assert evidence.producer_agent_id == opp.source_agent_id


# ---------------------------------------------------------------------------
# Bus message flow
# ---------------------------------------------------------------------------

def test_ma2_swarm_bus_publishes_messages() -> None:
    """Swarm must publish assessment and proposal messages through the bus."""
    bus, _, _ = _make_bus(clock=_fixed_clock(NOW))
    board = OpportunityBoard(run_id=TRACE.run_id, now=NOW)
    swarm = SpecialistSwarm(bus=bus, board=board)

    result = swarm.evaluate(
        contexts={"SOL": _ctx("SOL", returns=0.06, trend_spread=0.015)},
        candles_by_asset={"SOL": _candles_accelerating("SOL")},
        trace=TRACE,
        run_time=NOW,
        strategy_names=("momentum",),
    )
    assert len(result.messages) > 0
    msg_types = {m.message_type.value for m in result.messages}
    assert "OBSERVATION" in msg_types, "should publish asset assessment"
    assert "STATUS" in msg_types, "should publish strategy status"
