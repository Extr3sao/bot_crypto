"""ALPHA-001 — the falsification toolkit that the economic verdict leans on.

These tests pin the properties the campaign's decision depends on: the hurdle can
only rise with uncertainty, multiplicity corrections actually gate, the
best-of-N null cannot be passed by construction, the winner's curse shrinks a
selection, and the preregistered registry hash cannot drift silently.
"""

from __future__ import annotations

import math

import pytest

from trading_bot.research import alpha001 as a1


def test_hurdle_is_cost_plus_every_penalty() -> None:
    hurdle = a1.min_gross_hurdle_bps(n_effective=1000, sigma_trade_bps=400.0)
    statistical = 1.959963985 * 400.0 / math.sqrt(1000)
    assert hurdle["cost_bps"] == a1.COST_BPS_V3
    assert hurdle["execution_uncertainty_bps"] == pytest.approx(a1.COST_BPS_V3 * 0.25)
    assert hurdle["winners_curse_buffer_bps"] == pytest.approx(a1.WINNERS_CURSE_BUFFER_BPS)
    # every component is published rounded to 1e-6, so the identity holds at that tolerance
    assert hurdle["statistical_uncertainty_bps"] == pytest.approx(statistical, abs=1e-6)
    assert hurdle["min_gross_alpha_hurdle_bps"] == pytest.approx(
        a1.COST_BPS_V3 * 1.25 + a1.WINNERS_CURSE_BUFFER_BPS + statistical, abs=1e-5
    )


def test_hurdle_is_strictly_above_the_certified_cost() -> None:
    for n_effective in (10, 100, 1000, 5000):
        hurdle = a1.min_gross_hurdle_bps(n_effective=n_effective, sigma_trade_bps=400.0)
        assert hurdle["min_gross_alpha_hurdle_bps"] > a1.COST_BPS_V3 * 1.25


def test_hurdle_rejects_broken_inputs() -> None:
    with pytest.raises(ValueError):
        a1.min_gross_hurdle_bps(n_effective=0, sigma_trade_bps=400.0)
    with pytest.raises(ValueError):
        a1.min_gross_hurdle_bps(n_effective=100, sigma_trade_bps=0.0)


@pytest.mark.parametrize("probability", [0.05, 0.1, 0.5, 0.8, 0.95, 0.975, 0.999])
def test_probit_inverts_the_normal_cdf(probability: float) -> None:
    z = a1._probit(probability)
    assert a1._normal_cdf(z) == pytest.approx(probability, abs=1e-6)


def test_power_class_flags_an_unpowered_cell() -> None:
    weak = a1.power_class(n_effective=150, sigma_bps=500.0, hurdle_bps=55.0)
    strong = a1.power_class(n_effective=3000, sigma_bps=500.0, hurdle_bps=55.0)
    assert weak["class"] == "UNDERPOWERED"
    assert strong["class"] == "POWERED"
    assert float(weak["mde_bps"]) > float(weak["hurdle_bps"]) >= float(strong["mde_bps"]) - 1e-9


def test_effective_sample_size_never_exceeds_n_and_penalises_autocorrelation() -> None:
    independent = [(-1.0) ** index for index in range(50)]
    persistent = [1.0 if (index // 10) % 2 == 0 else -1.0 for index in range(50)]
    assert a1.effective_sample_size(independent) <= 50
    assert a1.effective_sample_size(persistent) < a1.effective_sample_size(independent)


def test_benjamini_hochberg_keeps_its_known_step_up_behaviour() -> None:
    # textbook step-up example: the largest rank with p_(k) <= k*q/m is k = 6
    pvalues = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    passes = a1.benjamini_hochberg(pvalues, q=0.10)
    assert passes[:6] == [True] * 6
    assert passes[6:] == [False] * 4


def test_holm_is_at_least_as_strict_as_bh() -> None:
    pvalues = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    bh = a1.benjamini_hochberg(pvalues, q=0.10)
    holm = a1.holm(pvalues, alpha=0.10)
    assert all(not (h and not b) for h, b in zip(holm, bh, strict=True))


def test_best_of_n_null_cannot_be_won_by_an_average_draw() -> None:
    null_best = [float(value) for value in range(1000)]
    assert a1.best_of_n_null(500.0, null_best)["p_null_best_ge_observed"] == pytest.approx(0.5)
    assert a1.best_of_n_null(2000.0, null_best)["significant_at_0_05"] is True
    assert a1.best_of_n_null(950.0, null_best)["p_null_best_ge_observed"] == pytest.approx(0.05)
    assert a1.best_of_n_null(950.0, null_best)["significant_at_0_05"] is False
    assert a1.best_of_n_null(980.0, null_best)["significant_at_0_05"] is True


def test_winners_curse_shrinks_the_selected_edge() -> None:
    shrunken = a1.winners_curse_shrinkage(observed_best=20.0, null_best_median=8.0)
    assert shrunken["selection_inflation_bps"] == pytest.approx(8.0)
    assert shrunken["shrunken_edge_bps"] == pytest.approx(12.0)


def test_concentration_flags_a_single_trade_edge() -> None:
    dominated = [100.0] + [1.0] * 20
    spread = [1.0] * 21
    assert a1.concentration(dominated)["classification"] == "FRAGILE"
    assert a1.concentration(spread)["classification"] == "ROBUST"


def test_stability_reports_every_window_without_filtering() -> None:
    report = a1.stability_by_window([1.0] * 10 + [-1.0] * 10, windows=4)
    assert len(report["windows"]) == 4
    assert report["n_positive"] == 2
    assert report["n_negative"] == 2
    assert report["consistent"] is False


def test_registry_is_frozen_and_sensitive() -> None:
    assert len(a1.HYPOTHESES) == 12
    assert len(a1.FAMILIES) == 6
    assert a1.hypothesis_registry_hash() == (
        "cf49586a349c292921faec53c8931a05e223dd3cd00a04e6009cb6ea1476068c"
    )
    weakened = list(a1.HYPOTHESES)[:-1]
    assert a1.hypothesis_registry_hash(hypotheses=weakened) != a1.hypothesis_registry_hash()


def test_pearson_and_spearman_agree_on_a_monotone_relation() -> None:
    x = [float(value) for value in range(20)]
    y = [value * 3.0 + 1.0 for value in x]
    assert a1.pearson(x, y) == pytest.approx(1.0)
    assert a1.spearman(x, y) == pytest.approx(1.0)
    assert a1.spearman(x, list(reversed(y))) == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
# the cost frontier — "is the cost the binding constraint, or the effect size?"
# --------------------------------------------------------------------------- #

#: The twelve gross means actually observed in ALPHA-001 discovery (bps).  They are
#: pinned here so the cost frontier cannot silently drift away from the evidence.
OBSERVED_GROSS_BPS = (
    -12.664029,
    4.120575,
    -34.466257,
    9.351029,
    -7.924788,
    14.770721,
    -54.848859,
    12.372074,
    18.575939,
    -18.575939,
    -1.400568,
    2.871321,
)

#: The frozen design terms the campaign admitted against.
FROZEN_STATISTICAL_BPS = 17.521692


def test_cost_frontier_decomposes_the_frozen_hurdle() -> None:
    # unrounded design terms, so the break-even lands exactly on the certified cost
    statistical = 1.959963985 * 400.0 / math.sqrt(2002)
    exact_hurdle = a1.COST_BPS_V3 * 1.25 + a1.WINNERS_CURSE_BUFFER_BPS + statistical
    frontier = a1.cost_frontier(gross_bps=exact_hurdle, statistical_bps=statistical)
    assert frontier["admission_gap_bps"] == pytest.approx(0.0, abs=1e-6)
    assert frontier["admission_break_even_cost_bps"] == pytest.approx(a1.COST_BPS_V3, abs=1e-5)
    assert frontier["path_to_viability"] == "ADMISSIBLE"
    assert frontier["required_rebate_bps"] == 0.0


def test_cost_frontier_turns_a_thin_edge_into_a_required_rebate() -> None:
    """The ALPHA-001 best cell: no cost level, not even zero, admits it."""
    frontier = a1.cost_frontier(gross_bps=18.575939, statistical_bps=FROZEN_STATISTICAL_BPS)
    expected = (18.575939 - a1.WINNERS_CURSE_BUFFER_BPS - FROZEN_STATISTICAL_BPS) / 1.25
    assert frontier["admission_break_even_cost_bps"] == pytest.approx(expected, abs=1e-6)
    assert frontier["admission_break_even_cost_bps"] < 0.0
    assert frontier["required_rebate_bps"] == pytest.approx(-expected, abs=1e-6)
    assert frontier["path_to_viability"] == "SAMPLE_TOO_SMALL"
    assert frontier["admissible_at_zero_cost"] is False


def test_cost_frontier_keeps_the_hurdle_above_gross_even_when_execution_is_free() -> None:
    free = a1.cost_frontier(
        gross_bps=18.575939, statistical_bps=FROZEN_STATISTICAL_BPS, cost_bps=0.0
    )
    assert free["hurdle_bps"] == pytest.approx(
        a1.WINNERS_CURSE_BUFFER_BPS + FROZEN_STATISTICAL_BPS, abs=1e-6
    )
    assert free["admission_gap_bps"] < 0.0
    assert free["net_positive_at_zero_cost"] is True
    assert free["path_to_viability"] == "SAMPLE_TOO_SMALL"


def test_cost_frontier_finds_the_cost_cut_a_bigger_edge_would_need() -> None:
    frontier = a1.cost_frontier(gross_bps=45.0, statistical_bps=FROZEN_STATISTICAL_BPS)
    assert frontier["path_to_viability"] == "COST_LIMITED"
    assert 0.0 < frontier["admission_break_even_cost_bps"] < a1.COST_BPS_V3
    reduction = frontier["cost_reduction_needed_fraction"]
    assert reduction is not None and 0.0 < reduction < 1.0
    assert reduction == pytest.approx(
        1.0 - frontier["admission_break_even_cost_bps"] / a1.COST_BPS_V3, abs=1e-6
    )


def test_cost_frontier_calls_out_an_edge_inside_the_selection_buffer() -> None:
    frontier = a1.cost_frontier(gross_bps=5.0, statistical_bps=FROZEN_STATISTICAL_BPS)
    assert frontier["path_to_viability"] == "BELOW_SELECTION_BUFFER"
    assert frontier["required_rebate_bps"] > a1.WINNERS_CURSE_BUFFER_BPS


def test_cost_frontier_net_break_even_drops_every_safety_margin() -> None:
    frontier = a1.cost_frontier(gross_bps=18.575939, statistical_bps=FROZEN_STATISTICAL_BPS)
    assert frontier["net_break_even_cost_bps"] == pytest.approx(18.575939)
    net_reduction = frontier["net_cost_reduction_needed_fraction"]
    assert net_reduction is not None
    assert net_reduction == pytest.approx(1.0 - 18.575939 / a1.COST_BPS_V3, abs=1e-6)
    # the margin-free reading is strictly more generous than the admitted one
    assert frontier["net_break_even_cost_bps"] > frontier["admission_break_even_cost_bps"]


def test_cost_frontier_is_monotone_in_gross_and_cost() -> None:
    weaker = a1.cost_frontier(gross_bps=10.0, statistical_bps=FROZEN_STATISTICAL_BPS)
    stronger = a1.cost_frontier(gross_bps=20.0, statistical_bps=FROZEN_STATISTICAL_BPS)
    assert stronger["admission_break_even_cost_bps"] > weaker["admission_break_even_cost_bps"]
    assert stronger["admission_gap_bps"] > weaker["admission_gap_bps"]
    cheaper = a1.cost_frontier(
        gross_bps=18.575939, statistical_bps=FROZEN_STATISTICAL_BPS, cost_bps=10.0
    )
    assert (
        cheaper["hurdle_bps"]
        < a1.cost_frontier(gross_bps=18.575939, statistical_bps=FROZEN_STATISTICAL_BPS)[
            "hurdle_bps"
        ]
    )
    # a cheaper venue moves the hurdle but never the required gross
    assert cheaper["admission_break_even_cost_bps"] == pytest.approx(
        a1.cost_frontier(gross_bps=18.575939, statistical_bps=FROZEN_STATISTICAL_BPS)[
            "admission_break_even_cost_bps"
        ],
        abs=1e-9,
    )


def test_cost_frontier_rejects_broken_inputs() -> None:
    with pytest.raises(ValueError):
        a1.cost_frontier(gross_bps=10.0, statistical_bps=-1.0)
    with pytest.raises(ValueError):
        a1.cost_frontier(gross_bps=10.0, statistical_bps=1.0, cost_bps=-0.5)
    with pytest.raises(ValueError):
        a1.cost_frontier(gross_bps=10.0, statistical_bps=1.0, execution_fraction=-0.1)
    # cost is allowed to be exactly zero; the fractions are then undefined, not zero
    free = a1.cost_frontier(gross_bps=10.0, statistical_bps=1.0, cost_bps=0.0)
    assert free["cost_reduction_needed_fraction"] is None
    assert free["net_cost_reduction_needed_fraction"] is None


@pytest.mark.parametrize("gross_bps", OBSERVED_GROSS_BPS)
@pytest.mark.parametrize("cost_bps", (23.790569, 10.0, 5.0, 0.0))
def test_no_observed_alpha001_cell_is_ever_admitted_at_any_cost(
    gross_bps: float, cost_bps: float
) -> None:
    """The whole point: cheaper execution cannot promote a preregistered loser."""
    frontier = a1.cost_frontier(
        gross_bps=gross_bps, statistical_bps=FROZEN_STATISTICAL_BPS, cost_bps=cost_bps
    )
    assert frontier["admission_gap_bps"] < 0.0
    assert frontier["path_to_viability"] != "ADMISSIBLE"
    # and at the certified cost, none of them is even net-positive
    if cost_bps == a1.COST_BPS_V3:
        assert frontier["net_cost_reduction_needed_fraction"] > 0.0
