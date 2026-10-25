"""EXP-003O — the independent rebuilder and the parity audit, pinned without the future.

The tests below fix the parts that a drift would silently break: the window convention (an EMA
re-seeded on 80 bars is not an EMA over the series), the rule predicates on hand-built bars, the
closed difference classes, and the causal contract that decides whether a row is a PIT
violation, a timing mismatch or nothing at all.

They deliberately do not touch the 275 724-key streams: those are reproduced by the pipeline,
not by a unit test.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import exp_003o_compare as compare  # noqa: E402
import exp_003o_contract as contract  # noqa: E402
import exp_003o_rebuilder as rebuilder  # noqa: E402
import exp_003o_verify as verify  # noqa: E402

INTERVAL = 3_600_000
START = 1_782_000_000_000


def bars_from(closes: list[float], volume: float = 100.0) -> list[contract.Bar]:
    return [
        contract.Bar(
            ts_ms=START + index * INTERVAL,
            open=closes[index - 1] if index else closes[0],
            high=max(closes[index - 1] if index else closes[0], closes[index]) * 1.001,
            low=min(closes[index - 1] if index else closes[0], closes[index]) * 0.999,
            close=closes[index],
            volume=volume,
        )
        for index in range(len(closes))
    ]


# --------------------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------------------


def test_inventory_has_the_24_cells_with_stable_parameter_hashes() -> None:
    cells = contract.cell_inventory()
    assert len(cells) == 24
    assert {cell["lane"] for cell in cells} == {"A", "B"}
    assert len({cell["cell_id"] for cell in cells}) == 24
    for cell in cells:
        assert contract.parameter_hash(cell["parameters"]) == contract.parameter_hash(
            dict(cell["parameters"])
        )


def test_window_digest_is_stable_and_sensitive() -> None:
    bars = bars_from([100.0, 101.0, 102.0])
    assert contract.window_digest(bars) == contract.window_digest(list(bars))
    changed = list(bars)
    changed[-1] = contract.Bar(
        ts_ms=bars[-1].ts_ms,
        open=bars[-1].open,
        high=bars[-1].high,
        low=bars[-1].low,
        close=bars[-1].close + 0.01,
        volume=bars[-1].volume,
    )
    assert contract.window_digest(changed) != contract.window_digest(bars)


def test_partition_lookup_is_half_open() -> None:
    assert contract.partition_of(contract.utc_ms("2026-07-11T00:00:00Z")) == "VAL"
    assert contract.partition_of(contract.utc_ms("2026-07-10T23:00:00Z")) == "IS"
    assert contract.partition_of(contract.utc_ms("2026-08-06T00:00:00Z")) is None


# --------------------------------------------------------------------------------------
# indicators, from the specification
# --------------------------------------------------------------------------------------


def test_ema_is_seeded_with_the_mean_of_its_first_values() -> None:
    values = np.asarray([[1.0, 2.0, 3.0, 4.0, 5.0]])
    # seed = mean(1,2,3) = 2, then k = 2/4 through 4 and 5
    manual = 2.0 + (4.0 - 2.0) * (2.0 / 4.0)
    manual = manual + (5.0 - manual) * (2.0 / 4.0)
    assert rebuilder.ema_last(values, 3)[0] == pytest.approx(manual)
    assert rebuilder.ema_series(values, 3).shape == (1, 3)


def test_rsi_is_100_when_no_bar_loses() -> None:
    values = np.asarray([[100.0 + index for index in range(20)]])
    assert rebuilder.rsi_last(values, 14)[0] == pytest.approx(100.0)


def test_atr_equals_the_mean_true_range_when_the_range_is_constant() -> None:
    closes = np.full((1, 20), 100.0)
    high = np.full((1, 20), 101.0)
    low = np.full((1, 20), 99.0)
    assert rebuilder.atr_last(high, low, closes, 14)[0] == pytest.approx(2.0)


def test_bollinger_uses_the_population_deviation() -> None:
    values = np.asarray([[float(index) for index in range(20)]])
    upper, lower, middle = rebuilder.bollinger_last(values, 20, 2.0)
    population = float(np.sqrt(((np.arange(20) - 9.5) ** 2).mean()))
    assert middle[0] == pytest.approx(9.5)
    assert upper[0] - middle[0] == pytest.approx(2.0 * population)
    assert middle[0] - lower[0] == pytest.approx(2.0 * population)


# --------------------------------------------------------------------------------------
# lane A rules on hand-built windows
# --------------------------------------------------------------------------------------


def _window(closes: list[float], volume: float = 100.0) -> dict[str, Any]:
    bars = bars_from(closes, volume)
    series = {
        "ts": np.asarray([bar.ts_ms for bar in bars], dtype=np.int64),
        "open": np.asarray([bar.open for bar in bars], dtype=float),
        "high": np.asarray([bar.high for bar in bars], dtype=float),
        "low": np.asarray([bar.low for bar in bars], dtype=float),
        "close": np.asarray([bar.close for bar in bars], dtype=float),
        "volume": np.asarray([bar.volume for bar in bars], dtype=float),
    }
    close = np.lib.stride_tricks.sliding_window_view(series["close"], 80)
    high = np.lib.stride_tricks.sliding_window_view(series["high"], 80)
    low = np.lib.stride_tricks.sliding_window_view(series["low"], 80)
    vol = np.lib.stride_tricks.sliding_window_view(series["volume"], 80)
    return {"series": series, "close": close, "high": high, "low": low, "volume": vol}


def test_ema_crossover_is_long_on_a_monotone_rise_and_short_on_a_fall() -> None:
    rising = _window([100.0 + index for index in range(80)])
    masks = rebuilder.lane_a_states(
        "ema_crossover", rising["close"], rising["high"], rising["low"], rising["volume"]
    )
    assert bool(masks["long"][0])
    assert not bool(masks["short"][0])

    falling = _window([200.0 - index for index in range(80)])
    masks = rebuilder.lane_a_states(
        "ema_crossover", falling["close"], falling["high"], falling["low"], falling["volume"]
    )
    assert bool(masks["short"][0])
    assert not bool(masks["long"][0])


def test_breakout_needs_a_volume_confirmed_break() -> None:
    flat = [100.0] * 79 + [100.0]
    quiet = _window(flat, volume=100.0)
    masks = rebuilder.lane_a_states(
        "breakout", quiet["close"], quiet["high"], quiet["low"], quiet["volume"]
    )
    assert not bool(masks["long"][0])

    jump = [100.0] * 79 + [104.0]
    bars = bars_from(jump, volume=100.0)
    bars[-1] = contract.Bar(
        ts_ms=bars[-1].ts_ms,
        open=bars[-1].open,
        high=bars[-1].high,
        low=bars[-1].low,
        close=104.0,
        volume=400.0,
    )
    series = {
        "close": np.asarray([[bar.close for bar in bars]]),
        "high": np.asarray([[bar.high for bar in bars]]),
        "low": np.asarray([[bar.low for bar in bars]]),
        "volume": np.asarray([[bar.volume for bar in bars]]),
    }
    masks = rebuilder.lane_a_states(
        "breakout", series["close"], series["high"], series["low"], series["volume"]
    )
    assert bool(masks["long"][0])


def test_trend_recomputes_the_previous_slow_ema_on_a_shorter_prefix() -> None:
    """The slope compares two differently seeded EMAs, not two values of one series."""

    closes = [100.0 + 0.5 * index for index in range(80)]
    window = _window(closes)
    masks = rebuilder.lane_a_states(
        "trend", window["close"], window["high"], window["low"], window["volume"]
    )
    assert bool(masks["long"][0])

    slow = rebuilder.ema_last(window["close"], 55)
    slow_previous = rebuilder.ema_last(window["close"][:, :-1], 55)
    slope = (slow - slow_previous) / slow_previous
    assert float(slope[0]) > 0.0005


# --------------------------------------------------------------------------------------
# lane B fixtures: activation and silence
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture_id", "expected_signals"),
    [
        ("vol_regime_breakout_active", 1),
        ("vol_regime_breakout_quiet", 0),
        ("trend_pullback_active", 1),
        ("trend_pullback_quiet", 0),
        ("mean_reversion_vol_liq_active", 2),
        ("mean_reversion_vol_liq_quiet", 0),
    ],
)
def test_fixtures_activate_and_stay_quiet(fixture_id: str, expected_signals: int) -> None:
    import exp_003o_fixtures as fixtures

    protocol = json.loads(
        (contract.OUT / "design" / "PROTOCOL.json").read_text(encoding="utf-8")
    )
    payload = next(item for item in fixtures.build(protocol) if item["fixture_id"] == fixture_id)
    cell = next(item for item in protocol["cells"] if item["cell_id"] == payload["cell_id"])
    bars = [
        contract.Bar(
            ts_ms=int(item["ts_ms"]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            volume=float(item["volume"]),
        )
        for item in payload["bars"]
    ]
    rows, _ = rebuilder.lane_b_rows(protocol, cell, fixture_id, bars)
    signals = [row for row in rows if row["state"] == "SIGNAL"]
    assert len(signals) == expected_signals
    if expected_signals:
        entries = [row for row in signals if row["direction"] != "FLAT"]
        assert entries, "an active fixture must contain at least one entry"
        assert all(row["direction"] == "LONG" for row in entries)
        assert int(signals[0]["decision_ms"]) > bars[int(cell["warmup_bars"])].ts_ms


# --------------------------------------------------------------------------------------
# comparator
# --------------------------------------------------------------------------------------


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "cell_id": "ema_crossover@1h",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "decision_ms": START + INTERVAL,
        "bar_open_ms": START,
        "bar_close_ms": START + INTERVAL,
        "data_available_ms": START + INTERVAL,
        "state": "SIGNAL",
        "direction": "LONG",
        "reason": None,
        "parameter_hash": "p" * 64,
        "input_snapshot_hash": "d" * 64,
        "window_first_ms": START - 79 * INTERVAL,
        "window_last_ms": START,
        "window_bars": 80,
        "producer": "test",
    }
    base.update(overrides)
    return base


def test_row_contract_rejects_a_window_that_reaches_into_the_future() -> None:
    compare.validate_row(_row(), INTERVAL)
    with pytest.raises(compare.RowError):
        compare.validate_row(_row(window_last_ms=START + INTERVAL), INTERVAL)
    with pytest.raises(compare.RowError):
        compare.validate_row(_row(state="NOT_READY", direction=None, reason=None), INTERVAL)


def test_classify_pair_names_the_first_difference_it_finds() -> None:
    left = _row()
    assert compare.classify_pair(left, dict(left)) is None
    assert (
        compare.classify_pair(left, _row(input_snapshot_hash="e" * 64)) == "INPUT_MISMATCH"
    )
    assert compare.classify_pair(left, _row(parameter_hash="q" * 64)) == "PARAMETER_HASH_MISMATCH"
    assert compare.classify_pair(left, _row(state="NO_SIGNAL", direction=None)) == "STATE_MISMATCH"
    assert compare.classify_pair(left, _row(direction="SHORT")) == "DIRECTION_MISMATCH"


def test_compare_reports_mismatches_and_never_averags_them(tmp_path: Path) -> None:
    protocol = {
        "run_id": "TEST",
        "timeframes_ms": {"5m": 300_000, "1h": INTERVAL, "4h": 14_400_000},
        "cells": [
            {
                "cell_id": "ema_crossover@1h",
                "lane": "A",
                "family": "ema_crossover",
                "timeframe": "1h",
                "warmup_bars": 79,
                "parameters": {"window_bars": 80},
                "parameter_hash": "p" * 64,
            }
        ],
    }
    left = {"cell_id": "ema_crossover@1h", "symbol": "BTCUSDT", "decision_ms": START + INTERVAL}
    protocol["cells"][0]["cell_id"] = left["cell_id"]

    original_rows = [_row(), _row(decision_ms=START + 2 * INTERVAL, state="NO_SIGNAL", direction=None)]
    independent_rows = [
        _row(direction="SHORT"),
        _row(decision_ms=START + 2 * INTERVAL, state="NO_SIGNAL", direction=None),
    ]
    left_path = tmp_path / "original.jsonl.gz"
    right_path = tmp_path / "independent.jsonl.gz"
    for path, rows in ((left_path, original_rows), (right_path, independent_rows)):
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item) + "\n")
    summary = compare.compare(protocol, left_path, right_path, tmp_path)
    assert summary["mismatches_unexplained"] == 1
    assert summary["differences_by_class"] == {"DIRECTION_MISMATCH": 1}
    assert summary["verdict"] == "FAIL"


# --------------------------------------------------------------------------------------
# verifier invariants
# --------------------------------------------------------------------------------------


def test_timing_contract_separates_pit_from_clock() -> None:
    good = _row()
    assert verify._row_timing_defect(good, INTERVAL) is None
    assert (
        verify._row_timing_defect(_row(data_available_ms=START), INTERVAL) == "PIT_VIOLATION"
    )
    # the decision moved to the open of its own bar, the bar and its data unchanged
    assert verify._row_timing_defect(_row(decision_ms=START), INTERVAL) == "TIMING_MISMATCH"
    assert (
        verify._row_timing_defect(_row(window_last_ms=START + INTERVAL), INTERVAL)
        == "PIT_VIOLATION"
    )


def test_join_streams_counts_a_missing_signal_as_a_signal_difference() -> None:
    key = ("ema_crossover@1h", "BTCUSDT", START + INTERVAL)
    joined = verify.join_streams({key: _row()}, {})
    assert joined["by_class"] == {"MISSING_SIGNAL": 1}


def test_prefix_compare_flags_a_state_that_moves_after_the_cut() -> None:
    key = ("ema_crossover@1h", "BTCUSDT", START + INTERVAL)
    full = {key: _row()}
    prefix = {key: _row(state="NO_SIGNAL", direction=None)}
    assert verify.prefix_compare(prefix, full) == [key]
    assert verify.prefix_compare(full, full) == []
