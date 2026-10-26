"""RFC-044 tests — profitability reentry watch (§58).

Deterministic only: reentry gate, duplicate detection, one-candidate lease,
freeze behaviour, event validity, capital constraint, registry/ledger
consistency and the no-strategy rule.  No strategy, no backtest, no market data.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import reentry_watch as RW  # noqa: E402

DOCS = REPO / "docs" / "research"
OUT = REPO / "reports" / "reentry-watch"
REPORTS = REPO / "reports"

HAS_ARTIFACTS = (OUT / "REENTRY_GATE_AUDIT.json").exists() and (
    DOCS / "REENTRY_DECISION_LEDGER.json"
).exists()

# --------------------------------------------------------------------------- #
# §5-§6 — event validity
# --------------------------------------------------------------------------- #


def test_valid_trigger_types_are_the_five_declared_classes() -> None:
    assert RW.VALID_TRIGGER_TYPES == (
        "A_NEW_EXTERNAL_EVIDENCE",
        "B_NEW_STRUCTURAL_MECHANISM",
        "C_MATERIAL_CAPITAL_CHANGE",
        "D_MATERIAL_INSTRUMENT_OR_BROKER_CHANGE",
        "E_NEW_DATA_UNLOCKING_EXISTING_SUPPORTED_HYPOTHESIS",
    )


def test_only_declared_triggers_are_valid() -> None:
    for trigger in RW.VALID_TRIGGER_TYPES:
        assert RW.is_valid_trigger(trigger)
    assert not RW.is_valid_trigger("NEW_INDICATOR")
    assert not RW.is_valid_trigger("")
    assert not RW.is_valid_trigger("F_RANDOM_IDEA")


def test_invalid_events_are_rejected() -> None:
    for kind in RW.INVALID_EVENT_KINDS:
        assert RW.is_invalid_event(kind)
    assert RW.is_invalid_event("parameter_tuning")
    assert RW.is_invalid_event("same_family_with_new_name")
    assert not RW.is_invalid_event("A_NEW_EXTERNAL_EVIDENCE")


def test_idle_time_is_not_an_event() -> None:
    # §44/§47: idling is never a reentry event, so no qualified event exists.
    decision = RW.reentry_decision(qualified_events=[])
    assert decision["decision"] == "NO_ACTION"
    assert decision["company_state_unchanged"] is True


# --------------------------------------------------------------------------- #
# §10 — opportunity validation
# --------------------------------------------------------------------------- #


def _opportunity(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {field: "X" for field in RW.OPPORTUNITY_FIELDS}
    base["TRIGGER_TYPE"] = "A_NEW_EXTERNAL_EVIDENCE"
    base["SOURCE_QUALITY"] = "A"
    base.update(overrides)
    return base


def test_complete_opportunity_with_valid_trigger_is_valid() -> None:
    result = RW.validate_opportunity(_opportunity())
    assert result["is_valid"] is True
    assert result["missing_fields"] == []
    assert result["valid_trigger"] is True


def test_opportunity_missing_fields_is_invalid() -> None:
    incomplete = _opportunity()
    del incomplete["PRIMARY_BENCHMARK"]
    del incomplete["COUNTER_EVIDENCE"]
    result = RW.validate_opportunity(incomplete)
    assert result["is_valid"] is False
    assert "PRIMARY_BENCHMARK" in result["missing_fields"]
    assert "COUNTER_EVIDENCE" in result["missing_fields"]


def test_opportunity_with_invalid_trigger_is_invalid() -> None:
    result = RW.validate_opportunity(_opportunity(TRIGGER_TYPE="F_RANDOM_IDEA"))
    assert result["is_valid"] is False
    assert result["valid_trigger"] is False


# --------------------------------------------------------------------------- #
# §11-§13 — source quality and minimum evidence
# --------------------------------------------------------------------------- #


def test_c_or_d_alone_cannot_reopen_research() -> None:
    assert RW.source_quality_sufficient(["C"]) is False
    assert RW.source_quality_sufficient(["D"]) is False
    assert RW.source_quality_sufficient(["C", "D"]) is False
    assert RW.source_quality_sufficient(["A"]) is True
    assert RW.source_quality_sufficient(["B"]) is True


def test_c_only_opportunity_is_invalid() -> None:
    result = RW.validate_opportunity(_opportunity(SOURCE_QUALITY="C"))
    assert result["is_valid"] is False
    assert result["source_quality_can_reopen"] is False


def test_minimum_evidence_requires_two_independent_high_quality_or_survives() -> None:
    two_independent = [
        {"quality": "A", "independent": True},
        {"quality": "B", "independent": True},
    ]
    assert RW.minimum_evidence_met(two_independent) is True
    same_project = [
        {"quality": "A", "independent": False},
        {"quality": "B", "independent": False},
    ]
    assert RW.minimum_evidence_met(same_project) is False
    survives = [{"quality": "A", "independent": True, "post_publication": "SURVIVES"}]
    assert RW.minimum_evidence_met(survives) is True
    decayed = [{"quality": "A", "independent": True, "post_publication": "DECAYED"}]
    assert RW.minimum_evidence_met(decayed) is False
    assert RW.minimum_evidence_met([{"quality": "D", "independent": True}]) is False


# --------------------------------------------------------------------------- #
# §14 — duplicate family detection
# --------------------------------------------------------------------------- #


def _archive() -> list[dict[str, Any]]:
    return json.loads((DOCS / "CANDIDATE_ARCHIVE.json").read_text(encoding="utf-8"))["candidates"]


def test_rehash_of_archived_family_is_detected() -> None:
    archive = _archive()
    rehash = {"MECHANISM": "time-series momentum / trend"}
    result = RW.detect_same_family_rehash(rehash, archive)
    assert result["SAME_FAMILY_REHASH"] is True
    assert result["matched_candidate"] == "EXT-TSMOM-001"


def test_renamed_dual_momentum_is_detected() -> None:
    archive = _archive()
    rehash = {"FAMILY": "dual momentum / GEM (ETF)"}
    assert RW.detect_same_family_rehash(rehash, archive)["SAME_FAMILY_REHASH"] is True


def test_genuinely_new_family_is_not_a_rehash() -> None:
    archive = _archive()
    novel = {"MECHANISM": "commodity calendar-spread roll yield"}
    result = RW.detect_same_family_rehash(novel, archive)
    assert result["SAME_FAMILY_REHASH"] is False
    assert result["matched_candidate"] is None


# --------------------------------------------------------------------------- #
# §17-§18 — research value and critical gates
# --------------------------------------------------------------------------- #


def test_research_value_is_a_product_over_cost() -> None:
    scores = {
        "evidence": 4.0,
        "business_plausibility": 3.0,
        "product_fit": 5.0,
        "data_feasibility": 4.0,
        "implementation_cost": 2.0,
    }
    assert RW.score_research_value(scores) == pytest.approx(4 * 3 * 5 * 4 / 2)


def test_research_value_rejects_non_positive_cost() -> None:
    with pytest.raises(ValueError):
        RW.score_research_value({"implementation_cost": 0.0})


def test_critical_gates_cannot_be_compensated_by_a_high_total() -> None:
    scores = {
        "evidence": 5.0,
        "business_plausibility": 5.0,
        "product_fit": 5.0,
        "data_feasibility": 5.0,
        "capital_fit": 2.0,  # below the 4 threshold
        "tradability": 5.0,
    }
    result = RW.critical_gates(scores)
    assert result["passed"] is False
    assert "capital_fit" in result["failing"]


def test_critical_gates_pass_when_every_threshold_is_met() -> None:
    scores = {name: float(thr) for name, thr in RW.CRITICAL_GATE_THRESHOLDS.items()}
    result = RW.critical_gates(scores)
    assert result["passed"] is True
    assert result["failing"] == []


# --------------------------------------------------------------------------- #
# §30-§32 — effort, data cost and economics sanity
# --------------------------------------------------------------------------- #


def test_high_effort_marginal_opportunity_is_rejected() -> None:
    assert RW.accept_research_effort("HIGH", marginal=True) is False
    assert RW.accept_research_effort("HIGH", marginal=False) is True
    assert RW.accept_research_effort("LOW", marginal=True) is True


def test_business_economics_sanity() -> None:
    assert RW.business_economics_sanity(500.0, 100.0) is True
    assert RW.business_economics_sanity(50.0, 100.0) is False


# --------------------------------------------------------------------------- #
# §22-§23 — the business reentry gate
# --------------------------------------------------------------------------- #


def test_business_reentry_gate_requires_every_condition() -> None:
    all_true = dict.fromkeys(RW.G_BUSINESS_REENTRY_CONDITIONS, True)
    assert RW.business_reentry_gate(all_true)["G_BUSINESS_REENTRY"] == "PASS"
    one_missing = dict(all_true)
    one_missing["BENCHMARK_CASE"] = False
    result = RW.business_reentry_gate(one_missing)
    assert result["G_BUSINESS_REENTRY"] == "FAIL"
    assert result["failing_conditions"] == ["BENCHMARK_CASE"]


def test_business_reentry_gate_normal_outcome_is_fail() -> None:
    assert RW.business_reentry_gate({})["G_BUSINESS_REENTRY"] == "FAIL"
    assert len(RW.business_reentry_gate({})["failing_conditions"]) == 9


# --------------------------------------------------------------------------- #
# §24-§27 — one-candidate lease
# --------------------------------------------------------------------------- #


def test_reentry_lease_forces_single_parameter_variant() -> None:
    lease = RW.create_reentry_lease(
        candidate_id="SC-REENTRY-001",
        trigger="A_NEW_EXTERNAL_EVIDENCE",
        source_basis="doi:example",
        capital=200.0,
        instrument="fractional ETF",
        primary_benchmark="buy-and-hold benchmark",
        risk_matched_benchmark="60/40 benchmark",
        cost_model_requirement="retail fees + spread",
        fastest_kill_test="cost > reported edge",
        max_parameter_variants=3,
    )
    assert lease["max_parameter_variants"] == RW.MAX_PARAMETER_VARIANTS == 1
    assert lease["expires_on_completion"] is True


def test_reentry_lease_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        RW.create_reentry_lease(
            candidate_id="",
            trigger="A_NEW_EXTERNAL_EVIDENCE",
            source_basis="x",
            capital=200.0,
            instrument="x",
            primary_benchmark="x",
            risk_matched_benchmark="x",
            cost_model_requirement="x",
            fastest_kill_test="x",
        )


def test_at_most_one_candidate_is_authorized() -> None:
    one = RW.authorize_candidates([{"candidate_id": "A"}])
    assert one["authorized"] is True
    assert one["count"] == 1
    assert one["over_budget"] is False
    two = RW.authorize_candidates([{"candidate_id": "A"}, {"candidate_id": "B"}])
    assert two["over_budget"] is True
    assert two["count"] == 0
    assert two["authorized"] is False


# --------------------------------------------------------------------------- #
# §45-§48 — decision defaults and unchanged economic state
# --------------------------------------------------------------------------- #


def test_no_qualified_event_yields_no_action() -> None:
    decision = RW.reentry_decision(qualified_events=[])
    assert decision["decision"] == "NO_ACTION"
    assert decision["G_BUSINESS_REENTRY"] == "NOT_EVALUATED"
    assert decision["authorized_candidate"] == "NONE"
    assert decision["next"] == "WAIT"
    assert decision["next_alpha_rfc_allowed"] == "NO"


def test_profit_kpis_and_freeze_are_fixed() -> None:
    assert RW.ALPHA_RESEARCH_FREEZE == "ACTIVE"
    assert RW.NEXT_ALPHA_RFC_ALLOWED == "NO"
    assert RW.ACTIVE_CANDIDATES == 0
    assert RW.PROFIT_KPIS == {
        "BUSINESS_VALIDATED_EDGE_COUNT": 0,
        "PAPER_CANDIDATE_COUNT": 0,
        "FORWARD_PROFITABLE_COUNT": 0,
        "LIVE_PROFITABLE_COUNT": 0,
        "REALIZED_TRADING_PNL": 0,
    }


def test_capital_contract_is_200_usdt() -> None:
    assert RW.REFERENCE_CAPITAL_USDT == 200.0
    assert RW.CAPITAL_CONSTRAINT == "STRATEGY MUST FIT CAPITAL"


def test_no_daemon_and_event_driven_only() -> None:
    assert RW.REENTRY_MODE == "EVENT_DRIVEN"
    assert RW.DAEMON_ALLOWED is False
    assert RW.SCHEDULED_ALPHA_SEARCH_ALLOWED is False


def test_next_economic_milestone_is_the_first_business_edge() -> None:
    assert RW.NEXT_ECONOMIC_MILESTONE == "BUSINESS_VALIDATED_EDGE 0 -> 1"


def test_false_success_counts_only_real_claims() -> None:
    assert RW.false_success_count({}) == 0
    assert RW.false_success_count({"new_strategy_invented": True}) == 1
    assert (
        RW.false_success_count(
            {"new_strategy_invented": True, "freeze_released_without_pass": True}
        )
        == 2
    )


def test_budgets_are_the_declared_limits() -> None:
    assert RW.MAX_PENDING_OPPORTUNITIES == 10
    assert RW.MAX_DEEP_REVIEW == 2
    assert RW.MAX_AUTHORIZED_CANDIDATES == 1
    assert RW.MAX_PARAMETER_VARIANTS == 1


# --------------------------------------------------------------------------- #
# §56 — no-strategy rule (source scan)
# --------------------------------------------------------------------------- #


def test_module_declares_no_strategy_or_backtest_code() -> None:
    path = REPO / "src" / "trading_bot" / "research" / "reentry_watch.py"
    text = path.read_text(encoding="utf-8")
    forbidden = (
        r"class\s+\w*(Strategy|Signal|Portfolio|Backtest|Broker|OrderBook|ExecutionEngine)",
        r"def\s+(backtest|run_backtest|simulate|place_order|submit_order|generate_signal)\b",
    )
    for pattern in forbidden:
        assert re.search(pattern, text) is None, pattern


# --------------------------------------------------------------------------- #
# §36/§38 — tracked registry & ledger consistency (skipped if not generated)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-044 artifacts not generated")
def test_registry_and_ledger_are_consistent() -> None:
    registry = json.loads((DOCS / "REENTRY_EVIDENCE_REGISTRY.json").read_text(encoding="utf-8"))
    ledger = json.loads((DOCS / "REENTRY_DECISION_LEDGER.json").read_text(encoding="utf-8"))
    assert registry["items"] == []
    fields = ("review_id", "date", "opportunity", "trigger", "decision", "reason")
    for entry in ledger["entries"]:
        assert all(str(entry.get(f, "")).strip() for f in fields)
    decisions = {e["review_id"]: e["decision"] for e in ledger["entries"]}
    assert decisions.get("RFC042") == "NO_REENTRY"
    assert decisions.get("RFC044") == "NO_ACTION"


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-044 artifacts not generated")
def test_gate_audit_reports_not_evaluated_without_event() -> None:
    audit = json.loads((OUT / "REENTRY_GATE_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["G_BUSINESS_REENTRY"] == "NOT_EVALUATED"
    assert audit["gate_result_for_absent_opportunity"]["G_BUSINESS_REENTRY"] == "FAIL"
    assert audit["profit_kpis_unchanged"] is True
    assert audit["capital_respected"] is True


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-044 artifacts not generated")
def test_final_report_starts_with_the_exact_title() -> None:
    md = (REPORTS / "RFC044_FINAL_REPORT.md").read_text(encoding="utf-8")
    assert md.splitlines()[0] == "RFC-044 PROFITABILITY REENTRY WATCH"
    report = json.loads((REPORTS / "RFC044_FINAL_REPORT.json").read_text(encoding="utf-8"))
    assert report["new_qualified_event"] == "NO"
    assert report["g_business_reentry"] == "NOT_EVALUATED"
    assert report["authorized_candidate"] == "NONE"
    assert report["next"] == "WAIT"
