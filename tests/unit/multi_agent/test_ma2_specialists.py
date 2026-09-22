"""MA-2 specialist and opportunity-board tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent import (
    AgentCapability,
    AgentRegistry,
    AssetExpert,
    BTCAssetExpert,
    CapabilityRegistry,
    MetaRanker,
    OpportunityBoard,
    OpportunityError,
    SOLAssetExpert,
    TraceContext,
    register_swarm_agents,
)
from trading_bot.multi_agent.specialists import MomentumExpert, StrategyEvaluation
from trading_bot.research.asset_intelligence.models import AssetContext
from trading_bot.research.families import MomentumFamily

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TRACE = TraceContext(
    run_id="ma2-test-run",
    trace_id="ma2-test-trace",
    correlation_id="ma2-correlation",
    causation_id="ma2-causation",
)


def context(asset: str = "BTC", timestamp: int = 1_767_268_800_000) -> AssetContext:
    return AssetContext(
        asset=asset,
        timestamp=timestamp,
        market_regime="TREND_UP",
        trend_state="up",
        volatility_state="normal",
        liquidity_state="deep",
        momentum_features={
            "returns": 0.04,
            "trend": {"direction": "up", "spread": 0.01},
            "rsi": 65.0,
        },
        volatility_features={"atr_norm": 0.01},
        volume_features={"surge": 1.2},
        data_quality={"bars_in_window": 120, "newest_bar_ts": timestamp},
        data_fingerprint="a" * 64,
        dataset_id="fixture",
        agent_version="base-crypto-v1",
        regime_method_version="asset-agent-regime-v1",
        window_start_ts=timestamp - 119 * 300_000,
        window_end_ts=timestamp,
        bar_count=120,
    )


def candles(asset: str = "BTC", count: int = 80) -> list[OHLCV]:
    """Generate deterministic candles with a strong uptrend."""
    start = 1_767_268_800_000 - (count - 1) * 300_000
    result: list[OHLCV] = []
    price = 100.0
    for index in range(count):
        ts = start + index * 300_000
        price += 0.3
        result.append(
            OHLCV(f"{asset}/USDT", ts, price - 0.2, price + 0.4, price - 0.4, price, 100.0)
        )
    return result


def _signal_candles(asset: str = "SOL", count: int = 80) -> list[OHLCV]:
    """Generate accelerating candles that trigger MomentumFamily LONG signal.

    Early bars are flat, later bars have strong uptrend. This produces
    a positive MACD histogram and positive momentum, satisfying the
    MomentumFamily signal criteria.
    """
    start = 1_767_268_800_000 - (count - 1) * 300_000
    result: list[OHLCV] = []
    price = 100.0
    for index in range(count):
        ts = start + index * 300_000
        if index < 40:
            price += 0.05
        else:
            price += 0.5
        result.append(
            OHLCV(f"{asset}/USDT", ts, price - 0.2, price + 0.4, price - 0.4, price, 100.0)
        )
    return result


def test_asset_experts_share_contract_and_produce_traceable_assessments() -> None:
    experts = (BTCAssetExpert(), SOLAssetExpert(), AssetExpert("ETH"))
    assessments = [expert.evaluate(context(expert.asset), trace=TRACE) for expert in experts]
    assert [item.asset for item in assessments] == ["BTC", "SOL", "ETH"]
    assert all(item.evidence_refs for item in assessments)
    assert all(item.trace.trace_id == TRACE.trace_id for item in assessments)
    assert all(
        item.manifest.capabilities == frozenset({AgentCapability.READ, AgentCapability.WRITE})
        for item in experts
    )


def test_strategy_expert_wraps_canonical_family_and_no_proposal_is_valid() -> None:
    expert = MomentumExpert()
    result = expert.evaluate(context(), candles(), trace=TRACE)
    assert isinstance(expert.family, MomentumFamily)
    assert isinstance(result, StrategyEvaluation)
    assert result.strategy == "momentum"
    assert isinstance(result.proposals, tuple)
    assert isinstance(result.evidence, tuple)


def test_strategy_expert_produces_proposals_with_strong_signal() -> None:
    """Verify strategy expert emits TradeProposal when signal criteria are met."""
    expert = MomentumExpert()
    ctx = context("SOL")
    result = expert.evaluate(ctx, _signal_candles("SOL"), trace=TRACE)
    assert result.proposals, "strong signal fixture must produce at least one proposal"
    proposal = result.proposals[0]
    assert proposal.asset == "SOL"
    assert proposal.direction.value == "LONG"
    assert proposal.strategy == "momentum"
    assert proposal.evidence_refs
    assert proposal.confidence > 0
    assert proposal.expires_at is not None
    assert proposal.expires_at > proposal.created_at


def test_all_registered_ma2_agents_have_no_execution_capability() -> None:
    registry = AgentRegistry()
    capabilities = CapabilityRegistry()
    manifests = register_swarm_agents(registry, capabilities)
    assert len(manifests) == 9
    for manifest in manifests:
        permissions = capabilities.permissions_for(manifest.agent_id, manifest.agent_version)
        assert AgentCapability.EXECUTE not in permissions
        assert AgentCapability.PRODUCTION_ACTION not in permissions
        assert AgentCapability.RISK_OVERRIDE not in permissions
        assert AgentCapability.DIRECT_BROKER_ACCESS not in permissions


def test_board_deduplicates_semantically_identical_proposals() -> None:
    expert = MomentumExpert()
    result = expert.evaluate(context("SOL"), _signal_candles("SOL"), trace=TRACE)
    assert result.proposals, "strong signal fixture must produce proposals"
    proposal = result.proposals[0]
    evidence = result.evidence[0]
    board = OpportunityBoard(run_id=TRACE.run_id, now=proposal.created_at)
    board.add_evidence(evidence)
    duplicate = proposal.model_copy(update={"proposal_id": "different-id"})
    first = board.add(
        proposal, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0"
    )
    second = board.add(
        duplicate, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0"
    )
    assert first == second
    assert board.snapshot().proposal_ids() == (proposal.proposal_id,)


def test_board_rejects_missing_evidence_and_expires_proposals() -> None:
    expert = MomentumExpert()
    result = expert.evaluate(context("SOL"), _signal_candles("SOL"), trace=TRACE)
    assert result.proposals, "strong signal fixture must produce proposals"
    proposal = result.proposals[0]
    board = OpportunityBoard(run_id=TRACE.run_id, now=proposal.created_at)
    with pytest.raises(OpportunityError, match="evidence"):
        board.add(proposal, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0")
    board.add_evidence(result.evidence[0])
    board.add(proposal, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0")
    assert proposal.expires_at is not None
    assert board.expire_stale(now=proposal.expires_at + timedelta(microseconds=1)) == (
        proposal.proposal_id,
    )
    assert board.rank() == ()


def test_meta_ranker_is_inspectable_and_conflict_status_is_explicit() -> None:
    expert = MomentumExpert()
    result = expert.evaluate(context("SOL"), _signal_candles("SOL"), trace=TRACE)
    assert result.proposals, "strong signal fixture must produce proposals"
    proposal = result.proposals[0]
    board = OpportunityBoard(run_id=TRACE.run_id, now=proposal.created_at)
    board.add_evidence(result.evidence[0])
    board.add(proposal, source_agent_id=expert.manifest.agent_id, source_agent_version="1.0.0")
    ranked = board.rank()
    assert len(ranked) == 1
    assert isinstance(MetaRanker(), MetaRanker)
    assert dict(ranked[0].score_components).keys() == {
        "proposal_confidence",
        "evidence_quality",
        "asset_assessment",
        "freshness",
        "regime_fit",
        "strategy_applicability",
    }
    assert ranked[0].conflict_status == "CLEAR"
