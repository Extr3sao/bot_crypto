"""RFC-025 — orthogonal data, information and PIT tests.

TEST_TARGET == RUNTIME_TARGET: these call the exact functions RFC-025 runs
(``scripts/sprint025_lib.py`` / ``sprint025_signals.py``). No network. The
holdout (W6-W7) must never be reached.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_signals as S  # noqa: E402
import sprint025_lib as OL  # noqa: E402
import sprint025_signals as SG  # noqa: E402

# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def test_asof_backward_only() -> None:
    times = np.array([10, 20, 30], dtype=np.int64)
    vals = np.array([1.0, 2.0, 3.0])
    dec = np.array([5, 10, 15, 20, 35], dtype=np.int64)
    out = OL.asof(times, vals, dec)
    assert np.isnan(out[0])  # nothing known at t=5
    assert out[1] == 1.0
    assert out[2] == 1.0  # as-of, never the future value
    assert out[3] == 2.0
    assert out[4] == 3.0


def test_diff1_first_is_nan() -> None:
    d = OL.diff1(np.array([1.0, 3.0, 6.0]))
    assert np.isnan(d[0])
    assert d[1] == 2.0 and d[2] == 3.0


def test_rolling_z_trailing_no_lookahead() -> None:
    x = np.arange(1.0, 51.0)
    z = OL.rolling_z(x, 10)
    assert np.all(np.isnan(z[:9]))
    # z at i uses only x[i-9..i]
    manual = (x[20] - np.mean(x[11:21])) / np.std(x[11:21])
    assert abs(z[20] - manual) < 1e-9


def test_rolling_z_nan_becomes_nan_not_imputed() -> None:
    x = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    z = OL.rolling_z(x, 3)
    assert np.isnan(z[2])  # window contains a NaN -> NaN, not filled


def test_forward_return_bps_alignment() -> None:
    c = np.array([100.0, 110.0, 121.0])
    fr = OL.forward_return_bps(c, 1)
    assert abs(fr[0] - 1000.0) < 1e-6
    assert abs(fr[1] - 1000.0) < 1e-6
    assert np.isnan(fr[2])


def test_spearman_known_values() -> None:
    x = np.arange(50.0)
    ic_pos = OL.spearman_ic(x, x)
    ic_neg = OL.spearman_ic(x, -x)
    assert ic_pos is not None and abs(ic_pos - 1.0) < 1e-9
    assert ic_neg is not None and abs(ic_neg + 1.0) < 1e-9


def test_quantile_spread_monotone() -> None:
    x = np.arange(100.0)
    y = np.arange(100.0) * 2.0
    qs = OL.quantile_spread(x, y, 5)
    assert qs["status"] == "OK"
    assert qs["top_minus_bottom_bps"] > 0
    assert qs["monotonicity"] == 1.0


def test_mde_table_decreases_with_n() -> None:
    t = OL.mde_table(60.0)
    assert t["20"] > t["1000"]
    assert t["100"] > t["500"]


# ---------------------------------------------------------------------------
# signal direction + volatility conditioning
# ---------------------------------------------------------------------------


def _bundle(n: int) -> L.Bundle:
    bars = L.Bars(
        ts=np.arange(n, dtype=np.float64) * 300000.0,
        o=np.full(n, 100.0),
        h=np.full(n, 101.0),
        lo=np.full(n, 99.0),
        c=np.full(n, 100.0),
        v=np.ones(n),
    )
    return L.build_bundle(bars, "5m")


def test_signal_is_contrarian(monkeypatch) -> None:
    n = 300
    feat = np.zeros(n)
    feat[200] = 3.0  # high feature
    feat[201] = -3.0  # low feature
    shock = np.ones(n, dtype=bool)
    b = _bundle(n)
    monkeypatch.setattr(
        OL, "ortho_on_bundle", lambda asset, bundle, at="close": {"basis_z": feat}
    )
    monkeypatch.setattr(OL, "vol_shock_of", lambda bundle: shock)
    sig = SG.signal_array("BTCUSDT", b, "basis_z", 1.5, cond_vol=False)
    assert sig[200] == -1  # high -> short
    assert sig[201] == 1  # low -> long


def test_signal_vol_conditioning_mutes_non_shock(monkeypatch) -> None:
    n = 300
    feat = np.zeros(n)
    feat[200] = 3.0
    shock = np.zeros(n, dtype=bool)  # no vol event
    b = _bundle(n)
    monkeypatch.setattr(
        OL, "ortho_on_bundle", lambda asset, bundle, at="close": {"basis_z": feat}
    )
    monkeypatch.setattr(OL, "vol_shock_of", lambda bundle: shock)
    sig = SG.signal_array("BTCUSDT", b, "basis_z", 1.5, cond_vol=True)
    assert sig[200] == 0
    # without the condition it fires
    sig2 = SG.signal_array("BTCUSDT", b, "basis_z", 1.5, cond_vol=False)
    assert sig2[200] == -1


def test_signal_uses_certified_vol_detector() -> None:
    # vol_shock_of must delegate to sprint002_signals._vol_shock (never redefined)
    n = 400
    rng = np.random.default_rng(7)
    c = 100.0 * np.cumprod(1.0 + rng.normal(0, 0.002, n))
    bars = L.Bars(
        ts=np.arange(n, dtype=np.float64) * 300000.0,
        o=c, h=c * 1.001, lo=c * 0.999, c=c, v=np.ones(n),
    )
    b = L.build_bundle(bars, "5m")
    assert np.array_equal(OL.vol_shock_of(b), np.asarray(S._vol_shock(b)))


# ---------------------------------------------------------------------------
# cost + holdout guards
# ---------------------------------------------------------------------------


def test_cost_model_unchanged() -> None:
    assert L.CERTIFIED_ROUND_TRIP_BPS == 23.790569


def test_holdout_windows_are_w6_w7() -> None:
    assert L.SPLITS["HOLDOUT"] == ("W6", "W7")
    assert L.SPLITS["DISCOVERY"] == ("W1", "W2", "W3", "W4")
    assert L.SPLITS["VALIDATION"] == ("W5",)


def test_ortho_on_bundle_missing_stays_nan(monkeypatch) -> None:
    # grid has only ts=0 and 600000; the bundle has ts=0,300000,600000
    grid_ts = np.array([0, 600000], dtype=np.int64)
    feats = {"basis": np.array([1.0, 2.0])}
    monkeypatch.setattr(
        OL, "build_asset_grid", lambda asset: {"asset": asset, "ts": grid_ts, "features": feats}
    )
    bars = L.Bars(
        ts=np.array([0.0, 300000.0, 600000.0]),
        o=np.ones(3), h=np.ones(3), lo=np.ones(3), c=np.ones(3), v=np.ones(3),
    )
    b = L.build_bundle(bars, "5m")
    out = OL.ortho_on_bundle("BTCUSDT", b, at="open")
    assert np.isnan(out["basis"][1])  # no imputation
    assert out["basis"][0] == 1.0 and out["basis"][2] == 2.0
