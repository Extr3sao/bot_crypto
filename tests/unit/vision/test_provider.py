"""Provider tests answer one question: is the image really in the request, and does a
failure stay a failure?

The HTTP layer is faked with ``httpx.MockTransport``; the payload is built by the real
code, so the assertion "the base64 you are about to send hashes to the chart's SHA-256"
is a statement about production bytes.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.chart import render_chart_png
from trading_bot.vision.prompt import build_prompt
from trading_bot.vision.provider import (
    MissingCredentialError,
    OpenAICompatibleVisionProvider,
    PriceTable,
    ProviderError,
    ReplayProvider,
    VisionRequest,
)

API_KEY = "sk-test-not-a-real-key"


def bars(count: int = 40) -> list[Bar]:
    out: list[Bar] = []
    price = 100.0
    for i in range(count):
        close = price * 1.002
        out.append(
            Bar(
                ts_ms=1_770_000_000_000 + i * 3_600_000,
                open=price,
                high=max(price, close) * 1.001,
                low=min(price, close) * 0.999,
                close=close,
                volume=120.0 + i,
            )
        )
        price = close
    return out


def request_for(answer_context: str = "LONG") -> VisionRequest:
    chart = render_chart_png(bars(), symbol="BTC/USDT")
    prompt = build_prompt(
        {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "window_bars": chart.bar_count,
            "last_close": 101.0,
            "equity": 10_000.0,
            "open_positions": 0,
            "max_open_positions": 3,
            "risk_per_trade_pct": 0.25,
            "max_weekly_loss_pct": 3.0,
            "position": None,
        }
    )
    return VisionRequest(chart=chart, prompt=prompt, decision_ts_ms=1_770_000_100_000)


def ok_body(text: str = '{"action":"LONG"}') -> dict:
    return {
        "id": "chatcmpl-abc123",
        "model": "gpt-4o-mini-2024-07-18",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1_234, "completion_tokens": 87, "total_tokens": 1_321},
    }


def provider(handler, **kwargs) -> OpenAICompatibleVisionProvider:
    kwargs.setdefault("api_key", API_KEY)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return OpenAICompatibleVisionProvider(transport=httpx.MockTransport(handler), **kwargs)


def test_without_a_credential_no_request_is_made():
    def explode(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("the adapter must not call out without a key")

    adapter = provider(explode, api_key=None)

    with pytest.raises(MissingCredentialError) as caught:
        adapter.analyze(request_for())

    assert caught.value.code == "MISSING_CREDENTIAL"


def test_the_payload_carries_the_exact_chart_bytes():
    request = request_for()
    captured: dict = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(http_request.content)
        captured["auth"] = http_request.headers.get("authorization")
        return httpx.Response(200, json=ok_body())

    response = provider(handler).analyze(request)

    image_url = captured["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    sent = base64.b64decode(image_url.split(",", 1)[1])
    assert sent == request.chart.png
    assert response.image_sha256_in_request == request.chart.sha256
    assert captured["auth"] == f"Bearer {API_KEY}"
    assert captured["body"]["messages"][1]["content"][1]["image_url"]["detail"] == "high"


def test_the_prompt_and_the_image_are_both_in_the_request():
    captured: dict = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(http_request.content)
        return httpx.Response(200, json=ok_body())

    request = request_for()
    provider(handler).analyze(request)

    body = captured["body"]
    assert body["messages"][0]["role"] == "system"
    assert "JSON" in body["messages"][0]["content"]
    assert body["messages"][1]["content"][0]["text"] == request.prompt.user
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "gpt-4o-mini"


def test_a_valid_answer_returns_usage_ids_and_an_estimated_cost():
    """The image is billed even when the provider reports fewer prompt tokens.

    A 1152x720 chart is ~6 tiles, so a call reporting 1 234 prompt tokens still pays for
    the declared image estimate; under-counting it would understate the cost of the run.
    """
    from trading_bot.vision.settings import load_vision_config

    request = request_for()
    response = provider(lambda _r: httpx.Response(200, json=ok_body())).analyze(request)

    assert response.model == "gpt-4o-mini-2024-07-18"
    assert response.request_id == "chatcmpl-abc123"
    assert response.usage["prompt_tokens"] == 1_234
    declared_tokens = load_vision_config(env={}).provider.prices.image_tokens_estimate
    assert declared_tokens == 1_400, "the declared image cost must track the chart spec"
    assert declared_tokens > response.usage["prompt_tokens"]
    expected = declared_tokens / 1_000_000 * 0.15 + 87 / 1_000_000 * 0.60
    assert response.cost_usd == pytest.approx(expected)
    assert response.attempts == 1


def test_a_bad_key_fails_immediately_and_never_leaks_the_key():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text=f"invalid api key {API_KEY}")

    adapter = provider(handler)

    with pytest.raises(ProviderError) as caught:
        adapter.analyze(request_for())

    assert caught.value.code == "AUTH_ERROR"
    assert calls["n"] == 1, "an authentication failure must not be retried"
    assert API_KEY not in str(caught.value)
    assert "***REDACTED***" in str(caught.value)


def test_transient_failures_are_retried_and_the_attempt_count_is_recorded():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, json=ok_body())

    response = provider(handler, max_attempts=3).analyze(request_for())

    assert calls["n"] == 3
    assert response.attempts == 3


def test_persistent_failure_raises_instead_of_returning_an_empty_decision():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    with pytest.raises(ProviderError) as caught:
        provider(handler, max_attempts=2).analyze(request_for())

    assert caught.value.code in {"EXHAUSTED", "HTTP_ERROR"}
    assert calls["n"] == 2


def test_a_malformed_envelope_is_reported_as_such():
    with pytest.raises(ProviderError) as caught:
        provider(lambda _r: httpx.Response(200, json={"id": "x"})).analyze(request_for())

    assert caught.value.code == "MALFORMED_ENVELOPE"


def test_an_empty_message_is_not_turned_into_a_no_trade():
    with pytest.raises(ProviderError) as caught:
        provider(lambda _r: httpx.Response(200, json=ok_body("   "))).analyze(request_for())

    assert caught.value.code == "EMPTY_CONTENT"


def test_a_transport_error_is_wrapped_without_the_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach host while using {API_KEY}")

    with pytest.raises(ProviderError) as caught:
        provider(handler, max_attempts=1).analyze(request_for())

    assert caught.value.code == "TRANSPORT_ERROR"
    assert API_KEY not in str(caught.value)


def test_the_price_table_bills_at_least_the_image_tokens():
    table = PriceTable(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0, image_tokens_estimate=1_000)

    cost = table.estimate(prompt_tokens=50, completion_tokens=100)

    assert cost == pytest.approx(1_000 / 1_000_000 * 1.0 + 100 / 1_000_000 * 2.0)


def test_the_replay_provider_records_every_request_it_was_given():
    scripted = ReplayProvider(['{"action":"NO_TRADE"}', '{"action":"LONG"}'])
    request = request_for()

    scripted.analyze(request)
    scripted.analyze(request)

    assert len(scripted.calls) == 2
    assert scripted.calls[0].chart.sha256 == request.chart.sha256
