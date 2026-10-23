"""RFC-034 tests — profitability-research closure & re-entry governance (§76).

Pure and deterministic: they pin the frozen economic marker, the canonical
candidate registry, the promotion/gate-order invariant, the verification-vs-
economic separation, the re-entry policy and the "no active candidate" state.
"""

from __future__ import annotations

import pytest

from trading_bot.research import economic_closure as EC
from trading_bot.research.certification_gate import (
    MANDATORY_GATES,
    check_gate_order,
    evaluate_promotion,
)

# --------------------------------------------------------------------------- #
# §76 — candidate registry statuses
# --------------------------------------------------------------------------- #


def test_canonical_candidate_statuses() -> None:
    assert EC.canonical_candidates() == {
        "EXT-TSMOM-001": "INVALIDATED_TRADABILITY",
        "EXT-TSMOM-002": "REJECTED_HISTORICAL_PLAUSIBILITY",
        "EXT-TSMOM-003": "REJECTED_VALIDATION",
        "EXT-XMOM-001": "REJECTED_ROBUSTNESS",
    }


def test_registry_ids_unique() -> None:
    ids = [c.candidate_id for c in EC.CANDIDATES]
    assert len(ids) == len(set(ids)) == 4


def test_every_candidate_gate_map_is_complete() -> None:
    for c in EC.CANDIDATES:
        assert set(c.gates) == set(MANDATORY_GATES)


# --------------------------------------------------------------------------- #
# §76 — no promotable invalidated candidate
# --------------------------------------------------------------------------- #


def test_no_promotable_invalidated_candidate() -> None:
    for c in EC.CANDIDATES:
        assert c.promotable is False, c.candidate_id
        assert c.blocking_gates, c.candidate_id


def test_promotable_matches_certification_gate() -> None:
    for c in EC.CANDIDATES:
        assert c.promotable == evaluate_promotion(c.gates).promotable


def test_no_candidate_is_paper_candidate() -> None:
    assert all(c.status != "PAPER_CANDIDATE" for c in EC.CANDIDATES)


# --------------------------------------------------------------------------- #
# §76 — gate ordering (a later PASS cannot compensate an earlier FAIL)
# --------------------------------------------------------------------------- #


def test_later_pass_does_not_lift_earlier_fail() -> None:
    gates = {
        "G_VALIDATION": "FAIL",
        "G_ROBUSTNESS": "NOT_REACHED",
        "G_HOLDOUT": "NOT_REACHED",
        "G_TRADABILITY": "PASS",
        "G_INDEPENDENT_VERIFICATION": "PASS",
    }
    assert evaluate_promotion(gates).promotable is False
    assert not check_gate_order(gates).passed  # order violation detected


def test_missing_gate_is_not_pass() -> None:
    gates = {
        "G_VALIDATION": "PASS",
        "G_ROBUSTNESS": "PASS",
        "G_HOLDOUT": "PASS",
        "G_TRADABILITY": "PASS",
    }
    assert evaluate_promotion(gates).promotable is False


def test_all_pass_is_promotable() -> None:
    gates = dict.fromkeys(MANDATORY_GATES, "PASS")
    assert evaluate_promotion(gates).promotable is True


def test_no_active_candidate_with_order_violation_is_promotable() -> None:
    for c in EC.CANDIDATES:
        if not check_gate_order(c.gates).passed:
            assert c.promotable is False


# --------------------------------------------------------------------------- #
# §76 — verification / economic result separation (§36-§40)
# --------------------------------------------------------------------------- #


def test_independent_reproduction_plus_negative_validation() -> None:
    out = EC.regression_verification_and_economic(reproduction_exact=True, validation_status="FAIL")
    assert out["verification_status"] == "PASS"
    assert out["economic_result"] == "FAIL"
    assert out["false_success"] == 0


def test_verifier_checks_do_not_count_strategy_loss() -> None:
    checks = EC.VerifierChecks(
        reproduction_exact=True,
        hashes_match=True,
        pit_ok=True,
        accounting_reconciled=True,
        contract_ok=True,
    )
    assert checks.failed() == ()
    assert checks.status == EC.VerificationStatus.PASS


def test_reproduction_mismatch_fails_verification() -> None:
    checks = EC.VerifierChecks(
        reproduction_exact=False,
        hashes_match=True,
        pit_ok=True,
        accounting_reconciled=True,
        contract_ok=True,
    )
    assert checks.failed() == ("reproduction_mismatch",)
    assert checks.status == EC.VerificationStatus.FAIL


def test_false_success_triggers() -> None:
    claim = EC.ClosureClaim(invalidated_candidate_promotable=True)
    assert claim.false_success() == ("invalidated_candidate_remains_promotable",)
    assert EC.ClosureClaim().false_success() == ()
    assert len(EC.FALSE_SUCCESS_TRIGGERS) == 6


# --------------------------------------------------------------------------- #
# §76 — re-entry policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.5, "REJECT"),
        (1.0, "TOO_THIN"),
        (1.24, "TOO_THIN"),
        (1.25, "WEAK"),
        (1.49, "WEAK"),
        (1.5, "POTENTIALLY_RESEARCHABLE"),
        (1.99, "POTENTIALLY_RESEARCHABLE"),
        (2.0, "STRONG_HEADROOM"),
        (5.0, "STRONG_HEADROOM"),
    ],
)
def test_headroom_classes(ratio: float, expected: str) -> None:
    assert EC.classify_headroom(ratio) == expected


def test_headroom_negative_rejected() -> None:
    with pytest.raises(ValueError):
        EC.classify_headroom(-0.1)


def test_admission_rejects_weak_critical_dimension() -> None:
    scores = dict.fromkeys(EC.SCORECARD_DIMENSIONS, 4)
    scores["evidence_strength"] = 1
    decision = EC.admission_decision(scores)
    assert decision.decision == "REJECT"
    assert any("evidence_strength" in r for r in decision.reasons)


def test_admission_approves_strong_candidate() -> None:
    scores = dict.fromkeys(EC.SCORECARD_DIMENSIONS, 4)
    assert EC.admission_decision(scores).decision == "APPROVED_FOR_RESEARCH"


def test_admission_rejects_missing_dimension() -> None:
    scores = {"evidence_strength": 5}
    assert EC.admission_decision(scores).decision == "REJECT_MISSING_DIMENSION"


def test_reentry_states_and_triggers() -> None:
    assert EC.REENTRY_STATES[0] == "PAUSED"
    assert EC.REENTRY_STATES[-1] == "REPRODUCTION"
    assert not (set(EC.VALID_REOPEN_TRIGGERS) & set(EC.INVALID_REOPEN_TRIGGERS))
    assert EC.is_valid_reopen_trigger("new peer-reviewed anomaly")
    assert EC.is_valid_reopen_trigger("new accessible dataset")
    assert not EC.is_valid_reopen_trigger("try more thresholds")
    assert not EC.is_valid_reopen_trigger("increase leverage")


def test_gate_order_canonical() -> None:
    assert EC.GATE_ORDER[0] == "DATA"
    assert EC.GATE_ORDER[-1] == "LIVE"
    assert EC.MAX_STRATEGIES == 2
    assert EC.MAX_CORE_VARIANTS_PER_STRATEGY == 3


# --------------------------------------------------------------------------- #
# §76 — no active candidate state & canonical marker
# --------------------------------------------------------------------------- #


def test_no_active_or_promotable_candidates() -> None:
    assert EC.active_candidate_count() == 0


def test_economic_marker_frozen() -> None:
    m = EC.ECONOMIC_MARKER
    assert m.statistical_historical_effect == 1
    assert m.all_execution_zeros is True


def test_canonical_project_marker() -> None:
    assert EC.PROFITABILITY_RESEARCH_STATUS == "PAUSED"
    assert EC.PLATFORM_STATUS == "RESEARCH_CAPABLE"
    assert EC.ECONOMIC_STATUS == "NO_VALIDATED_EXECUTABLE_EDGE"
    assert EC.CURRENT_DECISION == "PAUSE_TRADING_PROJECT"
    assert EC.NEXT_ALPHA_RFC_ALLOWED is False


def test_ledger_covers_all_economic_rfcs() -> None:
    rfcs = {row.rfc for row in EC.LEDGER}
    assert {
        "RFC-010B",
        "RFC-020",
        "RFC-021",
        "RFC-022",
        "RFC-023",
        "RFC-024",
        "RFC-025",
        "RFC-026",
        "RFC-027",
        "RFC-028",
        "RFC-029",
        "RFC-030",
        "RFC-031",
        "RFC-032",
        "RFC-033",
    } <= rfcs


def test_superseded_claims_present() -> None:
    assert EC.SUPERSEDED_CLAIMS
    assert any("PAPER CANDIDATES" in s["source"] for s in EC.SUPERSEDED_CLAIMS)
