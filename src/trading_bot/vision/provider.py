"""provider — one multimodal call, with the image actually in the request.

The adapter speaks the OpenAI-compatible chat-completions dialect, which is what
OpenAI, Groq, OpenRouter, DeepSeek, Together and local LM Studio/Ollama servers all
expose. That is deliberate: the provider is a deployment choice, not an architecture
choice, and switching one must not change how a decision is validated or recorded.

What this module refuses to do:

* invent a decision when the call fails — a transport error is a failed decision, and
  the lane records it as one, never as ``NO_TRADE`` dressed up as a model opinion;
* retry an authentication error — a wrong key retried three times is still a wrong key,
  and the reason must say so;
* echo the key. Error strings are redacted and tested for it.

Evidence, not vibes: every response keeps the provider's request id, the model it says
it served, the token usage, the measured latency and an estimated cost, and the request
keeps the SHA-256 of the exact image bytes. ``image_sha256_in_request`` is what turns
"the model probably saw the chart" into a checkable statement.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from trading_bot.vision.chart import ChartImage
from trading_bot.vision.prompt import PromptBundle

#: Default: the smallest multimodal model that is good enough to read a chart. Overridable.
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_ATTEMPTS = 3

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    """A call that did not produce a usable answer. Never swallowed by the lane."""

    def __init__(self, code: str, detail: str, *, attempts: int = 0) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.attempts = attempts


class MissingCredentialError(ProviderError):
    """No credential is configured. The run is BLOCKED, not failed and not passing."""


@dataclass(frozen=True, slots=True)
class VisionRequest:
    """Everything a provider needs, plus what the ledger will need afterwards."""

    chart: ChartImage
    prompt: PromptBundle
    decision_ts_ms: int
    temperature: float = 0.0
    max_output_tokens: int = 400
    detail: str = "high"

    @property
    def image_sha256(self) -> str:
        return self.chart.sha256

    def redacted_summary(self) -> dict[str, Any]:
        return {
            "image_sha256": self.chart.sha256,
            "image_bytes": self.chart.byte_length,
            "prompt_sha256": self.prompt.sha256,
            "prompt_version": self.prompt.version,
            "decision_ts_ms": self.decision_ts_ms,
            "temperature": self.temperature,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class VisionResponse:
    text: str
    model: str
    provider: str
    request_id: str
    latency_ms: int
    attempts: int
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    #: Hash of the bytes this call actually attached. The live adapter fills it from the
    #: request it built, so the ledger can compare it against the chart on disk.
    image_sha256_in_request: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "usage": self.usage,
            "cost_usd": self.cost_usd,
            "image_sha256_in_request": self.image_sha256_in_request,
            "response_chars": len(self.text),
        }


class VisionProvider(Protocol):
    name: str

    def analyze(self, request: VisionRequest) -> VisionResponse: ...


@dataclass(frozen=True, slots=True)
class PriceTable:
    """Published per-million-token prices, used only to *estimate* spend."""

    input_usd_per_mtok: float = 0.15
    output_usd_per_mtok: float = 0.60
    #: A 800x500 image at detail=high is billed as roughly this many input tokens.
    image_tokens_estimate: int = 1_000

    def estimate(self, *, prompt_tokens: int, completion_tokens: int) -> float:
        billed_input = max(prompt_tokens, self.image_tokens_estimate)
        return (
            billed_input / 1_000_000.0 * self.input_usd_per_mtok
            + completion_tokens / 1_000_000.0 * self.output_usd_per_mtok
        )


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***REDACTED***")
    return text


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


class OpenAICompatibleVisionProvider:
    """The live adapter. Requires a credential; fails loudly without one."""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        prices: PriceTable | None = None,
        supports_json_object: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_attempts = max(1, int(max_attempts))
        self._prices = prices or PriceTable()
        self._supports_json_object = supports_json_object
        self._sleep = sleep
        self._transport = transport

    # -- request construction ------------------------------------------------

    def build_payload(self, request: VisionRequest) -> dict[str, Any]:
        """The exact JSON body, including the base64 image. Public for tests."""
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.prompt.system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.prompt.user},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _data_uri(request.chart.png),
                                "detail": request.detail,
                            },
                        },
                    ],
                },
            ],
        }
        if self._supports_json_object:
            payload["response_format"] = {"type": "json_object"}
        return payload

    # -- the call ------------------------------------------------------------

    def analyze(self, request: VisionRequest) -> VisionResponse:
        if not self._api_key:
            raise MissingCredentialError(
                "MISSING_CREDENTIAL",
                "no VISION_API_KEY (or provider key) configured; the multimodal call "
                "cannot be made and no decision may be invented in its place",
            )

        payload = self.build_payload(request)
        # Hash what the request will actually carry, not what the caller thinks it carries.
        attached = payload["messages"][1]["content"][1]["image_url"]["url"].split(",", 1)[1]
        attached_sha = hashlib.sha256(base64.b64decode(attached)).hexdigest()
        if attached_sha != request.chart.sha256:
            raise ProviderError(
                "IMAGE_MISMATCH", "the bytes in the request are not the chart's bytes"
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        last_error = "unknown"
        started = time.perf_counter()

        for attempt in range(1, self._max_attempts + 1):
            try:
                with httpx.Client(timeout=self._timeout_s, transport=self._transport) as client:
                    response = client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = _redact(f"{type(exc).__name__}: {exc}", self._api_key)
                if attempt < self._max_attempts:
                    self._sleep(min(2.0 ** (attempt - 1), 8.0))
                    continue
                raise ProviderError(
                    "TRANSPORT_ERROR", last_error, attempts=attempt
                ) from exc

            if response.status_code in (401, 403):
                raise ProviderError(
                    "AUTH_ERROR",
                    _redact(f"HTTP {response.status_code}: {response.text[:300]}", self._api_key),
                    attempts=attempt,
                )
            if response.status_code in _RETRYABLE_STATUS and attempt < self._max_attempts:
                last_error = _redact(
                    f"HTTP {response.status_code}: {response.text[:300]}", self._api_key
                )
                self._sleep(min(2.0 ** (attempt - 1), 8.0))
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    "HTTP_ERROR",
                    _redact(f"HTTP {response.status_code}: {response.text[:300]}", self._api_key),
                    attempts=attempt,
                )

            try:
                body = response.json()
                text = body["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ProviderError(
                    "MALFORMED_ENVELOPE",
                    f"provider response lacks choices[0].message.content: {exc}",
                    attempts=attempt,
                ) from exc
            if not isinstance(text, str) or not text.strip():
                raise ProviderError(
                    "EMPTY_CONTENT", "provider returned an empty message", attempts=attempt
                )

            usage = {
                key: int(value)
                for key, value in (body.get("usage") or {}).items()
                if isinstance(value, int)
            }
            completion_tokens = int(usage.get("completion_tokens", 0))
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            latency_ms = int((time.perf_counter() - started) * 1000)
            return VisionResponse(
                text=text,
                model=str(body.get("model") or self._model),
                provider=self.name,
                request_id=str(body.get("id") or f"{self._model}-{request.decision_ts_ms}"),
                latency_ms=latency_ms,
                attempts=attempt,
                usage=usage,
                cost_usd=self._prices.estimate(
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
                ),
                raw=body,
                image_sha256_in_request=attached_sha,
            )

        raise ProviderError("EXHAUSTED", last_error, attempts=self._max_attempts)


class FixtureProvider:
    """Answers recorded from a real run, keyed by the image they were given.

    Keyed by image SHA-256, not by order: a replay that reads answer *n* for chart *n*
    would silently answer the wrong chart as soon as one decision is added or skipped.
    A chart with no recorded answer is a ``REPLAY_MISSING`` failure, never a guess.
    """

    name = "replay-fixtures"

    def __init__(self, answers_by_image: dict[str, str]) -> None:
        self._answers = dict(answers_by_image)
        self._calls: list[VisionRequest] = []

    @property
    def calls(self) -> list[VisionRequest]:
        return list(self._calls)

    def analyze(self, request: VisionRequest) -> VisionResponse:
        self._calls.append(request)
        text = self._answers.get(request.chart.sha256)
        if text is None:
            raise ProviderError(
                "REPLAY_MISSING",
                f"no recorded answer for image {request.chart.sha256[:16]}; "
                "a replay cannot invent one",
            )
        return VisionResponse(
            text=text,
            model="recorded",
            provider=self.name,
            request_id=f"fixture-{request.chart.sha256[:16]}",
            latency_ms=0,
            attempts=1,
            usage={},
            cost_usd=0.0,
            raw={"fixture": True},
            image_sha256_in_request=request.chart.sha256,
        )


class ReplayProvider:
    """Deterministic stand-in: fixed answers, same evidence shape.

    This is what unit tests and the offline comparison use. It is *not* a model: the
    ledger records ``provider="replay"`` so a replayed decision can never be mistaken
    for a live one.
    """

    name = "replay"

    def __init__(self, answers: list[str] | Callable[[VisionRequest], str]) -> None:
        self._answers = answers
        self._calls: list[VisionRequest] = []

    @property
    def calls(self) -> list[VisionRequest]:
        return list(self._calls)

    def analyze(self, request: VisionRequest) -> VisionResponse:
        self._calls.append(request)
        if callable(self._answers):
            text = self._answers(request)
        else:
            if not self._answers:
                raise ProviderError("REPLAY_EXHAUSTED", "no scripted answer left")
            text = self._answers.pop(0)
        return VisionResponse(
            text=text,
            model="replay",
            provider=self.name,
            request_id=f"replay-{len(self._calls)}",
            latency_ms=0,
            attempts=1,
            usage={},
            cost_usd=0.0,
            raw={"replay": True},
            image_sha256_in_request=request.chart.sha256,
        )


def response_fixture(response: VisionResponse) -> dict[str, Any]:
    """A recorded answer, compact enough to commit and complete enough to replay."""
    return {
        "text": response.text,
        "model": response.model,
        "provider": response.provider,
        "request_id": response.request_id,
        "usage": response.usage,
        "cost_usd": response.cost_usd,
        "image_sha256_in_request": response.image_sha256_in_request,
    }


def load_fixture_answers(path: Any) -> dict[str, str]:
    """Map ``image_sha256`` -> answer, so a replay is keyed by the image, not by order."""
    import pathlib

    rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {row["image_sha256"]: row["text"] for row in rows if row.get("text")}
