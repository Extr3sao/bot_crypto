"""VENUE-AND-EXECUTION-RESEARCH-V1 — machine-readable artifacts (§PHASE 1-3).

Read-only, offline, deterministic. Emits:

  docs/COST_MODEL_V3.json
  docs/VENUE_EXECUTION_MATRIX_V1.json
  docs/EXECUTION_MODEL_V1.json

No network, no credentials, no execution. Re-running on an unchanged tree must
produce byte-identical output (asserted by the verifier).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from trading_bot.research.microstructure.cost_model_v3 import (
    ADMISSION_SCENARIO_ID,
    COST_STRESS_MULTIPLES,
    VENUE_SPECS,
    LiquidityRegime,
    VenueSpec,
    default_model,
    scenario_ids,
    venue_matrix_rows,
)
from trading_bot.research.microstructure.execution_model_v1 import (
    EXECUTION_MODEL_VERSION,
    FillEvidence,
    MakerExecutionModel,
    SyntheticMakerScenario,
    TakerExecutionModel,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")

# Reference execution intent used for every scenario so the comparison is
# apples-to-apples. ASSUMED reference size/liquidity, documented here.
REFERENCE_SIZE_USD = 1_000.0
REFERENCE_LIQUIDITY: LiquidityRegime = "normal"
REFERENCE_HORIZON_MINUTES = 25.0
REFERENCE_INTENT: dict[str, object] = {
    "size_usd": REFERENCE_SIZE_USD,
    "liquidity_regime": REFERENCE_LIQUIDITY,
    "horizon_minutes": REFERENCE_HORIZON_MINUTES,
}


def _write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, sort_keys=False)
        fh.write("\n")


def _spec_row(spec: VenueSpec) -> dict[str, Any]:
    return {
        "scenario_id": spec.scenario_id,
        "venue": spec.venue,
        "product": spec.product,
        "jurisdiction": spec.jurisdiction,
        "symbol_class": spec.symbol_class,
        "tier": spec.tier,
        "fee_payment_mode": spec.fee_payment_mode,
        "maker_fee_bps": spec.maker_fee_bps,
        "taker_fee_bps": spec.taker_fee_bps,
        "discount_program": spec.discount_program,
        "discount_applicability": spec.discount_applicability,
        "default_taker_spread_bps": spec.default_taker_spread_bps,
        "min_notional_usd": spec.min_notional_usd,
        "fee_source_id": spec.fee_source_id,
        "spread_source_id": spec.spread_source_id,
        "funding_source_id": spec.funding_source_id,
        "integration_status": spec.integration_status,
        "notes": spec.notes,
    }


def build_cost_model_v3() -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for sid in scenario_ids():
        spec = VENUE_SPECS[sid]
        model = default_model(sid)
        cost = model.evaluate(
            size_usd=REFERENCE_SIZE_USD,
            liquidity_regime=REFERENCE_LIQUIDITY,
            horizon_minutes=REFERENCE_HORIZON_MINUTES,
        )
        scenarios.append(
            {
                "spec": _spec_row(spec),
                "evaluation": cost.as_dict(),
            }
        )
    return {
        "model": "COST_MODEL_V3",
        "generated_by": "scripts/venue_execution_research.py",
        "supersedes": "COST_MODEL_V2",
        "knowledge_classes": ["KNOWN", "OBSERVED", "ESTIMATED", "ASSUMED"],
        "applicability_verdicts": ["CONFIRMED", "POSSIBLE", "NOT_APPLICABLE", "UNKNOWN"],
        "reference_intent": REFERENCE_INTENT,
        "admission_scenario_id": ADMISSION_SCENARIO_ID,
        "stress_multiples": list(COST_STRESS_MULTIPLES),
        "model_constants": {
            "liquidity_multiplier": {"deep": 0.5, "normal": 1.0, "thin": 2.5},
            "reference_notional_usd": 10_000.0,
            "base_slippage_bps": 1.0,
            "base_impact_bps": 0.25,
            "maker_adverse_selection_bps": 0.5,
            "maker_fill_prob": 0.5,
            "maker_partial_fill_penalty_bps": 0.25,
            "knowledge": "ASSUMED/ESTIMATED modelling constants, not observations",
        },
        "prohibitions_enforced": [
            "maker rebates are not modelled",
            "limit orders are not assumed to fill",
            "a BNB/promotional discount can never be CONFIRMED without governance",
            "ZERO_COST is diagnostic only",
        ],
        "scenarios": scenarios,
    }


def build_venue_matrix() -> dict[str, Any]:
    rows = venue_matrix_rows(
        size_usd=REFERENCE_SIZE_USD,
        liquidity_regime=REFERENCE_LIQUIDITY,
        horizon_minutes=REFERENCE_HORIZON_MINUTES,
    )
    cheapest = min(rows, key=lambda r: float(r["taker_rt_cost_bps"]))
    frontier = [
        {
            "scenario_id": r["scenario_id"],
            "venue": r["venue"],
            "product": r["product"],
            "taker_rt_cost_bps": r["taker_rt_cost_bps"],
            "maker_rt_cost_bps_theoretical": r["maker_rt_cost_bps_theoretical"],
            "required_edge_bps_1p5x": r["taker_required_edge_bps_1p5x"],
        }
        for r in sorted(rows, key=lambda r: float(r["taker_rt_cost_bps"]))
    ]
    return {
        "model": "VENUE_EXECUTION_MATRIX_V1",
        "generated_by": "scripts/venue_execution_research.py",
        "reference_intent": REFERENCE_INTENT,
        "no_venue_is_declared_best": True,
        "cheapest_taker_scenario": cheapest["scenario_id"],
        "economic_frontier_ordered_by_taker_rt_cost": frontier,
        "rows": rows,
        "caveats": [
            "Fees are the PUBLISHED headline rates for the stated tier; "
            "promotions are recorded but never assumed.",
            "Spread/slippage for non-Binance venues are ASSUMED, not observed: "
            "we only measured Binance bookTicker.",
            "Cheapest headline fee != best venue: liquidity, depth, "
            "jurisdiction, API quality and settlement risk are not priced here.",
            "Derivatives rows are research-only and excluded from the runtime.",
        ],
    }


def build_execution_model() -> dict[str, Any]:
    taker = TakerExecutionModel()
    maker = MakerExecutionModel(maker_fee_bps=0.0)

    synthetic = SyntheticMakerScenario(
        fill_prob=0.40,
        partial_prob=0.20,
        missed_opportunity_cost_bps=3.0,
        adverse_selection_bps=1.0,
    )
    synthetic_outcome = maker.evaluate_synthetic(synthetic).as_dict()

    no_evidence = maker.evaluate(FillEvidence()).as_dict()

    return {
        "model": EXECUTION_MODEL_VERSION,
        "generated_by": "scripts/venue_execution_research.py",
        "taker": taker.as_dict(),
        "maker": maker.as_dict(),
        "maker_without_evidence": no_evidence,
        "maker_synthetic_stress_test": {
            "label": "SYNTHETIC_STRESS_TEST",
            "admissible": False,
            "scenario": {
                "fill_prob": synthetic.fill_prob,
                "partial_prob": synthetic.partial_prob,
                "missed_opportunity_cost_bps": synthetic.missed_opportunity_cost_bps,
                "adverse_selection_bps": synthetic.adverse_selection_bps,
            },
            "outcome": synthetic_outcome,
        },
        "required_evidence_for_admission": [
            "fill_rate (from a forward collection, n > 0)",
            "partial_fill_rate",
            "median time to fill",
            "adverse move after fill (bps)",
        ],
        "status": "EXECUTION_MODEL_REQUIRED",
        "status_reason": (
            "no measured fill evidence exists yet; the maker path stays "
            "EXECUTION_MODEL_REQUIRED and is barred from admission"
        ),
    }


def main() -> None:
    os.makedirs(DOCS, exist_ok=True)
    cost = build_cost_model_v3()
    matrix = build_venue_matrix()
    execution = build_execution_model()

    _write_json(os.path.join(DOCS, "COST_MODEL_V3.json"), cost)
    _write_json(os.path.join(DOCS, "VENUE_EXECUTION_MATRIX_V1.json"), matrix)
    _write_json(os.path.join(DOCS, "EXECUTION_MODEL_V1.json"), execution)

    print("-> docs/COST_MODEL_V3.json, VENUE_EXECUTION_MATRIX_V1.json, EXECUTION_MODEL_V1.json")
    print(f"admission scenario: {ADMISSION_SCENARIO_ID}")
    for row in matrix["economic_frontier_ordered_by_taker_rt_cost"]:
        print(
            f"  {row['scenario_id']:<28} taker_rt={row['taker_rt_cost_bps']:>7.2f} bps "
            f"required(1.5x)={row['required_edge_bps_1p5x']:>7.2f} bps"
        )


if __name__ == "__main__":
    main()
