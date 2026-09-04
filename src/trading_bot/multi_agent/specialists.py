"""Deterministic MA-2 specialist experts.

This module is intentionally limited to the intelligence plane. Experts
produce assessments and proposals, but have no execution, risk, broker, or
live-trading authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol

from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentEvidence,
    AgentLifecycleState,
    AgentManifest,
    AgentRole,
    ForbiddenAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
)
from trading_bot.research.alpha import AlphaFamily
from trading_bot.research.asset_intelligence.models import AssetContext
from trading_bot.research.families import (
    BreakoutFamily,
    MeanReversionFamily,
    MomentumFamily,
    TrendFamily,
    VolatilityFamily,
)
from trading_bot.research.types import AlphaSignal, FeaturesBag

SPECIALIST_SCHEMA_VERSION = "ma-2-v1"
SPECIALIST_VERSION = "1.0.0"
PROPOSAL_VALIDITY = timedelta(minutes=15)
SUPPORTED_ASSETS = ("BTC", "ETH", "SOL")


class SpecialistAgent(Protocol):
    """Small common interface shared by all MA-2 experts."""

    @property
    def manifest(self) -> AgentManifest: ...


@dataclass(frozen=True, slots=True)
class AssetAssessment:
    """Deterministic quality assessment derived only from AssetContext."""

    asset: str
    timestamp: int
    regime: str
    trend_quality: float
    volatility_quality: float
    liquidity_quality: float
    relative_strength: float
    market_quality: float
    confidence: float
    evidence: tuple[AgentEvidence, ...]
    trace: TraceContext
    agent_id: str
    agent_version: str

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timestamp": self.timestamp,
            "regime": self.regime,
            "trend_quality": self.trend_quality,
            "volatility_quality": self.volatility_quality,
            "liquidity_quality": self.liquidity_quality,
            "relative_strength": self.relative_strength,
            "market_quality": self.market_quality,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "trace": self.trace.model_dump(),
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
        }


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    """Strategy output; an empty proposal tuple is an explicit NO_PROPOSAL."""

    strategy: str
    asset: str
    context_timestamp: int
    proposals: tuple[TradeProposal, ...]
    evidence: tuple[AgentEvidence, ...]
    agent_id: str
    agent_version: str

    @property
    def no_proposal(self) -> bool:
        return not self.proposals

    @property
    def result_type(self) -> str:
        return "NO_PROPOSAL" if self.no_proposal else "PROPOSALS"


class _BaseSpecialist:
    """Shared manifest construction with execution capabilities denied."""

    def __init__(self, *, agent_id: str, role: AgentRole, description: str) -> None:
        self._manifest = AgentManifest(
            schema_version=SPECIALIST_SCHEMA_VERSION,
            agent_id=agent_id,
            agent_version=SPECIALIST_VERSION,
            role=role,
            description=description,
            capabilities=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            input_contracts=("AssetContext",),
            output_contracts=("AssetAssessment", "TradeProposal"),
            allowed_tools=(),
            forbidden_actions=frozenset(ForbiddenAction),
            lifecycle_state=AgentLifecycleState.ENABLED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest


def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(high, value)), 6)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()


def _trace_payload(trace: TraceContext, artifact_id: str) -> TraceContext:
    return trace.model_copy(
        update={
            "correlation_id": artifact_id,
            "causation_id": trace.causation_id or artifact_id,
        }
    )


def _evidence(
    *,
    evidence_id: str,
    run_id: str,
    producer: str,
    evidence_type: str,
    source_ref: str,
    claim_ref: str,
    observed_at: datetime,
    available_at: datetime,
    trace: TraceContext,
    payload: object,
) -> AgentEvidence:
    return AgentEvidence(
        schema_version=SPECIALIST_SCHEMA_VERSION,
        evidence_id=evidence_id,
        run_id=run_id,
        producer_agent_id=producer,
        evidence_type=evidence_type,
        source_ref=source_ref,
        claim_refs=(claim_ref,),
        observed_at=observed_at,
        available_at=available_at,
        content_hash=_canonical_hash(payload),
        metadata=(("artifact", claim_ref),),
        trace=trace,
    )


def _timestamp(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


class AssetExpert(_BaseSpecialist):
    """Shared asset expert implementation for BTC, ETH, and SOL."""

    def __init__(self, asset: str) -> None:
        normalized = asset.upper()
        if normalized not in SUPPORTED_ASSETS:
            raise ValueError(f"unsupported MA-2 asset: {asset}")
        self.asset = normalized
        super().__init__(
            agent_id=f"asset-expert-{normalized.lower()}",
            role=AgentRole.ASSET_EXPERT,
            description=f"Deterministic {normalized} AssetContext quality expert.",
        )

    def evaluate(
        self,
        context: AssetContext,
        *,
        trace: TraceContext,
        now_ts: int | None = None,
    ) -> AssetAssessment:
        context.validate(now_ts=now_ts)
        if context.asset != self.asset:
            raise ValueError(
                f"{self.asset} asset expert cannot evaluate {context.asset} context"
            )
        trend = context.trend_value or {}
        spread = abs(float(trend.get("spread", 0.0) or 0.0))
        trend_quality = _bounded(spread / 0.02)
        volatility = context.volatility_value or 0.0
        # Normalized volatility is descriptive quality, not a trade rule.
        volatility_quality = _bounded(1.0 - abs(volatility - 0.01) / 0.02)
        liquidity_quality = 1.0 if context.liquidity_state == "deep" else 0.5
        relative_strength = _bounded(0.5 + (context.returns_value or 0.0) * 5.0)
        bars = float(context.data_quality.get("bars_in_window", 0) or 0)
        market_quality = _bounded(bars / 120.0)
        confidence = _bounded(
            (trend_quality + volatility_quality + liquidity_quality + market_quality) / 4.0
        )
        assessment_id = f"assessment:{self.asset}:{context.timestamp}"
        artifact_trace = _trace_payload(trace, assessment_id)
        observed_at = _timestamp(context.timestamp)
        evidence = _evidence(
            evidence_id=f"evidence:{assessment_id}",
            run_id=trace.run_id,
            producer=self.manifest.agent_id,
            evidence_type="asset_assessment",
            source_ref=f"asset-context:{context.asset_context_id}",
            claim_ref=assessment_id,
            observed_at=observed_at,
            available_at=observed_at,
            trace=artifact_trace,
            payload=context.to_dict(),
        )
        return AssetAssessment(
            asset=self.asset,
            timestamp=context.timestamp,
            regime=context.market_regime or "UNKNOWN",
            trend_quality=trend_quality,
            volatility_quality=volatility_quality,
            liquidity_quality=liquidity_quality,
            relative_strength=relative_strength,
            market_quality=market_quality,
            confidence=confidence,
            evidence=(evidence,),
            trace=artifact_trace,
            agent_id=self.manifest.agent_id,
            agent_version=self.manifest.agent_version,
        )


class BTCAssetExpert(AssetExpert):
    def __init__(self) -> None:
        super().__init__("BTC")


class ETHAssetExpert(AssetExpert):
    def __init__(self) -> None:
        super().__init__("ETH")


class SOLAssetExpert(AssetExpert):
    def __init__(self) -> None:
        super().__init__("SOL")


class StrategyExpert(_BaseSpecialist):
    """Shared wrapper around one canonical AlphaFamily."""

    def __init__(self, family: AlphaFamily) -> None:
        self.family = family
        self.strategy = family.family_name
        super().__init__(
            agent_id=f"strategy-expert-{self.strategy}",
            role=AgentRole.STRATEGY_EXPERT,
            description=f"Deterministic {self.strategy} AlphaFamily adapter.",
        )

    def evaluate(
        self,
        context: AssetContext,
        candles: Sequence[OHLCV],
        *,
        trace: TraceContext,
        indicators: Mapping[str, IndicatorResult] | None = None,
        assessment: AssetAssessment | None = None,
        now_ts: int | None = None,
        timeframe: str = "5m",
    ) -> StrategyEvaluation:
        context.validate(now_ts=now_ts)
        if assessment is not None and assessment.asset != context.asset:
            raise ValueError("asset assessment does not match strategy context")
        eligible = [
            candle
            for candle in candles
            if candle.timestamp <= context.timestamp
            and candle.symbol.split("/")[0].upper() == context.asset.upper()
        ]
        eligible.sort(key=lambda candle: candle.timestamp)
        if not eligible:
            return StrategyEvaluation(
                strategy=self.strategy,
                asset=context.asset,
                context_timestamp=context.timestamp,
                proposals=(),
                evidence=(),
                agent_id=self.manifest.agent_id,
                agent_version=self.manifest.agent_version,
            )
        generated = self.family.generate(
            eligible,
            dict(indicators or {}),
            FeaturesBag(trend_regime=context.market_regime),
            timeframe=timeframe,
        )
        proposals: list[TradeProposal] = []
        proposal_evidence: list[AgentEvidence] = []
        for signal in generated:
            if signal.timestamp > context.timestamp:
                continue
            proposal, evidence = self._proposal_from_signal(context, signal, trace, timeframe)
            proposals.append(proposal)
            proposal_evidence.append(evidence)
        proposals.sort(key=lambda item: item.proposal_id)
        return StrategyEvaluation(
            strategy=self.strategy,
            asset=context.asset,
            context_timestamp=context.timestamp,
            proposals=tuple(proposals),
            evidence=tuple(proposal_evidence),
            agent_id=self.manifest.agent_id,
            agent_version=self.manifest.agent_version,
        )

    def _proposal_from_signal(
        self,
        context: AssetContext,
        signal: AlphaSignal,
        trace: TraceContext,
        timeframe: str,
    ) -> tuple[TradeProposal, AgentEvidence]:
        direction = TradeDirection(signal.direction)
        proposal_id = "proposal:" + _canonical_hash(
            {
                "asset": context.asset,
                "direction": direction.value,
                "strategy": self.strategy,
                "timeframe": timeframe,
                "regime": context.market_regime or "UNKNOWN",
                "data_time": signal.timestamp,
                "entry_reference": signal.entry_reference,
                "structural_stop": signal.structural_stop,
            }
        )[:24]
        created_at = _timestamp(signal.timestamp)
        artifact_trace = _trace_payload(trace, proposal_id)
        evidence = _evidence(
            evidence_id=f"evidence:{proposal_id}",
            run_id=trace.run_id,
            producer=self.manifest.agent_id,
            evidence_type="strategy_signal",
            source_ref=f"asset-context:{context.asset_context_id}",
            claim_ref=proposal_id,
            observed_at=created_at,
            available_at=created_at,
            trace=artifact_trace,
            payload={
                "signal": {
                    "family": signal.family,
                    "symbol": signal.symbol,
                    "timestamp": signal.timestamp,
                    "direction": signal.direction,
                    "entry_reference": signal.entry_reference,
                    "structural_stop": signal.structural_stop,
                },
                "context": context.asset_context_id,
            },
        )
        proposal = TradeProposal(
            schema_version=SPECIALIST_SCHEMA_VERSION,
            proposal_id=proposal_id,
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            asset=context.asset,
            direction=direction,
            strategy=self.strategy,
            timeframe=timeframe,
            regime=context.market_regime or "UNKNOWN",
            evidence_refs=(evidence.evidence_id,),
            invalidation=(
                f"{self.strategy} structural invalidation at {signal.structural_stop:.8f}"
            ),
            confidence=_bounded(
                0.5 + (context.returns_value or 0.0) * (1.0 if direction is TradeDirection.LONG else -1.0)
            ),
            data_time=created_at,
            created_at=created_at,
            expires_at=created_at + PROPOSAL_VALIDITY,
            trace=artifact_trace,
        )
        return proposal, evidence


class MomentumExpert(StrategyExpert):
    def __init__(self) -> None:
        super().__init__(MomentumFamily())


class TrendExpert(StrategyExpert):
    def __init__(self) -> None:
        super().__init__(TrendFamily())


class BreakoutExpert(StrategyExpert):
    def __init__(self) -> None:
        super().__init__(BreakoutFamily())


class MeanReversionExpert(StrategyExpert):
    def __init__(self) -> None:
        super().__init__(MeanReversionFamily())


class VolatilityExpert(StrategyExpert):
    def __init__(self) -> None:
        super().__init__(VolatilityFamily())


ASSET_EXPERT_FACTORIES = {
    "BTC": BTCAssetExpert,
    "ETH": ETHAssetExpert,
    "SOL": SOLAssetExpert,
}

STRATEGY_EXPERT_FACTORIES = {
    "momentum": MomentumExpert,
    "trend": TrendExpert,
    "breakout": BreakoutExpert,
    "mean_reversion": MeanReversionExpert,
    "volatility": VolatilityExpert,
}


__all__ = [
    "ASSET_EXPERT_FACTORIES",
    "SPECIALIST_SCHEMA_VERSION",
    "SPECIALIST_VERSION",
    "STRATEGY_EXPERT_FACTORIES",
    "AssetAssessment",
    "AssetExpert",
    "BTCAssetExpert",
    "BreakoutExpert",
    "ETHAssetExpert",
    "MeanReversionExpert",
    "MomentumExpert",
    "SOLAssetExpert",
    "StrategyEvaluation",
    "StrategyExpert",
    "TrendExpert",
    "VolatilityExpert",
]
