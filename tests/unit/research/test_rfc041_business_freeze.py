"""RFC-041 tests — business research freeze & re-entry governance (§72).

Pure and deterministic: they pin the canonical KPI model, the candidate
disposition registry, the freeze enforcement, the re-entry gate logic, the
paper/live admission rules and the JSON/MD consistency of the tracked state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import business_freeze as BF  # noqa: E402

# --------------------------------------------------------------------------- #
# §23/§58-§60 — capital, decision identity and schema
# --------------------------------------------------------------------------- #


def test_reference_capital_and_authorization() -> None:
    assert BF.REFERENCE_INITIAL_CAPITAL_USDT == 200.0
    assert BF.LIVE_CAPITAL_AUTHORIZED == 0
    assert BF.DECISION_ID == "BUSINESS-FREEZE-2026-001"
    assert BF.SCHEMA_VERSION == 1


def test_capital_principle() -> None:
    assert BF.CAPITAL_PRINCIPLE == "STRATEGY MUST FIT CAPITAL"
    assert "MUST NOT BE FORCED" in BF.ANTI_PRINCIPLE


# --------------------------------------------------------------------------- #
# §5 — canonical KPI model
# --------------------------------------------------------------------------- #


def test_kpi_names_complete_and_primary() -> None:
    assert set(BF.KPI_NAMES) == {
        "HISTORICAL_NET_EDGE_COUNT",
        "EXECUTABLE_VALIDATED_EDGE_COUNT",
        "BUSINESS_VALIDATED_EDGE_COUNT",
        "ROBUST_BUSINESS_EDGE_COUNT",
        "PAPER_CANDIDATE_COUNT",
        "FORWARD_PROFITABLE_COUNT",
        "LIVE_PROFITABLE_COUNT",
    }
    assert BF.KPI_PRIMARY == "BUSINESS_VALIDATED_EDGE_COUNT"


def test_kpi_counts_are_derived_and_business_is_zero() -> None:
    counts = BF.kpi_counts()
    assert counts["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
    assert counts["ROBUST_BUSINESS_EDGE_COUNT"] == 0
    assert counts["PAPER_CANDIDATE_COUNT"] == 0
    assert counts["FORWARD_PROFITABLE_COUNT"] == 0
    assert counts["LIVE_PROFITABLE_COUNT"] == 0
    # honest separation: historical / executable edges exist but are not business edges
    assert counts["HISTORICAL_NET_EDGE_COUNT"] >= counts["EXECUTABLE_VALIDATED_EDGE_COUNT"] >= 0
    assert counts["EXECUTABLE_VALIDATED_EDGE_COUNT"] >= 1


def test_business_kpi_names_are_zero_tolerance() -> None:
    counts = BF.kpi_counts()
    for name in BF.BUSINESS_KPI_NAMES:
        assert counts[name] == 0


# --------------------------------------------------------------------------- #
# §6/§7 — business edge definition and benchmark pre-declaration
# --------------------------------------------------------------------------- #


def test_business_edge_needs_all_seven_conditions() -> None:
    assert len(BF.BUSINESS_EDGE_CONDITIONS) == 7
    all_true = dict.fromkeys(BF.BUSINESS_EDGE_CONDITIONS, True)
    assert BF.business_edge_status(all_true) == "PASS"
    for name in BF.BUSINESS_EDGE_CONDITIONS:
        partial = dict(all_true)
        partial[name] = False
        assert BF.business_edge_status(partial) == "FAIL"
    assert BF.business_edge_status({}) == "FAIL"


def test_benchmark_declaration_rules() -> None:
    assert BF.REQUIRED_BENCHMARKS == ("PRIMARY_PASSIVE_BENCHMARK", "RISK_MATCHED_BENCHMARK")
    assert BF.benchmark_declaration_ok("SPY", "risk_matched", chosen_after_results=False)
    assert not BF.benchmark_declaration_ok("SPY", None, chosen_after_results=False)
    assert not BF.benchmark_declaration_ok("SPY", "risk_matched", chosen_after_results=True)


# --------------------------------------------------------------------------- #
# §9-§20 — candidate disposition registry
# --------------------------------------------------------------------------- #


def test_canonical_candidate_statuses() -> None:
    assert BF.canonical_candidate_statuses() == {
        "EXT-TSMOM-001": "INVALIDATED_TRADABILITY",
        "EXT-TSMOM-002": "REJECTED_HISTORICAL_PLAUSIBILITY",
        "EXT-TSMOM-003": "REJECTED_VALIDATION",
        "EXT-XMOM-001": "REJECTED_ROBUSTNESS",
        "MF-TREND-001": "RESEARCH_ASSET",
        "SC-TREND-001": "VALIDATED_DEFENSIVE",
        "SC-DUALMOM-002": "REJECTED_BUSINESS_EDGE",
        "SC-CANDIDATE-003": "NOT_AUTHORIZED",
    }


def test_registry_ids_unique_and_evidence_levels_valid() -> None:
    ids = [c.candidate_id for c in BF.CANDIDATE_DISPOSITIONS]
    assert len(ids) == len(set(ids)) == 8
    for c in BF.CANDIDATE_DISPOSITIONS:
        assert c.evidence_level in BF.EVIDENCE_LADDER
        assert c.reentry_condition


def test_no_active_candidate_remains() -> None:
    assert BF.active_candidate_count() == 0


def test_sc_trend_is_defensive_not_profit_engine() -> None:
    c = BF.disposition_by_id()["SC-TREND-001"]
    assert c.final_status == "VALIDATED_DEFENSIVE"
    assert c.disposition_class == "FUTURE_DEFENSIVE_OVERLAY_CANDIDATE"
    assert c.product_fit_200 == "PASS"
    assert c.business_edge is False


def test_mf_trend_is_research_asset_not_product() -> None:
    c = BF.disposition_by_id()["MF-TREND-001"]
    assert c.final_status == "RESEARCH_ASSET"
    assert c.product_fit_200 == "FAIL"
    assert c.executable_validated_edge is True
    assert c.business_edge is False


def test_sc_dual_mom_rejected_business_edge() -> None:
    c = BF.disposition_by_id()["SC-DUALMOM-002"]
    assert c.final_status == "REJECTED_BUSINESS_EDGE"
    assert c.business_edge is False
    assert c.evidence_retained is True


def test_no_p3() -> None:
    c = BF.disposition_by_id()["SC-CANDIDATE-003"]
    assert c.final_status == "NOT_AUTHORIZED"
    assert c.evidence_level == "NO_EDGE"


# --------------------------------------------------------------------------- #
# §25 — freeze enforcement
# --------------------------------------------------------------------------- #


def test_freeze_is_active_and_prohibits_new_work() -> None:
    assert BF.ALPHA_RESEARCH_FREEZE == "ACTIVE"
    assert "NEW ALPHA RFC" in BF.FREEZE_PROHIBITIONS
    assert "PAPER RUN" in BF.FREEZE_PROHIBITIONS
    assert "LIVE RUN" in BF.FREEZE_PROHIBITIONS


def test_no_alpha_rfc_while_frozen() -> None:
    assert BF.alpha_rfc_allowed(True, True) is False
    assert BF.alpha_rfc_allowed(True, False) is False
    assert BF.alpha_rfc_allowed(False, False) is False
    assert BF.alpha_rfc_allowed(False, True) is True


# --------------------------------------------------------------------------- #
# §27-§39 — reentry gate, scorecard and budget
# --------------------------------------------------------------------------- #


def _good_scores() -> dict[str, int]:
    return {d: 4 for d in BF.REENTRY_SCORECARD_DIMENSIONS}


def test_reentry_rejects_reject_only_proposal() -> None:
    decision = BF.reentry_gate(
        {
            "triggers": {"A": True},
            "reject_conditions": ["new RSI variation"],
            "evidence_strong_enough": True,
            "product_fit": "PASS",
            "expected_beats_benchmark": True,
            "scores": _good_scores(),
        }
    )
    assert decision.passed is False
    assert "reject_condition_present" in decision.failing


def test_reentry_rejects_without_trigger_and_weak_product() -> None:
    no_trigger = BF.reentry_gate(
        {
            "triggers": {},
            "reject_conditions": [],
            "evidence_strong_enough": True,
            "product_fit": "PASS",
            "expected_beats_benchmark": True,
            "scores": _good_scores(),
        }
    )
    assert no_trigger.passed is False
    assert "no_valid_trigger" in no_trigger.failing

    weak = BF.reentry_gate(
        {
            "triggers": {"B": True},
            "reject_conditions": [],
            "evidence_strong_enough": True,
            "product_fit": "FAIL",
            "expected_beats_benchmark": False,
            "scores": _good_scores(),
        }
    )
    assert weak.passed is False
    assert "product_fit_fail" in weak.failing
    assert "no_defensible_benchmark_case" in weak.failing


def test_reentry_passes_only_when_everything_holds() -> None:
    decision = BF.reentry_gate(
        {
            "triggers": {"B": True},
            "reject_conditions": [],
            "evidence_strong_enough": True,
            "product_fit": "PASS",
            "expected_beats_benchmark": True,
            "scores": _good_scores(),
        }
    )
    assert decision.passed is True
    assert decision.scorecard == "PROCEED"


def test_reject_condition_detection() -> None:
    assert BF.is_reject_condition("new RSI variation")
    assert BF.is_reject_condition("different moving average")
    assert BF.is_reject_condition("parameter optimization")
    assert BF.is_reject_condition("same strategy with renamed rules")
    assert BF.is_reject_condition("another crypto pair")
    assert not BF.is_reject_condition("new structural carry mechanism")


def test_reentry_has_five_triggers_and_reject_conditions() -> None:
    assert set(BF.REENTRY_TRIGGERS) == {"A", "B", "C", "D", "E"}
    assert len(BF.REENTRY_REJECT_CONDITIONS) >= 9


def test_scorecard_rules() -> None:
    assert BF.scorecard_decision({}) == "REJECT_MISSING_DIMENSION"
    weak = _good_scores()
    weak["external_evidence"] = 1
    assert BF.scorecard_decision(weak) == "REJECT"
    review = _good_scores()
    review["capital_fit"] = 2  # a critical dimension at 2 -> review, not proceed
    assert BF.scorecard_decision(review) == "ADMISSION_REVIEW"


def test_budget_and_failure_rule() -> None:
    assert BF.REENTRY_BUDGET == {"MAX_FAMILIES": 3, "MAX_FINALISTS": 2, "MAX_IMPLEMENTED": 1}
    assert BF.budget_ok(3, 2, 1)
    assert not BF.budget_ok(4, 2, 1)
    assert not BF.budget_ok(3, 3, 1)
    assert not BF.budget_ok(3, 2, 2)
    # §38 — a failed single implementation pauses again; no automatic second run
    assert BF.second_implementation_allowed(True) is False
    assert BF.second_implementation_allowed(False) is True


# --------------------------------------------------------------------------- #
# §48-§50 — paper / live admission and the 200-USDT role
# --------------------------------------------------------------------------- #


def test_no_paper_without_business_edge() -> None:
    assert BF.paper_admission_allowed(False) is False
    assert BF.paper_admission_allowed(True) is True


def test_no_live_without_full_admission() -> None:
    ok = {
        "paper_execution_pass": True,
        "forward_evidence": True,
        "risk_approval": True,
        "human_capital_approval": True,
    }
    assert BF.live_admission_allowed(**ok) is True
    for key in ok:
        missing = dict(ok)
        missing[key] = False
        assert BF.live_admission_allowed(**missing) is False


def test_canary_capital_is_future_only() -> None:
    role = BF.canary_capital_role()
    assert role["role"] == "FUTURE_LIVE_CANARY_CAPITAL"
    assert role["usable_now"] is False
    assert role["reference_initial_capital_usdt"] == 200.0


# --------------------------------------------------------------------------- #
# §44-§47 — proven / not proven / lessons / value chain
# --------------------------------------------------------------------------- #


def test_not_proven_contains_the_hard_things() -> None:
    assert "business edge" in BF.NOT_PROVEN
    assert "forward profitability" in BF.NOT_PROVEN
    assert "live profitability" in BF.NOT_PROVEN


def test_lessons_separation() -> None:
    assert BF.LESSONS == (
        "POSITIVE BACKTEST != BUSINESS EDGE",
        "BUSINESS EDGE != LIVE PROFIT",
    )


def test_value_chain_order() -> None:
    assert BF.VALUE_CHAIN[0] == "EXTERNAL EVIDENCE"
    assert BF.VALUE_CHAIN[-1] == "LIVE"
    assert BF.VALUE_CHAIN.index("PAPER CERTIFICATION") < BF.VALUE_CHAIN.index("LIVE")


# --------------------------------------------------------------------------- #
# §71 — false success
# --------------------------------------------------------------------------- #


def test_false_success_counts_only_real_bypasses() -> None:
    assert BF.false_success_count({}) == 0
    assert BF.false_success_count(dict.fromkeys(BF.FALSE_SUCCESS_TRIGGERS, False)) == 0
    assert BF.false_success_count({"new_p3_created": True}) == 1
    assert BF.false_success_count({"historical_positive_called_business_edge": True}) == 1


# --------------------------------------------------------------------------- #
# §58-§60 — canonical machine-readable state
# --------------------------------------------------------------------------- #


def test_economic_state_shape_and_invariants() -> None:
    state = BF.economic_state(source_commit="deadbeef", updated_at="2026-10-06T00:00:00Z")
    assert state["schema_version"] == BF.SCHEMA_VERSION
    assert state["source_commit"] == "deadbeef"
    assert state["decision_id"] == BF.DECISION_ID
    assert state["alpha_research_freeze"] == "ACTIVE"
    assert state["next_alpha_rfc_allowed"] is False
    assert state["active_candidates"] == 0
    assert state["live_capital_authorized"] == 0
    assert state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
    assert state["current_decision"] == "WAIT_FOR_REENTRY_QUALIFIED_BUSINESS_OPPORTUNITY"


def test_stale_status_audit_has_entries() -> None:
    audit = BF.stale_status_audit()
    assert audit["entry_count"] >= 5
    assert all("superseded_by" in e for e in audit["entries"])


# --------------------------------------------------------------------------- #
# §72 — JSON/MD consistency of the tracked canonical state
# --------------------------------------------------------------------------- #


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_tracked_state_json_md_consistency() -> None:
    docs = REPO / "docs" / "research"
    state_path = docs / "ECONOMIC_STATE.json"
    scoreboard_path = docs / "ECONOMIC_SCOREBOARD.json"
    if not state_path.exists() or not scoreboard_path.exists():
        pytest.skip("RFC-041 tracked state not present")
    state = _load(state_path)
    scoreboard = _load(scoreboard_path)
    assert state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == scoreboard["business_edge_count"] == 0
    assert state["current_decision"] == scoreboard["current_decision"]
    assert state["alpha_research_freeze"] == scoreboard["research_freeze"] == "ACTIVE"
    # the MD projection of each JSON artifact must exist and mention the decision
    for stem in (
        "CANDIDATE_ARCHIVE",
        "FINAL_BUSINESS_DECISION",
        "BUSINESS_REENTRY_POLICY",
        "ECONOMIC_SCOREBOARD",
    ):
        md = docs / f"{stem}.md"
        assert md.exists(), stem
    md_text = (docs / "FINAL_BUSINESS_DECISION.md").read_text(encoding="utf-8")
    assert "BUSINESS-FREEZE-2026-001" in md_text
