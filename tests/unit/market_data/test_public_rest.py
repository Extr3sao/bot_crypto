"""G-7: public source and replay source are tested without network access."""

from __future__ import annotations

import asyncio

import pytest

from trading_bot.market_data.public_rest import (
    PublicDataError,
    PublicRestKlineSource,
    ReplayMarketDataSource,
    capture_from_source,
)
from trading_bot.market_data.real_data_validation import timeframe_ms

BASE = 1_792_900_000_000
TF = "5m"
TF_MS = timeframe_ms(TF)


def _raw(ts: int, close: float) -> list[float]:
    return [ts, close - 1, close + 1, close - 2, close, 10.0, ts + TF_MS - 1]


def test_public_source_asks_for_an_extra_row_and_drops_the_forming_candle() -> None:
    source = PublicRestKlineSource(timeframe=TF, clock=lambda: BASE + 3 * TF_MS)
    seen: dict[str, object] = {}

    def fake(path: str, params: dict[str, object] | None = None) -> object:
        seen["path"] = path
        seen["params"] = params
        return [
            _raw(BASE, 100.0),
            _raw(BASE + TF_MS, 101.0),
            _raw(BASE + 2 * TF_MS, 102.0),
            _raw(BASE + 3 * TF_MS, 103.0),  # forming at the pinned clock
        ]

    source._request_json = fake  # type: ignore[method-assign]
    bars = asyncio.run(source.fetch_recent("BTC/USDT", limit=2))

    assert seen["path"] == "/api/v3/klines"
    assert seen["params"]["limit"] == 3  # 2 closed + 1 for the forming row
    assert [bar.close for bar in bars] == [101.0, 102.0]
    assert all(bar.timestamp + TF_MS <= BASE + 3 * TF_MS for bar in bars)
    assert len(source.capture()["symbols"]["BTC/USDT"]["bars"]) == 3


def test_public_source_rejects_private_endpoints() -> None:
    source = PublicRestKlineSource(timeframe=TF)
    with pytest.raises(PublicDataError):
        source._request_json("/api/v3/order")


def test_public_source_quote_methods_use_public_payloads() -> None:
    source = PublicRestKlineSource(timeframe=TF, clock=lambda: BASE)

    def fake(path: str, params: dict[str, object] | None = None) -> object:
        if path == "/api/v3/ticker/24hr":
            return {"quoteVolume": "123456.5"}
        if path == "/api/v3/ticker/bookTicker":
            return {"bidPrice": "100.0", "askPrice": "100.1"}
        raise AssertionError(path)

    source._request_json = fake  # type: ignore[method-assign]
    assert asyncio.run(source.fetch_24h_volume_usdt("BTC/USDT")) == 123456.5
    spread = asyncio.run(source.fetch_spread_bps("BTC/USDT"))
    assert 9.0 < spread < 11.0


def test_public_source_has_no_order_surface() -> None:
    source = PublicRestKlineSource(timeframe=TF)
    assert not hasattr(source, "create_order")
    assert not hasattr(source, "place_order")
    assert not hasattr(source, "cancel_order")


def _capture(count: int = 130) -> dict[str, object]:
    bars = [
        [
            BASE + index * TF_MS,
            100.0 + index,
            101.0 + index,
            99.0 + index,
            100.5 + index,
            10.0,
        ]
        for index in range(count)
    ]
    return {
        "schema_version": "g7-public-capture/v1",
        "provider": "binance-public-rest",
        "timeframe": TF,
        "captured_at_ms": BASE + count * TF_MS + 1000,
        "symbols": {
            "BTC/USDT": {
                "bars": bars,
                "received_at_ms": BASE + count * TF_MS + 1000,
                "quote": {"volume_24h_usdt": 50_000_000.0, "spread_bps": 1.0},
            }
        },
    }


def test_replay_only_serves_bars_closed_at_decision() -> None:
    capture = _capture()
    decision = BASE + 130 * TF_MS
    source = ReplayMarketDataSource(capture, decision_time_ms=decision, timeframe=TF)
    bars = asyncio.run(source.fetch_recent("BTC/USDT", limit=1000))
    assert len(bars) == 130
    assert all(bar.timestamp + TF_MS <= decision for bar in bars)
    snapshots = source.snapshot_records(decision)
    assert snapshots[0]["validation_status"] == "OK"
    assert snapshots[0]["data_mode"] == "HISTORICAL_REPLAY"
    assert snapshots[0]["decision_time_ms"] == decision


def test_capture_round_trip_is_exactly_hashable() -> None:
    source = PublicRestKlineSource(timeframe=TF, clock=lambda: BASE + 2 * TF_MS)
    source._request_json = lambda *args, **kwargs: [  # type: ignore[method-assign]
        _raw(BASE, 100.0),
        _raw(BASE + TF_MS, 101.0),
        _raw(BASE + 2 * TF_MS, 102.0),
    ]
    asyncio.run(source.fetch_recent("BTC/USDT", limit=2))
    payload = capture_from_source(source)
    assert payload["provider"] == "binance-public-rest"
    assert payload["symbols"]["BTC/USDT"]["bars"][0][0] == BASE
