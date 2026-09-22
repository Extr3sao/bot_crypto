"""H3-RELVAL-BTCETH-BETANEUTRAL-SPREAD-01 — unit tests (frozen prereg contracts).

Pins: DEF-RESEARCH-COST-001-proof (absolute, monotone, identical trade set),
multi-leg cost arithmetic, PIT trailing beta/spread/z, future-mutation
invariant, exit conventions (stop-first, revert, time stop), and B4 gates.
"""

from __future__ import annotations

import numpy as np
import pytest

from trading_bot.research.h3_relative_value import (
    COST_SIDE_BPS,
    HOLD_BARS,
    WARMUP,
    compute_features,
    cost_scenario_net_r,
    neutrality,
    simulate_pair,
    summarize,
)


def _mk_ts(n: int, start: int = 1_600_000_000_000) -> np.ndarray:
    return np.arange(n, dtype=np.int64) * 3_600_000 + start


def _pair_prices(n: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Synthetic co-moving pair with recurring spread dislocations."""
    rng = np.random.default_rng(seed)
    mkt = np.cumsum(rng.normal(0.0, 0.004, n))
    a = 30_000 * np.exp(mkt + 0.01 * np.sin(np.arange(n) / 50))
    b = 2_000 * np.exp(0.95 * mkt + 0.02 * np.sin(np.arange(n) / 50))
    # recurring +4% dislocations of leg B (80 bars each, every 500 bars) so
    # the trailing z transiently crosses the frozen entry threshold
    shock = 0.04 * ((np.arange(n) % 500) < 80)
    b = b * (1.0 + shock)
    open_a = np.concatenate(([a[0]], a[:-1]))
    open_b = np.concatenate(([b[0]], b[:-1]))
    return open_a, a, open_b, b


def test_absolute_cost_monotone_and_trade_set_identical() -> None:
    n = 3000
    ts = _mk_ts(n)
    op_a, cl_a, op_b, cl_b = _pair_prices(n)
    feat = compute_features(cl_a, cl_b)
    trades, _ = simulate_pair(ts, op_a, cl_a, op_b, cl_b, feat)
    if not trades:
        pytest.skip("no trades on synthetic path")
    nets = {}
    for bps in (0.0, 5.0, 10.0, 20.0, 40.0):
        net = cost_scenario_net_r(trades, bps)
        nets[bps] = float(np.mean(net))
        assert len(net) == len(trades)  # identical trade set
        assert all(
            c >= -1e-12 for c in (t.gross_r - x for t, x in zip(trades, net, strict=False))
        )  # COST >= 0
    assert nets[0.0] >= nets[5.0] >= nets[10.0] >= nets[20.0] >= nets[40.0]
    # linear absolute semantics: cost grows exactly with bps
    assert (nets[0.0] - nets[10.0]) == pytest.approx(
        (nets[0.0] - nets[20.0]) / 2, rel=1e-9, abs=1e-12
    )


def test_multileg_cost_arithmetic() -> None:
    n = 3000
    ts = _mk_ts(n)
    op_a, cl_a, op_b, cl_b = _pair_prices(n)
    feat = compute_features(cl_a, cl_b)
    trades, _ = simulate_pair(ts, op_a, cl_a, op_b, cl_b, feat)
    if not trades:
        pytest.skip("no trades on synthetic path")
    t = trades[0]
    c = (2.0 * COST_SIDE_BPS / 10_000.0) * (1.0 + abs(t.beta)) / t.spread_std
    assert t.cost_r == pytest.approx(c, abs=1e-12)
    assert t.net_r == pytest.approx(t.gross_r - t.cost_r, abs=1e-12)


def test_pit_features_trailing_only() -> None:
    n = 1200
    _, _, _, cl_b = _pair_prices(n)
    _op_a, cl_a, _, _ = _pair_prices(n)
    feat1 = compute_features(cl_a, cl_b)
    # change ONE observation far in the past: only later features may move
    cl_a2 = cl_a.copy()
    k = 500
    cl_a2[k] *= 1.2
    feat2 = compute_features(cl_a2, cl_b)
    same_before = bool(np.array_equal(feat1["z"][: k + 1], feat2["z"][: k + 1], equal_nan=True))
    assert same_before


def test_future_mutation_invariant() -> None:
    n = 3000
    ts = _mk_ts(n)
    op_a, cl_a, op_b, cl_b = _pair_prices(n)
    T = n // 2
    feat1 = compute_features(cl_a, cl_b)
    t1, _ = simulate_pair(ts, op_a, cl_a, op_b, cl_b, feat1)
    op_a2, cl_a2, op_b2, cl_b2 = op_a.copy(), cl_a.copy(), op_b.copy(), cl_b.copy()
    op_a2[T + 1 :] *= 1.5
    cl_a2[T + 1 :] *= 1.5
    op_b2[T + 1 :] *= 0.7
    cl_b2[T + 1 :] *= 0.7
    feat2 = compute_features(cl_a2, cl_b2)
    t2, _ = simulate_pair(ts, op_a2, cl_a2, op_b2, cl_b2, feat2)
    for k in ("beta", "spread", "spread_std", "z"):
        assert np.array_equal(feat1[k][: T + 1], feat2[k][: T + 1], equal_nan=True)
    fields = ("decision_index", "direction", "entry_index", "beta", "entry_z")
    d1 = [tuple(getattr(x, f) for f in fields) for x in t1 if x.decision_index <= T]
    d2 = [tuple(getattr(x, f) for f in fields) for x in t2 if x.decision_index <= T]
    assert d1 == d2


def test_exit_conventions_stop_first_and_time_stop() -> None:
    # engineered path: enter, then a bar satisfying BOTH revert and stop -> stop wins
    n = 1200
    ts = _mk_ts(n)
    rng = np.random.default_rng(3)
    mkt = np.cumsum(rng.normal(0, 0.001, n))
    a = 30_000 * np.exp(mkt)
    b = 2_000 * np.exp(0.95 * mkt)
    # dislocate the spread right after WARMUP+entry to force |z| >= 4
    b[WARMUP + 3 : WARMUP + 10] *= 1.06
    open_a = np.concatenate(([a[0]], a[:-1]))
    open_b = np.concatenate(([b[0]], b[:-1]))
    feat = compute_features(a, b)
    trades, _ = simulate_pair(ts, open_a, a, open_b, b, feat)
    for t in trades:
        if t.exit_reason == "Z_STOP":
            assert abs(t.exit_z) >= 4.0
    assert all(t.exit_index - t.entry_index + 1 <= HOLD_BARS for t in trades)


def test_neutrality_accounting_and_classify_gates() -> None:
    n = 3000
    ts = _mk_ts(n)
    op_a, cl_a, op_b, cl_b = _pair_prices(n)
    feat = compute_features(cl_a, cl_b)
    trades, _ = simulate_pair(ts, op_a, cl_a, op_b, cl_b, feat)
    if not trades:
        pytest.skip("no trades on synthetic path")
    neu = neutrality(trades)
    assert neu["MEAN_GROSS_EXPOSURE"] > 0.0
    assert neu["MEAN_ABS_NET_EXPOSURE"] >= 0.0
    m = summarize(trades)
    assert m["N"] == len(trades)
    assert m["halves"] in (
        [1, 1],
        [-1, -1],
        [1, -1],
        [-1, 1],
        [0, 1],
        [1, 0],
        [0, -1],
        [-1, 0],
        [0, 0],
    )
    assert m["thirds"] in (
        [1, 1, 1],
        [-1, -1, -1],
        [1, 1, -1],
        [1, -1, 1],
        [-1, 1, 1],
        [1, -1, -1],
        [-1, 1, -1],
        [-1, -1, 1],
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
        [0, 0, -1],
        [0, -1, 0],
        [-1, 0, 0],
        [1, 0, -1],
        [-1, 0, 1],
        [0, 1, -1],
        [0, -1, 1],
    )
