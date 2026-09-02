"""Asset Intelligence Layer package (RFC-AIL-000..006).

Point-in-time, deterministic, per-asset context for strategy families:

    OHLCV / Market Data
        ↓
    shared feature calculators (features.py)
        ↓
    AssetAgent (base.py, agents/)
        ↓
    AssetContext (models.py)
        ↓
    Strategy Families (families/, via StrategyInput.asset_context)

Boundary invariants (pinned by tests):
- Asset agents NEVER import execution, exchanges, or secrets.
- Every feature is computed exclusively from bars at or before the
  context timestamp (point-in-time, no lookahead).
- AssetContext is immutable after creation.
"""

from .features import FEATURE_VERSIONS, compute_shared
from .models import ASSET_CONTEXT_SCHEMA_VERSION, AssetContext, AssetContextError

__all__ = [
    "ASSET_CONTEXT_SCHEMA_VERSION",
    "FEATURE_VERSIONS",
    "AssetContext",
    "AssetContextError",
    "compute_shared",
]
