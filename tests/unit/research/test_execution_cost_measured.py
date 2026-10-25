"""Measured cost: every number says how it was obtained, and an unmeasured size is not scaled.

The assertions that matter are the uncomfortable ones:

* a size nobody walked produces ``DECLARED_SIZE_NOT_WALKED`` and a **lower bound**, never a
  measurement;
* an empty tape produces ``INSUFFICIENT_EVIDENCE``, never ``0.0`` bps, because a free round trip is
  a claim about the venue rather than an absence of data;
* the weakest component decides the class of the total, so a measured spread cannot make an
  assumed impact look measured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.research.execution_cost import (
    COST_CONFIRMED,
    COST_LOWER,
    INSUFFICIENT_EVIDENCE,
    MEASURED,
    SIZE_NOT_WALKED,
    AssetMeasurement,
    Quote,
    evaluate_cost_question,
    load_st6_quotes,
    measure_asset,
    measure_round_trip,
    percentile,
    weakest_class,
)
from trading_bot.research.execution_cost.measured import DEFAULT_TAKER_FEE_BPS
from trading_bot.research.microstructure.cost_model_v3 import VENUE_SPECS


def _quote(
    *,
    asset: str = "BTCUSDT",
    spread_bps: float = 0.0012,
    impact: float | None = 0.0,
    impact_size: float | None = 200.0,
    day: str = "2026-10-19",
    rejected: bool = False,
) -> Quote:
    return Quote(
        asset=asset,
        window_id="20261019T040323Z",
        day=day,
        observed_at_utc=f"{day}T04:03:22Z",
        bid=80_000.0,
        ask=80_000.0 + spread_bps * 80_000.0 / 10_000.0,
        spread_bps=spread_bps,
        impact_buy_bps=impact,
        impact_sell_bps=impact,
        impact_size_usdt=impact_size,
        raw_sha256="a" * 64,
        rejected=rejected,
    )


# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #
def test_the_fee_comes_from_the_shared_venue_registry() -> None:
    assert VENUE_SPECS["BINANCE_SPOT_STANDARD_TAKER"].taker_fee_bps == DEFAULT_TAKER_FEE_BPS


def test_weakest_class_wins() -> None:
    assert weakest_class(["KNOWN", "OBSERVED"]) == "OBSERVED"
    assert weakest_class(["OBSERVED", "ASSUMED"]) == "ASSUMED"
    assert weakest_class(["KNOWN"]) == "KNOWN"
    with pytest.raises(ValueError):
        weakest_class(["MEASURED"])


def test_percentile_is_nearest_rank_and_returns_a_measured_value() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50.0) == 3.0
    assert percentile(values, 100.0) == 5.0
    assert percentile(values, 10.0) == 1.0


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #
def test_a_walked_size_is_measured() -> None:
    result = measure_round_trip([_quote()], asset="BTCUSDT", size_usdt=200.0)
    assert result.status == MEASURED
    assert result.size_status == "OBSERVED_AT_DECLARED_SIZE"
    assert result.total_knowledge == "OBSERVED"
    assert result.total_bps == pytest.approx(2 * DEFAULT_TAKER_FEE_BPS + 0.0012)


def test_an_unwalked_size_yields_a_lower_bound_not_a_measurement() -> None:
    result = measure_round_trip([_quote()], asset="BTCUSDT", size_usdt=500.0)
    assert result.status == SIZE_NOT_WALKED
    assert result.size_status == "DECLARED_SIZE_NOT_WALKED"
    impact = next(c for c in result.components if c.name == "depth_impact_round_trip")
    assert impact.bps is None
    assert result.total_bps == pytest.approx(2 * DEFAULT_TAKER_FEE_BPS + 0.0012)
    assert any("LOWER BOUND" in note for note in result.notes)


def test_no_observation_is_not_a_free_trade() -> None:
    result = measure_round_trip([], asset="BTCUSDT", size_usdt=500.0)
    assert result.status == INSUFFICIENT_EVIDENCE
    assert result.total_bps is None
    assert result.observations == 0


def test_rejected_quotes_do_not_count_towards_evidence() -> None:
    quote = _quote()
    rejected = Quote(
        asset=quote.asset,
        window_id=quote.window_id,
        day=quote.day,
        observed_at_utc=quote.observed_at_utc,
        bid=quote.bid,
        ask=quote.bid,  # crossed; only legal because it is marked rejected
        spread_bps=quote.spread_bps,
        impact_buy_bps=0.0,
        impact_sell_bps=0.0,
        impact_size_usdt=200.0,
        raw_sha256="b" * 64,
        rejected=True,
    )
    result = measure_round_trip([quote, rejected], asset="BTCUSDT", size_usdt=200.0)
    assert result.observations == 1


def test_a_crossed_book_that_is_not_flagged_is_refused() -> None:
    with pytest.raises(ValueError):
        Quote(
            asset="BTCUSDT",
            window_id="w",
            day="2026-10-19",
            observed_at_utc="2026-10-19T00:00:00Z",
            bid=100.0,
            ask=99.0,
            spread_bps=1.0,
            impact_buy_bps=None,
            impact_sell_bps=None,
            impact_size_usdt=None,
            raw_sha256=None,
        )


def test_negative_cost_is_refused() -> None:
    with pytest.raises(ValueError):
        measure_round_trip([_quote()], asset="BTCUSDT", size_usdt=200.0, taker_fee_bps=-1.0)


def test_per_asset_distribution_reports_the_tail_not_just_the_median() -> None:
    quotes = [_quote(spread_bps=value) for value in (0.001, 0.002, 0.003, 9.0)]
    measurement = measure_asset(quotes, asset="BTCUSDT", size_usdt=200.0)
    assert measurement.observations == 4
    assert measurement.median_bps < measurement.p90_bps <= measurement.worst_bps


# --------------------------------------------------------------------------- #
# the frozen rule
# --------------------------------------------------------------------------- #
def _measurement(asset: str, median: float, *, status: str = MEASURED) -> AssetMeasurement:
    return AssetMeasurement(
        asset=asset,
        size_usdt=500.0,
        observations=200,
        days=90,
        median_bps=median,
        p10_bps=median - 0.1,
        p90_bps=median + 0.1,
        worst_bps=median + 0.2,
        knowledge="OBSERVED",
        size_status=(
            "OBSERVED_AT_DECLARED_SIZE" if status == MEASURED else "DECLARED_SIZE_NOT_WALKED"
        ),
        status=status,
        detail=measure_round_trip([_quote()], asset=asset, size_usdt=200.0),
    )


def test_the_rule_cannot_fire_before_the_sample_exists() -> None:
    outcome = evaluate_cost_question(
        {"BTCUSDT": _measurement("BTCUSDT", 18.0)}, observed_days=13, coverage=1.0
    )
    assert outcome["outcome"] == INSUFFICIENT_EVIDENCE
    assert outcome["authorises"] == "nothing"
    assert outcome["economic_executions"] == 0


def test_the_rule_can_say_cost_lower_on_a_complete_sample() -> None:
    measurements = {
        asset: _measurement(asset, 18.0) for asset in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }
    outcome = evaluate_cost_question(
        measurements,
        observed_days=90,
        coverage=1.0,
        reference_bps={"BTCUSDT": 24.786, "ETHUSDT": 24.786, "SOLUSDT": 27.310},
    )
    assert outcome["outcome"] == COST_LOWER
    assert outcome["authorises"] == "nothing"


def test_the_rule_can_say_cost_confirmed() -> None:
    measurements = {asset: _measurement(asset, 26.0) for asset in ("BTCUSDT", "ETHUSDT")}
    outcome = evaluate_cost_question(
        measurements, observed_days=90, coverage=1.0, reference_bps={"BTCUSDT": 24.786}
    )
    assert outcome["outcome"] == COST_CONFIRMED


def test_an_unwalked_size_can_never_produce_cost_lower() -> None:
    measurements = {
        asset: _measurement(asset, 18.0, status=SIZE_NOT_WALKED)
        for asset in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }
    outcome = evaluate_cost_question(measurements, observed_days=365, coverage=1.0)
    assert outcome["outcome"] == INSUFFICIENT_EVIDENCE


# --------------------------------------------------------------------------- #
# the real tape
# --------------------------------------------------------------------------- #
def test_the_real_st6_tape_loads_and_is_measurable() -> None:
    path = Path("data/st6/ST6_OBSERVATIONS.jsonl")
    if not path.exists():  # pragma: no cover - the tape is absent in a clean checkout
        pytest.skip("ST-6 observation tape is not present in this checkout")
    quotes = load_st6_quotes(path)
    assert len(quotes) > 0
    assert {quote.asset for quote in quotes} >= {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    measurement = measure_asset(quotes, asset="BTCUSDT", size_usdt=200.0)
    assert measurement.status == MEASURED
    assert measurement.median_bps >= 2 * DEFAULT_TAKER_FEE_BPS - 1e-9


def test_a_malformed_tape_line_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_st6_quotes(path)


def test_the_loader_marks_a_crossed_row_rejected_instead_of_dropping_it(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    path.write_text(
        json.dumps(
            {
                "asset": "BTCUSDT",
                "window_id": "w",
                "observed_at_utc": "2026-10-19T00:00:00Z",
                "bid": 100.0,
                "ask": 99.0,
                "spread_bps": 1.0,
                "impact": {"buy_bps": 0.0, "sell_bps": 0.0, "size_usdt": 200.0},
                "market": {"day": "2026-10-19"},
                "raw": {"uncompressed_sha256": "c" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    quotes = load_st6_quotes(path)
    assert quotes[0].rejected is True
    assert quotes[0].usable is False
