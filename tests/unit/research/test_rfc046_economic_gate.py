"""Independent verification of the RFC-046 economic feasibility report.

These tests take the *frozen constants* from ``docs/COST_MODEL_V3.json`` and the *published medians*
from the report, and re-derive every claim the report makes: the toll, the fee dominance, the
break-even, the turnover table, the family verdicts and the standing limits.  They never import the
builder's functions except for the two pure rules, which are tested directly against their stated
definition.

The route differs from both the builder (which re-simulates nothing but uses the model library) and
the verifier script (which reads the 1-hour series): here the median/verdict relationship is tested
as a *rule*, and the artefact is pinned against the governance documents.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
REPORT = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.json"
REPORT_MD = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.md"
VERIFICATION = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY_VERIFICATION.json"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
RFC046 = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
RUN_JSON = REPO / "data" / "rfc046" / "RUN_REPORT.json"
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"

BPS = 10_000.0
CAPITAL = 200.0
DOCUMENTED_SIZE = 1000.0
ADMISSION = "BINANCE_SPOT_STANDARD_TAKER"
MAKER = "BINANCE_SPOT_STANDARD_MAKER"
FAMILIES = (
    "scalping",
    "intraday",
    "mean_reversion",
    "momentum",
    "swing_trading",
    "trend_following",
)
FORBIDDEN_TOKENS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")
SCOPE_VERDICTS = (
    "VIABLE_COST_PROFILE_IDENTIFIED",
    "NO_VIABLE_PROFILE_IDENTIFIED",
    "INSUFFICIENT_EVIDENCE",
)
COST_VERDICTS = ("NOT_COST_COMPATIBLE", "COST_BOUNDARY", "COST_COMPATIBLE")


def _load_builder() -> object:
    spec = importlib.util.spec_from_file_location(
        "rfc046_economic_gate", REPO / "scripts" / "rfc046_economic_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def verification() -> dict:
    return json.loads(VERIFICATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def model() -> dict:
    return json.loads(COST_MODEL.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def constants(model: dict) -> dict:
    return model["model_constants"]


def _scenario(model: dict, scenario_id: str) -> dict:
    return next(s for s in model["scenarios"] if s["evaluation"]["scenario_id"] == scenario_id)


def _size_factor(size: float, constants: dict) -> float:
    return 1.0 + math.sqrt(size / float(constants["reference_notional_usd"]))


def _taker_toll(size: float, model: dict) -> float:
    """Fee + spread + slippage + impact, written out from the frozen constants."""
    scenario = _scenario(model, ADMISSION)
    spec, constants = scenario["spec"], model["model_constants"]
    factor = _size_factor(size, constants)
    return (
        2.0 * float(spec["taker_fee_bps"])
        + float(spec["default_taker_spread_bps"])
        + float(constants["base_slippage_bps"]) * factor * 2.0
        + float(constants["base_impact_bps"]) * (factor - 1.0) * 2.0
    )


def _maker_toll(model: dict) -> float:
    constants = model["model_constants"]
    fee = 2.0 * float(_scenario(model, MAKER)["spec"]["maker_fee_bps"])
    p = float(constants["maker_fill_prob"])
    return (
        fee
        + float(constants["maker_adverse_selection_bps"]) * 2.0
        + float(constants["maker_partial_fill_penalty_bps"]) * (1.0 - p) * 2.0
        + fee * (1.0 / p - 1.0)
    )


def test_artefacts_exist_and_are_verified_clean(report: dict, verification: dict) -> None:
    for path in (REPORT, REPORT_MD, VERIFICATION):
        assert path.is_file() and path.stat().st_size > 0, f"missing {path.name}"
    assert verification["status"] == "PASS", verification["failures"]
    assert verification["mismatches"] == 0
    assert verification["false_success"] == 0
    assert verification["builder_equals_verifier"] is False
    assert verification["checks_passed"] == verification["checks_total"]
    assert (
        verification["verified_artifact_sha256"] == hashlib.sha256(REPORT.read_bytes()).hexdigest()
    ), "the verification must cover the artefact as shipped"


def test_the_toll_at_both_reference_sizes_recomputes_from_the_frozen_constants(
    report: dict, model: dict
) -> None:
    audit = report["cost_audit"]
    assert audit["at_documented_reference_size"]["round_trip_bps"] == pytest.approx(
        _taker_toll(DOCUMENTED_SIZE, model), abs=1e-9
    )
    assert audit["at_reference_capital"]["round_trip_bps"] == pytest.approx(
        _taker_toll(CAPITAL, model), abs=1e-9
    )
    recorded = float(_scenario(model, ADMISSION)["evaluation"]["round_trip_bps"])
    assert audit["at_documented_reference_size"]["round_trip_bps"] == pytest.approx(
        recorded, abs=1e-4
    ), "the report must reproduce the figure the frozen model recorded"


def test_the_size_term_halves_at_its_documented_reference(constants: dict) -> None:
    """The model documents the reference notional as the size at which the term doubles."""
    assert _size_factor(float(constants["reference_notional_usd"]), constants) == pytest.approx(2.0)
    assert _size_factor(DOCUMENTED_SIZE, constants) == pytest.approx(1.316227766, abs=1e-9)


def test_the_toll_is_fee_dominated_and_the_shares_recompute(report: dict, model: dict) -> None:
    dominance = report["cost_audit"]["fee_dominance_at_200_usdt"]
    toll = report["cost_audit"]["at_reference_capital"]["round_trip_bps"]
    assert dominance["exchange_fees_bps"] == pytest.approx(20.0)
    assert dominance["fees_share_of_round_trip"] == pytest.approx(20.0 / toll, abs=1e-9)
    assert dominance["fees_share_of_round_trip"] > 0.8, "the fee schedule dominates the toll"
    parts = sum(c["value_bps"] for c in report["cost_audit"]["at_reference_capital"]["components"])
    assert parts == pytest.approx(toll, abs=1e-9), "the published components must sum to the toll"
    assert dominance["non_fee_bps"] == pytest.approx(toll - 20.0, abs=1e-9)


def test_the_maker_path_is_priced_by_the_model_and_declared_inadmissible(
    report: dict, model: dict
) -> None:
    maker = report["cost_audit"]["maker_path"]
    assert maker["at_documented_reference_size"]["round_trip_bps"] == pytest.approx(
        _maker_toll(model), abs=1e-9
    )
    assert maker["at_reference_capital"]["size_invariant"] is True
    assert maker["premium_over_taker_bps"] > 0.0, "at VIP0 passivity buys no fee saving"
    assert report["break_even"]["maker_modality"]["admissible"] is False
    execution = json.loads((REPO / "docs" / "EXECUTION_MODEL_V1.json").read_text(encoding="utf-8"))
    assert execution["status"] == "EXECUTION_MODEL_REQUIRED", (
        "the maker path stays inadmissible only while no fill evidence exists; if this changed, "
        "the economic conclusion must be revisited"
    )


def test_break_even_follows_the_toll_and_not_a_rounded_copy(report: dict, model: dict) -> None:
    section = report["break_even"]
    toll = _taker_toll(CAPITAL, model)
    cost_per_op = CAPITAL * toll / BPS
    assert section["minimum_gross_move_bps_per_round_trip"] == pytest.approx(toll, abs=1e-9)
    assert section["minimum_gross_move_usdt_per_round_trip"] == pytest.approx(cost_per_op, abs=1e-8)
    assert section["minimum_expectancy_bps_to_be_net_positive"] == pytest.approx(toll, abs=1e-9)
    assert section["required_gross_edge_bps_at_1p5x_stress"] == pytest.approx(1.5 * toll, abs=1e-9)
    three = section["three_daily_round_trips_illustrative"]
    assert three["cost_per_day_usdt"] == pytest.approx(3 * cost_per_op, abs=1e-8)
    assert three["cost_per_year_multiple_of_capital"] == pytest.approx(
        3 * 365 * cost_per_op / CAPITAL, abs=1e-9
    )
    assert three["cost_per_year_multiple_of_capital"] > 2.5, (
        "three round trips a day costs the account its capital several times a year in tolls"
    )


def test_the_frozen_campaign_figure_is_compared_not_silently_replaced(report: dict) -> None:
    frozen = report["break_even"]["frozen_campaign_comparison"]
    assert frozen["frozen_admission_bps"] == pytest.approx(23.7906)
    assert frozen["frozen_stress_threshold_bps"] == pytest.approx(23.7906 * 1.5, abs=1e-9)
    assert frozen["stress_delta_bps"] >= 0.0, (
        "the gate the campaign actually used must not be less demanding than a 1.5x stress at 200"
    )


def test_the_turnover_table_is_arithmetic_not_opinion(report: dict, model: dict) -> None:
    section = report["break_even"]["turnover_sensitivity"]
    toll = _taker_toll(CAPITAL, model)
    cost_per_op = CAPITAL * toll / BPS
    target = section["target_net_usdt"]
    assert target == pytest.approx(CAPITAL * 0.20)
    for row in section["rows"]:
        per_year = row["round_trips_per_day"] * 365.0
        assert row["annual_cost_usdt"] == pytest.approx(per_year * cost_per_op, abs=1e-8), row[
            "round_trips_per_day"
        ]
        assert row["annual_cost_pct_of_capital"] == pytest.approx(
            per_year * cost_per_op / CAPITAL, abs=1e-9
        )
        net_margin = (target / per_year) / CAPITAL * BPS
        assert row["net_margin_bps_per_trade"] == pytest.approx(net_margin, abs=1e-9)
        assert row["gross_bps_per_trade_to_net_target"] == pytest.approx(
            toll + net_margin, abs=1e-9
        )
        assert row["cost_overrun_bps_that_erases_target"] == pytest.approx(
            row["net_margin_bps_per_trade"], abs=1e-9
        ), "the margin over the toll is exactly what a cost overrun would erase"
    shares = {r["round_trips_per_day"]: r["net_margin_share_of_gross"] for r in section["rows"]}
    assert shares[10.0] < shares[3.0] < shares[1.0] < shares[0.2], (
        "the higher the turnover, the thinner the margin over the toll"
    )


def test_every_family_verdict_follows_the_published_rule(report: dict) -> None:
    families = report["family_classification"]
    boundary = families["boundary_capture"]
    assert set(families["families"]) == set(FAMILIES)
    for name, row in families["families"].items():
        median, toll = row["median_abs_move_bps"], row["cost_bps"]
        expected = (
            "NOT_COST_COMPATIBLE"
            if median <= toll
            else ("COST_BOUNDARY" if toll / median >= boundary else "COST_COMPATIBLE")
        )
        assert row["cost_verdict"] == expected, f"{name}: {row['cost_verdict']} != {expected}"
        assert row["cost_verdict"] in COST_VERDICTS
        assert row["capture_required_to_break_even"] == pytest.approx(toll / median, abs=1e-6)
        assert row["edge_existence"] == "NOT_DEMONSTRATED", "no family may claim an edge"
        assert 0.0 <= row["share_of_windows_below_cost"] <= 1.0
    assert families["families"]["scalping"]["cost_verdict"] == "NOT_COST_COMPATIBLE"
    assert families["families"]["scalping"]["capture_required_to_break_even"] > 2.0


def test_the_horizon_table_is_measured_on_the_campaign_bars(report: dict) -> None:
    measurement = report["horizon_measurement"]
    assert measurement["assets"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    for asset in measurement["assets"]:
        path = REPO / "data" / "raw" / "alpha003" / "price" / f"{asset}_5m.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert measurement["bars_available_per_asset"][asset] == len(rows)
    # The JSON is written with sorted keys, so ordering by the declared window size rather than by
    # the dict's iteration order is what makes the monotonicity claim checkable.
    by_window = sorted(
        measurement["per_horizon"].items(), key=lambda item: item[1]["bars_per_window"]
    )
    windows = [row["bars_per_window"] for _, row in by_window]
    medians = [row["median_abs_move_bps"] for _, row in by_window]
    assert windows == sorted(set(windows)), "each horizon must have a distinct window size"
    assert medians == sorted(medians), "the measured median move must grow with the horizon"
    assert by_window[0][0] == "5m" and by_window[-1][0] == "168h"
    assert medians[0] < report["break_even"]["minimum_gross_move_bps_per_round_trip"], (
        "at five minutes the typical move is smaller than the toll"
    )


def test_the_cost_verdict_rule_is_the_documented_one() -> None:
    builder = _load_builder()
    toll = 23.0
    assert builder._cost_verdict(10.0, toll) == "NOT_COST_COMPATIBLE"
    assert builder._cost_verdict(toll, toll) == "NOT_COST_COMPATIBLE"
    assert builder._cost_verdict(40.0, toll) == "COST_BOUNDARY"
    assert builder._cost_verdict(200.0, toll) == "COST_COMPATIBLE"


def test_the_rfc046_confirmations_match_the_recorded_artefacts(report: dict) -> None:
    review = report["rfc046_review"]
    forensics = json.loads(FORENSICS.read_text(encoding="utf-8"))
    run_report = json.loads(RUN_JSON.read_text(encoding="utf-8"))
    assert (
        review["sources"]["run_report_sha256"] == hashlib.sha256(RUN_JSON.read_bytes()).hexdigest()
    )
    assert (
        review["sources"]["cost_forensics_sha256"]
        == hashlib.sha256(FORENSICS.read_bytes()).hexdigest()
    )

    c1 = forensics["candidates"]["CAND-046-001"]
    claim = review["confirmations"]["CAND-046-001_has_no_gross_edge_out_of_sample"]
    assert claim["confirmed"] is True
    assert claim["oos_gross_bps"] == c1["oos_gross_expectancy_bps"] < 0.0
    assert claim["aggregate_is_stable_across_partitions"] is False
    assert "final_oos" in claim["partitions_without_gross_edge"]

    c2 = forensics["candidates"]["CAND-046-002"]
    claim2 = review["confirmations"]["CAND-046-002_loses_before_costs"]
    assert claim2["confirmed"] is True and claim2["gross_bps"] == c2["gross_expectancy_bps"] < 0.0

    c3 = forensics["candidates"]["CAND-046-003"]
    claim3 = review["confirmations"]["CAND-046-003_stays_zero_sample"]
    assert claim3["confirmed"] is True and claim3["trades_total"] == c3["trades_total"] == 0

    policy = review["oos_policy"]
    assert policy["reused_for_selection"] is False
    assert policy["new_hypotheses_generated"] == 0
    assert policy["candidates_re_evaluated"] == 0
    assert policy["spec_count"] == len(list(SPECS.glob("HYP-*.json"))) == 3
    recorded = {r["hypothesis_id"]: r["spec_hash"] for r in run_report["runs"]}
    assert policy["spec_hashes"] == recorded, "the frozen specs must match the campaign record"


def test_the_standing_limits_are_read_from_the_governance_documents(report: dict) -> None:
    state = report["standing_state"]
    rfc = json.loads(RFC046.read_text(encoding="utf-8"))
    operating = json.loads(OPERATING_MODEL.read_text(encoding="utf-8"))
    run_report = json.loads(RUN_JSON.read_text(encoding="utf-8"))
    assert state["campaign_status"] == run_report["campaign"]["campaign_status"]
    assert state["campaign_status"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert state["next_campaign"] == "NOT_AUTHORIZED"
    assert state["trades_authorized"] == rfc["runtime_state"]["trades_authorized"] == 0
    assert (
        state["profitability_verified"] is False is rfc["runtime_state"]["profitability_verified"]
    )
    assert state["live_trading"] is False is rfc["runtime_state"]["live_trading_enabled"]
    exemption = operating["next_action_policy"]["rfc046_limited_exemption"]
    assert (
        state["G_BUSINESS_REENTRY"] == exemption["gate_state"]["G_BUSINESS_REENTRY"] == "NOT_PASS"
    )
    assert state["false_success"] == 0 and report["false_success"] == 0
    assert rfc["invariants_while_active"]["real_orders"] == "REFUSED_BY_POLICY"


def test_the_decision_stays_inside_the_allowed_vocabulary(report: dict) -> None:
    decision = report["decision"]
    assert decision["scope_recommendation"] in SCOPE_VERDICTS
    assert decision["not_an_edge_claim"] is True
    assert decision["edge_status"] == "NOT_DEMONSTRATED"
    assert decision["next_campaign"] == "NOT_AUTHORIZED"
    assert decision["profile"]["round_trip_bps_at_200_usdt"] == pytest.approx(
        report["break_even"]["minimum_gross_move_bps_per_round_trip"], abs=1e-9
    )
    text = json.dumps(report, ensure_ascii=False) + REPORT_MD.read_text(encoding="utf-8")
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"the artefact must not claim {token}"
    assert "NONE" in report["admission_effect"]
    assert "admits nothing" in report["admission_effect"]


def test_the_run_records_its_own_instant_and_head(report: dict) -> None:
    stamp = report["generated_at_utc"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp), stamp
    forensics_stamp = json.loads(FORENSICS.read_text(encoding="utf-8"))["generated_at_utc"]
    assert stamp >= forensics_stamp, "the economic gate follows the forensics it builds on"
    assert re.fullmatch(r"[0-9a-f]{40}", report["head_at_run"]), report["head_at_run"]
    assert report["builder"].endswith("rfc046_economic_gate.py")
    assert report["builder_equals_verifier"] is False
