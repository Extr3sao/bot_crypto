"""Concrete AssetAgents (RFC-AIL-003): BTC, ETH, SOL.

All three currently share the identical BaseCryptoAssetAgent pipeline —
asset-specific behaviour is added ONLY when a real difference exists.
"""

from .base import BTCAssetAgent, ETHAssetAgent, SOLAssetAgent

__all__ = ["BTCAssetAgent", "ETHAssetAgent", "SOLAssetAgent"]
