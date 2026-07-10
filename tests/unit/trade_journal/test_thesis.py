from __future__ import annotations

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.trade_journal import EntryThesisInput, build_entry_thesis


def _candle(ts: int, open_: float, high: float, low: float, close: float) -> OHLCV:
    return OHLCV(
        symbol="BTC/USDT",
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def _candles_near_support() -> tuple[OHLCV, ...]:
    return (
        _candle(1, 100, 103, 99, 102),
        _candle(2, 102, 105, 101, 104),
        _candle(3, 104, 106, 95, 96),
        _candle(4, 96, 99, 94, 98),
        _candle(5, 98, 103, 97, 102),
        _candle(6, 102, 104, 100, 101),
        _candle(7, 101, 103, 100, 102),
    )


def test_build_entry_thesis_marks_long_near_support_as_met() -> None:
    thesis = build_entry_thesis(
        EntryThesisInput(
            trade_case_id="case-1",
            signal_id="signal-1",
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=98,
            tp_price=103,
            sl_price=94,
            timeframe="1m",
            entry_reason="support reclaim",
            candles=_candles_near_support(),
            indicators={"rsi": 51.0},
            created_at=8,
        ),
        swing_window=1,
        near_zone_bps=500,
    )

    assert "near_support" in thesis.criteria_met
    assert thesis.confidence_score > 0.5
    assert thesis.indicators["rsi"] == 51.0
    assert thesis.zones


def test_build_entry_thesis_marks_long_near_resistance_as_failed() -> None:
    thesis = build_entry_thesis(
        EntryThesisInput(
            trade_case_id="case-1",
            signal_id="signal-1",
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=109,
            tp_price=112,
            sl_price=105,
            timeframe="1m",
            entry_reason="breakout attempt",
            candles=(
                _candle(1, 100, 103, 99, 102),
                _candle(2, 102, 105, 101, 104),
                _candle(3, 104, 110, 103, 109),
                _candle(4, 109, 108, 104, 105),
                _candle(5, 105, 107, 103, 104),
            ),
            created_at=6,
        ),
        swing_window=1,
        near_zone_bps=250,
    )

    assert "near_resistance_against_long" in thesis.criteria_failed
    assert thesis.confidence_score < 0.5


def test_build_entry_thesis_rejects_bad_direction() -> None:
    with pytest.raises(ValueError, match="direction must be LONG or SHORT"):
        build_entry_thesis(
            EntryThesisInput(
                trade_case_id="case-1",
                signal_id="signal-1",
                symbol="BTC/USDT",
                direction="SIDEWAYS",
                entry_price=100,
                tp_price=102,
                sl_price=98,
                timeframe="1m",
                entry_reason="bad",
                candles=_candles_near_support(),
            )
        )

