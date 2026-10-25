"""ALPHA-002 — the preregistration must be frozen, complete and mechanically honest.

The campaign's whole claim to being falsifiable rests on three things these tests
pin down: the registry cannot drift, every declared hypothesis has exactly one
executable signal, and each signal actually implements the rule written in the
registry rather than something adjacent to it.
"""

from __future__ import annotations

import pytest

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha002 as a2

#: The preregistration hash: changing any rule, threshold, timeframe, universe,
#: feature list or gate term breaks this test on purpose, because a registry that can
#: change quietly after results are seen is not a preregistration.
FROZEN_PREREGISTRATION_HASH = "8b09f608256a31722b366f10e52513e9a347405d078138a9c350df1ad2439f6b"

#: A feature row that satisfies nothing.  Signals are asserted against this baseline
#: and then against one targeted mutation at a time, so a rule that fires by default
#: cannot pass.
NEUTRAL: dict[str, float] = {
    "ret_z": 0.0,
    "atr_pct": 0.01,
    "oi_chg": 0.0,
    "oi_accel": 0.0,
    "taker_imbalance": 0.0,
    "funding": 0.0,
    "ls_global_pctile": 0.5,
    "ls_top_position_pctile": 0.5,
    "momentum_delta": 0.0,
    "vol_regime": 0.0,
}


def row(**overrides: float) -> dict[str, float]:
    return {**NEUTRAL, **overrides}


def test_registry_is_frozen() -> None:
    assert len(a2.HYPOTHESES) == 3
    assert [item["hypothesis_id"] for item in a2.HYPOTHESES] == ["A2-H01", "A2-H02", "A2-H03"]
    assert a2.preregistration_hash() == FROZEN_PREREGISTRATION_HASH


def test_registry_hash_is_stable_and_sensitive() -> None:
    baseline = a2.preregistration_hash()
    assert a2.preregistration_hash(a2.PREREGISTRATION) == baseline
    weakened = dict(a2.PREREGISTRATION)
    weakened["thresholds"] = {**a2.THRESHOLDS, "breakout_ret_z": 1.5}
    assert a2.preregistration_hash(weakened) != baseline
    dropped = dict(a2.PREREGISTRATION)
    dropped["hypotheses"] = tuple(a2.HYPOTHESES[:-1])
    assert a2.preregistration_hash(dropped) != baseline


def test_cost_model_is_inherited_and_not_retuned() -> None:
    assert a2.COST_BPS_V3 == a1.COST_BPS_V3
    assert a2.PREREGISTRATION["cost_model"]["cost_bps"] == a1.COST_BPS_V3
    assert a2.PREREGISTRATION["cost_model"]["retuned"] is False


def test_statistical_gate_is_alpha001s_gate_unchanged() -> None:
    gate = a2.PREREGISTRATION["statistical_gate"]
    assert gate["inherited_from"] == "ALPHA-001"
    assert gate["inherited_from"] != "ALPHA-002"
    assert "BH" in gate["multiplicity"].replace("Benjamini-Hochberg", "BH")
    assert gate["underpowered_is_not_negative"] is True


def test_thresholds_are_the_declared_ones() -> None:
    assert a2.THRESHOLDS["breakout_ret_z"] == 1.0
    assert a2.THRESHOLDS["taker_imbalance_confirm"] == 0.05
    assert a2.THRESHOLDS["crowding_pctile"] == 0.90
    assert a2.THRESHOLDS["funding_extreme_abs"] > a2.THRESHOLDS["funding_elevated"]
    assert a2.PREREGISTRATION["thresholds"] == a2.THRESHOLDS


def test_universe_and_timeframes_match_the_capture_job() -> None:
    from trading_bot.research.alpha002_capture import UNIVERSE

    assert tuple(a2.UNIVERSE) == UNIVERSE
    assert a2.ENTRY_TIMEFRAMES[0] == "5m"
    assert a2.REGIME_TIMEFRAME == "1h"
    assert a2.FORWARD_BARS == 1


def test_every_declared_hypothesis_has_exactly_one_signal() -> None:
    declared = {item["hypothesis_id"] for item in a2.HYPOTHESES}
    assert declared == set(a2.SIGNALS)
    assert len(a2.SIGNALS) == len(a2.HYPOTHESES)


def test_every_hypothesis_is_marked_traded_and_has_a_rule() -> None:
    for item in a2.HYPOTHESES:
        assert item["traded"] is True
        assert item["direction_rule"]
        assert item["mechanism"]
        assert item["invalidation"]
        assert item["expected_regime"]


def test_non_traded_arms_are_declared_and_never_traded() -> None:
    declared = {item["arm_id"] for item in a2.PREREGISTRATION["non_traded_arms"]}
    assert declared == set(a2.NON_TRADED_ARMS)
    # an arm is a comparator, never a hypothesis that could be promoted
    hypothesis_ids = {item["hypothesis_id"] for item in a2.HYPOTHESES}
    assert not (declared & hypothesis_ids)
    for item in a2.PREREGISTRATION["non_traded_arms"]:
        assert item["hypothesis_id"] in hypothesis_ids
        assert "never" in item["role"]


def test_all_declared_features_are_real_keys() -> None:
    declared = {item["name"] for item in a2.FEATURES}
    assert declared == set(NEUTRAL)
    assert len(declared) == len(a2.FEATURES)


def test_no_signal_fires_on_a_neutral_row() -> None:
    for hypothesis_id, signal in a2.SIGNALS.items():
        assert signal(NEUTRAL) == 0, hypothesis_id
    for arm_id, arm in a2.NON_TRADED_ARMS.items():
        assert arm(NEUTRAL) is False, arm_id


def test_h1_requires_all_four_confirmations() -> None:
    assert a2.h1_breakout_confirmation(row(ret_z=1.5, oi_chg=0.01, taker_imbalance=0.10)) == 1
    # any single condition failing must kill the signal
    assert a2.h1_breakout_confirmation(row(ret_z=0.9, oi_chg=0.01, taker_imbalance=0.10)) == 0
    assert a2.h1_breakout_confirmation(row(ret_z=1.5, oi_chg=-0.01, taker_imbalance=0.10)) == 0
    assert a2.h1_breakout_confirmation(row(ret_z=1.5, oi_chg=0.01, taker_imbalance=0.04)) == 0
    assert (
        a2.h1_breakout_confirmation(
            row(ret_z=1.5, oi_chg=0.01, taker_imbalance=0.10, funding=0.001)
        )
        == 0
    )
    # extreme negative funding is equally disqualifying: the carry must be neutral
    assert (
        a2.h1_breakout_confirmation(
            row(ret_z=1.5, oi_chg=0.01, taker_imbalance=0.10, funding=-0.001)
        )
        == 0
    )
    assert a2.h1_breakout_confirmation(
        row(ret_z=1.5, oi_chg=0.01, taker_imbalance=0.10, funding=0.0002)
    ) == 1


def test_h1_short_covering_arm_is_the_oi_collapse_case() -> None:
    assert a2.h1_short_covering_arm(row(ret_z=1.5, oi_chg=-0.02)) is True
    assert a2.h1_short_covering_arm(row(ret_z=1.5, oi_chg=0.02)) is False
    assert a2.h1_short_covering_arm(row(ret_z=0.5, oi_chg=-0.02)) is False


def test_h2_requires_crowding_carry_and_deterioration_and_is_short_only() -> None:
    assert (
        a2.h2_crowded_reversal(
            row(ls_global_pctile=0.95, funding=0.0005, momentum_delta=-0.01)
        )
        == -1
    )
    # crowding by size counts too
    assert (
        a2.h2_crowded_reversal(
            row(ls_top_position_pctile=0.97, funding=0.0005, momentum_delta=-0.01)
        )
        == -1
    )
    assert (
        a2.h2_crowded_reversal(row(ls_global_pctile=0.85, funding=0.0005, momentum_delta=-0.01))
        == 0
    )
    assert (
        a2.h2_crowded_reversal(row(ls_global_pctile=0.95, funding=0.0, momentum_delta=-0.01))
        == 0
    )
    assert (
        a2.h2_crowded_reversal(row(ls_global_pctile=0.95, funding=0.0005, momentum_delta=0.01))
        == 0
    )
    # never long, whatever the input
    assert a2.h2_crowded_reversal(row(ls_global_pctile=0.99, funding=0.001, momentum_delta=-1.0)) == -1


def test_h3_takes_the_sign_of_the_move_and_needs_expansion_and_aligned_flow() -> None:
    assert a2.h3_flow_continuation(row(ret_z=1.5, oi_chg=0.01, taker_imbalance=0.10)) == 1
    assert a2.h3_flow_continuation(row(ret_z=-1.5, oi_chg=0.01, taker_imbalance=-0.10)) == -1
    # a collapsing book is a closing position, not new risk
    assert a2.h3_flow_continuation(row(ret_z=1.5, oi_chg=-0.01, taker_imbalance=0.10)) == 0
    # flow must align with the move
    assert a2.h3_flow_continuation(row(ret_z=1.5, oi_chg=0.01, taker_imbalance=-0.10)) == 0
    assert a2.h3_flow_continuation(row(ret_z=-1.5, oi_chg=0.01, taker_imbalance=0.10)) == 0
    # a weak move is not a move
    assert a2.h3_flow_continuation(row(ret_z=0.5, oi_chg=0.01, taker_imbalance=0.10)) == 0


def test_h3_exhaustion_arm_is_the_complement_of_the_continuation_subset() -> None:
    strong_collapse = row(ret_z=1.6, oi_chg=-0.02, taker_imbalance=0.20)
    assert a2.h3_exhaustion_arm(strong_collapse) is True
    assert a2.h3_flow_continuation(strong_collapse) == 0
    strong_expansion = row(ret_z=1.6, oi_chg=0.02, taker_imbalance=0.20)
    assert a2.h3_exhaustion_arm(strong_expansion) is False
    assert a2.h3_flow_continuation(strong_expansion) == 1


@pytest.mark.parametrize("hypothesis_id", ["A2-H01", "A2-H02", "A2-H03"])
def test_signals_only_ever_return_a_unit_direction(hypothesis_id: str) -> None:
    signal = a2.SIGNALS[hypothesis_id]
    for ret_z in (-3.0, -1.0, 0.0, 1.0, 3.0):
        for oi_chg in (-0.05, 0.0, 0.05):
            for imbalance in (-0.3, 0.0, 0.3):
                decision = signal(
                    row(
                        ret_z=ret_z,
                        oi_chg=oi_chg,
                        taker_imbalance=imbalance,
                        funding=0.0005,
                        ls_global_pctile=0.95,
                        ls_top_position_pctile=0.95,
                        momentum_delta=-0.02,
                    )
                )
                assert decision in (-1, 0, 1)
