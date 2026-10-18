"""ai_critic — BOT-CRI-01, an epistemic critic with no authority over the book.

``contracts``  FrozenTradeProposal, EvidenceLedger, CriticReview, AgentMessage, trace row.
``prompt``     TAP-PROMPT-CRI-001/v1 and the untrusted-text boundary.
``provider``   provider protocol plus replayed/scripted receipts (no SDK, no key).
``critic``     the review service: budget, deadline, strict parse, fail closed.
``policy``     OFF / SHADOW_ONLY / GATED_PAPER; the only allowed effect is suppressing a
               new entry, and only with an explicit AI-BOTS-003C authorisation.

Nothing here imports ``PaperBroker``, ``RiskManager`` or an exchange adapter. The critic is
not the repository's code verifier; that program lives outside this package and must not
import it.
"""

from __future__ import annotations

from trading_bot.intelligence.ai_critic.contracts import (
    PROMPT_ID,
    AgentMessage,
    CriticError,
    CriticReview,
    EvidenceLedger,
    EvidenceRef,
    FrozenTradeProposal,
    ReviewDecisionTrace,
)
from trading_bot.intelligence.ai_critic.critic import (
    BudgetExceeded,
    CriticBudget,
    CriticService,
    ReviewOutcome,
)
from trading_bot.intelligence.ai_critic.policy import (
    GATED_PAPER_AUTHORIZATION,
    CriticMode,
    GateDecision,
)
from trading_bot.intelligence.ai_critic.prompt import CriticPrompt, build_critic_prompt
from trading_bot.intelligence.ai_critic.provider import (
    CriticProvider,
    CriticProviderError,
    CriticRequest,
    CriticResponse,
    ReplayCriticProvider,
    ScriptedCriticProvider,
)
from trading_bot.intelligence.ai_critic.trace import CriticTraceWriter

__all__ = [
    "GATED_PAPER_AUTHORIZATION",
    "PROMPT_ID",
    "AgentMessage",
    "BudgetExceeded",
    "CriticBudget",
    "CriticError",
    "CriticMode",
    "CriticPrompt",
    "CriticProvider",
    "CriticProviderError",
    "CriticRequest",
    "CriticResponse",
    "CriticReview",
    "CriticService",
    "CriticTraceWriter",
    "EvidenceLedger",
    "EvidenceRef",
    "FrozenTradeProposal",
    "GateDecision",
    "ReplayCriticProvider",
    "ReviewDecisionTrace",
    "ReviewOutcome",
    "ScriptedCriticProvider",
    "build_critic_prompt",
]
