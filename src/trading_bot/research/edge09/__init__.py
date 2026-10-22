"""RFC-EDGE-009 — market microstructure and economic-edge research (research only).

This package is a DISCOVERY-PLANE package: nothing here is imported by the
runtime, nothing here places an order, and nothing here writes a risk limit.
It reads the corpora the project already holds (including the forward
microstructure capture) and the authoritative cost/risk contracts, and it
answers one question: is there an economically executable edge once the real
cost barrier, the real liquidity and the real frequency are applied?

The registration (thresholds, hypotheses and the decision rules) lives in
:mod:`trading_bot.research.edge09.registration` and is fixed *before* any
measurement is taken.
"""

from .registration import (
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    CLASSIFICATIONS,
    CONSUMED_HOLDOUTS,
    HYPOTHESES,
    LADDER,
    SCENARIOS_COMPARED,
    WP,
)

__all__ = [
    "ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY",
    "CLASSIFICATIONS",
    "CONSUMED_HOLDOUTS",
    "HYPOTHESES",
    "LADDER",
    "SCENARIOS_COMPARED",
    "WP",
]
