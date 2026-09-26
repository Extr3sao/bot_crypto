"""Research-only microstructure primitives (EXECUTION-COST & MICROSTRUCTURE-EDGE-V1).

Nothing in this package is imported by the production/runtime path.
"""

from .cost_model import (
    ADMISSION_COST_MODEL,
    ADMISSION_SAFETY_MULTIPLE,
    COST_MODEL_V2,
    CostScenario,
    component_table,
    cost_model_status,
)
from .features import FEATURE_SPECS, FeatureSpec, flow_features, forward_return_bps, rolling_zscore
from .integrity import (
    BookSnapshot,
    DataIntegrityError,
    IntegrityReport,
    check_book_snapshot,
    check_ordering_and_duplicates,
    check_price_series,
    classify_gaps,
    pit_slice,
)
from .types import (
    BasisPoint,
    FundingPoint,
    MicroBar,
    OpenInterestPoint,
    PremiumPoint,
)

__all__ = [
    "ADMISSION_COST_MODEL",
    "ADMISSION_SAFETY_MULTIPLE",
    "COST_MODEL_V2",
    "FEATURE_SPECS",
    "BasisPoint",
    "BookSnapshot",
    "CostScenario",
    "DataIntegrityError",
    "FeatureSpec",
    "FundingPoint",
    "IntegrityReport",
    "MicroBar",
    "OpenInterestPoint",
    "PremiumPoint",
    "check_book_snapshot",
    "check_ordering_and_duplicates",
    "check_price_series",
    "classify_gaps",
    "component_table",
    "cost_model_status",
    "flow_features",
    "forward_return_bps",
    "pit_slice",
    "rolling_zscore",
]
