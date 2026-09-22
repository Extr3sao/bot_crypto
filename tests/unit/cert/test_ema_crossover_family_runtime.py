"""RUN-OP-004 — direct tests of the RUNTIME-authoritative EMA implementation.

RUN-OP-003 proved with executed traces that the canonical PAPER runtime
executes ``EmaCrossoverFamily.generate`` (via StrategyRouter), while
``EmaCrossoverStrategy`` is TEST_ONLY. These tests target the family
directly so TESTED_IMPLEMENTATION == RUNTIME_IMPLEMENTATION.

Contract under test (from the family source):

- < 22 candles  -> no signal (fail closed);
- fast EMA > slow EMA and RSI > 50   -> LONG with ATR structural stop;
- fast EMA < slow EMA and RSI < 50   -> SHORT with ATR structural stop;
- flat / neutral (fast == slow)      -> no signal;
- indicators are self-computed when none are provided;
- explicit indicator values are honored when provided.
"""

from __future__ import annotations

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily

TS0 = 1_800_000_000_000
BAR_MS = 60_000


def _candles(symbol: str, n: int, *, rising: bool, flat: bool = False) -> list[OHLCV]:
    out: list[OHLCV] = []
    for i in range(n):
        close = 100.0 if flat else 100.0 + (i * 1.0 if rising else -i * 1.0)
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=TS0 + i * BAR_MS,
                open=close - 0.5,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1_000.0,
            )
        )
    return out


def _family() -> EmaCrossoverFamily:
    return EmaCrossoverFamily()


def test_insufficient_bars_returns_empty() -> None:
    candles = _candles("BTC/USDT", 21, rising=True)
    assert _family().generate(candles, {}) == []


def test_neutral_flat_input_returns_no_signal() -> None:
    candles = _candles("BTC/USDT", 100, rising=False, flat=True)
    assert _family().generate(candles, {}) == []


def test_atr_zero_returns_empty() -> None:
    """Flat candles self-compute ATR == 0 -> fail closed even on 100 bars."""
    candles = _candles("BTC/USDT", 100, rising=False, flat=True)
    assert _family().generate(candles, {}) == []


def test_bullish_rising_generates_long() -> None:
    family = _family()
    candles = _candles("BTC/USDT", 100, rising=True)
    signals = family.generate(candles, {})
    assert len(signals) == 1
    sig = signals[0]
    assert sig.family == "ema_crossover"
    assert sig.direction == "LONG"
    assert sig.symbol == "BTC/USDT"
    assert sig.timestamp == candles[-1].timestamp
    assert sig.entry_reference == pytest.approx(candles[-1].close)
    assert sig.structural_stop < sig.entry_reference  # ATR-based stop below entry
    assert sig.timeframe == "5m"
    assert sig.effective_stop == pytest.approx(sig.structural_stop)


def test_bearish_falling_generates_short() -> None:
    family = _family()
    candles = _candles("BTC/USDT", 100, rising=False)
    signals = family.generate(candles, {})
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == "SHORT"
    assert sig.symbol == "BTC/USDT"
    assert sig.structural_stop > sig.entry_reference  # ATR-based stop above entry


def test_metadata_features_present() -> None:
    candles = _candles("BTC/USDT", 100, rising=True)
    sig = _family().generate(candles, {})[0]
    assert sig.features is not None
    assert sig.features.rsi is not None
    assert sig.features.atr is not None
    assert sig.features.atr_pct is not None
    assert sig.features.ema_alignment is not None
    assert sig.features.structural_stop_width is not None


def test_explicit_indicators_are_honored() -> None:
    """Flat candles + explicit bullish indicators must produce LONG."""
    candles = _candles("BTC/USDT", 100, rising=False, flat=True)
    indicators = {"ema_fast": 101.0, "ema_slow": 100.0, "rsi": 60.0, "atr": 1.0}
    signals = _family().generate(candles, indicators)
    assert len(signals) == 1
    assert signals[0].direction == "LONG"


def test_explicit_bearish_indicators_are_honored() -> None:
    candles = _candles("BTC/USDT", 100, rising=False, flat=True)
    indicators = {"ema_fast": 99.0, "ema_slow": 100.0, "rsi": 40.0, "atr": 1.0}
    signals = _family().generate(candles, indicators)
    assert len(signals) == 1
    assert signals[0].direction == "SHORT"


def test_non_numeric_indicator_values_fail_closed() -> None:
    candles = _candles("BTC/USDT", 100, rising=True)
    indicators = {"ema_fast": "x", "ema_slow": 100.0, "rsi": 60.0, "atr": 1.0}
    assert _family().generate(candles, indicators) == []


def test_family_name_property() -> None:
    assert _family().family_name == "ema_crossover"
