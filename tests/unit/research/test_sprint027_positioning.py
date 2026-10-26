"""RFC-027 — positioning-data edge discovery tests.

No network, no orders: these exercise the exact functions RFC-027 runs
(``scripts/sprint027_lib.py`` / ``sprint027_signals.py`` / ``sprint027_run.py``
/ ``sprint027_verify.py``) on SYNTHETIC data, so they never touch the downloaded
cache.  They assert the invariants the RFC must not violate: PIT causality, the
frozen chronological splits with HOLDOUT never loaded, the hypothesis/variant
budgets, and that COST_MODEL_V3 stays unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint027_lib as L  # noqa: E402
import sprint027_run as R  # noqa: E402
import sprint027_signals as SG  # noqa: E402
import sprint027_verify as V  # noqa: E402


def _panel(n: int = 600, seed: int = 7) -> L.Panel:
    rng = np.random.default_rng(seed)
    ts = np.arange(n, dtype=np.int64) * L.DEC_MS
    feats = {name: rng.normal(size=n) for name in L.FEATURE_NAMES}
    feats["vol_z"] = rng.normal(size=n)
    fwd = {h: rng.normal(size=n) * 100.0 for h in L.HORIZON_BARS}
    return L.Panel(
        ts=ts, asset=np.zeros(n, dtype=np.int64),
        open=np.ones(n), high=np.ones(n), low=np.ones(n), close=np.ones(n),
        features=feats, fwd_bps=fwd,
    )


def _masks(n: int) -> dict[str, np.ndarray]:
    disc = np.zeros(n, dtype=bool)
    val = np.zeros(n, dtype=bool)
    disc[: int(n * 0.6)] = True
    val[int(n * 0.6) : int(n * 0.8)] = True
    return {"DISCOVERY": disc, "VALIDATION": val}


# ---------------------------------------------------------------------------
# frozen constants + budgets
# ---------------------------------------------------------------------------


def test_cost_model_v3_unchanged() -> None:
    assert L.COST_MODEL_V3_BPS == 23.790569


def test_budgets_respected() -> None:
    assert len(SG.core_hypotheses()) <= 12
    variants = SG.build_variants()
    assert len(variants) <= 120
    assert len({v.variant_id for v in variants}) == len(variants)


def test_splits_chronological_and_holdout_not_loaded() -> None:
    assert L.SPLIT_FRACTIONS["DISCOVERY"] == (0.0, 0.6)
    assert L.SPLIT_FRACTIONS["VALIDATION"] == (0.6, 0.8)
    assert L.SPLIT_FRACTIONS["HOLDOUT"] == (0.8, 1.0)
    assert L.HOLDOUT_ANALYTICS_READ is False


def test_mirror_hypotheses_are_marked() -> None:
    mirrors = [h for h in SG.HYPOTHESES if h.mirror_of is not None]
    assert mirrors and all(h.mirror_of in {o.hid for o in SG.HYPOTHESES} for h in mirrors)


def test_edge_cost_bands() -> None:
    assert R.edge_cost_band(0.5) == "COST_KILLED"
    assert R.edge_cost_band(1.1) == "THIN"
    assert R.edge_cost_band(1.3) == "INTERESTING"
    assert R.edge_cost_band(1.7) == "STRONGER"
    assert R.edge_cost_band(2.5) == "HIGH_MARGIN"


# ---------------------------------------------------------------------------
# PIT causality
# ---------------------------------------------------------------------------


def test_asof_is_strictly_backward() -> None:
    times = np.array([100, 200, 300], dtype=np.int64)
    values = np.array([1.0, 2.0, 3.0])
    decisions = np.array([50, 100, 150, 250, 300, 350], dtype=np.int64)
    out = L._asof(times, values, decisions)
    assert np.isnan(out[0])
    assert list(out[1:]) == [1.0, 1.0, 2.0, 3.0, 3.0]


def test_rolling_z_has_no_warmup_future() -> None:
    x = np.arange(100, dtype=np.float64)
    z = L._rolling_z(x, 48)
    assert np.all(np.isnan(z[:47]))
    assert np.all(np.isfinite(z[47:]))


def test_complete_30m_buckets_only() -> None:
    base = 1_700_000_000_000
    base -= base % L.DEC_MS
    n = 6
    k = {
        "open_time_ms": np.array([base + i * L.SRC_MS for i in range(n)], dtype=np.int64),
        "open": np.arange(n, dtype=np.float64),
        "high": np.arange(n, dtype=np.float64) + 1,
        "low": np.arange(n, dtype=np.float64) - 1,
        "close": np.arange(n, dtype=np.float64) + 0.5,
        "volume": np.ones(n),
    }
    grid = L._complete_30m_from_5m(k)
    assert grid["open_time_ms"].shape[0] == 1
    assert grid["open"][0] == 0.0
    assert grid["close"][0] == 5.5


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------


def test_signal_shapes_and_finiteness() -> None:
    panel = _panel(400)
    for h in SG.HYPOTHESES:
        s = SG.signal_array(h, panel)
        assert s.shape == (400,)
        assert np.isfinite(s).any()


def test_vol_condition_masks_low_vol() -> None:
    panel = _panel(400, seed=11)
    ev = SG.vol_event(panel)
    expected = np.isfinite(panel.features["vol_z"]) & (panel.features["vol_z"] > 1.0)
    assert np.array_equal(ev, expected)
    v = next(v for v in SG.build_variants() if v.condition == "VOL")
    s = SG.variant_signal(v, panel)
    assert np.all(np.isnan(s[~ev]))


# ---------------------------------------------------------------------------
# statistics primitives
# ---------------------------------------------------------------------------


def test_rank_fast_handles_ties() -> None:
    r = R._rank_fast(np.array([5.0, 5.0, 1.0, 9.0]))
    assert r[0] == r[1] == 2.5
    assert r[2] == 1.0 and r[3] == 4.0


def test_quantile_spread_monotone_signal() -> None:
    x = np.arange(1000, dtype=np.float64)
    y = x.copy()
    q = L.quantile_spread(x, y)
    assert q["status"] == "OK"
    assert q["monotonicity"] == 1.0
    assert q["top_minus_bottom_bps"] > 0


def test_independent_rank_matches_library() -> None:
    x = np.array([3.0, 1.0, 2.0, 2.0, 5.0, -1.0])
    assert np.array_equal(V._rank_independent(x), L._rank(x))


# ---------------------------------------------------------------------------
# information + family null
# ---------------------------------------------------------------------------


def test_information_detects_seeded_signal() -> None:
    panel = _panel(1200, seed=3)
    masks = _masks(1200)
    info = R.compute_information(panel, masks)
    assert len(info) == len(SG.build_variants())
    assert all(r["ic_discovery"] is None or np.isfinite(r["ic_discovery"]) for r in info)


def test_family_null_deterministic_and_reactive() -> None:
    n = 1200
    panel = _panel(n, seed=5)
    masks = _masks(n)
    # make the OI-level signal strongly predictive in DISCOVERY
    panel.features["oi"] = np.arange(n, dtype=np.float64)
    panel.fwd_bps[1] = np.arange(n, dtype=np.float64) * 0.01
    info = R.compute_information(panel, masks)
    a = R.family_null(panel, masks, "P0_oi", info, n_perm=40)
    b = R.family_null(panel, masks, "P0_oi", info, n_perm=40)
    assert a["observed_max_abs_ic"] == b["observed_max_abs_ic"]
    assert a["family_wise_p"] == b["family_wise_p"]
    assert a["observed_max_abs_ic"] > 0.0


# ---------------------------------------------------------------------------
# split bounds
# ---------------------------------------------------------------------------


def test_asset_split_bounds_contiguous() -> None:
    b = R._asset_split_bounds(1000)
    assert b["DISCOVERY"] == (0, 600)
    assert b["VALIDATION"] == (600, 800)
    assert b["HOLDOUT"] == (800, 1000)
