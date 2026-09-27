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
from .cost_model_v3 import (
    ADMISSION_SCENARIO_ID,
    VENUE_SPECS,
    AllInCost,
    CostComponent,
    CostModelV3,
    VenueSpec,
    cost_model_v3_all_in,
    cost_stress_table,
    default_model,
    venue_matrix_rows,
)
from .execution_model_v1 import (
    EXECUTION_MODEL_VERSION,
    ExecutionOutcome,
    FillEvidence,
    MakerExecutionModel,
    SyntheticMakerScenario,
    TakerExecutionModel,
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
    "ADMISSION_SCENARIO_ID",
    "COST_MODEL_V2",
    "EXECUTION_MODEL_VERSION",
    "FEATURE_SPECS",
    "VENUE_SPECS",
    "AllInCost",
    "BasisPoint",
    "BookSnapshot",
    "CostComponent",
    "CostModelV3",
    "CostScenario",
    "DataIntegrityError",
    "ExecutionOutcome",
    "FeatureSpec",
    "FillEvidence",
    "FundingPoint",
    "IntegrityReport",
    "MakerExecutionModel",
    "MicroBar",
    "OpenInterestPoint",
    "PremiumPoint",
    "SyntheticMakerScenario",
    "TakerExecutionModel",
    "VenueSpec",
    "check_book_snapshot",
    "check_ordering_and_duplicates",
    "check_price_series",
    "classify_gaps",
    "component_table",
    "cost_model_status",
    "cost_model_v3_all_in",
    "cost_stress_table",
    "default_model",
    "flow_features",
    "forward_return_bps",
    "pit_slice",
    "rolling_zscore",
    "venue_matrix_rows",
]
