"""Offline guards for the PROFITABILITY-GATE-035 closure artifacts.

These tests are network-free and do not re-run either script's verification pass. They assert the
properties a later edit is most likely to break: the formal closure values, the derived-not-typed
cost block, the internal consistency of the turnover arithmetic, the completeness of the root-cause
mapping, the fact that the proposal is a proposal, and the absence of any promotion claim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "reports" / "profitability_gate035"
PROPOSAL = REPO / "docs" / "roadmap" / "PROFITABILITY_DISCOVERY_PROPOSAL.md"

DELIVERABLES = (
    "FINAL_REPORT.md",
    "FINAL_REPORT.json",
    "SEARCH_POSTMORTEM.md",
    "ECONOMIC_FEASIBILITY.md",
    "ALTERNATIVE_PATHS.md",
    "INDEPENDENT_VERIFICATION.md",
)
REQUIRED_FIELDS = (
    "current_head",
    "rfc_035_final_status",
    "candidates_accepted",
    "rejection_root_causes",
    "current_runtime_state",
    "pending_technical_defects",
    "cost_feasibility",
    "recommended_next_path",
    "required_roadmap_amendment",
    "independent_verification",
    "false_success",
    "next_gate",
)
ROOT_CAUSES = ("RC-1", "RC-2", "RC-3", "RC-4", "RC-5", "RC-6", "RC-7", "RC-8")
FORBIDDEN = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY")
NEGATION_MARKERS = ("never", "not ", "no ", "false", "0", "cannot", "out of scope", "absence")


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads((OUT / "FINAL_REPORT.json").read_text(encoding="utf-8"))


def TEST_OPP(opportunity_id: str) -> Path:
    return REPO / "research" / "profitability" / "opportunities" / f"{opportunity_id}.json"


def test_all_deliverables_exist_and_are_not_empty() -> None:
    for name in DELIVERABLES:
        path = OUT / name
        assert path.is_file(), f"missing deliverable {name}"
        assert path.stat().st_size > 0, f"empty deliverable {name}"
    assert PROPOSAL.is_file() and PROPOSAL.stat().st_size > 0


def test_every_required_field_is_present(report: dict) -> None:
    for field in REQUIRED_FIELDS:
        assert field in report, f"missing §09 field {field}"
        assert report[field] is not None


def test_closure_values_are_exact(report: dict) -> None:
    closure = report["closure"]
    assert closure["RFC-035"] == "CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY"
    assert closure["REPLICATE_P0"] == "NONE"
    assert closure["RFC-036_REPLICATION"] == "BLOCKED"
    assert closure["PROFITABILITY_VERIFIED"] is False
    assert closure["TRADES_AUTHORIZED"] == 0
    assert closure["criteria_lowered"] is False
    assert closure["artifacts_preserved"] is True
    assert "universe" in closure["scope"]


def test_no_promotion_flag_is_set(report: dict) -> None:
    flags = report["flags"]
    assert flags["TRADES_AUTHORIZED"] == 0
    assert flags["PROFITABLE"] is False
    assert flags["EDGE_CONFIRMED"] is False
    assert flags["PRODUCTION_READY"] is False


def test_runtime_is_still_paper_and_unarmed(report: dict) -> None:
    runtime = report["current_runtime_state"]
    assert runtime["live_trading_enabled"] is False
    assert runtime["no_trade_is_first_class"] is True
    assert runtime["reference_capital_usdt"] == 200.0


def test_cost_is_derived_and_internally_consistent(report: dict) -> None:
    cost = report["cost_feasibility"]
    total = sum(float(c["value_bps"]) for c in cost["components"])
    assert abs(total - float(cost["round_trip_bps"])) < 1e-6
    known = sum(float(c["value_bps"]) for c in cost["components"] if c["knowledge"] == "KNOWN")
    assert abs(known - float(cost["known_bps"])) < 1e-6
    assert abs(float(cost["known_bps"]) + float(cost["estimated_bps"])
               - float(cost["round_trip_bps"])) < 1e-6
    assert float(cost["round_trip_bps"]) >= 23.79, "the cost must not be reduced below the documented floor"
    assert round(float(cost["round_trip_bps"]), 3) == 23.791
    # known_share is stored to 4 decimal places, so half a unit in the last place is the tightest
    # tolerance the artifact can support.
    assert abs(float(cost["known_share"]) - float(cost["known_bps"]) / float(cost["round_trip_bps"])) < 5e-5


def test_turnover_arithmetic_uses_the_measured_cost(report: dict) -> None:
    cost = report["cost_feasibility"]
    total = float(cost["round_trip_bps"])
    stress = float(cost["stress_multiple"])
    assert cost["turnover_cost_drag"], "the drag table must not be empty"
    for entry in cost["turnover_cost_drag"]:
        n = float(entry["round_trips_per_year"])
        # `total` is the artifact's own 4-dp value, so the rounding budget grows with n. The bps figure
        # is stored in bps; the two percentages are stored to 4 decimal places of a percent, so their
        # budget is half a unit in that last place plus the propagated rounding of `total`.
        tol_bps = 5e-5 * n + 5e-5
        tol_pct = 5e-5 + 5e-5 * n / 100.0
        assert abs(float(entry["annual_drag_bps"]) - total * n) < tol_bps, entry["label"]
        assert abs(float(entry["annual_drag_pct"]) - total * n / 100.0) < tol_pct, entry["label"]
        assert abs(float(entry["annual_drag_stressed_pct"]) - total * n * stress / 100.0) < tol_pct, entry["label"]
    frequencies = [e["round_trips_per_year"] for e in cost["turnover_cost_drag"]]
    assert frequencies == sorted(frequencies)
    assert len(set(frequencies)) == len(frequencies)


def test_cost_reports_known_and_assumed_separately(report: dict) -> None:
    cost = report["cost_feasibility"]
    assert cost["known_vs_assumed"], "the known/assumed list must not be empty"
    assert any("KNOWN" in x and "fee" in x for x in cost["known_vs_assumed"])
    assert cost["validity_scope"], "a validity scope must be stated"
    assert cost["measurement_origin"]["doc"]
    assert all(float(c["value_bps"]) >= 0 for c in cost["components"])


def test_every_scenario_and_sensitivity_is_present(report: dict) -> None:
    cost = report["cost_feasibility"]
    assert len(cost["scenarios"]) >= 8
    assert sum(1 for s in cost["scenarios"] if s["is_admission"]) == 1
    assert [e["size_usd"] for e in cost["size_sensitivity"]] == sorted(
        e["size_usd"] for e in cost["size_sensitivity"])
    regimes = {e["liquidity_regime"] for e in cost["liquidity_sensitivity"]}
    assert regimes == {"deep", "normal", "thin"}
    thin = next(e["round_trip_bps"] for e in cost["liquidity_sensitivity"] if e["liquidity_regime"] == "thin")
    deep = next(e["round_trip_bps"] for e in cost["liquidity_sensitivity"] if e["liquidity_regime"] == "deep")
    assert thin > deep


def test_root_causes_cover_all_eight_and_are_owned(report: dict) -> None:
    block = report["rejection_root_causes"]
    causes = {c["code"]: c for c in block["causes"]}
    assert set(causes) == set(ROOT_CAUSES)
    for code, entry in causes.items():
        assert entry["owner"] in ("SOURCE", "MARKET", "CONTRACT", "CONTRACT_AND_RUNTIME"), code
        assert isinstance(entry["reason_code_hits"], int)
    counts = block["round_2_reason_counts"]
    assert sum(c["reason_code_hits"] for c in causes.values()) == sum(int(v) for v in counts.values())
    assert not block["unmapped_reason_codes"]
    assert causes["RC-5"]["owner"] == "MARKET"


def test_root_cause_review_refuses_to_infer_absence_of_alpha(report: dict) -> None:
    notes = report["rejection_root_causes"]["not_concluded"]
    assert notes
    assert any("no profitable opportunity exists" in n.lower()
               or "not evidence of absence" in n.lower() for n in notes)


def test_recommendation_is_a_proposal_not_a_decision(report: dict) -> None:
    route = report["recommended_next_path"]
    assert route["route"] in ("A", "B", "C")
    assert route["status"] == "PROPOSED"
    assert len(route["comparison_matrix"]) == 8
    for row in route["comparison_matrix"]:
        assert row["A"] and row["B"] and row["C"]
    amendment = report["required_roadmap_amendment"]
    assert amendment["status"] == "PROPOSED_NOT_ACTIVATED"
    assert amendment["proposed_id"] == "RFC-046"
    assert amendment["reserved"]["RFC-036"] == "exact external replication"
    assert len(amendment["required_changes"]) == 4


def test_proposal_states_the_protocol_and_stays_inactive() -> None:
    text = PROPOSAL.read_text(encoding="utf-8")
    assert "PROPOSED" in text and "NOT ACTIVATED" in text
    for pid in (f"P-{i:02d}" for i in range(1, 14)):
        assert pid in text, f"missing protocol requirement {pid}"
    for clause in ("economic hypothesis", "point-in-time", "out-of-sample", "independent verifier",
                   "stop rule", "next_action_policy.trigger", "tasks/roadmap.md"):
        assert clause in text.lower() or clause in text, clause


def test_catalogue_and_registry_are_consistent(report: dict) -> None:
    registry = json.loads((REPO / "research" / "profitability" / "source_registry.json").read_text(encoding="utf-8"))
    audit = report["baseline_audit"]
    assert audit["catalogue"]["sources"] == len(registry["sources"])
    ids = [s["SOURCE_ID"] for s in registry["sources"]]
    assert len(set(ids)) == len(ids)
    assert audit["catalogue"]["round_sum"] == len(registry["sources"])
    opp_files = sorted((REPO / "research" / "profitability" / "opportunities").glob("OPP-*.json"))
    assert audit["opportunities"]["total"] == len(opp_files)
    assert [r["rfc"] for r in registry["rounds"]] == ["RFC-035", "RFC-035S2", "RFC-035S3"]
    for entry in audit["opportunities"]["superseded_in_round_3"].items():
        oid, current = entry
        record = json.loads(TEST_OPP(oid).read_text(encoding="utf-8"))
        assert record["current_rank"] == current
        assert record["rank"] != record["current_rank"]


def test_baseline_separates_observed_from_reproduced(report: dict) -> None:
    reproduction = report["baseline_reproduction"]
    assert reproduction["reproduced_in_this_run"]
    assert reproduction["observed_earlier_not_rerun"]
    assert "not rewritten" in reproduction["policy"]


def test_cap004b_and_campaign_are_quoted_faithfully(report: dict) -> None:
    real = json.loads((REPO / "reports" / "cap004b" / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    cap = report["baseline_audit"]["cap004b"]
    assert cap["verdict"] == real["VERDICT"]
    assert cap["sealed"] == real["SEALED"]
    assert cap["false_success"] == real["FALSE_SUCCESS"]
    manifest = json.loads(
        (REPO / "evidence" / "real_decisions" / "CAMPAIGN_MANIFEST.json").read_text(encoding="utf-8"))
    campaign = report["baseline_audit"]["campaign"]
    assert campaign["campaign_id"] == manifest["campaign_id"]
    assert campaign["trades_authorized"] == manifest["trades_authorized"] == 0
    assert campaign["alpha_research_freeze"] == "ACTIVE"


def test_independent_verification_recorded_its_own_result() -> None:
    iv = json.loads((OUT / "INDEPENDENT_VERIFICATION.json").read_text(encoding="utf-8"))
    assert iv["status"] == "PASS"
    assert iv["mismatches"] == 0
    assert iv["false_success"] == 0
    assert iv["checks"] == iv["passed"] == len(iv["all_checks"])
    assert iv["builder_imported"] is False
    assert iv["verifier"] != iv["builder"]


def test_negative_controls_are_recorded() -> None:
    payload = json.loads((OUT / "INDEPENDENT_VERIFICATION.json").read_text(encoding="utf-8"))
    controls = [c for c in payload["all_checks"] if c["check"].startswith("NEGATIVE CONTROL")]
    assert len(controls) >= 6
    assert all(c["ok"] for c in controls)


@pytest.mark.parametrize("name", DELIVERABLES)
def test_no_artifact_asserts_a_forbidden_success(name: str) -> None:
    path = OUT / name
    if path.suffix != ".md":
        return
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        lowered = line.lower()
        for token in FORBIDDEN:
            if token in line and not any(marker in lowered for marker in NEGATION_MARKERS):
                if f'"status": "{token}"' in line:
                    continue
                pytest.fail(f"{name}:{lineno} asserts {token}: {line.strip()[:120]}")
