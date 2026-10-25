"""ALPHA-003 — the preregistration must be frozen, complete and mechanically honest.

The campaign's whole claim to being falsifiable rests on four things these tests pin down:
the registry cannot drift, every declared hypothesis has exactly one executable signal,
each signal actually implements the rule written in the registry rather than something
adjacent to it, and the campaign uses no machine learning.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha003 as a3
from trading_bot.research import alpha003_experiment as ax
from trading_bot.research import alpha003_features as af

#: The preregistration hash: changing any rule, threshold, timeframe, pair, lag, feature or
#: gate term breaks this test on purpose, because a registry that can change quietly after
#: results are seen is not a preregistration.
FROZEN_PREREGISTRATION_HASH = "db43ad5283cad875ac014a622dc7acae423d0e44c5f64c473a039e3f9ed1c4c8"

MODULES = ("alpha003.py", "alpha003_features.py", "alpha003_experiment.py")

#: A derived feature row that satisfies nothing.  Signals are asserted against this baseline
#: and then against one targeted mutation at a time, so a rule that fires by default cannot
#: pass.
NEUTRAL: dict[str, float | None] = {
    "leader_ret_z": 0.0,
    "target_ret_z": 0.0,
    "target_mom_z": 0.0,
    "market_ret_z": 0.0,
    "relative_z": 0.0,
}


def features(**overrides: float) -> dict[str, float | None]:
    return {**NEUTRAL, **overrides}


# --------------------------------------------------------------------------- #
# the registry is frozen
# --------------------------------------------------------------------------- #


def test_registry_is_frozen() -> None:
    assert len(a3.HYPOTHESES) == 3
    assert [item["hypothesis_id"] for item in a3.HYPOTHESES] == ["A3-H01", "A3-H02", "A3-H03"]
    assert a3.preregistration_hash() == FROZEN_PREREGISTRATION_HASH


def test_registry_hash_is_stable_and_sensitive() -> None:
    baseline = a3.preregistration_hash()
    assert a3.preregistration_hash(a3.PREREGISTRATION) == baseline
    weakened = dict(a3.PREREGISTRATION)
    weakened["thresholds"] = {**a3.THRESHOLDS, "leader_ret_z": 1.5}
    assert a3.preregistration_hash(weakened) != baseline
    dropped = dict(a3.PREREGISTRATION)
    dropped["hypotheses"] = tuple(a3.HYPOTHESES[:-1])
    assert a3.preregistration_hash(dropped) != baseline
    widened = dict(a3.PREREGISTRATION)
    widened["universe"] = [*a3.UNIVERSE, "DOGEUSDT"]
    assert a3.preregistration_hash(widened) != baseline
    lagged = dict(a3.PREREGISTRATION)
    lagged["lead_lags"] = [*a3.LEAD_LAGS, 4]
    assert a3.preregistration_hash(lagged) != baseline


def test_cost_model_is_inherited_and_not_retuned() -> None:
    assert a3.COST_BPS_V3 == a1.COST_BPS_V3
    assert a3.PREREGISTRATION["cost_model"]["cost_bps"] == a1.COST_BPS_V3
    assert a3.PREREGISTRATION["cost_model"]["retuned"] is False


def test_no_machine_learning_in_the_campaign() -> None:
    """The campaign must not import anything but the standard library and trading_bot.

    Asserted on the import graph rather than on the words: the registry names the banned
    libraries on purpose, so a text search would be self-defeating.  Any third-party
    module — an ML library most of all — would fail this test the moment it is imported.
    """
    assert a3.PREREGISTRATION["machine_learning"]["used"] is False
    allowed = {
        "__future__",
        "bisect",
        "collections",
        "hashlib",
        "json",
        "math",
        "random",
        "statistics",
        "trading_bot",
        "typing",
    }
    root = Path(a3.__file__).resolve().parent
    for name in MODULES:
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert roots <= allowed, f"{name} imports {sorted(roots - allowed)}"


# --------------------------------------------------------------------------- #
# the registry, the signals and the baselines correspond exactly
# --------------------------------------------------------------------------- #


def test_every_traded_hypothesis_has_exactly_one_signal() -> None:
    declared = {
        item["hypothesis_id"] for item in a3.HYPOTHESES if bool(item["traded"])
    }
    assert set(a3.SIGNALS) == declared


def test_non_traded_arms_are_declared_and_are_not_signals() -> None:
    declared = {
        item["arm_id"] for item in a3.PREREGISTRATION["non_traded_arms"]
    }
    assert set(a3.NON_TRADED_ARMS) == declared
    assert not declared & set(a3.SIGNALS)


def test_required_features_cover_every_declared_arm() -> None:
    arms = (
        set(a3.SIGNALS)
        | set(a3.NON_TRADED_ARMS)
        | set(ax.BASELINES)
    )
    assert set(af.REQUIRED_FEATURES) == arms
    for arm, required in af.REQUIRED_FEATURES.items():
        for name in required:
            assert name in af.FEATURE_NAMES, f"{arm} requires undeclared feature {name}"


def test_incremental_baselines_match_the_registry() -> None:
    declared = {item["hypothesis_id"]: item["baseline_arm"] for item in a3.HYPOTHESES}
    assert declared == ax.INCREMENTAL_BASELINE
    for arm in ax.INCREMENTAL_BASELINE.values():
        assert arm in ax.BASELINES
    assert set(ax.ABLATIONS) == set(a3.SIGNALS)


def test_ablation_sets_contain_the_declared_baseline_and_full() -> None:
    for hypothesis_id, arms in ax.ABLATIONS.items():
        assert arms[0] == "FULL"
        assert ax.INCREMENTAL_BASELINE[hypothesis_id] in arms


def test_every_ablation_arm_is_directional() -> None:
    """Regression: a boolean contrast subset cannot be evaluated as a direction.

    ``A3-NT-01`` is declared as a *subset* (a predicate), not a signal.  The ablation table
    must therefore name its directional twin ``A3-B4_LEADER_ONLY`` instead, and every arm in
    every ablation set must be resolvable as a direction.
    """
    assert "A3-NT-01" not in ax.BASELINES
    assert not (set(a3.NON_TRADED_ARMS) & set(ax.BASELINES))
    for hypothesis_id, arms in ax.ABLATIONS.items():
        for label in arms:
            arm_id = hypothesis_id if label == "FULL" else label
            resolved = ax.preregistered_direction(arm_id, features(leader_ret_z=2.0, target_ret_z=0.5))
            assert resolved is not None, f"{arm_id} is not evaluable as a direction"


def test_leader_only_baseline_is_the_directional_twin_of_the_contrast() -> None:
    assert ax.arm_direction("A3-B4_LEADER_ONLY", features(leader_ret_z=2.0, target_ret_z=9.0)) == 1
    assert ax.arm_direction("A3-B4_LEADER_ONLY", features(leader_ret_z=-2.0, target_ret_z=-9.0)) == -1
    assert ax.arm_direction("A3-B4_LEADER_ONLY", features(leader_ret_z=0.5)) == 0
    # the boolean contrast and the directional twin agree on when to act
    for row in (features(leader_ret_z=2.0), features(leader_ret_z=0.5), features(leader_ret_z=-1.5)):
        acts = ax.arm_direction("A3-B4_LEADER_ONLY", row) != 0
        assert acts is bool(a3.h1_leader_only_contrast(row))


def test_registry_declares_one_mechanism_per_family() -> None:
    families = [item["family_id"] for item in a3.HYPOTHESES]
    assert len(set(families)) == len(families) == 3


# --------------------------------------------------------------------------- #
# the signals implement the written rules
# --------------------------------------------------------------------------- #


def test_signals_are_silent_on_a_neutral_row() -> None:
    for arm in a3.SIGNALS:
        assert ax.preregistered_direction(arm, features()) == 0


def test_h1_lead_lag_continuation() -> None:
    # leader up, target up but materially less -> long
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=2.0, target_ret_z=0.5)) == 1
    # the exact lag-gap boundary fires (>= is inclusive)
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=1.5, target_ret_z=1.0)) == 1
    # the exact leader threshold does not (strict >)
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=1.0, target_ret_z=0.0)) == 0
    # a lag gap below the threshold does not fire
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=2.0, target_ret_z=1.6)) == 0
    # target moved against the leader -> not a lagging target
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=2.0, target_ret_z=-1.0)) == 0
    # mirror: leader down, target down less -> short
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=-2.0, target_ret_z=-0.5)) == -1
    assert a3.h1_lead_lag_continuation(features(leader_ret_z=-2.0, target_ret_z=1.0)) == 0


def test_h2_relative_strength_persistence() -> None:
    assert a3.h2_relative_strength_persistence(features(relative_z=1.5)) == 1
    assert a3.h2_relative_strength_persistence(features(relative_z=-1.5)) == -1
    assert a3.h2_relative_strength_persistence(features(relative_z=1.0)) == 0


def test_h3_dispersion_convergence() -> None:
    # market up, target diverged down -> long the laggard
    assert a3.h3_dispersion_convergence(features(market_ret_z=2.0, relative_z=-2.0)) == 1
    # market down, target diverged up -> short the outperformer
    assert a3.h3_dispersion_convergence(features(market_ret_z=-2.0, relative_z=2.0)) == -1
    # no divergence against the market -> no trade
    assert a3.h3_dispersion_convergence(features(market_ret_z=2.0, relative_z=2.0)) == 0
    # the market must itself move
    assert a3.h3_dispersion_convergence(features(market_ret_z=0.5, relative_z=-2.0)) == 0
    # the divergence must clear the stricter convergence threshold
    assert a3.h3_dispersion_convergence(features(market_ret_z=2.0, relative_z=-1.0)) == 0


def test_nontraded_contrast_arms() -> None:
    assert a3.h1_leader_only_contrast(features(leader_ret_z=2.0, target_ret_z=5.0)) is True
    assert a3.h1_leader_only_contrast(features(leader_ret_z=0.5)) is False
    assert a3.h1_target_extended_contrast(features(leader_ret_z=2.0, target_ret_z=2.5)) is True
    assert a3.h1_target_extended_contrast(features(leader_ret_z=2.0, target_ret_z=0.5)) is False


def test_baselines() -> None:
    assert ax.arm_direction("A3-B0_UNCONDITIONAL_LONG", features()) == 1
    assert ax.arm_direction("A3-B1_OWN_MOMENTUM_SAME_LAG", features(target_ret_z=1.5)) == 1
    assert ax.arm_direction("A3-B1_OWN_MOMENTUM_SAME_LAG", features(target_ret_z=0.5)) == 0
    assert ax.arm_direction("A3-B1_OWN_MOMENTUM_R", features(target_mom_z=-2.0)) == -1
    assert ax.arm_direction("A3-B3_MARKET_DIRECTION", features(market_ret_z=0.2)) == 0


def test_a_missing_required_feature_is_not_a_decision() -> None:
    missing = features(leader_ret_z=2.0, target_ret_z=0.5)
    missing["target_ret_z"] = None
    assert ax.preregistered_direction("A3-H01", missing) is None
    assert ax.arm_direction("A3-H01", missing) is None


def test_full_ablation_reproduces_the_frozen_signal() -> None:
    rows = [
        features(leader_ret_z=2.0, target_ret_z=0.5),
        features(leader_ret_z=-2.0, target_ret_z=-0.1),
        features(leader_ret_z=0.2),
        features(market_ret_z=2.0, relative_z=-2.0, target_mom_z=-1.0),
        features(relative_z=1.4),
        features(),
    ]
    for hypothesis_id in a3.SIGNALS:
        for row in rows:
            assert ax.ablation_direction(hypothesis_id, "FULL", row) == ax.preregistered_direction(
                hypothesis_id, row
            )


def test_unknown_arm_is_rejected() -> None:
    with pytest.raises(KeyError):
        ax.arm_direction("A3-H99", features())
