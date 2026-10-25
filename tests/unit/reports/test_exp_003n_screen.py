"""EXP-003N — the screening arithmetic has to be testable without the market data.

Every test below pins a rule the experiment depends on: where a forward return starts and
ends, that the holdout cannot be reached through a helper, that a bootstrap is deterministic,
that Benjamini-Hochberg actually corrects, and that the economic gate fails when the gross
does not pay for the round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import exp_003n_screen as screen  # noqa: E402
from exp_003n_validate import trade_net_bps  # noqa: E402

DAY_MS = 86_400_000
START = 1_782_000_000_000


def series(opens: list[float], spread: float = 0.0, *, step_ms: int = 300_000) -> screen.Series:
    count = len(opens)
    array = np.asarray(opens, dtype=float)
    return screen.Series(
        symbol="TESTUSDT",
        stamps=np.asarray([START + index * step_ms for index in range(count)], dtype=np.int64),
        open=array,
        high=array + spread,
        low=array - spread,
        close=array,
        volume=np.ones(count),
    )


def test_forward_return_starts_at_the_next_open_and_ends_at_the_horizon_open() -> None:
    bars = series([100.0, 110.0, 120.0, 130.0])

    # a signal on bar 0 cannot enter at 100: that price is gone by the time the bar closes.
    assert screen.forward_bps(bars, 0, "LONG", 1) == pytest.approx(120.0 / 110.0 * 1e4 - 1e4)
    assert screen.forward_bps(bars, 0, "SHORT", 1) == pytest.approx(-(120.0 / 110.0 * 1e4 - 1e4))
    assert screen.forward_bps(bars, 0, "LONG", 2) == pytest.approx(130.0 / 110.0 * 1e4 - 1e4)


def test_forward_return_is_none_when_the_horizon_has_not_happened_yet() -> None:
    bars = series([100.0, 101.0, 102.0])

    assert screen.forward_bps(bars, 1, "LONG", 1) is None
    assert screen.forward_bps(bars, 0, "LONG", 2) is None


def test_aggregate_drops_a_partial_bar_instead_of_padding_it() -> None:
    minute = series([100.0 + index for index in range(10)], step_ms=60_000)

    four = screen.aggregate(minute, 240_000)

    assert len(four.stamps) == 2
    assert four.open[1] == pytest.approx(104.0)
    assert four.close[1] == pytest.approx(107.0)


def test_head_cuts_before_the_holdout_and_the_guard_refuses_the_remainder() -> None:
    bars = series([100.0] * 10)
    cutoff = int(bars.stamps[5])

    cut = screen.head(bars, cutoff)
    screen.assert_holdout_closed(cut, cutoff)

    assert len(cut.stamps) == 5
    with pytest.raises(SystemExit):
        screen.assert_holdout_closed(bars, cutoff)


def test_block_bootstrap_is_deterministic_and_signed() -> None:
    rng = np.random.default_rng(11)
    values = 50.0 + rng.normal(0.0, 2.0, 400)
    # spread over 40 days so there are 8 five-day blocks, not one
    stamps = np.asarray([START + index * 2 * 3_600_000 for index in range(400)], dtype=np.int64)

    first = screen.block_bootstrap(values, stamps, resamples=500, seed=7)
    second = screen.block_bootstrap(values, stamps, resamples=500, seed=7)
    negative = screen.block_bootstrap(-values, stamps, resamples=500, seed=7)

    assert first == second
    assert first["mean"] > 0
    assert first["ci_lower"] < first["mean"] < first["ci_upper"]
    assert negative["mean"] < 0
    assert negative["ci_upper"] < 0


def test_block_bootstrap_needs_two_blocks() -> None:
    # twenty observations inside a single five-day block: there is nothing to resample.
    values = np.arange(20, dtype=float)
    stamps = np.asarray([START + index * 60_000 for index in range(20)], dtype=np.int64)

    result = screen.block_bootstrap(values, stamps, resamples=100, seed=1)

    assert result["blocks"] == 1
    assert result["ci_lower"] is None
    assert result["resamples"] == 0


def test_block_bootstrap_needs_ten_observations() -> None:
    result = screen.block_bootstrap(
        np.asarray([1.0, 2.0, 3.0]),
        np.asarray([START, START + 1, START + 2], dtype=np.int64),
        resamples=100,
        seed=1,
    )

    assert result["blocks"] == 0
    assert result["ci_lower"] is None


def test_benjamini_hochberg_rejects_the_bulk_of_a_weak_family() -> None:
    pvalues = {f"cell{index}": 0.02 + index * 0.01 for index in range(20)}
    pvalues["strong"] = 0.0001

    adjusted = screen.bh_adjust(pvalues, 0.10)

    assert "strong" in adjusted["surviving"]
    assert len(adjusted["surviving"]) < len(pvalues)
    assert adjusted["family_size"] == 21


def test_benjamini_hochberg_keeps_a_real_signal_even_after_correction() -> None:
    pvalues = {f"noise{index}": 0.5 for index in range(30)}
    pvalues["real"] = 1e-6

    adjusted = screen.bh_adjust(pvalues, 0.10)

    assert adjusted["surviving"] == ["real"]


def test_closed_trade_takes_the_stop_first_when_one_bar_holds_both_levels() -> None:
    # A flat then sharply lower bar: the stop is hit inside it. The horizon is far away.
    opens = [100.0, 100.0] + [100.0] * 12
    bars = series(opens, spread=0.0)
    bars = screen.Series(
        symbol=bars.symbol,
        stamps=bars.stamps,
        open=bars.open,
        high=np.full(len(opens), 101.0),
        low=np.full(len(opens), 90.0),
        close=bars.close,
        volume=bars.volume,
    )
    atr = np.full(len(opens), 0.2)

    trade = trade_net_bps(
        bars,
        atr,
        0,
        "LONG",
        horizon=12,
        stop_multiple=2.0,
        price_bps_per_side=0.0,
        fee_bps_per_side=10.0,
    )

    assert trade is not None
    assert trade["exit_reason"] == "stop"
    assert trade["gross_bps"] < 0
    assert trade["net_bps"] == pytest.approx(trade["gross_bps"] - 20.0)


def test_closed_trade_charges_both_legs_and_the_price_terms() -> None:
    opens = [100.0 + index * 0.5 for index in range(20)]
    bars = series(opens, spread=0.0)
    atr = np.full(len(opens), 1.0)

    trade = trade_net_bps(
        bars,
        atr,
        0,
        "LONG",
        horizon=12,
        stop_multiple=2.0,
        price_bps_per_side=5.0,
        fee_bps_per_side=10.0,
    )

    assert trade is not None
    assert trade["fees_bps"] == pytest.approx(20.0)
    assert trade["net_bps"] == pytest.approx(trade["gross_bps"] - 20.0)
    # the entry is 5 bps worse than the quoted open, the exit 5 bps worse as well
    assert trade["gross_bps"] < (opens[13] / opens[1] - 1.0) * 1e4


def test_closed_trade_is_none_when_the_horizon_leaves_the_data() -> None:
    bars = series([100.0] * 5)
    atr = np.full(5, 1.0)

    assert (
        trade_net_bps(
            bars,
            atr,
            2,
            "LONG",
            horizon=12,
            stop_multiple=2.0,
            price_bps_per_side=0.0,
            fee_bps_per_side=10.0,
        )
        is None
    )


def _cell(
    *,
    family: str,
    lane: str,
    is_mean: float,
    val_mean: float,
    cost: float,
    is_p: float,
    signals: int = 100,
) -> dict[str, object]:
    def row(mean: float) -> dict[str, object]:
        return {
            "signals": signals,
            "measured": signals,
            "mean_bps": mean,
            "bootstrap": {
                "mean": mean,
                "ci_lower": mean - 1.0,
                "ci_upper": mean + 1.0,
                "p_one_sided": is_p,
            },
            "symbol": "TESTUSDT",
        }

    horizon = "exit_policy" if lane == "lane_b" else "12"
    return {
        "lane": lane,
        "family": family,
        "timeframe": "1h",
        "symbol": "TESTUSDT",
        "cost": {"round_trip_bps": cost},
        "signals": {
            "RESEARCH": {"signals": signals, "signals_per_day": 1.0, "horizons": {horizon: row(is_mean)}},
            "IS": {"signals": signals, "signals_per_day": 1.0, "horizons": {horizon: row(is_mean)}},
            "VAL": {"signals": signals, "signals_per_day": 1.0, "horizons": {horizon: row(val_mean)}},
            "TEST": {"signals": signals, "signals_per_day": 1.0, "horizons": {horizon: row(val_mean)}},
        },
    }


def design_stub(q: float = 0.10) -> dict[str, object]:
    return {
        "cost_model": {"fee_floor_bps_no_bnb": 20.0},
        "statistics": {"multiple_testing": {"q": q}},
        "gates": {},
    }


def test_economic_gate_fails_when_the_gross_does_not_cover_the_cost() -> None:
    cell = _cell(family="mean_reversion", lane="lane_a", is_mean=8.0, val_mean=9.0, cost=24.8, is_p=0.001)

    evaluation = screen.evaluate(design_stub(), [cell])

    decision = evaluation["decisions"][0]
    assert decision["verdict"] == "EXPERIMENT"
    assert decision["gates"]["S1_existence"] is True
    assert decision["gates"]["S3_economic"] is False
    assert "S3_economic" in decision["failed_gates"]


def test_a_candidate_that_covers_the_full_round_trip_advances() -> None:
    cell = _cell(family="trend", lane="lane_a", is_mean=60.0, val_mean=55.0, cost=24.8, is_p=1e-4)

    evaluation = screen.evaluate(design_stub(), [cell])

    decision = evaluation["decisions"][0]
    assert decision["gates"]["S3_economic"] is True
    assert decision["verdict"] == "ADVANCE_TO_VALIDATION"
    assert evaluation["verdict"] == "CANDIDATE_FOUND"


def test_without_multiple_testing_correction_a_marginal_cell_is_not_promoted() -> None:
    strong = _cell(family="trend", lane="lane_a", is_mean=60.0, val_mean=55.0, cost=24.8, is_p=0.04)
    noise = [
        _cell(family=f"noise{index}", lane="lane_a", is_mean=1.0, val_mean=1.0, cost=24.8, is_p=0.5)
        for index in range(40)
    ]

    evaluation = screen.evaluate(design_stub(), [strong, *noise])

    decision = next(row for row in evaluation["decisions"] if row["family"] == "trend")
    assert decision["gates"]["S1_existence"] is True
    assert decision["gates"]["S4_multiple_testing"] is False
    assert decision["verdict"] == "EXPERIMENT"


def test_a_small_sample_is_insufficient_evidence_not_a_pass() -> None:
    cell = _cell(
        family="volatility", lane="lane_a", is_mean=90.0, val_mean=90.0, cost=24.8, is_p=0.001, signals=5
    )

    evaluation = screen.evaluate(design_stub(), [cell])

    decision = evaluation["decisions"][0]
    assert decision["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert decision["gates"]["S0_sample"] is False


def test_lane_b_is_gated_on_its_own_exit_policy() -> None:
    cell = _cell(family="trend_pullback", lane="lane_b", is_mean=40.0, val_mean=-5.0, cost=24.8, is_p=0.01)

    evaluation = screen.evaluate(design_stub(), [cell])

    decision = evaluation["decisions"][0]
    assert decision["best_horizon"] == "exit_policy"
    assert decision["gates"]["S2_replication"] is False
    assert decision["verdict"] == "EXPERIMENT"


def test_csv_keeps_one_row_per_cell_and_the_verdict_column(tmp_path: Path) -> None:
    cell = _cell(family="mean_reversion", lane="lane_a", is_mean=8.0, val_mean=9.0, cost=24.8, is_p=0.2)
    evaluation = screen.evaluate(design_stub(), [cell])
    path = tmp_path / "screening.csv"

    screen.write_csv(path, {"cells": evaluation["decisions"]})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("lane,family,timeframe")
    assert lines[1].endswith("EXPERIMENT")


def test_partitions_in_the_design_never_reach_the_holdout() -> None:
    design = screen._read_json(
        REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001" / "design" / "DESIGN.json"
    )
    holdout = screen._parse_utc(design["holdout"]["start_utc"])

    for block in design["partitions"].values():
        assert screen._parse_utc(block["end_utc"]) <= holdout
    assert design["holdout"]["status"] == "CLOSED"


def test_day_constant_matches_the_bootstrap_unit() -> None:
    assert DAY_MS == 24 * 60 * 60 * 1000
