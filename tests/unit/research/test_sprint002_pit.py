"""RFC-022 / EDGE DISCOVERY SPRINT 002 — PIT, accounting and isolation tests.

TEST_TARGET == RUNTIME_TARGET: the resampler, the event engine and the
lead/lag signal are the exact functions ``scripts/sprint002_*.py`` execute, so
the tests exercise the same code paths that produced the sprint artifacts.

Covered contracts:
  * ``resample`` is past-only (prefix invariance) and drops the trailing bucket;
  * ``resample`` reproduces the certified 15m/30m/1h files from the 5m source;
  * ``run_spec`` enters at the OPEN of the bar after the signal bar;
  * ``net_bps == gross_bps - cost_bps`` and the certified cost is applied;
  * intra-bar stop takes priority over target; time stop exits at the open;
  * slippage stress scales only the modelled slippage component;
  * the split map is disjoint and the holdout windows are never in discovery;
  * ``sig_lead_lag`` consumes the leader's *past* bar and never the future.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_signals as S  # noqa: E402

START_MS = 1_772_323_200_000
CONFIG_HASH = "d4ff9414a45680c6f709eb9f49865cbb797025d6c0f2b08993903385a7120ef1"
SPLIT_SHA = {
    "DISCOVERY": "6b0d8f61e0a5d98117dc2af241d9f8487cfa26b6e3e82c074ea4ff7498b00892",
    "VALIDATION": "7b2ed3a086ec5ce0ebeaf122e8fcadeaf6c6e9185050ea20b7e512a429d7756e",
    "HOLDOUT": "3acc341089247b3c142f87eae62845057ac09db7923b7c253a7ea03ce4b23238",
}

HAS_DATA = any(L.DATA_DIR.glob("*.json"))
needs_data = pytest.mark.skipif(not HAS_DATA, reason="baseline dataset not present")


def synth(n: int, *, tf_min: float = 30.0, seed: int = 5) -> L.Bars:
    """Deterministic OHLCV series with valid prices, no external data."""
    rng = np.random.default_rng(seed)
    ts = START_MS + np.arange(n, dtype=np.float64) * tf_min * 60_000.0
    ret = rng.normal(0.0004, 0.004, size=n)
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate(([100.0], close[:-1]))
    span = np.abs(rng.normal(0.0, 0.002, size=n)) * close + 0.01
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span
    vol = rng.integers(5, 50, size=n).astype(np.float64)
    return L.Bars(ts=ts, o=open_, h=high, lo=low, c=close, v=vol)


def _prefix(bars: L.Bars, k: int) -> L.Bars:
    return L.Bars(
        ts=bars.ts[:k],
        o=bars.o[:k],
        h=bars.h[:k],
        lo=bars.lo[:k],
        c=bars.c[:k],
        v=bars.v[:k],
    )


def _spike(idx: int) -> L.SignalFn:
    def fn(b: L.Bundle) -> np.ndarray:
        arr = np.zeros(len(b), dtype=np.float64)
        if idx < arr.shape[0]:
            arr[idx] = 1.0
        return arr

    return fn


def _spec(
    signals: L.SignalFn,
    *,
    tgt: float = 4.0,
    stop: float = 2.0,
    hold: int = 32,
) -> L.Spec:
    return L.Spec(
        candidate_id="T",
        hypothesis_id="H-T",
        family="t",
        timeframe="30m",
        signals=signals,
        warmup=262,
        atr_target_mult=tgt,
        atr_target_is_atr=True,
        atr_stop_mult=stop,
        hold_bars=hold,
    )


# ---------------------------------------------------------------------------
# certified configuration
# ---------------------------------------------------------------------------


def test_cost_model_matches_certified_values() -> None:
    assert L.CERTIFIED_ROUND_TRIP_BPS == 23.790569
    assert L.SLIPPAGE_COMPONENT_BPS == 2.632456
    assert L.COST_STRESS["PLUS_25"] == 29.738211
    assert L.COST_STRESS["PLUS_50"] == 35.685854
    assert L.COST_STRESS["PLUS_100"] == 47.581138


def test_config_hash_is_locked() -> None:
    assert L.config_hash() == CONFIG_HASH


# ---------------------------------------------------------------------------
# deterministic, past-only resample
# ---------------------------------------------------------------------------


def test_resample_emits_complete_buckets_and_drops_trailing() -> None:
    bars = synth(48, tf_min=5.0)  # 8 complete 30m buckets (per = 6)
    out = L.resample(bars, 30)
    assert len(out) == 7  # the trailing complete bucket is never emitted
    assert out.ts[0] == bars.ts[0]  # label = first source bar
    assert out.o[0] == bars.o[0]
    assert out.h[0] == bars.h[:6].max()
    assert out.lo[0] == bars.lo[:6].min()
    assert out.c[0] == bars.c[5]
    assert out.v[0] == bars.v[:6].sum()
    assert out.ts[1] - out.ts[0] == 30 * 60_000


def test_resample_is_prefix_invariant() -> None:
    """A truncated history resamples to exactly the same prefix: no future leak."""
    bars = synth(48, tf_min=5.0)
    full = L.resample(bars, 30)
    pref = L.resample(_prefix(bars, 30), 30)
    assert len(pref) == 4  # 30 bars = 5 buckets; the last is never emitted
    n = len(pref)
    assert np.array_equal(full.ts[:n], pref.ts)
    assert np.array_equal(full.o[:n], pref.o)
    assert np.array_equal(full.h[:n], pref.h)
    assert np.array_equal(full.lo[:n], pref.lo)
    assert np.array_equal(full.c[:n], pref.c)
    assert np.array_equal(full.v[:n], pref.v)


@needs_data
def test_resample_reproduces_certified_derived_files() -> None:
    files = L.dataset_files()
    base = [f for f in files if f.timeframe == "5m"]
    assert base
    f = base[0]
    bars = L.load_bars(f.path)
    for tf in ("15m", "30m", "1h"):
        out = L.resample(bars, int(L.TF_MIN[tf]))
        stored = next(
            x for x in files if x.asset == f.asset and x.window == f.window and x.timeframe == tf
        )
        ref = L.load_bars(stored.path)
        assert np.array_equal(out.ts, ref.ts)
        assert np.allclose(out.o, ref.o)
        assert np.allclose(out.h, ref.h)
        assert np.allclose(out.lo, ref.lo)
        assert np.allclose(out.c, ref.c)
        assert np.allclose(out.v, ref.v)


# ---------------------------------------------------------------------------
# split / holdout isolation
# ---------------------------------------------------------------------------


def test_splits_are_disjoint_and_holdout_is_separate() -> None:
    assert L.SPLITS["DISCOVERY"] == ("W1", "W2", "W3", "W4")
    assert L.SPLITS["VALIDATION"] == ("W5",)
    assert L.SPLITS["HOLDOUT"] == ("W6", "W7")
    seen = [w for ws in L.SPLITS.values() for w in ws]
    assert len(seen) == len(set(seen)) == 7
    holdout = set(L.SPLITS["HOLDOUT"])
    for split in ("DISCOVERY", "VALIDATION"):
        assert holdout.isdisjoint(L.SPLITS[split])


@needs_data
def test_certified_split_hashes_are_stable() -> None:
    got = L.split_hashes()
    for split, sha in SPLIT_SHA.items():
        assert got[split]["sha256"] == sha
    assert got["DISCOVERY"]["files"] == 48
    assert got["VALIDATION"]["files"] == 12
    assert got["HOLDOUT"]["files"] == 24


# ---------------------------------------------------------------------------
# event engine: entry, accounting, exit priority
# ---------------------------------------------------------------------------


def test_entry_is_next_bar_open_no_lookahead() -> None:
    bars = synth(400)
    bundle = L.build_bundle(bars, "30m")
    trades = L.run_spec(_spec(_spike(300)), bundle, "X", "W1")
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_ts == bars.ts[301]
    assert t.entry == bars.o[301]
    assert t.entry_ts > bars.ts[300]  # never the signal bar itself


def test_net_equals_gross_minus_certified_cost() -> None:
    bars = synth(400)
    bundle = L.build_bundle(bars, "30m")
    trades = L.run_spec(_spec(_spike(300)), bundle, "X", "W1")
    assert trades
    for t in trades:
        assert t.cost_bps == L.CERTIFIED_ROUND_TRIP_BPS
        assert t.net_bps == pytest.approx(t.gross_bps - t.cost_bps)


def test_stop_takes_priority_over_target() -> None:
    bars = synth(400)
    bundle = L.build_bundle(bars, "30m")
    trades = L.run_spec(_spec(_spike(300), tgt=0.0, stop=0.0), bundle, "X", "W1")
    assert len(trades) == 1
    assert trades[0].reason == "stop"


def test_time_stop_exits_at_open_after_hold_bars() -> None:
    bars = synth(400)
    bundle = L.build_bundle(bars, "30m")
    trades = L.run_spec(_spec(_spike(300), tgt=1000.0, stop=1000.0, hold=20), bundle, "X", "W1")
    assert len(trades) == 1
    t = trades[0]
    assert t.reason == "time_stop"
    assert t.hold_bars == 20
    assert t.exit == bars.o[301 + 20]
    assert t.exit_ts == bars.ts[301 + 20]


def test_slippage_stress_scales_only_slippage_component() -> None:
    bars = synth(400)
    bundle = L.build_bundle(bars, "30m")
    spec = _spec(_spike(300))
    base = L.run_spec(spec, bundle, "X", "W1")
    doubled = L.run_spec(spec, bundle, "X", "W1", slip_mult=2.0)
    assert len(base) == len(doubled) == 1
    assert base[0].gross_bps == doubled[0].gross_bps
    assert doubled[0].cost_bps - base[0].cost_bps == pytest.approx(L.SLIPPAGE_COMPONENT_BPS)


def test_run_spec_is_deterministic() -> None:
    bars = synth(400)
    bundle = L.build_bundle(bars, "30m")
    spec = _spec(_spike(300))
    a = L.run_spec(spec, bundle, "X", "W1")
    b = L.run_spec(spec, bundle, "X", "W1")
    assert [t.entry_ts for t in a] == [t.entry_ts for t in b]
    assert [t.net_bps for t in a] == [t.net_bps for t in b]


# ---------------------------------------------------------------------------
# lead/lag: strictly past leader information
# ---------------------------------------------------------------------------


def test_lead_lag_uses_past_leader_bar_only() -> None:
    bars = synth(120, tf_min=30.0)
    bundle = L.build_bundle(bars, "30m")
    sig = S.sig_lead_lag(bundle, bundle, lag_bars=1)
    for i in range(2, len(bars)):
        r = float(bundle.ret1[i - 1])
        if not np.isfinite(r) or r == 0.0:
            continue
        assert sig[i] == (1.0 if r > 0 else -1.0)
    assert sig.any()


def test_lead_lag_rejects_future_leader_bar() -> None:
    """A leader whose bars all sit *after* the follower must emit nothing."""
    bars = synth(60, tf_min=30.0)
    future = L.Bars(
        ts=bars.ts + 1000 * 30 * 60_000,
        o=bars.o,
        h=bars.h,
        lo=bars.lo,
        c=bars.c,
        v=bars.v,
    )
    leader = L.build_bundle(future, "30m")
    follower = L.build_bundle(bars, "30m")
    sig = S.sig_lead_lag(leader, follower, lag_bars=1)
    assert not sig.any()
