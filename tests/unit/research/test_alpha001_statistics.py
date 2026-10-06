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
