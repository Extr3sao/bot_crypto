"""Market Regime Engine (FASE 8, P18).

Decoupled from AlphaFamily — each family CHOOSES which regime labels
to use, but does NOT create them.

Supported regimes:
- BULL: sustained upward price movement
- BEAR: sustained downward price movement
- MIXED: no clear direction
- HIGH_VOL: elevated volatility (ATR-based)
- LOW_VOL: compressed volatility
- TRENDING: strong directional movement (regardless of direction)
- RANGING: mean-reverting / choppy market

Design:
- RegimeEngine is a standalone module.
- AlphaFamily may query regime but does NOT set regime.
- Regime labels are descriptive (P7), not prescriptive.
- Multiple regimes can be active simultaneously (BULL + HIGH_VOL).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from trading_bot.market_data.types import OHLCV

# ---------------------------------------------------------------------------
# Regime Types
# ---------------------------------------------------------------------------

RegimeType = Literal["BULL", "BEAR", "MIXED", "HIGH_VOL", "LOW_VOL", "TRENDING", "RANGING"]


@dataclass(frozen=True, slots=True)
class RegimeSnapshot:
    """Current regime state at a point in time."""

    timestamp: int
    active_regimes: frozenset[RegimeType]
    confidence: dict[RegimeType, float]  # 0.0 - 1.0 per regime
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def primary_regime(self) -> RegimeType | None:
        """The regime with highest confidence, or None if no regime active."""
        if not self.confidence:
            return None
        return max(self.confidence, key=self.confidence.get)  # type: ignore[arg-type]

    def is_active(self, regime: RegimeType) -> bool:
        """Check if a specific regime is active."""
        return regime in self.active_regimes

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "active_regimes": sorted(self.active_regimes),
            "confidence": self.confidence,
            "primary_regime": self.primary_regime,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Regime Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeConfig:
    """Configurable thresholds for regime detection."""

    # Trend detection
    trend_lookback: int = 20  # bars to compute trend
    trend_threshold_pct: float = 2.0  # min % move for BULL/BEAR

    # Volatility detection
    vol_lookback: int = 20
    vol_high_percentile: float = 80.0  # above this = HIGH_VOL
    vol_low_percentile: float = 20.0  # below this = LOW_VOL

    # Trending vs Ranging
    adx_period: int = 14
    adx_trending_threshold: float = 25.0  # above = TRENDING
    adx_ranging_threshold: float = 20.0  # below = RANGING


# ---------------------------------------------------------------------------
# Regime Engine
# ---------------------------------------------------------------------------


class RegimeEngine:
    """Standalone market regime detector (P18).

    Decoupled from AlphaFamily — provides regime labels that families
    may optionally use for diagnostic features (P7).

    P18 contract:
    - RegimeEngine creates regime labels.
    - AlphaFamily queries regime but does NOT set it.
    - Multiple regimes can be active simultaneously.
    - Labels are descriptive, not prescriptive.
    """

    def __init__(self, config: RegimeConfig | None = None) -> None:
        self._config = config or RegimeConfig()
        self._log = structlog.get_logger("regime_engine")

    def detect(self, candles: list[OHLCV]) -> RegimeSnapshot:
        """Detect current regime from candle data.

        Args:
            candles: Recent candle history (at least config.trend_lookback bars)

        Returns:
            RegimeSnapshot with active regimes and confidence scores
        """
        if len(candles) < self._config.trend_lookback:
            return RegimeSnapshot(
                timestamp=candles[-1].timestamp if candles else 0,
                active_regimes=frozenset(),
                confidence={},
                metadata={"reason": "insufficient_data"},
            )

        confidence: dict[RegimeType, float] = {}

        # 1. Trend detection (BULL/BEAR/MIXED)
        bull_conf, bear_conf = self._detect_trend(candles)
        if bull_conf > 0:
            confidence["BULL"] = bull_conf
        if bear_conf > 0:
            confidence["BEAR"] = bear_conf
        if bull_conf < 0.3 and bear_conf < 0.3:
            confidence["MIXED"] = 1.0 - max(bull_conf, bear_conf)

        # 2. Volatility detection (HIGH_VOL/LOW_VOL)
        high_vol_conf, low_vol_conf = self._detect_volatility(candles)
        if high_vol_conf > 0:
            confidence["HIGH_VOL"] = high_vol_conf
        if low_vol_conf > 0:
            confidence["LOW_VOL"] = low_vol_conf

        # 3. Trending vs Ranging (ADX-based)
        trending_conf, ranging_conf = self._detect_trend_strength(candles)
        if trending_conf > 0:
            confidence["TRENDING"] = trending_conf
        if ranging_conf > 0:
            confidence["RANGING"] = ranging_conf

        # Filter to active regimes (confidence > 0.3)
        active = frozenset(r for r, c in confidence.items() if c > 0.3)

        return RegimeSnapshot(
            timestamp=candles[-1].timestamp,
            active_regimes=active,
            confidence=confidence,
        )

    def _detect_trend(self, candles: list[OHLCV]) -> tuple[float, float]:
        """Detect BULL/BEAR trend from price movement.

        Returns (bull_confidence, bear_confidence) in [0, 1].
        """
        lookback = self._config.trend_lookback
        recent = candles[-lookback:]

        start_price = recent[0].open
        end_price = recent[-1].close

        if start_price <= 0:
            return 0.0, 0.0

        pct_change = (end_price - start_price) / start_price * 100
        threshold = self._config.trend_threshold_pct

        if pct_change > threshold:
            # Bullish
            confidence = min(1.0, pct_change / (threshold * 2))
            return confidence, 0.0
        elif pct_change < -threshold:
            # Bearish
            confidence = min(1.0, abs(pct_change) / (threshold * 2))
            return 0.0, confidence
        else:
            return 0.0, 0.0

    def _detect_volatility(self, candles: list[OHLCV]) -> tuple[float, float]:
        """Detect HIGH_VOL/LOW_VOL from ATR percentile.

        Returns (high_vol_confidence, low_vol_confidence).
        """
        lookback = self._config.vol_lookback
        recent = candles[-lookback:]

        if len(recent) < 3:
            return 0.0, 0.0

        # Compute ATR for each bar
        atrs: list[float] = []
        for i in range(1, len(recent)):
            high = recent[i].high
            low = recent[i].low
            prev_close = recent[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            atrs.append(tr)

        if not atrs:
            return 0.0, 0.0

        current_atr = atrs[-1]
        avg_atr = sum(atrs) / len(atrs)

        if avg_atr <= 0:
            return 0.0, 0.0

        ratio = current_atr / avg_atr

        high_threshold = 1.0 + (self._config.vol_high_percentile - 50) / 100
        low_threshold = 1.0 - (50 - self._config.vol_low_percentile) / 100

        high_conf = 0.0
        low_conf = 0.0

        if ratio > high_threshold:
            high_conf = min(1.0, (ratio - high_threshold) / high_threshold + 0.5)
        elif ratio < low_threshold:
            low_conf = min(1.0, (low_threshold - ratio) / low_threshold + 0.5)

        return high_conf, low_conf

    def _detect_trend_strength(self, candles: list[OHLCV]) -> tuple[float, float]:
        """Detect TRENDING vs RANGING using simplified ADX.

        Returns (trending_confidence, ranging_confidence).
        """
        lookback = self._config.adx_period * 2
        if len(candles) < lookback:
            return 0.0, 0.0

        recent = candles[-lookback:]

        # Simplified ADX: compute directional movement
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        tr_list: list[float] = []

        for i in range(1, len(recent)):
            high_diff = recent[i].high - recent[i - 1].high
            low_diff = recent[i - 1].low - recent[i].low

            plus_dm.append(max(high_diff, 0) if high_diff > low_diff else 0)
            minus_dm.append(max(low_diff, 0) if low_diff > high_diff else 0)

            tr = max(
                recent[i].high - recent[i].low,
                abs(recent[i].high - recent[i - 1].close),
                abs(recent[i].low - recent[i - 1].close),
            )
            tr_list.append(tr)

        if not tr_list or sum(tr_list) == 0:
            return 0.0, 0.0

        # Smoothed averages
        avg_tr = sum(tr_list) / len(tr_list)
        avg_plus = sum(plus_dm) / len(plus_dm)
        avg_minus = sum(minus_dm) / len(minus_dm)

        # +DI and -DI
        plus_di = (avg_plus / avg_tr * 100) if avg_tr > 0 else 0
        minus_di = (avg_minus / avg_tr * 100) if avg_tr > 0 else 0

        # DX
        di_sum = plus_di + minus_di
        dx = abs(plus_di - minus_di) / di_sum * 100 if di_sum > 0 else 0

        # Simplified ADX (single period)
        adx = dx

        trending_threshold = self._config.adx_trending_threshold
        ranging_threshold = self._config.adx_ranging_threshold

        if adx > trending_threshold:
            conf = min(1.0, (adx - ranging_threshold) / (trending_threshold - ranging_threshold + 1))
            return conf, 0.0
        elif adx < ranging_threshold:
            conf = min(1.0, (ranging_threshold - adx) / ranging_threshold + 0.3)
            return 0.0, conf
        else:
            return 0.0, 0.0


__all__ = ["RegimeConfig", "RegimeEngine", "RegimeSnapshot", "RegimeType"]
