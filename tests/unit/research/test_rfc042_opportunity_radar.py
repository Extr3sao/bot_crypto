"""RFC-042 tests — business opportunity radar & reentry governance (§53).

Governance and scoring only: they pin the search budget, the non-compensable
critical dimensions, the same-family rehash rejection, the capital-fit
elimination, the reentry trigger requirement, the single-candidate lease, the
freeze transition and the absence of any strategy artifact.
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

from trading_bot.research import opportunity_radar as OR  # noqa: E402


def make_opp(**overrides: Any) -> OR.Opportunity:
    base: dict[str, Any] = {
        "opportunity_id": "OPP-TEST-001",
        "title": "synthetic test opportunity",
        "strategy_family": "overnight drift",
        "mechanism": "behavioral",
        "trigger": "A",
        "instrument": "UCITS ETF",
        "capital_fit": "PASS",
        "product_fit_200": "PASS",
        "tradability": "PASS",
        "data_feasibility": "PASS",
        "post_publication": "SURVIVES",
        "implementation_distance": "RUNTIME_READY",
        "time_to_economic_answer": "SHORT",
        "source_ids": ("SRC-042-01",),
    }
    base.update(overrides)
    return OR.Opportunity(**base)


def full_scores(**overrides: int) -> dict[str, int]:
    scores = dict.fromkeys(OR.SCORECARD_DIMENSIONS, 5)
    scores.update(overrides)
    return scores


# --------------------------------------------------------------------------- #
# §21-§22 — scorecard and non-compensable critical fails
# --------------------------------------------------------------------------- #


def test_scorecard_has_ten_dimensions_and_five_critical() -> None:
    assert len(OR.SCORECARD_DIMENSIONS) == 10
    assert set(OR.CRITICAL_THRESHOLDS) == {
        "external_evidence",
        "business_edge_plausibility",
        "capital_fit_200",
        "tradability",
        "data_feasibility",
    }
    assert OR.CRITICAL_THRESHOLDS["capital_fit_200"] == 4


def test_scorecard_rejects_missing_dimension() -> None:
    with pytest.raises(ValueError):
        OR.total_score({"external_evidence": 5})


def test_scorecard_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        OR.total_score(full_scores(external_evidence=6))
    with pytest.raises(ValueError):
        OR.total_score(full_scores(external_evidence=-1))


def test_critical_fail_cannot_be_compensated_by_the_total() -> None:
    scores = full_scores(business_edge_plausibility=2)
    assert OR.total_score(scores) == 47
    assert "business_edge_plausibility" in OR.critical_fails(scores)
    verdict = OR.gate_business_reentry(
        trigger="A",
        materially_new_evidence=True,
        credible_mechanism=True,
        capital_fit="PASS",
        tradability_score=5,
        data_feasibility_score=5,
        headroom=3.0,
        benchmark_adjusted_value_credible=True,
        fast_falsification_defined=True,
        scores=scores,
        materially_better_than_archive=True,
    )
    assert verdict.passed is False
    assert "critical_dimension_below_threshold" in verdict.failing


def test_high_score_only_buys_a_deep_review() -> None:
    opp = make_opp(scores=full_scores(business_edge_plausibility=2))
    assert OR.select_deep_reviews([opp]) == ("OPP-TEST-001",)
    assert OR.critical_fails(opp.scores)  # still cannot pass the gate


# --------------------------------------------------------------------------- #
# §6 — budget caps
# --------------------------------------------------------------------------- #


def test_max_opportunities_screened_enforced() -> None:
    opps = [make_opp(opportunity_id=f"OPP-{i}", scores=full_scores()) for i in range(9)]
    assert OR.MAX_OPPORTUNITIES_SCREENED == 8
    with pytest.raises(ValueError):
        OR.screened(opps)


def test_max_deep_reviews_enforced() -> None:
    assert OR.MAX_DEEP_REVIEWS == 3
    opps = [make_opp(opportunity_id=f"OPP-{i}", scores=full_scores()) for i in range(5)]
    assert len(OR.select_deep_reviews(opps)) == 3
    with pytest.raises(ValueError):
        OR.select_deep_reviews(opps, limit=4)


def test_max_one_authorization_enforced() -> None:
    assert OR.MAX_REENTRY_CANDIDATES == 1
    assert OR.authorize_single_candidate([]) is None
    assert OR.authorize_single_candidate(["OPP-042-002"]) == "OPP-042-002"
    with pytest.raises(ValueError):
        OR.authorize_single_candidate(["OPP-042-001", "OPP-042-002"])


# --------------------------------------------------------------------------- #
# §8 — same-family rehash rejection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("original", "renamed"),
    [
        ("SMA crossover trend", "EMA crossover trend"),
        ("12 months lookback", "10 months lookback"),
        ("momentum", "relative strength"),
        ("threshold 0 crossover", "threshold 1% crossover"),
        ("BTC trend following", "ETH trend following"),
        ("ETF A trend", "ETF B trend"),
    ],
)
def test_same_family_rehash_is_rejected(original: str, renamed: str) -> None:
    assert OR.is_same_family_rehash(original, renamed)


def test_genuinely_different_families_are_not_rehash() -> None:
    assert not OR.is_same_family_rehash("overnight drift", "covered call volatility risk premium")
    assert not OR.is_same_family_rehash("turn-of-the-month", "minimum volatility index")


def test_rehash_opportunity_is_not_scored_or_deep_reviewed() -> None:
    opp = make_opp(
        rehash_of=("SC-TREND-001",),
        scores=full_scores(),
    )
    assert OR.disposition(opp) == "REJECTED_SAME_FAMILY_REHASH"
    assert OR.screened([opp]) == ()
    assert OR.select_deep_reviews([opp]) == ()


# --------------------------------------------------------------------------- #
# §7/§10-§11 — exclusions and capital fit
# --------------------------------------------------------------------------- #


def test_excluded_family_without_new_evidence_is_not_screened() -> None:
    opp = make_opp(excluded_family_key="crypto_tsmom", scores=full_scores())
    assert OR.disposition(opp) == "EXCLUDED_BY_DEFAULT_WITHOUT_NEW_EVIDENCE"
    assert OR.screened([opp]) == ()


def test_excluded_family_with_materially_new_evidence_is_screened() -> None:
    opp = make_opp(
        excluded_family_key="crypto_tsmom",
        materially_new_evidence=True,
        scores=full_scores(),
    )
    assert OR.disposition(opp) == "SCREENED"


def test_capital_fit_fail_is_eliminated_even_with_a_perfect_score() -> None:
    opp = make_opp(capital_fit="FAIL", scores=full_scores())
    assert OR.disposition(opp) == "REJECTED_CAPITAL_FIT_200"
    assert OR.screened([opp]) == ()


def test_product_fit_fail_is_eliminated() -> None:
    opp = make_opp(product_fit_200="FAIL", scores=full_scores())
    assert OR.disposition(opp) == "REJECTED_CAPITAL_FIT_200"


# --------------------------------------------------------------------------- #
# §26-§27 — the reentry gate
# --------------------------------------------------------------------------- #


def gate(**overrides: Any) -> OR.ReentryVerdict:
    kwargs: dict[str, Any] = {
        "trigger": "A",
        "materially_new_evidence": True,
        "credible_mechanism": True,
        "capital_fit": "PASS",
        "tradability_score": 5,
        "data_feasibility_score": 5,
        "headroom": 3.0,
        "benchmark_adjusted_value_credible": True,
        "fast_falsification_defined": True,
        "scores": full_scores(),
        "materially_better_than_archive": True,
    }
    kwargs.update(overrides)
    return OR.gate_business_reentry(**kwargs)


def test_fully_specified_proposal_passes_the_gate() -> None:
    assert gate().passed is True


def test_reentry_requires_a_valid_trigger() -> None:
    assert gate(trigger=None).passed is False
    assert "invalid_or_absent_trigger" in gate(trigger=None).failing
    assert "invalid_or_absent_trigger" in gate(trigger="Z").failing


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"materially_new_evidence": False}, "no_new_or_material_evidence"),
        ({"credible_mechanism": False}, "implausible_economic_mechanism"),
        ({"capital_fit": "LIMITED"}, "capital_fit_200_not_pass"),
        ({"tradability_score": 3}, "tradability_below_4"),
        ({"data_feasibility_score": 2}, "data_feasibility_below_3"),
        ({"headroom": 1.0}, "insufficient_cost_headroom"),
        ({"headroom": None}, "insufficient_cost_headroom"),
        ({"benchmark_adjusted_value_credible": False}, "no_credible_benchmark_adjusted_value"),
        ({"fast_falsification_defined": False}, "no_fast_falsification_path"),
        (
            {"materially_better_than_archive": False},
            "not_materially_better_than_archived_candidates",
        ),
    ],
)
def test_each_missing_condition_blocks_reentry(override: dict[str, Any], expected: str) -> None:
    verdict = gate(**override)
    assert verdict.passed is False
    assert expected in verdict.failing


def test_headroom_classification() -> None:
    assert OR.headroom_class(2.0) == "STRONG"
    assert OR.headroom_class(1.7) == "RESEARCHABLE"
    assert OR.headroom_class(1.2) == "WEAK"
    assert OR.headroom_class(None) == "UNKNOWN"


# --------------------------------------------------------------------------- #
# §28-§31/§40-§42 — freeze transition and the single lease
# --------------------------------------------------------------------------- #


def test_no_candidate_keeps_the_freeze_active() -> None:
    transition = OR.freeze_transition(None)
    assert transition["research_freeze"] == "ACTIVE"
    assert transition["research_status"] == "PAUSED"
    assert transition["next_alpha_rfc_allowed"] is False
    assert transition["release_scope"] == "NONE"


def test_one_candidate_is_released_for_one_candidate_only() -> None:
    transition = OR.freeze_transition("OPP-042-002")
    assert transition["research_freeze"] == "RELEASED_FOR_ONE_CANDIDATE"
    assert transition["research_status"] == "REENTRY_APPROVED"
    assert transition["next_alpha_rfc_allowed"] is True
    assert transition["release_scope"] == "ONE_CANDIDATE"


def test_reentry_lease_covers_one_candidate_and_expires() -> None:
    lease = OR.reentry_lease(
        candidate_id="OPP-042-002",
        source_basis=["SRC-042-07"],
        capital_target=200.0,
        primary_benchmark="UCITS MSCI World ETF",
        risk_matched_benchmark="volatility-scaled passive equity",
        max_parameter_variants=0,
        research_cycle_id="RC-042-001",
    )
    assert lease["candidate_id"] == "OPP-042-002"
    assert lease["capital_target"] == 200.0
    assert lease["expires_on_completion"] is True
    assert lease["max_parameter_variants"] == 0


# --------------------------------------------------------------------------- #
# §49/§51 — KPIs and FALSE_SUCCESS
# --------------------------------------------------------------------------- #


def test_profit_kpis_are_zero() -> None:
    assert OR.PROFIT_KPIS["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
    assert OR.PROFIT_KPIS["PAPER_CANDIDATE_COUNT"] == 0
    assert OR.PROFIT_KPIS["FORWARD_PROFITABLE_COUNT"] == 0
    assert OR.PROFIT_KPIS["LIVE_PROFITABLE_COUNT"] == 0
    assert OR.PROFIT_KPIS["REALIZED_TRADING_PNL"] == 0
    assert OR.REFERENCE_CAPITAL_USDT == 200.0


def test_false_success_counts_only_true_claims() -> None:
    assert OR.false_success_count({}) == 0
    assert OR.false_success_count({"strategy_implemented": True}) == 1
    assert OR.false_success_count(dict.fromkeys(OR.FALSE_SUCCESS_TRIGGERS, True)) == len(
        OR.FALSE_SUCCESS_TRIGGERS
    )


# --------------------------------------------------------------------------- #
# §43 — no strategy artifact
# --------------------------------------------------------------------------- #


def test_module_exposes_no_executable_trading_constructs() -> None:
    source = (REPO / "src" / "trading_bot" / "research" / "opportunity_radar.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        r"^\s*class\s+\w*(Strategy|Signal|Portfolio|Backtest|Broker|Order|Pnl)",
        r"^\s*def\s+\w*(signal|backtest|pnl|portfolio|place_order|submit_order)\b",
    )
    for pattern in forbidden:
        assert not re.findall(pattern, source, flags=re.MULTILINE)


# --------------------------------------------------------------------------- #
# artifacts (present after `scripts/rfc042_run.py` + `rfc042_verify.py`)
# --------------------------------------------------------------------------- #

OUT = REPO / "reports" / "business-opportunity-radar"
HAS_ARTIFACTS = (OUT / "REENTRY_DECISION.json").exists()


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-042 artifacts not generated in this checkout")
def test_artifacts_record_a_failed_reentry_and_an_active_freeze() -> None:
    decision = json.loads((OUT / "REENTRY_DECISION.json").read_text(encoding="utf-8"))
    assert decision["result"] == "FAIL"
    assert decision["authorized_candidate"] == "NONE"
    assert decision["transition"]["research_freeze"] == "ACTIVE"
    assert decision["transition"]["next_alpha_rfc_allowed"] is False


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-042 artifacts not generated in this checkout")
def test_final_report_shape_and_zero_kpis() -> None:
    report = json.loads((REPO / "reports" / "RFC042_FINAL_REPORT.json").read_text(encoding="utf-8"))
    assert report["opportunities_screened"] <= OR.MAX_OPPORTUNITIES_SCREENED
    assert report["deep_reviewed"] <= OR.MAX_DEEP_REVIEWS
    assert report["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
    assert report["next_alpha_rfc_allowed"] == "NO"
    assert report["next"] == "WAIT"
    first_line = (
        (REPO / "reports" / "RFC042_FINAL_REPORT.md").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first_line == "RFC-042 BUSINESS OPPORTUNITY RADAR"
