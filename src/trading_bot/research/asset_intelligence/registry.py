"""CryptoAssetAgentRegistry (RFC-AIL-006).

Thin deterministic resolver: asset symbol → AssetAgent. Deliberately NOT
an autonomous "domain agent" — registration, resolution and listing only.
Cross-asset context (BTC dominance, correlations) belongs in a separate
CrossAssetContext layer and is NOT fabricated here while no data source
exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from trading_bot.market_data.types import OHLCV

from .agents import BTCAssetAgent, ETHAssetAgent, SOLAssetAgent
from .base import AssetAgent
from .models import AssetContext, AssetContextError

__all__ = ["CryptoAssetAgentRegistry", "resolve_agent"]


class _AgentFactory(Protocol):
    def __call__(self) -> AssetAgent: ...


_DEFAULT_AGENTS: dict[str, _AgentFactory] = {
    "BTC": BTCAssetAgent,
    "ETH": ETHAssetAgent,
    "SOL": SOLAssetAgent,
}


class CryptoAssetAgentRegistry:
    """Registry of supported crypto assets and their agents."""

    def __init__(self, agents: dict[str, _AgentFactory] | None = None) -> None:
        self._agents = dict(_DEFAULT_AGENTS if agents is None else agents)

    def register(self, asset_id: str, factory: _AgentFactory) -> None:
        if not asset_id:
            raise AssetContextError("registry: asset_id must be non-empty")
        self._agents[asset_id.upper()] = factory

    def resolve(self, asset_id: str) -> AssetAgent:
        """Fail closed on unknown assets (negative test N6)."""
        factory = self._agents.get((asset_id or "").upper())
        if factory is None:
            raise AssetContextError(f"no AssetAgent registered for asset: {asset_id}")
        return factory()

    def supported_assets(self) -> list[str]:
        return sorted(self._agents)

    def build_context(
        self,
        asset_id: str,
        candles: Sequence[OHLCV],
        timestamp: int,
        *,
        data_fingerprint: str = "",
        dataset_id: str = "",
    ) -> AssetContext:
        """Resolve the agent and build a validated context in one step."""
        agent = self.resolve(asset_id)
        context = agent.build_context(
            candles, timestamp, data_fingerprint=data_fingerprint, dataset_id=dataset_id
        )
        agent.validate_context(context)
        return context


def resolve_agent(asset_id: str) -> AssetAgent:
    """Module-level convenience resolver (default registry)."""
    return CryptoAssetAgentRegistry().resolve(asset_id)
