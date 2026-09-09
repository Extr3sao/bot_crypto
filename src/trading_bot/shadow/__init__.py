"""Shadow package — next-campaign only, never imported by POC01 runtime.

Captures verified candidates rejected by Risk and resolves them as
counterfactual shadow trades. Isolated from PaperBroker, PortfolioStore,
RiskManager and campaign accounting by construction.
"""

from __future__ import annotations

from trading_bot.shadow.capture import (
    SHADOW_LABELS,
    ShadowCandidateCapture,
    ShadowCandidateLedger,
)
from trading_bot.shadow.outcome import (
    ShadowBar,
    ShadowOutcomeEngine,
    ShadowTrade,
    ShadowTradeOutcome,
)

__all__ = [
    "SHADOW_LABELS",
    "ShadowBar",
    "ShadowCandidateCapture",
    "ShadowCandidateLedger",
    "ShadowOutcomeEngine",
    "ShadowTrade",
    "ShadowTradeOutcome",
]
