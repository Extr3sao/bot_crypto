"""RFC-024 — statistics, PIT and isolation tests for directional discovery.

TEST_TARGET == RUNTIME_TARGET: these call the exact functions the RFC-024
analysis driver runs (``scripts/sprint024_lib.py`` / ``sprint024_signals.py``).
The holdout (W6-W7) must never be reachable.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_signals as S  # noqa: E402
import sprint024_lib as R  # noqa: E402
import sprint024_signals as D  # noqa: E402

FROZEN_REGISTRY_HASH = "3dcfab2b2a851afdd919b72c1926e6098b3a5e15e9bce1946c11a4175217b5fa"


# ---------------------------------------------------------------------------
# registry freeze + budget
# ---------------------------------------------------------------------------


def test_registry_frozen_hash_and_count() -> None:
    assert R.REGISTRY_HASH == FROZEN_REGISTRY_HASH
    assert len(R.REGISTRY) == 6
    ids = [h["hypothesis_id"] for h in R.REGISTRY]
    assert len(set(ids)) == 6


def test_registry_within_hypothesis_budget() -> None:
    assert 4 <= len(R.REGISTRY) <= 8
    assert len({h["family"] for h in R.REGISTRY}) >= 4


def test_registry_has_no_parameter_grid() -> None:
    for h in R.REGISTRY:
        assert isinstance(h["timeframe"], str)
        assert set(h["exit_horizon"]) == {"target_mult", "target_is_atr", "stop_mult", "hold_bars"}


def test_exit_is_shared_single_constant() -> None:
    for h in R.REGISTRY:
        assert R.hyp_exit(h) == R.hyp_exit(R.REGISTRY[0])


# ---------------------------------------------------------------------------
# multiple-testing correction
# ---------------------------------------------------------------------------


def test_multiple_testing_no_pass_when_all_adverse() -> None:
    rows = [(f"H{i}", -3.0, 100) for i in range(6)]
    mt = R.multiple_testing(rows)
    assert mt["n_raw_p_lt_005"] == 0
    assert mt["n_bh_pass"] == 0 and mt["n_holm_pass"] == 0


def test_multiple_testing_detects_strong_signal() -> None:
    rows = [("A", 6.0, 200)] + [(f"H{i}", -2.0, 200) for i in range(5)]
    mt = R.multiple_testing(rows)
    assert mt["n_raw_p_lt_005"] == 1
    assert "A" in mt["bh_pass"] and "A" in mt["holm_pass"]


def test_multiple_testing_requires_min_trades() -> None:
    mt = R.multiple_testing([("A", 6.0, 10)])
    assert mt["n_tested"] == 0


def test_raw_p_matches_normal_sf() -> None:
    mt = R.multiple_testing([("A", 1.959964, 100)])
    assert mt["raw_p"]["A"] == pytest.approx(0.025, abs=1e-4)


# ---------------------------------------------------------------------------
# best-of-N null
# ---------------------------------------------------------------------------


def test_permute_preserves_count_and_multiset() -> None:
    sig = np.array([0, 1, -1, 0, 1, 0, 0, -1], dtype=np.int8)
    rng = np.random.default_rng(0)
    out = R._permute_sig(sig, rng)
    assert list(np.sort(out)) == list(np.sort(sig))
    assert int(np.count_nonzero(out)) == int(np.count_nonzero(sig))
    assert out.dtype == sig.dtype


def test_p_best_ge_observed_wilson() -> None:
    draws = [{"best_net_bps": v} for v in (0.0, 5.0, 5.0, 10.0, 20.0)]
    res = R.p_best_ge_observed(draws, 6.0)
    assert res["n_ge_observed"] == 2
    assert res["p_value"] == pytest.approx(0.4)
    lo, hi = res["p_ci95_wilson"]
    assert 0.0 <= lo <= 0.4 <= hi <= 1.0


def test_summarise_null_reports_hypothesis_count() -> None:
    draws = [{"best_net_bps": float(i), "best_hypothesis_index": 0, "best_hypothesis_id": "H-DIR-01", "n_valid": 6} for i in range(1, 51)]
    s = R.summarise_null(draws)
    assert s["n_hypotheses"] == len(R.REGISTRY)
    assert s["max_best_net_bps"] == 50.0


# ---------------------------------------------------------------------------
# power / MDE
# ---------------------------------------------------------------------------


def test_mde_monotone_in_n() -> None:
    assert R.mde(100.0, 20) > R.mde(100.0, 100) > R.mde(100.0, 400)


def test_mde_matches_formula() -> None:
    factor = R.G.z_two_sided(0.95) + R.G.z_power(0.80)
    assert R.mde(117.0, 100) == pytest.approx(factor * 117.0 / math.sqrt(100), abs=1e-6)


def test_power_row_flags_underpowered_for_small_n() -> None:
    h = R.REGISTRY[0]
    disc = [L.Trade("c", h["hypothesis_id"], h["family"], "X", "W1", h["timeframe"], "LONG",
                    0.0, 1.0, 100.0, 101.0, "target", 1, 30.0, 23.79, 6.2, 0.0, 0.0, 0.0)
            for _ in range(150)]
    val = disc[:15]
    row = R.power_row(h, disc, val)
    assert row["verdict"] == "UNDERPOWERED"


# ---------------------------------------------------------------------------
# directional classification
# ---------------------------------------------------------------------------


def _info(ci_low: float) -> dict[str, Any]:
    return {"horizons": {"30m": {"status": "OK", "mean_signed_ci95": [ci_low, ci_low + 5.0]}}}


def test_directional_class_positive_ci_is_directional() -> None:
    assert R.directional_class(_info(1.0)) == "DIRECTIONAL_ALPHA"


def test_directional_class_none_when_ci_spans_zero() -> None:
    assert R.directional_class(_info(-3.0)) == "NO_DIRECTIONAL_INFORMATION"


# ---------------------------------------------------------------------------
# signals: reuse frozen shock, PIT safety, value set
# ---------------------------------------------------------------------------


def test_shock_event_is_the_frozen_detector() -> None:
    _a, _w, b = R.G.split_bundles("DISCOVERY", "30m")[0]
    assert np.array_equal(D.shock_event(b), np.asarray(S._vol_shock(b), dtype=bool))


def test_signal_values_are_in_int8_set() -> None:
    for h in R.REGISTRY:
        if h["kind"] != "single":
            continue
        _a, _w, b = R.G.split_bundles("DISCOVERY", h["timeframe"])[0]
        sig = D.SIG_FN[h["signal"]](b)
        assert sig.dtype == np.int8
        assert set(np.unique(sig).tolist()) <= {-1, 0, 1}


def _truncate(bars: L.Bars, n: int) -> L.Bars:
    return L.Bars(ts=bars.ts[:n], o=bars.o[:n], h=bars.h[:n], lo=bars.lo[:n], c=bars.c[:n], v=bars.v[:n])


@pytest.mark.parametrize("sig_name", ["shock_trend_continuation", "shock_confirm_followthrough", "shock_range_location"])
def test_signals_are_point_in_time(sig_name: str) -> None:
    f = next(x for x in L.dataset_files() if x.asset == "BTCUSDT" and x.window == "W1" and x.timeframe == "30m")
    bars = L.load_bars(f.path)
    full = L.build_bundle(bars, "30m")
    n = 500
    trunc = L.build_bundle(_truncate(bars, n), "30m")
    fn = D.SIG_FN[sig_name]
    assert np.array_equal(np.asarray(fn(trunc)), np.asarray(fn(full))[:n])


def test_forward_from_entry_is_nan_near_end() -> None:
    _a, _w, b = R.G.split_bundles("DISCOVERY", "30m")[0]
    fwd = R._forward_from_entry(b, 4)
    assert np.isnan(fwd[-1])
    assert np.isfinite(fwd[100])


# ---------------------------------------------------------------------------
# holdout isolation + cost invariance + determinism
# ---------------------------------------------------------------------------


def test_holdout_is_disjoint_from_used_splits() -> None:
    assert L.SPLITS["HOLDOUT"] == ("W6", "W7")
    used = set(L.SPLITS["DISCOVERY"]) | set(L.SPLITS["VALIDATION"])
    assert used == {"W1", "W2", "W3", "W4", "W5"}
    assert used.isdisjoint(L.SPLITS["HOLDOUT"])


def test_run_hypothesis_refuses_holdout() -> None:
    with pytest.raises(ValueError):
        R.run_hypothesis(R.REGISTRY[0], "HOLDOUT")


def test_cost_is_frozen() -> None:
    assert R.COST == 23.790569
    assert R.COST == L.CERTIFIED_ROUND_TRIP_BPS


def test_run_hypothesis_is_deterministic() -> None:
    h = R.REGISTRY[0]
    a, _ = R.run_hypothesis(h, "DISCOVERY")
    b, _ = R.run_hypothesis(h, "DISCOVERY")
    assert [t.net_bps for t in a] == [t.net_bps for t in b]
    assert [t.entry_ts for t in a] == [t.entry_ts for t in b]


def test_seed_and_null_target_are_frozen() -> None:
    assert R.SEED == 20261024
    assert R.N_NULL_TARGET >= 1000
