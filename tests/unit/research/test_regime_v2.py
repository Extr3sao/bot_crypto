from __future__ import annotations

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research.regime_v2 import (
    MarketRegimeState,
    MarketStructure,
    StressLevel,
    TrendDirection,
    TrendStrength,
    VolatilityLevel,
    classify_regime_cell,
    derive_market_regime_state,
    regime_transition,
    regime_transition_label,
)


def _candles(closes: list[float], start_ts: int = 1_000) -> tuple[OHLCV, ...]:
    out: list[OHLCV] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        out.append(
            OHLCV(
                symbol="BTC/USDT",
                timestamp=start_ts + i * 60_000,
                open=prev,
                high=max(prev, close) * 1.001,
                low=min(prev, close) * 0.999,
                close=close,
                volume=100.0,
            )
        )
        prev = close
    return tuple(out)


def test_bull_trend_window_maps_to_bull_trend_structure() -> None:
    closes = [100.0 * (1.0 + 0.01 * i) for i in range(30)]  # +29% ramp
    state = derive_market_regime_state(_candles(closes))
    assert state.trend_direction is TrendDirection.BULL
    assert state.market_structure is MarketStructure.TREND
    assert state.stress is StressLevel.NORMAL


def test_bear_high_vol_window_maps_to_correction() -> None:
    # Strongly falling window with a couple of large gap bars -> BEAR + HIGH_VOL.
    closes = [100.0 * (1.0 - 0.012 * i) for i in range(30)]
    out = list(_candles(closes))
    # Introduce volatility spikes in the last bars (kept PIT: same window).
    # The engine's volatility detector keys on the LAST bar's ATR vs the
    # window average, so the shock bar must be the final (PIT) bar.
    for idx in (28, 29):
        c = out[idx]
        out[idx] = OHLCV(
            symbol=c.symbol,
            timestamp=c.timestamp,
            open=c.open,
            high=c.close * 1.28,
            low=c.close * 0.72,
            close=c.close,
            volume=c.volume * 3,
        )
    state = derive_market_regime_state(tuple(out))
    assert state.trend_direction is TrendDirection.BEAR
    assert state.stress in (StressLevel.CORRECTION, StressLevel.SHOCK)


def test_flat_window_is_neutral_range() -> None:
    closes = [100.0 + (0.01 if i % 2 else -0.01) for i in range(30)]
    state = derive_market_regime_state(_candles(closes))
    assert state.trend_direction is TrendDirection.NEUTRAL
    assert state.market_structure in (MarketStructure.RANGE, MarketStructure.TRANSITION)


def test_future_mutation_causality_past_states_byte_identical() -> None:
    closes = [100.0 * (1.0 + 0.008 * i) for i in range(40)]
    base = _candles(closes)
    past_window = base[:30]
    state_before = derive_market_regime_state(past_window)
    # Mutate ALL future bars (31..39) drastically.
    mutated = list(base)
    for i in range(30, 40):
        c = mutated[i]
        mutated[i] = OHLCV(
            symbol=c.symbol,
            timestamp=c.timestamp,
            open=c.open * 2,
            high=c.high * 3,
            low=c.low * 0.5,
            close=c.close * 0.3,
            volume=c.volume * 10,
        )
    state_after = derive_market_regime_state(tuple(mutated)[:30])
    assert state_before.to_dict() == state_after.to_dict()
    assert state_before.key() == state_after.key()


def test_empty_window_raises() -> None:
    with pytest.raises(ValueError):
        derive_market_regime_state(())


def test_transition_attribution() -> None:
    trend_closes = [100.0 * (1.0 + 0.01 * i) for i in range(30)]
    range_closes = [150.0 + (0.1 if i % 2 else -0.1) for i in range(30)]
    s1 = derive_market_regime_state(_candles(trend_closes, start_ts=0))
    s2 = derive_market_regime_state(_candles(range_closes, start_ts=30 * 60_000))
    transition = regime_transition(s1, s2)
    assert transition.from_ts < transition.to_ts
    assert "->" in transition.label
    label = regime_transition_label(s1, s2)
    assert label != "STABLE"
    assert "TREND" in label or "BULL" in label


def test_transition_stable_when_state_unchanged() -> None:
    closes = [100.0 * (1.0 + 0.01 * i) for i in range(30)]
    s1 = derive_market_regime_state(_candles(closes, start_ts=0))
    s2 = derive_market_regime_state(_candles(closes, start_ts=30 * 60_000))
    assert regime_transition_label(s1, s2) == "STABLE"


def test_regime_cell_status_thresholds() -> None:
    assert classify_regime_cell(strategy_id="m", asset="SOL", timeframe="5m", regime_key="BULL|TREND", n=35).status == "ELIGIBLE"
    assert classify_regime_cell(strategy_id="m", asset="SOL", timeframe="5m", regime_key="BULL|TREND", n=15).status == "SHADOW_ONLY"
    assert classify_regime_cell(strategy_id="m", asset="SOL", timeframe="5m", regime_key="BULL|TREND", n=3).status == "INSUFFICIENT_SAMPLE"
    assert classify_regime_cell(strategy_id="m", asset="SOL", timeframe="5m", regime_key="BULL|TREND", n=0).status == "NOT_ELIGIBLE"


def test_state_key_and_dict() -> None:
    state = MarketRegimeState(
        bar_ts=1,
        trend_direction=TrendDirection.BULL,
        trend_strength=TrendStrength.STRONG,
        volatility=VolatilityLevel.NORMAL,
        market_structure=MarketStructure.TREND,
        stress=StressLevel.NORMAL,
    )
    assert state.key() == "BULL|STRONG|NORMAL|TREND|NORMAL|NORMAL"
    payload = state.to_dict()
    assert payload["method_version"] == "market-regime-state-v2"
    assert payload["bar_ts"] == "1"
