"""W1-OP TARGET-B — permanent regression: LONG stop floor consistency.

Historical defect: for LONG signals the family floored `structural_stop` at
0.01 but passed the RAW (possibly negative) value as `effective_stop`, and
never signaled the floor via `floor_bound` / `minimum_stop_floor`. On
low-priced / high-volatility input a single signal could declare
structural_stop=0.01 while effective_stop<0 — nonsense for downstream
risk/execution code and a contract violation of the AlphaSignal P6 fields
(effective_stop = stop "after floor/clamp").

Contract under test:
  - effective_stop == structural_stop on every signal
  - effective_stop > 0
  - when the 0.01 floor is applied: floor_bound is True and
    minimum_stop_floor == 0.01
  - SHORT signals are unaffected (stop = price + atr*1.5, no floor)
"""
from __future__ import annotations

from trading_bot.market_data.types import OHLCV
from trading_bot.research.families.ema_crossover_family import (
    EmaCrossoverFamily,
)

T0 = 1_700_000_000_000


def _candles(close: float, n: int = 22) -> list[OHLCV]:
    return [OHLCV(symbol="TEST/USDT", timestamp=T0 + i * 60_000,
                  open=close, high=close, low=close, close=close,
                  volume=100.0) for i in range(n)]


def _family() -> EmaCrossoverFamily:
    return EmaCrossoverFamily()


def test_long_floor_consistency_low_price():
    """atr*1.5 > price: LONG stop must be floored consistently at 0.01 on
    BOTH fields, with the floor application visible to consumers."""
    sigs = _family().generate(
        _candles(0.02),
        indicators={"ema_fast": 0.03, "ema_slow": 0.01, "rsi": 60.0,
                    "atr": 0.05})
    assert len(sigs) == 1, "expected exactly one LONG signal"
    sig = sigs[0]
    assert sig.direction == "LONG"
    assert sig.structural_stop == 0.01
    assert sig.effective_stop == sig.structural_stop, (
        "effective_stop must equal structural_stop after the floor")
    assert sig.effective_stop > 0
    assert sig.floor_bound is True, "floor application must be signaled"
    assert sig.minimum_stop_floor == 0.01


def test_long_no_floor_normal_price():
    """Normal case: natural stop above the floor — both fields equal the
    natural value and no floor is signaled."""
    sigs = _family().generate(
        _candles(100.0),
        indicators={"ema_fast": 105.0, "ema_slow": 95.0, "rsi": 60.0,
                    "atr": 2.0})
    assert len(sigs) == 1
    sig = sigs[0]
    natural = 100.0 - 2.0 * 1.5
    assert sig.structural_stop == natural
    assert sig.effective_stop == natural
    assert sig.floor_bound is False
    assert sig.minimum_stop_floor is None


def test_short_unaffected():
    """SHORT stop = price + atr*1.5 (no floor needed) — consistency holds."""
    sigs = _family().generate(
        _candles(100.0),
        indicators={"ema_fast": 95.0, "ema_slow": 105.0, "rsi": 40.0,
                    "atr": 2.0})
    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == "SHORT"
    expected = 100.0 + 2.0 * 1.5
    assert sig.structural_stop == expected
    assert sig.effective_stop == sig.structural_stop
    assert sig.effective_stop > 0