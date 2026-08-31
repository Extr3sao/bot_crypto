"""RouterGates — configurable gates for the StrategyRouter."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["STALE_THRESHOLD_MS", "RouterGates"]

# Context is stale if the window ends more than this far behind the
# requested timestamp (15 minutes, matching AssetContext.STALE_AFTER_MS).
STALE_THRESHOLD_MS = 15 * 60 * 1000


@dataclass(frozen=True, slots=True)
class RouterGates:
    """Gates a strategy must pass before the router selects it."""

    require_confirmed: bool = True
    require_regime_match: bool = True
    min_data_quality: float = 0.5
    require_fresh_context: bool = True
