"""contracts — what a critic may say, and what it may never touch.

``FrozenTradeProposal``  the proposer's decision, hashed before the critic sees it. A
                         review that names a different hash is reviewing a different
                         proposal, and is refused.
``EvidenceRef`` / ``EvidenceLedger``
                         authenticated facts a citation may point at. A model citation
                         is an id, never a digest it wrote itself: the digest comes from
                         the ledger, so a hallucinated id has nothing to resolve to.
``CriticReview``         ACCEPT / CHALLENGE / ABSTAIN with evidence and counter-evidence.
                         No size, no leverage, no stop, no order, no direction change:
                         those fields do not exist here, and ``extra="forbid"`` turns an
                         attempt to add them into a schema failure instead of a silent
                         grant.
``AgentMessage``         the hash-only record of one turn in the exchange.
``ReviewDecisionTrace``  what the gate did with the review, and whether the economy was
                         touched (it never is, in SHADOW_ONLY).

The reviewer is an *epistemic* critic: it argues about whether the thesis is supported by
the evidence it was given. It is not the code verifier of this repository, which is a
separate program that never imports this package.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

REVIEW_SCHEMA_VERSION: Final = "TAP_CRITIC_REVIEW_V1"
PROPOSAL_SCHEMA_VERSION: Final = "TAP_FROZEN_PROPOSAL_V1"
PROMPT_ID: Final = "TAP-PROMPT-CRI-001/v1"

Verdict = Literal["ACCEPT", "CHALLENGE", "ABSTAIN"]
ReceiptKind = Literal["REAL", "MOCK", "REPLAY", "NONE"]
AbstainReason = Literal[
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
]
ChallengeKind = Literal[
    "UNSUPPORTED_THESIS",
    "CONTRADICTED_EVIDENCE",
    "STALE_EVIDENCE",
    "MISSING_INVALIDATION",
]

#: Keys a critic model may never set. They are refused by name with a stable code so a
#: prompt injection that tries to seize sizing is visible in the trace.
FORBIDDEN_REVIEW_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "action",
        "amount",
        "direction",
        "execute",
        "gate",
        "leverage",
        "margin",
        "notional",
        "notional_usdt",
        "order",
        "order_type",
        "override_gate",
        "position_size",
        "price",
        "quantity",
        "qty",
        "risk_pct",
        "side",
        "size",
        "size_usdt",
        "stop",
        "stop_loss",
        "stop_loss_pct",
        "take_profit",
        "take_profit_pct",
        "target",
    }
)

#: Intents that close, reduce or protect a position. A critic never blocks these.
PROTECTIVE_INTENTS: Final[frozenset[str]] = frozenset(
    {"CLOSE", "REDUCE", "STOP", "TAKE_PROFIT", "EXIT"}
)

_ASSET_RE = re.compile(r"^[A-Z0-9]{2,12}/[A-Z0-9]{2,12}$")
_REF_RE = re.compile(r"^[a-z][a-z0-9_]*:[A-Za-z0-9._:-]{1,96}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CriticError(ValueError):
    """A refusal with a stable ``code`` so counts are comparable across runs."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class EvidenceRef(BaseModel):
    """An authenticated fact. The digest is computed by the producer, not the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref_id: str
    kind: Literal[
        "bar", "indicator", "report", "orderbook", "position", "account",
        "news", "calendar", "chart", "decision", "context",
    ]
    sha256: str
    summary: str = Field(min_length=1, max_length=240)
    source: str = Field(min_length=1, max_length=160)

    @field_validator("ref_id")
    @classmethod
    def _ref_shape(cls, value: str) -> str:
        if not _REF_RE.match(value):
            raise ValueError(f"ref_id must look like 'kind:identifier', got {value!r}")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha_shape(cls, value: str) -> str:
        if not _SHA_RE.match(value):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value


class EvidenceLedger(BaseModel):
    """The authenticated evidence a review may cite."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[EvidenceRef, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> EvidenceLedger:
        ids = [item.ref_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence ref_id in ledger")
        return self

    def by_id(self) -> dict[str, EvidenceRef]:
        return {item.ref_id: item for item in self.items}

    def resolve(self, refs: Iterable[str]) -> dict[str, EvidenceRef]:
        known = self.by_id()
        missing = sorted(ref for ref in refs if ref not in known)
        if missing:
            raise CriticError(
                "UNRESOLVED_EVIDENCE_REFERENCE",
                "the review cites evidence that is not in the authenticated ledger: "
                + ", ".join(missing),
            )
        return {ref: known[ref] for ref in refs}

    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class FrozenTradeProposal(BaseModel):
    """The proposer's decision, frozen before review.

    ``frozen_sha256`` covers every other field. ``freeze`` is the only constructor that
    should be used by a proposer; ``validate_frozen`` is what the critic calls.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["TAP_FROZEN_PROPOSAL_V1"] = "TAP_FROZEN_PROPOSAL_V1"
    proposal_id: str = Field(min_length=1, max_length=80)
    bot_id: str = Field(min_length=1, max_length=40)
    run_id: str = Field(min_length=1, max_length=80)
    asset: str
    side: Literal["buy", "sell", "close"]
    intent: Literal["OPEN", "CLOSE", "REDUCE", "STOP", "TAKE_PROFIT", "REVERSE"]
    confidence: float = Field(ge=0.0, le=1.0)
    timeframe: str = Field(min_length=1, max_length=12)
    decision_time_ms: int = Field(ge=0)
    horizon_bars: int = Field(ge=1, le=168)
    thesis: str = Field(min_length=1, max_length=600)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=12)
    opinion_digest: str
    frozen_sha256: str

    @field_validator("asset")
    @classmethod
    def _asset_shape(cls, value: str) -> str:
        text = str(value or "").strip().upper()
        if not _ASSET_RE.match(text):
            raise ValueError(f"asset must look like BTC/USDT, got {value!r}")
        return text

    @field_validator("opinion_digest", "frozen_sha256")
    @classmethod
    def _hash_shape(cls, value: str) -> str:
        if not _SHA_RE.match(value):
            raise ValueError("digest must be 64 lowercase hex characters")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _refs_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            if not _REF_RE.match(ref):
                raise ValueError(f"evidence ref must look like 'kind:identifier', got {ref!r}")
        return value

    @model_validator(mode="after")
    def _side_matches_intent(self) -> FrozenTradeProposal:
        if self.intent == "OPEN" and self.side == "close":
            raise ValueError("an OPEN intent cannot have side='close'")
        if self.intent in PROTECTIVE_INTENTS and self.side != "close":
            raise ValueError(f"{self.intent} must be a closing intent")
        return self

    def _hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("frozen_sha256", None)
        return payload

    @classmethod
    def freeze(cls, **payload: Any) -> FrozenTradeProposal:
        # Build the object first so defaults are part of the hash, then seal it. Hashing
        # the raw keyword arguments would let a default change the digest silently.
        draft = cls(**payload, frozen_sha256="0" * 64)
        digest = canonical_sha256(
            {k: v for k, v in draft.model_dump(mode="json").items() if k != "frozen_sha256"}
        )
        return draft.model_copy(update={"frozen_sha256": digest})

    def validate_frozen(self) -> FrozenTradeProposal:
        if canonical_sha256(self._hash_payload()) != self.frozen_sha256:
            raise CriticError(
                "PROPOSAL_TAMPERED",
                f"proposal {self.proposal_id} does not match its frozen hash",
            )
        return self

    @property
    def protective(self) -> bool:
        return self.intent in PROTECTIVE_INTENTS


class CriticReview(BaseModel):
    """An epistemic opinion about one frozen proposal. It carries no authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["TAP_CRITIC_REVIEW_V1"] = "TAP_CRITIC_REVIEW_V1"
    review_id: str = Field(min_length=1, max_length=80)
    bot_id: Literal["BOT-CRI-01"] = "BOT-CRI-01"
    proposal_id: str = Field(min_length=1, max_length=80)
    proposal_sha256: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=1200)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    counter_evidence_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    challenge_kind: ChallengeKind | None = None
    abstain_reason: AbstainReason | None = None
    decision_time_ms: int = Field(ge=0)
    responded_at_ms: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    prompt_id: Literal["TAP-PROMPT-CRI-001/v1"] = PROMPT_ID
    prompt_sha256: str
    provider: str = Field(min_length=1, max_length=60)
    model_id: str = Field(min_length=1, max_length=120)
    provider_receipt_id: str = Field(min_length=1, max_length=120)
    receipt_kind: ReceiptKind
    cost_usd: float = Field(ge=0.0)
    review_sha256: str

    @field_validator("proposal_sha256", "prompt_sha256", "review_sha256")
    @classmethod
    def _hash_shape(cls, value: str) -> str:
        if not _SHA_RE.match(value):
            raise ValueError("digest must be 64 lowercase hex characters")
        return value

    @field_validator("evidence_refs", "counter_evidence_refs")
    @classmethod
    def _citation_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            if not _REF_RE.match(ref):
                raise ValueError(f"citation must look like 'kind:identifier', got {ref!r}")
        return value

    @model_validator(mode="after")
    def _verdict_is_consistent(self) -> CriticReview:
        support = set(self.evidence_refs)
        counter = set(self.counter_evidence_refs)
        if self.verdict == "ACCEPT":
            if not support:
                raise ValueError("ACCEPT requires at least one supporting evidence ref")
            if counter:
                raise ValueError("ACCEPT cannot cite counter-evidence; use CHALLENGE or ABSTAIN")
            if self.abstain_reason is not None or self.challenge_kind is not None:
                raise ValueError("ACCEPT cannot carry an abstain reason or a challenge kind")
        elif self.verdict == "CHALLENGE":
            if not counter:
                raise ValueError("CHALLENGE requires at least one counter-evidence ref")
            if not counter - support:
                raise ValueError(
                    "CHALLENGE must cite counter-evidence that is not also its support"
                )
            if self.abstain_reason is not None:
                raise ValueError("CHALLENGE cannot carry an abstain reason")
            if self.challenge_kind is None:
                raise ValueError("CHALLENGE must name a challenge_kind")
        else:  # ABSTAIN
            if self.abstain_reason is None:
                raise ValueError("ABSTAIN must carry an abstain_reason")
            if self.challenge_kind is not None:
                raise ValueError("ABSTAIN cannot carry a challenge_kind")
        if self.responded_at_ms < self.decision_time_ms:
            raise ValueError("responded_at_ms cannot precede decision_time_ms")
        if self.latency_ms != self.responded_at_ms - self.decision_time_ms:
            raise ValueError("latency_ms must equal responded_at_ms - decision_time_ms")
        return self

    def _hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("review_sha256", None)
        return payload

    @classmethod
    def seal(cls, **payload: Any) -> CriticReview:
        draft = cls(**payload, review_sha256="0" * 64)
        digest = canonical_sha256(
            {k: v for k, v in draft.model_dump(mode="json").items() if k != "review_sha256"}
        )
        return draft.model_copy(update={"review_sha256": digest})

    def validate_sealed(self) -> CriticReview:
        if canonical_sha256(self._hash_payload()) != self.review_sha256:
            raise CriticError("SCHEMA_INVALID", "review does not match its sealed hash")
        return self


class AgentMessage(BaseModel):
    """One turn in the exchange, stored by hash; the text is bounded and hashed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1, max_length=80)
    run_id: str = Field(min_length=1, max_length=80)
    role: Literal["proposer", "critic", "system"]
    proposal_sha256: str
    at_ms: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=4000)
    content_sha256: str

    @model_validator(mode="after")
    def _content_matches_hash(self) -> AgentMessage:
        if text_sha256(self.content) != self.content_sha256:
            raise ValueError("content_sha256 does not match the stored content")
        return self

    @classmethod
    def seal(cls, **payload: Any) -> AgentMessage:
        return cls(**payload, content_sha256=text_sha256(str(payload["content"])))


class ReviewDecisionTrace(BaseModel):
    """What happened to a review, including whether it could have changed the book."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    run_id: str
    mode: Literal["OFF", "SHADOW_ONLY", "GATED_PAPER"]
    proposal_id: str
    proposal_sha256: str
    review_id: str
    review_sha256: str
    verdict: Verdict
    gate_action: Literal["ALLOW", "SUPPRESS_NEW_ENTRY"]
    gate_reason: str
    economics_affected: bool
    receipt_kind: ReceiptKind
    prompt_id: str
    prompt_sha256: str
    at_ms: int
    cost_usd: float
    latency_ms: int


def review_payload_is_forbidden(payload: Mapping[str, Any]) -> str | None:
    """Return the first forbidden field a model tried to set, if any."""
    present = sorted(set(payload) & FORBIDDEN_REVIEW_FIELDS)
    return present[0] if present else None


def parse_review_payload(
    payload: Mapping[str, Any],
    *,
    ledger: EvidenceLedger,
    service_fields: Mapping[str, Any],
) -> CriticReview:
    """Validate a model's answer against the schema and the authenticated ledger.

    The model supplies only its judgement. Identity, hashes, timestamps, provider receipt
    and cost are service-owned and cannot be overridden.
    """
    forbidden = review_payload_is_forbidden(payload)
    if forbidden:
        raise CriticError(
            "SCHEMA_FORBIDDEN_FIELD",
            f"the review tried to set a field a critic may never set: {forbidden}",
        )
    allowed = {
        "verdict", "confidence", "rationale", "evidence_refs",
        "counter_evidence_refs", "challenge_kind", "abstain_reason",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise CriticError(
            "SCHEMA_INVALID",
            f"the review carries fields outside the contract: {', '.join(unknown)}",
        )
    merged = {**service_fields, **payload}
    try:
        review = CriticReview.seal(**merged)
        review.validate_sealed()
    except ValidationError as exc:
        fields = ", ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise CriticError("SCHEMA_INVALID", fields) from exc
    except ValueError as exc:
        raise CriticError("SCHEMA_VALIDATION", str(exc)) from exc

    # Every citation must resolve to authenticated evidence. A hallucinated id has no
    # digest behind it, so it cannot become a citation.
    ledger.resolve((*review.evidence_refs, *review.counter_evidence_refs))
    return review


def evidence_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    source: str,
) -> list[EvidenceRef]:
    """Build authenticated refs from producer-owned rows (never from model text)."""
    refs: list[EvidenceRef] = []
    for index, row in enumerate(rows):
        digest = canonical_sha256(row)
        refs.append(
            EvidenceRef(
                ref_id=f"{kind}:{digest[:16]}",
                kind=kind,  # pydantic validates the literal at construction
                sha256=digest,
                summary=str(row.get("summary") or f"{kind} row {index}")[:240],
                source=source,
            )
        )
    return refs
