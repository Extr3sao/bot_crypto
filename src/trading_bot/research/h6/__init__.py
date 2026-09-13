"""H6 discovery execution package preparation.

This package prepares the H6 execution machinery ONLY. H6 economic
execution remains BLOCKED until external verification passes and the
confirmation lock is cleared.

Frozen authority (V4) is NOT hard-coded here. It resolves from the single
versioned runtime binding:

    docs/external-audit-01/h6-v4-repair/H6_RUNTIME_AUTHORITY_BINDING_V4.json

via ``trading_bot.research.h6.runtime_authority``. While the binding does not
exist (pre-freeze) the runtime is UNBOUND_PRE_FREEZE and fails closed. The V3
package hard-coded the superseded V1 blob ``e683e04`` across eleven files.
"""

from __future__ import annotations

from trading_bot.research.h6.contracts import (
    DATASET_SHA256,
    PriceDirection,
    SignalDirection,
    SPEC_SHA256,
    H6FeatureState,
    H6Signal,
)
from trading_bot.research.h6.cost import (
    COST_SENSITIVITY_BPS,
    COST_TOTAL_ROUND_TRIP_BPS,
    H6CostResult,
    compute_cost_result,
)
from trading_bot.research.h6.drift_guard import assert_runtime_matches_frozen_spec
from trading_bot.research.h6.eligibility import (
    CompletedHourOI,
    ObservedOI,
    build_completed_hour_oi,
    completed_hour_changes_before,
    decision_eligibility_at_t,
)
from trading_bot.research.h6.execution_harness import (
    H6ExternalVerificationRequired,
    H6PreregMismatch,
    can_execute_h6,
    run_h6_dry_run,
)
from trading_bot.research.h6.execution_ledger import (
    H6ExecutionAttempt,
    H6ExecutionLedger,
)
from trading_bot.research.h6.external_verification import (
    ExternalVerificationState,
    external_verification_state,
)
from trading_bot.research.h6.feature_engine import (
    H6FeatureEngine,
    compute_signal,
)
from trading_bot.research.h6.funding import (
    FUNDING_DISCOVERY_ACCOUNTING,
    FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION,
    H6FundingNotAvailable,
    funding_included_for_discovery,
)
from trading_bot.research.h6.gate_config import (
    H6DiscoveryGates,
    H6FrozenParameterOverride,
    frozen_h6_gates,
)
from trading_bot.research.h6.result_schema import (
    ALLOWED_TERMINAL_RESULTS,
    H6ResultSchema,
    build_schema_placeholder,
)
from trading_bot.research.h6.whitelist import (
    ALLOWED_H6_FIELDS,
    FORBIDDEN_H6_FIELDS,
    H6ForbiddenFeatureAccess,
    H6FieldAccess,
)

__all__ = [
    "ALLOWED_H6_FIELDS",
    "ALLOWED_TERMINAL_RESULTS",
    "COST_SENSITIVITY_BPS",
    "COST_TOTAL_ROUND_TRIP_BPS",
    "DATASET_SHA256",
    "CompletedHourOI",
    "ExternalVerificationState",
    "FORBIDDEN_H6_FIELDS",
    "H6CostResult",
    "H6DiscoveryGates",
    "H6ExecutionAttempt",
    "H6ExecutionLedger",
    "H6FeatureEngine",
    "H6FeatureState",
    "H6FieldAccess",
    "H6ForbiddenFeatureAccess",
    "H6FundingNotAvailable",
    "H6FrozenParameterOverride",
    "H6PreregMismatch",
    "H6ResultSchema",
    "H6Signal",
    "FUNDING_DISCOVERY_ACCOUNTING",
    "FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION",
    "H6ExternalVerificationRequired",
    "ObservedOI",
    "PriceDirection",
    "SignalDirection",
    "SPEC_SHA256",
    "assert_runtime_matches_frozen_spec",
    "build_completed_hour_oi",
    "build_schema_placeholder",
    "can_execute_h6",
    "completed_hour_changes_before",
    "compute_cost_result",
    "compute_signal",
    "decision_eligibility_at_t",
    "external_verification_state",
    "frozen_h6_gates",
    "funding_included_for_discovery",
    "run_h6_dry_run",
]
