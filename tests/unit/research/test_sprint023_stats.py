"""RFC-023 — statistics and isolation tests for the generalization diagnosis.

TEST_TARGET == RUNTIME_TARGET: these call the exact functions the RFC-023
analysis driver runs (``scripts/sprint023_lib.py``). The holdout (W6-W7) must
never be reachable from the diagnosis splits.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint023_lib as G  # noqa: E402

# ---------------------------------------------------------------------------
# rank / correlation
# ---------------------------------------------------------------------------


def test_rankdata_averages_ties() -> None:
    r = G.rankdata(np.array([3.0, 1.0, 1.0, 2.0]))
    assert list(r) == [4.0, 1.5, 1.5, 3.0]


def test_spearman_matches_pearson_on_ranks() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    y = np.array([2.0, 1.0, 4.0, 3.0, 6.0, 5.0])
    ic = G.spearman_ic(x, y)
    assert ic is not None
    assert ic == pytest.approx(0.828571, abs=1e-5)


def test_pearson_none_on_constant() -> None:
    assert G.pearson(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0])) is None


# ---------------------------------------------------------------------------
# robust statistics
# ---------------------------------------------------------------------------


def test_trimmed_and_winsorized_reduce_outlier_pull() -> None:
    x = np.array([-100.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 1000.0])
    assert G.trimmed_mean(x, 0.10) == pytest.approx(4.5, abs=0.6)
    w = G.winsorized_mean(x, 0.20)
    assert w == pytest.approx(4.5, abs=0.6)


def test_mde_is_monotone_and_matches_formula() -> None:
    sigma = 100.0
    table = G.mde_table(sigma, ns=(25, 100, 400))
    assert table["25"] > table["100"] > table["400"]
    factor = G.z_two_sided(0.95) + G.z_power(0.80)
    assert table["100"] == pytest.approx(factor * sigma / 10.0, abs=1e-3)


def test_required_n_scales_inversely_with_edge() -> None:
    rn = G.required_n(100.0)
    assert rn["5bps"] > rn["10bps"] > rn["20bps"]


# ---------------------------------------------------------------------------
# permutation null
# ---------------------------------------------------------------------------


def test_permute_signal_preserves_count_and_multiset() -> None:
    sig = np.array([0, 1, -1, 0, 1, 0, 0, -1], dtype=np.int8)
    rng = np.random.default_rng(0)
    out = G._permute_signal(sig, rng)
    assert list(np.sort(out)) == list(np.sort(sig))
    assert int(np.count_nonzero(out)) == int(np.count_nonzero(sig))
    assert out.dtype == sig.dtype


def test_p_best_ge_observed_wilson_bounds() -> None:
    draws = [{"best_net_bps": v} for v in (0.0, 5.0, 5.0, 10.0, 20.0)]
    res = G.p_best_ge_observed(draws, 6.0)
    assert res["n_ge_observed"] == 2
    assert res["p_value"] == pytest.approx(0.4)
    lo, hi = res["p_ci95_wilson"]
    assert 0.0 <= lo <= 0.4 <= hi <= 1.0


def test_summarise_null_percentiles() -> None:
    draws = [
        {"best_net_bps": float(i), "best_sharpe": 0.0, "best_pnl_usdt": 0.0, "n_valid": 80}
        for i in range(1, 101)
    ]
    s = G.summarise_null(draws)
    assert s["n_draws"] == 100
    assert s["median_best_net_bps"] == pytest.approx(50.5, abs=1.0)
    assert s["max_best_net_bps"] == 100.0


# ---------------------------------------------------------------------------
# direction vs magnitude classifier
# ---------------------------------------------------------------------------


def _info(hit: float, ci_low: float, lift: float) -> dict[str, Any]:
    return {
        "horizons": {
            "1h": {
                "status": "OK",
                "direction_hit_rate": hit,
                "hit_rate_ci95": [ci_low, min(1.0, ci_low + 0.1)],
                "abs_move_lift": lift,
            }
        }
    }


def test_classify_direction_magnitude_cells() -> None:
    assert G.classify_direction_magnitude(_info(0.60, 0.55, 1.30)) == "BOTH"
    assert G.classify_direction_magnitude(_info(0.60, 0.55, 1.02)) == "DIRECTIONAL_ALPHA"
    assert G.classify_direction_magnitude(_info(0.50, 0.45, 1.40)) == "VOLATILITY_ALPHA_ONLY"
    assert G.classify_direction_magnitude(_info(0.50, 0.45, 1.02)) == "NO_INFORMATION"


# ---------------------------------------------------------------------------
# trade concentration on synthetic trades
# ---------------------------------------------------------------------------


def _trade(net: float) -> L.Trade:
    return L.Trade(
        candidate_id="T",
        hypothesis_id="H",
        family="f",
        asset="X",
        window="W1",
        timeframe="30m",
        side="LONG",
        entry_ts=0.0,
        exit_ts=1.0,
        entry=100.0,
        exit=101.0,
        reason="target",
        hold_bars=1,
        gross_bps=net + 20.0,
        cost_bps=20.0,
        net_bps=net,
        mfe_bps=0.0,
        mae_bps=0.0,
        atr_bps_at_entry=0.0,
    )


def test_concentration_detects_single_trade_dependency() -> None:
    c = G.concentration([_trade(100.0)] + [_trade(-10.0)] * 9)
    assert c["pct_top1"] == pytest.approx(100.0 / 10.0, abs=1e-3)
    assert c["net_bps_ex_best"] < 0
    assert c["verdict"] == "SINGLE_TRADE_DEPENDENCY"


def test_concentration_diversified_edge() -> None:
    c = G.concentration([_trade(10.0)] * 10)
    assert c["verdict"] == "DIVERSIFIED_EDGE"


def test_outlier_influence_flags_tail_dependence() -> None:
    o = G.outlier_influence([_trade(500.0)] + [_trade(-10.0)] * 20)
    assert o["tail_dependent"] is True
    assert o["median_bps"] < 0 < o["mean_bps"]


# ---------------------------------------------------------------------------
# holdout isolation
# ---------------------------------------------------------------------------


def test_holdout_is_disjoint_from_diagnosis_splits() -> None:
    assert L.SPLITS["HOLDOUT"] == ("W6", "W7")
    diagnosis = set(L.SPLITS["DISCOVERY"]) | set(L.SPLITS["VALIDATION"])
    assert diagnosis == {"W1", "W2", "W3", "W4", "W5"}
    assert diagnosis.isdisjoint(L.SPLITS["HOLDOUT"])


def test_horizons_and_seeds_are_frozen() -> None:
    assert G.HORIZONS == (1, 2, 4, 8, 16)
    assert G.N_PERM == 200
    assert G.SEED == 20261023
    assert G.COST == 23.790569
