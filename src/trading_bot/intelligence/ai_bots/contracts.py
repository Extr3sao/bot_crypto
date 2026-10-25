"""contracts — the only shape an AI bot may answer in.

Two objects, one direction of travel:

``AITradeOpinion``  what a model is allowed to say (RFC 6.3). No size, no leverage, no
                    order, no risk edit. The forbidden keys are refused by name, so an
                    answer that tries to set them is rejected instead of partially read.
``TradeProposal``   the canonical proposal the runner hands to the RiskManager. It
                    carries the opinion's evidence references and timestamp, so the
                    deterministic side never has to trust a string.

The translation keeps the model's own view intact (`thesis`, `invalidation`) while the
size and the protective levels stay the property of ``RiskManager``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from trading_bot.vision.contract import FORBIDDEN_FIELDS, VisionDecision

OPINION_SCHEMA_VERSION: Final = "AIBOT_OPINION_V1"

Decision = Literal["LONG", "SHORT", "CLOSE", "NO_TRADE"]
Side = Literal["buy", "sell", "close"]


class OpinionRejectedBySchema(ValueError):
    """An opinion that cannot be accepted. ``code`` is stable and countable."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class AITradeOpinion(BaseModel):
    """A discretionary opinion. It is a *view*, not an instruction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AIBOT_OPINION_V1"] = "AIBOT_OPINION_V1"
    bot_id: str
    run_id: str
    asset: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    timeframe: str
    decision_time_ms: int = Field(ge=0)
    horizon_bars: int = Field(ge=1, le=168)
    thesis: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    counter_evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    invalidation: str | None = Field(default=None, max_length=240)
    invalidation_price: float | None = Field(default=None, gt=0.0, le=10_000_000.0)
    no_trade_reason: str | None = Field(default=None, max_length=240)

    @field_validator("asset", mode="before")
    @classmethod
    def _asset_shape(cls, value: Any) -> Any:
        text = str(value or "").strip().upper()
        if "/" not in text:
            raise ValueError(f"asset must look like BTC/USDT, got {value!r}")
        return text

    @property
    def directional(self) -> bool:
        return self.decision in ("LONG", "SHORT")


class TradeProposal(BaseModel):
    """The canonical proposal: what the deterministic side will actually consider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    bot_id: str
    run_id: str
    asset: str
    side: Literal["buy", "sell", "close"]
    confidence: float = Field(ge=0.0, le=1.0)
    timeframe: str
    decision_time_ms: int
    horizon_bars: int
    thesis: str
    evidence_refs: list[str] = Field(default_factory=list)
    opinion_digest: str
    #: Policy-owned, filled by the runner after RiskManager answers. A proposal arriving
    #: from a bot never carries them.
    risk_approved_notional_usdt: float | None = None
    policy_stop_loss_pct: float | None = None
    policy_take_profit_pct: float | None = None


def opinion_digest(opinion: AITradeOpinion) -> str:
    payload = json.dumps(opinion.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def reject_forbidden_fields(payload: dict[str, Any]) -> None:
    """A key no model may set is a rejection, not something to ignore."""
    forbidden = sorted(set(payload) & FORBIDDEN_FIELDS)
    if forbidden:
        raise OpinionRejectedBySchema(
            "SCHEMA_FORBIDDEN_FIELD",
            f"the opinion carries fields no model may set: {', '.join(forbidden)}",
        )


def validate_opinion(payload: dict[str, Any]) -> AITradeOpinion:
    reject_forbidden_fields(payload)
    try:
        return AITradeOpinion.model_validate(payload)
    except ValidationError as exc:
        fields = ", ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise OpinionRejectedBySchema("SCHEMA_VIOLATION", fields) from exc


def opinion_from_vision_decision(
    decision: VisionDecision,
    *,
    bot_id: str,
    run_id: str,
    asset: str,
    timeframe: str,
    image_sha256: str,
    decision_time_ms: int,
) -> AITradeOpinion:
    """Lift a parsed visual decision into the bot-plane contract.

    ``evidence_refs`` names the image by hash, which is what makes the opinion auditable:
    the picture it was formed from is a value, not a description.
    """
    return AITradeOpinion(
        bot_id=bot_id,
        run_id=run_id,
        asset=asset,
        decision=decision.action,
        confidence=float(decision.confidence),
        timeframe=timeframe,
        decision_time_ms=int(decision_time_ms),
        horizon_bars=int(decision.horizon_bars),
        thesis=decision.rationale,
        evidence_refs=[f"image:{image_sha256}", f"bar:{int(decision_time_ms)}"],
        counter_evidence_refs=[],
        invalidation=decision.invalidation,
        invalidation_price=decision.invalidation_price,
        no_trade_reason=decision.rationale if decision.action == "NO_TRADE" else None,
    )


def proposal_from_opinion(proposal_id: str, opinion: AITradeOpinion) -> TradeProposal:
    """Map an actionable opinion onto the canonical proposal. ``NO_TRADE`` is not one."""
    if opinion.decision == "NO_TRADE":
        raise OpinionRejectedBySchema(
            "NOT_A_PROPOSAL", "NO_TRADE is a decision, not a proposal: nothing to execute"
        )
    side: Side = cast(
        "Side",
        {
            "LONG": "buy",
            "SHORT": "sell",
            "CLOSE": "close",
        }[opinion.decision],
    )
    return TradeProposal(
        proposal_id=proposal_id,
        bot_id=opinion.bot_id,
        run_id=opinion.run_id,
        asset=opinion.asset,
        side=side,
        confidence=opinion.confidence,
        timeframe=opinion.timeframe,
        decision_time_ms=opinion.decision_time_ms,
        horizon_bars=opinion.horizon_bars,
        thesis=opinion.thesis,
        evidence_refs=list(opinion.evidence_refs),
        opinion_digest=opinion_digest(opinion),
    )
