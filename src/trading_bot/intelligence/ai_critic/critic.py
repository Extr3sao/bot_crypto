"""critic — BOT-CRI-01: review one frozen proposal, fail closed, never touch the book.

The service is intentionally boring: authenticate the proposal, spend nothing when it can
already refuse, make at most one provider attempt, validate the answer against the schema
*and* the evidence ledger, seal it, and let the policy decide what (if anything) it may do.

Failure is always an ``ABSTAIN`` with a stable reason. A malformed answer never becomes an
``ACCEPT`` by default, a late answer never becomes an ``ACCEPT``, and an exception never
escapes into the caller's trading loop.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from trading_bot.intelligence.ai_critic.contracts import (
    PROMPT_ID,
    AgentMessage,
    CriticError,
    CriticReview,
    EvidenceLedger,
    EvidenceRef,
    FrozenTradeProposal,
    ReviewDecisionTrace,
    canonical_sha256,
    parse_review_payload,
    text_sha256,
)
from trading_bot.intelligence.ai_critic.policy import (
    CriticMode,
    GateDecision,
    decide,
)
from trading_bot.intelligence.ai_critic.prompt import CriticPrompt, build_critic_prompt
from trading_bot.intelligence.ai_critic.provider import (
    CriticProvider,
    CriticProviderError,
    CriticRequest,
    CriticResponse,
)
from trading_bot.intelligence.ai_critic.trace import CriticTraceWriter


class BudgetExceeded(CriticError):
    def __init__(self, limit: str) -> None:
        super().__init__("BUDGET_EXCEEDED", f"critic budget exhausted: {limit}")


@dataclass
class CriticBudget:
    """Per-run budget. Enforced before a call, so it can never be exceeded silently."""

    max_calls: int = 4
    max_spend_usd: float = 0.25
    calls: int = 0
    spend_usd: float = 0.0

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"max_calls={self.max_calls}")
        if self.spend_usd >= self.max_spend_usd:
            raise BudgetExceeded(f"max_spend_usd={self.max_spend_usd}")

    def consume(self, cost_usd: float) -> None:
        self.calls += 1
        self.spend_usd = round(self.spend_usd + float(cost_usd or 0.0), 8)


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    proposal: FrozenTradeProposal
    review: CriticReview
    gate: GateDecision
    trace: ReviewDecisionTrace
    prompt: CriticPrompt | None
    evidence: Mapping[str, EvidenceRef]
    provider_called: bool


def _review_id(proposal_sha: str, prompt_sha: str, reason: str) -> str:
    return "REV-" + canonical_sha256(
        {"proposal": proposal_sha, "prompt": prompt_sha, "reason": reason}
    )[:16]


@dataclass
class CriticService:
    """One critic per run. Reuse the instance so the budget is shared across proposals."""

    ledger: EvidenceLedger
    provider: CriticProvider
    traces: CriticTraceWriter | None = None
    mode: CriticMode = CriticMode.SHADOW_ONLY
    budget: CriticBudget = field(default_factory=CriticBudget)
    timeout_ms: int = 1500
    now_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000))
    gated_authorization: str | None = None

    # -- helpers ----------------------------------------------------------
    def _abstain(
        self,
        *,
        proposal: FrozenTradeProposal,
        reason: str,
        detail: str,
        prompt: CriticPrompt | None,
        responded_at_ms: int,
        provider: str,
        model_id: str,
        receipt_kind: str,
        receipt_id: str,
        cost_usd: float,
        provider_called: bool,
    ) -> CriticReview:
        prompt_sha = prompt.sha256 if prompt is not None else text_sha256("")
        latency = max(0, responded_at_ms - proposal.decision_time_ms)
        return CriticReview.seal(
            review_id=_review_id(proposal.frozen_sha256, prompt_sha, reason),
            proposal_id=proposal.proposal_id,
            proposal_sha256=proposal.frozen_sha256,
            verdict="ABSTAIN",
            confidence=0.0,
            rationale=f"{reason}: {detail}"[:1200],
            evidence_refs=tuple(),
            counter_evidence_refs=tuple(),
            abstain_reason=reason,  # validated against the literal vocabulary below
            decision_time_ms=proposal.decision_time_ms,
            responded_at_ms=responded_at_ms,
            latency_ms=latency,
            prompt_sha256=prompt_sha,
            provider=provider,
            model_id=model_id,
            provider_receipt_id=receipt_id,
            receipt_kind=receipt_kind,
            cost_usd=float(cost_usd or 0.0),
        )

    def _finish(
        self,
        *,
        proposal: FrozenTradeProposal,
        review: CriticReview,
        prompt: CriticPrompt | None,
        evidence: Mapping[str, EvidenceRef],
        provider_called: bool,
    ) -> ReviewOutcome:
        gate = decide(
            self.mode,
            proposal,
            review,
            authorization=self.gated_authorization,
        )
        trace = ReviewDecisionTrace(
            trace_id="TRC-" + review.review_id,
            run_id=proposal.run_id,
            mode=self.mode.value,
            proposal_id=proposal.proposal_id,
            proposal_sha256=proposal.frozen_sha256,
            review_id=review.review_id,
            review_sha256=review.review_sha256,
            verdict=review.verdict,
            gate_action=gate.action,
            gate_reason=gate.reason,
            economics_affected=gate.economics_affected,
            receipt_kind=review.receipt_kind,
            prompt_id=review.prompt_id,
            prompt_sha256=review.prompt_sha256,
            at_ms=review.responded_at_ms,
            cost_usd=review.cost_usd,
            latency_ms=review.latency_ms,
        )
        if self.traces is not None:
            self.traces.review(review)
            self.traces.decision(trace)
            self.traces.message(
                AgentMessage.seal(
                    message_id="MSG-PROP-" + proposal.frozen_sha256[:16],
                    run_id=proposal.run_id,
                    role="proposer",
                    proposal_sha256=proposal.frozen_sha256,
                    at_ms=proposal.decision_time_ms,
                    content=proposal.thesis,
                )
            )
            self.traces.message(
                AgentMessage.seal(
                    message_id="MSG-CRI-" + review.review_id,
                    run_id=proposal.run_id,
                    role="critic",
                    proposal_sha256=proposal.frozen_sha256,
                    at_ms=review.responded_at_ms,
                    content=review.rationale,
                )
            )
        return ReviewOutcome(
            proposal=proposal,
            review=review,
            gate=gate,
            trace=trace,
            prompt=prompt,
            evidence=evidence,
            provider_called=provider_called,
        )

    # -- main entry point -------------------------------------------------
    def review(self, proposal: FrozenTradeProposal) -> ReviewOutcome:
        provider_name = str(getattr(self.provider, "name", "unknown"))
        model_id = str(getattr(self.provider, "model_id", "unknown"))
        no_evidence: Mapping[str, EvidenceRef] = {}

        def refuse(reason: str, detail: str, *, prompt: CriticPrompt | None = None,
                   provider_called: bool = False, receipt_kind: str = "NONE",
                   receipt_id: str = "no-receipt", cost: float = 0.0) -> ReviewOutcome:
            now = self.now_ms()
            review = self._abstain(
                proposal=proposal,
                reason=reason,
                detail=detail,
                prompt=prompt,
                responded_at_ms=max(now, proposal.decision_time_ms),
                provider=provider_name,
                model_id=model_id,
                receipt_kind=receipt_kind,
                receipt_id=receipt_id,
                cost_usd=cost,
                provider_called=provider_called,
            )
            return self._finish(
                proposal=proposal,
                review=review,
                prompt=prompt,
                evidence=no_evidence,
                provider_called=provider_called,
            )

        # 1. The proposal must match the hash the proposer froze.
        try:
            proposal.validate_frozen()
        except CriticError as exc:
            return refuse(exc.code, exc.detail)

        # 2. Every evidence ref the proposal relies on must authenticate.
        try:
            evidence = self.ledger.resolve(proposal.evidence_refs)
        except CriticError as exc:
            # The proposal's own evidence is a precondition of reviewing it, and is named
            # differently from a model's invented citation further down.
            return refuse("EVIDENCE_UNRESOLVED", exc.detail)

        # 3. Build the prompt; its hash and injection flags are recorded either way.
        prompt = build_critic_prompt(proposal, evidence)
        started_at = max(self.now_ms(), proposal.decision_time_ms)

        # 4. A deadline that has already passed costs nothing.
        if started_at >= proposal.decision_time_ms + self.timeout_ms:
            return refuse(
                "LATE_RESPONSE",
                f"the review deadline ({self.timeout_ms} ms) passed before any call",
                prompt=prompt,
            )

        # 5. Untrusted text that tries to steer the reviewer is not sanitised into an
        #    opinion; it is recorded and abstained on.
        if prompt.injection_suspected:
            return refuse(
                "PROMPT_INJECTION_SUSPECTED",
                "untrusted text contains instruction-override patterns: "
                + ", ".join(prompt.injection_flags),
                prompt=prompt,
            )

        # 6. Budget is checked before spending, not after.
        try:
            self.budget.check()
        except BudgetExceeded as exc:
            return refuse("BUDGET_EXCEEDED", exc.detail, prompt=prompt)

        # 7. Exactly one provider attempt; no retry loop hides latency or cost.
        request = CriticRequest(
            prompt_system=prompt.system,
            prompt_user=prompt.user,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            proposal_sha256=proposal.frozen_sha256,
        )
        try:
            response: CriticResponse = self.provider.complete(request)
        except CriticProviderError as exc:
            self.budget.consume(0.0)
            if self.traces is not None:
                self.traces.invocation(
                    {
                        "invocation_id": f"CRI-{proposal.run_id}-{self.budget.calls:05d}",
                        "run_id": proposal.run_id,
                        "bot_id": "BOT-CRI-01",
                        "provider": provider_name,
                        "model_id": model_id,
                        "prompt_id": prompt.version,
                        "prompt_sha256": prompt.sha256,
                        "input_proposal_sha256": proposal.frozen_sha256,
                        "receipt_kind": "NONE",
                        "provider_receipt_id": "no-receipt",
                        "model_status": exc.code,
                        "error_class": type(exc).__name__,
                        "provider_cost_usd": 0.0,
                        "latency_ms": max(0, self.now_ms() - proposal.decision_time_ms),
                    }
                )
            return refuse(
                "PROVIDER_ERROR",
                f"{exc.code}: {exc.detail}",
                prompt=prompt,
                provider_called=True,
            )
        self.budget.consume(response.cost_usd)
        responded_at = self.now_ms()
        wall_latency = max(0, responded_at - proposal.decision_time_ms)
        if self.traces is not None:
            self.traces.invocation(
                {
                    "invocation_id": f"CRI-{proposal.run_id}-{self.budget.calls:05d}",
                    "run_id": proposal.run_id,
                    "bot_id": "BOT-CRI-01",
                    "provider": response.provider,
                    "model_id": response.model_id,
                    "prompt_id": prompt.version,
                    "prompt_sha256": prompt.sha256,
                    "input_proposal_sha256": proposal.frozen_sha256,
                    "receipt_kind": response.receipt_kind,
                    "provider_receipt_id": response.receipt_id,
                    "model_status": "OK",
                    "error_class": None,
                    "provider_cost_usd": float(response.cost_usd or 0.0),
                    "latency_ms": int(max(wall_latency, response.latency_ms)),
                    "response_sha256": response.response_sha256,
                }
            )

        # 8. A late answer is not an opinion about a still-open opportunity.
        if response.latency_ms > self.timeout_ms or wall_latency > self.timeout_ms:
            return refuse(
                "LATE_RESPONSE",
                f"provider latency {response.latency_ms} ms / wall {wall_latency} ms "
                f"exceeds the {self.timeout_ms} ms deadline",
                prompt=prompt,
                provider_called=True,
                receipt_kind=response.receipt_kind,
                receipt_id=response.receipt_id,
                cost=response.cost_usd,
            )

        # 9. Strict JSON: fences, prose and non-objects are refusals, not salvage jobs.
        text = response.text.strip()
        if not text.startswith("{"):
            return refuse("INVALID_JSON", "the answer is not a JSON object",
                          prompt=prompt, provider_called=True,
                          receipt_kind=response.receipt_kind,
                          receipt_id=response.receipt_id, cost=response.cost_usd)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return refuse("INVALID_JSON", f"{type(exc).__name__}: {exc}",
                          prompt=prompt, provider_called=True,
                          receipt_kind=response.receipt_kind,
                          receipt_id=response.receipt_id, cost=response.cost_usd)
        if not isinstance(payload, dict):
            return refuse("INVALID_JSON", "the answer is not a JSON object",
                          prompt=prompt, provider_called=True,
                          receipt_kind=response.receipt_kind,
                          receipt_id=response.receipt_id, cost=response.cost_usd)

        # 10. Schema, evidence resolution and verdict consistency.
        service_fields: dict[str, Any] = {
            "review_id": _review_id(proposal.frozen_sha256, prompt.sha256, "model"),
            "proposal_id": proposal.proposal_id,
            "proposal_sha256": proposal.frozen_sha256,
            "decision_time_ms": proposal.decision_time_ms,
            "responded_at_ms": responded_at,
            "latency_ms": wall_latency,
            "prompt_sha256": prompt.sha256,
            "provider": response.provider,
            "model_id": response.model_id,
            "provider_receipt_id": response.receipt_id,
            "receipt_kind": response.receipt_kind,
            "cost_usd": float(response.cost_usd or 0.0),
        }
        try:
            review = parse_review_payload(payload, ledger=self.ledger,
                                          service_fields=service_fields)
        except CriticError as exc:
            reason = exc.code
            if reason == "SCHEMA_VALIDATION":
                reason = "SCHEMA_INVALID"
            # A verdict that cites its own support as contradiction is a contradiction;
            # merely *missing* counter-evidence stays a schema failure.
            if "not also its support" in exc.detail or "ACCEPT cannot cite" in exc.detail:
                reason = "CONTRADICTION"
            if reason not in _ABSTAIN_REASONS:
                reason = "SCHEMA_INVALID"
            return refuse(reason, exc.detail, prompt=prompt, provider_called=True,
                          receipt_kind=response.receipt_kind,
                          receipt_id=response.receipt_id, cost=response.cost_usd)

        return self._finish(
            proposal=proposal,
            review=review,
            prompt=prompt,
            evidence=evidence,
            provider_called=True,
        )


_ABSTAIN_REASONS = frozenset(
    {
        "INSUFFICIENT_EVIDENCE",
        "LATE_RESPONSE",
        "BUDGET_EXCEEDED",
        "PROVIDER_ERROR",
        "INVALID_JSON",
        "SCHEMA_INVALID",
        "SCHEMA_FORBIDDEN_FIELD",
        "UNRESOLVED_EVIDENCE_REFERENCE",
        "CONTRADICTION",
        "PROMPT_INJECTION_SUSPECTED",
        "PROPOSAL_TAMPERED",
        "EVIDENCE_UNRESOLVED",
    }
)

__all__ = [
    "PROMPT_ID",
    "BudgetExceeded",
    "CriticBudget",
    "CriticService",
    "ReviewOutcome",
]
