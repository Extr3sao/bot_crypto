"""CONTRACT — the transport maps a real Binance payload into the source protocol."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from trading_bot.market_data.minute_collector import (
    MINUTE_MS,
    BinanceRestSource,
    SourceUnavailable,
)

T0 = 1_700_000_000_000 - (1_700_000_000_000 % MINUTE_MS)


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def urlopen_with(payload: object, *, status: int = 200):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def _open(request, timeout=None):
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(body, status=status)

    return _open


def test_a_real_kline_page_is_parsed_with_the_exchange_clock(monkeypatch) -> None:
    klines = [
        [T0, "100.0", "101.0", "99.0", "100.5", "12.3", T0 + MINUTE_MS - 1, "0", 5, "0", "0", "0"],
        [T0 + MINUTE_MS, "100.5", "102.0", "100.0", "101.5", "9.9", T0 + 2 * MINUTE_MS - 1, "0", 5, "0", "0", "0"],
    ]
    calls: list[str] = []

    def _open(request, timeout=None):
        calls.append(request.full_url)
        if "/api/v3/time" in request.full_url:
            return FakeResponse(json.dumps({"serverTime": T0 + 3 * MINUTE_MS}).encode())
        return FakeResponse(json.dumps(klines).encode())

    monkeypatch.setattr("urllib.request.urlopen", _open)
    page = BinanceRestSource().fetch("BTCUSDT", limit=2)
    assert page.symbol == "BTCUSDT"
    assert page.server_time_ms == T0 + 3 * MINUTE_MS
    assert page.received_at_ms > 0
    assert len(page.rows) == 2
    assert page.rows[0][0] == T0
    assert any("/api/v3/klines" in url for url in calls)
    assert any("/api/v3/time" in url for url in calls)


def test_the_request_is_public_and_carries_no_credential() -> None:
    captured: dict[str, str] = {}

    def _open(request, timeout=None):
        captured.update(dict(request.header_items()))
        return FakeResponse(json.dumps({"serverTime": T0}).encode())

    import urllib.request

    original = urllib.request.urlopen
    urllib.request.urlopen = _open
    try:
        BinanceRestSource(user_agent="trading-agentic-portable/1.0").server_time()
    finally:
        urllib.request.urlopen = original
    header_names = {name.lower() for name in captured}
    assert "x-mbx-apikey" not in header_names
    assert "authorization" not in header_names
    assert captured.get("User-agent") == "trading-agentic-portable/1.0"


def test_a_rate_limit_is_a_disconnect_not_an_empty_page(monkeypatch) -> None:
    def _raise(request, timeout=None):
        raise urllib.error.HTTPError(
            url=request.full_url, code=429, msg="Too Many Requests", hdrs=None, fp=io.BytesIO()
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    with pytest.raises(SourceUnavailable) as raised:
        BinanceRestSource().server_time()
    assert raised.value.code == "HTTP_429"


def test_unparsable_json_is_a_disconnect(monkeypatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", urlopen_with(b"<html>nope</html>"))
    with pytest.raises(SourceUnavailable) as raised:
        BinanceRestSource().server_time()
    assert raised.value.code == "BAD_JSON"


def test_the_exchange_clock_is_required(monkeypatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", urlopen_with({"serverTime": None}))
    with pytest.raises(SourceUnavailable):
        BinanceRestSource().server_time()
