"""ALPHA-003 — the experiment must detect a real lead-lag and refuse to invent one.

Three synthetic worlds are the falsification harness the preregistration asks for:

* **known lead-lag** — the target genuinely follows the leader one bar later, and the
  pipeline must find it, on the right pair and not on the other pairs;
* **no lead-lag** — independent series, and the pipeline must find nothing;
* **common factor only** — every asset reacts to the *same* shock at the *same* time, which
  is contemporaneous co-movement and not a lead, and the pipeline must not confuse the two.

The remainder pins the multiplicity machinery, the incremental-delta definition, and the
adversarial cases (one trade carrying the cell, one window carrying the cell) that must
produce a REJECT rather than a candidate.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha003 as a3
from trading_bot.research import alpha003_experiment as ax
from trading_bot.research import alpha003_features as af

PERIOD = 5 * 60 * 1000
T0 = 1_700_000_000_000

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")


# --------------------------------------------------------------------------- #
# synthetic worlds
# --------------------------------------------------------------------------- #


def bars_from_returns(returns: list[float], *, spread: float = 0.0004) -> list[list[float]]:
    out: list[list[float]] = []
    price = 100.0
    previous = 100.0
    for index, value in enumerate(returns):
        price = price * (1.0 + value)
        open_, close = previous, price
        out.append(
            [
                T0 + index * PERIOD,
                open_,
                max(open_, close) * (1.0 + spread),
                min(open_, close) * (1.0 - spread),
                close,
                1.0,
            ]
        )
        previous = price
    return out


def known_lead_lag(n: int = 12_000, seed: int = 101) -> dict[str, list[list[float]]]:
    """SOL follows BTC one bar later; ETH and XRP are contemporaneous only."""
    rng = random.Random(seed)
    btc = [rng.gauss(0.0, 0.002) for _ in range(n)]
    eth = [0.5 * btc[i] + rng.gauss(0.0, 0.0015) for i in range(n)]
    xrp = [0.5 * btc[i] + rng.gauss(0.0, 0.0015) for i in range(n)]
    sol = [
        0.4 * btc[i] + (0.7 * btc[i - 1] if i >= 1 else 0.0) + rng.gauss(0.0, 0.0010)
        for i in range(n)
    ]
    return {
        "BTCUSDT": bars_from_returns(btc),
        "ETHUSDT": bars_from_returns(eth),
        "SOLUSDT": bars_from_returns(sol),
        "XRPUSDT": bars_from_returns(xrp),
    }


def independent(n: int = 12_000, seed: int = 202) -> dict[str, list[list[float]]]:
    rng = random.Random(seed)
    return {
        symbol: bars_from_returns([rng.gauss(0.0, 0.002) for _ in range(n)])
        for symbol in SYMBOLS
    }


def common_factor_only(n: int = 12_000, seed: int = 303) -> dict[str, list[list[float]]]:
    """One shock hits every asset in the same bar: correlation without a lead."""
    rng = random.Random(seed)
    factor = [rng.gauss(0.0, 0.002) for _ in range(n)]
    return {
        symbol: bars_from_returns(
            [0.9 * factor[i] + rng.gauss(0.0, 0.0012) for i in range(n)]
        )
        for symbol in SYMBOLS
    }


def frame_for(bars: dict[str, list[list[float]]]) -> list[dict[str, Any]]:
    return af.build_frame(timeframe="5m", bars_by_symbol=bars, windows=(1, 2))


def cell_arms(
    frame: list[dict[str, Any]], cell_id: str, arm_id: str
) -> tuple[list[int | None], list[float | None]]:
    spec = ax.parse_cell(cell_id)
    target = str(spec["target"])
    directions = [
        ax.arm_direction(arm_id, af.cell_row(row, target=target, leader=spec["leader"], lag=spec["lag"]))
        for row in frame
    ]
    forwards = [af.forward_return_for(row, target) for row in frame]
    return directions, forwards


def cell_summary(
    frame: list[dict[str, Any]], cell_id: str, *, hurdle_bps: float
) -> tuple[dict[str, Any], dict[str, Any], float]:
    spec = ax.parse_cell(cell_id)
    hypothesis_id = str(spec["hypothesis_id"])
    full = ax.evaluate_directions(*cell_arms(frame, cell_id, hypothesis_id), hurdle_bps=hurdle_bps)
    baseline_arm = ax.INCREMENTAL_BASELINE[hypothesis_id]
    baseline = ax.evaluate_directions(
        *cell_arms(frame, cell_id, baseline_arm), hurdle_bps=hurdle_bps
    )
    incremental = float(full["gross_bps"]) - float(baseline["gross_bps"])
    return full, baseline, incremental


def run_family(
    frame: list[dict[str, Any]], *, hurdle_bps: float, draws: int = 200
) -> tuple[dict[str, tuple[dict[str, Any], dict[str, Any], float]], list[str], dict[str, Any]]:
    """The runner's arithmetic, in miniature: every cell, corrected for multiplicity.

    Returns the per-cell summaries, the cells that would be promoted, and the family-level
    best-of-N permutation null.
    """
    cells = ax.cell_ids()
    summaries = {cell: cell_summary(frame, cell, hurdle_bps=hurdle_bps) for cell in cells}
    pvalues = [float(summaries[cell][0]["p_raw"]) for cell in cells]
    bh = a1.benjamini_hochberg(pvalues, q=ax.BH_Q)
    holm = a1.holm(pvalues, alpha=ax.HOLM_ALPHA)
    arms = {
        cell: cell_arms(frame, cell, str(ax.parse_cell(cell)["hypothesis_id"])) for cell in cells
    }
    null = ax.permutation_null(arms, draws=draws, seed=11)
    p_null = float(null.get("p_null_best_ge_observed", 1.0))
    candidates: list[str] = []
    for index, cell in enumerate(cells):
        full, _baseline, incremental = summaries[cell]
        gate = ax.promotion_gate(
            summary=full,
            incremental_delta_bps=incremental,
            bh_pass=bh[index],
            holm_pass=holm[index],
            p_null_best_ge_observed=p_null,
        )
        if gate["verdict"] == "VALIDATION_CANDIDATE":
            candidates.append(cell)
    return summaries, candidates, null


# --------------------------------------------------------------------------- #
# splits and the cell enumeration
# --------------------------------------------------------------------------- #


def test_calendar_boundaries_are_half_open_and_locked() -> None:
    boundaries = ax.calendar_boundaries(1000, 2000)
    assert boundaries["discovery"] == (1000, 1600)
    assert boundaries["validation"] == (1600, 1800)
    assert boundaries["holdout"] == (1800, 2001)
    assert ax.in_window(1000, boundaries["discovery"])
    assert not ax.in_window(1600, boundaries["discovery"])
    assert ax.in_window(1600, boundaries["validation"])
    assert ax.in_window(1799, boundaries["validation"])
    assert not ax.in_window(1800, boundaries["validation"])
    assert ax.in_window(1800, boundaries["holdout"])
    assert ax.in_window(2000, boundaries["holdout"])
    assert not ax.in_window(2001, boundaries["holdout"])


def test_calendar_boundaries_reject_a_degenerate_span() -> None:
    with pytest.raises(ValueError):
        ax.calendar_boundaries(2000, 1000)


def test_the_cell_set_is_closed_and_exactly_the_declared_one() -> None:
    cells = ax.cell_ids()
    assert len(cells) == 36
    assert len(set(cells)) == 36
    h1 = [cell for cell in cells if cell.startswith("A3-H01")]
    assert len(h1) == len(a3.LEADER_TARGET_PAIRS) * len(a3.LEAD_LAGS) * len(a3.ENTRY_TIMEFRAMES)
    lags = {ax.parse_cell(cell)["lag"] for cell in h1}
    assert lags == set(a3.LEAD_LAGS)
    # every cell round-trips, and no cell may carry an undeclared lag or timeframe
    for cell in cells:
        spec = ax.parse_cell(cell)
        assert spec["timeframe"] in a3.ENTRY_TIMEFRAMES
        assert spec["lag"] in (None, *a3.LEAD_LAGS)
        assert spec["target"] in a3.UNIVERSE
    # lag fishing and pair fishing are excluded by construction
    with pytest.raises(ValueError):
        ax.parse_cell("A3-H01|BTCUSDT->SOLUSDT|L7|5m")
    with pytest.raises(ValueError):
        ax.parse_cell("A3-H01|BTCUSDT->DOGEUSDT|L1|5m")
    with pytest.raises(ValueError):
        ax.parse_cell("A3-H01|SOLUSDT->BTCUSDT|L1|5m")


# --------------------------------------------------------------------------- #
# the statistic
# --------------------------------------------------------------------------- #


def test_evaluate_directions_on_a_known_series() -> None:
    summary = ax.evaluate_directions([1] * 500 + [0] * 500, [0.001] * 1000, hurdle_bps=5.0)
    assert summary["n"] == 500
    assert summary["n_evaluated"] == 1000
    assert summary["gross_bps"] == pytest.approx(10.0)
    assert summary["net_bps"] == pytest.approx(10.0 - a1.COST_BPS_V3)
    assert summary["gross_above_hurdle"] is True


def test_evaluate_directions_counts_a_missing_source_as_no_decision() -> None:
    directions: list[int | None] = [1, 1, None, 0, 1]
    forwards: list[float | None] = [0.001, None, 0.001, 0.001, 0.001]
    summary = ax.evaluate_directions(directions, forwards, hurdle_bps=1.0)
    assert summary["n_evaluated"] == 3
    assert summary["n"] == 2


def test_evaluate_directions_is_underpowered_when_the_noise_swamps_the_hurdle() -> None:
    # three trades with a wide spread: no achievable effect detection at this hurdle
    summary = ax.evaluate_directions([1] * 3, [0.05, -0.05, 0.05], hurdle_bps=50.0)
    assert summary["power_class"] == "UNDERPOWERED"


def test_permutation_null_uses_only_usable_arms() -> None:
    arms = {
        "tiny": ([1] * 5, [0.001] * 5),
        "wide": ([1 if i % 2 else -1 for i in range(400)], [0.001] * 400),
    }
    null = ax.permutation_null(arms, draws=50, seed=1)
    assert null["arms"] == ["wide"]
    assert 0.0 <= null["p_null_best_ge_observed"] <= 1.0


# --------------------------------------------------------------------------- #
# §  synthetic worlds
# --------------------------------------------------------------------------- #


def test_a_known_lead_lag_is_detected_on_the_right_pair() -> None:
    """The world genuinely leads; the pipeline must find it, and find it first."""
    frame = frame_for(known_lead_lag())
    cell = "A3-H01|BTCUSDT->SOLUSDT|L1|5m"
    summaries, _candidates, null = run_family(frame, hurdle_bps=43.0)
    full, baseline, incremental = summaries[cell]
    assert full["n"] > 500
    assert full["gross_bps"] > 5.0
    assert incremental > 5.0
    assert float(full["gross_bps"]) > float(baseline["gross_bps"])
    assert full["power_class"] == "POWERED"
    # the direction carries real rank information about the forward return
    assert float(full["ic"]) > 0.5
    # it is the single best cell in the family, not one of many
    best = max(ax.cell_ids(), key=lambda name: float(summaries[name][0]["gross_bps"]))
    assert best == cell
    # and the selection null refuses to call it luck
    assert null["best_arm"] == cell
    assert float(null["p_null_best_ge_observed"]) < 0.05


def test_the_known_lead_lag_is_not_found_on_a_pair_that_has_none() -> None:
    """ETH is driven by BTC contemporaneously; there is no continuation to find."""
    frame = frame_for(known_lead_lag())
    full, _baseline, incremental = cell_summary(
        frame, "A3-H01|BTCUSDT->ETHUSDT|L1|5m", hurdle_bps=43.0
    )
    assert abs(float(full["ic"])) < 0.1
    assert full["gross_bps"] < 5.0
    assert incremental < 5.0


def test_independent_series_produce_no_supported_cell_and_no_candidate() -> None:
    """No relation exists, so nothing may survive correction or the promotion gate.

    Raw p-values below 0.05 do appear — that is what a 5% level means across 36 cells — and
    the point of the test is that the frozen multiplicity machinery discards every one of
    them.  Asserting on the raw count instead would be asserting the correction does not work.
    """
    frame = frame_for(independent())
    summaries, candidates, null = run_family(frame, hurdle_bps=43.0)
    cells = ax.cell_ids()
    pvalues = [float(summaries[cell][0]["p_raw"]) for cell in cells]
    assert not any(a1.benjamini_hochberg(pvalues, q=ax.BH_Q))
    assert not any(a1.holm(pvalues, alpha=ax.HOLM_ALPHA))
    assert candidates == []
    assert float(null["p_null_best_ge_observed"]) > 0.05
    assert not any(float(summaries[cell][0]["gross_above_hurdle"]) for cell in cells)
    # and the largest raw effect in the family is economically meaningless
    assert max(float(summaries[cell][0]["gross_bps"]) for cell in cells) < 5.0


def test_common_factor_only_is_not_mistaken_for_a_lead_lag() -> None:
    """Contemporaneous co-movement must not be promoted into a lead.

    The discriminator that matters is not how often the rule fires — a common shock does
    produce large one-sided moves, so the lag-gap condition fires about as often in both
    worlds — but whether the direction carries information about the *next* bar.  On the
    lead-lag world it does; on the purely contemporaneous world it does not.
    """
    cell = "A3-H01|BTCUSDT->SOLUSDT|L1|5m"
    factor_frame = frame_for(common_factor_only())
    lead_frame = frame_for(known_lead_lag())
    factor_summaries, factor_candidates, factor_null = run_family(factor_frame, hurdle_bps=43.0)
    lead_full, _baseline, _incremental = cell_summary(lead_frame, cell, hurdle_bps=43.0)
    factor_full, _fb, factor_incremental = factor_summaries[cell]
    assert factor_full["n"] > 100  # it does fire; firing is not the same as being right
    assert abs(float(factor_full["ic"])) < 0.1
    assert float(lead_full["ic"]) > 0.5
    assert float(factor_full["gross_bps"]) < 5.0
    assert factor_incremental < 5.0
    assert factor_candidates == []
    assert float(factor_null["p_null_best_ge_observed"]) > 0.05


# --------------------------------------------------------------------------- #
# §  adversarial cells
# --------------------------------------------------------------------------- #


#: A deterministic 2000-trade arm: +50 bps mean, 20 bps dispersion, no drift in the sign of
#: its contributions.  Used as the "a real cell" floor for the gate tests.
STEADY_DIRECTIONS: list[int | None] = [1] * 2000
STEADY_FORWARDS: list[float | None] = [0.003, 0.007] * 1000


def test_multiple_testing_gates_a_raw_significant_but_corrected_insignificant_cell() -> None:
    full = ax.evaluate_directions(STEADY_DIRECTIONS, STEADY_FORWARDS, hurdle_bps=5.0)
    assert float(full["gross_bps"]) > 0.0
    assert full["power_class"] == "POWERED"
    gate = ax.promotion_gate(
        summary=full,
        incremental_delta_bps=5.0,
        bh_pass=False,
        holm_pass=False,
        p_null_best_ge_observed=0.01,
    )
    assert gate["verdict"] == "REJECT"
    assert gate["checks"]["bh_fdr_pass"] is False


def test_a_negative_incremental_delta_is_rejected_even_when_raw_positive() -> None:
    full = ax.evaluate_directions(STEADY_DIRECTIONS, STEADY_FORWARDS, hurdle_bps=5.0)
    gate = ax.promotion_gate(
        summary=full,
        incremental_delta_bps=-0.5,
        bh_pass=True,
        holm_pass=True,
        p_null_best_ge_observed=0.01,
    )
    assert gate["verdict"] == "REJECT"
    assert gate["checks"]["incremental_positive"] is False


def test_one_trade_carrying_the_cell_is_fragile_and_rejected() -> None:
    forwards = [0.01] + [0.00001] * 399
    full = ax.evaluate_directions([1] * 400, forwards, hurdle_bps=5.0)
    assert full["concentration"]["classification"] == "FRAGILE"
    gate = ax.promotion_gate(
        summary=full,
        incremental_delta_bps=1.0,
        bh_pass=True,
        holm_pass=True,
        p_null_best_ge_observed=0.0,
    )
    assert gate["verdict"] == "REJECT"
    assert gate["checks"]["concentration_robust"] is False


def test_a_cell_whose_edge_lives_in_one_window_cannot_be_promoted() -> None:
    """A cell whose contributions flip sign between sub-windows may not advance.

    The verdict word is not asserted: a blocky contribution series also has little effective
    sample, so the honest word can be INCONCLUSIVE rather than REJECT.  What is asserted is
    the substantive claim — the frozen gate refuses to promote it.
    """
    forwards = [0.004] * 100 + [-0.003] * 300
    full = ax.evaluate_directions([1] * 400, forwards, hurdle_bps=10.0)
    assert full["stability"]["consistent"] is False
    gate = ax.promotion_gate(
        summary=full,
        incremental_delta_bps=1.0,
        bh_pass=True,
        holm_pass=True,
        p_null_best_ge_observed=0.0,
    )
    assert gate["checks"]["stability_consistent"] is False
    assert gate["passed"] is False
    assert gate["verdict"] != "VALIDATION_CANDIDATE"


def test_an_underpowered_cell_is_inconclusive_not_negative() -> None:
    full = ax.evaluate_directions(
        [1] * 6, [0.05, -0.05, 0.06, -0.04, 0.05, -0.05], hurdle_bps=60.0
    )
    assert full["power_class"] == "UNDERPOWERED"
    gate = ax.promotion_gate(
        summary=full,
        incremental_delta_bps=1.0,
        bh_pass=True,
        holm_pass=True,
        p_null_best_ge_observed=0.0,
    )
    assert gate["verdict"] == "INCONCLUSIVE"


def test_a_cell_passing_every_gate_is_only_a_validation_candidate() -> None:
    full = ax.evaluate_directions(STEADY_DIRECTIONS, STEADY_FORWARDS, hurdle_bps=5.0)
    assert full["gross_above_hurdle"] is True
    assert full["power_class"] == "POWERED"
    assert full["concentration"]["classification"] == "ROBUST"
    assert full["stability"]["consistent"] is True
    gate = ax.promotion_gate(
        summary=full,
        incremental_delta_bps=10.0,
        bh_pass=True,
        holm_pass=True,
        p_null_best_ge_observed=0.001,
    )
    assert gate["passed"] is True
    # and even then the word is VALIDATION_CANDIDATE, never ALPHA
    assert gate["verdict"] == "VALIDATION_CANDIDATE"


def test_an_undeclared_arm_cannot_be_evaluated() -> None:
    with pytest.raises(KeyError):
        ax.arm_direction("A3-H04", {"leader_ret_z": 2.0, "target_ret_z": 0.5})
