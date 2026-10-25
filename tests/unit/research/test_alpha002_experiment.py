"""ALPHA-002 — experiment tests.

These tests defend the campaign's integrity rather than its result:

* the ablation labelled ``FULL`` is asserted to reproduce the frozen registry
  signal exactly, so an ablation can never quietly become a second hypothesis;
* a missing required source is a *non-decision*, never a trade;
* the split is asserted to keep the holdout out of development;
* the statistic is checked against a synthetic known effect and a synthetic null.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha002 as a2
from trading_bot.research import alpha002_experiment as ax
from trading_bot.research import alpha002_features as af

FEATURE_ROW = {
    "ret_z": 1.5,
    "atr_pct": 0.004,
    "oi_chg": 0.01,
    "oi_accel": 0.002,
    "taker_imbalance": 0.12,
    "funding": 0.00005,
    "ls_global_pctile": 0.6,
    "ls_top_position_pctile": 0.55,
    "momentum_delta": -0.001,
    "vol_regime": 1.0,
}


# --------------------------------------------------------------------------- #
# the rule is applied, not re-derived
# --------------------------------------------------------------------------- #


def _random_rows(count: int, seed: int) -> list[dict[str, float]]:
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        rows.append(
            {
                "ret_z": rng.uniform(-4.0, 4.0),
                "atr_pct": rng.uniform(0.001, 0.02),
                "oi_chg": rng.uniform(-0.05, 0.05),
                "oi_accel": rng.uniform(-0.01, 0.01),
                "taker_imbalance": rng.uniform(-1.0, 1.0),
                "funding": rng.uniform(-0.001, 0.001),
                "ls_global_pctile": rng.random(),
                "ls_top_position_pctile": rng.random(),
                "momentum_delta": rng.uniform(-0.01, 0.01),
                "vol_regime": rng.choice([1.0, -1.0]),
            }
        )
    return rows


@pytest.mark.parametrize("hypothesis_id", ["A2-H01", "A2-H02", "A2-H03"])
def test_full_ablation_reproduces_the_frozen_signal(hypothesis_id: str) -> None:
    frozen = a2.SIGNALS[hypothesis_id]
    for row in _random_rows(400, seed=hash(hypothesis_id) % 10_000):
        assert ax.ablation_direction(hypothesis_id, "FULL", row) == frozen(row)


def test_required_features_cover_exactly_what_each_rule_reads() -> None:
    for hypothesis_id in a2.SIGNALS:
        none_row = dict(FEATURE_ROW)
        for name in af.REQUIRED_FEATURES[hypothesis_id]:
            none_row[name] = None  # type: ignore[assignment]
        assert ax.preregistered_direction(hypothesis_id, none_row) is None


def test_a_missing_source_is_never_a_trade() -> None:
    row = dict(FEATURE_ROW)
    row["oi_chg"] = None  # type: ignore[assignment]
    assert ax.preregistered_direction("A2-H01", row) is None
    row2 = dict(FEATURE_ROW)
    row2["funding"] = None  # type: ignore[assignment]
    assert ax.preregistered_direction("A2-H02", row2) is None


def test_frozen_rules_are_the_ones_declared() -> None:
    assert ax.preregistered_direction("A2-H01", FEATURE_ROW) == 1
    # funding 0.00005 is not elevated, so the crowded-reversal arm stands down
    assert ax.preregistered_direction("A2-H02", FEATURE_ROW) == 0
    assert ax.preregistered_direction("A2-H03", FEATURE_ROW) == 1


def test_ablations_remove_the_derivatives_confirmation() -> None:
    # a breakout with no open-interest expansion: PRICE_ONLY fires, +OI does not
    row = dict(FEATURE_ROW)
    row["oi_chg"] = -0.01
    assert ax.ablation_direction("A2-H01", "PRICE_ONLY", row) == 1
    assert ax.ablation_direction("A2-H01", "PRICE+OI", row) == 0
    assert ax.ablation_direction("A2-H01", "FULL", row) == 0


# --------------------------------------------------------------------------- #
# splits
# --------------------------------------------------------------------------- #


def test_calendar_boundaries_are_the_frozen_fractions() -> None:
    boundaries = ax.calendar_boundaries(0, 1000)
    assert boundaries["discovery"] == (0, 600)
    assert boundaries["validation"] == (600, 800)
    assert boundaries["holdout"] == (800, 1001)


def test_holdout_is_excluded_from_development_windows() -> None:
    boundaries = ax.calendar_boundaries(0, 1000)
    for stamp in range(800, 1001):
        assert not ax.in_window(stamp, boundaries["discovery"])
        assert not ax.in_window(stamp, boundaries["validation"])
    assert ax.in_window(799, boundaries["validation"])
    assert not ax.in_window(800, boundaries["validation"])


def test_boundaries_reject_an_inverted_span() -> None:
    with pytest.raises(ValueError):
        ax.calendar_boundaries(10, 10)


# --------------------------------------------------------------------------- #
# the statistic
# --------------------------------------------------------------------------- #


def test_known_positive_effect_is_measured() -> None:
    forwards = [0.001, 0.0012, 0.0008, 0.0011, 0.0009]
    summary = ax.evaluate_directions([1, 1, 1, 1, 1], forwards, hurdle_bps=5.0)
    assert summary["n"] == 5
    assert summary["gross_bps"] == pytest.approx(10.0, abs=1e-6)
    assert summary["net_bps"] == pytest.approx(10.0 - a1.COST_BPS_V3, abs=1e-6)
    assert summary["gross_above_hurdle"] is True


def test_short_direction_flips_the_sign() -> None:
    forwards = [0.001, 0.0012, 0.0008, 0.0011, 0.0009]
    summary = ax.evaluate_directions([-1, -1, -1, -1, -1], forwards, hurdle_bps=5.0)
    assert summary["gross_bps"] == pytest.approx(-10.0, abs=1e-6)
    assert summary["net_bps"] < 0.0


def test_synthetic_null_does_not_show_an_effect() -> None:
    rng = random.Random(7)
    forwards = [rng.gauss(0.0, 0.002) for _ in range(400)]
    directions = [rng.choice([-1, 1]) for _ in range(400)]
    summary = ax.evaluate_directions(directions, forwards, hurdle_bps=30.0)
    assert abs(summary["gross_bps"]) < 20.0
    assert summary["gross_above_hurdle"] is False


def test_non_decisions_are_not_counted() -> None:
    summary = ax.evaluate_directions(
        [None, 1, 0, None], [0.001, 0.001, 0.001, 0.001], hurdle_bps=1.0
    )
    # two rows carried a decision; only one of them was a trade
    assert summary["n_evaluated"] == 2
    assert summary["n"] == 1
    assert summary["gross_bps"] == pytest.approx(10.0, abs=1e-6)


def test_an_empty_arm_is_not_a_negative_result() -> None:
    summary = ax.evaluate_directions([0, 0, 0], [0.001, 0.002, -0.001], hurdle_bps=30.0)
    assert summary["n"] == 0
    assert summary["power_class"] == "UNDERPOWERED"
    assert summary["contributions"] == []


def test_longer_horizon_effect_is_scaled_to_bps() -> None:
    summary = ax.evaluate_directions([1, 1], [0.01, 0.01], hurdle_bps=1.0)
    assert summary["gross_bps"] == pytest.approx(100.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# selection null and promotion
# --------------------------------------------------------------------------- #


def test_permutation_null_flags_a_direction_aligned_effect() -> None:
    rng = random.Random(11)
    forwards = [rng.gauss(0.001, 0.001) for _ in range(300)]
    aligned = [1 if value > 0 else -1 for value in forwards]
    null = ax.permutation_null({"ALIGNED": (aligned, forwards)}, draws=200, seed=1)
    assert null["p_null_best_ge_observed"] < 0.05


def test_anti_aligned_directions_cannot_look_significant() -> None:
    rng = random.Random(13)
    forwards = [rng.gauss(0.0, 0.002) for _ in range(300)]
    anti = [-1 if value > 0 else 1 for value in forwards]
    null = ax.permutation_null({"ANTI": (anti, forwards)}, draws=200, seed=2)
    assert null["p_null_best_ge_observed"] > 0.5


def _promotable_summary() -> dict[str, Any]:
    summary = ax.evaluate_directions([1] * 40, [0.01] * 40, hurdle_bps=1.0)
    summary["power_class"] = "POWERED"
    summary["concentration"] = {"classification": "ROBUST"}
    summary["stability"] = {"consistent": True}
    return summary


def test_promotion_requires_every_gate() -> None:
    summary = _promotable_summary()
    gate = ax.promotion_gate(
        summary=summary,
        bh_pass=True,
        holm_pass=True,
        baseline_delta_bps=1.0,
        p_null_best_ge_observed=0.01,
    )
    assert gate["passed"] is True
    assert gate["verdict"] == "OOS_CANDIDATE"
    assert gate["passed"] == all(gate["checks"].values())
    assert len(gate["checks"]) == 9

    # each single failure, holding everything else at pass, is a REJECT
    assert (
        ax.promotion_gate(
            summary=summary,
            bh_pass=False,
            holm_pass=True,
            baseline_delta_bps=1.0,
            p_null_best_ge_observed=0.01,
        )["passed"]
        is False
    )
    assert (
        ax.promotion_gate(
            summary=summary,
            bh_pass=True,
            holm_pass=True,
            baseline_delta_bps=-1.0,
            p_null_best_ge_observed=0.01,
        )["passed"]
        is False
    )
    assert (
        ax.promotion_gate(
            summary=summary,
            bh_pass=True,
            holm_pass=True,
            baseline_delta_bps=1.0,
            p_null_best_ge_observed=0.5,
        )["passed"]
        is False
    )


def test_a_below_hurdle_cell_is_rejected_not_promoted() -> None:
    summary = ax.evaluate_directions([1] * 40, [0.0001] * 40, hurdle_bps=30.0)
    summary["power_class"] = "POWERED"
    summary["concentration"] = {"classification": "ROBUST"}
    summary["stability"] = {"consistent": True}
    gate = ax.promotion_gate(
        summary=summary,
        bh_pass=True,
        holm_pass=True,
        baseline_delta_bps=1.0,
        p_null_best_ge_observed=0.01,
    )
    assert gate["passed"] is False
    assert gate["verdict"] == "REJECT"


def test_underpowered_is_inconclusive_not_negative() -> None:
    summary = ax.evaluate_directions([0, 0], [0.001, 0.002], hurdle_bps=30.0)
    gate = ax.promotion_gate(
        summary=summary,
        bh_pass=False,
        holm_pass=False,
        baseline_delta_bps=0.0,
        p_null_best_ge_observed=1.0,
    )
    assert gate["verdict"] == "INCONCLUSIVE"


def test_baselines_are_deterministic_and_bounded() -> None:
    row = dict(FEATURE_ROW)
    assert ax.BASELINES["B0_UNCONDITIONAL_LONG"](row) == 1
    assert ax.BASELINES["B3_MOMENTUM_CONTINUATION"](row) == 1
    row["ret_z"] = -2.0
    assert ax.BASELINES["B3_MOMENTUM_CONTINUATION"](row) == -1
