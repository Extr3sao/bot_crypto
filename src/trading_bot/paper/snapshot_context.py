"""Snapshot → AssetContext bridge for the paper decision path (CP-PO-002).

Pure composition layer implementing the resolution mandated by FQ2/FQ3:

    MarketSnapshot(symbol, timestamp)
        ↓ FetcherBarReader (existing scanner fetcher protocol)
        PIT OHLCV slice (bar.timestamp <= snapshot.timestamp)
        ↓ CryptoAssetAgentRegistry.build_context (canonical builder —
          slices again to the feature window and classifies the regime)
        AssetContext

This module owns NO indicators, NO regime classification, NO strategy
selection, NO risk, NO execution and NO market-data persistence. It only
composes existing canonical components and enforces the point-in-time
trim: every bar used is ``bar.timestamp <= snapshot.timestamp``.
"""

from __future__ import annotations

from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry

__all__ = ["SnapshotContextBridge", "context_from_snapshot"]


class SnapshotContextBridge:
    """Compose (symbol, timestamp) → PIT OHLCV → AssetAgent → AssetContext."""

    def __init__(
        self,
        reader: Any,  # HistoricalBarReader (structural typing)
        registry: CryptoAssetAgentRegistry | None = None,
        *,
        lookback_bars: int = 120,
    ) -> None:
        self._reader = reader
        self._registry = registry or CryptoAssetAgentRegistry()
        if lookback_bars <= 0:
            raise ValueError("lookback_bars must be positive")
        self._lookback_bars = lookback_bars

    async def build(
        self,
        symbol: str,
        timestamp_ms: int,
        *,
        data_fingerprint: str = "",
        dataset_id: str = "",
    ) -> Any:  # AssetContext
        """Build a validated AssetContext as of ``timestamp_ms``.

        Raises (fail closed) when the reader fails or the registry rejects
        the context (insufficient history, PIT violation, etc.).
        """
        bars = await self._reader.get_ohlcv(
            symbol,
            as_of_timestamp_ms=timestamp_ms,
            lookback_bars=self._lookback_bars,
        )
        pit_bars = trim_to_pit(bars, timestamp_ms)
        if not pit_bars:
            raise ValueError(f"no historical bars at or before {timestamp_ms} for {symbol}")
        return self._registry.build_context(
            symbol.split("/")[0],  # "BTC/USDT" → "BTC"
            pit_bars,
            timestamp_ms,
            data_fingerprint=data_fingerprint,
            dataset_id=dataset_id,
        )


def trim_to_pit(bars: list[OHLCV], timestamp_ms: int) -> list[OHLCV]:
    """Keep only bars stamped at or before ``timestamp_ms`` (PIT trim).

    The bar stamped exactly at the decision timestamp is INCLUDED — it is
    the completed decision bar. Anything later is future data.
    """
    return [b for b in bars if b.timestamp <= timestamp_ms]


def context_from_snapshot(
    snapshot: Any,
    bars: list[OHLCV],
    *,
    registry: CryptoAssetAgentRegistry | None = None,
) -> Any:
    """Synchronous variant for callers that already hold the bar slice.

    Applies the PIT trim against ``snapshot.timestamp`` before delegating
    to the canonical ``CryptoAssetAgentRegistry.build_context``.
    """
    ts = int(snapshot.timestamp)
    pit_bars = trim_to_pit(bars, ts)
    if not pit_bars:
        raise ValueError(f"no historical bars at or before {ts} for {snapshot.symbol}")
    reg = registry or CryptoAssetAgentRegistry()
    return reg.build_context(
        str(snapshot.symbol).split("/")[0],
        pit_bars,
        ts,
    )
