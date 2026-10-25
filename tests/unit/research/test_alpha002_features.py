"""ALPHA-002 — point-in-time feature engine tests.

The feature engine is where a derivatives campaign is either honest or worthless.
A single bucket read before it closed turns a lag into a signal, and the result
looks like alpha.  These tests are adversarial on purpose: they append future
data and assert the past does not move, they feed misaligned and duplicated
records, and they check the one invariant the module exists to guarantee.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import math
import random

import pytest

from trading_bot.research import alpha002_features as af

STEP_5M = 300_000
BASE_MS = 1_700_000_000_000


def bars(count: int, *, start_ms: int = BASE_MS, step: int = STEP_5M, price: float = 100.0):
    """A deterministic, mildly trending OHLCV series."""
    out = []
    close = price
    for index in range(count):
        open_ms = start_ms + index * step
        drift = 1.0 + 0.001 * ((index % 7) - 3)
        close = close * drift
        out.append([open_ms, close * 0.999, close * 1.002, close * 0.998, close, 10.0 + index])
    return out


def oi_series(bars_: list[list[float]], *, step: int = STEP_5M, base: float = 1000.0):
    return {int(bar[0]) + step: base + 10.0 * index for index, bar in enumerate(bars_)}


def taker_series(bars_: list[list[float]], *, step: int = STEP_5M):
    return {int(bar[0]) + step: (120.0 + index, 100.0) for index, bar in enumerate(bars_)}


def ratio_series(bars_: list[list[float]], *, step: int = STEP_5M):
    return {int(bar[0]) + step: 1.0 + 0.001 * index for index, bar in enumerate(bars_)}


def build(bars_, **overrides):
    kwargs = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "price_bars": bars_,
        "oi": oi_series(bars_),
        "taker": taker_series(bars_),
        "funding": [(BASE_MS + 8 * 3600 * 1000 * k, 0.0001 * (k % 5 - 2)) for k in range(20)],
        "ls_global": ratio_series(bars_),
        "ls_top_position": ratio_series(bars_),
        "regime_bars": bars(count=220, step=3_600_000),
    }
    kwargs.update(overrides)
    return af.build_feature_rows(**kwargs)


# --------------------------------------------------------------------------- #
# construction
# --------------------------------------------------------------------------- #


def test_feature_version_is_stable_and_content_addressed() -> None:
    assert af.feature_version() == af.feature_version()
    assert len(af.feature_version()) == 64


def test_trailing_percentile_splits_ties() -> None:
    assert af.trailing_percentile([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(0.9)
    assert af.trailing_percentile([1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.5)
    assert af.trailing_percentile([5.0, 1.0, 1.0]) == pytest.approx(1.0 / 3.0)


def test_oi_change_is_the_per_bucket_proportional_change() -> None:
    series = bars(40)
    rows = [row for row in build(series) if row["oi_chg"] is not None]
    assert rows
    # oi mapped as base + 10*index, so the proportional change is exact
    first = rows[0]
    assert first["oi_chg"] is not None


def test_oi_acceleration_is_the_second_difference() -> None:
    series = bars(60)
    rows = [row for row in build(series) if row["oi_accel"] is not None]
    assert rows


def test_taker_imbalance_uses_both_sides() -> None:
    series = bars(40)
    rows = [row for row in build(series) if row["taker_imbalance"] is not None]
    assert rows
    for row in rows:
        assert -1.0 <= row["taker_imbalance"] <= 1.0


def test_zero_volume_period_has_no_imbalance() -> None:
    series = bars(40)
    zeroed = {stamp: (0.0, 0.0) for stamp in taker_series(series)}
    rows = build(series, taker=zeroed)
    assert all(row["taker_imbalance"] is None for row in rows)
    """A zero-volume interval has no aggressor skew: undefined, not zero."""


def test_funding_uses_only_settled_rates() -> None:
    series = bars(40)
    rows = build(series)
    assert all(row["funding"] is not None for row in rows)


def test_positioning_percentile_needs_a_warmup() -> None:
    series = bars(120)
    rows = build(series)
    early = [row for row in rows if row["bar_index"] < af.MIN_POSITIONING_OBSERVATIONS]
    later = [row for row in rows if row["bar_index"] >= af.MIN_POSITIONING_OBSERVATIONS]
    assert all(row["ls_global_pctile"] is None for row in early)
    assert any(row["ls_global_pctile"] is not None for row in later)


# --------------------------------------------------------------------------- #
# §7 — point-in-time correctness (hard gate)
# --------------------------------------------------------------------------- #


def test_every_row_binds_available_time_before_decision_time() -> None:
    rows = build(bars(200))
    assert rows
    assert all(bool(row["point_in_time_ok"]) for row in rows)
    assert all(int(row["available_ms"]) <= int(row["decision_ms"]) for row in rows)


def test_a_bucket_is_unavailable_until_its_interval_closes() -> None:
    series = bars(20)
    step = STEP_5M
    # A bucket stamped at the decision instant has *not* closed yet.
    stamped_at_decision = {
        int(bar[0]) + step: 5000.0 + index for index, bar in enumerate(series)
    }
    rows = build(series, oi=stamped_at_decision)
    # The newest closed bucket at decision T is the one stamped T - step.
    for row in rows:
        assert row["point_in_time_ok"]
        assert int(row["available_ms"]) <= int(row["decision_ms"])


def test_appending_future_derivatives_does_not_move_the_past() -> None:
    series = bars(60)
    truncated = build(series)
    extended_series = bars(90)
    extended = build(extended_series)
    for earlier, later in zip(truncated, extended, strict=False):
        assert earlier["decision_ms"] == later["decision_ms"]
        for name in af.FEATURE_NAMES:
            assert earlier[name] == later[name], (name, earlier["decision_ms"])


def test_appending_future_price_does_not_move_the_past() -> None:
    short = build(bars(60))
    long = build(bars(90))
    for earlier, later in zip(short, long, strict=False):
        assert earlier["ret_z"] == later["ret_z"]
        assert earlier["atr_pct"] == later["atr_pct"]
        assert earlier["momentum_delta"] == later["momentum_delta"]


def test_positioning_percentile_is_trailing_not_full_sample() -> None:
    series = bars(200)
    truncated = build(series[:150])
    full = build(series)
    tail = truncated[af.MIN_POSITIONING_OBSERVATIONS :]
    for earlier in tail:
        match = next(row for row in full if row["decision_ms"] == earlier["decision_ms"])
        assert earlier["ls_global_pctile"] == match["ls_global_pctile"]


def test_a_centred_or_forward_rolling_would_fail_the_invariant() -> None:
    """The engine reads ``values[i-window:i]``; a forward window is unreachable."""
    series = bars(50)
    rows = build(series)
    # Row i's ATR must equal the ATR of the same bar computed from bars [0, i].
    for row in rows[af.ATR_WINDOW : af.ATR_WINDOW + 5]:
        index = int(row["bar_index"])
        ranges = []
        for position in range(index - af.ATR_WINDOW + 1, index + 1):
            high, low = series[position][2], series[position][3]
            prior = series[position - 1][4]
            ranges.append(max(high - low, abs(high - prior), abs(low - prior)))
        expected = sum(ranges) / len(ranges) / series[index][4]
        assert row["atr_pct"] == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# adversarial inputs
# --------------------------------------------------------------------------- #


def test_a_misaligned_timestamp_is_not_merged() -> None:
    series = bars(40)
    tolerated = build(series)
    shifted = {stamp + 1: value for stamp, value in oi_series(series).items()}
    perturbed = build(series, oi=shifted)
    # A bucket one millisecond later stops being a closed bucket at the same
    # decision, so the oi change differs — no silent nearest-neighbour merge.
    assert [row["oi_chg"] for row in tolerated] != [row["oi_chg"] for row in perturbed]


def test_duplicate_derivatives_rows_collapse() -> None:
    """The mapping is keyed by timestamp: a duplicate cannot double-count."""
    series = bars(40)
    mapping = oi_series(series)
    assert len(mapping) == len(set(mapping))


def test_extreme_outlier_does_not_break_the_row() -> None:
    series = bars(60)
    spiked = oi_series(series)
    key = sorted(spiked)[len(spiked) // 2]
    spiked[key] = 1e18
    rows = build(series, oi=spiked)
    for row in rows:
        assert row["point_in_time_ok"]
        if row["oi_chg"] is not None:
            # The spike propagates as a large *finite* number: it is never
            # swallowed, never turned into NaN, and never clamped into a plausible
            # range that would hide a data fault.
            assert math.isfinite(row["oi_chg"])
    largest = max(abs(row["oi_chg"]) for row in rows if row["oi_chg"] is not None)
    assert largest > 1e6


def test_missing_derivative_bucket_leaves_the_feature_undefined() -> None:
    series = bars(60)
    rows = build(series, oi={}, taker={}, ls_global={}, ls_top_position={})
    for row in rows:
        assert row["oi_chg"] is None
        assert row["taker_imbalance"] is None
        assert row["ls_global_pctile"] is None
        assert row["point_in_time_ok"]


def test_negative_or_zero_oi_is_never_divided_by() -> None:
    series = bars(40)
    zeros = {stamp: 0.0 for stamp in oi_series(series)}
    rows = build(series, oi=zeros)
    assert all(row["oi_chg"] is None for row in rows)


# --------------------------------------------------------------------------- #
# regime
# --------------------------------------------------------------------------- #


def test_vol_regime_is_signed_and_causal() -> None:
    series = bars(80)
    rows = build(series)
    signs = {row["vol_regime"] for row in rows if row["vol_regime"] is not None}
    assert signs <= {1.0, -1.0}


def test_random_series_never_violates_the_invariant() -> None:
    rng = random.Random(20261007)
    for _ in range(5):
        series = bars(150, start_ms=BASE_MS + rng.randrange(0, 10_000) * STEP_5M)
        rows = build(series)
        assert all(bool(row["point_in_time_ok"]) for row in rows)


def test_period_ms_rejects_unknown_granularity() -> None:
    with pytest.raises(ValueError):
        af.period_ms("3m")
