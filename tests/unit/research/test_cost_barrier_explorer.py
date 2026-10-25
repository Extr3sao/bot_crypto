"""Contract tests for the COST-BARRIER EXPLORER (WP-6).

The explorer is held to what it claims:

* every cell's edge is the WP-3 audit's own published number, never a
  re-measurement or an interpolation;
* reachability is exactly "gross strictly above the stressed line" -
  re-derived mechanically here for all 120 configurations and 4 stress levels;
* a missing edge is reported as UNKNOWN and is never counted as reachable;
* the boundary is strict: a cell that exactly pays its costs is not reachable;
* the horizon claims are measurements (flat at zero funding, funding-only
  otherwise), not assertions;
* the artefact cannot touch the sources it reads, and rebuilds bit-for-bit;
* the independent verifier accepts the committed artefact and rejects corrupted
  copies of it - including one where the fabricated edge would flip a verdict.

The scripts are imported as modules, so the tests exercise the same functions the
artefacts were produced by.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RECOVERY = ROOT / "data" / "recovery"


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def explorer():
    return load_script("cost_barrier_explorer")


@pytest.fixture(scope="module")
def verifier():
    return load_script("cost_barrier_verify")


@pytest.fixture(scope="module")
def built(explorer):
    return explorer.build()


@pytest.fixture(scope="module")
def stored():
    return json.loads((RECOVERY / "COST_BARRIER_EXPLORER.json").read_text(encoding="utf-8"))


def test_payload_hash_reproduces_and_matches_the_committed_artefact(explorer, built, stored):
    first = explorer.payload_hash(built)
    second = explorer.payload_hash(explorer.build())
    assert first == second, "a rebuild changed the explorer's identity"
    assert first == stored["payload_sha256"], (
        "the committed artefact is not the fresh build; rerun scripts/cost_barrier_explorer.py"
    )


def test_reading_the_sources_leaves_them_byte_identical(built):
    paths = [built["sources"][i]["path"] for i in range(len(built["sources"]))]
    before = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in paths}
    load_script("cost_barrier_explorer").build()
    after = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in paths}
    assert before == after


def test_every_cell_edge_is_the_audits_own_published_value(built):
    audit = json.loads((RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json").read_text(encoding="utf-8"))
    assert len(built["cells"]) == audit["strategy_count"] == 24
    for cell in built["cells"]:
        published = audit["strategies"][cell["cell_id"]]["economics"]["zero_cost_gross_bps"]
        assert cell["zero_cost_gross_bps"] == published
        assert cell["gross_evidence"].startswith("ZERO_COST")


def test_reachability_is_strictly_above_the_stressed_line(built):
    seen = 0
    for row in built["reachability"]["matrix"]:
        cfg = next(
            c for c in built["venue_grid"]
            if (c["scenario_id"], c["order_mode"], c["size_usd"], c["liquidity_regime"])
            == (row["scenario_id"], row["order_mode"], row["size_usd"], row["liquidity_regime"])
        )
        for multiple in (1.0, 1.25, 1.5, 2.0):
            required = cfg["round_trip_bps"] * multiple
            expected = sorted(
                c["cell_id"] for c in built["cells"]
                if c["zero_cost_gross_bps"] is not None and c["zero_cost_gross_bps"] > required
            )
            assert row["reachable_counts_by_stress"][f"{multiple}x"] == len(expected)
            seen += 1
        assert sorted(row["reachable_cell_ids"]) == sorted(
            c["cell_id"] for c in built["cells"]
            if c["zero_cost_gross_bps"] is not None
            and c["zero_cost_gross_bps"] > cfg["round_trip_bps"]
        )
    assert seen == len(built["reachability"]["matrix"]) * 4


def test_no_cell_clears_a_line_priced_without_an_assumed_component(built):
    frontier = built["reachability"]["frontier"]
    observed = frontier["cheapest_line_observed_only"]
    assert observed["rests_on_assumed_component"] is False
    assert frontier["reachable_cells_observed_only"] == 0
    assert frontier["max_zero_cost_gross_bps"] < observed["round_trip_bps"]
    # the lines that do carry a cell all rest on an ASSUMED maker fill model
    for row in built["reachability"]["matrix"]:
        if row["reachable_counts_by_stress"]["1.0x"] > 0:
            assert row["rests_on_assumed_component"] is True
            assert row["knowledge_class"] == "ASSUMED"


def test_horizon_claims_are_measured(built):
    model_horizon = built["horizon"]["model_horizon"]
    assert model_horizon["verdict"] == "HORIZON_INVARIANT_AT_ZERO_FUNDING"
    assert all(row["max_minus_min_bps"] == 0.0 for row in model_horizon["rows"])
    assert len(model_horizon["rows"]) >= 2 * len({r["scenario_id"] for r in model_horizon["rows"]})

    funding = built["horizon"]["funding_horizon"]
    assert funding["minute_per_interval_derived"] == 480.0
    drift = [
        abs(float(row["funding_carry_bps"]) - float(row["analytic_carry_bps"]))
        for row in funding["rows"] if row["analytic_carry_bps"] is not None
    ]
    assert drift and max(drift) <= 1e-9
    by_horizon = {
        (row["scenario_id"], row["order_mode"], row["funding_rate_bps_per_interval"], row["horizon_minutes"]):
        row["funding_carry_bps"] for row in funding["rows"]
    }
    key = ("BINANCE_USDM_PERP_TAKER", "taker", 1.0)
    assert by_horizon[(*key, 1440.0)] > by_horizon[(*key, 480.0)] > by_horizon[(*key, 240.0)] == 0.5


def test_the_market_horizon_is_reused_not_redefined(built):
    market = built["horizon"]["market_horizon"]
    assert market["source_definition"] == "bars_to_X = median bars for a move equal to X bps"
    assert {row["timeframe"] for row in market["rows"]} == {c["timeframe"] for c in built["cells"]}
    worst = {
        tf: min(row["abs_ret_bps_median"] for row in market["rows"] if row["timeframe"] == tf)
        for tf in {row["timeframe"] for row in market["rows"]}
    }
    assert worst["5m"] < worst["15m"] < worst["30m"] < worst["1h"]


def test_a_missing_edge_is_unknown_and_never_counted(explorer, built):
    cells = [dict(c) for c in built["cells"]]
    cells.append({
        "cell_id": "synthetic@99m", "strategy_id": "synthetic@99m", "family": "synthetic",
        "timeframe": "99m", "ledger_status": "NO_GROSS_EDGE", "admitted_for_paper": False,
        "zero_cost_gross_bps": None, "gross_evidence": "ZERO_COST",
        "trades": None, "sample_sufficient": False, "runtime_admission_rt_bps": None,
    })
    reach = explorer.reachability(cells, built["venue_grid"])
    row = next(r for r in reach["cell_view"] if r["cell_id"] == "synthetic@99m")
    assert row["verdict"] == "UNKNOWN_GROSS_EDGE_NOT_PUBLISHED"
    assert "best_configuration" not in row
    for cfg in reach["matrix"]:
        assert "synthetic@99m" not in cfg["reachable_cell_ids"]


def test_boundary_is_strict_and_a_fabricated_edge_flips_the_verdict(explorer, built):
    line = built["reachability"]["frontier"]["cheapest_line_any"]["round_trip_bps"]
    rows = built["venue_grid"]
    for label, gross, expected in (
        ("exactly at the cheapest line", line, "NOT_REACHABLE_AT_ANY_MODELED_VENUE"),
        ("one bps above the cheapest line", line + 1.0,
         "REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL"),
    ):
        cells = [dict(c) for c in built["cells"]]
        cells.append({
            "cell_id": f"synthetic:{label}", "strategy_id": f"synthetic:{label}",
            "family": "synthetic", "timeframe": "99m", "ledger_status": "NO_GROSS_EDGE",
            "admitted_for_paper": False, "zero_cost_gross_bps": gross,
            "gross_evidence": "SYNTHETIC TEST CELL", "trades": 1000,
            "sample_sufficient": True, "runtime_admission_rt_bps": None,
        })
        reach = explorer.reachability(cells, rows)
        row = next(r for r in reach["cell_view"] if r["cell_id"] == f"synthetic:{label}")
        assert row["verdict"] == expected, label


def test_the_three_operations_frequency_axis_is_cost_only(built):
    frequency = built["frequency"]
    assert frequency["published_current_operations_per_day"] == 0
    assert frequency["requirement_round_trips_per_year"] == 1095.0
    for row in frequency["rows"]:
        assert row["annual_cost_bps"] == pytest.approx(row["round_trip_bps"] * 1095.0, rel=1e-12)
        assert row["annual_cost_bps"] == pytest.approx(row["annual_cost_pct_of_stake"] * 100.0,
                                                       rel=1e-9)


def test_the_verifier_accepts_the_committed_artefact(verifier, stored):
    truth = verifier.recompute()
    assert verifier.compare(stored, truth) == []
    assert truth["cells"][truth["best_cell"]]["gross"] < truth["configs"][truth["cheapest_observed"]]["round_trip_bps"]


def test_the_verifier_rejects_a_fabricated_edge(verifier, stored):
    truth = verifier.recompute()
    mutated = deepcopy(stored)
    for row in mutated["cells"]:
        row["zero_cost_gross_bps"] += 20.0
    mismatches = verifier.compare(mutated, truth)
    assert mismatches, "a fabricated edge was accepted"


def test_the_verifier_rejects_a_flipped_verdict_and_a_broken_hash(verifier, stored):
    truth = verifier.recompute()
    flipped = deepcopy(stored)
    for row in flipped["reachability"]["cell_view"]:
        if row["verdict"] == "NOT_REACHABLE_AT_ANY_MODELED_VENUE":
            row["verdict"] = "REACHABLE_TAKER"
            break
    assert verifier.compare(flipped, truth)
    tampered = deepcopy(stored)
    tampered["payload_sha256"] = "0" * 64
    assert verifier.compare(tampered, truth)


def test_markdown_carries_the_headline_and_no_promotion_claim(explorer, built):
    text = explorer.render_markdown({**built, "payload_sha256": explorer.payload_hash(built)})
    frontier = built["reachability"]["frontier"]
    assert f"{frontier['max_zero_cost_gross_bps']}" in text
    assert "reachable on an observed-only line: **0**" in text
    assert "HORIZON_INVARIANT_AT_ZERO_FUNDING" in text
    for forbidden in ("RENTABLE", "CERTIFIED", "PRODUCTION_READY"):
        assert forbidden not in text or "Nothing here declares" in text


def test_the_committed_verification_document_is_clean():
    doc = json.loads((RECOVERY / "COST_BARRIER_VERIFICATION.json").read_text(encoding="utf-8"))
    assert doc["status"] == "PASS"
    assert doc["checks_failed"] == 0
    assert doc["controls_total"] >= 10
    assert doc["controls_missed"] == 0
    assert doc["false_success"] == 0
    assert doc["builder_imported"] is False
    assert doc["verifier"] != doc["builder"]


def test_governance_flags_stay_unauthorized(built):
    claims = built["claims"]
    assert claims["authorization_state"] == "NOT_AUTHORIZED"
    assert claims["trades_authorized"] == 0
    assert claims["false_success"] == 0
    for flag in ("promotion_claimed", "rentable_claimed", "certified_claimed",
                 "production_ready_claimed"):
        assert claims[flag] is False
    assert built["checks_failed"] == 0
