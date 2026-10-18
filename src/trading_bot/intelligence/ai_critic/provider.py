"""provider — the critic's transport, and the receipts it must leave.

The runtime never calls a paid model by accident: the service only knows this protocol,
and every response carries a ``receipt_kind`` (``REAL``, ``MOCK``, ``REPLAY``). A mock
answer can therefore never be counted as a real model call in a report.

``ReplayCriticProvider`` replays recorded answers; ``ScriptedCriticProvider`` is the same
class with an explicit ``MOCK`` receipt. Neither imports a provider SDK, so importing the
critic package does not require an API key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from trading_bot.intelligence.ai_critic.contracts import ReceiptKind, text_sha256


@dataclass(frozen=True, slots=True)
class CriticRequest:
    prompt_system: str
    prompt_user: str
    prompt_version: str
    prompt_sha256: str
    proposal_sha256: str


@dataclass(frozen=True, slots=True)
class CriticResponse:
    text: str
    provider: str
    model_id: str
    receipt_id: str
    receipt_kind: ReceiptKind
    latency_ms: int
    cost_usd: float = 0.0

    @property
    def response_sha256(self) -> str:
        return text_sha256(self.text)


class CriticProviderError(Exception):
    """A transport failure with a stable code; the service turns it into ABSTAIN."""

    def __init__(self, code: str, detail: str, attempts: int = 1) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.attempts = attempts


class CriticProvider(Protocol):
    name: str
    model_id: str

    def complete(self, request: CriticRequest) -> CriticResponse: ...


@dataclass
class ScriptedCriticProvider:
    """Deterministic answers for tests and the ablation. Never a real model call."""

    answers: Sequence[str | Exception]
    name: str = "scripted-critic"
    model_id: str = "STUB-CRITIC-004"
    receipt_kind: ReceiptKind = "MOCK"
    latency_ms: int = 5
    cost_usd: float = 0.0
    calls: int = 0
    prompts: list[str] = field(default_factory=list)

    def complete(self, request: CriticRequest) -> CriticResponse:
        self.prompts.append(request.prompt_user)
        index = self.calls
        self.calls += 1
        if index >= len(self.answers):
            raise CriticProviderError(
                "PROVIDER_EXHAUSTED",
                f"{self.name} has no answer for call {index + 1}",
                attempts=1,
            )
        answer = self.answers[index]
        if isinstance(answer, Exception):
            if isinstance(answer, CriticProviderError):
                raise answer
            raise CriticProviderError(type(answer).__name__, str(answer), attempts=1) from answer
        return CriticResponse(
            text=answer,
            provider=self.name,
            model_id=self.model_id,
            # Deterministic per (proposal, answer): a replay of the same exchange must
            # yield the same sealed review, not just the same verdict.
            receipt_id=(
                f"{self.name}-{request.proposal_sha256[:12]}-"
                f"{text_sha256(answer)[:12]}"
            ),
            receipt_kind=self.receipt_kind,
            latency_ms=self.latency_ms,
            cost_usd=self.cost_usd,
        )


def ReplayCriticProvider(
    answers: Sequence[str | Exception],
    *,
    name: str = "replay-critic",
    model_id: str = "REPLAY-CRITIC-004",
    latency_ms: int = 5,
    cost_usd: float = 0.0,
) -> ScriptedCriticProvider:
    """A provider that replays recorded answers, labelled ``REPLAY``."""
    return ScriptedCriticProvider(
        answers=answers,
        name=name,
        model_id=model_id,
        receipt_kind="REPLAY",
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
