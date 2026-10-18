"""policy — the only two things a critic may do to a book: nothing, or say "not this entry".

SHADOW_ONLY is not a weaker gate; it is not a gate at all. The review is written down and
the book is untouched, which is what makes the shadow arm economically identical to the
baseline by construction rather than by hope.

GATED_PAPER is deliberately harder to reach than a flag: it needs both the mode *and* an
explicit authorisation that the AI-BOTS-003C validation happened. Even then the only
action available is ``SUPPRESS_NEW_ENTRY`` on an ``OPEN`` intent. A closing, reducing,
stop, take-profit or protective intent is allowed before the review is even consulted, so
no critic can trap a position.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from trading_bot.intelligence.ai_critic.contracts import (
    CriticError,
    CriticReview,
    FrozenTradeProposal,
)

#: The string the runtime expects before GATED_PAPER may alter anything. It is set only by
#: a caller that has the AI-BOTS-003C validation in hand; this module does not verify it.
GATED_PAPER_AUTHORIZATION = "AI_BOTS_003C_VALIDATED"


class CriticMode(StrEnum):
    OFF = "OFF"
    SHADOW_ONLY = "SHADOW_ONLY"
    GATED_PAPER = "GATED_PAPER"


GateAction = Literal["ALLOW", "SUPPRESS_NEW_ENTRY"]


@dataclass(frozen=True, slots=True)
class GateDecision:
    action: GateAction
    reason: str
    economics_affected: bool


def _allow(reason: str) -> GateDecision:
    return GateDecision(action="ALLOW", reason=reason, economics_affected=False)


def decide(
    mode: CriticMode,
    proposal: FrozenTradeProposal,
    review: CriticReview,
    *,
    authorization: str | None = None,
) -> GateDecision:
    """Decide what the review is allowed to do. Never returns a direction or a size."""
    if proposal.protective or proposal.intent != "OPEN":
        return _allow("PROTECTIVE_OR_EXIT_NEVER_BLOCKED")
    if mode is CriticMode.OFF:
        return _allow("CRITIC_DISABLED")
    if mode is CriticMode.SHADOW_ONLY:
        return _allow("SHADOW_OBSERVATION")
    if mode is CriticMode.GATED_PAPER:
        if authorization != GATED_PAPER_AUTHORIZATION:
            raise CriticError(
                "GATED_PAPER_NOT_AUTHORIZED",
                "GATED_PAPER requires the AI-BOTS-003C validation token; "
                "an unauthorised gate must not alter the book",
            )
        if review.abstain_reason == "LATE_RESPONSE":
            # A late opinion cannot approve an entry that has already left.
            return GateDecision("SUPPRESS_NEW_ENTRY", "LATE_OPINION_NO_TRADE", True)
        if review.verdict == "CHALLENGE":
            return GateDecision("SUPPRESS_NEW_ENTRY", "CRITIC_CHALLENGE", True)
        return _allow("NOT_CHALLENGED")
    raise CriticError("UNKNOWN_MODE", f"unknown critic mode {mode!r}")
