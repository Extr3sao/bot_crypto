"""RFC-035 focused tests (§90) - admission review, not implementation.

Covers: scorecard determinism, critical-dimension rejection, the top-5 / finalist
/ authorized caps, G_REENTRY logic, no authorization on weak evidence or failed
tradability, the PAUSED -> REENTRY_APPROVED transition, and the exact decision
value vocabulary.
"""

from __future__ import annotations

import dataclasses

from trading_bot.research import strategic_profitability_v2 as SP


def _variant(base_id: str, **overrides: object) -> SP.StrategyFamily:
    base = SP.family_by_id(base_id)
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# determinism & structure
# --------------------------------------------------------------------------- #


def test_universe_is_ten_to_fifteen_families() -> None:
    assert 10 <= len(SP.STRATEGY_FAMILIES) <= 15


def test_required_groups_a_to_j_present() -> None:
    groups = {f.required_group for f in SP.STRATEGY_FAMILIES}
    for g in "ABCDEFGHIJ":
        assert g in groups


def test_scorecard_is_deterministic() -> None:
    a = SP.plan_summary()
    b = SP.plan_summary()
    assert a == b
    assert [f.family_id for f in SP.select_top5()] == [f.family_id for f in SP.select_top5()]


def test_every_family_scores_all_dimensions_in_range() -> None:
    for fam in SP.STRATEGY_FAMILIES:
        assert set(fam.scores) == set(SP.SCORECARD_DIMENSIONS)
        assert all(0 <= v <= 5 for v in fam.scores.values())


# --------------------------------------------------------------------------- #
# critical-dimension rejection
# --------------------------------------------------------------------------- #


def test_critical_dimension_weak_removes_from_top5_pool() -> None:
    weak = _variant(
        "MANAGED_FUTURES_TREND",
        scores={**SP.family_by_id("MANAGED_FUTURES_TREND").scores, "data_feasibility": 1},
    )
    assert weak.weak_critical_dimensions == ("data_feasibility",)
    assert not weak.in_top5_pool


def test_volatility_risk_premium_is_data_blocked() -> None:
    vrp = SP.family_by_id("VOLATILITY_RISK_PREMIUM")
    assert "data_feasibility" in vrp.weak_critical_dimensions
    assert vrp.family_id not in [f.family_id for f in SP.select_top5()]
    gate = SP.evaluate_reentry_gate()
    assert SP.decision_for(vrp, gate) == "DEFER_DATA"


# --------------------------------------------------------------------------- #
# caps
# --------------------------------------------------------------------------- #


def test_top5_cap() -> None:
    assert len(SP.select_top5()) <= SP.MAX_TOP5


def test_finalist_cap() -> None:
    assert len(SP.select_finalists()) <= SP.MAX_FINALISTS


def test_authorized_cap() -> None:
    assert len(SP.authorize_reproductions()) <= SP.MAX_AUTHORIZED
    assert SP.MAX_AUTHORIZED == 2
    assert SP.MAX_IMPLEMENTED_STRATEGIES == 2
    assert SP.MAX_PARAMETER_VARIANTS == 3


def test_finalists_are_subset_of_top5() -> None:
    top5 = {f.family_id for f in SP.select_top5()}
    assert {f.family_id for f in SP.select_finalists()} <= top5


def test_finalist_excludes_reject_economics() -> None:
    for fam in SP.select_finalists():
        assert fam.headroom_class not in {"REJECT", "TOO_THIN"}


# --------------------------------------------------------------------------- #
# G_REENTRY logic
# --------------------------------------------------------------------------- #


def test_gate_passes_with_a_qualifying_family() -> None:
    gate = SP.evaluate_reentry_gate()
    assert gate.status is SP.ReentryStatus.PASS
    assert gate.authorized_p1 == "MANAGED_FUTURES_TREND"
    assert gate.authorized_p2 == "FUTURES_CURVE_CARRY"


def test_no_authorization_on_weak_evidence() -> None:
    weak = _variant(
        "MANAGED_FUTURES_TREND",
        scores={**SP.family_by_id("MANAGED_FUTURES_TREND").scores, "evidence_strength": 3},
    )
    assert SP.candidate_passes_reentry(weak) is False


def test_no_authorization_on_tradability_failure() -> None:
    weak = _variant(
        "MANAGED_FUTURES_TREND",
        scores={**SP.family_by_id("MANAGED_FUTURES_TREND").scores, "tradability": 2},
    )
    assert SP.candidate_passes_reentry(weak) is False


def test_no_authorization_on_paid_data() -> None:
    paid = _variant("MANAGED_FUTURES_TREND", data_cost_class="PAID")
    assert SP.candidate_passes_reentry(paid) is False


def test_net_evidence_exception_allows_thin_headroom() -> None:
    exc = _variant(
        "MANAGED_FUTURES_TREND", headroom_ratio=1.2, net_evidence_exception=True
    )
    assert SP.candidate_passes_reentry(exc) is True


# --------------------------------------------------------------------------- #
# status transition
# --------------------------------------------------------------------------- #


def test_paused_to_reentry_approved_transition() -> None:
    gate = SP.evaluate_reentry_gate()
    assert SP.ENTRY_PROFITABILITY_RESEARCH_STATUS == "PAUSED"
    assert SP.ENTRY_NEXT_ALPHA_RFC_ALLOWED is False
    assert SP.profitability_research_status(gate) == "REENTRY_APPROVED"
    assert SP.next_alpha_rfc_allowed(gate) is True


def test_failed_gate_keeps_paused() -> None:
    failed = SP.ReentryGate(SP.ReentryStatus.FAIL, (), None, None)
    assert SP.profitability_research_status(failed) == "PAUSED"
    assert SP.next_alpha_rfc_allowed(failed) is False


# --------------------------------------------------------------------------- #
# decisions & false success
# --------------------------------------------------------------------------- #


def test_decisions_use_exact_vocabulary() -> None:
    gate = SP.evaluate_reentry_gate()
    for fam in SP.STRATEGY_FAMILIES:
        assert SP.decision_for(fam, gate) in SP.DECISIONS


def test_relative_value_pairs_rejected_on_economics() -> None:
    gate = SP.evaluate_reentry_gate()
    assert SP.decision_for(SP.family_by_id("RELATIVE_VALUE_PAIRS"), gate) == "REJECT_ECONOMICS"


def test_false_success_audit_is_zero() -> None:
    gate = SP.evaluate_reentry_gate()
    assert SP.audit_false_success(gate)["false_success"] == 0


def test_economic_marker_stays_at_execution_zeros() -> None:
    summary = SP.plan_summary()
    kpi = summary["kpi"]
    assert kpi["executable_validated_edge_count"] == 0
    assert kpi["robust_edge_count"] == 0
    assert kpi["paper_candidate_count"] == 0
    assert kpi["forward_profitable_count"] == 0
    assert kpi["live_profitable_count"] == 0


# --------------------------------------------------------------------------- #
# headroom bands & source registry
# --------------------------------------------------------------------------- #


def test_headroom_bands() -> None:
    assert SP.classify_headroom(0.9) == "REJECT"
    assert SP.classify_headroom(1.1) == "TOO_THIN"
    assert SP.classify_headroom(1.4) == "WEAK"
    assert SP.classify_headroom(1.7) == "RESEARCHABLE"
    assert SP.classify_headroom(2.5) == "STRONG_HEADROOM"


def test_finalists_have_strong_sources() -> None:
    strong = {s.source_id for s in SP.SOURCES if s.is_strong}
    for fam in SP.select_finalists():
        assert set(fam.source_ids) & strong, fam.family_id
