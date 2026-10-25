"""RFC-049 Discovery 2 — contract tests for the Phase B artifacts.

Offline: they validate the delivered evidence contracts, the authorization record, the
frozen-baseline integrity and the verifier's independence; they do not re-run economics.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
D2 = ROOT / "data" / "rfc049" / "discovery2"
DATA = ROOT / "data" / "rfc049"

DELIVERABLES = (
    "DISCOVERY2_EXECUTION_PLAN.md",
    "CAMPAIGN_AUTHORIZATION.json",
    "DISCOVERY2_STATISTICAL_ELIGIBILITY.json",
    "ECONOMIC_RESULTS.json",
    "FILTER_ABLATION.md",
    "FILTER_ABLATION.json",
    "ACTIVE_STRATEGY_STATUS.md",
    "ACTIVE_STRATEGY_STATUS.json",
    "INDEPENDENT_VERIFICATION.json",
    "CAMPAIGN_CLOSURE.json",
    "CAMPAIGN_CLOSURE.md",
)

FORBIDDEN_CLAIMS = ("PROFITABLE", "CERTIFIED_ALPHA", "PRODUCTION_READY", "EDGE_CONFIRMED", "PROFITABILITY_VERIFIED")
VERDICTS = {"CANDIDATE_REJECTED", "PENDING_SEALED_OOS"}


def load(name: str) -> dict:
    return json.loads((D2 / name).read_text(encoding="utf-8"))


def affirmative_claims(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    hits = []
    for token in FORBIDDEN_CLAIMS:
        if re.search(r'["\']' + re.escape(token) + r'["\']\s*:\s*true', text, re.I):
            hits.append(f"{path.name}:{token} (json assertion)")
        if re.search(re.escape(token) + r"\s+is\s+(true|confirmed)", text, re.I):
            hits.append(f"{path.name}:{token} (prose assertion)")
    return hits


def test_all_deliverables_present_and_parse() -> None:
    for name in DELIVERABLES:
        path = D2 / name
        assert path.exists(), f"missing deliverable {name}"
        if name.endswith(".json"):
            assert json.loads(path.read_text(encoding="utf-8"))


def test_frozen_specs_untouched_by_phase_b() -> None:
    manifest = json.loads((DATA / "PREREGISTRATION_MANIFEST.json").read_text(encoding="utf-8"))
    for hid, row in manifest["spec_hashes"].items():
        if row["status"] != "SPEC_FROZEN":
            continue
        digest = hashlib.sha256((ROOT / row["spec_file"]).read_bytes()).hexdigest()
        assert digest == row["spec_file_sha256"], f"{hid} spec changed after the freeze"


def test_historical_phase_a_artifacts_are_not_rewritten() -> None:
    # the Phase A NOT_RUN contracts and the historical activation gate must survive Phase B
    economic = json.loads((DATA / "ECONOMIC_RESULTS.json").read_text(encoding="utf-8"))
    assert economic["status"] == "NOT_RUN"
    audit = json.loads((DATA / "DATA_EXPOSURE_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["activation_gate"]["next_campaign"] == "NOT_AUTHORIZED"
    assert audit["activation_gate"]["authorized"] is False


def test_authorization_record_matches_the_adr() -> None:
    auth = load("CAMPAIGN_AUTHORIZATION.json")
    assert auth["next_campaign"] == "AUTHORIZED"
    assert auth["authorization_scope"] == "OFFLINE_DEV_VAL_ONLY"
    assert auth["historical_artifacts_rewritten"] is False
    assert auth["charter_control_check"]["additional_unsatisfied_authorization_for_authorized_scope"] == "NONE"
    excluded = auth["explicitly_excluded"]
    assert excluded["live_trading"] == "DISABLED"
    assert excluded["trades_authorized"] == 0
    assert excluded["parameter_searches"] == 0
    assert "CLOSED" in excluded["sealed_forward_oos"]


def test_results_keep_the_sealed_window_closed_and_emit_no_pass() -> None:
    results = load("ECONOMIC_RESULTS.json")
    scope = results["result_scope"]
    assert scope["sealed_oos_opened"] is False
    assert scope["no_pass_possible_now"] is True
    assert scope["profitability_verified"] is False
    assert results["checks_failed"] == 0
    for hid in ("H-049-001", "H-049-002"):
        assert results[hid]["verdict"] in VERDICTS
        if results[hid]["verdict"] == "CANDIDATE_REJECTED":
            assert results[hid]["failed_criteria"], f"{hid} rejected without a failed criterion"


def test_cost_model_is_the_frozen_one() -> None:
    results = load("ECONOMIC_RESULTS.json")
    cost = results["cost_model"]
    assert cost["scenario"] == "BINANCE_SPOT_STANDARD_TAKER"
    assert abs(cost["round_trip_bps_200_usdt"] - 23.353553391) < 1e-6
    assert abs(cost["stress_1_5x_bps"] - 35.030330086) < 1e-6


def test_partitions_and_pit_are_enforced() -> None:
    results = load("ECONOMIC_RESULTS.json")
    assert results["grid"] == {"first": "2018-12-30", "last": "2026-10-04", "instants": 406}
    for hid in ("H-049-001", "H-049-002"):
        assert results["pit_audit"][hid]["violations"] == 0
        assert results["pit_audit"][hid]["max_value_date"] < "2026-10-11"
        m = results[hid]["per_asset"]["BTCUSDT"]
        assert m["development"]["round_trips"] > 0 and m["validation"]["round_trips"] > 0
        for part in ("development", "validation"):
            assert m[part]["lcb_95_net_expectancy_bps"] is not None
            assert m[part]["bootstrap_p_le_zero"] is not None
            assert len(m[part]["lcb_block_sensitivity_bps"]) == 3


def test_counts_match_the_rfc049b_publication() -> None:
    feas = json.loads((DATA / "admission" / "OOS_SAMPLE_FEASIBILITY.json").read_text(encoding="utf-8"))
    results = load("ECONOMIC_RESULTS.json")
    for hid in ("H-049-001", "H-049-002"):
        assert results[hid]["per_asset"]["BTCUSDT"]["all_exposed"]["round_trips"] == feas[hid]["round_trips"]["all_exposed"]


def test_eligibility_keeps_the_floor_and_flags_the_sealed_risk() -> None:
    elig = load("DISCOVERY2_STATISTICAL_ELIGIBILITY.json")
    assert elig["thresholds_changed"] is False
    assert "20 round trips or 24 months" in elig["statistical_criterion_unchanged"]
    for hid in ("H-049-001", "H-049-002"):
        stat = elig[hid]["statistical_sufficiency"]
        assert stat["sealed_window_risk"] == "INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION"
        assert stat["expected_round_trips_in_24_month_sealed_window"] < 20
        assert elig[hid]["technical_validity"]["contract_status"] == "valid"


def test_ablation_adopts_nothing_and_touches_no_frozen_hypothesis() -> None:
    ablation = load("FILTER_ABLATION.json")
    assert ablation["adoption"]["status"] == "NOT_ADOPTED"
    assert ablation["hypothesis_record"]["status"] == "DIAGNOSTIC_NOT_ADMITTED"
    assert ablation["scope"]["h_049_001_modified"] is False
    assert ablation["scope"]["h_049_002_modified"] is False
    assert ablation["checks_failed"] == 0
    assert set(ablation["arms"]) == {"base", "base+stablecoin", "base+macro", "base+both"}


def test_active_audit_reports_zero_operations_and_no_label() -> None:
    audit = load("ACTIVE_STRATEGY_STATUS.json")
    assert audit["ledger"]["total"] == 24
    assert audit["ledger"]["admitted_for_paper"] == 0
    funnel = audit["funnel"]["current"]
    assert funnel["proposals"] == 0 and funnel["authorized"] == 0 and funnel["executed"] == 0
    assert audit["objective_3_ops_per_day"]["assessment"] == "NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE"
    assert audit["low_frequency_line"]["label_found_in_repository"] is False
    assert audit["checks_failed"] == 0


def test_verification_passed_with_controls_and_no_false_success() -> None:
    verdict = load("INDEPENDENT_VERIFICATION.json")
    assert verdict["status"] == "PASS"
    assert verdict["checks_failed"] == 0
    assert verdict["builder_imported"] is False
    assert verdict["shared_code_with_builder"] is False
    assert verdict["negative_controls_missed"] == []
    assert verdict["FALSE_SUCCESS"] == 0
    assert len(verdict["negative_controls"]) >= 8
    assert all(row["result"] == "DETECTED" for row in verdict["negative_controls"])


def test_verifier_never_imports_the_builder() -> None:
    source = (ROOT / "scripts" / "rfc049c_verify.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+rfc049c_engine", source, re.M)
    assert not re.search(r"^\s*(from|import)\s+rfc049c_ablation", source, re.M)


def test_no_forbidden_claim_is_asserted() -> None:
    for name in DELIVERABLES:
        assert not affirmative_claims(D2 / name), f"{name} asserts a forbidden claim"


def test_closure_is_terminal_and_registered_as_an_adr() -> None:
    closure = load("CAMPAIGN_CLOSURE.json")
    assert closure["campaign"]["terminal_state"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert closure["campaign"]["stop_rule_fired"].startswith("ST-2")
    assert closure["checks_failed"] == 0
    assert closure["decided_by"].startswith("operator")
    assert closure["prohibitions_honoured"]["historical_artifacts_rewritten"] is False
    adr = (ROOT / "tasks" / "decisions.md").read_text(encoding="utf-8")
    assert "## ADR-0026" in adr
    assert "ADR-0026" in closure["adr"]


def test_closure_criteria_match_the_economic_results() -> None:
    closure = load("CAMPAIGN_CLOSURE.json")
    results = load("ECONOMIC_RESULTS.json")
    recorded = closure["mandatory_stop_artifacts"]["rejection_reason_per_candidate_with_gate_id"]
    for hid in ("H-049-001", "H-049-002"):
        assert recorded[hid]["verdict"] == "CANDIDATE_REJECTED"
        from_closure = {
            f"{row['criterion']}:{row['partition']}" for row in recorded[hid]["failed_criteria"]
        }
        assert from_closure == set(results[hid]["failed_criteria"]), hid
    assert closure["mandatory_stop_artifacts"]["trials_counted"]["attempts_discarded"] == 0
    assert closure["mandatory_stop_artifacts"]["trials_counted"]["reconstructable"] is True


def test_sealed_oos_is_retired_unused_and_not_opened() -> None:
    closure = load("CAMPAIGN_CLOSURE.json")
    resolution = closure["sealed_oos_resolution"]
    assert resolution["decision"] == "CANCELLED_NOT_OPENED"
    accounting = resolution["inspection_accounting"]
    assert accounting["sealed_window_read"] is False
    assert accounting["sealed_window_deleted"] is False
    assert accounting["inspections_used"] == 0
    assert accounting["inspections_retired_unused"] == 1
    assert accounting["inspections_transferred"] == 0
    assert closure["governance_flags_after_closure"]["SEALED_OOS"] == "CANCELLED_NOT_OPENED"
    assert closure["governance_flags_after_closure"]["OOS_OPENED"] is False
    # the frozen Phase A declaration survives untouched: it is superseded, not rewritten
    manifest = json.loads((DATA / "PREREGISTRATION_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["partition_policy"]["sealed_oos"].startswith("forward observations strictly after")
    assert manifest["freeze_timestamp_utc"] == "2026-10-10T11:26:20Z"
    assert load("ECONOMIC_RESULTS.json")["result_scope"]["sealed_oos_opened"] is False


def test_closure_creates_no_authorization_or_promotion() -> None:
    flags = load("CAMPAIGN_CLOSURE.json")["governance_flags_after_closure"]
    assert flags["NEXT_CAMPAIGN"] == "NOT_AUTHORIZED"
    assert flags["PAPER_PROMOTION"] == "NOT_AUTHORIZED"
    assert flags["LIVE_TRADING"] == "DISABLED"
    assert flags["TRADES_AUTHORIZED"] == 0
    assert flags["PROFITABILITY_VERIFIED"] is False
    assert flags["HYPOTHESIS_001"] == flags["HYPOTHESIS_002"] == "CLOSED_REJECTED_DEV_VAL"
    assert flags["HYPOTHESIS_BUDGET"] == "EXHAUSTED_NO_REFILL"
    text = (D2 / "CAMPAIGN_CLOSURE.md").read_text(encoding="utf-8")
    assert "DISCOVERY_CAMPAIGN_FAILED" in text and "CANCELLED_NOT_OPENED" in text


def test_execution_plan_was_written_before_the_run() -> None:
    text = (D2 / "DISCOVERY2_EXECUTION_PLAN.md").read_text(encoding="utf-8")
    assert "written_before_economic_run | **true**" in text
    assert "490049" in text  # the frozen bootstrap seed
    assert "OFFLINE_DEV_VAL_ONLY" in text
