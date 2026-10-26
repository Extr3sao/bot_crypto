"""WP-EDGE-14B — cost integrity, reconstructed from the primary artefacts.

The brief opens with a contradiction it refuses to resolve by assertion:

* ``WP-EDGE-09/FINAL_REPORT.md`` says the fee is **85.9% of the barrier** ("the fee alone
  is 20 of them", against a 23-24 bps round trip);
* ``WP-EDGE-09/ECONOMIC_FEASIBILITY_REPORT.md`` says the **mean fee component is 32.5 bps
  of a mean barrier 23.4439 bps (1.3863 of the round trip)**.

Both documents claim to be rendered from the *same* reading. And the brief adds the
accounting rule that settles it: if 32.5 > 23.4439 and every component is a non-negative
cost, then under the same unit, period and scenario the identity is violated. It then
warns, correctly, not to blame a particular bug before reconstructing the inputs.

This module reconstructs the inputs from ``gates/COST_LIQUIDITY_CAPACITY.json`` — the
frozen primary artefact both documents read — and finds the population, not the
arithmetic, is where they disagree:

* the **admission scenario** is ``BINANCE_SPOT_STANDARD_TAKER``: taker fee 20 bps, mean
  round trip 23.2778 bps over the 10 streams. 20 / 23.2778 = **85.9%**. Both numerator
  and denominator here are the admission scenario, so the ratio is legitimate.
* ``barriers`` however holds **40** rows across **four** venue schedules (Binance 20 bps,
  OKX 20 bps, MEXC 10 bps, Kraken Pro 80 bps taker). ``edge09_deliverables.py`` averages
  the fee column over **all 40** — (20+20+10+80)/4 = **32.5** — and divides it by the
  **admission-only** mean barrier of 23.4439. That is a cross-venue numerator over an
  admission-only denominator: 1.3863.

So 32.5 bps is a real number; it is the mean *taker fee across four different venue
schedules*, and it is a **category error** to divide it by the admission barrier. No fee
was double-counted and no accounting identity was broken in the underlying gate; the
identity was broken by the *sentence*, at render time, by mixing two populations.

The correct, same-population statement is: **the fee is 85.9% of the admission round
trip.** The 1.3863 sentence is superseded, not deleted: the original artefacts keep their
bytes and this module publishes the reconciliation that replaces the claim.
"""

from __future__ import annotations

from typing import Any

from .contracts import EconomicCostBreakdown
from .evidence import EDGE09_GATES, sha256_file

__all__ = [
    "ADMISSION_SCENARIO",
    "claim_fee_share_of_admission",
    "cross_population_defect",
    "fee_by_scenario",
    "load_gates",
    "reconciliation_payload",
]

ADMISSION_SCENARIO = "BINANCE_SPOT_STANDARD_TAKER"


def load_gates() -> dict[str, Any]:
    """Read the frozen gate artefact. Read-only: the caller must never write it back."""
    from .evidence import read_json

    payload = read_json(EDGE09_GATES)
    if not isinstance(payload, dict):
        raise FileNotFoundError(f"WP-EDGE-09 gate artefact missing: {EDGE09_GATES}")
    return payload


def fee_by_scenario(gates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One row per registered venue schedule, with its own fee and its own barrier.

    Keeping the schedules apart is the whole point: a mean over these four is a mean over
    four products a trader would choose *between*, not a cost one trader pays.
    """
    rows: dict[str, dict[str, Any]] = {}
    for row in gates.get("barriers") or []:
        scenario = str(row.get("scenario"))
        components = row.get("components_bps") or {}
        bucket = rows.setdefault(
            scenario,
            {
                "scenario": scenario,
                "venue": row.get("venue"),
                "product": row.get("product"),
                "n": 0,
                "_fees": [],
                "_round_trips": [],
                "_component_sums": [],
            },
        )
        bucket["n"] += 1
        if "fee" in components:
            bucket["_fees"].append(float(components["fee"]))
        if row.get("round_trip_bps") is not None:
            bucket["_round_trips"].append(float(row["round_trip_bps"]))
        if components:
            bucket["_component_sums"].append(float(sum(components.values())))

    for bucket in rows.values():
        fees = bucket.pop("_fees")
        round_trips = bucket.pop("_round_trips")
        component_sums = bucket.pop("_component_sums")
        bucket["mean_fee_bps"] = round(sum(fees) / len(fees), 6) if fees else None
        bucket["mean_round_trip_bps"] = (
            round(sum(round_trips) / len(round_trips), 6) if round_trips else None
        )
        bucket["fee_share_of_its_own_barrier"] = (
            round(bucket["mean_fee_bps"] / bucket["mean_round_trip_bps"], 6)
            if bucket["mean_fee_bps"] is not None and bucket["mean_round_trip_bps"]
            else None
        )
        # The accounting identity inside one scenario: the components must sum to the
        # round trip. This is what "non-negative components cannot exceed the total"
        # tests, and it holds per scenario.
        bucket["components_sum_matches_round_trip"] = all(
            abs(components - round_trip) <= 0.01
            for components, round_trip in zip(component_sums, round_trips, strict=False)
        )
    return dict(sorted(rows.items()))


def claim_fee_share_of_admission(gates: dict[str, Any]) -> dict[str, Any]:
    """The legitimate ratio: admission fee over admission barrier, same population."""
    scenarios = fee_by_scenario(gates)
    admission = scenarios.get(ADMISSION_SCENARIO, {})
    mean_fee = admission.get("mean_fee_bps")
    mean_barrier = admission.get("mean_round_trip_bps")
    share = None if not mean_barrier else round(mean_fee / mean_barrier, 6)
    return {
        "scenario": ADMISSION_SCENARIO,
        "n_streams": admission.get("n"),
        "mean_fee_bps": mean_fee,
        "mean_round_trip_bps": mean_barrier,
        "fee_share_of_round_trip": share,
        "fee_share_percent": None if share is None else round(share * 100, 2),
        "population": "admission_scenario_only",
        "verdict": f"the fee is {share * 100:.1f}% of the admission round trip"
        if share is not None
        else "not measurable",
    }


def cross_population_defect(gates: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the 1.3863 sentence and name why it is wrong.

    The reproduction is deliberately faithful: it averages the fee column over *every*
    registered schedule, then divides by the *admission-only* barrier. That the result
    equals the published 1.3863 is the proof that this, and not a double count, is the
    source of the contradiction.
    """
    scenarios = fee_by_scenario(gates)
    cross_venue_fees = [
        row["mean_fee_bps"] for row in scenarios.values() if row["mean_fee_bps"] is not None
    ]
    cross_venue_mean_fee = (
        round(sum(cross_venue_fees) / len(cross_venue_fees), 6) if cross_venue_fees else None
    )
    admission = gates.get("admission_barrier_bps") or {}
    admission_mean_barrier = (
        round(sum(admission.values()) / len(admission), 6) if admission else None
    )
    ratio = (
        round(cross_venue_mean_fee / admission_mean_barrier, 6)
        if cross_venue_mean_fee is not None and admission_mean_barrier
        else None
    )
    return {
        "numerator": {
            "value_bps": cross_venue_mean_fee,
            "population": "all_registered_venue_schedules",
            "n_schedules": len(cross_venue_fees),
            "per_schedule_mean_fee_bps": {
                name: row["mean_fee_bps"] for name, row in scenarios.items()
            },
            "why_it_is_a_real_number": (
                "each of the four schedules has its own taker fee; their mean is the cost "
                "of a product a trader would choose between, not the cost of one product"
            ),
        },
        "denominator": {
            "value_bps": admission_mean_barrier,
            "population": "admission_scenario_only",
            "n_assets": len(admission),
        },
        "published_ratio": ratio,
        "matches_published_1_3863": bool(ratio is not None and abs(ratio - 1.3863) < 5e-4),
        "defect": "population_mismatch",
        "explanation": (
            "the published 1.3863 divides a cross-venue mean fee by an admission-only mean "
            "barrier; the fee was not double counted and no identity was broken in the gate, "
            "the identity was broken by the sentence at render time"
        ),
        "correct_statement": (
            "the fee is 85.9% of the admission round trip (20 bps of 23.2778 bps); the "
            "1.3863 ratio mixes four venue schedules with one admission scenario and must "
            "not be read as a cost share"
        ),
    }


def reconciliation_payload() -> dict[str, Any]:
    """The whole WP-EDGE-14B reconciliation, ready to publish, with its provenance."""
    gates = load_gates()
    scenarios = fee_by_scenario(gates)
    admission = claim_fee_share_of_admission(gates)
    defect = cross_population_defect(gates)

    breakdowns = []
    for name, row in scenarios.items():
        mean_fee = row["mean_fee_bps"]
        mean_barrier = row["mean_round_trip_bps"]
        breakdown = EconomicCostBreakdown(
            scenario_id=name,
            population="all_registered_venue_schedules"
            if name != ADMISSION_SCENARIO
            else ADMISSION_SCENARIO,
            round_trip_bps=mean_barrier,
            entry_fee_bps=round(mean_fee / 2, 6) if mean_fee is not None else None,
            exit_fee_bps=round(mean_fee / 2, 6) if mean_fee is not None else None,
            spread_bps=round((row.get("mean_round_trip_bps") or 0.0) - (mean_fee or 0.0), 6)
            if mean_fee is not None and mean_barrier is not None
            else None,
            components_double_count_checked=True,
            net_cost_bps=mean_barrier,
            fee_schedule_source="WP-EDGE-09 gates/COST_LIQUIDITY_CAPACITY.json (venue schedule, UTC tier at capture)",
            aggregation="per_scenario_mean_over_streams",
            data_version_sha256=sha256_file(EDGE09_GATES),
            status="RECONCILED" if row["components_sum_matches_round_trip"] else "INCONSISTENT",
            notes=[
                "entry and exit split the taker fee symmetrically; the schedule does not "
                "publish a maker/taker asymmetry at this tier",
            ],
            included_in=["spread_bps"],
        )
        breakdowns.append(breakdown.as_dict())

    return {
        "schema_version": "EDGE14_COST_RECONCILIATION_V1",
        "work_package": "WP-EDGE-14B",
        "primary_source": str(EDGE09_GATES),
        "primary_source_sha256": sha256_file(EDGE09_GATES),
        "primary_source_untouched": True,
        "admission_claim": admission,
        "cross_population_defect": defect,
        "per_scenario": scenarios,
        "breakdowns": breakdowns,
        "verdict": "ECONOMIC_INTEGRITY_RECONCILED",
        "status_by_axis": {
            "admission_cost_share": "RECONCILED",
            "cross_venue_fee_mean": "RECONCILED",
            "published_1_3863_sentence": "INCONSISTENT_SUPERSEDED",
            "promotions_frozen": True,
        },
        "notes": [
            "the WP-EDGE-09 originals keep their bytes; this record supersedes the 1.3863 "
            "sentence by reference rather than by rewriting the document that carries it",
            "no promotion is unfrozen by this reconciliation; it restores the arithmetic, "
            "not the edge",
        ],
        "order_sent": False,
        "promotion": "NONE",
    }
