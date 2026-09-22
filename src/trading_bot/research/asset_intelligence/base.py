"""AssetAgent contract + shared crypto base (RFC-AIL-003, RFC-AIL-004).

``AssetAgent`` is the protocol every per-asset agent implements. A base
crypto implementation (``BaseCryptoAssetAgent``) provides the shared
pipeline: slice a point-in-time window, run the shared feature
calculators, classify regime, and assemble a versioned AssetContext.
Asset-specific behaviour is added by subclasses ONLY where assets really
differ (currently: nothing — BTC/ETH/SOL share identical pipelines).

The base agent takes the FULL dataset plus the context timestamp and
slices internally — this is what guarantees no lookahead: nothing past
``timestamp`` is ever passed to a calculator.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from trading_bot.market_data.types import OHLCV

from .features import compute_shared
from .models import AssetContext, AssetContextError

__all__ = ["AGENT_VERSION", "AssetAgent", "BaseCryptoAssetAgent"]

AGENT_VERSION = "base-crypto-v1"

# Point-in-time lookback window for features (bars, not ms) — sized to
# cover the EMA21/RSI14/ATR14 warmup plus margin, regardless of timeframe.
FEATURE_WINDOW_BARS = 120


class AssetAgent(Protocol):
    """Contract for every per-asset agent (RFC-AIL-003)."""

    @property
    def asset_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def required_inputs(self) -> list[str]: ...

    def build_context(
        self,
        candles: Sequence[OHLCV],
        timestamp: int,
        *,
        data_fingerprint: str = "",
        dataset_id: str = "",
    ) -> AssetContext: ...

    def validate_context(self, context: AssetContext, *, now_ts: int | None = None) -> None: ...


class BaseCryptoAssetAgent:
    """Shared crypto pipeline: slice window → features → regime → context.

    Subclasses add asset-specific behaviour only where assets really
    differ. ``build_context`` slices ``candles`` to the point-in-time
    window ending at ``timestamp`` BEFORE any calculator runs, so no
    future bar can influence the context (no lookahead by construction).
    """

    asset_id = "CRYPTO"
    version = AGENT_VERSION

    def required_inputs(self) -> list[str]:
        return ["ohlcv"]

    # -- point-in-time slicing --------------------------------------------
    def slice_window(self, candles: Sequence[OHLCV], timestamp: int) -> list[OHLCV]:
        """This asset's bars with timestamp <= ``timestamp``, newest-last.

        Filters by symbol first (asset isolation: other assets' bars never
        enter the window), then caps to the point-in-time lookback.

        Raises AssetContextError when there is not enough history for the
        mandatory features (fail closed, N4).
        """
        past = [
            c
            for c in candles
            if c.timestamp <= timestamp and c.symbol.split("/")[0].upper() == self.asset_id
        ]
        if not past:
            raise AssetContextError(f"no bars at or before ts {timestamp} for {self.asset_id}")
        past.sort(key=lambda c: c.timestamp)
        window = past[-FEATURE_WINDOW_BARS:]
        if len(window) < 22:
            raise AssetContextError(
                f"insufficient history for {self.asset_id}: {len(window)} bars "
                "in point-in-time window (need >= 22)"
            )
        return window

    # -- regime classification (deterministic, point-in-time) -------------
    def classify_regime(self, window: list[OHLCV]) -> str:
        """TREND_UP/TREND_DOWN/RANGE/HIGH_VOLATILITY/LOW_VOLATILITY."""
        shared = compute_shared(window)
        trend = shared.trend or {}
        spread = float(trend.get("spread", 0.0) or 0.0)
        vol = shared.volatility_atr
        vol = float(vol) if vol is not None else 0.0
        if vol > 0.02:
            return "HIGH_VOLATILITY"
        if vol < 0.004:
            return "LOW_VOLATILITY"
        if spread > 0.004:
            return "TREND_UP"
        if spread < -0.004:
            return "TREND_DOWN"
        return "RANGE"

    # -- context assembly ---------------------------------------------------
    def build_context(
        self,
        candles: Sequence[OHLCV],
        timestamp: int,
        *,
        data_fingerprint: str = "",
        dataset_id: str = "",
    ) -> AssetContext:
        window = self.slice_window(candles, timestamp)
        shared = compute_shared(window)

        momentum: dict[str, object] = {}
        volatility: dict[str, object] = {}
        if shared.returns is not None:
            momentum["returns"] = shared.returns
        if shared.trend is not None:
            momentum["trend"] = shared.trend
        if shared.momentum_rsi is not None:
            momentum["rsi"] = shared.momentum_rsi
        if shared.volatility_atr is not None:
            volatility["atr_norm"] = shared.volatility_atr

        regime = self.classify_regime(window)
        trend_direction = (shared.trend or {}).get("direction")
        trend_direction = str(trend_direction) if trend_direction is not None else None
        vol_state = (
            "high"
            if regime == "HIGH_VOLATILITY"
            else "low"
            if regime == "LOW_VOLATILITY"
            else "normal"
        )
        liq = shared.liquidity
        liquidity_state = None
        if liq is not None:
            liquidity_state = "deep" if liq["spread_median"] < 0.002 else "thin"

        data_quality = {
            "bars_in_window": len(window),
            "newest_bar_ts": window[-1].timestamp,
        }

        return AssetContext(
            asset=self.asset_id,
            timestamp=timestamp,
            market_regime=regime,
            trend_state=trend_direction,
            volatility_state=vol_state,
            liquidity_state=liquidity_state,
            momentum_features=momentum,
            volatility_features=volatility,
            volume_features=shared.volume or {},
            data_quality=data_quality,
            # dataset provenance comes from the signed dataset metadata;
            # callers pass it through so the context carries full provenance
            data_fingerprint=data_fingerprint,
            dataset_id=dataset_id,
            agent_version=self.version,
            regime_method_version="asset-agent-regime-v1",
            window_start_ts=window[0].timestamp,
            window_end_ts=window[-1].timestamp,
            bar_count=len(window),
        )

    def validate_context(self, context: AssetContext, *, now_ts: int | None = None) -> None:
        context.validate(now_ts=now_ts)
