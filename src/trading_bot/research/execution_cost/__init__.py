"""What a round trip costs, with every number labelled by how it was obtained.

The repository has never lacked a cost model; ``cost_model_v3`` and ``cost_model_v4`` both price a
round trip, and both already carry a ``KnowledgeClass`` per component. What it lacked is a cost
*measurement*: a number produced from quotes that were actually recorded, whose weakest component
is visible at the point of use.

This package adds no new pricing arithmetic. It reuses ``VENUE_SPECS`` for the fee and
``KnowledgeClass`` for the vocabulary, and it does two things the models cannot:

1. **It measures the spread from the tape.** The ST-6 collector stored ``bid``/``ask`` and a depth
   walk per asset per window; the median measured spread is therefore a fact about the venue, not a
   ``_MAJORS_SPREAD_BPS = 1.0`` constant.
2. **It refuses to answer at a size nobody walked.** ST-6 walked 200 USDT. A 500 USDT number is
   not that number scaled up — depth is not linear — so the type system says
   ``DECLARED_SIZE_NOT_WALKED`` and reports a *lower bound* instead of a measurement.

RESEARCH_ONLY. No order, no credential, no promotion; ``economic_executions: 0`` by construction.
"""

from __future__ import annotations

from .measured import (
    COST_CONFIRMED,
    COST_LOWER,
    INSUFFICIENT_EVIDENCE,
    MEASURED,
    NOT_A_DECISION,
    SIZE_NOT_WALKED,
    AssetMeasurement,
    CostComponent,
    MeasuredRoundTrip,
    Quote,
    evaluate_cost_question,
    load_st6_quotes,
    measure_asset,
    measure_round_trip,
    percentile,
    weakest_class,
)

__all__ = [
    "COST_CONFIRMED",
    "COST_LOWER",
    "INSUFFICIENT_EVIDENCE",
    "MEASURED",
    "NOT_A_DECISION",
    "SIZE_NOT_WALKED",
    "AssetMeasurement",
    "CostComponent",
    "MeasuredRoundTrip",
    "Quote",
    "evaluate_cost_question",
    "load_st6_quotes",
    "measure_asset",
    "measure_round_trip",
    "percentile",
    "weakest_class",
]
