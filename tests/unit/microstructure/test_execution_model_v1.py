"""Tests for EXECUTION_MODEL_V1 (§PHASE 3)."""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.execution_model_v1 import (
    ExecutionOutcome,
    FillEvidence,
    MakerExecutionModel,
    SyntheticMakerScenario,
    TakerExecutionModel,
)

# --- taker -----------------------------------------------------------------


def test_taker_round_trip_includes_fee_spread_and_slippage() -> None:
    model = TakerExecutionModel(base_slippage_bps=1.0, half_spread_bps=0.5)
    cost = model.round_trip_cost_bps(fee_bps_per_side=10.0, size_usd=1_000.0)
    assert cost == pytest.approx(2 * (10.0 + 0.5 + 1.0))


def test_taker_book_walk_is_zero_within_participation_capacity() -> None:
    model = TakerExecutionModel(participation_rate=0.10)
    assert model.book_walk_bps(size_usd=1_000.0, visible_notional_usd=50_000.0) == 0.0


def test_taker_book_walk_grows_with_size() -> None:
    model = TakerExecutionModel(participation_rate=0.10, books_per_level_bps=0.5)
    assert model.book_walk_bps(size_usd=10_000.0, visible_notional_usd=50_000.0) > 0.0
    big = model.book_walk_bps(size_usd=100_000.0, visible_notional_usd=50_000.0)
    small = model.book_walk_bps(size_usd=10_000.0, visible_notional_usd=50_000.0)
    assert big > small


def test_taker_rejects_invalid_inputs() -> None:
    model = TakerExecutionModel()
    with pytest.raises(ValueError):
        model.book_walk_bps(size_usd=1.0, visible_notional_usd=0.0)
    with pytest.raises(ValueError):
        TakerExecutionModel(participation_rate=0.0)


def test_taker_is_evidence_backed() -> None:
    assert TakerExecutionModel().as_dict()["status"] == "EVIDENCE_BACKED"


# --- maker evidence --------------------------------------------------------


def test_maker_without_evidence_is_execution_model_required() -> None:
    model = MakerExecutionModel(maker_fee_bps=0.0)
    out = model.evaluate(FillEvidence())
    assert out.status == "EXECUTION_MODEL_REQUIRED"
    assert out.expected_effective_cost_bps is None
    assert out.prob_missed == 1.0


def test_partial_evidence_is_not_usable() -> None:
    ev = FillEvidence(n_orders=100, fill_rate=0.6)
    assert not ev.is_usable


def test_maker_with_evidence_reports_effective_cost() -> None:
    model = MakerExecutionModel(maker_fee_bps=0.0)
    ev = FillEvidence(
        n_orders=1_000,
        fill_rate=0.6,
        partial_fill_rate=0.1,
        median_time_to_fill_ms=250,
        adverse_move_after_fill_bps=1.5,
        source="forward-smoke",
    )
    out = model.evaluate(ev)
    assert out.status == "EVIDENCE_BACKED"
    assert out.expected_effective_cost_bps is not None
    assert out.expected_effective_cost_bps > 0.0
    assert out.prob_filled == pytest.approx(0.6)


def test_zero_maker_fee_still_has_positive_effective_cost() -> None:
    """A 0% maker fee is not a free option: adverse selection remains."""
    model = MakerExecutionModel(maker_fee_bps=0.0)
    out = model.evaluate(FillEvidence(n_orders=500, fill_rate=0.5, adverse_move_after_fill_bps=2.0))
    assert out.expected_effective_cost_bps is not None
    assert out.expected_effective_cost_bps > 0.0


def test_maker_rebate_is_rejected_as_a_baseline() -> None:
    with pytest.raises(ValueError, match="rebate"):
        MakerExecutionModel(maker_fee_bps=0.0, maker_rebate_bps=0.5)


# --- synthetic -------------------------------------------------------------


def test_synthetic_scenario_is_labelled_and_not_admissible() -> None:
    model = MakerExecutionModel(maker_fee_bps=0.0)
    scen = SyntheticMakerScenario(
        fill_prob=0.4, partial_prob=0.2, missed_opportunity_cost_bps=3.0, adverse_selection_bps=1.0
    )
    out = model.evaluate_synthetic(scen)
    assert out.status == "SYNTHETIC_STRESS_TEST"
    assert out.prob_filled + out.prob_partial + out.prob_missed == pytest.approx(1.0)


def test_synthetic_label_cannot_be_changed() -> None:
    with pytest.raises(ValueError, match="SYNTHETIC_STRESS_TEST"):
        SyntheticMakerScenario(
            fill_prob=0.5,
            partial_prob=0.0,
            missed_opportunity_cost_bps=1.0,
            adverse_selection_bps=1.0,
            label="REAL",
        )


# --- outcome invariants ----------------------------------------------------


def test_outcome_requires_probabilities_to_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        ExecutionOutcome(
            prob_filled=0.5,
            prob_partial=0.0,
            prob_missed=0.0,
            expected_effective_cost_bps=1.0,
            expected_slippage_bps=1.0,
            adverse_selection_bps=1.0,
            status="SYNTHETIC_STRESS_TEST",
        )


def test_maker_model_dict_is_deterministic() -> None:
    a = MakerExecutionModel(maker_fee_bps=2.0).as_dict()
    b = MakerExecutionModel(maker_fee_bps=2.0).as_dict()
    assert a == b
