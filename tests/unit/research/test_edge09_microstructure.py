"""Tests for the RFC-EDGE-009 research package.

They cover the parts whose failure would be silent: the point-in-time clock of
the panel, the run filter (a capture tree holds several runs), the accounting of
a truncated segment, the stride of the frequency bound, the barrier arithmetic
and the order of the classification ladder.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from trading_bot.research.edge09 import panel
from trading_bot.research.edge09.experiments import (
    frequency_classification,
    frequency_experiment,
    imbalance,
    pool_frequency,
    rank,
    spearman,
)
from trading_bot.research.edge09.gates import (
    QUOTE_SIZE_USD,
    aggregate_frequency,
    capacity_rows,
    spread_stats,
)
from trading_bot.research.edge09.panel import PanelSeries, PanelWriter, read_panel
from trading_bot.research.edge09.registration import (
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    CLASSIFICATIONS,
    CONSUMED_HOLDOUTS,
    HYPOTHESES,
    LADDER,
    MIN_GROSS_SAFETY_MULTIPLE,
    MIN_OBSERVATIONS,
    UNIVERSE,
)
from trading_bot.research.edge09.verdict import classify


def _book_ticker(receive_time: int, bid: float, ask: float, run: str = "run-a") -> str:
    return json.dumps(
        {
            "run_id": run,
            "event_type": "book_ticker",
            "receive_time": receive_time,
            "bid": f"{bid:.8f}",
            "ask": f"{ask:.8f}",
            "bid_qty": "2.0",
            "ask_qty": "1.0",
        }
    )


def _agg_trade(
    receive_time: int, price: float, quantity: float, side: str, run: str = "run-a"
) -> str:
    return json.dumps(
        {
            "run_id": run,
            "event_type": "agg_trade",
            "receive_time": receive_time,
            "price": f"{price:.8f}",
            "quantity": f"{quantity:.8f}",
            "aggressor_side": side,
        }
    )


@contextmanager
def _writer(tmp_path: Path) -> Iterator[tuple[PanelWriter, Path]]:
    """The three panel layers, opened where the test can see them close."""
    base = tmp_path / "out"
    base.mkdir(parents=True, exist_ok=True)
    with (
        (base / "PANEL_SECONDS.csv").open("w", encoding="utf-8", newline="\n") as seconds,
        (base / "OI_SAMPLES.csv").open("w", encoding="utf-8", newline="\n") as oi,
        (base / "DEPTH_SNAPSHOTS.csv").open("w", encoding="utf-8", newline="\n") as depth,
    ):
        yield PanelWriter(seconds, oi, depth), base


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


# ----------------------------------------------------------------------- panel


def test_book_ticker_becomes_one_row_per_second_with_the_state_at_the_boundary(
    tmp_path: Path,
) -> None:
    segment = _write(
        tmp_path / "book.jsonl.gz",
        [
            _book_ticker(1_000_120, 100.0, 100.2),
            _book_ticker(1_000_500, 101.0, 101.2),
            _book_ticker(1_001_050, 102.0, 102.2),
            _book_ticker(1_002_010, 103.0, 103.2),
        ],
    )
    with _writer(tmp_path) as (writer, base):
        panel.ingest_book_ticker(writer, "run-a", "spot", "BTCUSDT", [segment])
    rows = read_panel(base / "PANEL_SECONDS.csv")

    # The first second only establishes state; then one row per boundary, with
    # the state of the FIRST event at or after that boundary.
    assert [row["second_ms"] for row in rows] == [1_001_000, 1_002_000]
    assert rows[0]["mid"] == pytest.approx(102.1)
    assert rows[1]["mid"] == pytest.approx(103.1)
    assert rows[0]["decision_time"] == 1_001_050


def test_second_row_clock_stays_inside_its_own_second(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "book.jsonl.gz",
        [_book_ticker(1_000_120, 100.0, 100.2), _book_ticker(1_001_050, 102.0, 102.2)],
    )
    with _writer(tmp_path) as (writer, base):
        panel.ingest_book_ticker(writer, "run-a", "spot", "BTCUSDT", [segment])
    for row in read_panel(base / "PANEL_SECONDS.csv"):
        assert row["second_ms"] <= row["decision_time"] < row["second_ms"] + 1000


def test_rows_of_another_run_are_skipped(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "book.jsonl.gz",
        [
            _book_ticker(1_000_120, 100.0, 100.2, run="run-b"),
            _book_ticker(1_001_050, 500.0, 500.2, run="run-b"),
            _book_ticker(1_000_120, 100.0, 100.2, run="run-a"),
            _book_ticker(1_001_050, 102.0, 102.2, run="run-a"),
        ],
    )
    with _writer(tmp_path) as (writer, base):
        panel.ingest_book_ticker(writer, "run-a", "spot", "BTCUSDT", [segment])
    rows = read_panel(base / "PANEL_SECONDS.csv")
    assert rows and all(row["run"] == "run-a" for row in rows)
    assert rows[0]["mid"] == pytest.approx(102.1)


def test_trade_flow_is_joined_into_the_second_it_belongs_to(tmp_path: Path) -> None:
    book = _write(
        tmp_path / "book.jsonl.gz",
        [_book_ticker(1_000_120, 100.0, 100.2), _book_ticker(1_001_050, 102.0, 102.2)],
    )
    trades = _write(
        tmp_path / "trades.jsonl.gz",
        [
            _agg_trade(1_001_100, 102.1, 3.0, "buy"),
            _agg_trade(1_001_200, 102.0, 1.0, "sell"),
        ],
    )
    with _writer(tmp_path) as (writer, base):
        flow = panel.ingest_agg_trades(writer, "run-a", "spot", "BTCUSDT", [trades])
        panel.ingest_book_ticker(writer, "run-a", "spot", "BTCUSDT", [book], flow)
    rows = read_panel(base / "PANEL_SECONDS.csv")
    assert rows[0]["trades"] == 2
    assert rows[0]["signed_volume"] == pytest.approx(2.0)


def test_a_truncated_segment_is_counted_and_does_not_stop_the_panel(tmp_path: Path) -> None:
    good = _write(
        tmp_path / "good.jsonl.gz",
        [_book_ticker(1_000_120, 100.0, 100.2), _book_ticker(1_001_050, 102.0, 102.2)],
    )
    torn = tmp_path / "torn.jsonl.gz"
    payload = gzip.compress((_book_ticker(1_100_120, 100.0, 100.2) + "\n").encode("utf-8"))
    torn.write_bytes(payload[:-4])  # a gzip stream that ends before its trailer

    with _writer(tmp_path) as (writer, base):
        panel.ingest_book_ticker(writer, "run-a", "spot", "BTCUSDT", [good, torn])
        stats = writer.stats["run-a|spot|BTCUSDT"]
    assert stats.truncated_segments == 1
    assert stats.truncated_paths
    assert read_panel(base / "PANEL_SECONDS.csv")


def test_missing_seconds_are_counted_not_carried_forward(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "book.jsonl.gz",
        [
            _book_ticker(1_000_120, 100.0, 100.2),
            _book_ticker(1_001_050, 102.0, 102.2),
            _book_ticker(1_010_050, 103.0, 103.2),
        ],
    )
    with _writer(tmp_path) as (writer, _base):
        panel.ingest_book_ticker(writer, "run-a", "spot", "BTCUSDT", [segment])
        stats = writer.stats["run-a|spot|BTCUSDT"]
    assert stats.missing_seconds == 8
    assert stats.seconds == 2


def test_forward_return_is_taken_from_a_row_at_or_after_the_horizon() -> None:
    rows = [
        {"decision_time": 1_000_000, "mid": 100.0, "second_ms": 1_000_000},
        {"decision_time": 1_002_000, "mid": 101.0, "second_ms": 1_002_000},
        {"decision_time": 1_003_000, "mid": 102.0, "second_ms": 1_003_000},
    ]
    series = PanelSeries("run", "spot", "BTCUSDT", rows)
    # The partner of a 1 s horizon from t=1_000_000 is the row at 1_002_000, not
    # the nearest row: a horizon is never satisfied early.
    assert series.forward_mid(0, 1) == pytest.approx(101.0)
    assert series.forward_return_bps(0, 1) == pytest.approx(100.0)
    assert series.index_at_or_after(1_002_500) == 2


# ---------------------------------------------------------------------- gates


def test_spread_stats_reports_the_measurement_not_a_default() -> None:
    stats = spread_stats([{"spread_bps": 0.0}, {"spread_bps": 0.01}, {"spread_bps": 0.03}])
    assert stats["observations"] == 2
    assert stats["median_bps"] == pytest.approx(0.02)
    assert spread_stats([{"spread_bps": 0.0}])["median_bps"] is None


def test_capacity_is_measured_inside_the_band() -> None:
    depth = [
        {
            "run": "r",
            "market": "spot",
            "symbol": "BTCUSDT",
            "ts_ms": 1,
            "side": "bid",
            "level": 0,
            "price": 100.0,
            "qty": 1.0,
        },
        {
            "run": "r",
            "market": "spot",
            "symbol": "BTCUSDT",
            "ts_ms": 1,
            "side": "bid",
            "level": 1,
            "price": 99.99,
            "qty": 1.0,
        },
        {
            "run": "r",
            "market": "spot",
            "symbol": "BTCUSDT",
            "ts_ms": 1,
            "side": "ask",
            "level": 0,
            "price": 100.02,
            "qty": 1.0,
        },
    ]
    row = capacity_rows(depth, bands_bps=(1.0,))[0]
    assert row["mid"] == pytest.approx(100.01)
    # A 1 bp band around 100.01 is 0.010001 usd wide: the level at 100.00 is
    # inside it and the one at 99.99 is outside, so the band admits exactly one.
    assert row["bid_notional_within_1.0bps_usd"] == pytest.approx(100.0)
    wider = capacity_rows(depth, bands_bps=(2.0,))[0]
    assert wider["bid_notional_within_2.0bps_usd"] == pytest.approx(100.0 + 99.99)


def test_frequency_bound_counts_non_overlapping_windows() -> None:
    rows = []
    for index in range(10):
        rows.append(
            {
                "run": "r",
                "market": "spot",
                "symbol": "BTCUSDT",
                "second_ms": index * 1000,
                "decision_time": index * 1000,
                "mid": 100.0 + index,
                "bid": 100.0,
                "ask": 100.2,
                "spread_bps": 1.0,
                "bid_qty": 1.0,
                "ask_qty": 1.0,
                "quote_events": 1,
                "trades": 0,
                "signed_volume": 0.0,
                "last_trade_price": 0.0,
            }
        )
    series = PanelSeries("r", "spot", "BTCUSDT", rows)
    series_map = {("r", "spot", "BTCUSDT"): series}
    from trading_bot.research.edge09.gates import frequency_rows

    frequency = frequency_rows(series_map, {("spot", "BTCUSDT"): 1.0})
    for_horizon = {row["horizon_seconds"]: row for row in frequency if row["horizon_seconds"] == 5}
    # Ten one-second rows span nine seconds, so at a 5 s horizon only the window
    # at t=0 can be closed by the sample; the overlapping count is four times
    # larger because it counts the same move from every second it is visible.
    assert for_horizon[5]["non_overlapping_windows"] == 1
    assert for_horizon[5]["non_overlapping_clearing"] == 1
    assert for_horizon[5]["measured_windows"] == 5
    assert for_horizon[5]["measured_windows"] > for_horizon[5]["non_overlapping_windows"]
    pooled = aggregate_frequency(frequency, 5)
    assert pooled["streams_summed"] == 1
    assert pooled["clearing_per_day"] is not None


# -------------------------------------------------------------------- verdict


def test_ladder_is_applied_in_order() -> None:
    common = {"track": "ACTIVE", "cost_bps": 23.0}
    assert (
        classify(n=10, ic=0.5, gross_bps=100.0, **common)["classification"] == "INSUFFICIENT_SAMPLE"
    )
    assert (
        classify(n=MIN_OBSERVATIONS, ic=0.0, gross_bps=100.0, **common)["classification"]
        == "NO_INFORMATION"
    )
    assert (
        classify(n=MIN_OBSERVATIONS, ic=0.2, gross_bps=-1.0, **common)["classification"]
        == "NO_GROSS_EDGE"
    )
    below = classify(n=MIN_OBSERVATIONS, ic=0.2, gross_bps=22.0, **common)
    assert below["classification"] == "COST_KILLED"
    assert below["failed_filter"] == "F2"
    margin = classify(n=MIN_OBSERVATIONS, ic=0.2, gross_bps=23.0 * 1.2, **common)
    assert margin["classification"] == "COST_KILLED"
    assert margin["failed_filter"] == "F3"
    capacity = classify(
        n=MIN_OBSERVATIONS,
        ic=0.2,
        gross_bps=23.0 * MIN_GROSS_SAFETY_MULTIPLE,
        capacity_ok=False,
        **common,
    )
    assert capacity["classification"] == "CAPACITY_KILLED"
    frequency = classify(
        n=MIN_OBSERVATIONS,
        ic=0.2,
        gross_bps=100.0,
        capacity_ok=True,
        opportunities_per_day=0.5,
        **common,
    )
    assert frequency["classification"] == "FREQUENCY_KILLED"
    admitted = classify(
        n=MIN_OBSERVATIONS,
        ic=0.2,
        gross_bps=100.0,
        capacity_ok=True,
        opportunities_per_day=10.0,
        **common,
    )
    assert admitted["classification"] == "ADMIT_RESEARCH"
    assert admitted["promotion"] == "NONE"


def test_every_classification_is_registered_vocabulary() -> None:
    outputs = {
        classify(n=1, ic=None, gross_bps=None, cost_bps=None, track="ACTIVE")["classification"],
        classify(n=MIN_OBSERVATIONS, ic=0.0, gross_bps=1.0, cost_bps=1.0, track="ACTIVE")[
            "classification"
        ],
        classify(n=MIN_OBSERVATIONS, ic=0.2, gross_bps=-1.0, cost_bps=1.0, track="ACTIVE")[
            "classification"
        ],
        classify(n=MIN_OBSERVATIONS, ic=0.2, gross_bps=1.0, cost_bps=2.0, track="ACTIVE")[
            "classification"
        ],
        classify(
            n=MIN_OBSERVATIONS,
            ic=0.2,
            gross_bps=5.0,
            cost_bps=2.0,
            track="ACTIVE",
            capacity_ok=False,
        )["classification"],
        classify(
            n=MIN_OBSERVATIONS,
            ic=0.2,
            gross_bps=5.0,
            cost_bps=2.0,
            track="ACTIVE",
            capacity_ok=True,
            opportunities_per_day=0.0,
        )["classification"],
        classify(
            n=MIN_OBSERVATIONS,
            ic=0.2,
            gross_bps=5.0,
            cost_bps=2.0,
            track="ACTIVE",
            capacity_ok=True,
            opportunities_per_day=9.0,
        )["classification"],
    }
    assert outputs <= set(CLASSIFICATIONS)


# --------------------------------------------------------------- experiments


def test_imbalance_is_signed_and_silent_when_empty() -> None:
    assert imbalance({"bid_qty": 3.0, "ask_qty": 1.0}) == pytest.approx(0.5)
    assert imbalance({"bid_qty": 1.0, "ask_qty": 3.0}) == pytest.approx(-0.5)
    assert imbalance({"bid_qty": 0.0, "ask_qty": 0.0}) is None


def test_rank_averages_ties() -> None:
    assert rank([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_is_one_for_a_monotone_relation() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert spearman(xs, ys) == pytest.approx(1.0)
    assert spearman(xs, list(reversed(ys))) == pytest.approx(-1.0)


def _series_with_mids(mids: list[float]) -> PanelSeries:
    """One stream whose mid follows ``mids``, one row per second."""
    rows = [
        {
            "run": "r",
            "market": "spot",
            "symbol": "BTCUSDT",
            "second_ms": index * 1000,
            "decision_time": index * 1000,
            "mid": mid,
            "bid": mid - 0.01,
            "ask": mid + 0.01,
            "spread_bps": 2.0,
            "bid_qty": 9.0,
            "ask_qty": 1.0,
            "quote_events": 1,
            "trades": 0,
            "signed_volume": 0.0,
            "last_trade_price": 0.0,
        }
        for index, mid in enumerate(mids)
    ]
    return PanelSeries("r", "spot", "BTCUSDT", rows)


def test_opportunity_count_is_long_only_and_the_span_is_declared() -> None:
    """A downward move is not an opportunity this runtime can execute."""
    falling = frequency_experiment(
        _series_with_mids([100.0] * 5 + [99.0] * 15), horizon_seconds=5, barrier_bps=50.0
    )
    assert falling["clearing_long_only"] == 0
    assert falling["clearing_any_direction"] == 5
    assert falling["opportunities_per_day"] == 0.0
    assert falling["opportunities_per_day_any_direction"] > 0.0
    # Nineteen one-second rows span nineteen seconds: the rate is extrapolated
    # from hours of capture and the row says so.
    assert falling["span_days"] == pytest.approx(19 / 86_400.0, abs=1e-5)
    assert falling["span_hours"] == pytest.approx(19 / 3600.0, abs=1e-3)
    assert falling["rate_extrapolated_from_hours"] is True

    rising = frequency_experiment(
        _series_with_mids([100.0] * 5 + [101.0] * 15), horizon_seconds=5, barrier_bps=50.0
    )
    assert rising["clearing_long_only"] == 5
    assert rising["clearing_any_direction"] == 5
    assert rising["opportunities_per_day"] > 0.0


def test_pooled_frequency_keeps_horizons_apart() -> None:
    cells = [
        {
            "horizon_seconds": 1,
            "span_days": 0.05,
            "opportunities_per_day": 1.0,
            "opportunities_per_day_any_direction": 2.0,
        },
        {
            "horizon_seconds": 1,
            "span_days": 0.05,
            "opportunities_per_day": 2.0,
            "opportunities_per_day_any_direction": 3.0,
        },
        {
            "horizon_seconds": 60,
            "span_days": 0.05,
            "opportunities_per_day": 144.0,
            "opportunities_per_day_any_direction": 312.0,
        },
        {"horizon_seconds": 60, "span_days": 0.05, "opportunities_per_day": None},
    ]
    pooled = {row["horizon_seconds"]: row for row in pool_frequency(cells)}
    # Summing across horizons would report 147/day: the same tape counted twice.
    assert pooled[1]["opportunities_per_day"] == pytest.approx(3.0)
    assert pooled[1]["opportunities_per_day_any_direction"] == pytest.approx(5.0)
    assert pooled[60]["opportunities_per_day"] == pytest.approx(144.0)
    assert pooled[60]["streams_summed"] == 1
    assert pooled[60]["meets_target"] is True
    assert pooled[60]["rate_extrapolated_from_hours"] is True


def test_frequency_is_only_killed_when_every_horizon_is_below_target() -> None:
    below = pool_frequency(
        [
            {
                "horizon_seconds": 1,
                "span_days": 0.05,
                "opportunities_per_day": 0.0,
                "opportunities_per_day_any_direction": 4.0,
            }
        ]
    )
    verdict = frequency_classification(below)
    assert verdict["classification"] == "FREQUENCY_KILLED"
    assert verdict["failed_filter"] == "F5"
    assert "0.0" in verdict["reason"]

    mixed = pool_frequency(
        [
            {
                "horizon_seconds": 1,
                "span_days": 0.05,
                "opportunities_per_day": 0.0,
                "opportunities_per_day_any_direction": 0.0,
            },
            {
                "horizon_seconds": 60,
                "span_days": 0.05,
                "opportunities_per_day": 144.0,
                "opportunities_per_day_any_direction": 312.0,
            },
        ]
    )
    verdict = frequency_classification(mixed)
    assert verdict["classification"] == "OBSERVED"
    assert "h=60s" in verdict["reason"]
    assert frequency_classification([])["classification"] == "INSUFFICIENT_SAMPLE"


# --------------------------------------------------------------- registration


def test_hypotheses_are_unique_and_complete() -> None:
    ids = [hypothesis.id for hypothesis in HYPOTHESES]
    assert len(ids) == len(set(ids))
    assert {"E-01", "E-05", "E-07"} <= set(ids)
    assert [row["id"] for row in LADDER] == ["F0", "F1", "F2", "F3", "F4", "F5"]


def test_the_universe_shares_no_symbol_with_a_consumed_holdout() -> None:
    consumed: set[str] = set()
    for row in CONSUMED_HOLDOUTS:
        if row.get("symbols"):
            consumed.update(part.strip() for part in row["symbols"].split(","))
    assert set(UNIVERSE) & consumed == set()


def test_active_target_is_the_registered_objective() -> None:
    assert ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY == 3.0
    assert QUOTE_SIZE_USD == 1000.0
