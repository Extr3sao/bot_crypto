"""RFC-049B — contract tests for the Discovery 2 admission artifacts.

These tests are offline: they validate the delivered evidence contracts, the
frozen-baseline attestation and the verifier's independence, without any network
access and without recomputing economics (there is none to recompute).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "rfc049"
ADM = DATA / "admission"

DELIVERABLES = (
    "ADMISSION_AUDIT.md",
    "ADMISSION_AUDIT.json",
    "PIT_SOURCE_VERIFICATION.json",
    "HYPOTHESIS_INDEPENDENCE.md",
    "OOS_SAMPLE_FEASIBILITY.json",
    "INDEPENDENT_VERIFICATION.json",
    "FINAL_ADMISSION_REPORT.md",
    "FINAL_ADMISSION_REPORT.json",
)

FORBIDDEN_CLAIMS = (
    "PROFITABLE",
    "CERTIFIED_ALPHA",
    "PRODUCTION_READY",
    "EDGE_CONFIRMED",
    "PROFITABILITY_VERIFIED",
)
PIT_CLASSES = {"PIT_VERIFIED", "PIT_CONSERVATIVE_PROXY", "PIT_UNKNOWN", "PIT_FAILED"}


def load(name: str) -> dict:
    return json.loads((ADM / name).read_text(encoding="utf-8"))


def affirmative_claims(path: Path) -> list[str]:
    """Only assertions count.

    The governance flags must appear in these artifacts by name with the value
    false, and the negative-control log quotes an injected claim as text; both are
    disclosures, so the checker looks for assertion shapes only.
    """
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
        path = ADM / name
        assert path.exists(), f"missing deliverable {name}"
        if name.endswith(".json"):
            assert json.loads(path.read_text(encoding="utf-8"))


def test_frozen_specs_and_datasets_untouched() -> None:
    manifest = json.loads((DATA / "PREREGISTRATION_MANIFEST.json").read_text(encoding="utf-8"))
    for hid, row in manifest["spec_hashes"].items():
        if row["status"] != "SPEC_FROZEN":
            continue
        digest = hashlib.sha256((ROOT / row["spec_file"]).read_bytes()).hexdigest()
        assert digest == row["spec_file_sha256"], f"{hid} spec changed after the freeze"


def test_audit_reports_no_economic_quantity() -> None:
    audit = load("ADMISSION_AUDIT.json")
    assert audit["returns_computed"] is False
    assert audit["pnl_computed"] is False
    assert audit["oos_opened"] is False
    assert audit["experiments_executed"] == 0
    assert audit["checks_failed"] == 0
    assert audit["checks_blocked"] >= 0


def test_governance_gate_intact() -> None:
    status = load("FINAL_ADMISSION_REPORT.json")["CAMPAIGN_AUTHORIZATION_STATUS"]
    assert status["next_campaign"] == "NOT_AUTHORIZED"
    assert status["campaign_authorized"] is False
    assert status["experiments_executed"] == 0
    assert status["oos_opened"] is False
    assert status["trades_authorized"] == 0
    assert status["live_trading"] == "DISABLED"
    assert status["profitability_verified"] is False


def test_no_forbidden_claim_is_asserted() -> None:
    for name in DELIVERABLES:
        assert not affirmative_claims(ADM / name), f"{name} asserts a forbidden claim"


def test_pit_classes_use_the_declared_vocabulary() -> None:
    pit = load("PIT_SOURCE_VERIFICATION.json")
    for row in pit["inputs"].values():
        assert row["classification"] in PIT_CLASSES
    composite = pit["composite_classification"]
    assert composite["H-049-001"] in PIT_CLASSES and composite["H-049-002"] in PIT_CLASSES
    assert not pit["data_time_le_decision_time_violations"]["H-049-001"]
    assert not pit["data_time_le_decision_time_violations"]["H-049-002"]


def test_macro_inputs_are_verified_at_primary_source() -> None:
    cross = load("ADMISSION_AUDIT.json")["macro_inputs"]["primary_source_crosschecks"]
    assert cross["h41_total_assets_matches_fred"] is True
    assert cross["h41_tga_week_average_matches_fred"] is True
    assert all(row["matches"] for row in cross["nyfed_rrp_matches_fred"])


def test_stablecoin_variable_semantics_are_explicit() -> None:
    stable = load("ADMISSION_AUDIT.json")["stablecoin_variable"]
    assert stable["frozen_field"] == "totalCirculatingUSD.peggedUSD"
    assert "valuation" in stable["field_meaning_verified"]
    assert stable["missing_days"] == 0
    assert stable["revision_exposure"]["settled_days_revised"] == 0


def test_feasibility_counts_are_internally_consistent() -> None:
    feas = load("OOS_SAMPLE_FEASIBILITY.json")
    for hid in ("H-049-001", "H-049-002"):
        row = feas[hid]
        years = row["exposed_years_measured"]
        if years:
            expected = row["round_trips"]["all_exposed"] / years
            assert abs(expected - row["round_trips_per_year_all_exposed"]) < 0.05
        assert row["sealed_window_risk"] in (
            "INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION",
            "floor reachable within 24 months at the measured rate",
        )
    assert feas["thresholds_changed"] is False


def test_independence_is_measured_not_asserted() -> None:
    overlap = load("FINAL_ADMISSION_REPORT.json")["INDEPENDENCE"]
    total = (
        overlap["weeks_both_long"]
        + overlap["weeks_a_long_only"]
        + overlap["weeks_b_long_only"]
        + overlap["weeks_both_flat"]
    )
    assert total > 100
    assert 0.0 <= overlap["state_agreement_rate"] <= 1.0
    assert 0.0 <= overlap["jaccard_on_long_weeks"] <= 1.0


def test_verifier_is_independent_of_the_builder() -> None:
    source = (ROOT / "scripts" / "rfc049b_verify.py").read_text(encoding="utf-8")
    # the property is that it never imports the builder, not that it never names it
    assert not re.search(r"^\s*(from|import)\s+rfc049b_admission", source, re.M)
    assert not re.search(r"^\s*(from|import)\s+rfc049b_verify\b", source, re.M)


def test_negative_controls_all_fired() -> None:
    verdict = load("INDEPENDENT_VERIFICATION.json")
    assert verdict["builder_imported"] is False
    assert verdict["shared_code_with_builder"] is False
    assert verdict["checks_failed"] == 0
    assert verdict["status"] == "PASS"
    assert verdict["negative_controls_missed"] == []
    assert verdict["FALSE_SUCCESS"] == 0
    assert len(verdict["negative_controls"]) >= 10
    assert all(row["result"] == "DETECTED" for row in verdict["negative_controls"])
