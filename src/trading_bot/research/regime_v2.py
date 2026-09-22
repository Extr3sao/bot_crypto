"""Canonical MarketRegimeState — REGIME-INTELLIGENCE-V2 (Track C).

Composes over the existing PIT regime engine (``research/regime.py``) instead
of replacing it: the existing ``RegimeEngine`` remains the runtime-reachable
label source; this module adds the canonical six-dimension state required for
attribution and the future performance matrix. All calculations are PIT-safe:
every dimension is derived from the observation window ending at ``bar_ts``
and never from later bars.

Dimensions (Track C minimum):

- trend_direction:  BULL / BEAR / NEUTRAL
- trend_strength:   WEAK / MEDIUM / STRONG
- volatility:       LOW / NORMAL / HIGH / EXTREME
- market_structure: TREND / RANGE / BREAKOUT / TRANSITION
- stress:           NORMAL / CORRECTION / SHOCK
- correlation_regime: NORMAL / FUSED  (populated by Track D at runtime;
  defaults to NORMAL until a correlation provider is wired)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trading_bot.market_data.types import OHLCV
from trading_bot.research.regime import RegimeEngine, RegimeSnapshot


class TrendDirection(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


class TrendStrength(StrEnum):
    WEAK = "WEAK"
    MEDIUM = "MEDIUM"
    STRONG = "STRONG"


class VolatilityLevel(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class MarketStructure(StrEnum):
    TREND = "TREND"
    RANGE = "RANGE"
    BREAKOUT = "BREAKOUT"
    TRANSITION = "TRANSITION"


class StressLevel(StrEnum):
    NORMAL = "NORMAL"
    CORRECTION = "CORRECTION"
    SHOCK = "SHOCK"


class CorrelationRegime(StrEnum):
    NORMAL = "NORMAL"
    FUSED = "FUSED"


REGIME_STATE_VERSION = "market-regime-state-v2"


@dataclass(frozen=True, slots=True)
class MarketRegimeState:
    """Canonical regime state at one point in time (PIT)."""

    bar_ts: int
    trend_direction: TrendDirection
    trend_strength: TrendStrength
    volatility: VolatilityLevel
    market_structure: MarketStructure
    stress: StressLevel
    correlation_regime: CorrelationRegime = CorrelationRegime.NORMAL
    method_version: str = REGIME_STATE_VERSION

    def key(self) -> str:
        return "|".join(
            (
                self.trend_direction.value,
                self.trend_strength.value,
                self.volatility.value,
                self.market_structure.value,
                self.stress.value,
                self.correlation_regime.value,
            )
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "bar_ts": str(self.bar_ts),
            "trend_direction": self.trend_direction.value,
            "trend_strength": self.trend_strength.value,
            "volatility": self.volatility.value,
            "market_structure": self.market_structure.value,
            "stress": self.stress.value,
            "correlation_regime": self.correlation_regime.value,
            "method_version": self.method_version,
        }


@dataclass(frozen=True, slots=True)
class RegimeTransition:
    """Attribution record linking two consecutive regime states."""

    from_key: str
    to_key: str
    from_ts: int
    to_ts: int

    @property
    def label(self) -> str:
        return f"{self.from_key} -> {self.to_key}"

    def to_dict(self) -> dict[str, str]:
        return {
            "from_key": self.from_key,
            "to_key": self.to_key,
            "from_ts": str(self.from_ts),
            "to_ts": str(self.to_ts),
            "label": self.label,
        }


def derive_market_regime_state(candles: tuple[OHLCV, ...]) -> MarketRegimeState:
    """Derive the canonical state from the PIT window ``candles``.

    The caller must pass ONLY bars with close <= the decision timestamp. The
    function itself never looks ahead: it consumes exactly the window given.
    """
    if not candles:
        raise ValueError("derive_market_regime_state requires a non-empty window")
    engine = RegimeEngine()
    snapshot: RegimeSnapshot = engine.detect(list(candles))
    confidence = snapshot.confidence

    # trend_direction + strength from BULL/BEAR confidence
    bull = confidence.get("BULL", 0.0)
    bear = confidence.get("BEAR", 0.0)
    if bull >= 0.3 and bull >= bear:
        direction = TrendDirection.BULL
    elif bear >= 0.3:
        direction = TrendDirection.BEAR
    else:
        direction = TrendDirection.NEUTRAL
    peak = max(bull, bear)
    strength = (
        TrendStrength.STRONG
        if peak >= 0.75
        else TrendStrength.MEDIUM
        if peak >= 0.5
        else TrendStrength.WEAK
    )

    # volatility from HIGH_VOL/LOW_VOL confidence
    high_vol = confidence.get("HIGH_VOL", 0.0)
    low_vol = confidence.get("LOW_VOL", 0.0)
    if high_vol >= 0.75:
        volatility = VolatilityLevel.EXTREME
    elif high_vol >= 0.3:
        volatility = VolatilityLevel.HIGH
    elif low_vol >= 0.3:
        volatility = VolatilityLevel.LOW
    else:
        volatility = VolatilityLevel.NORMAL

    # market structure from TRENDING/RANGING confidence
    trending = confidence.get("TRENDING", 0.0)
    ranging = confidence.get("RANGING", 0.0)
    if trending >= 0.3 and trending >= ranging:
        structure = MarketStructure.TREND
    elif ranging >= 0.3:
        structure = MarketStructure.RANGE
    elif direction is not TrendDirection.NEUTRAL:
        structure = MarketStructure.BREAKOUT
    else:
        structure = MarketStructure.TRANSITION

    # stress: drawdown-like proxy from direction + volatility (PIT window)
    if volatility is VolatilityLevel.EXTREME:
        stress = StressLevel.SHOCK
    elif volatility is VolatilityLevel.HIGH and direction is TrendDirection.BEAR:
        stress = StressLevel.CORRECTION
    else:
        stress = StressLevel.NORMAL

    return MarketRegimeState(
        bar_ts=candles[-1].timestamp,
        trend_direction=direction,
        trend_strength=strength,
        volatility=volatility,
        market_structure=structure,
        stress=stress,
    )


def regime_transition(prev: MarketRegimeState, curr: MarketRegimeState) -> RegimeTransition:
    """Build the attribution transition between two consecutive states."""
    return RegimeTransition(
        from_key=prev.key(), to_key=curr.key(), from_ts=prev.bar_ts, to_ts=curr.bar_ts
    )


def regime_transition_label(prev: MarketRegimeState, curr: MarketRegimeState) -> str:
    """Compact human label, e.g. 'TREND->RANGE' or 'BULL->CORRECTION'."""
    a = f"{prev.trend_direction.value}|{prev.market_structure.value}"
    b = f"{curr.trend_direction.value}|{curr.market_structure.value}"
    if a != b:
        return f"{a}->{b}"
    if prev.stress != curr.stress:
        return f"{prev.stress.value}->{curr.stress.value}"
    if prev.volatility != curr.volatility:
        return f"{prev.volatility.value}->{curr.volatility.value}"
    return "STABLE"


@dataclass(frozen=True, slots=True)
class RegimeCellStatus:
    """Status of one (strategy x asset x timeframe x regime) statistic cell."""

    strategy_id: str
    asset: str
    timeframe: str
    regime_key: str
    n: int
    status: str  # ELIGIBLE / NOT_ELIGIBLE / SHADOW_ONLY / INSUFFICIENT_SAMPLE


def classify_regime_cell(
    *,
    strategy_id: str,
    asset: str,
    timeframe: str,
    regime_key: str,
    n: int,
    min_eligible_n: int = 30,
    min_shadow_n: int = 10,
) -> RegimeCellStatus:
    """C2: canonical status for a regime performance matrix cell.

    Deterministic thresholds; no activation logic lives here (POC01 frozen).
    """
    if n >= min_eligible_n:
        status = "ELIGIBLE"
    elif n >= min_shadow_n:
        status = "SHADOW_ONLY"
    elif n > 0:
        status = "INSUFFICIENT_SAMPLE"
    else:
        status = "NOT_ELIGIBLE"
    return RegimeCellStatus(
        strategy_id=strategy_id,
        asset=asset,
        timeframe=timeframe,
        regime_key=regime_key,
        n=n,
        status=status,
    )
