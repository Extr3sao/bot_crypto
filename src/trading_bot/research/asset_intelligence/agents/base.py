"""Concrete AssetAgents (RFC-AIL-003): BTC, ETH, SOL.

All three currently share the identical BaseCryptoAssetAgent pipeline —
asset-specific behaviour is added ONLY when a real difference exists.
"""

from ..base import AGENT_VERSION, BaseCryptoAssetAgent

__all__ = ["BTCAssetAgent", "ETHAssetAgent", "SOLAssetAgent"]


class BTCAssetAgent(BaseCryptoAssetAgent):
    asset_id = "BTC"
    version = AGENT_VERSION


class ETHAssetAgent(BaseCryptoAssetAgent):
    asset_id = "ETH"
    version = AGENT_VERSION


class SOLAssetAgent(BaseCryptoAssetAgent):
    asset_id = "SOL"
    version = AGENT_VERSION
