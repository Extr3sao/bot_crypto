"""Research discovery governance contracts.

This package is a RESEARCH PLANE capability. It must not:
- modify ARC-02 frozen economics
- trade
- call Risk / PaperBroker / Execution
- change leverage, sizing, or production strategy parameters
- promote a strategy
- automatically rerun a failed hypothesis

It may only produce: diagnostics, research candidates, structured evidence,
research budgets, source records.
"""

from __future__ import annotations

from trading_bot.research.discovery_failure_diagnostics import StrategyFailureDiagnostics
from trading_bot.research.discovery_hypothesis_generator import HypothesisGenerator
from trading_bot.research.discovery_research_budget import ResearchBudget
from trading_bot.research.discovery_external_intake import ExternalStrategyIntake
from trading_bot.research.discovery_market_intelligence import MarketIntelligenceProvider

__all__ = [
    "StrategyFailureDiagnostics",
    "HypothesisGenerator",
    "ResearchBudget",
    "ExternalStrategyIntake",
    "MarketIntelligenceProvider",
]
