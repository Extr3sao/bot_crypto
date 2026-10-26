"""G-7: real-data validation must reject every unsafe window explicitly."""

from __future__ import annotations

from dataclasses import replace

from trading_bot.market_data.real_data_validation import (
    bar_content_hash,
    timeframe_ms,
    validate_closed_bars,
)
from trading_bot.market_data.types import OHLCV

BASE = 1_792_900_000_000
TF = "5m"


def _bars(count: int = 120) -> list[OHLCV]:
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=BASE + index * timeframe_ms(TF),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=10.0,
        )
        for index in range(count)
    ]


def _validate(
    bars: list[OHLCV],
    *,
    decision: int | None = None,
    received: int | None = None,
    min_bars: int = 100,
):
    last_close = max(bar.timestamp for bar in bars) + timeframe_ms(TF) if bars else BASE
    return validate_closed_bars(
        bars,
        provider="test-public",
        asset="BTC",
        symbol="BTC/USDT",
        timeframe=TF,
        decision_time_ms=last_close if decision is None else decision,
        received_at_ms=last_close if received is None else received,
        min_bars=min_bars,
    )


def test_valid_window_is_ok_and_hashes_exactly() -> None:
    bars = _bars()
    result = _validate(bars)
    assert result.ok, result.issues
    assert result.validation_status == "OK"
    assert result.bar_count == 120
    assert result.data_time_ms == bars[-1].timestamp
    assert result.freshness_ms == 0
    assert result.data_hash == bar_content_hash(bars)
    assert result.data_time_ms + timeframe_ms(TF) <= result.decision_time_ms


def test_stale_window_is_rejected_against_documented_budget() -> None:
    bars = _bars()
    last_close = bars[-1].timestamp + timeframe_ms(TF)
    result = _validate(bars, decision=last_close + 2 * timeframe_ms(TF))
    assert result.validation_status == "STALE"
    assert any(issue["code"] == "STALE" for issue in result.issues)


def test_future_or_forming_bar_is_rejected() -> None:
    bars = _bars()
    result = _validate(bars, decision=bars[-1].timestamp + timeframe_ms(TF) - 1)
    assert result.validation_status == "FUTURE"
    assert any(issue["code"] == "FUTURE" for issue in result.issues)


def test_duplicate_timestamp_is_rejected_without_deduplication() -> None:
    bars = [*_bars(), _bars()[-1]]
    result = _validate(bars)
    assert result.validation_status == "DUPLICATE"
    assert any(issue["code"] == "DUPLICATE" for issue in result.issues)


def test_gap_is_rejected_without_interpolation() -> None:
    bars = _bars()
    result = _validate([bar for index, bar in enumerate(bars) if index != 60])
    assert result.validation_status == "GAP"
    assert any(issue["code"] == "GAP" for issue in result.issues)


def test_out_of_order_window_is_rejected() -> None:
    bars = _bars()
    bars[-1], bars[-2] = bars[-2], bars[-1]
    result = _validate(bars)
    assert result.validation_status == "OUT_OF_ORDER"
    assert any(issue["code"] == "OUT_OF_ORDER" for issue in result.issues)


def test_bad_ohlcv_is_rejected() -> None:
    bars = _bars()
    bars[-1] = replace(bars[-1], high=bars[-1].low - 1.0)
    result = _validate(bars)
    assert result.validation_status == "BAD_OHLCV"
    assert any(issue["code"] == "BAD_OHLCV" for issue in result.issues)


def test_short_window_is_incomplete() -> None:
    result = _validate(_bars(60))
    assert result.validation_status == "INCOMPLETE"
    assert any(issue["code"] == "INCOMPLETE" for issue in result.issues)
