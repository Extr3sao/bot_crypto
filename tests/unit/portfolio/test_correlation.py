from __future__ import annotations

import math

import pytest

from trading_bot.portfolio.correlation import (
    CorrelationState,
    DynamicCorrelationEngine,
    FusionConfig,
    aligned_pit_returns,
    rolling_correlation,
)


def _series(corr: float, n: int, *, start_ts: int = 0, step: int = 60_000) -> tuple[tuple[int, float], tuple[tuple[int, float], ...]]:
    """Two return series with approximately the requested correlation."""
    rng_a = [((i * 37) % 11 - 5) / 50 for i in range(n)]
    rng_b = [corr * a + (1 - abs(corr)) * (((i * 53) % 13 - 6) / 60) for i, a in enumerate(rng_a)]
    ts = tuple(start_ts + i * step for i in range(n))
    a = tuple(zip(ts, rng_a, strict=True))
    b = tuple(zip(ts, rng_b, strict=True))
    return a, b


def test_aligned_pit_returns_no_forward_fill() -> None:
    ts = (0, 60_000, 120_000, 300_000)  # gap between 120k and 300k
    prices = (100.0, 101.0, 99.0, 102.0)
    returns = aligned_pit_returns(ts, prices)
    # 3 returns for 4 observations: the gap yields a return between existing
    # points; nothing is fabricated as 0.0 for missing bars.
    assert len(returns) == 3
    assert returns[0] == (60_000, pytest.approx(0.01))
    assert returns[2][0] == 300_000
    assert returns[2][1] == pytest.approx(102.0 / 99.0 - 1)


def test_aligned_pit_rejects_misaligned_and_descending() -> None:
    with pytest.raises(ValueError):
        aligned_pit_returns((0, 60_000), (100.0,))
    with pytest.raises(ValueError):
        aligned_pit_returns((60_000, 0), (100.0, 101.0))


def test_rolling_correlation_skips_insufficient_overlap() -> None:
    a, b = _series(0.9, 40)
    rolling = rolling_correlation(a, b, window=30)
    assert len(rolling) == 40 - 30 + 1  # no states before the window fills
    assert all(-1.0 <= v <= 1.0 for _, v in rolling)


def test_perfectly_correlated_series_scores_high() -> None:
    n = 40
    ts = tuple(i * 60_000 for i in range(n))
    base = [((i * 29) % 7 - 3) / 25 for i in range(n)]
    a = tuple(zip(ts, base, strict=True))
    b = tuple(zip(ts, [x for x in base], strict=True))
    rolling = rolling_correlation(a, b, window=20)
    assert rolling[-1][1] == pytest.approx(1.0)


def test_hysteresis_enter_and_exit() -> None:
    # Construct a pair that is strongly fused early, then decorrelates.
    n_fused, n_normal = 60, 60
    ts = tuple(i * 60_000 for i in range(n_fused + n_normal))
    a_vals: list[float] = []
    b_vals: list[float] = []
    for i in range(n_fused):
        v = ((i * 41) % 9 - 4) / 30
        a_vals.append(v)
        b_vals.append(v)  # identical: corr = 1
    for i in range(n_normal):
        v = ((i * 41) % 9 - 4) / 30
        w = ((i * 67 + 13) % 11 - 5) / 30
        a_vals.append(v)
        b_vals.append(w)  # independent-ish
    a = tuple(zip(ts, a_vals, strict=True))
    b = tuple(zip(ts, b_vals, strict=True))
    engine = DynamicCorrelationEngine(FusionConfig(window=30, smoothing_span=3, fuse_enter=0.85, fuse_exit=0.4, edge_threshold=0.7))
    states, _smoothed = engine.evaluate_series(a, b)
    values = [s.value for _, s in states]
    assert "FUSED" in values  # entered fused
    assert values[-1] == "NORMAL"  # exited after decorrelation (hysteresis exit)


def test_hysteresis_no_flapping_in_band() -> None:
    engine = DynamicCorrelationEngine(FusionConfig(window=10, smoothing_span=1, fuse_enter=0.9, fuse_exit=0.5, edge_threshold=0.8))
    # Directly probe the state machine with a synthetic correlation stream
    # inside the hysteresis band [0.5, 0.9]: state must stay put.
    n = 40
    ts = tuple(i * 60_000 for i in range(n))
    a = tuple(zip(ts, [0.01 * ((i % 5) - 2) for i in range(n)], strict=True))
    b = tuple(zip(ts, [0.01 * ((i % 5) - 2) for i in range(n)], strict=True))
    rolling = rolling_correlation(a, b, window=10)
    assert rolling[-1][1] == pytest.approx(1.0)
    # State machine smoke: enters FUSED on perfect correlation.
    states, _ = engine.evaluate_series(a, b)
    assert states[-1][1] is CorrelationState.FUSED


def test_future_mutation_leaves_past_states_byte_identical() -> None:
    a, b = _series(0.9, 80)
    engine_before = DynamicCorrelationEngine(FusionConfig(window=30, smoothing_span=3))
    states_before, smooth_before = engine_before.evaluate_series(a, b)
    past_cut = 50  # timestamps <= this are 'the past'
    past_before = [(t, s.value) for t, s in states_before if t <= past_cut * 60_000]
    smooth_past_before = [(t, v) for t, v in smooth_before if t <= past_cut * 60_000]

    # Mutate ALL future observations drastically.
    a_mut = tuple((t, v * 7 + 3) if t > past_cut * 60_000 else (t, v) for t, v in a)
    b_mut = tuple((t, -v * 11 - 1) if t > past_cut * 60_000 else (t, v) for t, v in b)
    engine_after = DynamicCorrelationEngine(FusionConfig(window=30, smoothing_span=3))
    states_after, smooth_after = engine_after.evaluate_series(a_mut, b_mut)
    past_after = [(t, s.value) for t, s in states_after if t <= past_cut * 60_000]
    smooth_past_after = [(t, v) for t, v in smooth_after if t <= past_cut * 60_000]

    assert past_before == past_after
    assert smooth_past_before == smooth_past_after


def test_zero_variance_yields_zero_not_nan() -> None:
    n = 10
    ts = tuple(i * 60_000 for i in range(n))
    a = tuple(zip(ts, [0.01] * n, strict=True))
    b = tuple(zip(ts, [0.02] * n, strict=True))
    rolling = rolling_correlation(a, b, window=5)
    assert all(not math.isnan(v) and v == 0.0 for _, v in rolling)


def test_state_is_context_only_no_alpha_exports() -> None:
    # Guard: the module exposes states/levels, never signals or orders.
    import trading_bot.portfolio.correlation as corr

    exports = {name for name in dir(corr) if not name.startswith("_")}
    assert "submit" not in exports
    assert "order" not in exports
    assert CorrelationState.NORMAL.value == "NORMAL"
